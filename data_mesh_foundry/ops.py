"""Operate workspace API: run, monitor, support and optimize published data products."""
import datetime as dt
from collections import Counter, defaultdict, deque

from fastapi import APIRouter, Body, HTTPException, Request

from db import query, one, execute

router = APIRouter(prefix="/api/ops")
UTC = dt.timezone.utc
ENV_ORDER = ["DEV", "SIT", "UAT", "PROD"]
FREQ_MIN = {"15 Minutes": 15, "Hourly": 60, "Daily": 1440, "Weekly": 10080, "Event Driven": None}
BACKFILL_KINDS = ["Single Day Reload", "Historical Reload", "Partition Reload", "Full Product Refresh"]
INCIDENT_TYPES = ["Pipeline Failure", "Data Quality Issue", "Security Issue", "Access Issue", "Infrastructure Failure", "SLA Violation", "Contract Violation"]
ARTIFACT_STATES = ["Active", "Deprecated", "Archived", "Retired"]
ACCESS_STAGES = ["Request", "Steward Approval", "Security Approval", "Provision Access"]
ROLE_RANK = {"Reader": 1, "Contributor": 2, "Owner": 3}
COST_SPLIT = {"Compute": 0.58, "Pipeline": 0.25, "Storage": 0.17}  # platform spend allocation model


def user_of(request: Request) -> str:
    return request.headers.get("x-forwarded-email") or request.headers.get("x-forwarded-preferred-username") or "local.user@corp.com"


def event(env, kind, message, actor):
    execute("INSERT INTO mesh.events(env,kind,message,actor) VALUES (%s,%s,%s,%s)", (env, kind, message, actor))


def _now():
    return dt.datetime.now(UTC)


def _ts(v):
    if v is None:
        return None
    if not isinstance(v, dt.datetime):
        v = dt.datetime.fromisoformat(str(v))
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else 100.0


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _expected_min(sla):
    s = (sla or "").lower()
    return 15 if "real" in s else 60 if "hour" in s else 10080 if "week" in s else 1440


def _forecast(values):
    """Least-squares linear projection of the next point."""
    n = len(values)
    if n < 2:
        return values[-1] if values else 0
    mx, my = (n - 1) / 2, sum(values) / n
    slope = sum((x - mx) * (y - my) for x, y in enumerate(values)) / sum((x - mx) ** 2 for x in range(n))
    return max(0.0, my + slope * (n - mx))


# ---------------------------------------------------------------- shared state builders
PIPE_SQL = """SELECT pl.id, pl.name, pl.env, pl.engine, pl.status, pl.health, pl.last_run, pl.duration_min, pl.rows_per_hour,
                     pl.latency_min, pl.product_id, p.name AS product, p.sla, d.name AS domain, d.custodian AS team,
                     s.frequency, s.paused, s.next_run
              FROM mesh.pipelines pl JOIN mesh.products p ON p.id=pl.product_id JOIN mesh.domains d ON d.id=p.domain_id
              LEFT JOIN mesh.pipeline_schedules s ON s.pipeline_id=pl.id"""


def _pipelines(env=None):
    rows = query(PIPE_SQL + (" WHERE pl.env=%s" if env else "") + " ORDER BY d.name, p.name, pl.env", (env,) if env else None)
    now = _now()
    for r in rows:
        mins, last = FREQ_MIN.get(r["frequency"]), _ts(r["last_run"])
        state = "Succeeded" if r["status"] == "Completed" else r["status"]
        if state in ("Running", "Queued", "Succeeded") and not r["paused"] and mins and last and (now - last).total_seconds() / 60 > mins * 1.5:
            state = "Delayed"
        r["run_state"] = state
    return rows


def _runs(env):
    return query("""SELECT r.pipeline_id, r.started_at, r.duration_min, r.rows_processed, r.status FROM mesh.pipeline_runs r
                    JOIN mesh.pipelines pl ON pl.id=r.pipeline_id WHERE pl.env=%s""", (env,))


def _run_totals(runs):
    t = defaultdict(lambda: [0, 0])
    for r in runs:
        t[r["pipeline_id"]][0] += 1
        t[r["pipeline_id"]][1] += r["status"] == "Failed"
    return t


def _availability(env):
    prods = query("""SELECT p.id, p.name, p.sla, d.name AS domain, d.custodian AS team, ps.version, ps.quality_score, ps.freshness_min,
                            ps.consumers, ps.usage_30d
                     FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id
                     JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s ORDER BY d.name, p.name""", (env,))
    pls = {}
    for pl in query("SELECT id, product_id, status, health, latency_min FROM mesh.pipelines WHERE env=%s ORDER BY id", (env,)):
        pls.setdefault(pl["product_id"], pl)
    totals = _run_totals(_runs(env))
    now = _now()
    out = []
    for p in prods:
        pl = pls.get(p["id"], {})
        exp, fresh = _expected_min(p["sla"]), p["freshness_min"] or 0
        tot, failed = totals.get(pl.get("id"), (0, 0))
        avail = 100.0 - (30.0 * failed / tot if tot else 0) - (1.2 if pl.get("status") == "Failed" else 0)
        if pl.get("status") == "Failed" or fresh > 2 * exp:
            light, fstate, sla = "Red", "Breached", "Breached"
        elif fresh > exp or pl.get("health") == "Warning":
            light, fstate, sla = "Amber", "Delayed", "At Risk"
        else:
            light, fstate, sla = "Green", "On Time", "Healthy"
        last = now - dt.timedelta(minutes=fresh)
        out.append({**p, "env": env, "pipeline_id": pl.get("id"), "pipeline_status": pl.get("status"), "latency_min": pl.get("latency_min"),
                    "expected_min": exp, "last_refresh": last, "expected_refresh": last + dt.timedelta(minutes=exp),
                    "delay_min": max(0, round(fresh - exp)), "availability_pct": round(avail, 2), "light": light,
                    "freshness_state": fstate, "sla_status": sla, "run_total": tot, "run_failed": failed})
    return out


def _quotas():
    rows = query("SELECT q.*, d.name AS domain FROM mesh.quotas q JOIN mesh.domains d ON d.id=q.domain_id ORDER BY d.name, q.id")
    live = {
        "Storage": query("SELECT domain_id, sum(storage_tb) AS v FROM mesh.domain_states GROUP BY domain_id"),
        "Compute": query("SELECT domain_id, sum(compute_dbu) AS v FROM mesh.domain_states GROUP BY domain_id"),
        "Pipelines": query("SELECT p.domain_id, count(*) AS v FROM mesh.pipelines pl JOIN mesh.products p ON p.id=pl.product_id GROUP BY p.domain_id"),
        "Monthly Budget": query("""SELECT domain_id, sum(amount) AS v FROM mesh.cost_monthly
                                   WHERE month=(SELECT max(month) FROM mesh.cost_monthly) GROUP BY domain_id"""),
    }
    live = {k: {r["domain_id"]: float(r["v"] or 0) for r in v} for k, v in live.items()}
    for r in rows:
        if r["resource"] in live:
            r["used"] = round(live[r["resource"]].get(r["domain_id"], 0.0), 1)
        used, alloc = float(r["used"] or 0), float(r["allocated"] or 0)
        r["remaining"] = round(alloc - used, 1)
        r["pct"] = _pct(used, alloc) if alloc else 0
        r["status"] = "Critical" if r["pct"] >= 90 else "Warning" if r["pct"] >= 75 else "Healthy"
    return rows


def _impact(product_ids):
    edges = defaultdict(list)
    for e in query("SELECT src_product_id, dst_product_id FROM mesh.lineage"):
        edges[e["src_product_id"]].append(e["dst_product_id"])
    names = {p["id"]: p["name"] for p in query("SELECT id, name FROM mesh.products")}
    consumers = defaultdict(list)
    for c in query("SELECT * FROM mesh.consumers ORDER BY id"):
        consumers[c["product_id"]].append(c)
    out = []
    for pid in product_ids:
        seen, todo = set(), deque(edges[pid])
        while todo:
            x = todo.popleft()
            if x in seen or x == pid:
                continue
            seen.add(x)
            todo.extend(edges[x])
        cs = [c for a in [pid, *seen] for c in consumers[a]]
        out.append({"product_id": pid, "product": names.get(pid), "downstream": sorted(names[x] for x in seen),
                    "dashboards": [c["name"] for c in cs if c["kind"] == "Dashboard"], "apis": [c["name"] for c in cs if c["kind"] == "API"],
                    "teams": sorted({c["name"] for c in cs if c["kind"] == "Team"})})
    return out


# ---------------------------------------------------------------- operational dashboard
@router.get("/dashboard")
def dashboard(env: str = "PROD"):
    av, pls, quotas = _availability(env), _pipelines(env), _quotas()
    healthy = sum(1 for p in pls if p["health"] == "Healthy")
    return {
        "kpis": {"active_products": len(av), "healthy_pipelines_pct": _pct(healthy, len(pls)),
                 "open_incidents": one("SELECT count(*) AS n FROM mesh.incidents WHERE env=%s AND status<>'Resolved'", (env,))["n"],
                 "sla_compliance": _pct(sum(a["sla_status"] != "Breached" for a in av), len(av)),
                 "availability": _avg(a["availability_pct"] for a in av)},
        "pipeline_counts": Counter(p["run_state"] for p in pls),
        "availability": av,
        "cost_trend": query("SELECT month, sum(amount) AS amount FROM mesh.cost_monthly GROUP BY month ORDER BY month"),
        "budget": sum(q["allocated"] or 0 for q in quotas if q["resource"] == "Monthly Budget"),
        "access_requests": query("""SELECT a.*, w.stage FROM mesh.approvals a LEFT JOIN mesh.access_workflow w ON w.approval_id=a.id
                                    WHERE a.kind='Access' AND a.status='Pending' ORDER BY a.created_at DESC LIMIT 6"""),
        "deployments": query("SELECT * FROM mesh.deployments WHERE env=%s ORDER BY created_at DESC LIMIT 6", (env,)),
        "failed_jobs": [p for p in pls if p["status"] == "Failed"],
        "quota_alerts": [q for q in quotas if q["status"] != "Healthy"],
        "product_alerts": [a for a in av if a["light"] != "Green" or (a["quality_score"] or 100) < 85],
    }


# ---------------------------------------------------------------- pipeline operations
@router.get("/pipelines")
def pipeline_ops(env: str = "PROD"):
    runs = _runs(env)
    daily = defaultdict(lambda: {"succeeded": 0, "failed": 0, "duration": 0.0, "rows": 0, "n": 0})
    for r in runs:
        d = daily[_ts(r["started_at"]).date().isoformat()]
        d["n"] += 1
        d["failed" if r["status"] == "Failed" else "succeeded"] += 1
        d["duration"] += r["duration_min"] or 0
        d["rows"] += r["rows_processed"] or 0
    trend = [{"day": k, "succeeded": v["succeeded"], "failed": v["failed"], "rows": v["rows"],
              "avg_duration": round(v["duration"] / v["n"], 1)} for k, v in sorted(daily.items())]
    ok = sum(1 for r in runs if r["status"] != "Failed")
    backfills = query("""SELECT b.*, pl.name AS pipeline, pl.env FROM mesh.backfills b JOIN mesh.pipelines pl ON pl.id=b.pipeline_id
                         ORDER BY b.created_at DESC LIMIT 50""")
    return {"pipelines": _pipelines(), "trend": trend, "success_rate": _pct(ok, len(runs)),
            "avg_duration": _avg(r["duration_min"] for r in runs), "rows_processed": sum(r["rows_processed"] or 0 for r in runs),
            "backfills": backfills, "frequencies": list(FREQ_MIN), "backfill_kinds": BACKFILL_KINDS}


@router.post("/pipelines/{pid}/schedule")
def schedule(pid: int, request: Request, body: dict = Body(...)):
    pl = one("SELECT id, name, env FROM mesh.pipelines WHERE id=%s", (pid,))
    if not pl:
        raise HTTPException(404, "Pipeline not found")
    execute("INSERT INTO mesh.pipeline_schedules(pipeline_id,frequency,paused) VALUES (%s,'Daily',%s) ON CONFLICT (pipeline_id) DO NOTHING", (pid, False))
    action = body.get("action")
    if action == "pause":
        execute("UPDATE mesh.pipeline_schedules SET paused=%s, next_run=NULL, updated_at=now() WHERE pipeline_id=%s", (True, pid))
        msg = "paused"
    elif action in ("resume", "reschedule"):
        cur = one("SELECT frequency FROM mesh.pipeline_schedules WHERE pipeline_id=%s", (pid,))
        freq = body.get("frequency") or cur["frequency"]
        if freq not in FREQ_MIN:
            raise HTTPException(400, f"frequency must be one of {list(FREQ_MIN)}")
        mins = FREQ_MIN[freq]
        execute("UPDATE mesh.pipeline_schedules SET paused=%s, frequency=%s, next_run=%s, updated_at=now() WHERE pipeline_id=%s",
                (False, freq, _now() + dt.timedelta(minutes=mins) if mins else None, pid))
        msg = f"{action}d ({freq})"
    else:
        raise HTTPException(400, "action must be pause, resume or reschedule")
    event(pl["env"], "Pipeline", f"Schedule {msg}: {pl['name']}", user_of(request))
    return one("SELECT * FROM mesh.pipeline_schedules WHERE pipeline_id=%s", (pid,))


@router.post("/backfills")
def create_backfill(request: Request, body: dict = Body(...)):
    if body.get("kind") not in BACKFILL_KINDS:
        raise HTTPException(400, f"kind must be one of {BACKFILL_KINDS}")
    pl = one("SELECT id, name, env FROM mesh.pipelines WHERE id=%s", (body.get("pipeline_id"),))
    if not pl:
        raise HTTPException(404, "Pipeline not found")
    user = user_of(request)
    b = one("""INSERT INTO mesh.backfills(pipeline_id,kind,start_date,end_date,partition_key,status,requested_by)
               VALUES (%s,%s,%s,%s,%s,'Queued',%s) RETURNING *""",
            (pl["id"], body["kind"], body.get("start_date") or None, body.get("end_date") or None, body.get("partition_key") or None, user))
    event(pl["env"], "Pipeline", f"{body['kind']} queued for {pl['name']}", user)
    return b


# ---------------------------------------------------------------- data availability
@router.get("/availability")
def availability(env: str = "PROD"):
    av = _availability(env)
    by_domain = defaultdict(list)
    for a in av:
        by_domain[a["domain"]].append(a)
    report = [{"domain": k, "products": len(v), "availability": _avg(a["availability_pct"] for a in v),
               "on_time": sum(a["light"] == "Green" for a in v), "breaches": sum(a["sla_status"] == "Breached" for a in v)}
              for k, v in by_domain.items()]
    return {"products": av, "impact": _impact([a["id"] for a in av if a["light"] != "Green"]), "report": report}


# ---------------------------------------------------------------- access operations
@router.get("/access")
def access(env: str = "PROD"):
    now = _now()
    grants = query("""SELECT g.*, p.name AS product FROM mesh.access_grants g JOIN mesh.products p ON p.id=g.product_id
                      WHERE g.env=%s ORDER BY g.principal, p.name""", (env,))
    members = query("SELECT * FROM mesh.group_members ORDER BY group_name, principal")
    groups = query("SELECT * FROM mesh.user_groups ORDER BY name")
    for g in groups:
        g["member_list"] = [m["principal"] for m in members if m["group_name"] == g["name"]]
        g["grants"] = sum(1 for x in grants if x["principal"] == g["name"])
    requests = query("""SELECT a.*, w.stage FROM mesh.approvals a LEFT JOIN mesh.access_workflow w ON w.approval_id=a.id
                        WHERE a.kind='Access' ORDER BY a.created_at DESC""")
    for r in requests:
        expired = r["status"] == "Pending" and (now - _ts(r["created_at"])).total_seconds() > 72 * 3600
        r["state"] = "Expired" if expired else r["status"]
        r["stage"] = r["stage"] or ("Steward Approval" if r["status"] == "Pending" else "Provision Access" if r["status"] == "Approved" else "-")
    principals = {}
    for g in grants:
        principals.setdefault(g["principal"], g["principal_type"])
    for m in members:
        principals.setdefault(m["principal"], "User")
    dormant = [g for g in grants if g["principal_type"] != "Group"
               and (not g["last_access"] or (now - _ts(g["last_access"])).days > 90)]
    audit = query("SELECT * FROM mesh.access_audit WHERE env=%s ORDER BY created_at DESC LIMIT 150", (env,))
    return {"grants": grants, "groups": groups, "requests": requests, "stages": ACCESS_STAGES, "audit": audit, "dormant": dormant,
            "env_access": query("SELECT principal, env, count(*) AS n FROM mesh.access_grants GROUP BY principal, env"),
            "principals": [{"name": k, "type": v} for k, v in sorted(principals.items())]}


@router.get("/access/effective")
def effective(principal: str, env: str = "PROD"):
    groups = [m["group_name"] for m in query("SELECT group_name FROM mesh.group_members WHERE principal=%s", (principal,))]
    rows = query("""SELECT g.principal, g.principal_type, g.role, g.product_id, p.name AS product FROM mesh.access_grants g
                    JOIN mesh.products p ON p.id=g.product_id WHERE g.env=%s""", (env,))
    ptype = next((r["principal_type"] for r in rows if r["principal"] == principal), "Group" if one(
        "SELECT 1 AS x FROM mesh.user_groups WHERE name=%s", (principal,)) else "User")
    per = {}
    for r in rows:
        direct, via = r["principal"] == principal, r["principal"] in groups
        if not (direct or via):
            continue
        e = per.setdefault(r["product_id"], {"product": r["product"], "direct": None, "inherited": []})
        if direct:
            e["direct"] = max([e["direct"], r["role"]], key=lambda x: ROLE_RANK.get(x, 0))
        else:
            e["inherited"].append({"role": r["role"], "via": r["principal"]})
    for e in per.values():
        e["effective"] = max([e["direct"]] + [i["role"] for i in e["inherited"]], key=lambda x: ROLE_RANK.get(x, 0))
    return {"principal": principal, "type": ptype, "groups": groups, "permissions": sorted(per.values(), key=lambda x: x["product"])}


@router.post("/access/requests/{aid}/advance")
def advance_request(aid: int, request: Request):
    a = one("SELECT * FROM mesh.approvals WHERE id=%s AND kind='Access'", (aid,))
    if not a or a["status"] != "Pending":
        raise HTTPException(400, "Only pending access requests can be advanced")
    w = one("SELECT stage FROM mesh.access_workflow WHERE approval_id=%s", (aid,))
    nxt = ACCESS_STAGES[ACCESS_STAGES.index(w["stage"] if w else "Steward Approval") + 1]
    user = user_of(request)
    execute("""INSERT INTO mesh.access_workflow(approval_id,stage) VALUES (%s,%s)
               ON CONFLICT (approval_id) DO UPDATE SET stage=EXCLUDED.stage""", (aid, nxt))
    if nxt == "Provision Access":
        execute("UPDATE mesh.approvals SET status='Approved', decided_by=%s, decided_at=now() WHERE id=%s", (user, aid))
        if a["product_id"]:
            execute("INSERT INTO mesh.access_grants(principal,principal_type,product_id,env,role) VALUES (%s,'User',%s,%s,'Reader')",
                    (a["requester"], a["product_id"], a["env"]))
        execute("INSERT INTO mesh.access_audit(principal,action,object_name,env,detail) VALUES (%s,'GRANT',%s,%s,%s)",
                (a["requester"], a["object_name"], a["env"], f"Reader provisioned by {user}"))
    event(a["env"], "Approval", f"Access request #{aid} moved to {nxt}: {a['object_name']}", user)
    return {"id": aid, "stage": nxt}


@router.post("/access/grants/{gid}/revoke")
def revoke(gid: int, request: Request):
    g = one("SELECT g.*, p.name AS product FROM mesh.access_grants g JOIN mesh.products p ON p.id=g.product_id WHERE g.id=%s", (gid,))
    if not g:
        raise HTTPException(404, "Grant not found")
    user = user_of(request)
    execute("DELETE FROM mesh.access_grants WHERE id=%s", (gid,))
    execute("INSERT INTO mesh.access_audit(principal,action,object_name,env,detail) VALUES (%s,'REVOKE',%s,%s,%s)",
            (g["principal"], g["product"], g["env"], f"{g['role']} revoked by {user}"))
    event(g["env"], "Security", f"{g['role']} on {g['product']} revoked from {g['principal']}", user)
    return {"revoked": gid}


@router.post("/groups/{name}/members")
def group_member(name: str, request: Request, body: dict = Body(...)):
    principal = (body.get("principal") or "").strip()
    if not principal:
        raise HTTPException(400, "principal is required")
    if not one("SELECT 1 AS x FROM mesh.user_groups WHERE name=%s", (name,)):
        raise HTTPException(404, "Group not found")
    user = user_of(request)
    if body.get("remove"):
        execute("DELETE FROM mesh.group_members WHERE group_name=%s AND principal=%s", (name, principal))
        action = "removed from"
    else:
        execute("INSERT INTO mesh.group_members(group_name,principal) VALUES (%s,%s) ON CONFLICT DO NOTHING", (name, principal))
        action = "added to"
    execute("UPDATE mesh.user_groups SET members=(SELECT count(*) FROM mesh.group_members WHERE group_name=%s) WHERE name=%s", (name, name))
    execute("INSERT INTO mesh.access_audit(principal,action,object_name,env,detail) VALUES (%s,'ROLE_CHANGE',%s,'PROD',%s)",
            (principal, name, f"{action} group by {user}"))
    event("PROD", "Security", f"{principal} {action} {name}", user)
    return {"ok": True}


# ---------------------------------------------------------------- budget & quota management
PRODUCT_COST_SQL = """WITH dc AS (SELECT domain_id, amount FROM mesh.cost_monthly WHERE env=%(e)s AND month=(SELECT max(month) FROM mesh.cost_monthly WHERE env=%(e)s)),
                         pu AS (SELECT p.id, p.name, p.domain_id, ps.usage_30d, sum(ps.usage_30d) OVER (PARTITION BY p.domain_id) AS du
                                FROM mesh.products p JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%(e)s)
                      SELECT pu.name, dc.amount * pu.usage_30d / NULLIF(pu.du,0) AS amount
                      FROM pu JOIN dc ON dc.domain_id=pu.domain_id ORDER BY amount DESC"""


@router.get("/budget")
def budget(env: str = "PROD"):
    latest = one("SELECT max(month) AS m FROM mesh.cost_monthly")["m"]
    rows = query("""SELECT d.id, d.name, d.custodian AS team, c.env, c.amount FROM mesh.cost_monthly c
                    JOIN mesh.domains d ON d.id=c.domain_id WHERE c.month=%s""", (latest,))
    env_rows = [r for r in rows if r["env"] == env]
    total = sum(r["amount"] for r in env_rows)
    by_env = defaultdict(float)
    for r in rows:
        by_env[r["env"]] += r["amount"]
    quotas = _quotas()
    budgets = {q["domain_id"]: q["allocated"] or 0 for q in quotas if q["resource"] == "Monthly Budget"}
    chargeback = []
    for d in query("SELECT id, name, custodian FROM mesh.domains ORDER BY name"):
        spend = sum(r["amount"] for r in rows if r["id"] == d["id"])
        b = budgets.get(d["id"], 0)
        chargeback.append({"domain_id": d["id"], "domain": d["name"], "team": d["custodian"], "spend": round(spend), "budget": b, "variance": round(b - spend),
                           "share": _pct(spend, sum(by_env.values())),
                           **{k: round(sum(r["amount"] for r in rows if r["id"] == d["id"] and r["env"] == k)) for k in ENV_ORDER}})

    history = query("SELECT domain_id, month, sum(amount) AS amount FROM mesh.cost_monthly GROUP BY domain_id, month ORDER BY month")
    usage_hist = query("SELECT domain_id, month, sum(storage_tb) AS storage, sum(dbu) AS dbu FROM mesh.usage_monthly GROUP BY domain_id, month ORDER BY month")
    forecast = []
    for d in chargeback:
        did = d["domain_id"]
        spend = [h["amount"] for h in history if h["domain_id"] == did]
        st = [u["storage"] for u in usage_hist if u["domain_id"] == did]
        cp = [u["dbu"] for u in usage_hist if u["domain_id"] == did]
        nxt = _forecast(spend)
        ratio = nxt / d["budget"] if d["budget"] else 0
        forecast.append({"domain": d["domain"], "current": d["spend"], "forecast": round(nxt), "budget": d["budget"],
                         "storage_now": round(st[-1], 1) if st else 0, "storage_next": round(_forecast(st), 1),
                         "storage_growth_pct": _pct(st[-1] - st[0], st[0] * (len(st) - 1)) if len(st) > 1 and st[0] else 0,
                         "compute_now": round(cp[-1]) if cp else 0, "compute_next": round(_forecast(cp)),
                         "compute_growth_pct": _pct(cp[-1] - cp[0], cp[0] * (len(cp) - 1)) if len(cp) > 1 and cp[0] else 0,
                         "risk": "High" if ratio > 1 else "Medium" if ratio > 0.9 else "Low"})

    usage = query("""SELECT month, sum(dbu) AS dbu, sum(storage_tb) AS storage_tb, sum(api_calls) AS api_calls, sum(queries) AS queries
                     FROM mesh.usage_monthly WHERE env=%s GROUP BY month ORDER BY month""", (env,))
    usage_domain = query("""SELECT d.name AS domain, u.dbu, u.storage_tb, u.api_calls, u.queries FROM mesh.usage_monthly u
                            JOIN mesh.domains d ON d.id=u.domain_id WHERE u.env=%s AND u.month=(SELECT max(month) FROM mesh.usage_monthly)
                            ORDER BY u.dbu DESC""", (env,))
    workspaces = query("""SELECT e.code, e.name, e.workspace, sum(u.dbu) AS dbu, sum(u.storage_tb) AS storage_tb FROM mesh.environments e
                          LEFT JOIN mesh.usage_monthly u ON u.env=e.code AND u.month=(SELECT max(month) FROM mesh.usage_monthly)
                          GROUP BY e.code, e.name, e.workspace, e.tier ORDER BY e.tier""")

    recs = []
    for f in forecast:
        if f["risk"] != "Low":
            recs.append({"area": "Budget", "target": f["domain"], "text": f"Forecast ${f['forecast']:,} vs budget ${f['budget']:,.0f}: enable cluster auto-termination and right-size job clusters",
                         "saving": round(f["forecast"] * 0.08)})
    for q in quotas:
        if q["status"] != "Healthy" and q["resource"] in ("Storage", "Compute"):
            recs.append({"area": "Quota", "target": f"{q['domain']} {q['resource']}", "text": f"{q['pct']}% of quota used: archive cold partitions / apply VACUUM and lifecycle policies",
                         "saving": round((q["used"] or 0) * (23 if q["resource"] == "Storage" else 0.1))})
    nonprod = sum(v for k, v in by_env.items() if k != "PROD")
    if nonprod / max(1, sum(by_env.values())) > 0.25:
        recs.append({"area": "Environments", "target": "DEV / SIT / UAT", "text": f"Non-production is {_pct(nonprod, sum(by_env.values()))}% of spend: use smaller pools and schedules",
                     "saving": round(nonprod * 0.2)})
    failed = [p for p in _pipelines(env) if p["status"] == "Failed"]
    if failed:
        recs.append({"area": "Pipelines", "target": ", ".join(p["name"] for p in failed[:3]), "text": "Failed pipelines are consuming retry compute: fix root cause before re-running",
                     "saving": round(sum(p["duration_min"] or 0 for p in failed) * 12)})
    for p in query("""SELECT p.name, ps.usage_30d FROM mesh.products p JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env='PROD'
                      WHERE ps.usage_30d < 500 ORDER BY ps.usage_30d"""):
        recs.append({"area": "Products", "target": p["name"], "text": f"Only {p['usage_30d']} queries in 30 days: candidate for deprecation", "saving": 150})

    return {"month": latest, "total": round(total), "breakdown": {k: round(total * v) for k, v in COST_SPLIT.items()},
            "by_domain": sorted([{"name": r["name"], "amount": r["amount"]} for r in env_rows], key=lambda x: -x["amount"]),
            "by_team": sorted([{"name": r["team"], "amount": r["amount"]} for r in env_rows], key=lambda x: -x["amount"]),
            "by_env": [{"env": k, "amount": round(by_env.get(k, 0))} for k in ENV_ORDER],
            "by_product": [r for r in query(PRODUCT_COST_SQL, {"e": env}) if r["amount"] is not None][:12],
            "trend": query("SELECT month, sum(amount) AS amount FROM mesh.cost_monthly WHERE env=%s GROUP BY month ORDER BY month", (env,)),
            "domain_trend": query("""SELECT c.month, d.name, c.amount FROM mesh.cost_monthly c JOIN mesh.domains d ON d.id=c.domain_id
                                     WHERE c.env=%s ORDER BY c.month""", (env,)),
            "chargeback": chargeback, "usage": usage, "usage_domain": usage_domain, "workspaces": workspaces,
            "quotas": quotas, "forecast": forecast, "recommendations": recs, "split": COST_SPLIT}


@router.put("/quotas/{qid}")
def update_quota(qid: int, request: Request, body: dict = Body(...)):
    try:
        alloc = float(body["allocated"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "allocated must be a number")
    if alloc < 0:
        raise HTTPException(400, "allocated must be >= 0")
    q = one("""UPDATE mesh.quotas SET allocated=%s WHERE id=%s RETURNING *""", (alloc, qid))
    if not q:
        raise HTTPException(404, "Quota not found")
    event("PROD", "FinOps", f"Quota {q['resource']} for domain #{q['domain_id']} set to {alloc:g} {q['unit']}", user_of(request))
    return q


# ---------------------------------------------------------------- published artifact management
@router.get("/artifacts")
def artifacts(env: str = "PROD"):
    prods = query("""SELECT p.id, p.name, p.lifecycle, d.name AS domain, ps.version FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id
                     LEFT JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s ORDER BY p.name""", (env,))
    catalog = [{"type": "Data Product", "name": p["name"], "domain": p["domain"], "version": p["version"] or "-", "status": p["lifecycle"]} for p in prods if p["version"]]
    catalog += [{"type": "Pipeline", "name": p["name"], "domain": p["domain"], "version": p["engine"], "status": p["status"]} for p in _pipelines(env)]
    for c in query("""SELECT c.name, c.kind, c.version, c.status, d.name AS domain FROM mesh.contracts c JOIN mesh.products p ON p.id=c.product_id
                      JOIN mesh.domains d ON d.id=p.domain_id ORDER BY c.name"""):
        catalog.append({"type": "Schema" if c["kind"] == "Schema" else "Contract", "name": c["name"], "domain": c["domain"], "version": c["version"], "status": c["status"]})
    catalog += [{"type": "Policy", "name": p["name"], "domain": "Platform", "version": "-", "status": p["lifecycle"]} for p in query("SELECT * FROM mesh.policies ORDER BY name")]
    for c in query("""SELECT c.kind, c.name, d.name AS domain FROM mesh.consumers c JOIN mesh.products p ON p.id=c.product_id
                      JOIN mesh.domains d ON d.id=p.domain_id WHERE c.kind IN ('Dashboard','API') ORDER BY c.name"""):
        catalog.append({"type": c["kind"], "name": c["name"], "domain": c["domain"], "version": "-", "status": "Active"})
    retire_state = {"Published": "Active", "Deprecated": "Deprecated", "Archived": "Archived", "Retired": "Retired"}
    return {
        "catalog": catalog,
        "releases": query("SELECT * FROM mesh.deployments WHERE env=%s ORDER BY created_at DESC LIMIT 60", (env,)),
        "versions": query("SELECT * FROM mesh.artifact_versions ORDER BY name, released_at"),
        "current": {p["name"]: p["version"] for p in prods if p["version"]},
        "rollback": query("SELECT * FROM mesh.deployments WHERE env=%s AND status='Succeeded' ORDER BY created_at DESC LIMIT 40", (env,)),
        "retirement": [{**p, "artifact_state": retire_state.get(p["lifecycle"], "Pre-release")} for p in prods],
        "states": ARTIFACT_STATES,
    }


@router.post("/artifacts/{pid}/state")
def artifact_state(pid: int, request: Request, body: dict = Body(...)):
    state = body.get("state")
    if state not in ARTIFACT_STATES:
        raise HTTPException(400, f"state must be one of {ARTIFACT_STATES}")
    p = one("UPDATE mesh.products SET lifecycle=%s WHERE id=%s RETURNING *", ("Published" if state == "Active" else state, pid))
    if not p:
        raise HTTPException(404, "Product not found")
    event("PROD", "Governance", f"Artifact {p['name']} set to {state}", user_of(request))
    return p


# ---------------------------------------------------------------- monitoring & alerting
@router.get("/monitoring")
def monitoring(env: str = "PROD"):
    av, pls, quotas = _availability(env), _pipelines(env), _quotas()
    envrow = one("SELECT * FROM mesh.environments WHERE code=%s", (env,)) or {}
    healthy_pct = _pct(sum(p["health"] == "Healthy" for p in pls), len(pls))
    storage = [q for q in quotas if q["resource"] == "Storage"]
    worst = max(storage, key=lambda q: q["pct"]) if storage else None
    breached = [a["id"] for a in av if a["sla_status"] == "Breached"]
    apis = [c for c in query("SELECT * FROM mesh.consumers WHERE kind='API'") if c["product_id"] in breached]
    red = sum(a["light"] == "Red" for a in av)
    tiles = [
        {"name": "Platform Health", "status": envrow.get("health", "Healthy"), "metric": f"{envrow.get('workspace', '')} {envrow.get('status', '')}"},
        {"name": "Pipeline Health", "status": "Healthy" if healthy_pct >= 95 else "Warning" if healthy_pct >= 80 else "Error", "metric": f"{healthy_pct}% healthy"},
        {"name": "Storage Health", "status": {"Critical": "Error", "Warning": "Warning"}.get(worst["status"], "Healthy") if worst else "Healthy",
         "metric": f"peak {worst['pct']}% ({worst['domain']})" if worst else "-"},
        {"name": "API Health", "status": "Warning" if apis else "Healthy", "metric": f"{len(apis)} APIs on breached products"},
        {"name": "Product Health", "status": "Error" if red > 2 else "Warning" if red else "Healthy", "metric": f"{red} of {len(av)} products breached"},
    ]
    alerts = query("SELECT * FROM mesh.alerts WHERE env=%s ORDER BY CASE status WHEN 'Resolved' THEN 1 ELSE 0 END, created_at DESC", (env,))
    open_alerts = [a for a in alerts if a["status"] != "Resolved"]
    return {"tiles": tiles, "alerts": alerts, "severity": {s: sum(a["severity"] == s for a in open_alerts) for s in ["Critical", "Major", "Minor", "Information"]}}


@router.post("/alerts/{aid}/action")
def alert_action(aid: int, request: Request, body: dict = Body(...)):
    status = {"acknowledge": "Acknowledged", "resolve": "Resolved"}.get(body.get("action"))
    if not status:
        raise HTTPException(400, "action must be acknowledge or resolve")
    a = one("UPDATE mesh.alerts SET status=%s WHERE id=%s RETURNING *", (status, aid))
    if not a:
        raise HTTPException(404, "Alert not found")
    event(a["env"], "Alert", f"Alert {status.lower()}: {a['message']}", user_of(request))
    return a


# ---------------------------------------------------------------- incident management
@router.get("/incidents")
def incidents(env: str = "PROD"):
    rows = query("""SELECT i.*, p.name AS product, m.summary AS pm_summary, m.root_cause AS pm_root_cause, m.actions AS pm_actions, m.author AS pm_author
                    FROM mesh.incidents i LEFT JOIN mesh.products p ON p.id=i.product_id LEFT JOIN mesh.postmortems m ON m.incident_id=i.id
                    WHERE i.env=%s ORDER BY CASE i.status WHEN 'Resolved' THEN 1 ELSE 0 END, i.created_at DESC""", (env,))
    impact = {x["product_id"]: x for x in _impact({r["product_id"] for r in rows if r["product_id"]})}
    for r in rows:
        r["impact"] = impact.get(r["product_id"])
    return {"incidents": rows, "types": INCIDENT_TYPES, "products": query("SELECT id, name FROM mesh.products ORDER BY name")}


@router.post("/incidents")
def create_incident(request: Request, body: dict = Body(...)):
    if body.get("kind") not in INCIDENT_TYPES:
        raise HTTPException(400, f"kind must be one of {INCIDENT_TYPES}")
    if not (body.get("title") or "").strip():
        raise HTTPException(400, "title is required")
    if body.get("severity") not in ("Low", "Medium", "High", "Critical"):
        raise HTTPException(400, "severity must be Low, Medium, High or Critical")
    env = body.get("env", "PROD")
    i = one("""INSERT INTO mesh.incidents(kind,title,severity,status,owner,product_id,env) VALUES (%s,%s,%s,'Open',NULL,%s,%s) RETURNING *""",
            (body["kind"], body["title"].strip(), body["severity"], body.get("product_id") or None, env))
    event(env, "Incident", f"Incident opened: {i['title']}", user_of(request))
    return i


@router.post("/incidents/{iid}/postmortem")
def postmortem(iid: int, request: Request, body: dict = Body(...)):
    i = one("SELECT * FROM mesh.incidents WHERE id=%s", (iid,))
    if not i:
        raise HTTPException(404, "Incident not found")
    user = user_of(request)
    execute("""INSERT INTO mesh.postmortems(incident_id,summary,root_cause,actions,author) VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (incident_id) DO UPDATE SET summary=EXCLUDED.summary, root_cause=EXCLUDED.root_cause,
               actions=EXCLUDED.actions, author=EXCLUDED.author""",
            (iid, body.get("summary", ""), body.get("root_cause", ""), body.get("actions", ""), user))
    event(i["env"], "Incident", f"Post-mortem recorded for incident #{iid}", user)
    return {"ok": True}


# ---------------------------------------------------------------- environment operations
@router.get("/environments")
def environments():
    envs = query("SELECT * FROM mesh.environments ORDER BY tier")
    deps = query("SELECT env, status, count(*) AS n FROM mesh.deployments GROUP BY env, status")
    drift = query("SELECT * FROM mesh.state_objects WHERE status<>'Synced' ORDER BY env, object_type, name")
    for e in envs:
        e["deployments"] = {d["status"]: d["n"] for d in deps if d["env"] == e["code"]}
        e["drift"] = sum(1 for d in drift if d["env"] == e["code"])
        e["last_deployment"] = one("SELECT * FROM mesh.deployments WHERE env=%s ORDER BY created_at DESC LIMIT 1", (e["code"],))
    states = query("""SELECT p.name, d.name AS domain, ps.env, ps.version FROM mesh.product_states ps JOIN mesh.products p ON p.id=ps.product_id
                      JOIN mesh.domains d ON d.id=p.domain_id ORDER BY p.name""")
    matrix = {}
    for s in states:
        matrix.setdefault(s["name"], {"product": s["name"], "domain": s["domain"]})[s["env"]] = s["version"]
    promotions = []
    for row in matrix.values():
        for lo, hi in zip(ENV_ORDER, ENV_ORDER[1:]):
            if row.get(lo) and row.get(lo) != row.get(hi):
                promotions.append({"product": row["product"], "from": lo, "to": hi, "version": row[lo], "target_version": row.get(hi)})
    return {"environments": envs, "comparison": list(matrix.values()), "promotions": promotions, "drift": drift}


# ---------------------------------------------------------------- SLA management
def _sla_metrics(items, incidents):
    tot, failed = sum(i["run_total"] for i in items), sum(i["run_failed"] for i in items)
    keys = {(i["id"], i["env"]) for i in items}
    resolved = [x for x in incidents if (x["product_id"], x["env"]) in keys and x["status"] == "Resolved"]
    mttr = _avg((_ts(x["updated_at"]) - _ts(x["created_at"])).total_seconds() / 3600 for x in resolved)
    return {"products": len(items), "availability": _avg(i["availability_pct"] for i in items),
            "freshness_pct": _pct(sum(i["light"] == "Green" for i in items), len(items)),
            "pipeline_success": _pct(tot - failed, tot), "response_time": _avg(i["latency_min"] for i in items),
            "mttr_h": round(mttr, 1) if mttr is not None else None, "mtbf_h": round(14 * 24 / failed, 1) if failed else None,
            "breaches": sum(i["sla_status"] == "Breached" for i in items)}


@router.get("/sla")
def sla(env: str = "PROD", by: str = "product"):
    keyfn = {"product": lambda a: a["name"], "domain": lambda a: a["domain"], "team": lambda a: a["team"], "environment": lambda a: a["env"]}
    if by not in keyfn:
        raise HTTPException(400, f"by must be one of {list(keyfn)}")
    items = [a for e in (ENV_ORDER if by == "environment" else [env]) for a in _availability(e)]
    incidents = query("SELECT product_id, env, status, created_at, updated_at FROM mesh.incidents")
    groups = defaultdict(list)
    for a in items:
        groups[keyfn[by](a)].append(a)
    rows = [{"key": k, **_sla_metrics(v, incidents)} for k, v in groups.items()]
    return {"overall": _sla_metrics(items, incidents), "rows": sorted(rows, key=lambda r: r["availability"] or 0)}

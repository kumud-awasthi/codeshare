"""Manage workspace API: team and data product onboarding, governance, platform services and configuration."""
import datetime as dt

from fastapi import APIRouter, Body, HTTPException, Request

from db import query, one, execute, Json
from ops import user_of, event, _availability, _avg, _pct, monitoring as ops_monitoring
from seed import PROVISION_ITEMS, CHECKLIST_ITEMS

router = APIRouter(prefix="/api/mgmt")
PERSONAS = ["Domain Owner", "Data Product Owner", "Data Steward", "Data Engineer", "Data Consumer", "Governance Reviewer"]
CLASSIFICATIONS = ["Public", "Internal", "Confidential", "Restricted", "PII", "PHI", "Sensitive Financial"]
REVIEW_STAGES = ["Owner Review", "Data Steward Review", "Security Review", "Governance Review", "Publish"]
CERT_LEVELS = ["Bronze", "Silver", "Gold", "Certified Enterprise Product"]
CERT_STATES = ["Requested", "Under Review", "Certified", "Expired", "Revoked"]
CERT_TRANSITIONS = {"request": ({None, "Expired", "Revoked"}, "Requested"), "review": ({"Requested"}, "Under Review"),
                    "certify": ({"Under Review"}, "Certified"), "expire": ({"Certified"}, "Expired"),
                    "revoke": ({"Requested", "Under Review", "Certified"}, "Revoked")}
COMPLIANCE_STATES = ["Compliant", "At Risk", "Non-Compliant"]
RULE_AREAS = {"Policy": ["Retention", "Archival", "Classification", "Sharing"],
              "Standard": ["Naming Convention", "Data Modeling", "Table Structure", "API Standards", "Product Templates"]}
CONNECTOR_TYPES = ["SAP", "Oracle", "Salesforce", "Snowflake", "Fabric", "Kafka", "REST APIs", "Files"]
ONBOARD_FIELDS = ["use_cases", "consumers", "target_tables", "refresh_frequency", "retention_policy", "classification",
                  "expected_volume", "usage_limits", "access_policy", "cert_level"]
MARKETPLACE = [
    {"category": "Infrastructure", "item": "New Workspace", "description": "Databricks workspace with Unity Catalog binding and network isolation", "sla": "3 days"},
    {"category": "Infrastructure", "item": "New Catalog", "description": "Unity Catalog catalog with domain grants and storage location", "sla": "1 day"},
    {"category": "Infrastructure", "item": "New Environment", "description": "Additional DEV / SIT / UAT environment with CI/CD wiring", "sla": "5 days"},
    {"category": "Data Services", "item": "New Product Template", "description": "Scaffold repo, contract, quality rules and pipeline", "sla": "Same day"},
    {"category": "Data Services", "item": "New Connector", "description": "Managed ingestion connector to a new source system", "sla": "5 days"},
    {"category": "Data Services", "item": "New Pipeline", "description": "Lakeflow pipeline from template with monitoring", "sla": "2 days"},
    {"category": "AI Services", "item": "New Agent", "description": "Agent on Mosaic AI with governed tool access to data products", "sla": "5 days"},
    {"category": "AI Services", "item": "New Model Endpoint", "description": "Model serving endpoint routed through the LLM Gateway", "sla": "2 days"},
    {"category": "AI Services", "item": "Semantic Search", "description": "Vector Search index over a data product", "sla": "3 days"},
]


def _iso_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _readiness():
    rows = query("""SELECT p.id, p.name, p.description, p.owner, p.lifecycle, p.certified, p.sla, p.tags, p.schema_def, p.domain_id,
                           d.name AS domain, d.steward, o.use_cases, o.consumers, o.target_tables, o.refresh_frequency, o.retention_policy,
                           o.classification, o.review_stage, o.cert_level, o.cert_status, o.expected_volume, o.usage_limits, o.access_policy
                    FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id LEFT JOIN mesh.product_onboarding o ON o.product_id=p.id
                    ORDER BY p.name""")
    contracts = query("SELECT product_id, kind, status FROM mesh.contracts")
    scores = query("SELECT product_id, quality_score FROM mesh.product_states")
    for r in rows:
        r["review_stage"] = r["review_stage"] or "Owner Review"
        r["missing_metadata"] = [f for f in ("description", "owner", "classification", "use_cases") if not r[f]]
        r["metadata_status"] = "Incomplete" if r["missing_metadata"] else "Complete"
        producer = [c for c in contracts if c["product_id"] == r["id"] and c["kind"] in ("Producer", "SLA", "Schema")]
        r["contracts"] = [c for c in contracts if c["product_id"] == r["id"]]
        r["contract_status"] = "Complete" if any(c["status"] == "Active" for c in producer) else "Pending" if producer else "Missing"
        past_security = r["review_stage"] == "Published" or REVIEW_STAGES.index(r["review_stage"]) > REVIEW_STAGES.index("Security Review")
        r["security_status"] = "Missing" if not r["classification"] else "Approved" if past_security else "Pending"
        q = _avg(s["quality_score"] for s in scores if s["product_id"] == r["id"])
        r["quality"] = q
        r["quality_status"] = "Missing" if q is None else "Passed" if q >= 90 else "Warning" if q >= 80 else "Failed"
        r["approval_status"] = "Approved" if r["review_stage"] == "Published" else r["review_stage"]
        r["compliant"] = r["metadata_status"] == "Complete" and r["contract_status"] == "Complete" and r["security_status"] == "Approved"
        cols = (r["schema_def"] or {}).get("columns", [])
        r["undocumented_columns"] = [c.get("name") for c in cols if not c.get("description")]
    return rows


def _ensure_onboarding(pid):
    if not one("SELECT id FROM mesh.products WHERE id=%s", (pid,)):
        raise HTTPException(404, "Product not found")
    execute("INSERT INTO mesh.product_onboarding(product_id,review_stage) VALUES (%s,'Owner Review') ON CONFLICT (product_id) DO NOTHING", (pid,))
    return one("""SELECT o.*, p.name, p.lifecycle FROM mesh.product_onboarding o JOIN mesh.products p ON p.id=o.product_id
                  WHERE o.product_id=%s""", (pid,))


def _set_check(tid, item, done):
    execute("""INSERT INTO mesh.team_checklist(team_id,item,done) VALUES (%s,%s,%s)
               ON CONFLICT (team_id,item) DO UPDATE SET done=EXCLUDED.done, updated_at=now()""", (tid, item, done))


def _team(tid):
    t = one("SELECT * FROM mesh.teams WHERE id=%s", (tid,))
    if not t:
        raise HTTPException(404, "Team not found")
    return t


# ---------------------------------------------------------------- new team onboarding
@router.get("/teams")
def teams():
    rows = query("SELECT t.*, d.name AS domain FROM mesh.teams t LEFT JOIN mesh.domains d ON d.id=t.domain_id ORDER BY t.name")
    members = query("SELECT * FROM mesh.team_members ORDER BY persona, member")
    prov = {(p["team_id"], p["item"]): p["status"] for p in query("SELECT * FROM mesh.team_provisioning")}
    checks = {(c["team_id"], c["item"]): bool(c["done"]) for c in query("SELECT * FROM mesh.team_checklist")}
    ready = _readiness()
    av = _availability("PROD")
    for t in rows:
        t["members"] = [m for m in members if m["team_id"] == t["id"]]
        t["provisioning"] = {i: prov.get((t["id"], i), "Not Started") for i in PROVISION_ITEMS}
        t["checklist"] = {i: checks.get((t["id"], i), False) for i in CHECKLIST_ITEMS}
        owned = [r for r in ready if r["domain_id"] == t["domain_id"]]
        t_av = [a for a in av if a["id"] in {r["id"] for r in owned}]
        t["health"] = {"active_members": len(t["members"]), "products": len(owned),
                       "sla": _avg(a["availability_pct"] for a in t_av), "breaches": sum(a["sla_status"] == "Breached" for a in t_av),
                       "compliance": _pct(sum(r["compliant"] for r in owned), len(owned)) if owned else None}
    domains = query("""SELECT d.*, (SELECT count(*) FROM mesh.products p WHERE p.domain_id=d.id) AS products FROM mesh.domains d ORDER BY d.name""")
    return {"teams": rows, "domains": domains, "personas": PERSONAS, "provision_items": PROVISION_ITEMS, "checklist_items": CHECKLIST_ITEMS}


@router.post("/teams")
def register_team(request: Request, body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Team name is required")
    if one("SELECT id FROM mesh.teams WHERE name=%s", (name,)):
        raise HTTPException(409, "A team with this name already exists")
    if body.get("domain_id") and not one("SELECT id FROM mesh.domains WHERE id=%s", (body["domain_id"],)):
        raise HTTPException(404, "Domain not found")
    t = one("""INSERT INTO mesh.teams(name,business_unit,domain_id,owner,steward,tech_lead,product_owner,status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'Onboarding') RETURNING *""",
            (name, body.get("business_unit"), body.get("domain_id") or None, body.get("owner"), body.get("steward"),
             body.get("tech_lead"), body.get("product_owner")))
    for persona, key in [("Domain Owner", "owner"), ("Data Steward", "steward"), ("Data Engineer", "tech_lead"), ("Data Product Owner", "product_owner")]:
        if body.get(key):
            execute("INSERT INTO mesh.team_members(team_id,member,persona) VALUES (%s,%s,%s)", (t["id"], body[key], persona))
    for item in PROVISION_ITEMS:
        execute("INSERT INTO mesh.team_provisioning(team_id,item,status) VALUES (%s,%s,'Not Started')", (t["id"], item))
    for item in CHECKLIST_ITEMS:
        _set_check(t["id"], item, item == "Team Registered" or (item == "Roles Assigned" and bool(body.get("owner"))))
    event("PROD", "Onboarding", f"Team registered: {name}", user_of(request))
    return t


@router.post("/teams/{tid}/domain")
def assign_domain(tid: int, request: Request, body: dict = Body(...)):
    t = _team(tid)
    d = one("SELECT * FROM mesh.domains WHERE id=%s", (body.get("domain_id"),))
    if not d:
        raise HTTPException(404, "Domain not found")
    execute("UPDATE mesh.teams SET domain_id=%s WHERE id=%s", (d["id"], tid))
    event("PROD", "Onboarding", f"Team {t['name']} assigned to domain {d['name']}", user_of(request))
    return {"ok": True}


@router.post("/teams/{tid}/members")
def add_member(tid: int, request: Request, body: dict = Body(...)):
    t = _team(tid)
    member, persona = (body.get("member") or "").strip(), body.get("persona")
    if not member:
        raise HTTPException(400, "member is required")
    if persona not in PERSONAS:
        raise HTTPException(400, f"persona must be one of {PERSONAS}")
    m = one("INSERT INTO mesh.team_members(team_id,member,persona) VALUES (%s,%s,%s) RETURNING *", (tid, member, persona))
    _set_check(tid, "Roles Assigned", True)
    event("PROD", "Onboarding", f"{member} added to {t['name']} as {persona}", user_of(request))
    return m


@router.post("/teams/{tid}/members/{mid}/remove")
def remove_member(tid: int, mid: int, request: Request):
    t = _team(tid)
    m = one("SELECT * FROM mesh.team_members WHERE id=%s AND team_id=%s", (mid, tid))
    if not m:
        raise HTTPException(404, "Member not found")
    execute("DELETE FROM mesh.team_members WHERE id=%s", (mid,))
    event("PROD", "Onboarding", f"{m['member']} removed from {t['name']}", user_of(request))
    return {"ok": True}


@router.post("/teams/{tid}/provision")
def provision(tid: int, request: Request, body: dict = Body(...)):
    t = _team(tid)
    item = body.get("item")
    items = PROVISION_ITEMS if item == "all" else [item]
    if not set(items) <= set(PROVISION_ITEMS):
        raise HTTPException(400, f"item must be 'all' or one of {PROVISION_ITEMS}")
    for i in items:
        execute("""INSERT INTO mesh.team_provisioning(team_id,item,status) VALUES (%s,%s,'Provisioned')
                   ON CONFLICT (team_id,item) DO UPDATE SET status='Provisioned', updated_at=now()""", (tid, i))
    done = one("SELECT count(*) AS n FROM mesh.team_provisioning WHERE team_id=%s AND status='Provisioned'", (tid,))["n"]
    if done >= len(PROVISION_ITEMS):
        _set_check(tid, "Workspace Created", True)
    event("PROD", "Onboarding", f"Provisioned {', '.join(items)} for {t['name']}", user_of(request))
    return {"provisioned": items}


@router.post("/teams/{tid}/checklist")
def checklist(tid: int, request: Request, body: dict = Body(...)):
    t = _team(tid)
    if body.get("item") not in CHECKLIST_ITEMS:
        raise HTTPException(400, f"item must be one of {CHECKLIST_ITEMS}")
    _set_check(tid, body["item"], bool(body.get("done")))
    event("PROD", "Onboarding", f"{t['name']}: {body['item']} {'completed' if body.get('done') else 'reopened'}", user_of(request))
    return {"ok": True}


@router.post("/teams/{tid}/activate")
def activate(tid: int, request: Request):
    t = _team(tid)
    done = {c["item"] for c in query("SELECT item FROM mesh.team_checklist WHERE team_id=%s AND done=%s", (tid, True))}
    missing = [i for i in CHECKLIST_ITEMS if i not in done]
    if missing:
        raise HTTPException(400, f"Readiness checklist incomplete: {', '.join(missing)}")
    if not t["domain_id"]:
        raise HTTPException(400, "Assign a domain before activating the team")
    execute("UPDATE mesh.teams SET status='Active' WHERE id=%s", (tid,))
    event("PROD", "Onboarding", f"Team activated: {t['name']}", user_of(request))
    return {"ok": True}


# ---------------------------------------------------------------- new data product onboarding
@router.get("/products")
def products():
    return {"products": _readiness(), "classifications": CLASSIFICATIONS, "stages": REVIEW_STAGES, "cert_levels": CERT_LEVELS,
            "cert_states": CERT_STATES, "domains": query("SELECT id, name FROM mesh.domains ORDER BY name")}


@router.put("/products/{pid}/onboarding")
def update_onboarding(pid: int, request: Request, body: dict = Body(...)):
    o = _ensure_onboarding(pid)
    fields = {k: (v or None) for k, v in body.items() if k in ONBOARD_FIELDS}
    if fields.get("classification") and fields["classification"] not in CLASSIFICATIONS:
        raise HTTPException(400, f"classification must be one of {CLASSIFICATIONS}")
    if fields.get("cert_level") and fields["cert_level"] not in CERT_LEVELS:
        raise HTTPException(400, f"cert_level must be one of {CERT_LEVELS}")
    if fields:
        # column names come from the ONBOARD_FIELDS allow-list
        execute(f"UPDATE mesh.product_onboarding SET {', '.join(k + '=%s' for k in fields)}, updated_at=now() WHERE product_id=%s",
                (*fields.values(), pid))
        event("DEV", "Onboarding", f"{o['name']} onboarding updated: {', '.join(fields)}", user_of(request))
    return one("SELECT * FROM mesh.product_onboarding WHERE product_id=%s", (pid,))


@router.post("/products/{pid}/review")
def review(pid: int, request: Request, body: dict = Body(...)):
    o = _ensure_onboarding(pid)
    stage, decision = o["review_stage"] or "Owner Review", body.get("decision")
    if stage == "Published":
        raise HTTPException(400, "Product is already published")
    if decision == "reject":
        nxt, lifecycle = "Owner Review", "Draft"
    elif decision == "approve":
        if stage == "Security Review" and not o["classification"]:
            raise HTTPException(400, "Classify the product before approving the security review")
        nxt = "Published" if stage == "Publish" else REVIEW_STAGES[REVIEW_STAGES.index(stage) + 1]
        lifecycle = "Published" if nxt == "Published" else "Review"
    else:
        raise HTTPException(400, "decision must be approve or reject")
    execute("UPDATE mesh.product_onboarding SET review_stage=%s, updated_at=now() WHERE product_id=%s", (nxt, pid))
    execute("UPDATE mesh.products SET lifecycle=%s WHERE id=%s", (lifecycle, pid))
    event("DEV", "Approval", f"{o['name']}: {stage} {decision}d" + (" - published" if nxt == "Published" else ""), user_of(request))
    return {"stage": nxt, "lifecycle": lifecycle}


@router.post("/products/{pid}/certification")
def certification(pid: int, request: Request, body: dict = Body(...)):
    o = _ensure_onboarding(pid)
    action = body.get("action")
    if action not in CERT_TRANSITIONS:
        raise HTTPException(400, f"action must be one of {list(CERT_TRANSITIONS)}")
    allowed, nxt = CERT_TRANSITIONS[action]
    if o["cert_status"] not in allowed:
        raise HTTPException(400, f"Cannot {action} a certification in state {o['cert_status'] or 'None'}")
    level = body.get("level") or o["cert_level"] or "Bronze"
    if level not in CERT_LEVELS:
        raise HTTPException(400, f"level must be one of {CERT_LEVELS}")
    execute("UPDATE mesh.product_onboarding SET cert_status=%s, cert_level=%s, updated_at=now() WHERE product_id=%s", (nxt, level, pid))
    execute("UPDATE mesh.products SET certified=%s WHERE id=%s", (nxt == "Certified", pid))
    event("PROD", "Certification", f"{o['name']} certification {nxt.lower()} ({level})", user_of(request))
    return {"cert_status": nxt, "cert_level": level}


# ---------------------------------------------------------------- governance
@router.get("/governance")
def governance(env: str = "PROD"):
    ready = _readiness()
    rules = query("SELECT * FROM mesh.quality_rules WHERE env IN ('DEV','SIT','UAT','PROD')")
    order = ["DEV", "SIT", "UAT", "PROD"]
    lower = order[max(0, order.index(env) - 1)] if env in order else "UAT"
    quality = []
    for r in ready:
        cur = [x for x in rules if x["product_id"] == r["id"] and x["env"] == env]
        if not cur:
            continue
        prev = [x["pass_rate"] for x in rules if x["product_id"] == r["id"] and x["env"] == lower]
        score = _avg(x["pass_rate"] for x in cur)
        quality.append({"id": r["id"], "name": r["name"], "domain": r["domain"], "score": score,
                        "trend": round(score - _avg(prev), 1) if prev and lower != env else None,
                        "violations": sum(x["status"] != "Pass" for x in cur),
                        "dimensions": {x["dimension"]: x["pass_rate"] for x in cur}})
    dims = {}
    for q in quality:
        for k, v in q["dimensions"].items():
            dims.setdefault(k, []).append(v)
    lineage = query("""SELECT l.kind, s.name AS source, sd.name AS source_domain, t.name AS target, td.name AS target_domain
                       FROM mesh.lineage l JOIN mesh.products s ON s.id=l.src_product_id JOIN mesh.domains sd ON sd.id=s.domain_id
                       JOIN mesh.products t ON t.id=l.dst_product_id JOIN mesh.domains td ON td.id=t.domain_id ORDER BY s.name""")
    return {
        "rules": query("SELECT * FROM mesh.gov_rules ORDER BY kind, area, name"), "areas": RULE_AREAS,
        "policies": query("SELECT * FROM mesh.policies ORDER BY name"),
        "metadata": {"missing_metadata": [r for r in ready if r["missing_metadata"]],
                     "missing_owners": [r for r in ready if not r["owner"] or not r["steward"]],
                     "missing_classification": [r for r in ready if not r["classification"]],
                     "incomplete_docs": [r for r in ready if r["undocumented_columns"] or not r["use_cases"]]},
        "quality": quality, "dimensions": {k: _avg(v) for k, v in dims.items()},
        "compliance": query("SELECT * FROM mesh.compliance_checks ORDER BY framework, name"), "compliance_states": COMPLIANCE_STATES,
        "lineage": lineage, "certification": ready, "cert_states": CERT_STATES, "cert_levels": CERT_LEVELS,
    }


@router.post("/governance/rules")
def create_rule(request: Request, body: dict = Body(...)):
    kind, area = body.get("kind"), body.get("area")
    if kind not in RULE_AREAS or area not in RULE_AREAS[kind]:
        raise HTTPException(400, "Invalid kind/area")
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "name is required")
    user = user_of(request)
    r = one("INSERT INTO mesh.gov_rules(kind,area,name,rule,value,status,owner) VALUES (%s,%s,%s,%s,%s,'Active',%s) RETURNING *",
            (kind, area, body["name"].strip(), body.get("rule", ""), body.get("value", ""), user))
    event("PROD", "Governance", f"{kind} added ({area}): {r['name']}", user)
    return r


@router.post("/governance/compliance/{cid}")
def assess(cid: int, request: Request, body: dict = Body(...)):
    if body.get("status") not in COMPLIANCE_STATES:
        raise HTTPException(400, f"status must be one of {COMPLIANCE_STATES}")
    c = one("UPDATE mesh.compliance_checks SET status=%s, last_assessed=now() WHERE id=%s RETURNING *", (body["status"], cid))
    if not c:
        raise HTTPException(404, "Compliance check not found")
    event("PROD", "Governance", f"Compliance {c['name']} assessed as {c['status']}", user_of(request))
    return c


# ---------------------------------------------------------------- platform services
@router.get("/platform")
def platform():
    services = query("SELECT * FROM mesh.platform_services ORDER BY category, name")
    compute = [s for s in services if s["category"] == "Compute"]
    running = sum(s["details"].get("state") == "Running" for s in compute)
    tiles = ops_monitoring("PROD")["tiles"]
    tiles.insert(2, {"name": "Cluster Health", "status": "Healthy" if all(s["status"] == "Healthy" for s in compute) else "Warning",
                     "metric": f"{running} of {len(compute)} compute services running"})
    return {"services": services, "monitoring": [t for t in tiles if t["name"] != "Product Health"], "marketplace": MARKETPLACE,
            "requests": query("SELECT * FROM mesh.service_requests ORDER BY created_at DESC"),
            "teams": [t["name"] for t in query("SELECT name FROM mesh.teams ORDER BY name")], "connector_types": CONNECTOR_TYPES}


@router.post("/platform/services")
def create_connector(request: Request, body: dict = Body(...)):
    name, src = (body.get("name") or "").strip(), body.get("source_type")
    if not name:
        raise HTTPException(400, "name is required")
    if src not in CONNECTOR_TYPES:
        raise HTTPException(400, f"source_type must be one of {CONNECTOR_TYPES}")
    try:
        sla = int(body.get("sla_min") or 1440)
    except (TypeError, ValueError):
        raise HTTPException(400, "sla_min must be a number")
    user = user_of(request)
    s = one("INSERT INTO mesh.platform_services(category,name,status,owner,details) VALUES ('Ingestion',%s,'Healthy',%s,%s) RETURNING *",
            (name, user, Json({"source_type": src, "schedule": body.get("schedule") or "Daily", "last_sync": None, "sla_min": sla, "records_24h": 0})))
    event("PROD", "Platform", f"Connector created: {name} ({src})", user)
    return s


@router.post("/platform/services/{sid}/action")
def service_action(sid: int, request: Request, body: dict = Body(...)):
    s = one("SELECT * FROM mesh.platform_services WHERE id=%s", (sid,))
    if not s:
        raise HTTPException(404, "Service not found")
    action, d, status = body.get("action"), dict(s["details"] or {}), s["status"]
    if action == "sync" and s["category"] in ("Ingestion", "Catalog"):
        d["last_sync"], status = _iso_now(), "Healthy"
    elif action in ("start", "stop") and s["category"] == "Compute":
        d["state"] = "Running" if action == "start" else "Stopped"
    elif action == "autoscale" and s["category"] == "Compute":
        d["autoscale"] = not d.get("autoscale")
    else:
        raise HTTPException(400, f"Action {action} is not supported for {s['category']} services")
    execute("UPDATE mesh.platform_services SET details=%s, status=%s, updated_at=now() WHERE id=%s", (Json(d), status, sid))
    event("PROD", "Platform", f"{s['name']}: {action}", user_of(request))
    return {"ok": True}


@router.post("/platform/requests")
def create_request(request: Request, body: dict = Body(...)):
    offer = next((m for m in MARKETPLACE if m["item"] == body.get("item")), None)
    if not offer:
        raise HTTPException(400, "Unknown marketplace item")
    user = user_of(request)
    r = one("""INSERT INTO mesh.service_requests(category,item,team,requester,justification,status)
               VALUES (%s,%s,%s,%s,%s,'Submitted') RETURNING *""", (offer["category"], offer["item"], body.get("team"), user, body.get("justification", "")))
    event("PROD", "Platform", f"Service requested: {offer['item']} for {body.get('team') or 'unassigned team'}", user)
    return r


@router.post("/platform/requests/{rid}/action")
def request_action(rid: int, request: Request, body: dict = Body(...)):
    transitions = {"approve": ({"Submitted"}, "Approved"), "fulfil": ({"Approved"}, "Fulfilled"), "reject": ({"Submitted", "Approved"}, "Rejected")}
    r = one("SELECT * FROM mesh.service_requests WHERE id=%s", (rid,))
    if not r:
        raise HTTPException(404, "Request not found")
    if body.get("action") not in transitions or r["status"] not in transitions[body["action"]][0]:
        raise HTTPException(400, f"Cannot {body.get('action')} a request in state {r['status']}")
    nxt = transitions[body["action"]][1]
    execute("UPDATE mesh.service_requests SET status=%s, updated_at=now() WHERE id=%s", (nxt, rid))
    event("PROD", "Platform", f"Service request #{rid} ({r['item']}) {nxt.lower()}", user_of(request))
    return {"status": nxt}


# ---------------------------------------------------------------- platform configuration
@router.get("/config")
def config():
    return query("SELECT * FROM mesh.platform_config ORDER BY category, setting")


@router.put("/config/{setting}")
def update_config(setting: str, request: Request, body: dict = Body(...)):
    user = user_of(request)
    c = one("UPDATE mesh.platform_config SET value=%s, updated_by=%s, updated_at=now() WHERE setting=%s RETURNING *",
            (str(body.get("value", "")), user, setting))
    if not c:
        raise HTTPException(404, "Setting not found")
    event("PROD", "Configuration", f"{setting} set to {c['value']}", user)
    return c

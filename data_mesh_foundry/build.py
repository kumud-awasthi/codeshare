"""Build workspace API: intake readiness, development, publication, post-release validation and IAM validation."""
from fastapi import APIRouter, Body, HTTPException, Request

from db import query, one, execute, Json
from ops import user_of, event
from mgmt import _readiness
from seed import TEST_SUITES

router = APIRouter(prefix="/api/build")
ENVS = ["DEV", "SIT", "UAT", "PROD"]
CHECK_STATES = ["Passed", "Failed", "Pending"]
SIGNOFFS = ["Security Team", "Platform Team", "Data Product Owner"]
CONSUMER_TESTS = ["Authorized User -> Success", "Unauthorized User -> Denied", "Restricted Data -> Masked"]
MANUAL_CHECKS = {"intake": ["Business requirements approved"], "source": ["Connectivity established", "Data profiling completed"],
                 "environment": ["Compute resources assigned"], "signoff": SIGNOFFS}
MODEL_KINDS = ["Table", "View", "Schema", "Dimension", "Fact"]
MODEL_LAYERS = ["Bronze", "Silver", "Gold", "Semantic"]
MODEL_TYPES = ["Physical", "Logical", "Semantic"]
RULE_CATEGORIES = {"Business": ["Calculation", "Transformation", "Standardization", "Aggregation"],
                   "Quality": ["Null Check", "Duplicate Check", "Threshold Check", "Reference Validation", "Business Rule Validation"]}
RELEASE_STAGES = ["Product Owner", "Data Steward", "Platform Team", "Release Manager", "Publish"]
ROLE_RANK = {"Reader": 1, "Contributor": 2, "Owner": 3}
SENSITIVE = {"PII", "PHI", "Sensitive Financial", "Confidential", "Restricted"}
UNAUTHORIZED_PROBE = "unauthorized.probe@corp.com"


def _get(pid):
    p = next((r for r in _readiness() if r["id"] == pid), None)
    if not p:
        raise HTTPException(404, "Product not found")
    return p


def _auto(item, ok, detail=""):
    return {"item": item, "status": "Passed" if ok else "Failed", "source": "auto", "detail": detail}


def _manual(rows, area, item):
    r = rows.get((area, item))
    return {"item": item, "status": r["status"] if r else "Pending", "source": "manual", "area": area,
            "detail": f"{r['checked_by'] or ''} {r['note'] or ''}".strip() if r else "Awaiting confirmation", "checked_at": r["checked_at"] if r else None}


def _checks(pid):
    return {(c["area"], c["item"]): c for c in query("SELECT * FROM mesh.build_checks WHERE product_id=%s", (pid,))}


def _tests(pid):
    return query("SELECT * FROM mesh.build_tests WHERE product_id=%s ORDER BY suite, name", (pid,))


def _build_status(p, tests):
    if p["lifecycle"] == "Published":
        return "Published"
    if tests and all(t["status"] == "Passed" for t in tests):
        return "Ready to Publish"
    return "Testing" if any(t["status"] != "Not Run" for t in tests) else "In Development"


def _effective(grants, members, principal):
    groups = {m["group_name"] for m in members if m["principal"] == principal}
    roles = [g["role"] for g in grants if g["principal"] == principal or g["principal"] in groups]
    return max(roles, key=lambda r: ROLE_RANK.get(r, 0)) if roles else None


# ---------------------------------------------------------------- product list
@router.get("/products")
def products():
    rows = query("""SELECT p.id, p.name, p.lifecycle, p.owner, d.name AS domain FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id
                    ORDER BY p.name""")
    tests = query("SELECT product_id, status FROM mesh.build_tests")
    for r in rows:
        r["build_status"] = _build_status(r, [t for t in tests if t["product_id"] == r["id"]])
    return rows


@router.post("/products/{pid}/checks")
def set_check(pid: int, request: Request, body: dict = Body(...)):
    _get(pid)
    area, item, status = body.get("area"), body.get("item"), body.get("status")
    if item not in MANUAL_CHECKS.get(area, []):
        raise HTTPException(400, "Unknown manual check")
    if status not in CHECK_STATES:
        raise HTTPException(400, f"status must be one of {CHECK_STATES}")
    user = user_of(request)
    execute("""INSERT INTO mesh.build_checks(product_id,area,item,status,checked_by,note) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (product_id,area,item) DO UPDATE SET status=EXCLUDED.status, checked_by=EXCLUDED.checked_by,
               note=EXCLUDED.note, checked_at=now()""", (pid, area, item, status, user, body.get("note")))
    event("DEV", "Build", f"Product #{pid}: {item} marked {status.lower()}", user)
    return {"ok": True}


# ---------------------------------------------------------------- intake & readiness
@router.get("/products/{pid}/readiness")
def readiness(pid: int):
    p = _get(pid)
    rows = _checks(pid)
    prov = {r["item"] for r in query("""SELECT item FROM mesh.team_provisioning WHERE status='Provisioned'
                                         AND team_id IN (SELECT id FROM mesh.teams WHERE domain_id=%s)""", (p["domain_id"],))}
    storage = one("SELECT allocated FROM mesh.quotas WHERE domain_id=%s AND resource='Storage'", (p["domain_id"],))
    sources = (p["schema_def"] or {}).get("sources") or []

    def active(kind):
        return any(c["kind"] == kind and c["status"] == "Active" for c in p["contracts"])

    areas = {
        "intake": [_auto("Product request approved", p["lifecycle"] != "Draft" or p["review_stage"] != "Owner Review", f"Lifecycle {p['lifecycle']} / {p['review_stage']}"),
                   _manual(rows, "intake", "Business requirements approved"),
                   _auto("Product owner assigned", bool(p["owner"]), p["owner"] or "No owner"),
                   _auto("Domain assigned", bool(p["domain"]), p["domain"]),
                   _auto("Use cases documented", bool(p["use_cases"]), p["use_cases"] or "Missing use cases")],
        "source": [_auto("Source systems identified", bool(sources), ", ".join(sources) or "No sources"),
                   _manual(rows, "source", "Connectivity established"), _manual(rows, "source", "Data profiling completed"),
                   _auto("Data classifications completed", bool(p["classification"]), p["classification"] or "Unclassified")],
        "environment": [_auto("Development workspace provisioned", "Databricks Workspace Access" in prov, "Domain team workspace access"),
                        _auto("Catalog/schema created", "Unity Catalog Permissions" in prov, f"{p['domain'].lower()}.bronze / silver / gold"),
                        _auto("Storage allocated", bool(storage), f"{storage['allocated']:g} TB domain quota" if storage else "No storage quota"),
                        _manual(rows, "environment", "Compute resources assigned")],
        "contract": [_auto("Producer contract approved", active("Producer")), _auto("SLA approved", active("SLA"), p["sla"] or ""),
                     _auto("Schema approved", active("Schema")),
                     _auto("Consumer expectations defined", bool(p["expected_volume"] and p["access_policy"]),
                           f"{p['expected_volume'] or '-'} / {p['access_policy'] or '-'}")],
        "security": [_auto("Security review approved", p["security_status"] == "Approved", f"Classification {p['classification'] or '-'}, stage {p['review_stage']}")],
    }
    passed = {k: all(c["status"] == "Passed" for c in v) for k, v in areas.items()}
    dashboard = [{"name": n, "area": a, "passed": passed[a]} for n, a in [("Business Approval", "intake"), ("Source Connectivity", "source"),
                                                                        ("Development Environment", "environment"), ("Contracts Approved", "contract"),
                                                                        ("Security Review", "security")]]
    return {"product": {k: p[k] for k in ("id", "name", "domain", "owner", "lifecycle", "classification", "review_stage")},
            "areas": areas, "dashboard": dashboard, "overall": "Ready for Build" if all(passed.values()) else "Not Ready",
            "contracts": p["contracts"]}


# ---------------------------------------------------------------- develop
@router.get("/products/{pid}/develop")
def develop(pid: int):
    p = _get(pid)
    tests = _tests(pid)
    states = query("SELECT env, version, status FROM mesh.product_states WHERE product_id=%s", (pid,))
    up = query("""SELECT p.name FROM mesh.lineage l JOIN mesh.products p ON p.id=l.src_product_id WHERE l.dst_product_id=%s""", (pid,))
    down = query("""SELECT p.name FROM mesh.lineage l JOIN mesh.products p ON p.id=l.dst_product_id WHERE l.src_product_id=%s""", (pid,))
    return {
        "product": {k: p[k] for k in ("id", "name", "domain", "owner", "steward", "description", "lifecycle", "sla", "classification", "use_cases", "schema_def")},
        "version": next((s["version"] for s in states if s["env"] == "DEV"), None),
        "environments": sorted((s["env"] for s in states), key=ENVS.index), "build_status": _build_status(p, tests),
        "models": query("SELECT * FROM mesh.build_models WHERE product_id=%s ORDER BY layer, name", (pid,)),
        "pipelines": query("SELECT * FROM mesh.pipelines WHERE product_id=%s ORDER BY id", (pid,)),
        "rules": query("SELECT * FROM mesh.build_rules WHERE product_id=%s ORDER BY kind, category, name", (pid,)),
        "dq_results": query("SELECT rule, dimension, pass_rate, status FROM mesh.quality_rules WHERE product_id=%s AND env='DEV'", (pid,)),
        "tests": tests, "suites": TEST_SUITES,
        "glossary": query("SELECT term, definition FROM mesh.glossary WHERE domain_id=%s OR domain_id IS NULL ORDER BY term", (p["domain_id"],)),
        "upstream": [r["name"] for r in up], "downstream": [r["name"] for r in down],
        "model_kinds": MODEL_KINDS, "model_layers": MODEL_LAYERS, "model_types": MODEL_TYPES, "rule_categories": RULE_CATEGORIES,
    }


@router.post("/products/{pid}/models")
def add_model(pid: int, request: Request, body: dict = Body(...)):
    _get(pid)
    if body.get("kind") not in MODEL_KINDS or body.get("layer") not in MODEL_LAYERS or body.get("model_type") not in MODEL_TYPES:
        raise HTTPException(400, "Invalid kind, layer or model type")
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "name is required")
    m = one("""INSERT INTO mesh.build_models(product_id,name,kind,layer,model_type,column_count,status) VALUES (%s,%s,%s,%s,%s,%s,'Draft') RETURNING *""",
            (pid, body["name"].strip(), body["kind"], body["layer"], body["model_type"], int(body.get("column_count") or 0)))
    event("DEV", "Build", f"Model added: {m['name']}", user_of(request))
    return m


@router.post("/products/{pid}/rules")
def add_rule(pid: int, request: Request, body: dict = Body(...)):
    _get(pid)
    kind, cat = body.get("kind"), body.get("category")
    if kind not in RULE_CATEGORIES or cat not in RULE_CATEGORIES[kind]:
        raise HTTPException(400, "Invalid rule kind/category")
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "name is required")
    r = one("""INSERT INTO mesh.build_rules(product_id,kind,category,name,expression,threshold,status) VALUES (%s,%s,%s,%s,%s,%s,'Active') RETURNING *""",
            (pid, kind, cat, body["name"].strip(), body.get("expression", ""), body.get("threshold") or None))
    event("DEV", "Build", f"{kind} rule added: {r['name']}", user_of(request))
    return r


@router.post("/products/{pid}/tests/run")
def run_tests(pid: int, request: Request, body: dict = Body(...)):
    p = _get(pid)
    suite = body.get("suite", "All")
    if suite != "All" and suite not in TEST_SUITES:
        raise HTTPException(400, f"suite must be 'All' or one of {TEST_SUITES}")
    failing_dq = one("SELECT count(*) AS n FROM mesh.quality_rules WHERE product_id=%s AND env='DEV' AND status='Fail'", (pid,))["n"]
    results = {"Passed": 0, "Failed": 0}
    for t in _tests(pid):
        if suite != "All" and t["suite"] != suite:
            continue
        status = "Failed" if t["suite"] == "Data Validation" and failing_dq else "Passed"
        results[status] += 1
        execute("UPDATE mesh.build_tests SET status=%s, duration_s=%s, last_run=now() WHERE id=%s", (status, round(1 + (t["id"] % 7) * 1.3, 1), t["id"]))
    event("DEV", "Build", f"{suite} tests for {p['name']}: {results['Passed']} passed, {results['Failed']} failed", user_of(request))
    return results


@router.get("/products/{pid}/runbook")
def runbook(pid: int):
    p = _get(pid)
    pls = query("""SELECT pl.name, pl.env, pl.engine, s.frequency FROM mesh.pipelines pl LEFT JOIN mesh.pipeline_schedules s ON s.pipeline_id=pl.id
                   WHERE pl.product_id=%s ORDER BY pl.env""", (pid,))
    lines = [f"# Runbook: {p['name']}", "", f"Domain: {p['domain']}  |  Owner: {p['owner']}  |  Steward: {p['steward']}", f"SLA: {p['sla']}", "",
             "## Pipelines"] + [f"- {x['name']} ({x['env']}, {x['engine']}, {x['frequency'] or 'unscheduled'})" for x in pls] + [
             "", "## Failure handling", "1. Check Operate > Pipeline Operations > Recovery for the failed job.",
             "2. Re-run the job; if data is missing, submit a Partition Reload backfill.",
             "3. If the SLA is breached, open an incident and notify consumers listed in Data Availability > Consumer Impact.",
             "", "## Escalation", f"- L1: {p['domain'].lower()}-oncall@corp.com", f"- L2: {p['owner']}", "- L3: platform-ops@corp.com"]
    return {"kind": "runbook", "code": "\n".join(lines)}


# ---------------------------------------------------------------- publish
def _package(pid, p):
    models = query("SELECT name, kind FROM mesh.build_models WHERE product_id=%s", (pid,))
    return {
        "Tables": [m["name"] for m in models if m["kind"] in ("Table", "Fact", "Dimension")],
        "Views": [m["name"] for m in models if m["kind"] == "View"],
        "Pipelines": sorted({r["name"] for r in query("SELECT name FROM mesh.pipelines WHERE product_id=%s", (pid,))}),
        "Quality Rules": [r["name"] for r in query("SELECT name FROM mesh.build_rules WHERE product_id=%s AND kind='Quality'", (pid,))],
        "Metadata": ["Business description", "Ownership", f"Classification: {p['classification'] or 'missing'}", "Glossary terms"],
        "Documentation": ["README", "Data contract", "Runbook"],
    }


def _publish_checks(p, tests):
    return [_auto("Testing Complete", bool(tests) and all(t["status"] == "Passed" for t in tests), f"{sum(t['status'] == 'Passed' for t in tests)}/{len(tests)} tests passed"),
            _auto("Documentation Complete", p["metadata_status"] == "Complete", ", ".join(p["missing_metadata"]) or "Complete"),
            _auto("Quality Passed", p["quality_status"] == "Passed", f"Quality score {p['quality']}"),
            _auto("Contracts Approved", p["contract_status"] == "Complete", p["contract_status"]),
            _auto("Security Approved", p["security_status"] == "Approved", p["security_status"])]


@router.get("/products/{pid}/publish")
def publish_view(pid: int):
    p = _get(pid)
    tests = _tests(pid)
    return {"product": {k: p[k] for k in ("id", "name", "domain", "lifecycle", "owner")}, "checks": _publish_checks(p, tests),
            "package": _package(pid, p), "stages": RELEASE_STAGES,
            "releases": query("SELECT * FROM mesh.build_releases WHERE product_id=%s ORDER BY created_at DESC", (pid,)),
            "states": {s["env"]: s for s in query("SELECT env, version, status, updated_at FROM mesh.product_states WHERE product_id=%s", (pid,))},
            "deployments": query("SELECT * FROM mesh.deployments WHERE object_name=%s ORDER BY created_at DESC LIMIT 20", (p["name"],))}


@router.post("/products/{pid}/releases")
def create_release(pid: int, request: Request, body: dict = Body(...)):
    p = _get(pid)
    version = (body.get("version") or "").strip()
    if not version:
        raise HTTPException(400, "version is required")
    if one("SELECT id FROM mesh.build_releases WHERE product_id=%s AND version=%s", (pid, version)):
        raise HTTPException(409, f"Release {version} already exists")
    pkg = _package(pid, p)
    user = user_of(request)
    r = one("""INSERT INTO mesh.build_releases(product_id,version,status,stage,artifacts,notes,created_by)
               VALUES (%s,%s,'In Approval','Product Owner',%s,%s,%s) RETURNING *""",
            (pid, version, Json({k: len(v) for k, v in pkg.items()}), body.get("notes", ""), user))
    event("DEV", "Release", f"Release package {p['name']} {version} created", user)
    return r


@router.post("/releases/{rid}/decision")
def release_decision(rid: int, request: Request, body: dict = Body(...)):
    r = one("SELECT r.*, p.name FROM mesh.build_releases r JOIN mesh.products p ON p.id=r.product_id WHERE r.id=%s", (rid,))
    if not r:
        raise HTTPException(404, "Release not found")
    if r["status"] != "In Approval":
        raise HTTPException(400, f"Release is {r['status']}")
    if body.get("decision") == "reject":
        status, stage = "Rejected", r["stage"]
    elif body.get("decision") == "approve":
        stage = RELEASE_STAGES[RELEASE_STAGES.index(r["stage"]) + 1]
        status = "Approved" if stage == "Publish" else "In Approval"
    else:
        raise HTTPException(400, "decision must be approve or reject")
    execute("UPDATE mesh.build_releases SET status=%s, stage=%s, updated_at=now() WHERE id=%s", (status, stage, rid))
    event("DEV", "Release", f"{r['name']} {r['version']}: {r['stage']} {body['decision']}d", user_of(request))
    return {"status": status, "stage": stage}


@router.post("/releases/{rid}/publish")
def publish_release(rid: int, request: Request):
    r = one("SELECT * FROM mesh.build_releases WHERE id=%s", (rid,))
    if not r:
        raise HTTPException(404, "Release not found")
    if r["status"] != "Approved":
        raise HTTPException(400, "Only approved releases can be published")
    p = _get(r["product_id"])
    failed = [c["item"] for c in _publish_checks(p, _tests(p["id"])) if c["status"] != "Passed"]
    if failed:
        raise HTTPException(400, f"Publish readiness not met: {', '.join(failed)}")
    user = user_of(request)
    execute("UPDATE mesh.build_releases SET status='Published', updated_at=now() WHERE id=%s", (rid,))
    execute("UPDATE mesh.products SET lifecycle='Published' WHERE id=%s", (p["id"],))
    execute("UPDATE mesh.product_onboarding SET review_stage='Published', updated_at=now() WHERE product_id=%s", (p["id"],))
    execute("""INSERT INTO mesh.product_states(product_id,env,version,status,quality_score,usage_30d,consumers,trend,freshness_min)
               VALUES (%s,'PROD',%s,'Published',100,0,0,0,0)
               ON CONFLICT (product_id,env) DO UPDATE SET version=EXCLUDED.version, status='Published', updated_at=now()""", (p["id"], r["version"]))
    execute("""INSERT INTO mesh.deployments(object_type,object_name,version,env,status,requested_by,notes)
               VALUES ('Product',%s,%s,'PROD','Succeeded',%s,'Publish execution')""", (p["name"], r["version"], user))
    execute("UPDATE mesh.build_models SET status='Deployed', updated_at=now() WHERE product_id=%s", (p["id"],))
    event("PROD", "Publication", f"Product published: {p['name']} {r['version']}", user)
    return {"published": r["version"]}


@router.get("/releases")
def releases():
    return query("""SELECT r.*, p.name AS product, d.name AS domain FROM mesh.build_releases r JOIN mesh.products p ON p.id=r.product_id
                    JOIN mesh.domains d ON d.id=p.domain_id ORDER BY r.updated_at DESC""")


# ---------------------------------------------------------------- validation center
@router.get("/products/{pid}/validation")
def validation(pid: int, env: str = "PROD"):
    p = _get(pid)
    models = query("SELECT * FROM mesh.build_models WHERE product_id=%s", (pid,))
    pls = query("SELECT * FROM mesh.pipelines WHERE product_id=%s AND env=%s", (pid, env))
    dashboards = one("SELECT count(*) AS n FROM mesh.consumers WHERE product_id=%s AND kind='Dashboard'", (pid,))["n"]
    tables = [m for m in models if m["kind"] in ("Table", "Fact", "Dimension")]
    views = [m for m in models if m["kind"] == "View"]
    policies = [p["classification"], p["retention_policy"], p["access_policy"]]
    artifacts = [
        ("Tables", len(tables), sum(m["status"] == "Deployed" for m in tables)),
        ("Views", len(views), sum(m["status"] == "Deployed" for m in views)),
        ("Pipelines", max(1, len(pls)), len(pls)),
        ("Jobs", len(pls), sum(x["status"] != "Failed" for x in pls)),
        ("Dashboards", dashboards, dashboards),
        ("Contracts", len(p["contracts"]), sum(c["status"] == "Active" for c in p["contracts"])),
        ("Policies", 3, sum(bool(x) for x in policies)),
    ]
    artifacts = [{"type": t, "expected": e, "published": n, "status": "Passed" if n >= e else "Failed"} for t, e, n in artifacts]

    approved = (p["schema_def"] or {}).get("columns", [])
    snap = one("SELECT schema_cols FROM mesh.build_schema_snapshots WHERE product_id=%s AND env=%s", (pid, env))
    published = {c["name"]: c["type"] for c in (snap["schema_cols"] if snap else [])}
    schema = []
    for c in approved:
        pub = published.get(c["name"])
        status = "Missing" if pub is None else "Type Changed" if pub != c["type"] else "Match"
        schema.append({"column": c["name"], "approved": c["type"], "published": pub, "status": status})
    schema += [{"column": n, "approved": None, "published": t, "status": "Unexpected"} for n, t in published.items() if n not in {c["name"] for c in approved}]

    rules = query("SELECT * FROM mesh.quality_rules WHERE product_id=%s AND env=%s", (pid, env))
    critical = [r for r in rules if r["status"] == "Fail"]
    sources = (p["schema_def"] or {}).get("sources") or []
    up = query("SELECT p.name FROM mesh.lineage l JOIN mesh.products p ON p.id=l.src_product_id WHERE l.dst_product_id=%s", (pid,))
    down = query("SELECT p.name FROM mesh.lineage l JOIN mesh.products p ON p.id=l.dst_product_id WHERE l.src_product_id=%s", (pid,))
    threshold = float((one("SELECT value FROM mesh.platform_config WHERE setting='quality_threshold'") or {"value": 95})["value"])
    return {
        "product": {k: p[k] for k in ("id", "name", "domain", "lifecycle")}, "env": env, "has_snapshot": bool(snap),
        "artifacts": artifacts, "artifacts_status": "Passed" if all(a["status"] == "Passed" for a in artifacts) else "Failed",
        "schema": schema, "schema_status": "No snapshot" if not snap else "Passed" if all(s["status"] == "Match" for s in schema) else "Drift Detected",
        "data": query("SELECT * FROM mesh.build_data_checks WHERE product_id=%s AND env=%s ORDER BY id", (pid, env)),
        "quality": {"active": len(rules), "thresholds_met": sum(r["pass_rate"] >= 95 for r in rules), "critical": critical, "rules": rules,
                    "status": "Passed" if rules and not critical else "Failed" if rules else "No rules"},
        "lineage": {"sources": sources, "transformations": [{"name": x["name"], "engine": x["engine"], "layers": x["layers"]} for x in pls],
                    "upstream": [u["name"] for u in up], "downstream": [d["name"] for d in down],
                    "status": "Passed" if sources and pls else "Failed"},
        "certification": {"status": p["cert_status"], "level": p["cert_level"], "compliant": p["compliant"], "quality": p["quality"], "threshold": threshold,
                          "result": "Passed" if p["cert_status"] == "Certified" and p["compliant"] and (p["quality"] or 0) >= threshold else "Failed"},
    }


@router.post("/products/{pid}/validation/reconcile")
def reconcile(pid: int, request: Request, body: dict = Body(...)):
    p = _get(pid)
    env = body.get("env", "PROD")
    failed = one("SELECT count(*) AS n FROM mesh.pipelines WHERE product_id=%s AND env=%s AND status='Failed'", (pid, env))["n"]
    if not failed:
        execute("UPDATE mesh.build_data_checks SET target_value=source_value, status='Passed', checked_at=now() WHERE product_id=%s AND env=%s", (pid, env))
    else:
        execute("UPDATE mesh.build_data_checks SET checked_at=now() WHERE product_id=%s AND env=%s", (pid, env))
    event(env, "Validation", f"Reconciliation for {p['name']}: {'passed' if not failed else 'blocked by failed pipeline'}", user_of(request))
    return {"reconciled": not failed}


# ---------------------------------------------------------------- IAM validation
@router.get("/products/{pid}/iam")
def iam(pid: int, env: str = "PROD"):
    p = _get(pid)
    dom = one("SELECT * FROM mesh.domains WHERE id=%s", (p["domain_id"],))
    grants = query("SELECT * FROM mesh.access_grants WHERE product_id=%s AND env=%s", (pid, env))
    members = query("SELECT * FROM mesh.group_members")
    consumer_groups = [g["principal"] for g in grants if g["principal_type"] == "Group" and g["role"] == "Reader"]
    eng = f"sp-{p['domain'].lower()}-etl"

    def row(party, principal, required, exact=False):
        eff = _effective(grants, members, principal) if principal else None
        rank, need = ROLE_RANK.get(eff, 0), ROLE_RANK[required]
        status = "Failed" if rank < need else "Over-privileged" if exact and rank > need else "Passed"
        return {"party": party, "principal": principal, "required": required, "effective": eff, "status": status}

    access = [row("Product Owner", p["owner"], "Contributor"), row("Data Steward", dom["steward"], "Contributor"), row("Data Engineer", eng, "Contributor"),
              {"party": "Consumer Groups", "principal": ", ".join(consumer_groups) or None, "required": "Reader", "effective": "Reader" if consumer_groups else None,
               "status": "Passed" if consumer_groups else "Failed"},
              row("Operations Team", "platform-admins", "Owner")]
    roles = [row("Domain Owner", dom["owner"], "Owner", True), row("Data Product Owner", p["owner"], "Contributor", True),
             {**access[3], "party": "Consumer"}, row("Steward", dom["steward"], "Contributor", True), row("Administrator", "platform-admins", "Owner", True)]

    cols = (p["schema_def"] or {}).get("columns", [])
    pii_cols = [c["name"] for c in cols if c.get("pii")]
    sensitive = p["classification"] in SENSITIVE
    controls = query("SELECT * FROM mesh.security_controls")
    mine = [c for c in controls if p["name"] in c["target"] and c["status"] == "Enforced"]
    tag_based = [c for c in controls if c["kind"] == "ABAC" and c["status"] == "Enforced"]

    def sec(name, required, found, detail):
        return {"control": name, "required": required, "found": found, "detail": detail,
                "status": "Not Required" if not required else "Enforced" if found else "Missing"}

    security = [sec("Row-level security", sensitive, any(c["kind"] == "Row Security" for c in mine), "Row filter on product table"),
                sec("Column-level security", bool(pii_cols), any(c["kind"] == "Column Security" for c in mine), f"PII columns: {', '.join(pii_cols) or 'none'}"),
                sec("Masking rules", bool(pii_cols), any("mask" in c["rule"].lower() for c in mine) or bool(tag_based), "Column masks / tag-based masking"),
                sec("Sensitive data controls", sensitive, bool(tag_based), f"Classification {p['classification'] or 'unclassified'}")]
    rows = _checks(pid)
    consumer = [{"test": t, "status": rows[("consumer", t)]["status"] if ("consumer", t) in rows else "Not Run",
                 "detail": rows[("consumer", t)]["note"] if ("consumer", t) in rows else "", "checked_at": rows[("consumer", t)]["checked_at"] if ("consumer", t) in rows else None}
                for t in CONSUMER_TESTS]
    policies = [_auto("Retention Policy", bool(p["retention_policy"]), p["retention_policy"] or "Not attached"),
                _auto("Classification Policy", bool(p["classification"]), p["classification"] or "Not attached"),
                _auto("Sharing Policy", bool(p["access_policy"]), p["access_policy"] or "Not attached"),
                _auto("Compliance Policy", p["compliant"], "Metadata, contract and security complete" if p["compliant"] else "Product readiness incomplete")]
    signoffs = [_manual(rows, "signoff", s) for s in SIGNOFFS]
    ready = (all(a["status"] == "Passed" for a in access) and all(r["status"] != "Failed" for r in roles)
             and all(s["status"] != "Missing" for s in security) and all(c["status"] == "Passed" for c in consumer)
             and all(x["status"] == "Passed" for x in policies) and all(s["status"] == "Passed" for s in signoffs))
    return {"product": {k: p[k] for k in ("id", "name", "domain", "owner", "classification")}, "env": env, "access": access, "roles": roles,
            "security": security, "consumer": consumer, "policies": policies, "signoffs": signoffs,
            "handover": "Ready for Operate handover" if ready else "Not ready"}


@router.post("/products/{pid}/iam/grant")
def iam_grant(pid: int, request: Request, body: dict = Body(...)):
    p = _get(pid)
    principal, role, env = (body.get("principal") or "").strip(), body.get("role"), body.get("env", "PROD")
    if not principal or role not in ROLE_RANK or env not in ENVS:
        raise HTTPException(400, "principal, role (Reader/Contributor/Owner) and env are required")
    user = user_of(request)
    execute("INSERT INTO mesh.access_grants(principal,principal_type,product_id,env,role) VALUES (%s,%s,%s,%s,%s)",
            (principal, body.get("principal_type") or "User", pid, env, role))
    execute("INSERT INTO mesh.access_audit(principal,action,object_name,env,detail) VALUES (%s,'GRANT',%s,%s,%s)",
            (principal, p["name"], env, f"{role} granted by {user} (IAM validation)"))
    event(env, "Security", f"{role} on {p['name']} granted to {principal}", user)
    return {"ok": True}


@router.post("/products/{pid}/iam/consumer-tests")
def consumer_tests(pid: int, request: Request, body: dict = Body(...)):
    p = _get(pid)
    env = body.get("env", "PROD")
    grants = query("SELECT * FROM mesh.access_grants WHERE product_id=%s AND env=%s", (pid, env))
    pii = [c["name"] for c in (p["schema_def"] or {}).get("columns", []) if c.get("pii")]
    masked = any(c["status"] == "Enforced" and (c["kind"] == "ABAC" or (p["name"] in c["target"] and "mask" in c["rule"].lower()))
                 for c in query("SELECT * FROM mesh.security_controls"))
    reader = next((g["principal"] for g in grants if g["role"] in ROLE_RANK), None)
    results = {
        CONSUMER_TESTS[0]: (bool(reader), f"SELECT as {reader}: success" if reader else "No authorized principal found"),
        CONSUMER_TESTS[1]: (not any(g["principal"] == UNAUTHORIZED_PROBE for g in grants), f"SELECT as {UNAUTHORIZED_PROBE}: permission denied"),
        CONSUMER_TESTS[2]: (masked or not pii, f"{', '.join(pii)} returned masked" if pii and masked else "PII columns not masked" if pii else "No restricted columns"),
    }
    user = user_of(request)
    for test, (ok, note) in results.items():
        execute("""INSERT INTO mesh.build_checks(product_id,area,item,status,checked_by,note) VALUES (%s,'consumer',%s,%s,%s,%s)
                   ON CONFLICT (product_id,area,item) DO UPDATE SET status=EXCLUDED.status, checked_by=EXCLUDED.checked_by,
                   note=EXCLUDED.note, checked_at=now()""", (pid, test, "Passed" if ok else "Failed", user, note))
    event(env, "Validation", f"Consumer access tests for {p['name']}: {sum(ok for ok, _ in results.values())}/3 passed", user)
    return {t: ("Passed" if ok else "Failed") for t, (ok, _) in results.items()}

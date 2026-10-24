"""Data Mesh Control Plane - FastAPI State API over Lakebase or local SQLite."""
import os
import logging
import threading
import datetime as dt
from typing import Optional, List

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Body, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import db
import ops
import mgmt
import build
from db import query, one, execute, Json
from ops import user_of, event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("mesh.app")

HERE = os.path.dirname(os.path.abspath(__file__))
REGIONS = [{"code": "canadacentral", "name": "Canada Central"}, {"code": "eastus", "name": "East US"},
           {"code": "westeurope", "name": "Europe West"}]
STATE_SOURCES = ["Lakebase", "Databricks Catalog"]
LIFECYCLE = ["Draft", "Review", "Approved", "Published", "Retired"]
ENV_ORDER = ["DEV", "SIT", "UAT", "PROD"]

DB_STATE = {"status": "initializing", "error": None, "backend": db.BACKEND}


def _init():
    if not db.configured():
        DB_STATE.update(status="not_configured", error="Lakebase resource not attached (PGHOST / LAKEBASE_ENDPOINT missing)")
        log.error(DB_STATE["error"])
        return
    try:
        from seed import init_db
        DB_STATE.update(status="ready", seed=init_db())
        log.info("State store ready on %s: %s", db.describe(), DB_STATE)
    except Exception as ex:  # noqa
        log.exception("State store init failed")
        DB_STATE.update(status="error", error=str(ex))


app = FastAPI(title="Data Mesh Control Plane", version="1.0")


@app.on_event("startup")
def startup():
    threading.Thread(target=_init, daemon=True).start()


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    log.exception("API error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


def require_db():
    if DB_STATE["status"] != "ready":
        raise HTTPException(503, f"State store {DB_STATE['status']}: {DB_STATE.get('error') or 'please retry shortly'}")


app.include_router(ops.router, dependencies=[Depends(require_db)])
app.include_router(mgmt.router, dependencies=[Depends(require_db)])
app.include_router(build.router, dependencies=[Depends(require_db)])


# ---------------------------------------------------------------- context
@app.get("/api/health")
def health():
    return DB_STATE


@app.get("/api/context")
def get_context(request: Request):
    require_db()
    user = user_of(request)
    prefs = one("SELECT env, region, state_source FROM mesh.user_prefs WHERE user_email=%s", (user,)) or \
        {"env": "PROD", "region": "canadacentral", "state_source": "Lakebase"}
    envs = query("SELECT * FROM mesh.environments ORDER BY tier DESC")
    notif = one("""SELECT (SELECT count(*) FROM mesh.approvals WHERE status='Pending') AS approvals,
                          (SELECT count(*) FROM mesh.incidents WHERE status<>'Resolved') AS incidents""")
    return {"user": user, "prefs": prefs, "environments": envs, "regions": REGIONS, "state_sources": STATE_SOURCES,
            "notifications": notif, "lakebase_endpoint": os.environ.get("LAKEBASE_ENDPOINT")}


@app.put("/api/context")
def put_context(request: Request, body: dict = Body(...)):
    require_db()
    execute("""INSERT INTO mesh.user_prefs(user_email, env, region, state_source, updated_at) VALUES (%s,%s,%s,%s,now())
               ON CONFLICT (user_email) DO UPDATE SET env=EXCLUDED.env, region=EXCLUDED.region,
               state_source=EXCLUDED.state_source, updated_at=now()""",
            (user_of(request), body.get("env", "PROD"), body.get("region", "canadacentral"), body.get("state_source", "Lakebase")))
    return {"ok": True}


# ---------------------------------------------------------------- home / command center
@app.get("/api/home")
def home(env: str = "PROD"):
    require_db()
    ov = one("""
      SELECT (SELECT count(*) FROM mesh.domains) AS domains,
             (SELECT count(*) FROM mesh.product_states WHERE env=%(e)s) AS products,
             (SELECT count(*) FROM mesh.pipelines WHERE env=%(e)s AND status='Running') AS active_pipelines,
             (SELECT count(*) FROM mesh.pipelines WHERE env=%(e)s) AS total_pipelines,
             (SELECT count(*) FROM mesh.pipelines WHERE env=%(e)s AND status='Failed') AS failed_pipelines,
             (SELECT round(avg(quality_score)::numeric,1)::float FROM mesh.domain_states WHERE env=%(e)s) AS quality_score,
             (SELECT round(avg(governance_score)::numeric,1)::float FROM mesh.domain_states WHERE env=%(e)s) AS governance_score,
             (SELECT round(sum(storage_tb)::numeric,1)::float FROM mesh.domain_states WHERE env=%(e)s) AS storage_tb,
             (SELECT sum(compute_dbu)::float FROM mesh.domain_states WHERE env=%(e)s) AS compute_dbu,
             (SELECT sum(rows_per_hour)::bigint FROM mesh.pipelines WHERE env=%(e)s AND status<>'Failed') AS throughput,
             (SELECT round(avg(freshness_min)::numeric,0)::float FROM mesh.product_states WHERE env=%(e)s) AS freshness_min,
             (SELECT count(*) FROM mesh.incidents WHERE env=%(e)s AND status<>'Resolved') AS incidents,
             (SELECT health FROM mesh.environments WHERE code=%(e)s) AS env_health
    """, {"e": env})
    ov["sla"] = round(100.0 * (ov["total_pipelines"] - ov["failed_pipelines"]) / max(ov["total_pipelines"], 1), 1)
    domains = query("""SELECT d.id, d.name, s.health, s.quality_score, s.governance_score, d.owner,
                         (SELECT count(*) FROM mesh.products p JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%(e)s WHERE p.domain_id=d.id) AS products
                       FROM mesh.domains d LEFT JOIN mesh.domain_states s ON s.domain_id=d.id AND s.env=%(e)s ORDER BY d.id""", {"e": env})
    events = query("SELECT * FROM mesh.events WHERE env=%s ORDER BY created_at DESC LIMIT 14", (env,))
    execk = one("""SELECT round(avg(p.days_to_create)::numeric,1)::float AS time_to_product_days,
                     round(100.0*avg(CASE WHEN ps.consumers>0 THEN 1 ELSE 0 END)::numeric,1)::float AS adoption_pct,
                     sum(ps.usage_30d)::bigint AS usage_30d
                   FROM mesh.products p JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s""", (env,))
    cost_dom = query("""SELECT d.name, c.amount FROM mesh.cost_monthly c JOIN mesh.domains d ON d.id=c.domain_id
                        WHERE c.env=%(e)s AND c.month=(SELECT max(month) FROM mesh.cost_monthly WHERE env=%(e)s) ORDER BY c.amount DESC""", {"e": env})
    cost_trend = query("SELECT month, sum(amount)::float AS amount FROM mesh.cost_monthly WHERE env=%s GROUP BY month ORDER BY month", (env,))
    approvals = query("SELECT * FROM mesh.approvals WHERE env=%s AND status='Pending' ORDER BY created_at DESC LIMIT 6", (env,))
    failed = query("SELECT * FROM mesh.deployments WHERE env=%s AND status IN ('Failed','Rolled Back') ORDER BY created_at DESC LIMIT 6", (env,))
    changes = query("SELECT * FROM mesh.deployments WHERE env=%s ORDER BY created_at DESC LIMIT 6", (env,))
    top = query("""SELECT p.id, p.name, d.name AS domain, ps.usage_30d, ps.consumers, ps.trend, p.certified
                   FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s
                   ORDER BY ps.usage_30d DESC LIMIT 6""", (env,))
    return {"overview": ov, "domains": domains, "events": events, "exec": {**execk, "sla": ov["sla"], "cost_per_domain": cost_dom},
            "cost_trend": cost_trend, "pending_approvals": approvals, "failed_deployments": failed,
            "recent_changes": changes, "top_products": top}


# ---------------------------------------------------------------- discover
@app.get("/api/domains")
def list_domains():
    require_db()
    return query("SELECT * FROM mesh.domains ORDER BY id")


@app.get("/api/products")
def list_products(env: str = "PROD", q: Optional[str] = None, domains: Optional[str] = None, certified: Optional[bool] = None):
    require_db()
    sql = """SELECT p.id, p.name, p.description, p.owner, p.certified, p.lifecycle, p.sla, p.tags, d.name AS domain,
                    ps.version, ps.status, ps.quality_score, ps.usage_30d, ps.consumers, ps.trend
             FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id
             JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%(e)s WHERE 1=1"""
    params = {"e": env}
    if q:
        # lightweight semantic search: match name, description, tags, column names and glossary terms
        sql += """ AND (p.name ILIKE %(q)s OR p.description ILIKE %(q)s OR d.name ILIKE %(q)s OR array_to_string(p.tags,' ') ILIKE %(q)s
                     OR p.schema_def::text ILIKE %(q)s
                     OR d.id IN (SELECT domain_id FROM mesh.glossary WHERE term ILIKE %(q)s OR definition ILIKE %(q)s))"""
        params["q"] = f"%{q}%"
    if domains:
        sql += " AND d.name = ANY(%(d)s)"
        params["d"] = domains.split(",")
    if certified is not None:
        sql += " AND p.certified = %(c)s"
        params["c"] = certified
    return query(sql + " ORDER BY ps.usage_30d DESC", params)


@app.get("/api/products/{pid}")
def product_detail(pid: int, env: str = "PROD"):
    require_db()
    p = one("""SELECT p.*, d.name AS domain, d.steward, d.custodian FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id WHERE p.id=%s""", (pid,))
    if not p:
        raise HTTPException(404, "Product not found")
    p["states"] = query("SELECT * FROM mesh.product_states WHERE product_id=%s ORDER BY array_position(ARRAY['DEV','SIT','UAT','PROD'], env)", (pid,))
    p["upstream"] = query("""SELECT p.id, p.name, d.name AS domain, l.kind FROM mesh.lineage l JOIN mesh.products p ON p.id=l.src_product_id
                             JOIN mesh.domains d ON d.id=p.domain_id WHERE l.dst_product_id=%s""", (pid,))
    p["downstream"] = query("""SELECT p.id, p.name, d.name AS domain, l.kind FROM mesh.lineage l JOIN mesh.products p ON p.id=l.dst_product_id
                               JOIN mesh.domains d ON d.id=p.domain_id WHERE l.src_product_id=%s""", (pid,))
    p["quality"] = query("SELECT * FROM mesh.quality_rules WHERE product_id=%s AND env=%s ORDER BY dimension", (pid, env))
    p["contracts"] = query("""SELECT c.*, d.name AS consumer_domain FROM mesh.contracts c LEFT JOIN mesh.domains d ON d.id=c.consumer_domain_id
                              WHERE c.product_id=%s ORDER BY c.kind""", (pid,))
    p["pipelines"] = query("SELECT * FROM mesh.pipelines WHERE product_id=%s ORDER BY array_position(ARRAY['DEV','SIT','UAT','PROD'], env)", (pid,))
    p["access_requests"] = query("SELECT * FROM mesh.approvals WHERE product_id=%s AND kind='Access' ORDER BY created_at DESC LIMIT 10", (pid,))
    return p


@app.get("/api/glossary")
def glossary():
    require_db()
    return query("SELECT g.*, d.name AS domain FROM mesh.glossary g LEFT JOIN mesh.domains d ON d.id=g.domain_id ORDER BY term")


@app.get("/api/insights")
def insights(env: str = "PROD"):
    require_db()
    most_used = query("""SELECT p.id, p.name, d.name AS domain, ps.usage_30d FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id
                         JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s ORDER BY ps.usage_30d DESC LIMIT 5""", (env,))
    trending = query("""SELECT p.id, p.name, d.name AS domain, ps.trend FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id
                        JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s ORDER BY ps.trend DESC LIMIT 5""", (env,))
    by_domain = query("""SELECT d.name AS domain, sum(ps.usage_30d)::bigint AS usage, sum(ps.consumers)::int AS consumers
                         FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%s
                         GROUP BY d.name ORDER BY usage DESC""", (env,))
    return {"most_used": most_used, "trending": trending, "by_domain": by_domain}


@app.post("/api/access-requests")
def request_access(request: Request, body: dict = Body(...)):
    require_db()
    p = one("SELECT id, name FROM mesh.products WHERE id=%s", (body["product_id"],))
    user = user_of(request)
    r = one("""INSERT INTO mesh.approvals(kind,object_name,product_id,env,requester,justification,status)
               VALUES ('Access',%s,%s,%s,%s,%s,'Pending') RETURNING *""",
            (p["name"], p["id"], body.get("env", "PROD"), user, body.get("justification", "")))
    event(body.get("env", "PROD"), "Approval", f"Access requested on {p['name']} by {user}", user)
    return r


@app.get("/api/approvals")
def approvals(request: Request, env: Optional[str] = None, status: Optional[str] = None, mine: bool = False):
    require_db()
    sql, params = "SELECT * FROM mesh.approvals WHERE 1=1", []
    if env:
        sql += " AND env=%s"; params.append(env)
    if status:
        sql += " AND status=%s"; params.append(status)
    if mine:
        sql += " AND requester=%s"; params.append(user_of(request))
    return query(sql + " ORDER BY created_at DESC LIMIT 100", params)


@app.post("/api/approvals/{aid}/decision")
def decide(aid: int, request: Request, body: dict = Body(...)):
    require_db()
    decision = body.get("decision")
    if decision not in ("Approved", "Rejected"):
        raise HTTPException(400, "decision must be Approved or Rejected")
    user = user_of(request)
    a = one("UPDATE mesh.approvals SET status=%s, decided_by=%s, decided_at=now() WHERE id=%s RETURNING *", (decision, user, aid))
    if not a:
        raise HTTPException(404, "Approval not found")
    if a and decision == "Approved" and a["kind"] == "Publish" and a["product_id"]:
        execute("UPDATE mesh.products SET lifecycle='Published' WHERE id=%s", (a["product_id"],))
        event(a["env"], "Publication", f"Product published: {a['object_name']}", user)
    if a and decision == "Approved" and a["kind"] == "Deployment":
        execute("UPDATE mesh.deployments SET status='Succeeded' WHERE env=%s AND status='Pending' AND %s LIKE object_name || '%%'", (a["env"], a["object_name"]))
    event(a["env"], "Approval", f"{a['kind']} request {decision.lower()}: {a['object_name']}", user)
    return a


# ---------------------------------------------------------------- topology
@app.get("/api/topology")
def topology(env: str = "PROD"):
    require_db()
    doms = query("""SELECT d.id, d.name, s.health FROM mesh.domains d LEFT JOIN mesh.domain_states s ON s.domain_id=d.id AND s.env=%s ORDER BY d.id""", (env,))
    prods = query("""SELECT p.id, p.name, p.domain_id, p.certified, ps.version, ps.quality_score,
                       (SELECT count(*) FROM mesh.contracts c WHERE c.product_id=p.id) AS contracts,
                       (SELECT health FROM mesh.pipelines pl WHERE pl.product_id=p.id AND pl.env=%(e)s LIMIT 1) AS pipeline_health
                     FROM mesh.products p LEFT JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%(e)s ORDER BY p.domain_id, p.id""", {"e": env})
    edges = query("SELECT src_product_id AS source, dst_product_id AS target, kind FROM mesh.lineage")
    return {"domains": doms, "products": prods, "edges": edges}


# ---------------------------------------------------------------- build
@app.post("/api/domains")
def create_domain(request: Request, body: dict = Body(...)):
    require_db()
    d = one("""INSERT INTO mesh.domains(name,description,owner,steward,custodian) VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (body["name"], body.get("description", ""), body.get("owner"), body.get("steward"), body.get("custodian")))
    for e in ENV_ORDER:
        execute("INSERT INTO mesh.domain_states(domain_id,env,health,quality_score,governance_score,storage_tb,compute_dbu,freshness_min) VALUES (%s,%s,'Healthy',100,100,0,0,0)", (d["id"], e))
    event("PROD", "Domain", f"Domain created: {d['name']}", user_of(request))
    return d


@app.put("/api/domains/{did}")
def update_domain(did: int, request: Request, body: dict = Body(...)):
    require_db()
    d = one("UPDATE mesh.domains SET owner=%s, steward=%s, custodian=%s WHERE id=%s RETURNING *",
            (body.get("owner"), body.get("steward"), body.get("custodian"), did))
    event("PROD", "Domain", f"Domain roles updated: {d['name']}", user_of(request))
    return d


@app.post("/api/products")
def create_product(request: Request, body: dict = Body(...)):
    require_db()
    user = user_of(request)
    if one("SELECT 1 AS x FROM mesh.products WHERE name=%s", (body["name"],)):
        raise HTTPException(409, "A product with this name already exists")
    lifecycle = "Review" if body.get("publish") else "Draft"
    schema_def = {"sources": body.get("sources", []), "columns": body.get("columns", [])}
    p = one("""INSERT INTO mesh.products(name,domain_id,description,owner,certified,lifecycle,sla,tags,schema_def,days_to_create)
               VALUES (%s,%s,%s,%s,false,%s,%s,%s,%s,1) RETURNING *""",
            (body["name"], body["domain_id"], body.get("description", ""), body.get("owner") or user, lifecycle,
             body.get("sla", "Daily"), body.get("tags", []), Json(schema_def)))
    execute("INSERT INTO mesh.product_states VALUES (%s,'DEV','v0.1','Draft',100,0,0,0,0,now())", (p["id"],))
    execute("INSERT INTO mesh.contracts(name,product_id,kind,status,version,spec) VALUES (%s,%s,'Schema','Draft','0.1',%s)",
            (f"{p['name']}-schema", p["id"], Json({"columns": [c.get("name") for c in schema_def["columns"]]})))
    execute("INSERT INTO mesh.state_objects(object_type,name,env,current_state,desired_state,status) VALUES ('Product',%s,'DEV','absent','v0.1','Pending')", (p["name"],))
    if body.get("publish"):
        execute("INSERT INTO mesh.approvals(kind,object_name,product_id,env,requester,justification,status) VALUES ('Publish',%s,%s,'DEV',%s,'Wizard publish request','Pending')",
                (p["name"], p["id"], user))
    event("DEV", "Product", f"Data product created: {p['name']} ({lifecycle})", user)
    return p


@app.get("/api/contracts")
def list_contracts(product_id: Optional[int] = None):
    require_db()
    sql = """SELECT c.*, p.name AS product, d.name AS consumer_domain FROM mesh.contracts c JOIN mesh.products p ON p.id=c.product_id
             LEFT JOIN mesh.domains d ON d.id=c.consumer_domain_id"""
    if product_id:
        return query(sql + " WHERE c.product_id=%s ORDER BY c.created_at DESC", (product_id,))
    return query(sql + " ORDER BY c.created_at DESC LIMIT 200")


@app.post("/api/contracts")
def create_contract(request: Request, body: dict = Body(...)):
    require_db()
    p = one("SELECT * FROM mesh.products WHERE id=%s", (body["product_id"],))
    kind = body.get("kind", "Producer")
    spec = {"sla": body.get("sla"), "freshness_minutes": body.get("freshness_minutes"), "completeness": body.get("completeness"),
            "columns": [c["name"] for c in (p["schema_def"] or {}).get("columns", [])], "terms": body.get("terms")}
    c = one("""INSERT INTO mesh.contracts(name,product_id,kind,consumer_domain_id,status,version,spec)
               VALUES (%s,%s,%s,%s,'Draft','1.0',%s) RETURNING *""",
            (body.get("name") or f"{p['name']}-{kind.lower()}-{dt.datetime.now():%H%M%S}", p["id"], kind, body.get("consumer_domain_id"), Json(spec)))
    event("DEV", "Contract", f"{kind} contract created: {c['name']}", user_of(request))
    return c


@app.get("/api/pipelines")
def list_pipelines(env: str = "PROD"):
    require_db()
    return query("""SELECT pl.*, p.name AS product, d.name AS domain FROM mesh.pipelines pl JOIN mesh.products p ON p.id=pl.product_id
                    JOIN mesh.domains d ON d.id=p.domain_id WHERE pl.env=%s ORDER BY pl.status, pl.name""", (env,))


@app.post("/api/pipelines")
def create_pipeline(request: Request, body: dict = Body(...)):
    require_db()
    pl = one("""INSERT INTO mesh.pipelines(name,product_id,env,engine,status,health,layers,last_run,duration_min,rows_per_hour,latency_min)
                VALUES (%s,%s,%s,%s,'Queued','Healthy',%s,NULL,0,0,0) RETURNING *""",
             (body["name"], body["product_id"], body.get("env", "DEV"), body.get("engine", "Lakeflow SDP"),
              Json(body.get("layers", ["Source", "Bronze", "Silver", "Gold", "Product"]))))
    execute("INSERT INTO mesh.state_objects(object_type,name,env,current_state,desired_state,status) VALUES ('Pipeline',%s,%s,'absent','Running','Pending')",
            (pl["name"], pl["env"]))
    event(pl["env"], "Pipeline", f"Pipeline designed: {pl['name']} ({pl['engine']})", user_of(request))
    return pl


@app.post("/api/pipelines/{plid}/rerun")
def rerun_pipeline(plid: int, request: Request):
    require_db()
    pl = one("UPDATE mesh.pipelines SET status='Running', health='Healthy', last_run=now() WHERE id=%s RETURNING *", (plid,))
    event(pl["env"], "Pipeline", f"Pipeline re-run triggered: {pl['name']}", user_of(request))
    return pl


def _cols(p):
    return (p.get("schema_def") or {}).get("columns") or [{"name": "id", "type": "BIGINT"}]


@app.post("/api/generate")
def generate(body: dict = Body(...)):
    """AI-assisted build: template-driven code generation from Lakebase product metadata."""
    require_db()
    p = one("SELECT p.*, d.name AS domain FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id WHERE p.id=%s", (body["product_id"],))
    kind = body.get("kind", "sql")
    cols = _cols(p)
    dom = p["domain"].lower()
    tbl = p["name"].lower()
    src = ((p["schema_def"] or {}).get("sources") or ["source.raw"])[0]
    names = ", ".join(c["name"] for c in cols)
    if kind == "sql":
        code = (f"-- Gold table for data product {p['name']}\nCREATE OR REPLACE TABLE {dom}.gold.{tbl} AS\nSELECT\n  "
                + ",\n  ".join(c["name"] for c in cols) + f"\nFROM {dom}.silver.{tbl}_clean\nWHERE business_date >= date_sub(current_date(), 365);")
    elif kind == "pyspark":
        code = (f"from pyspark.sql import functions as F\n\nbronze = spark.read.table(\"{src}\")\n"
                f"silver = (bronze.dropDuplicates([\"{cols[0]['name']}\"])\n          .withColumn(\"_updated_at\", F.current_timestamp()))\n"
                f"silver.write.mode(\"overwrite\").saveAsTable(\"{dom}.silver.{tbl}_clean\")\n\n"
                f"gold = spark.read.table(\"{dom}.silver.{tbl}_clean\").select({', '.join(repr(c['name']) for c in cols)})\n"
                f"gold.write.mode(\"overwrite\").saveAsTable(\"{dom}.gold.{tbl}\")")
    elif kind == "dbt":
        code = (f"-- models/{dom}/gold/{tbl}.sql\n{{{{ config(materialized='table', tags=['data_product','{dom}']) }}}}\n\n"
                f"select {names}\nfrom {{{{ ref('{tbl}_clean') }}}}\n\n"
                f"# models/{dom}/gold/schema.yml\nversion: 2\nmodels:\n  - name: {tbl}\n    columns:\n"
                + "\n".join(f"      - name: {c['name']}\n        tests: [not_null]" if not c.get("nullable", True) else f"      - name: {c['name']}" for c in cols))
    elif kind == "contract":
        code = (f"apiVersion: v3.0.0\nkind: DataContract\nid: {tbl}\nname: {p['name']}\ndomain: {p['domain']}\nowner: {p['owner']}\n"
                f"status: {p['lifecycle'].lower()}\nsla:\n  freshness: {p['sla']}\n  completeness: '>= 99%'\nschema:\n  - name: {tbl}\n    properties:\n"
                + "\n".join(f"      - name: {c['name']}\n        logicalType: {c['type'].lower()}\n        required: {str(not c.get('nullable', True)).lower()}"
                            + ("\n        classification: pii" if c.get("pii") else "") for c in cols))
    else:
        code = (f"# {p['name']}\n\n{p['description']}\n\n* Domain: {p['domain']}\n* Owner: {p['owner']}\n* SLA: {p['sla']}\n"
                f"* Lifecycle: {p['lifecycle']}\n* Certified: {'Yes' if p['certified'] else 'No'}\n\n## Schema\n\n| Column | Type | Description | PII |\n|---|---|---|---|\n"
                + "\n".join(f"| {c['name']} | {c['type']} | {c.get('description', '')} | {'Yes' if c.get('pii') else 'No'} |" for c in cols))
    return {"kind": kind, "code": code}


@app.get("/api/deployments")
def deployments(env: Optional[str] = None):
    require_db()
    if env:
        return query("SELECT * FROM mesh.deployments WHERE env=%s ORDER BY created_at DESC LIMIT 100", (env,))
    return query("SELECT * FROM mesh.deployments ORDER BY created_at DESC LIMIT 100")


@app.post("/api/deployments")
def deploy(request: Request, body: dict = Body(...)):
    require_db()
    user = user_of(request)
    target = body["target_env"]
    gated = target == "PROD"
    status = "Pending" if gated else "Succeeded"
    d = one("""INSERT INTO mesh.deployments(object_type,object_name,version,env,status,requested_by,notes)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (body["object_type"], body["object_name"], body["version"], target, status, user, body.get("notes", "Deployment Hub")))
    existing = one("SELECT id FROM mesh.state_objects WHERE env=%s AND name=%s AND object_type=%s", (target, body["object_name"], body["object_type"]))
    if existing:
        if gated:
            execute("UPDATE mesh.state_objects SET desired_state=%s, status='Pending', updated_at=now() WHERE id=%s", (body["version"], existing["id"]))
        else:
            execute("UPDATE mesh.state_objects SET desired_state=%s, current_state=%s, status='Synced', updated_at=now() WHERE id=%s",
                    (body["version"], body["version"], existing["id"]))
    else:
        execute("INSERT INTO mesh.state_objects(object_type,name,env,current_state,desired_state,status) VALUES (%s,%s,%s,%s,%s,%s)",
                (body["object_type"], body["object_name"], target, "absent" if gated else body["version"], body["version"], "Pending" if gated else "Synced"))
    if body["object_type"] == "Product" and not gated:
        execute("""INSERT INTO mesh.product_states(product_id,env,version,status,quality_score,usage_30d,consumers,trend,freshness_min)
                   SELECT id,%s,%s,'Staged',100,0,0,0,0 FROM mesh.products WHERE name=%s
                   ON CONFLICT (product_id,env) DO UPDATE SET version=EXCLUDED.version, updated_at=now()""", (target, body["version"], body["object_name"]))
    if gated:
        execute("""INSERT INTO mesh.approvals(kind,object_name,product_id,env,requester,justification,status)
                   VALUES ('Deployment',%s,(SELECT id FROM mesh.products WHERE name=%s),%s,%s,'Production release gate','Pending')""",
                (f"{body['object_name']} {body['version']}", body["object_name"], target, user))
    event(target, "Deployment", f"Deployment {status.lower()}: {body['object_name']} {body['version']} to {target}", user)
    return d


@app.post("/api/deployments/{did}/rollback")
def rollback(did: int, request: Request):
    require_db()
    d = one("UPDATE mesh.deployments SET status='Rolled Back' WHERE id=%s RETURNING *", (did,))
    event(d["env"], "Deployment", f"Rolled back: {d['object_name']} {d['version']}", user_of(request))
    return d


# ---------------------------------------------------------------- operate
@app.get("/api/operate")
def operate(env: str = "PROD"):
    require_db()
    counts = query("SELECT status, count(*)::int AS n FROM mesh.pipelines WHERE env=%s GROUP BY status", (env,))
    quality = query("SELECT dimension, round(avg(pass_rate)::numeric,1)::float AS score FROM mesh.quality_rules WHERE env=%s GROUP BY dimension ORDER BY dimension", (env,))
    rules = query("""SELECT q.*, p.name AS product FROM mesh.quality_rules q JOIN mesh.products p ON p.id=q.product_id
                     WHERE q.env=%s ORDER BY q.pass_rate ASC LIMIT 15""", (env,))
    rule_summary = query("""SELECT rule, round(avg(pass_rate)::numeric,1)::float AS pass_rate, sum(CASE WHEN status='Fail' THEN 1 ELSE 0 END)::int AS failing
                            FROM mesh.quality_rules WHERE env=%s GROUP BY rule ORDER BY rule""", (env,))
    incidents = query("""SELECT i.*, p.name AS product FROM mesh.incidents i LEFT JOIN mesh.products p ON p.id=i.product_id
                         WHERE i.env=%s ORDER BY CASE i.status WHEN 'Resolved' THEN 1 ELSE 0 END, i.created_at DESC""", (env,))
    cost_domain = query("""SELECT d.name, c.amount FROM mesh.cost_monthly c JOIN mesh.domains d ON d.id=c.domain_id
                           WHERE c.env=%(e)s AND c.month=(SELECT max(month) FROM mesh.cost_monthly WHERE env=%(e)s) ORDER BY c.amount DESC""", {"e": env})
    cost_product = query("""WITH dc AS (SELECT domain_id, amount FROM mesh.cost_monthly WHERE env=%(e)s AND month=(SELECT max(month) FROM mesh.cost_monthly WHERE env=%(e)s)),
                              pu AS (SELECT p.id, p.name, p.domain_id, ps.usage_30d, sum(ps.usage_30d) OVER (PARTITION BY p.domain_id) AS du
                                     FROM mesh.products p JOIN mesh.product_states ps ON ps.product_id=p.id AND ps.env=%(e)s)
                            SELECT pu.name, round((dc.amount * pu.usage_30d / NULLIF(pu.du,0))::numeric,0)::float AS amount
                            FROM pu JOIN dc ON dc.domain_id=pu.domain_id ORDER BY amount DESC NULLS LAST LIMIT 10""", {"e": env})
    cost_env = query("""SELECT env, sum(amount)::float AS amount FROM mesh.cost_monthly WHERE month=(SELECT max(month) FROM mesh.cost_monthly)
                        GROUP BY env ORDER BY array_position(ARRAY['DEV','SIT','UAT','PROD'], env)""")
    cost_trend = query("""SELECT c.month, d.name, c.amount FROM mesh.cost_monthly c JOIN mesh.domains d ON d.id=c.domain_id WHERE c.env=%s ORDER BY c.month""", (env,))
    perf = one("""SELECT round(avg(duration_min)::numeric,1)::float AS avg_duration, round(avg(latency_min)::numeric,1)::float AS avg_latency,
                         sum(rows_per_hour)::bigint AS throughput FROM mesh.pipelines WHERE env=%s""", (env,))
    fresh = one("SELECT round(avg(freshness_min)::numeric,0)::float AS freshness, round(max(freshness_min)::numeric,0)::float AS worst FROM mesh.product_states WHERE env=%s", (env,))
    failed = sum(c["n"] for c in counts if c["status"] == "Failed")
    lat = perf["avg_latency"] or 0
    obs = [
        {"stage": "Source", "status": "Healthy", "metric": "14 systems connected"},
        {"stage": "Ingestion", "status": "Warning" if failed else "Healthy", "metric": f"{round(lat * 0.3, 1)} min latency"},
        {"stage": "Transformation", "status": "Error" if failed > 1 else ("Warning" if failed else "Healthy"), "metric": f"{failed} failed pipelines"},
        {"stage": "Serving", "status": "Healthy", "metric": f"{round(lat * 0.2, 1)} min latency"},
        {"stage": "Consumption", "status": "Warning" if (fresh["worst"] or 0) > 120 else "Healthy", "metric": f"avg freshness {fresh['freshness']} min"},
    ]
    impact = query("""SELECT DISTINCT p2.name AS impacted, p.name AS failed_product FROM mesh.pipelines pl JOIN mesh.products p ON p.id=pl.product_id
                      JOIN mesh.lineage l ON l.src_product_id=p.id JOIN mesh.products p2 ON p2.id=l.dst_product_id
                      WHERE pl.env=%s AND pl.status='Failed'""", (env,))
    return {"counts": counts, "pipelines": list_pipelines(env), "quality": quality, "rules": rules, "rule_summary": rule_summary,
            "incidents": incidents, "cost_domain": cost_domain, "cost_product": cost_product, "cost_env": cost_env,
            "cost_trend": cost_trend, "performance": perf, "freshness": fresh, "observability": obs, "lineage_impact": impact}


@app.post("/api/incidents/{iid}/action")
def incident_action(iid: int, request: Request, body: dict = Body(...)):
    require_db()
    user = user_of(request)
    action = body.get("action")
    if action == "assign":
        i = one("UPDATE mesh.incidents SET owner=%s, status='Investigating', updated_at=now() WHERE id=%s RETURNING *", (body.get("owner") or user, iid))
    elif action == "escalate":
        i = one("""UPDATE mesh.incidents SET status='Escalated', severity=CASE severity WHEN 'Low' THEN 'Medium' WHEN 'Medium' THEN 'High' ELSE 'Critical' END,
                   updated_at=now() WHERE id=%s RETURNING *""", (iid,))
    elif action == "ticket":
        i = one("UPDATE mesh.incidents SET ticket='INC' || lpad((10000+id)::text,7,'0'), updated_at=now() WHERE id=%s RETURNING *", (iid,))
    elif action == "resolve":
        i = one("UPDATE mesh.incidents SET status='Resolved', updated_at=now() WHERE id=%s RETURNING *", (iid,))
    else:
        raise HTTPException(400, "Unknown action")
    event(i["env"], "Incident", f"Incident #{iid} {action}: {i['title']}", user)
    return i


# ---------------------------------------------------------------- manage
@app.get("/api/manage")
def manage(env: str = "PROD"):
    require_db()
    domains = query("""SELECT d.*, (SELECT count(*) FROM mesh.products p WHERE p.domain_id=d.id)::int AS products FROM mesh.domains d ORDER BY d.id""")
    envs = query("""SELECT e.*,
                      (SELECT count(*) FROM mesh.deployments x WHERE x.env=e.code AND x.status='In Progress')::int AS active,
                      (SELECT count(*) FROM mesh.deployments x WHERE x.env=e.code AND x.status='Pending')::int AS pending,
                      (SELECT count(*) FROM mesh.deployments x WHERE x.env=e.code AND x.status='Succeeded')::int AS succeeded,
                      (SELECT count(*) FROM mesh.state_objects s WHERE s.env=e.code AND s.status<>'Synced')::int AS drift
                    FROM mesh.environments e ORDER BY e.tier""")
    return {
        "domains": domains,
        "policies": query("SELECT * FROM mesh.policies ORDER BY array_position(ARRAY['Draft','Review','Approved','Published','Retired'], lifecycle), name"),
        "security": query("SELECT * FROM mesh.security_controls ORDER BY kind"),
        "roles": query("SELECT * FROM mesh.roles ORDER BY id"),
        "groups": query("SELECT * FROM mesh.user_groups ORDER BY name"),
        "environments": envs,
        "active_deployments": query("SELECT * FROM mesh.deployments WHERE status IN ('In Progress','Pending') ORDER BY created_at DESC LIMIT 20"),
        "rollbacks": query("SELECT * FROM mesh.deployments WHERE status='Rolled Back' ORDER BY created_at DESC LIMIT 20"),
        "lifecycle": LIFECYCLE,
        "product_lifecycle": query("SELECT lifecycle, count(*)::int AS n FROM mesh.products GROUP BY lifecycle"),
    }


@app.post("/api/policies")
def create_policy(request: Request, body: dict = Body(...)):
    require_db()
    p = one("INSERT INTO mesh.policies(name,category,lifecycle,owner,description) VALUES (%s,%s,'Draft',%s,%s) RETURNING *",
            (body["name"], body.get("category", "Policy"), user_of(request), body.get("description", "")))
    event("PROD", "Governance", f"{p['category']} drafted: {p['name']}", user_of(request))
    return p


@app.post("/api/policies/{pid}/advance")
def advance_policy(pid: int, request: Request):
    require_db()
    p = one("SELECT * FROM mesh.policies WHERE id=%s", (pid,))
    idx = LIFECYCLE.index(p["lifecycle"]) if p["lifecycle"] in LIFECYCLE else 0
    nxt = LIFECYCLE[min(idx + 1, len(LIFECYCLE) - 1)]
    p = one("UPDATE mesh.policies SET lifecycle=%s, updated_at=now() WHERE id=%s RETURNING *", (nxt, pid))
    event("PROD", "Governance", f"{p['category']} {p['name']} moved to {nxt}", user_of(request))
    return p


@app.post("/api/products/{pid}/lifecycle")
def product_lifecycle(pid: int, request: Request, body: dict = Body(...)):
    require_db()
    p = one("UPDATE mesh.products SET lifecycle=%s, certified=CASE WHEN %s THEN true ELSE certified END WHERE id=%s RETURNING *",
            (body["lifecycle"], bool(body.get("certify")), pid))
    event("PROD", "Certification" if body.get("certify") else "Governance", f"{p['name']} lifecycle set to {p['lifecycle']}", user_of(request))
    return p


@app.post("/api/groups/{gid}/review")
def review_group(gid: int, request: Request):
    require_db()
    g = one("UPDATE mesh.user_groups SET last_review=current_date, review_status='Completed' WHERE id=%s RETURNING *", (gid,))
    event("PROD", "Security", f"Access review completed for {g['name']}", user_of(request))
    return g


# ---------------------------------------------------------------- state management (Lakebase)
@app.get("/api/state")
def state(env: str = "PROD"):
    require_db()
    objs = query("SELECT * FROM mesh.state_objects WHERE env=%s ORDER BY CASE status WHEN 'Drift' THEN 0 WHEN 'Pending' THEN 1 ELSE 2 END, object_type, name", (env,))
    summary = query("SELECT env, status, count(*)::int AS n FROM mesh.state_objects GROUP BY env, status")
    return {"objects": objs, "summary": summary}


@app.post("/api/state/sync")
def sync_state(request: Request, body: dict = Body(default={})):
    require_db()
    env = body.get("env", "PROD")
    if body.get("id"):
        rows = query("UPDATE mesh.state_objects SET current_state=desired_state, status='Synced', updated_at=now() WHERE id=%s RETURNING *", (body["id"],))
    else:
        rows = query("UPDATE mesh.state_objects SET current_state=desired_state, status='Synced', updated_at=now() WHERE env=%s AND status<>'Synced' RETURNING *", (env,))
    for r in rows:
        if r["object_type"] == "Pipeline":
            execute("UPDATE mesh.pipelines SET status='Running', health='Healthy', last_run=now() WHERE env=%s AND name LIKE %s",
                    (r["env"], r["name"].replace("_pipeline", "") + "%"))
    event(env, "State", f"Environment sync reconciled {len(rows)} object(s)", user_of(request))
    return {"synced": len(rows)}


@app.post("/api/state/detect-drift")
def detect_drift(request: Request, body: dict = Body(default={})):
    """Compare runtime pipeline state with desired state and record drift in Lakebase."""
    require_db()
    env = body.get("env", "PROD")
    failed = query("SELECT name FROM mesh.pipelines WHERE env=%s AND status='Failed'", (env,))
    n = 0
    for f in failed:
        short = f["name"].replace(f"_{env.lower()}_pipeline", "_pipeline")
        ex = one("SELECT id FROM mesh.state_objects WHERE env=%s AND object_type='Pipeline' AND name=%s", (env, short))
        if ex:
            execute("UPDATE mesh.state_objects SET current_state='Failed', desired_state='Running', status='Drift', updated_at=now() WHERE id=%s", (ex["id"],))
        else:
            execute("INSERT INTO mesh.state_objects(object_type,name,env,current_state,desired_state,status) VALUES ('Pipeline',%s,%s,'Failed','Running','Drift')", (short, env))
        n += 1
    event(env, "State", f"Drift analysis completed: {n} pipeline drift(s)", user_of(request))
    return {"drift": n}


# ---------------------------------------------------------------- Databricks Catalog state source
@app.get("/api/catalog")
def catalog(catalog: Optional[str] = None, schema: Optional[str] = None):
    try:
        w = db.workspace()
        if catalog and schema:
            items = [{"name": t.name, "type": str(t.table_type.value if t.table_type else ""), "full_name": t.full_name, "comment": t.comment}
                     for _, t in zip(range(200), w.tables.list(catalog_name=catalog, schema_name=schema))]
            return {"level": "tables", "items": items}
        if catalog:
            return {"level": "schemas", "items": [{"name": s.name, "comment": s.comment} for _, s in zip(range(200), w.schemas.list(catalog_name=catalog))]}
        return {"level": "catalogs", "items": [{"name": c.name, "comment": c.comment} for _, c in zip(range(200), w.catalogs.list())]}
    except Exception as ex:
        return {"level": "error", "items": [], "error": str(ex)}


@app.post("/api/admin/reseed")
def reseed():
    from seed import init_db
    return {"result": init_db(force=True)}


# ---------------------------------------------------------------- static UI
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("DATABRICKS_APP_PORT") or os.environ.get("PORT", "8000")))

"""State store schema (mesh.*) and initial Data Mesh state seed (Lakebase or SQLite)."""
import random
import logging
import datetime as dt

import db
from db import Json, one, query

log = logging.getLogger("mesh.seed")

DDL = """
CREATE SCHEMA IF NOT EXISTS mesh;
CREATE TABLE IF NOT EXISTS mesh.environments(
  code TEXT PRIMARY KEY, name TEXT, region TEXT, tier INT, health TEXT, status TEXT, workspace TEXT);
CREATE TABLE IF NOT EXISTS mesh.user_prefs(
  user_email TEXT PRIMARY KEY, env TEXT, region TEXT, state_source TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.domains(
  id SERIAL PRIMARY KEY, name TEXT UNIQUE, description TEXT, owner TEXT, steward TEXT, custodian TEXT,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.domain_states(
  domain_id INT REFERENCES mesh.domains(id), env TEXT, health TEXT, quality_score DOUBLE PRECISION,
  governance_score DOUBLE PRECISION, storage_tb DOUBLE PRECISION, compute_dbu DOUBLE PRECISION,
  freshness_min DOUBLE PRECISION, updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY(domain_id, env));
CREATE TABLE IF NOT EXISTS mesh.products(
  id SERIAL PRIMARY KEY, name TEXT UNIQUE, domain_id INT REFERENCES mesh.domains(id), description TEXT,
  owner TEXT, certified BOOLEAN DEFAULT FALSE, lifecycle TEXT, sla TEXT, tags TEXT[], schema_def JSONB,
  days_to_create INT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.product_states(
  product_id INT REFERENCES mesh.products(id), env TEXT, version TEXT, status TEXT,
  quality_score DOUBLE PRECISION, usage_30d INT, consumers INT, trend DOUBLE PRECISION,
  freshness_min DOUBLE PRECISION, updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY(product_id, env));
CREATE TABLE IF NOT EXISTS mesh.pipelines(
  id SERIAL PRIMARY KEY, name TEXT, product_id INT REFERENCES mesh.products(id), env TEXT, engine TEXT,
  status TEXT, health TEXT, layers JSONB, last_run TIMESTAMPTZ, duration_min DOUBLE PRECISION,
  rows_per_hour BIGINT, latency_min DOUBLE PRECISION, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.deployments(
  id SERIAL PRIMARY KEY, object_type TEXT, object_name TEXT, version TEXT, env TEXT, status TEXT,
  requested_by TEXT, notes TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.approvals(
  id SERIAL PRIMARY KEY, kind TEXT, object_name TEXT, product_id INT, env TEXT, requester TEXT,
  justification TEXT, status TEXT, decided_by TEXT, created_at TIMESTAMPTZ DEFAULT now(), decided_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS mesh.contracts(
  id SERIAL PRIMARY KEY, name TEXT, product_id INT REFERENCES mesh.products(id), kind TEXT,
  consumer_domain_id INT, status TEXT, version TEXT, spec JSONB, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.lineage(
  id SERIAL PRIMARY KEY, src_product_id INT, dst_product_id INT, kind TEXT);
CREATE TABLE IF NOT EXISTS mesh.incidents(
  id SERIAL PRIMARY KEY, kind TEXT, title TEXT, severity TEXT, status TEXT, owner TEXT, product_id INT,
  env TEXT, ticket TEXT, created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.events(
  id SERIAL PRIMARY KEY, env TEXT, kind TEXT, message TEXT, actor TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.quality_rules(
  id SERIAL PRIMARY KEY, product_id INT, env TEXT, rule TEXT, dimension TEXT, pass_rate DOUBLE PRECISION, status TEXT);
CREATE TABLE IF NOT EXISTS mesh.cost_monthly(
  domain_id INT, env TEXT, month DATE, amount DOUBLE PRECISION, PRIMARY KEY(domain_id, env, month));
CREATE TABLE IF NOT EXISTS mesh.state_objects(
  id SERIAL PRIMARY KEY, object_type TEXT, name TEXT, env TEXT, current_state TEXT, desired_state TEXT,
  status TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.policies(
  id SERIAL PRIMARY KEY, name TEXT, category TEXT, lifecycle TEXT, owner TEXT, description TEXT,
  updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.security_controls(
  id SERIAL PRIMARY KEY, name TEXT, kind TEXT, target TEXT, rule TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS mesh.roles(
  id SERIAL PRIMARY KEY, name TEXT, description TEXT, members INT, privileges TEXT);
CREATE TABLE IF NOT EXISTS mesh.user_groups(
  id SERIAL PRIMARY KEY, name TEXT, team TEXT, members INT, permissions TEXT, last_review DATE, review_status TEXT);
CREATE TABLE IF NOT EXISTS mesh.glossary(
  id SERIAL PRIMARY KEY, term TEXT, definition TEXT, domain_id INT);
CREATE TABLE IF NOT EXISTS mesh.pipeline_schedules(
  pipeline_id INT PRIMARY KEY, frequency TEXT, paused BOOLEAN DEFAULT FALSE, next_run TIMESTAMPTZ, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.pipeline_runs(
  id SERIAL PRIMARY KEY, pipeline_id INT, started_at TIMESTAMPTZ, duration_min DOUBLE PRECISION, rows_processed BIGINT, status TEXT);
CREATE TABLE IF NOT EXISTS mesh.backfills(
  id SERIAL PRIMARY KEY, pipeline_id INT, kind TEXT, start_date TEXT, end_date TEXT, partition_key TEXT, status TEXT,
  requested_by TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.consumers(
  id SERIAL PRIMARY KEY, product_id INT, kind TEXT, name TEXT, owner TEXT);
CREATE TABLE IF NOT EXISTS mesh.group_members(
  group_name TEXT, principal TEXT, PRIMARY KEY(group_name, principal));
CREATE TABLE IF NOT EXISTS mesh.access_grants(
  id SERIAL PRIMARY KEY, principal TEXT, principal_type TEXT, product_id INT, env TEXT, role TEXT,
  last_access TIMESTAMPTZ, granted_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.access_audit(
  id SERIAL PRIMARY KEY, principal TEXT, action TEXT, object_name TEXT, env TEXT, detail TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.access_workflow(
  approval_id INT PRIMARY KEY, stage TEXT);
CREATE TABLE IF NOT EXISTS mesh.usage_monthly(
  domain_id INT, env TEXT, month DATE, dbu DOUBLE PRECISION, storage_tb DOUBLE PRECISION, api_calls BIGINT, queries BIGINT,
  PRIMARY KEY(domain_id, env, month));
CREATE TABLE IF NOT EXISTS mesh.quotas(
  id SERIAL PRIMARY KEY, domain_id INT, resource TEXT, unit TEXT, allocated DOUBLE PRECISION, used DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS mesh.artifact_versions(
  id SERIAL PRIMARY KEY, object_type TEXT, name TEXT, version TEXT, schema_changes TEXT, quality_changes TEXT,
  contract_changes TEXT, released_by TEXT, released_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS mesh.alerts(
  id SERIAL PRIMARY KEY, env TEXT, category TEXT, severity TEXT, source TEXT, message TEXT, status TEXT,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.postmortems(
  incident_id INT PRIMARY KEY, summary TEXT, root_cause TEXT, actions TEXT, author TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.teams(
  id SERIAL PRIMARY KEY, name TEXT UNIQUE, business_unit TEXT, domain_id INT, owner TEXT, steward TEXT, tech_lead TEXT,
  product_owner TEXT, status TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.team_members(
  id SERIAL PRIMARY KEY, team_id INT, member TEXT, persona TEXT, added_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.team_provisioning(
  team_id INT, item TEXT, status TEXT, updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY(team_id, item));
CREATE TABLE IF NOT EXISTS mesh.team_checklist(
  team_id INT, item TEXT, done BOOLEAN DEFAULT FALSE, updated_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY(team_id, item));
CREATE TABLE IF NOT EXISTS mesh.product_onboarding(
  product_id INT PRIMARY KEY, use_cases TEXT, consumers TEXT, target_tables TEXT, refresh_frequency TEXT, retention_policy TEXT,
  classification TEXT, review_stage TEXT, cert_level TEXT, cert_status TEXT, expected_volume TEXT, usage_limits TEXT,
  access_policy TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.gov_rules(
  id SERIAL PRIMARY KEY, kind TEXT, area TEXT, name TEXT, rule TEXT, value TEXT, status TEXT, owner TEXT,
  updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.compliance_checks(
  id SERIAL PRIMARY KEY, framework TEXT, name TEXT, requirement TEXT, status TEXT, owner TEXT, last_assessed TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.platform_services(
  id SERIAL PRIMARY KEY, category TEXT, name TEXT, status TEXT, owner TEXT, details JSONB, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.service_requests(
  id SERIAL PRIMARY KEY, category TEXT, item TEXT, team TEXT, requester TEXT, justification TEXT, status TEXT,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.platform_config(
  setting TEXT PRIMARY KEY, value TEXT, category TEXT, description TEXT, updated_by TEXT, updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.build_checks(
  product_id INT, area TEXT, item TEXT, status TEXT, checked_by TEXT, note TEXT, checked_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(product_id, area, item));
CREATE TABLE IF NOT EXISTS mesh.build_models(
  id SERIAL PRIMARY KEY, product_id INT, name TEXT, kind TEXT, layer TEXT, model_type TEXT, column_count INT, status TEXT,
  updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.build_rules(
  id SERIAL PRIMARY KEY, product_id INT, kind TEXT, category TEXT, name TEXT, expression TEXT, threshold TEXT, status TEXT,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.build_tests(
  id SERIAL PRIMARY KEY, product_id INT, suite TEXT, name TEXT, status TEXT, duration_s DOUBLE PRECISION, last_run TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS mesh.build_releases(
  id SERIAL PRIMARY KEY, product_id INT, version TEXT, status TEXT, stage TEXT, artifacts JSONB, notes TEXT, created_by TEXT,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS mesh.build_schema_snapshots(
  product_id INT, env TEXT, schema_cols JSONB, captured_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY(product_id, env));
CREATE TABLE IF NOT EXISTS mesh.build_data_checks(
  id SERIAL PRIMARY KEY, product_id INT, env TEXT, check_type TEXT, metric TEXT, source_value DOUBLE PRECISION,
  target_value DOUBLE PRECISION, status TEXT, checked_at TIMESTAMPTZ DEFAULT now());
"""

OPS_TABLES = ["pipeline_schedules", "pipeline_runs", "backfills", "consumers", "group_members", "access_grants", "access_audit",
              "access_workflow", "usage_monthly", "quotas", "artifact_versions", "alerts", "postmortems"]
MGMT_TABLES = ["teams", "team_members", "team_provisioning", "team_checklist", "product_onboarding", "gov_rules",
               "compliance_checks", "platform_services", "service_requests", "platform_config"]
BUILD_TABLES = ["build_checks", "build_models", "build_rules", "build_tests", "build_releases", "build_schema_snapshots", "build_data_checks"]

ENVS = [
    ("PROD", "Production", "canadacentral", 4, "Healthy", "Active", "adb-prod"),
    ("UAT", "UAT", "canadacentral", 3, "Healthy", "Active", "adb-uat"),
    ("SIT", "SIT", "eastus", 2, "Warning", "Active", "adb-sit"),
    ("DEV", "Development", "eastus", 1, "Healthy", "Active", "adb-dev"),
]

DOMAINS = [
    ("Finance", "Financial reporting, ledger and revenue", "anna.fin@corp.com", "raj.steward@corp.com", "platform-finance"),
    ("Sales", "Pipeline, opportunities and forecasting", "mark.sales@corp.com", "li.steward@corp.com", "platform-sales"),
    ("Customer", "Customer master, consent and 360 view", "sofia.cx@corp.com", "omar.steward@corp.com", "platform-customer"),
    ("Marketing", "Campaigns, audiences and attribution", "jules.mkt@corp.com", "nina.steward@corp.com", "platform-marketing"),
    ("Operations", "Inventory, supply chain and suppliers", "tom.ops@corp.com", "eva.steward@corp.com", "platform-ops"),
]

PROD_HEALTH = {"Finance": "Healthy", "Sales": "Healthy", "Customer": "Warning", "Marketing": "Error", "Operations": "Healthy"}
PROD_COST = {"Finance": 3200, "Sales": 2800, "Customer": 2350, "Marketing": 1500, "Operations": 1900}

# name, domain, description, certified, lifecycle, sla, tags, sources
PRODUCTS = [
    ("RevenueAnalytics", "Finance", "Recognised revenue by product, region and channel", True, "Published", "Daily 06:00 ET", ["gold", "kpi"], ["erp.gl_entries", "billing.invoices"]),
    ("GeneralLedger", "Finance", "Conformed general ledger with chart of accounts", True, "Published", "Hourly", ["gold", "sox"], ["erp.gl_entries"]),
    ("CostAllocation", "Finance", "Shared cost allocation and chargeback", False, "Draft", "Daily", ["silver"], ["cloud.billing_export"]),
    ("PipelineAnalytics", "Sales", "Opportunity pipeline coverage and velocity", True, "Published", "Hourly", ["gold"], ["crm.opportunities"]),
    ("DealIntelligence", "Sales", "Deal scoring and win/loss signals", False, "Published", "Daily", ["ml", "gold"], ["crm.opportunities", "crm.activities"]),
    ("SalesForecast", "Sales", "Weekly bookings forecast by segment", False, "Review", "Weekly", ["ml"], ["crm.opportunities"]),
    ("Customer360", "Customer", "Golden customer profile across all touchpoints", True, "Published", "Hourly", ["gold", "pii"], ["crm.accounts", "web.sessions", "support.tickets"]),
    ("ChurnSignals", "Customer", "Churn propensity and early warning signals", False, "Published", "Daily", ["ml"], ["support.tickets"]),
    ("CustomerConsent", "Customer", "Consent and privacy preferences (CASL / GDPR)", True, "Approved", "Near real-time", ["pii", "regulatory"], ["web.consent_events"]),
    ("CampaignPerformance", "Marketing", "Multi-touch campaign attribution", False, "Published", "Daily", ["gold"], ["ads.impressions", "ads.clicks"]),
    ("AudienceSegments", "Marketing", "Activation-ready audience segments", False, "Published", "Daily", ["activation"], ["cdp.profiles"]),
    ("InventoryInsights", "Operations", "Inventory position, aging and stock-outs", True, "Published", "Hourly", ["gold"], ["wms.stock", "erp.items"]),
    ("SupplierKPIs", "Operations", "Supplier OTIF, quality and lead time", False, "Review", "Daily", ["gold"], ["erp.purchase_orders"]),
]

LINEAGE = [
    ("Customer360", "ChurnSignals"), ("Customer360", "AudienceSegments"), ("Customer360", "RevenueAnalytics"),
    ("CustomerConsent", "AudienceSegments"), ("CustomerConsent", "Customer360"), ("GeneralLedger", "RevenueAnalytics"),
    ("DealIntelligence", "RevenueAnalytics"), ("PipelineAnalytics", "SalesForecast"), ("PipelineAnalytics", "DealIntelligence"),
    ("CampaignPerformance", "PipelineAnalytics"), ("InventoryInsights", "SupplierKPIs"), ("SupplierKPIs", "CostAllocation"),
    ("GeneralLedger", "CostAllocation"), ("ChurnSignals", "CampaignPerformance"),
]

ENGINES = ["Lakeflow SDP", "Spark Job", "DBT Model", "Fabric Pipeline", "Airflow DAG"]


def _columns(name, rnd):
    base = [
        {"name": f"{name.lower()}_id", "type": "BIGINT", "description": "Surrogate key", "pii": False, "nullable": False},
        {"name": "business_date", "type": "DATE", "description": "Business date", "pii": False, "nullable": False},
        {"name": "region", "type": "STRING", "description": "Sales region", "pii": False, "nullable": True},
    ]
    extra = {
        "Customer": [{"name": "customer_email", "type": "STRING", "description": "Primary email", "pii": True, "nullable": True},
                     {"name": "lifetime_value", "type": "DECIMAL(18,2)", "description": "Customer LTV", "pii": False, "nullable": True}],
        "Revenue": [{"name": "revenue_amount", "type": "DECIMAL(18,2)", "description": "Recognised revenue", "pii": False, "nullable": False}],
    }
    for k, v in extra.items():
        if k in name:
            base += v
    base.append({"name": "score" if rnd.random() > 0.5 else "amount", "type": "DOUBLE", "description": "Primary measure", "pii": False, "nullable": True})
    base.append({"name": "_updated_at", "type": "TIMESTAMP", "description": "Load timestamp", "pii": False, "nullable": False})
    return base


def init_db(force: bool = False) -> str:
    db.run_script(DDL)
    row = one("SELECT count(*) AS n FROM mesh.domains")
    if row and row["n"] > 0 and not force:
        added = ""
        if one("SELECT count(*) AS n FROM mesh.quotas")["n"] == 0:
            _seed_ops()
            added += "+ops"
        if one("SELECT count(*) AS n FROM mesh.teams")["n"] == 0:
            _seed_mgmt()
            added += "+mgmt"
        if one("SELECT count(*) AS n FROM mesh.build_models")["n"] == 0:
            _seed_build()
            added += "+build"
        return "existing" + added
    if force:
        tables = ["environments", "domains", "domain_states", "products", "product_states", "pipelines", "deployments",
                  "approvals", "contracts", "lineage", "incidents", "events", "quality_rules", "cost_monthly", "state_objects",
                  "policies", "security_controls", "roles", "user_groups", "glossary"] + OPS_TABLES + MGMT_TABLES + BUILD_TABLES
        if db.is_sqlite():
            db.run_script("".join(f"DELETE FROM mesh.{t};" for t in reversed(tables)))
        else:
            db.run_script(f"TRUNCATE {', '.join('mesh.' + t for t in tables)} RESTART IDENTITY CASCADE")
    _seed()
    _seed_ops()
    _seed_mgmt()
    _seed_build()
    return "seeded"


def _seed():
    rnd = random.Random(42)
    now = dt.datetime.now(dt.timezone.utc)
    with db.connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            cur.executemany("INSERT INTO mesh.environments VALUES (%s,%s,%s,%s,%s,%s,%s)", ENVS)
            dom_ids = {}
            for d in DOMAINS:
                cur.execute("INSERT INTO mesh.domains(name,description,owner,steward,custodian) VALUES (%s,%s,%s,%s,%s) RETURNING id", d)
                dom_ids[d[0]] = cur.fetchone()["id"]
            for name, did in dom_ids.items():
                for env in [e[0] for e in ENVS]:
                    health = PROD_HEALTH[name] if env == "PROD" else rnd.choice(["Healthy", "Healthy", "Healthy", "Warning"])
                    q = {"Healthy": 94, "Warning": 84, "Error": 71}[health] + rnd.uniform(-3, 4)
                    cur.execute("INSERT INTO mesh.domain_states VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())",
                                (did, env, health, round(q, 1), round(rnd.uniform(78, 98), 1),
                                 round(rnd.uniform(2, 40) / (5 - [e[0] for e in ENVS].index(env) if env != "PROD" else 1), 2),
                                 round(rnd.uniform(800, 5200) * (1 if env == "PROD" else 0.3), 0), round(rnd.uniform(8, 140), 0)))
                # cost trend: 6 months
                for env in [e[0] for e in ENVS]:
                    base = PROD_COST[name] * {"PROD": 1, "UAT": 0.35, "SIT": 0.22, "DEV": 0.18}[env]
                    for m in range(6):
                        month = (now.replace(day=1) - dt.timedelta(days=30 * (5 - m))).date().replace(day=1)
                        amt = base if m == 5 else base * rnd.uniform(0.78, 1.08)
                        cur.execute("INSERT INTO mesh.cost_monthly VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", (did, env, month, round(amt, 0)))

            prod_ids = {}
            for (name, dom, desc, cert, life, sla, tags, sources) in PRODUCTS:
                schema_def = {"sources": sources, "columns": _columns(name, rnd)}
                cur.execute("""INSERT INTO mesh.products(name,domain_id,description,owner,certified,lifecycle,sla,tags,schema_def,days_to_create,created_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                            (name, dom_ids[dom], desc, DOMAINS[[d[0] for d in DOMAINS].index(dom)][2], cert, life, sla, tags,
                             Json(schema_def), rnd.randint(4, 28), now - dt.timedelta(days=rnd.randint(30, 400))))
                pid = cur.fetchone()["id"]
                prod_ids[name] = (pid, dom)
                envs = ["DEV", "SIT"] if life == "Draft" else (["DEV", "SIT", "UAT"] if life in ("Review", "Approved") else ["DEV", "SIT", "UAT", "PROD"])
                minor = rnd.randint(0, 4)
                for env in envs:
                    bump = {"PROD": 0, "UAT": 1, "SIT": 1, "DEV": 2}[env]
                    status = "Published" if env == "PROD" else ("Draft" if life == "Draft" else "Staged")
                    usage = rnd.randint(200, 9000) if env == "PROD" else rnd.randint(5, 300)
                    dq = 96 - (12 if dom == "Marketing" and env == "PROD" else 0) - (6 if dom == "Customer" and env == "PROD" else 0) + rnd.uniform(-3, 3)
                    cur.execute("INSERT INTO mesh.product_states VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())",
                                (pid, env, f"v1.{minor + bump}", status, round(dq, 1), usage, rnd.randint(1, 24) if env == "PROD" else rnd.randint(0, 4),
                                 round(rnd.uniform(-15, 45), 1), round(rnd.uniform(5, 180), 0)))
                    # pipeline
                    engine = ENGINES[(pid + bump) % len(ENGINES)]
                    status_p = rnd.choices(["Running", "Completed", "Queued", "Failed"], [3, 5, 1, 1])[0]
                    if env == "PROD" and dom == "Marketing" and name == "CampaignPerformance":
                        status_p = "Failed"
                    if env == "PROD" and name == "ChurnSignals":
                        status_p = "Failed"
                    health = "Failed" if status_p == "Failed" else ("Warning" if (env == "PROD" and dom == "Customer") or rnd.random() < 0.12 else "Healthy")
                    cur.execute("""INSERT INTO mesh.pipelines(name,product_id,env,engine,status,health,layers,last_run,duration_min,rows_per_hour,latency_min)
                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                (f"{name.lower()}_{env.lower()}_pipeline", pid, env, engine, status_p, health,
                                 Json(["Source", "Bronze", "Silver", "Gold", "Product"]), now - dt.timedelta(minutes=rnd.randint(3, 600)),
                                 round(rnd.uniform(2, 75), 1), rnd.randint(20_000, 4_000_000), round(rnd.uniform(1, 90), 1)))
                    for rule, dim in [("100% mandatory fields populated", "Completeness"), ("Duplicate check on business key", "Consistency"),
                                      ("Business rule validation", "Accuracy"), ("Freshness within SLA", "Timeliness")]:
                        pr = min(100.0, round(rnd.uniform(88, 100.4) - (10 if dom == "Marketing" and env == "PROD" else 0), 1))
                        cur.execute("INSERT INTO mesh.quality_rules(product_id,env,rule,dimension,pass_rate,status) VALUES (%s,%s,%s,%s,%s,%s)",
                                    (pid, env, rule, dim, pr, "Pass" if pr >= 95 else ("Warn" if pr >= 85 else "Fail")))

                for kind in ["Producer", "SLA", "Schema"]:
                    spec = {"sla": sla, "freshness_minutes": 60 if "Hourly" in sla else 1440, "columns": [c["name"] for c in schema_def["columns"]],
                            "quality": {"completeness": ">= 99%"}}
                    cur.execute("INSERT INTO mesh.contracts(name,product_id,kind,status,version,spec) VALUES (%s,%s,%s,%s,%s,%s)",
                                (f"{name}-{kind.lower()}", pid, kind, "Active" if life != "Draft" else "Draft", "1.0", Json(spec)))

            for src, dst in LINEAGE:
                cross = prod_ids[src][1] != prod_ids[dst][1]
                cur.execute("INSERT INTO mesh.lineage(src_product_id,dst_product_id,kind) VALUES (%s,%s,%s)",
                            (prod_ids[src][0], prod_ids[dst][0], "cross-domain" if cross else "intra-domain"))
                if cross:
                    cur.execute("INSERT INTO mesh.contracts(name,product_id,kind,consumer_domain_id,status,version,spec) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                (f"{src}-to-{dst}-consumer", prod_ids[src][0], "Consumer", dom_ids[prod_ids[dst][1]], "Active", "1.0",
                                 Json({"consumer": dst, "purpose": "Downstream product", "freshness_minutes": 1440})))

            users = ["priya.analyst@corp.com", "kevin.ds@corp.com", "maria.bi@corp.com", "ahmed.eng@corp.com", "chloe.risk@corp.com"]
            for i, (kind, obj, env, status) in enumerate([
                ("Access", "Customer360", "PROD", "Pending"), ("Access", "RevenueAnalytics", "PROD", "Pending"),
                ("Publish", "SupplierKPIs", "UAT", "Pending"), ("Deployment", "RevenueAnalytics v1.2", "PROD", "Pending"),
                ("Contract", "CustomerConsent-sla", "UAT", "Pending"), ("Access", "ChurnSignals", "PROD", "Approved"),
                ("Access", "GeneralLedger", "PROD", "Rejected"), ("Publish", "SalesForecast", "UAT", "Pending"),
                ("Access", "InventoryInsights", "UAT", "Pending"), ("Deployment", "Customer360 v1.4", "UAT", "Approved"),
            ]):
                base = obj.split(" ")[0].split("-")[0]
                cur.execute("""INSERT INTO mesh.approvals(kind,object_name,product_id,env,requester,justification,status,decided_by,created_at,decided_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (kind, obj, prod_ids.get(base, (None,))[0], env, users[i % len(users)], f"{kind} request for {obj}", status,
                             None if status == "Pending" else "platform.admin@corp.com", now - dt.timedelta(hours=rnd.randint(1, 96)),
                             None if status == "Pending" else now - dt.timedelta(hours=rnd.randint(0, 5))))

            for i in range(36):
                env = rnd.choice(["DEV", "DEV", "SIT", "UAT", "PROD"])
                pname = rnd.choice(list(prod_ids))
                otype = rnd.choice(["Product", "Pipeline", "Contract"])
                status = rnd.choices(["Succeeded", "Failed", "Rolled Back", "In Progress", "Pending"], [12, 2, 1, 1, 1])[0]
                cur.execute("INSERT INTO mesh.deployments(object_type,object_name,version,env,status,requested_by,notes,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (otype, pname if otype == "Product" else (f"{pname.lower()}_pipeline" if otype == "Pipeline" else f"{pname}-producer"),
                             f"v1.{rnd.randint(0, 6)}", env, status, rnd.choice(users), "CI/CD release", now - dt.timedelta(hours=rnd.randint(1, 24 * 20))))
            cur.execute("INSERT INTO mesh.deployments(object_type,object_name,version,env,status,requested_by,notes,created_at) VALUES ('Product','CampaignPerformance','v1.3','PROD','Failed','jules.mkt@corp.com','Schema validation failed', now() - interval '3 hours')")

            for kind, title, sev, status, owner, prod, env in [
                ("Pipeline Failure", "campaignperformance_prod_pipeline failed at Silver stage", "High", "Open", None, "CampaignPerformance", "PROD"),
                ("SLA Violation", "Customer360 freshness exceeded 60 min SLA", "Medium", "Investigating", "sofia.cx@corp.com", "Customer360", "PROD"),
                ("Data Quality Issue", "Duplicate audience IDs detected", "High", "Open", None, "AudienceSegments", "PROD"),
                ("Contract Violation", "ChurnSignals dropped column churn_reason", "Critical", "Escalated", "omar.steward@corp.com", "ChurnSignals", "PROD"),
                ("Pipeline Failure", "churnsignals_prod_pipeline OOM on Gold", "High", "Open", None, "ChurnSignals", "PROD"),
                ("Data Quality Issue", "Null supplier_id in 2.1% rows", "Low", "Resolved", "eva.steward@corp.com", "SupplierKPIs", "UAT"),
                ("SLA Violation", "SalesForecast weekly run late", "Medium", "Open", None, "SalesForecast", "UAT"),
                ("Pipeline Failure", "Fabric pipeline credential expired", "Medium", "Open", None, "CostAllocation", "SIT"),
            ]:
                cur.execute("INSERT INTO mesh.incidents(kind,title,severity,status,owner,product_id,env,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (kind, title, sev, status, owner, prod_ids[prod][0], env, now - dt.timedelta(hours=rnd.randint(1, 48))))

            ev_templates = [
                ("Deployment", "Deployment completed: {p} {v} to {e}"), ("Contract", "Data contract updated: {p}-producer"),
                ("Pipeline", "Pipeline failed: {pl}"), ("Certification", "Dataset certified: {p}"),
                ("Schema", "Schema change detected on {p}: column added"), ("Publication", "Product published: {p} {v}"),
                ("Approval", "Access approved on {p} for analyst group"), ("Incident", "Incident opened on {p}"),
            ]
            for i in range(60):
                env = rnd.choice(["PROD", "PROD", "UAT", "SIT", "DEV"])
                kind, tpl = rnd.choice(ev_templates)
                p = rnd.choice(list(prod_ids))
                cur.execute("INSERT INTO mesh.events(env,kind,message,actor,created_at) VALUES (%s,%s,%s,%s,%s)",
                            (env, kind, tpl.format(p=p, v=f"v1.{rnd.randint(0, 5)}", e=env, pl=f"{p.lower()}_{env.lower()}_pipeline"),
                             rnd.choice(users), now - dt.timedelta(minutes=rnd.randint(5, 60 * 72))))

            for env in [e[0] for e in ENVS]:
                rows = [
                    ("Product", "RevenueAnalytics", "v1.1", "v1.2", "Pending"),
                    ("Contract", "CustomerConsent-sla", "Active", "Active", "Synced"),
                    ("Pipeline", "campaignperformance_pipeline", "Failed", "Running", "Drift"),
                    ("Product", "Customer360", "v1.4", "v1.4", "Synced"),
                    ("Pipeline", "churnsignals_pipeline", "Failed", "Running", "Drift"),
                    ("Policy", "PII Column Masking", "Enforced", "Enforced", "Synced"),
                    ("Product", "SupplierKPIs", "absent", "v1.0", "Pending"),
                    ("Contract", "ChurnSignals-schema", "v1.0", "v1.1", "Drift"),
                ] if env == "PROD" else [
                    ("Product", "SalesForecast", "v1.2", "v1.3", "Pending"),
                    ("Pipeline", "supplierkpis_pipeline", "Running", "Running", "Synced"),
                    ("Contract", "Customer360-sla", "Active", "Active", "Synced"),
                    ("Product", "CostAllocation", "v0.9", "v1.0", rnd.choice(["Pending", "Drift"])),
                ]
                cur.executemany("INSERT INTO mesh.state_objects(object_type,name,env,current_state,desired_state,status) VALUES (%s,%s,%s,%s,%s,%s)",
                                [(r[0], r[1], env, r[2], r[3], r[4]) for r in rows])

            cur.executemany("INSERT INTO mesh.policies(name,category,lifecycle,owner,description) VALUES (%s,%s,%s,%s,%s)", [
                ("PII Column Masking", "Policy", "Published", "governance@corp.com", "Mask columns tagged pii for non-privileged groups"),
                ("Data Retention 7y", "Policy", "Approved", "legal@corp.com", "Retain financial data 7 years"),
                ("Naming Standard v2", "Standard", "Review", "platform@corp.com", "catalog.domain_layer.entity naming"),
                ("Data Product Certification", "Certification", "Published", "governance@corp.com", "Quality >= 95, owner, contract, docs"),
                ("Cross-Border Transfer", "Policy", "Draft", "privacy@corp.com", "Restrict PII replication outside Canada"),
                ("Contract Versioning", "Standard", "Published", "platform@corp.com", "SemVer for schema contracts"),
                ("Legacy Hive Access", "Policy", "Retired", "platform@corp.com", "Superseded by Unity Catalog"),
            ])
            cur.executemany("INSERT INTO mesh.security_controls(name,kind,target,rule,status) VALUES (%s,%s,%s,%s,%s)", [
                ("Domain read grants", "RBAC", "catalog finance", "GRANT SELECT TO finance-consumers", "Enforced"),
                ("PII tag-based access", "ABAC", "tag pii = true", "Allow only group pii-approved", "Enforced"),
                ("Region row filter", "Row Security", "Customer360", "region = current_user_region()", "Enforced"),
                ("Email masking", "Column Security", "Customer360.customer_email", "mask_email(customer_email)", "Enforced"),
                ("Salary masking", "Column Security", "GeneralLedger.payroll_amount", "NULL for non-HR", "Pending"),
            ])
            cur.executemany("INSERT INTO mesh.roles(name,description,members,privileges) VALUES (%s,%s,%s,%s)", [
                ("Data Consumer", "Discover and query certified products", 412, "USE CATALOG, SELECT"),
                ("Data Steward", "Curate metadata, quality and glossary", 23, "APPLY TAG, MODIFY metadata"),
                ("Domain Owner", "Own products, approve access and publish", 9, "ALL PRIVILEGES on domain"),
                ("Platform Admin", "Operate the mesh platform", 5, "Metastore admin"),
            ])
            cur.executemany("INSERT INTO mesh.user_groups(name,team,members,permissions,last_review,review_status) VALUES (%s,%s,%s,%s,%s,%s)", [
                ("finance-consumers", "Finance BI", 86, "SELECT finance.*", now.date() - dt.timedelta(days=40), "Completed"),
                ("sales-engineers", "Sales Ops", 14, "ALL on sales.*", now.date() - dt.timedelta(days=95), "Overdue"),
                ("customer-stewards", "CX Data", 6, "MODIFY customer.*", now.date() - dt.timedelta(days=20), "Completed"),
                ("marketing-analysts", "Marketing", 51, "SELECT marketing.*", now.date() - dt.timedelta(days=130), "Overdue"),
                ("pii-approved", "Privacy", 18, "Unmasked PII", now.date() - dt.timedelta(days=10), "In Review"),
                ("platform-admins", "Platform", 5, "Admin", now.date() - dt.timedelta(days=60), "Completed"),
            ])
            cur.executemany("INSERT INTO mesh.glossary(term,definition,domain_id) VALUES (%s,%s,%s)", [
                ("Recognised Revenue", "Revenue recognised under IFRS 15 in the reporting period", dom_ids["Finance"]),
                ("Active Customer", "Customer with a transaction in the trailing 90 days", dom_ids["Customer"]),
                ("Churn", "Customer with no activity for 180 days or cancelled contract", dom_ids["Customer"]),
                ("Pipeline Coverage", "Open pipeline value / quota for the period", dom_ids["Sales"]),
                ("OTIF", "On-time in-full delivery rate", dom_ids["Operations"]),
                ("Attribution", "Credit assignment of conversions to campaign touches", dom_ids["Marketing"]),
                ("Data Product", "Governed, discoverable dataset with owner, contract and SLA", None),
                ("Data Contract", "Agreement on schema, quality and SLA between producer and consumer", None),
            ])
    log.info("Seeded Data Mesh state into %s", db.describe())


OPS_USERS = ["priya.analyst@corp.com", "kevin.ds@corp.com", "maria.bi@corp.com", "ahmed.eng@corp.com", "chloe.risk@corp.com",
             "john.doe@corp.com", "local.user@corp.com"]
GROUP_MEMBERS = {
    "finance-consumers": ["priya.analyst@corp.com", "maria.bi@corp.com", "john.doe@corp.com"],
    "sales-engineers": ["john.doe@corp.com", "ahmed.eng@corp.com"],
    "customer-stewards": ["chloe.risk@corp.com", "local.user@corp.com"],
    "marketing-analysts": ["maria.bi@corp.com", "kevin.ds@corp.com"],
    "pii-approved": ["chloe.risk@corp.com"],
    "platform-admins": ["ahmed.eng@corp.com", "local.user@corp.com"],
}
GROUP_GRANTS = {"finance-consumers": ("Finance", "Reader"), "sales-engineers": ("Sales", "Contributor"),
                "customer-stewards": ("Customer", "Contributor"), "marketing-analysts": ("Marketing", "Reader"),
                "pii-approved": ("Customer", "Reader")}
FREQ_MIN = {"15 Minutes": 15, "Hourly": 60, "Daily": 1440, "Weekly": 10080}


def _seed_ops():
    """Seed the Operate workspace state (schedules, runs, access, FinOps, artifacts, alerts)."""
    rnd = random.Random(7)
    now = dt.datetime.now(dt.timezone.utc)
    pls = query("""SELECT pl.id, pl.env, pl.status, pl.engine, pl.duration_min, pl.rows_per_hour, p.sla
                   FROM mesh.pipelines pl JOIN mesh.products p ON p.id=pl.product_id ORDER BY pl.id""")
    prods = query("SELECT p.id, p.name, d.name AS domain FROM mesh.products p JOIN mesh.domains d ON d.id=p.domain_id ORDER BY p.id")
    doms = query("SELECT id, name FROM mesh.domains ORDER BY id")
    dstates = query("SELECT domain_id, env, storage_tb, compute_dbu FROM mesh.domain_states")
    states = query("SELECT product_id, env, version FROM mesh.product_states")
    months = [r["month"] for r in query("SELECT DISTINCT month FROM mesh.cost_monthly ORDER BY month")]
    latest_cost = {r["domain_id"]: r["amount"] for r in query(
        "SELECT domain_id, sum(amount) AS amount FROM mesh.cost_monthly WHERE month=(SELECT max(month) FROM mesh.cost_monthly) GROUP BY domain_id")}
    pending_access = query("SELECT id FROM mesh.approvals WHERE kind='Access' AND status='Pending'")
    resolved = query("SELECT id, title FROM mesh.incidents WHERE status='Resolved'")
    in_env = {(s["product_id"], s["env"]) for s in states}

    with db.connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            for pl in pls:
                sla = pl["sla"].lower()
                freq = "15 Minutes" if "real" in sla else "Hourly" if "hour" in sla else "Weekly" if "week" in sla else "Daily"
                if pl["engine"] == "Airflow DAG" and freq == "Daily":
                    freq = "Event Driven"
                paused = pl["env"] == "DEV" and rnd.random() < 0.25
                mins = FREQ_MIN.get(freq)
                cur.execute("INSERT INTO mesh.pipeline_schedules(pipeline_id,frequency,paused,next_run) VALUES (%s,%s,%s,%s)",
                            (pl["id"], freq, paused, None if paused or not mins else now + dt.timedelta(minutes=rnd.randint(1, mins))))
                for day in range(14, 0, -1):
                    failed = (day == 1 and pl["status"] == "Failed") or rnd.random() < 0.06
                    dur = round(pl["duration_min"] * rnd.uniform(0.7, 1.4), 1)
                    cur.execute("INSERT INTO mesh.pipeline_runs(pipeline_id,started_at,duration_min,rows_processed,status) VALUES (%s,%s,%s,%s,%s)",
                                (pl["id"], now - dt.timedelta(days=day - 1, hours=rnd.randint(1, 6)), dur,
                                 0 if failed else int(pl["rows_per_hour"] * dur / 60), "Failed" if failed else "Succeeded"))

            for p in prods:
                for i in range(rnd.randint(1, 3)):
                    cur.execute("INSERT INTO mesh.consumers(product_id,kind,name,owner) VALUES (%s,%s,%s,%s)",
                                (p["id"], "Dashboard", f"{p['name']} {['Executive', 'Operational', 'Self-Service'][i]} Dashboard", f"{p['domain'].lower()}-bi@corp.com"))
                for i in range(rnd.randint(0, 2)):
                    cur.execute("INSERT INTO mesh.consumers(product_id,kind,name,owner) VALUES (%s,%s,%s,%s)",
                                (p["id"], "API", f"/api/v{i + 1}/{p['name'].lower()}", f"{p['domain'].lower()}-api@corp.com"))
                team = rnd.choice(doms)["name"]
                cur.execute("INSERT INTO mesh.consumers(product_id,kind,name,owner) VALUES (%s,%s,%s,%s)",
                            (p["id"], "Team", f"{team} Analytics", f"{team.lower()}-analytics@corp.com"))

            for g, members in GROUP_MEMBERS.items():
                cur.executemany("INSERT INTO mesh.group_members(group_name,principal) VALUES (%s,%s)", [(g, m) for m in members])

            def grant(principal, ptype, pid, env, role):
                last = None if rnd.random() < 0.1 else now - dt.timedelta(days=rnd.randint(0, 150), hours=rnd.randint(0, 23))
                cur.execute("INSERT INTO mesh.access_grants(principal,principal_type,product_id,env,role,last_access,granted_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (principal, ptype, pid, env, role, last, now - dt.timedelta(days=rnd.randint(160, 400))))

            for env in ["PROD", "UAT"]:
                for p in prods:
                    if (p["id"], env) not in in_env:
                        continue
                    for g, (dom, role) in GROUP_GRANTS.items():
                        if p["domain"] == dom:
                            grant(g, "Group", p["id"], env, role)
                    grant("platform-admins", "Group", p["id"], env, "Owner")
                    grant(f"sp-{p['domain'].lower()}-etl", "Service Principal", p["id"], env, "Contributor")
                    if p["domain"] == "Sales":
                        grant("john.doe@corp.com", "User", p["id"], env, "Reader")
                    if rnd.random() < 0.35:
                        grant(rnd.choice(OPS_USERS[:5]), "User", p["id"], env, rnd.choice(["Reader", "Reader", "Contributor"]))

            for _ in range(80):
                p = rnd.choice(prods)
                action = rnd.choices(["READ", "GRANT", "REVOKE", "ROLE_CHANGE"], [14, 2, 1, 1])[0]
                who = rnd.choice(OPS_USERS[:6] + [f"sp-{p['domain'].lower()}-etl"])
                detail = {"READ": "SELECT on gold table", "GRANT": "Reader granted", "REVOKE": "Access revoked after review",
                          "ROLE_CHANGE": "Reader -> Contributor"}[action]
                cur.execute("INSERT INTO mesh.access_audit(principal,action,object_name,env,detail,created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                            (who, action, p["name"], rnd.choice(["PROD", "PROD", "PROD", "UAT"]), detail, now - dt.timedelta(minutes=rnd.randint(10, 60 * 24 * 30))))
            for a in pending_access:
                cur.execute("INSERT INTO mesh.access_workflow(approval_id,stage) VALUES (%s,%s)", (a["id"], rnd.choice(["Steward Approval", "Security Approval"])))

            for s in dstates:
                for m, month in enumerate(months):
                    f = 0.8 + 0.04 * m
                    prod = s["env"] == "PROD"
                    cur.execute("INSERT INTO mesh.usage_monthly VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                (s["domain_id"], s["env"], month, round(s["compute_dbu"] * f * rnd.uniform(0.95, 1.05)),
                                 round(s["storage_tb"] * (0.85 + 0.03 * m), 2), int(rnd.randint(20_000, 400_000) * f * (1 if prod else 0.05)),
                                 int(rnd.randint(5_000, 90_000) * f * (1 if prod else 0.1))))

            for d in doms:
                st = sum(s["storage_tb"] for s in dstates if s["domain_id"] == d["id"])
                cp = sum(s["compute_dbu"] for s in dstates if s["domain_id"] == d["id"])
                tight = d["name"] == "Marketing"
                cur.executemany("INSERT INTO mesh.quotas(domain_id,resource,unit,allocated,used) VALUES (%s,%s,%s,%s,%s)", [
                    (d["id"], "Storage", "TB", round(st * (1.05 if tight else rnd.uniform(1.2, 1.6))), None),
                    (d["id"], "Compute", "DBU/month", round(cp * rnd.uniform(1.1, 1.5), -2), None),
                    (d["id"], "Catalogs", "catalogs", 6, rnd.randint(2, 6)),
                    (d["id"], "Workspaces", "workspaces", 4, 4),
                    (d["id"], "Pipelines", "pipelines", 12, None),
                    (d["id"], "Monthly Budget", "USD", round(latest_cost.get(d["id"], 0) * (0.97 if tight else rnd.uniform(1.05, 1.3)), -2), None),
                ])

            schema_notes = ["Added column region_code", "Widened amount to DECIMAL(18,4)", "Renamed cust_id to customer_id", "No schema change",
                            "Added column _ingest_ts", "Dropped deprecated column legacy_flag"]
            quality_notes = ["Added not-null rule on business key", "Raised completeness threshold to 99.5%", "No quality rule change",
                             "Added freshness check (60 min)", "Added duplicate check on business key"]
            contract_notes = ["No contract change", "SLA tightened to hourly", "Added consumer Marketing", "Bumped contract to 1.1 (minor)"]
            for p in prods:
                top = max(int(s["version"].split(".")[1]) for s in states if s["product_id"] == p["id"])
                for v in range(top + 1):
                    cur.execute("""INSERT INTO mesh.artifact_versions(object_type,name,version,schema_changes,quality_changes,contract_changes,released_by,released_at)
                                   VALUES ('Product',%s,%s,%s,%s,%s,%s,%s)""",
                                (p["name"], f"v1.{v}", "Initial schema" if v == 0 else rnd.choice(schema_notes), "Baseline rules" if v == 0 else rnd.choice(quality_notes),
                                 "Contract 1.0" if v == 0 else rnd.choice(contract_notes), rnd.choice(OPS_USERS[:5]), now - dt.timedelta(days=(top - v + 1) * rnd.randint(12, 30))))

            alerts = [
                ("PROD", "Pipeline", "Critical", "campaignperformance_prod_pipeline", "Pipeline failed at Silver stage (3 retries exhausted)", "Open"),
                ("PROD", "Pipeline", "Critical", "churnsignals_prod_pipeline", "Out of memory on Gold aggregation", "Open"),
                ("PROD", "Product", "Major", "Customer360", "Freshness SLA (60 min) breached", "Acknowledged"),
                ("PROD", "Storage", "Major", "Marketing domain", "Storage quota above 90%", "Open"),
                ("PROD", "API", "Minor", "/api/v1/audiencesegments", "p95 latency 1.8s above 1.0s target", "Open"),
                ("PROD", "Platform", "Information", "adb-prod", "Databricks runtime 16.4 LTS available", "Open"),
                ("PROD", "Product", "Minor", "AudienceSegments", "Duplicate audience IDs detected (0.4%)", "Acknowledged"),
                ("PROD", "Platform", "Major", "Unity Catalog", "Metastore audit log delivery delayed", "Resolved"),
                ("UAT", "Pipeline", "Major", "salesforecast_uat_pipeline", "Weekly run late by 6 hours", "Open"),
                ("UAT", "Storage", "Information", "UAT workspace", "Storage growth 12% month over month", "Open"),
                ("SIT", "Platform", "Major", "Fabric connection", "Service credential expired", "Open"),
                ("DEV", "Pipeline", "Minor", "costallocation_dev_pipeline", "Schedule paused for 7 days", "Open"),
            ]
            for env, cat, sev, src, msg, status in alerts:
                cur.execute("INSERT INTO mesh.alerts(env,category,severity,source,message,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (env, cat, sev, src, msg, status, now - dt.timedelta(minutes=rnd.randint(5, 60 * 48))))
            for inc in resolved:
                cur.execute("INSERT INTO mesh.postmortems(incident_id,summary,root_cause,actions,author) VALUES (%s,%s,%s,%s,%s)",
                            (inc["id"], inc["title"], "Upstream ERP extract delivered null supplier keys after a source schema change",
                             "Added not-null expectation; added schema change alert on source", "eva.steward@corp.com"))
    log.info("Seeded Operate workspace state")


PROVISION_ITEMS = ["Databricks Workspace Access", "Unity Catalog Permissions", "Git Repository", "CI/CD Pipeline", "Monitoring Dashboard"]
CHECKLIST_ITEMS = ["Team Registered", "Roles Assigned", "Security Approved", "Workspace Created", "Training Completed"]


def _seed_mgmt():
    """Seed the Manage workspace state (teams, product onboarding, governance, platform services, configuration)."""
    rnd = random.Random(11)
    now = dt.datetime.now(dt.timezone.utc)

    def iso(d):
        return d.strftime("%Y-%m-%dT%H:%M:%SZ")

    doms = {d["name"]: d for d in query("SELECT * FROM mesh.domains")}
    prods = query("SELECT id, name, lifecycle, certified, sla, tags, domain_id FROM mesh.products ORDER BY id")
    dname = {d["id"]: n for n, d in doms.items()}
    teams = [(f"{n} Data Team", f"{n} BU", n, d["owner"], d["steward"], f"{n.lower()}.lead@corp.com", f"{n.lower()}.po@corp.com", "Active")
             for n, d in doms.items()]
    teams.append(("Customer Analytics", "Retail Banking", "Customer", "john.smith@corp.com", "sarah.parker@corp.com", "david.chen@corp.com",
                  "maria.bi@corp.com", "Onboarding"))

    with db.connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            for name, bu, dom, owner, steward, lead, po, status in teams:
                cur.execute("""INSERT INTO mesh.teams(name,business_unit,domain_id,owner,steward,tech_lead,product_owner,status,created_at)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                            (name, bu, doms[dom]["id"], owner, steward, lead, po, status, now - dt.timedelta(days=rnd.randint(5, 400))))
                tid = cur.fetchone()["id"]
                members = [(owner, "Domain Owner"), (steward, "Data Steward"), (lead, "Data Engineer"), (po, "Data Product Owner")]
                members += [(f"{dom.lower()}.eng{i}@corp.com", "Data Engineer") for i in range(rnd.randint(1, 3))]
                members += [(f"{dom.lower()}.analyst{i}@corp.com", "Data Consumer") for i in range(rnd.randint(1, 4))]
                members.append(("governance@corp.com", "Governance Reviewer"))
                cur.executemany("INSERT INTO mesh.team_members(team_id,member,persona) VALUES (%s,%s,%s)", [(tid, m, p) for m, p in members])
                active = status == "Active"
                cur.executemany("INSERT INTO mesh.team_provisioning(team_id,item,status) VALUES (%s,%s,%s)",
                                [(tid, i, "Provisioned" if active or k < 2 else "Not Started") for k, i in enumerate(PROVISION_ITEMS)])
                cur.executemany("INSERT INTO mesh.team_checklist(team_id,item,done) VALUES (%s,%s,%s)",
                                [(tid, i, active or k < 2) for k, i in enumerate(CHECKLIST_ITEMS)])

            for p in prods:
                tags = p["tags"] or []
                cls = "PII" if "pii" in tags else "Sensitive Financial" if "sox" in tags or dname[p["domain_id"]] == "Finance" else "Internal"
                if p["name"] in ("CostAllocation", "SupplierKPIs"):
                    cls = None
                stage = {"Published": "Published", "Approved": "Governance Review", "Review": "Data Steward Review"}.get(p["lifecycle"], "Owner Review")
                level = "Certified Enterprise Product" if p["certified"] and "sox" in tags else "Gold" if p["certified"] else rnd.choice(["Bronze", "Silver"])
                cstatus = "Certified" if p["certified"] else {"DealIntelligence": "Under Review", "ChurnSignals": "Requested", "AudienceSegments": "Expired"}.get(p["name"])
                dom = dname[p["domain_id"]].lower()
                cur.execute("""INSERT INTO mesh.product_onboarding(product_id,use_cases,consumers,target_tables,refresh_frequency,retention_policy,
                               classification,review_stage,cert_level,cert_status,expected_volume,usage_limits,access_policy) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (p["id"], None if p["name"] == "CostAllocation" else f"{p['name']} reporting and analytics", "Finance BI, Executive dashboards",
                             f"{dom}.gold.{p['name'].lower()}", p["sla"], "10 Years" if dom == "finance" else "7 Years" if cls == "PII" else "3 Years",
                             cls, stage, level, cstatus, f"{rnd.randint(1, 40)}M rows/day", f"{rnd.choice([500, 1000, 5000])} queries/day",
                             "Restricted - steward approval" if cls in ("PII", "Sensitive Financial") else "Request & approve"))

            cur.executemany("INSERT INTO mesh.gov_rules(kind,area,name,rule,value,status,owner) VALUES (%s,%s,%s,%s,%s,'Active',%s)", [
                ("Policy", "Retention", "PII Retention", "Data classified PII is retained then purged", "7 Years", "privacy@corp.com"),
                ("Policy", "Retention", "Financial Data", "Ledger and revenue data retained for audit", "10 Years", "legal@corp.com"),
                ("Policy", "Archival", "Cold Partition Archival", "Partitions untouched for 24 months move to archive tier", "24 Months", "platform@corp.com"),
                ("Policy", "Classification", "Mandatory Classification", "Every gold table carries a classification tag", "Required", "governance@corp.com"),
                ("Policy", "Sharing", "External Sharing", "Delta Sharing allowed for Public/Internal only; Confidential needs DPO approval", "Restricted", "privacy@corp.com"),
                ("Standard", "Naming Convention", "Catalog Naming", "catalog.domain_layer.entity in snake_case", "v2", "platform@corp.com"),
                ("Standard", "Data Modeling", "Gold Modeling", "Gold layer uses star schemas with conformed dimensions", "v1", "architecture@corp.com"),
                ("Standard", "Table Structure", "Mandatory Columns", "Tables include business_date, _source and _updated_at", "v1", "platform@corp.com"),
                ("Standard", "API Standards", "Data APIs", "REST, versioned /api/vN, OpenAPI 3.1, OAuth2", "v1", "architecture@corp.com"),
                ("Standard", "Product Templates", "Data Product Template", "README, contract, quality rules, CI/CD and runbook", "v2", "platform@corp.com"),
            ])
            cur.executemany("INSERT INTO mesh.compliance_checks(framework,name,requirement,status,owner,last_assessed) VALUES (%s,%s,%s,%s,%s,%s)", [
                (f, n, r, s, o, now - dt.timedelta(days=rnd.randint(1, 60))) for f, n, r, s, o in [
                    ("Internal Policy", "PII Column Masking", "PII columns masked for non-privileged groups", "Compliant", "governance@corp.com"),
                    ("Internal Policy", "Data Retention", "Retention policies applied to all gold tables", "At Risk", "legal@corp.com"),
                    ("Internal Policy", "Mandatory Classification", "All products classified", "Non-Compliant", "governance@corp.com"),
                    ("Internal Policy", "Naming Standard v2", "Catalog objects follow naming standard", "Compliant", "platform@corp.com"),
                    ("Regulatory", "OSFI B-13", "Technology and cyber risk management", "Compliant", "risk@corp.com"),
                    ("Regulatory", "PIPEDA / CASL", "Consent captured and honoured for marketing use", "At Risk", "privacy@corp.com"),
                    ("Regulatory", "GDPR Right to Erasure", "Erasure requests fulfilled within 30 days", "Compliant", "privacy@corp.com"),
                    ("Regulatory", "SOX ITGC", "Change management on financial data products", "Compliant", "audit@corp.com"),
                    ("Security Control", "Encryption at Rest", "Customer-managed keys on all storage", "Compliant", "security@corp.com"),
                    ("Security Control", "Quarterly Access Reviews", "All groups reviewed every 90 days", "Non-Compliant", "security@corp.com"),
                    ("Security Control", "Secret Rotation", "Service principal secrets rotated every 90 days", "At Risk", "security@corp.com"),
                    ("Security Control", "Audit Logging", "Workspace and Unity Catalog audit logs delivered", "Compliant", "security@corp.com"),
                ]])

            services = []
            for src, sched, status in [("SAP", "Hourly", "Healthy"), ("Oracle", "Daily", "Healthy"), ("Salesforce", "15 Minutes", "Healthy"),
                                       ("Snowflake", "Daily", "Warning"), ("Fabric", "Hourly", "Error"), ("Kafka", "Streaming", "Healthy"),
                                       ("REST APIs", "Hourly", "Healthy"), ("Files", "Event Driven", "Healthy")]:
                services.append(("Ingestion", f"{src} Connector", status, "platform-ingestion@corp.com",
                                 {"source_type": src, "schedule": sched, "last_sync": iso(now - dt.timedelta(minutes=rnd.randint(5, 900))),
                                  "sla_min": 60 if sched in ("Hourly", "15 Minutes", "Streaming") else 1440, "records_24h": rnd.randint(50_000, 40_000_000)}))
            for name, cap in [("Delta Lake", 400), ("Unity Catalog", 5), ("Volumes", 60), ("Lakehouse Storage", 500), ("Lakebase", 2)]:
                used = round(cap * rnd.uniform(0.35, 0.92), 1)
                services.append(("Storage", name, "Warning" if used / cap > 0.85 else "Healthy", "platform-storage@corp.com",
                                 {"capacity_tb": cap, "used_tb": used, "retention": rnd.choice(["30 days time travel", "7 days time travel", "Policy based"]),
                                  "growth_pct": round(rnd.uniform(1, 9), 1), "cost_month": round(used * 23)}))
            for name, kind, size, state in [("shared-etl-cluster", "Clusters", "Standard_D16ds_v5", "Running"), ("bi-warehouse-pro", "SQL Warehouses", "Medium", "Running"),
                                            ("serverless-pool", "Serverless Pools", "Auto", "Running"), ("lakeflow-workflows", "Workflows", "Serverless", "Running"),
                                            ("nightly-jobs", "Jobs", "Standard_E8ds_v5", "Stopped"), ("ds-sandbox-cluster", "Clusters", "Standard_NC6s_v3", "Running")]:
                services.append(("Compute", name, "Healthy", "platform-compute@corp.com",
                                 {"type": kind, "size": size, "autoscale": kind != "Jobs", "min_workers": 1, "max_workers": rnd.choice([4, 8, 16]),
                                  "state": state, "cost_day": rnd.randint(40, 900)}))
            for name, objs in [("Unity Catalog", 4210), ("Business Glossary", 8), ("Metadata Sync", 1320), ("Lineage Collection", 14)]:
                services.append(("Catalog", name, "Healthy", "governance@corp.com",
                                 {"objects": objs, "coverage_pct": round(rnd.uniform(78, 99), 1), "last_sync": iso(now - dt.timedelta(minutes=rnd.randint(5, 600)))}))
            for name in ["Data Product Copilot", "Metadata Generation", "Schema Recommendation", "Auto Documentation", "LLM Gateway"]:
                reqs = rnd.randint(300, 40_000)
                services.append(("AI", name, "Healthy", "platform-ai@corp.com",
                                 {"requests_24h": reqs, "latency_ms": rnd.randint(250, 2400), "tokens_24h": reqs * rnd.randint(600, 2200),
                                  "cost_month": round(reqs * rnd.uniform(0.4, 1.6))}))
            cur.executemany("INSERT INTO mesh.platform_services(category,name,status,owner,details) VALUES (%s,%s,%s,%s,%s)",
                            [(c, n, s, o, Json(d)) for c, n, s, o, d in services])

            cur.executemany("INSERT INTO mesh.service_requests(category,item,team,requester,justification,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)", [
                (c, i, t, r, j, s, now - dt.timedelta(hours=rnd.randint(2, 200))) for c, i, t, r, j, s in [
                    ("Infrastructure", "New Workspace", "Customer Analytics", "david.chen@corp.com", "Dedicated analytics workspace", "Submitted"),
                    ("Data Services", "New Connector", "Sales Data Team", "sales.lead@corp.com", "HubSpot marketing data", "Approved"),
                    ("AI Services", "Semantic Search", "Customer Data Team", "customer.po@corp.com", "Search over support tickets", "Fulfilled"),
                    ("Infrastructure", "New Catalog", "Finance Data Team", "finance.lead@corp.com", "Separate catalog for regulatory reporting", "Submitted"),
                    ("AI Services", "New Agent", "Marketing Data Team", "marketing.po@corp.com", "Campaign insights agent", "Rejected"),
                ]])
            cur.executemany("INSERT INTO mesh.platform_config(setting,value,category,description,updated_by) VALUES (%s,%s,%s,%s,'platform.admin@corp.com')", [
                ("default_region", "canadacentral", "General", "Default Azure region for new workspaces"),
                ("state_store", "Lakebase", "General", "System of record for mesh state"),
                ("max_workspaces_per_domain", "4", "General", "Workspace quota per domain"),
                ("require_contract_for_publish", "true", "Governance", "Block publishing without an active producer contract"),
                ("quality_threshold", "95", "Governance", "Minimum quality score for certification"),
                ("certification_validity_days", "365", "Governance", "Days before a certification expires"),
                ("pii_masking_default", "true", "Security", "Mask PII columns by default"),
                ("access_request_expiry_hours", "72", "Security", "Pending access requests expire after"),
                ("alert_email", "platform-ops@corp.com", "Notifications", "Operations alert distribution list"),
                ("teams_webhook_enabled", "false", "Notifications", "Post alerts to Microsoft Teams"),
            ])
    log.info("Seeded Manage workspace state")


TEST_SUITES = ["Unit", "System", "Integration", "Regression", "Data Validation"]


def _seed_build():
    """Seed the Build workspace state (models, rules, tests, releases, validation evidence)."""
    rnd = random.Random(23)
    now = dt.datetime.now(dt.timezone.utc)
    prods = query("""SELECT p.id, p.name, p.lifecycle, p.schema_def, d.name AS domain FROM mesh.products p
                     JOIN mesh.domains d ON d.id=p.domain_id ORDER BY p.id""")
    states = query("SELECT product_id, env, version FROM mesh.product_states")
    with db.connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            for p in prods:
                pid, name, dom, life = p["id"], p["name"].lower(), p["domain"].lower(), p["lifecycle"]
                cols = (p["schema_def"] or {}).get("columns", [])
                published = life == "Published"
                status = "Deployed" if published else "Draft" if life == "Draft" else "Validated"
                cur.executemany("INSERT INTO mesh.build_models(product_id,name,kind,layer,model_type,column_count,status) VALUES (%s,%s,%s,%s,%s,%s,%s)", [
                    (pid, f"{dom}.bronze.{name}_raw", "Table", "Bronze", "Physical", len(cols) + 3, status),
                    (pid, f"{dom}.silver.{name}_clean", "Table", "Silver", "Physical", len(cols) + 1, status),
                    (pid, f"{dom}.gold.fct_{name}", "Fact", "Gold", "Physical", len(cols), status),
                    (pid, f"{dom}.gold.dim_region", "Dimension", "Gold", "Physical", 4, status),
                    (pid, f"{dom}.gold.vw_{name}", "View", "Gold", "Logical", len(cols), status),
                    (pid, f"{p['name']} Semantic Model", "Schema", "Semantic", "Semantic", len(cols) + 2, status),
                ])
                key = cols[0]["name"] if cols else "id"
                cur.executemany("INSERT INTO mesh.build_rules(product_id,kind,category,name,expression,threshold,status) VALUES (%s,%s,%s,%s,%s,%s,'Active')", [
                    (pid, "Business", "Calculation", "Net amount", "amount - discount - refunds", None),
                    (pid, "Business", "Standardization", "Region codes", "map region to ISO 3166-2", None),
                    (pid, "Business", "Aggregation", "Daily rollup", "group by business_date, region", None),
                    (pid, "Quality", "Null Check", f"{key} not null", f"{key} IS NOT NULL", "100%"),
                    (pid, "Quality", "Duplicate Check", "Unique business key", f"count(distinct {key}) = count(*)", "100%"),
                    (pid, "Quality", "Threshold Check", "Row volume", "row_count between 0.8x and 1.2x of 7-day average", "+/-20%"),
                    (pid, "Quality", "Reference Validation", "Valid region", "region IN (ref.regions)", "99%"),
                ])
                for suite in TEST_SUITES:
                    for i in range(2):
                        st = "Passed" if published or (life != "Draft" and rnd.random() < 0.7) else "Not Run" if life == "Draft" else rnd.choice(["Failed", "Not Run"])
                        cur.execute("INSERT INTO mesh.build_tests(product_id,suite,name,status,duration_s,last_run) VALUES (%s,%s,%s,%s,%s,%s)",
                                    (pid, suite, f"{suite.lower().replace(' ', '_')}_{name}_{i + 1}", st, round(rnd.uniform(0.5, 90), 1),
                                     None if st == "Not Run" else now - dt.timedelta(hours=rnd.randint(1, 200))))
                prod_ver = next((s["version"] for s in states if s["product_id"] == pid and s["env"] == "PROD"), None)
                if published and prod_ver:
                    cur.execute("""INSERT INTO mesh.build_releases(product_id,version,status,stage,artifacts,notes,created_by,created_at)
                                   VALUES (%s,%s,'Published','Publish',%s,'Production release',%s,%s)""",
                                (pid, prod_ver, Json({"Tables": 4, "Views": 1, "Pipelines": 1, "Quality Rules": 4}), "release.manager@corp.com",
                                 now - dt.timedelta(days=rnd.randint(5, 60))))
                elif life in ("Review", "Approved"):
                    cur.execute("""INSERT INTO mesh.build_releases(product_id,version,status,stage,artifacts,notes,created_by)
                                   VALUES (%s,'v1.0','In Approval',%s,%s,'First production release',%s)""",
                                (pid, rnd.choice(["Data Steward", "Platform Team"]), Json({"Tables": 4, "Views": 1, "Pipelines": 1, "Quality Rules": 4}), "release.manager@corp.com"))
                for env in [s["env"] for s in states if s["product_id"] == pid and s["env"] in ("UAT", "PROD")]:
                    snap = [{"name": c["name"], "type": c["type"]} for c in cols]
                    if env == "PROD" and p["name"] == "ChurnSignals" and len(snap) > 2:
                        snap.pop(-2)
                    if env == "PROD" and p["name"] == "Customer360":
                        snap = [dict(c, type="VARCHAR(320)") if c["name"] == "customer_email" else c for c in snap]
                    cur.execute("INSERT INTO mesh.build_schema_snapshots(product_id,env,schema_cols) VALUES (%s,%s,%s)", (pid, env, Json(snap)))
                    rows = rnd.randint(200_000, 20_000_000)
                    drift = env == "PROD" and p["name"] in ("CampaignPerformance", "ChurnSignals")
                    amount = round(rows * rnd.uniform(20, 300), 2)
                    for ctype, metric, src, tgt in [
                        ("Record Count", "rows", rows, rows - (rnd.randint(1_000, 50_000) if drift else 0)),
                        ("Aggregation", "sum(amount)", amount, round(amount * (0.97 if drift else 1), 2)),
                        ("Source-to-Target Reconciliation", "matched keys %", 100, 96.4 if drift else 100),
                        ("Historical Consistency", "days with data (90d)", 90, 88 if drift else 90),
                    ]:
                        ok = src == 0 or abs(src - tgt) / src <= 0.005
                        cur.execute("INSERT INTO mesh.build_data_checks(product_id,env,check_type,metric,source_value,target_value,status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                    (pid, env, ctype, metric, src, tgt, "Passed" if ok else "Failed"))
                checks = [("intake", "Business requirements approved", life != "Draft"), ("source", "Connectivity established", p["name"] != "CostAllocation"),
                          ("source", "Data profiling completed", life != "Draft"), ("environment", "Compute resources assigned", p["name"] != "SupplierKPIs")]
                if published:
                    checks += [("signoff", s, True) for s in ("Security Team", "Platform Team", "Data Product Owner")]
                cur.executemany("INSERT INTO mesh.build_checks(product_id,area,item,status,checked_by) VALUES (%s,%s,%s,%s,%s)",
                                [(pid, a, i, "Passed" if ok else "Pending", "platform.admin@corp.com" if ok else None) for a, i, ok in checks])
    log.info("Seeded Build workspace state")

"""Smoke test: exercise every API endpoint against a running server."""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
fails = []


def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            print(f"OK   {method} {path}")
            return json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        fails.append(path)
        print(f"FAIL {method} {path} -> {e.code} {e.read()[:300]}")


call("POST", "/api/admin/reseed")
for env in ["PROD", "DEV"]:
    for p in ["/api/health", "/api/context", f"/api/home?env={env}", "/api/domains", f"/api/products?env={env}",
              f"/api/products?env={env}&q=customer&domains=Customer,Sales&certified=true", "/api/glossary", f"/api/insights?env={env}",
              f"/api/approvals?env={env}&status=Pending", "/api/approvals?mine=true", f"/api/topology?env={env}", "/api/contracts",
              "/api/contracts?product_id=1", f"/api/pipelines?env={env}", "/api/deployments", f"/api/deployments?env={env}",
              f"/api/operate?env={env}", f"/api/manage?env={env}", f"/api/state?env={env}", "/api/catalog"]:
        call("GET", p)
call("GET", "/api/products/1?env=PROD")
for env in ["PROD", "UAT", "DEV"]:
    for p in ["dashboard", "pipelines", "availability", "access", "access/effective?principal=john.doe@corp.com", "budget", "artifacts",
              "monitoring", "incidents", "environments", "sla?by=product", "sla?by=domain", "sla?by=team", "sla?by=environment"]:
        call("GET", f"/api/ops/{p}{'&' if '?' in p else '?'}env={env}")
call("POST", "/api/ops/pipelines/1/schedule", {"action": "pause"})
call("POST", "/api/ops/pipelines/1/schedule", {"action": "reschedule", "frequency": "Hourly"})
call("POST", "/api/ops/backfills", {"pipeline_id": 1, "kind": "Historical Reload", "start_date": "2026-09-01", "end_date": "2026-09-30"})
pending = [r for r in call("GET", "/api/ops/access?env=PROD")["requests"] if r["status"] == "Pending"]
for _ in range(3):
    if call("POST", f"/api/ops/access/requests/{pending[0]['id']}/advance")["stage"] == "Provision Access":
        break
grant = call("GET", "/api/ops/access?env=PROD")["grants"][0]
call("POST", f"/api/ops/access/grants/{grant['id']}/revoke")
call("POST", "/api/ops/groups/finance-consumers/members", {"principal": "new.user@corp.com"})
call("POST", "/api/ops/groups/finance-consumers/members", {"principal": "new.user@corp.com", "remove": True})
q = call("GET", "/api/ops/budget?env=PROD")["quotas"][0]
call("PUT", f"/api/ops/quotas/{q['id']}", {"allocated": 99})
call("POST", "/api/ops/artifacts/2/state", {"state": "Deprecated"})
call("POST", "/api/ops/artifacts/2/state", {"state": "Active"})
call("POST", "/api/ops/alerts/1/action", {"action": "acknowledge"})
inc = call("POST", "/api/ops/incidents", {"kind": "Security Issue", "title": "Smoke incident", "severity": "High", "product_id": 1, "env": "PROD"})
call("POST", f"/api/ops/incidents/{inc['id']}/postmortem", {"summary": "s", "root_cause": "r", "actions": "a"})
for p in ["teams", "products", "governance?env=PROD", "governance?env=DEV", "platform", "config"]:
    call("GET", f"/api/mgmt/{p}")
t = call("POST", "/api/mgmt/teams", {"name": "Smoke Team", "business_unit": "BU", "domain_id": 1, "owner": "o@corp.com"})
call("POST", f"/api/mgmt/teams/{t['id']}/domain", {"domain_id": 2})
m = call("POST", f"/api/mgmt/teams/{t['id']}/members", {"member": "m@corp.com", "persona": "Data Engineer"})
call("POST", f"/api/mgmt/teams/{t['id']}/members/{m['id']}/remove")
call("POST", f"/api/mgmt/teams/{t['id']}/provision", {"item": "all"})
for item in ["Security Approved", "Training Completed"]:
    call("POST", f"/api/mgmt/teams/{t['id']}/checklist", {"item": item, "done": True})
call("POST", f"/api/mgmt/teams/{t['id']}/activate")
call("PUT", "/api/mgmt/products/3/onboarding", {"classification": "Internal", "use_cases": "Chargeback"})
for _ in range(5):
    call("POST", "/api/mgmt/products/3/review", {"decision": "approve"})
for a in ["request", "review", "certify", "expire"]:
    call("POST", "/api/mgmt/products/3/certification", {"action": a, "level": "Silver"})
call("POST", "/api/mgmt/governance/rules", {"kind": "Standard", "area": "API Standards", "name": "Smoke std", "rule": "r", "value": "v1"})
call("POST", "/api/mgmt/governance/compliance/1", {"status": "At Risk"})
svc = call("POST", "/api/mgmt/platform/services", {"name": "Smoke Connector", "source_type": "Kafka", "schedule": "Hourly", "sla_min": 60})
call("POST", f"/api/mgmt/platform/services/{svc['id']}/action", {"action": "sync"})
comp = [s for s in call("GET", "/api/mgmt/platform")["services"] if s["category"] == "Compute"][0]
call("POST", f"/api/mgmt/platform/services/{comp['id']}/action", {"action": "stop"})
call("POST", f"/api/mgmt/platform/services/{comp['id']}/action", {"action": "autoscale"})
req = call("POST", "/api/mgmt/platform/requests", {"item": "New Catalog", "team": "Smoke Team", "justification": "j"})
call("POST", f"/api/mgmt/platform/requests/{req['id']}/action", {"action": "approve"})
call("POST", f"/api/mgmt/platform/requests/{req['id']}/action", {"action": "fulfil"})
call("PUT", "/api/mgmt/config/quality_threshold", {"value": "96"})
prods = call("GET", "/api/build/products")
for p in prods:
    for path in ["readiness", "develop", "publish", "validation?env=PROD", "validation?env=DEV", "iam?env=PROD", "iam?env=UAT", "runbook"]:
        call("GET", f"/api/build/products/{p['id']}/{path}")
call("GET", "/api/build/releases")
pid = next(p["id"] for p in prods if p["name"] == "SalesForecast")
call("POST", f"/api/build/products/{pid}/checks", {"area": "source", "item": "Connectivity established", "status": "Passed"})
call("POST", f"/api/build/products/{pid}/models", {"name": "sales.gold.dim_segment", "kind": "Dimension", "layer": "Gold", "model_type": "Physical", "column_count": 5})
call("POST", f"/api/build/products/{pid}/rules", {"kind": "Quality", "category": "Null Check", "name": "segment not null", "expression": "segment IS NOT NULL", "threshold": "100%"})
call("POST", f"/api/build/products/{pid}/tests/run", {"suite": "All"})
rel = call("POST", f"/api/build/products/{pid}/releases", {"version": "v9.9", "notes": "smoke"})
for _ in range(4):
    call("POST", f"/api/build/releases/{rel['id']}/decision", {"decision": "approve"})
call("POST", f"/api/build/products/{pid}/validation/reconcile", {"env": "UAT"})
call("POST", f"/api/build/products/{pid}/iam/grant", {"principal": "smoke@corp.com", "role": "Reader", "env": "UAT"})
call("POST", f"/api/build/products/{pid}/iam/consumer-tests", {"env": "UAT"})
call("POST", f"/api/build/products/{pid}/checks", {"area": "signoff", "item": "Security Team", "status": "Passed"})
call("PUT", "/api/context", {"env": "UAT", "region": "eastus", "state_source": "Lakebase"})
call("POST", "/api/access-requests", {"product_id": 1, "env": "PROD", "justification": "test"})
call("POST", "/api/approvals/1/decision", {"decision": "Approved"})
call("POST", "/api/approvals/3/decision", {"decision": "Approved"})
call("POST", "/api/approvals/4/decision", {"decision": "Approved"})
d = call("POST", "/api/domains", {"name": "SmokeDomain", "owner": "a@b.com"})
call("PUT", f"/api/domains/{d['id']}", {"owner": "x@b.com", "steward": "s", "custodian": "c"})
p = call("POST", "/api/products", {"name": "SmokeProduct", "domain_id": 1, "tags": ["a", "b"], "columns": [{"name": "id", "type": "BIGINT"}], "publish": True})
call("POST", "/api/contracts", {"product_id": p["id"], "kind": "Consumer", "consumer_domain_id": 2})
pl = call("POST", "/api/pipelines", {"name": "smoke_pipeline", "product_id": p["id"], "env": "DEV"})
call("POST", f"/api/pipelines/{pl['id']}/rerun")
for k in ["sql", "pyspark", "dbt", "contract", "docs"]:
    call("POST", "/api/generate", {"product_id": 1, "kind": k})
call("POST", "/api/deployments", {"object_type": "Product", "object_name": "SmokeProduct", "version": "v0.2", "target_env": "SIT"})
dep = call("POST", "/api/deployments", {"object_type": "Product", "object_name": "SmokeProduct", "version": "v0.2", "target_env": "PROD"})
call("POST", f"/api/deployments/{dep['id']}/rollback")
for a in ["assign", "escalate", "ticket", "resolve"]:
    call("POST", "/api/incidents/1/action", {"action": a})
pol = call("POST", "/api/policies", {"name": "Smoke Policy"})
call("POST", f"/api/policies/{pol['id']}/advance")
call("POST", "/api/products/1/lifecycle", {"lifecycle": "Published", "certify": True})
call("POST", "/api/groups/1/review")
call("POST", "/api/state/detect-drift", {"env": "PROD"})
call("POST", "/api/state/sync", {"env": "PROD"})
call("POST", "/api/admin/reseed")
print("FAILURES:", fails or "none")
sys.exit(1 if fails else 0)

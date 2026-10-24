/* Data Mesh Control Plane - Foundry-inspired single pane UI (vanilla JS, Lakebase-backed State API) */
const S = { ctx: null, env: "PROD", region: "canadacentral", source: "Lakebase", filters: { q: "", domains: [], certified: null }, opsF: {} };
const $ = (sel) => document.querySelector(sel);
const view = () => $("#view");

// ------------------------------------------------------------------ utilities
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n, d = 0) => (n === null || n === undefined ? "-" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const money = (n) => (n === null || n === undefined ? "-" : "$" + Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 }));
const compact = (n) => (n === null || n === undefined ? "-" : Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n));
function ago(ts) {
  if (!ts) return "-";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}
const TONE = {
  Healthy: "ok", Succeeded: "ok", Completed: "ok", Running: "info", Synced: "ok", Pass: "ok", Approved: "ok", Published: "ok", Active: "ok", Enforced: "ok", Resolved: "ok",
  Warning: "warn", Warn: "warn", Pending: "warn", Queued: "neutral", Review: "warn", Investigating: "warn", "In Progress": "info", "In Review": "warn", Staged: "info", Medium: "warn",
  Error: "err", Failed: "err", Fail: "err", Drift: "err", Rejected: "err", "Rolled Back": "err", Escalated: "err", Open: "err", Overdue: "err", Critical: "err", High: "err",
  Draft: "neutral", Retired: "neutral", Low: "neutral",
  Delayed: "warn", "At Risk": "warn", Breached: "err", "On Time": "ok", Acknowledged: "info", Major: "warn", Minor: "info", Information: "neutral",
  Expired: "neutral", Deprecated: "warn", Archived: "neutral", "Pre-release": "info", Paused: "neutral", Current: "info",
  "Steward Approval": "info", "Security Approval": "info", "Provision Access": "ok", Reader: "neutral", Contributor: "info", Owner: "warn",
  READ: "neutral", GRANT: "ok", REVOKE: "err", ROLE_CHANGE: "warn",
  "Not Started": "neutral", Provisioned: "ok", Onboarding: "info", Submitted: "info", Fulfilled: "ok", Stopped: "neutral", Requested: "info",
  "Under Review": "warn", Certified: "ok", Revoked: "err", Complete: "ok", Incomplete: "warn", Missing: "err", Passed: "ok", Compliant: "ok",
  "Non-Compliant": "err", "Owner Review": "info", "Data Steward Review": "info", "Security Review": "info", "Governance Review": "info", Publish: "info",
  "Cross-domain": "info", "Intra-domain": "neutral",
  "In Development": "info", Testing: "warn", "Ready to Publish": "ok", "Not Run": "neutral", "Ready for Build": "ok", "Not Ready": "err", Deployed: "ok",
  Validated: "info", "In Approval": "warn", Packaged: "info", "Drift Detected": "err", Match: "ok", "Type Changed": "warn", Unexpected: "warn",
  "Not Required": "neutral", "Over-privileged": "warn", "No snapshot": "neutral", "No rules": "neutral", "Ready for Operate handover": "ok", "Not ready": "err",
};
const pill = (s) => `<span class="pill ${TONE[s] || "neutral"}">${esc(s)}</span>`;
const dot = (s) => `<span class="dot ${TONE[s] || "neutral"}"></span>`;
const envName = (code) => (S.ctx?.environments.find((e) => e.code === code) || {}).name || code;

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " error" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast hidden"), 3500);
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let data = null;
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) {
    const msg = (data && data.detail) || res.statusText;
    toast(msg, true);
    throw new Error(msg);
  }
  return data;
}
const post = (path, body) => api(path, { method: "POST", body: body || {} });
const E = () => encodeURIComponent(S.env);

function table(rows, cols, opts = {}) {
  if (!rows || !rows.length) return `<div class="empty">${opts.empty || "No records"}</div>`;
  return `<table><thead><tr>${cols.map((c) => `<th>${c[0]}</th>`).join("")}</tr></thead><tbody>${rows
    .map((r, i) => `<tr ${opts.onclick ? `class="click" data-i="${i}" data-tbl="${opts.onclick}"` : ""}>${cols.map((c) => `<td>${c[1](r)}</td>`).join("")}</tr>`)
    .join("")}</tbody></table>`;
}
function kpi(label, value, delta) {
  return `<div class="card kpi"><div class="label">${label}</div><div class="value">${value}</div>${delta ? `<div class="delta">${delta}</div>` : ""}</div>`;
}
function hbars(rows, labelKey, valKey, fmt = num, color) {
  const max = Math.max(1, ...rows.map((r) => r[valKey] || 0));
  return rows.map((r) => `<div class="hbar"><span>${esc(r[labelKey])}</span><div class="bar"><span style="width:${(100 * (r[valKey] || 0)) / max}%;${color ? "background:" + color : ""}"></span></div><span style="text-align:right">${fmt(r[valKey])}</span></div>`).join("");
}
function colChart(rows, labelFn, valKey, h = 150) {
  if (!rows.length) return '<div class="empty">No data</div>';
  const w = 560, pad = 28, bw = (w - pad * 2) / rows.length;
  const max = Math.max(1, ...rows.map((r) => r[valKey]));
  const bars = rows.map((r, i) => {
    const bh = ((h - 40) * r[valKey]) / max;
    const x = pad + i * bw + bw * 0.2, y = h - 22 - bh;
    return `<rect x="${x}" y="${y}" width="${bw * 0.6}" height="${bh}" rx="3" fill="#2272b4"/><text x="${x + bw * 0.3}" y="${y - 4}" text-anchor="middle" font-size="10" fill="#5f6b7a">${compact(r[valKey])}</text><text x="${x + bw * 0.3}" y="${h - 6}" text-anchor="middle" font-size="10" fill="#5f6b7a">${esc(labelFn(r))}</text>`;
  });
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">${bars.join("")}</svg>`;
}
const monthLbl = (r) => new Date(r.month + "T00:00:00").toLocaleString(undefined, { month: "short" });

function openDrawer(html) { $("#drawerBody").innerHTML = html; $("#drawer").classList.remove("hidden"); }
function closeDrawer() { $("#drawer").classList.add("hidden"); }

function tabs(items, active, base) {
  return `<div class="tabs">${items.map(([k, l]) => `<a href="#/${base}/${k}" class="${k === active ? "active" : ""}">${l}</a>`).join("")}</div>`;
}
function head(title, sub, right = "") {
  return `<div class="pagehead"><div><h1>${title}</h1><div class="sub">${sub}</div></div><div class="btnrow">${right}</div></div>`;
}
function envBanner(extra = "") {
  const e = S.ctx.environments.find((x) => x.code === S.env) || {};
  const r = S.ctx.regions.find((x) => x.code === S.region) || {};
  return `<div class="envbanner"><span>Environment: <b>${esc(e.name)}</b></span><span>${dot(e.health)}${esc(e.health)}</span><span class="muted">Region: ${esc(r.name)}</span><span class="muted">State source: ${esc(S.source)}</span>${extra}</div>`;
}

// ------------------------------------------------------------------ context panel
async function loadContext() {
  for (let i = 0; i < 30; i++) {
    const h = await fetch("/api/health").then((r) => r.json()).catch(() => ({ status: "error" }));
    if (h.status === "ready") break;
    if (h.status === "error" || h.status === "not_configured") {
      view().innerHTML = `<div class="card"><h3>Lakebase state store unavailable</h3><p>${esc(h.error)}</p><p class="muted">Attach a Lakebase (postgres) resource to this app and redeploy.</p></div>`;
      $("#stateFoot").textContent = "Lakebase: " + h.status;
      return false;
    }
    view().innerHTML = `<div class="loading">Initializing Lakebase state store (${i + 1})...</div>`;
    await new Promise((r) => setTimeout(r, 2000));
  }
  S.ctx = await api("/api/context");
  S.env = S.ctx.prefs.env; S.region = S.ctx.prefs.region; S.source = S.ctx.prefs.state_source;
  $("#userName").textContent = S.ctx.user;
  $("#notifBadge").textContent = (S.ctx.notifications.approvals || 0) + (S.ctx.notifications.incidents || 0);
  $("#stateFoot").innerHTML = `Lakebase connected<br><span class="small">${esc(S.ctx.lakebase_endpoint || "")}</span>`;
  renderPanel();
  return true;
}
function renderPanel() {
  $("#envList").innerHTML = S.ctx.environments.map((e) => `<li data-env="${e.code}" class="${e.code === S.env ? "sel" : ""}"><span>${dot(e.health)}${esc(e.name)}</span>${e.code === S.env ? '<span class="check">&#10003;</span>' : ""}</li>`).join("");
  $("#regionList").innerHTML = S.ctx.regions.map((r) => `<li data-region="${r.code}" class="${r.code === S.region ? "sel" : ""}"><span>${esc(r.name)}</span>${r.code === S.region ? '<span class="check">&#10003;</span>' : ""}</li>`).join("");
  $("#sourceList").innerHTML = S.ctx.state_sources.map((s) => `<li data-source="${s}" class="${s === S.source ? "sel" : ""}"><span>${esc(s)}</span>${s === S.source ? '<span class="check">&#10003;</span>' : ""}</li>`).join("");
}
async function savePrefs() {
  renderPanel();
  await api("/api/context", { method: "PUT", body: { env: S.env, region: S.region, state_source: S.source } });
  route();
}

// ------------------------------------------------------------------ COMMAND CENTER (landing)
async function pageCommand() {
  const d = await api(`/api/home?env=${E()}`);
  const o = d.overview;
  const cards = [
    ["home", "&#127968;", "Home", "Executive and operational overview of the entire mesh"],
    ["discover", "&#128269;", "Discover", "Marketplace for certified data products"],
    ["build", "&#128295;", "Build", "Intake readiness, development, publication and post-release validation"],
    ["operate", "&#128200;", "Operate", "Operations center: pipelines, availability, access, FinOps and SLAs"],
    ["manage", "&#9881;", "Manage", "Team and product onboarding, governance, platform services and configuration"],
  ];
  const globalHealth = o.failed_pipelines > 2 || o.incidents > 4 ? "Error" : o.failed_pipelines || o.incidents ? "Warning" : "Healthy";
  view().innerHTML = `
    ${head("Command Center", "Single pane of glass for the Data Mesh, sourced from Lakebase and Databricks metadata", `<a class="btn" href="#/topology">Mesh Topology</a>`)}
    ${envBanner(`<span>Global health: ${pill(globalHealth)}</span><span class="muted">${S.ctx.notifications.approvals} pending approvals &middot; ${S.ctx.notifications.incidents} open incidents</span>`)}
    <div class="grid g5">${cards.map((c) => `<div class="card navcard" data-go="${c[0]}"><div class="icon">${c[1]}</div><div class="title">${c[2]}</div><div class="desc">${c[3]}</div></div>`).join("")}</div>
    <div class="grid g6 section">
      ${kpi("Domains", o.domains)}${kpi("Data Products", o.products)}${kpi("Active Pipelines", o.active_pipelines, `${o.failed_pipelines} failed`)}
      ${kpi("Incidents", o.incidents)}${kpi("SLA Compliance", o.sla + "%")}${kpi("Quality Score", o.quality_score)}
    </div>
    <div class="grid g3 section">
      <div class="card"><h3>Recent Changes <a class="small" href="#/build/deployments">Deployment Management</a></h3>${table(d.recent_changes, [["Object", (r) => esc(r.object_name)], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)], ["When", (r) => ago(r.created_at)]])}</div>
      <div class="card"><h3>Pending Approvals <span class="muted small">${d.pending_approvals.length}</span></h3>${approvalList(d.pending_approvals)}</div>
      <div class="card"><h3>Failed Deployments</h3>${table(d.failed_deployments, [["Object", (r) => esc(r.object_name)], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)], ["When", (r) => ago(r.created_at)]], { empty: "No failed deployments" })}</div>
    </div>
    <div class="grid g2 section">
      <div class="card"><h3>Top Data Products</h3>${table(d.top_products, [["Product", (r) => `<a data-prod="${r.id}">${esc(r.name)}</a>${r.certified ? ' <span class="pill ok">Certified</span>' : ""}`], ["Domain", (r) => esc(r.domain)], ["Queries (30d)", (r) => num(r.usage_30d)], ["Consumers", (r) => r.consumers], ["Trend", (r) => (r.trend >= 0 ? "+" : "") + r.trend + "%"]])}</div>
      <div class="card"><h3>Cost Trends <span class="muted small">${esc(envName(S.env))}, monthly</span></h3>${colChart(d.cost_trend, monthLbl, "amount", 190)}</div>
    </div>`;
}
function approvalList(rows) {
  if (!rows.length) return '<div class="empty">Nothing pending</div>';
  return table(rows, [
    ["Type", (r) => pill(r.kind === "Access" ? "In Progress" : "Pending").replace(/In Progress|Pending/, r.kind)],
    ["Object", (r) => `${esc(r.object_name)}<div class="small muted">${esc(r.requester)}</div>`],
    ["", (r) => `<div class="btnrow"><button class="btn sm primary" data-approve="${r.id}">Approve</button><button class="btn sm danger" data-reject="${r.id}">Reject</button></div>`],
  ]);
}

// ------------------------------------------------------------------ HOME
async function pageHome() {
  const d = await api(`/api/home?env=${E()}`);
  const o = d.overview, x = d.exec;
  view().innerHTML = `
    ${head("Home", "Executive and operational overview of the entire data mesh")}
    ${envBanner()}
    <div class="grid g5">${kpi("Domains", o.domains)}${kpi("Products", o.products)}${kpi("Pipelines", o.total_pipelines, `${o.active_pipelines} running`)}${kpi("Incidents", o.incidents)}${kpi("SLA", o.sla + "%")}</div>
    <div class="grid g2 section">
      <div class="card"><h3>Domain Health</h3>${table(d.domains, [["Domain", (r) => `${dot(r.health)}<b>${esc(r.name)}</b>`], ["Status", (r) => pill(r.health)], ["Products", (r) => r.products], ["Quality", (r) => r.quality_score], ["Governance", (r) => r.governance_score], ["Owner", (r) => `<span class="small">${esc(r.owner)}</span>`]])}</div>
      <div class="card"><h3>Recent Activities</h3>${table(d.events, [["Event", (r) => `<span class="tag">${esc(r.kind)}</span> ${esc(r.message)}`], ["Actor", (r) => `<span class="small muted">${esc(r.actor)}</span>`], ["When", (r) => ago(r.created_at)]])}</div>
    </div>
    <h3 class="section">Platform Overview</h3>
    <div class="grid g5">
      ${kpi("Number of Domains", o.domains)}${kpi("Data Products", o.products)}${kpi("Active Pipelines", o.active_pipelines)}${kpi("Failed Pipelines", `<span style="color:var(--red)">${o.failed_pipelines}</span>`)}
      ${kpi("Quality Score", o.quality_score)}${kpi("Governance Score", o.governance_score)}${kpi("Environment Health", pill(o.env_health))}
      ${kpi("Storage Utilization", num(o.storage_tb, 1) + " TB")}${kpi("Compute Consumption", compact(o.compute_dbu) + " DBU")}${kpi("Pipeline Throughput", compact(o.throughput) + " rows/h")}
    </div>
    <div class="grid g2 section">
      <div class="card"><h3>Executive KPIs</h3>
        <div class="grid g4">${kpi("Time to Product Creation", x.time_to_product_days + " days")}${kpi("Data Product Adoption", x.adoption_pct + "%", compact(x.usage_30d) + " queries / 30d")}${kpi("SLA Compliance", x.sla + "%")}${kpi("Data Freshness", o.freshness_min + " min", "average lag")}</div>
        <h3 class="section">Cost per Domain <span class="muted small">current month</span></h3>${hbars(x.cost_per_domain, "name", "amount", money)}
      </div>
      <div class="card"><h3>Recent Events by Type</h3>${eventsByType(d.events)}</div>
    </div>`;
}
function eventsByType(events) {
  const groups = {};
  events.forEach((e) => (groups[e.kind] = groups[e.kind] || []).push(e));
  const order = ["Schema", "Publication", "Approval", "Incident", "Deployment", "Contract", "Pipeline", "Certification"];
  return order.filter((k) => groups[k]).map((k) => `<div style="margin-bottom:10px"><b>${k}</b>${groups[k].slice(0, 3).map((e) => `<div class="small muted">${esc(e.message)} &middot; ${ago(e.created_at)}</div>`).join("")}</div>`).join("") || '<div class="empty">No events</div>';
}

// ------------------------------------------------------------------ DISCOVER
async function pageDiscover(sub = "catalog") {
  const t = [["catalog", "Data Product Catalog"], ["glossary", "Business Glossary"], ["access", "Self Service Access"], ["insights", "Consumer Insights"]];
  if (S.source === "Databricks Catalog") t.push(["uc", "Unity Catalog"]);
  const shell = (body) => (view().innerHTML = `${head("Discover", "Marketplace for data products")}${envBanner()}${tabs(t, sub, "discover")}${body}`);
  if (sub === "catalog") {
    const doms = await api("/api/domains");
    shell(`<div class="searchbar"><input id="prodSearch" placeholder="Search data products (name, column, glossary term, tag)" value="${esc(S.filters.q)}"/><button class="btn primary" id="prodSearchBtn">Search</button></div>
      <div class="discover"><div class="card facet"><h3>Categories</h3>${doms.map((d) => `<label><input type="checkbox" data-facet="${esc(d.name)}" ${S.filters.domains.includes(d.name) ? "checked" : ""}/> ${esc(d.name)}</label>`).join("")}
        <h3 class="section">Certification</h3>
        <label><input type="radio" name="cert" value="" ${S.filters.certified === null ? "checked" : ""}/> All</label>
        <label><input type="radio" name="cert" value="true" ${S.filters.certified === true ? "checked" : ""}/> Certified only</label>
        <label><input type="radio" name="cert" value="false" ${S.filters.certified === false ? "checked" : ""}/> Not certified</label></div>
        <div id="prodResults"><div class="loading">Loading...</div></div></div>`);
    loadProducts();
  } else if (sub === "glossary") {
    const g = await api("/api/glossary");
    shell(`<div class="card">${table(g, [["Term", (r) => `<b>${esc(r.term)}</b>`], ["Definition", (r) => esc(r.definition)], ["Domain", (r) => esc(r.domain || "Enterprise")]])}</div>`);
  } else if (sub === "access") {
    const [mine, pend] = await Promise.all([api(`/api/approvals?mine=true`), api(`/api/approvals?env=${E()}&status=Pending`)]);
    const access = pend.filter((a) => a.kind === "Access");
    shell(`<div class="grid g2"><div class="card"><h3>Approve Access <span class="muted small">${access.length} pending in ${esc(envName(S.env))}</span></h3>${approvalList(access)}</div>
      <div class="card"><h3>Track My Requests</h3>${table(mine, [["Object", (r) => esc(r.object_name)], ["Kind", (r) => esc(r.kind)], ["Env", (r) => esc(r.env)], ["Status", (r) => pill(r.status)], ["Submitted", (r) => ago(r.created_at)]], { empty: "You have not submitted requests yet. Open a product and select Request Access." })}</div></div>`);
  } else if (sub === "insights") {
    const d = await api(`/api/insights?env=${E()}`);
    shell(`<div class="grid g3"><div class="card"><h3>Most Used Datasets</h3>${hbars(d.most_used, "name", "usage_30d")}</div>
      <div class="card"><h3>Trending Products</h3>${table(d.trending, [["Product", (r) => `<a data-prod="${r.id}">${esc(r.name)}</a>`], ["Domain", (r) => esc(r.domain)], ["30d trend", (r) => `<b style="color:${r.trend >= 0 ? "var(--green)" : "var(--red)"}">${r.trend >= 0 ? "+" : ""}${r.trend}%</b>`]])}</div>
      <div class="card"><h3>Usage Statistics by Domain</h3>${table(d.by_domain, [["Domain", (r) => esc(r.domain)], ["Queries", (r) => num(r.usage)], ["Consumers", (r) => r.consumers]])}</div></div>`);
  } else if (sub === "uc") {
    shell(`<div class="card"><h3>Unity Catalog Browser <span class="muted small">live metadata via app service principal</span></h3><div id="ucBody"><div class="loading">Loading catalogs...</div></div></div>`);
    loadUC();
  }
}
async function loadProducts() {
  const p = new URLSearchParams({ env: S.env });
  if (S.filters.q) p.set("q", S.filters.q);
  if (S.filters.domains.length) p.set("domains", S.filters.domains.join(","));
  if (S.filters.certified !== null) p.set("certified", S.filters.certified);
  const rows = await api("/api/products?" + p.toString());
  $("#prodResults").innerHTML = `<div class="muted small" style="margin-bottom:8px">${rows.length} data products in ${esc(envName(S.env))}</div>
    <div class="grid g3">${rows.map((r) => `<div class="card prodcard" data-prod="${r.id}"><div class="name"><span>${esc(r.name)}</span>${r.certified ? '<span class="pill ok">Certified</span>' : pill(r.lifecycle)}</div>
      <div class="desc">${esc(r.description)}</div><div>${(r.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
      <div class="meta" style="margin-top:10px"><span>${esc(r.domain)}</span><span>${esc(r.version)}</span><span>DQ ${r.quality_score}</span><span>${num(r.usage_30d)} queries</span></div></div>`).join("")}</div>`;
}
async function loadUC(catalog, schema) {
  const p = new URLSearchParams();
  if (catalog) p.set("catalog", catalog);
  if (schema) p.set("schema", schema);
  const d = await api("/api/catalog?" + p.toString());
  const crumbs = `<div class="small" style="margin-bottom:8px"><a data-uc="">Catalogs</a>${catalog ? ` / <a data-uc="${esc(catalog)}">${esc(catalog)}</a>` : ""}${schema ? ` / ${esc(schema)}` : ""}</div>`;
  if (d.level === "error") { $("#ucBody").innerHTML = crumbs + `<div class="empty">${esc(d.error)}</div>`; return; }
  const rows = d.items;
  let body;
  if (d.level === "catalogs") body = table(rows, [["Catalog", (r) => `<a data-uc="${esc(r.name)}">${esc(r.name)}</a>`], ["Comment", (r) => esc(r.comment || "")]], { empty: "No catalogs visible to the app service principal" });
  else if (d.level === "schemas") body = table(rows, [["Schema", (r) => `<a data-uc="${esc(catalog)}" data-ucs="${esc(r.name)}">${esc(r.name)}</a>`], ["Comment", (r) => esc(r.comment || "")]]);
  else body = table(rows, [["Table", (r) => esc(r.full_name)], ["Type", (r) => esc(r.type)], ["Comment", (r) => esc(r.comment || "")]]);
  $("#ucBody").innerHTML = crumbs + body;
}

async function openProduct(id) {
  const p = await api(`/api/products/${id}?env=${E()}`);
  const cols = (p.schema_def && p.schema_def.columns) || [];
  const st = p.states.find((s) => s.env === S.env) || p.states[p.states.length - 1] || {};
  const sec = (t, b) => `<div class="section"><h3>${t}</h3>${b}</div>`;
  openDrawer(`
    <div class="pagehead"><div><h1>${esc(p.name)} ${p.certified ? '<span class="pill ok">Certified</span>' : ""} ${pill(p.lifecycle)}</h1><div class="sub">${esc(p.domain)} domain &middot; ${esc(p.description)}</div></div>
      <div class="btnrow"><button class="btn primary" data-reqaccess="${p.id}">Request Access</button></div></div>
    <div class="grid g4">${kpi("Version (" + esc(envName(S.env)) + ")", esc(st.version || "-"))}${kpi("Quality", st.quality_score ?? "-")}${kpi("Queries (30d)", num(st.usage_30d))}${kpi("Consumers", st.consumers ?? "-")}</div>
    ${sec("Product Overview", `<div class="small">SLA: <b>${esc(p.sla)}</b> &middot; Sources: ${((p.schema_def && p.schema_def.sources) || []).map((s) => `<span class="tag">${esc(s)}</span>`).join("")} &middot; Freshness: ${st.freshness_min ?? "-"} min</div>
      ${table(p.states, [["Environment", (r) => esc(envName(r.env))], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)], ["Quality", (r) => r.quality_score], ["Updated", (r) => ago(r.updated_at)]])}`)}
    ${sec("Schema", table(cols, [["Column", (r) => `<b>${esc(r.name)}</b>`], ["Type", (r) => esc(r.type)], ["Description", (r) => esc(r.description || "")], ["PII", (r) => (r.pii ? pill("High").replace("High", "PII") : "")], ["Nullable", (r) => (r.nullable === false ? "No" : "Yes")]]))}
    ${sec("Lineage", `<div class="flow">${p.upstream.map((u) => `<div class="node source"><div class="t"><a data-prod="${u.id}">${esc(u.name)}</a></div><div class="s">${esc(u.domain)}</div></div>`).join("") || '<div class="node source"><div class="t">Source systems</div></div>'}
      <span class="arrow">&rarr;</span><div class="node product"><div class="t">${esc(p.name)}</div><div class="s">${esc(p.domain)}</div></div><span class="arrow">&rarr;</span>
      ${p.downstream.map((u) => `<div class="node gold"><div class="t"><a data-prod="${u.id}">${esc(u.name)}</a></div><div class="s">${esc(u.domain)}${u.kind === "cross-domain" ? " (cross-domain)" : ""}</div></div>`).join("") || '<div class="node"><div class="t">No consumers</div></div>'}</div>`)}
    ${sec("Quality", table(p.quality, [["Rule", (r) => esc(r.rule)], ["Dimension", (r) => esc(r.dimension)], ["Pass rate", (r) => r.pass_rate + "%"], ["Status", (r) => pill(r.status)]], { empty: "No quality rules in this environment" }))}
    ${sec("Owners", `<div class="grid g3">${kpi("Domain Owner", `<span class="small">${esc(p.owner)}</span>`)}${kpi("Data Steward", `<span class="small">${esc(p.steward)}</span>`)}${kpi("Custodian", `<span class="small">${esc(p.custodian)}</span>`)}</div>`)}
    ${sec("Usage Metrics", hbars(p.states, "env", "usage_30d"))}
    ${sec("Contracts", table(p.contracts, [["Contract", (r) => esc(r.name)], ["Kind", (r) => esc(r.kind)], ["Consumer", (r) => esc(r.consumer_domain || "-")], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)]]))}
    ${sec("Pipelines", table(p.pipelines, [["Pipeline", (r) => esc(r.name)], ["Env", (r) => esc(r.env)], ["Engine", (r) => esc(r.engine)], ["Status", (r) => pill(r.status)], ["Last run", (r) => ago(r.last_run)]]))}
  `);
}
function requestAccess(id) {
  const just = prompt("Business justification for access:", "Analytics use case");
  if (just === null) return;
  post("/api/access-requests", { product_id: Number(id), env: S.env, justification: just }).then(() => toast("Access request submitted and tracked in Lakebase"));
}

// ------------------------------------------------------------------ MESH TOPOLOGY
async function pageTopology() {
  const d = await api(`/api/topology?env=${E()}`);
  view().innerHTML = `${head("Mesh Topology", "Domains, data products, contracts, dependencies and cross-domain consumption")}${envBanner()}
    <div class="legend"><span>${dot("Healthy")}Healthy</span><span>${dot("Warning")}Warning</span><span>${dot("Error")}Error</span><span>&#9473; intra-domain lineage</span><span style="color:var(--accent)">&#9476; cross-domain consumption</span><span>Node size = number of contracts</span></div>
    <div class="grid" style="grid-template-columns: 1fr 300px"><div>${topoSvg(d)}</div><div class="card" id="topoSide"><h3>Selection</h3><div class="muted">Click a domain or product to inspect dependencies.</div><div class="section">${topoTree(d)}</div></div></div>`;
  S.topo = d;
}
function topoSvg(d) {
  const W = 1200, colW = W / d.domains.length, pos = {};
  let maxRows = 0;
  d.domains.forEach((dm, i) => {
    const ps = d.products.filter((p) => p.domain_id === dm.id);
    maxRows = Math.max(maxRows, ps.length);
    ps.forEach((p, j) => (pos[p.id] = { x: colW * i + colW / 2, y: 190 + j * 110, p, dm }));
    dm._x = colW * i + colW / 2;
  });
  const H = 190 + maxRows * 110 + 20;
  const col = (h) => ({ Healthy: "#1f9d55", Warning: "#d38b00", Error: "#d0342c", Failed: "#d0342c" }[h] || "#9aa3ab");
  const edges = d.edges.filter((e) => pos[e.source] && pos[e.target]).map((e) => {
    const a = pos[e.source], b = pos[e.target], cross = e.kind === "cross-domain";
    const mx = (a.x + b.x) / 2, my = Math.min(a.y, b.y) - (cross ? 60 : 0);
    const path = cross ? `M${a.x},${a.y} Q${mx},${my} ${b.x},${b.y}` : `M${a.x + 40},${a.y} C${a.x + 90},${a.y} ${b.x + 90},${b.y} ${b.x + 40},${b.y}`;
    return `<path class="edge" data-s="${e.source}" data-t="${e.target}" d="${path}" fill="none" stroke="${cross ? "#ff6a3d" : "#7a8792"}" stroke-width="1.6" ${cross ? 'stroke-dasharray="5 4"' : ""} marker-end="url(#arr${cross ? "c" : ""})" opacity="0.75"/>`;
  });
  const doms = d.domains.map((dm) => `<g class="dnode" data-dom="${dm.id}"><rect x="${dm._x - 80}" y="30" width="160" height="54" rx="10" fill="#1b3139"/><rect x="${dm._x - 80}" y="30" width="6" height="54" rx="3" fill="${col(dm.health)}"/>
     <text x="${dm._x}" y="54" text-anchor="middle" style="fill:#fff;font-size:13px;font-weight:600">${esc(dm.name)} Domain</text><text x="${dm._x}" y="72" text-anchor="middle" style="fill:#cfd8dc">${esc(dm.health || "-")}</text>
     ${d.products.filter((p) => p.domain_id === dm.id).map((p) => `<line x1="${dm._x}" y1="84" x2="${pos[p.id].x}" y2="${pos[p.id].y - 28}" stroke="#c5ccd3" stroke-width="1"/>`).join("")}</g>`);
  const prods = Object.values(pos).map(({ x, y, p }) => {
    const r = 20 + Math.min(10, p.contracts * 1.5);
    return `<g class="dnode" data-pnode="${p.id}"><circle cx="${x}" cy="${y}" r="${r}" fill="#fff" stroke="${col(p.pipeline_health)}" stroke-width="3" ${p.version ? "" : 'stroke-dasharray="3 3"'}/>
      ${p.certified ? `<circle cx="${x + r - 4}" cy="${y - r + 4}" r="6" fill="#2272b4"/>` : ""}<text x="${x}" y="${y + 4}" text-anchor="middle" style="font-size:10px;fill:#5f6b7a">${p.contracts}c</text>
      <text x="${x}" y="${y + r + 14}" text-anchor="middle" style="font-weight:600">${esc(p.name)}</text><text x="${x}" y="${y + r + 27}" text-anchor="middle" style="fill:#5f6b7a">${esc(p.version || "not deployed")}</text></g>`;
  });
  return `<svg class="topo" id="topoSvg" viewBox="0 0 ${W} ${H}" style="height:${Math.min(760, H)}px"><defs>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#7a8792"/></marker>
    <marker id="arrc" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#ff6a3d"/></marker></defs>
    ${doms.join("")}${edges.join("")}${prods.join("")}</svg>`;
}
function topoTree(d) {
  return d.domains.map((dm) => `<div style="margin-bottom:8px"><b>${dot(dm.health)}${esc(dm.name)} Domain</b>${d.products.filter((p) => p.domain_id === dm.id).map((p) => `<div class="small" style="padding-left:16px">&#9500;&#9472; <a data-prod="${p.id}">${esc(p.name)}</a></div>`).join("")}</div>`).join("");
}
function topoSelect(pid, domId) {
  const d = S.topo; if (!d) return;
  const svg = $("#topoSvg");
  let ids = new Set();
  if (pid) {
    ids.add(pid);
    d.edges.forEach((e) => { if (e.source === pid) ids.add(e.target); if (e.target === pid) ids.add(e.source); });
  } else d.products.filter((p) => p.domain_id === domId).forEach((p) => ids.add(p.id));
  svg.querySelectorAll("[data-pnode]").forEach((g) => (g.style.opacity = ids.has(Number(g.dataset.pnode)) ? 1 : 0.2));
  svg.querySelectorAll(".edge").forEach((e) => (e.style.opacity = ids.has(Number(e.dataset.s)) && ids.has(Number(e.dataset.t)) ? 1 : 0.08));
  const name = (id) => (d.products.find((p) => p.id === id) || {}).name;
  if (pid) {
    const p = d.products.find((x) => x.id === pid);
    const up = d.edges.filter((e) => e.target === pid), dn = d.edges.filter((e) => e.source === pid);
    $("#topoSide").innerHTML = `<h3>${esc(p.name)} <a class="small" data-prod="${pid}">Details</a></h3><div class="small">Version ${esc(p.version || "not deployed")} &middot; DQ ${p.quality_score ?? "-"} &middot; ${p.contracts} contracts &middot; pipeline ${pill(p.pipeline_health || "n/a")}</div>
      <div class="section"><b>Depends on</b>${up.map((e) => `<div class="small">${esc(name(e.source))} <span class="muted">${e.kind}</span></div>`).join("") || '<div class="small muted">Source systems only</div>'}</div>
      <div class="section"><b>Consumed by</b>${dn.map((e) => `<div class="small">${esc(name(e.target))} <span class="muted">${e.kind}</span></div>`).join("") || '<div class="small muted">No consumers</div>'}</div>
      <div class="section"><button class="btn sm" id="topoReset">Reset view</button></div>`;
  } else {
    const dm = d.domains.find((x) => x.id === domId);
    const own = new Set(d.products.filter((p) => p.domain_id === domId).map((p) => p.id));
    const outC = d.edges.filter((e) => own.has(e.source) && !own.has(e.target)).length, inC = d.edges.filter((e) => own.has(e.target) && !own.has(e.source)).length;
    $("#topoSide").innerHTML = `<h3>${esc(dm.name)} Domain</h3><div>${pill(dm.health)}</div><div class="section small">${own.size} products &middot; ${outC} outbound cross-domain feeds &middot; ${inC} inbound</div><div class="section"><button class="btn sm" id="topoReset">Reset view</button></div>`;
  }
}

// ------------------------------------------------------------------ BUILD (Foundry-style build workspace)
const BUILD_NAV = [
  ["intake", "&#128203;", "Intake &amp; Readiness", [["review", "Product Intake Review"], ["source", "Source Readiness"], ["environment", "Environment Readiness"], ["contracts", "Contract Validation"], ["dashboard", "Readiness Dashboard"]]],
  ["develop", "&#128736;", "Develop Data Product", [["workspace", "Product Workspace"], ["modeling", "Data Modeling"], ["pipelines", "Pipeline Development"], ["business", "Business Rules"], ["quality", "Data Quality Rules"], ["docs", "Metadata &amp; Documentation"], ["tests", "Test Execution"]]],
  ["publish", "&#128640;", "Publish Data Product", [["readiness", "Publish Readiness"], ["package", "Release Package"], ["promotion", "Promotion Pipeline"], ["approval", "Approval Workflow"], ["execution", "Publish Execution"]]],
  ["validation", "&#9989;", "Validation Center", [["artifacts", "Artifact Validation"], ["schema", "Schema Validation"], ["data", "Data Validation"], ["quality", "Quality Validation"], ["lineage", "Lineage Validation"], ["certification", "Certification Validation"]]],
  ["iam", "&#128272;", "IAM Validation", [["access", "Access Review"], ["roles", "Role Validation"], ["security", "Data Security Validation"], ["consumer", "Consumer Access Validation"], ["policy", "Policy Validation"], ["signoff", "Security Signoff"]]],
  ["deployments", "&#128667;", "Deployment Management"],
  ["releases", "&#127991;", "Release Management"],
  ["docs", "&#128214;", "Documentation Hub"],
];
const BUILD_DESC = {
  intake: "Validate onboarding prerequisites before development begins",
  develop: "Primary workspace for data product engineering teams",
  publish: "Release and promote the data product through environments",
  validation: "Validate published artifacts after release",
  iam: "Validate security and consumer access before handover to Operate",
  deployments: "Deploy products, pipelines and contracts across environments",
  releases: "Track release packages and approvals across all data products",
  docs: "Generated documentation, contracts and runbooks",
};
const BUILD_FLOW = [["intake", "Validate Intake"], ["develop", "Develop & Test"], ["publish", "Publish"], ["validation", "Validate Deployment"], ["iam", "Validate Security"], ["operate", "Handover to Operate"]];
const PIPE_ENGINES = ["Databricks Workflows", "Lakeflow SDP", "DBT Model", "Spark Notebook", "Fabric Pipeline"];
const buildBanner = (sec) => {
  const i = BUILD_FLOW.findIndex(([k]) => k === sec);
  return i < 0 ? "" : `<div class="card buildflow">${steps(BUILD_FLOW.map(([, l]) => l), BUILD_FLOW[i][1])}</div>`;
};
async function pickProduct() {
  const list = await api("/api/build/products");
  const cur = list.find((p) => String(p.id) === opsF("bprod")) || list.find((p) => p.lifecycle !== "Published") || list[0];
  return [list, cur];
}
function prodPicker(list, cur) {
  return `<div class="card"><div class="filters" style="grid-template-columns: 360px 1fr;margin:0"><div><label>Data product</label><select data-opsf="bprod">${list.map((p) => `<option value="${p.id}" ${p.id === cur.id ? "selected" : ""}>${esc(p.name)} (${esc(p.domain)})</option>`).join("")}</select></div>
    <div style="align-self:end" class="btnrow">${pill(cur.lifecycle)} ${pill(cur.build_status)} <span class="small muted">Owner: ${esc(cur.owner)}</span></div></div></div>`;
}
function checkTable(rows) {
  return table(rows, [["Check", (r) => `<b>${esc(r.item)}</b>`], ["Status", (r) => pill(r.status)], ["Evidence", (r) => small(r.detail)], ["Source", (r) => `<span class="tag">${r.source}</span>`],
    ["", (r) => (r.source === "manual" ? `<div class="btnrow">${r.status !== "Passed" ? `<button class="btn sm primary" data-bchk="${r.area}|${esc(r.item)}" data-st="Passed">Confirm</button>` : ""}${r.status !== "Failed" ? `<button class="btn sm" data-bchk="${r.area}|${esc(r.item)}" data-st="Failed">Fail</button>` : ""}</div>` : "")]]);
}
const genOut = (buttons) => `<div class="card"><h3>Generated Output <span class="btnrow">${buttons}<button class="btn sm" id="aiCopy">Copy</button></span></h3><pre class="code" id="aiOut">Select a generator.</pre></div>`;

const BUILD = {
  async intake(sub) {
    const [list, cur] = await pickProduct();
    const d = await api(`/api/build/products/${cur.id}/readiness`);
    const top = prodPicker(list, cur);
    const titles = { review: ["intake", "Product Intake Review"], source: ["source", "Source Readiness"], environment: ["environment", "Environment Readiness"], contracts: ["contract", "Contract Validation"] };
    if (sub === "dashboard") {
      return `${top}<div class="grid section" style="grid-template-columns: 380px 1fr"><div class="card"><h3>Readiness Dashboard</h3><ul class="checklist">${d.dashboard.map((x) => `<li class="${x.passed ? "done" : ""}"><span>${x.passed ? "&#10003;" : "&#10007;"} ${x.name}</span>${pill(x.passed ? "Passed" : "Failed")}</li>`).join("")}</ul>
        <div class="section"><b>Overall Status:</b> ${pill(d.overall)}</div></div>
        <div class="card"><h3>All Checks</h3>${table(Object.entries(d.areas).flatMap(([a, rows]) => rows.map((r) => ({ ...r, a }))), [["Area", (r) => `<span class="tag">${esc(r.a)}</span>`], ["Check", (r) => esc(r.item)], ["Status", (r) => pill(r.status)], ["Evidence", (r) => small(r.detail)]])}</div></div>`;
    }
    const [area, title] = titles[sub];
    let extra = "";
    if (sub === "contracts") {
      const doms = await api("/api/domains");
      extra = `<div class="grid section" style="grid-template-columns: 340px 1fr"><div class="card"><h3>Create Contract</h3><input type="hidden" id="cProd" value="${cur.id}"/>
        <label>Contract type</label><select id="cKind"><option>Producer</option><option>Consumer</option><option>SLA</option><option>Schema</option></select>
        <label>Consumer domain (consumer contracts)</label><select id="cCons"><option value="">-</option>${doms.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
        <label>SLA definition</label><input id="cSla" value="Daily by 06:00 ET"/><label>Freshness (minutes)</label><input id="cFresh" value="60"/><label>Completeness</label><input id="cComp" value=">= 99%"/>
        <label>Terms</label><textarea id="cTerms">Breaking schema changes require 30 days notice.</textarea><div class="section"><button class="btn primary" id="cSave">Create contract</button></div></div>
        <div class="card"><h3>Contracts</h3>${table(d.contracts, [["Type", (r) => esc(r.kind)], ["Status", (r) => pill(r.status)]], { empty: "No contracts" })}</div></div>`;
    }
    const ok = d.areas[area].every((c) => c.status === "Passed");
    return `${top}<div class="card section"><h3>${title} ${pill(ok ? "Passed" : "Failed")}</h3>${checkTable(d.areas[area])}</div>${extra}`;
  },

  async develop(sub) {
    const [list, cur] = await pickProduct();
    const d = await api(`/api/build/products/${cur.id}/develop`), P = d.product;
    const top = `${prodPicker(list, cur)}<input type="hidden" id="aiProd" value="${cur.id}"/>`;
    const q = d.rules.filter((r) => r.kind === "Quality"), b = d.rules.filter((r) => r.kind === "Business");
    if (sub === "workspace") {
      const passed = d.tests.filter((t) => t.status === "Passed").length;
      return `${top}<div class="grid g6 section">${kpi("Product Name", `<span style="font-size:16px">${esc(P.name)}</span>`)}${kpi("Domain", esc(P.domain))}${kpi("Owner", `<span style="font-size:13px">${esc(P.owner)}</span>`)}${kpi("Release Version", esc(d.version || "-"))}${kpi("Environment", d.environments.join(" / ") || "-")}${kpi("Build Status", pill(d.build_status))}</div>
        <div class="grid g5 section">${[["modeling", "Models", d.models.length], ["pipelines", "Pipelines", d.pipelines.length], ["business", "Business Rules", b.length], ["quality", "Quality Rules", q.length], ["tests", "Tests Passed", `${passed}/${d.tests.length}`]]
          .map(([k, l, v]) => `<div class="card navcard" data-href="#/build/develop/${k}"><div class="small muted">${l}</div><div class="kpi"><div class="value">${v}</div></div></div>`).join("")}</div>
        <div class="card section"><h3>Description</h3><div>${esc(P.description)}</div><div class="small muted section">SLA ${esc(P.sla)} &middot; Classification ${esc(P.classification || "unclassified")} &middot; Steward ${esc(P.steward)}</div></div>`;
    }
    if (sub === "modeling") {
      return `${top}<div class="grid g5 section">${["Table", "View", "Schema", "Dimension", "Fact"].map((k) => kpi(k + "s", d.models.filter((m) => m.kind === k).length)).join("")}</div>
        <div class="grid section" style="grid-template-columns: 1fr 300px"><div class="card"><h3>Physical, Logical, Gold and Semantic Models</h3>${table(d.models, [["Name", (r) => `<code>${esc(r.name)}</code>`], ["Kind", (r) => `<span class="tag">${esc(r.kind)}</span>`], ["Layer", (r) => esc(r.layer)], ["Model", (r) => esc(r.model_type)], ["Columns", (r) => r.column_count], ["Status", (r) => pill(r.status)]])}</div>
        <div class="card"><h3>Add Model</h3><label>Name</label><input id="bmName" placeholder="${esc(P.domain.toLowerCase())}.gold.dim_customer"/><label>Kind</label><select id="bmKind">${opts(d.model_kinds)}</select>
          <label>Layer</label><select id="bmLayer">${opts(d.model_layers, "Gold")}</select><label>Model type</label><select id="bmType">${opts(d.model_types)}</select><label>Columns</label><input id="bmCols" type="number" value="8"/>
          <div class="section"><button class="btn primary" id="bmSave">Add model</button></div></div></div>`;
    }
    if (sub === "pipelines") {
      return `${top}<div class="card section"><h3>Product Pipelines</h3>${d.pipelines.map((p) => `<div class="small"><b>${esc(p.name)}</b> &middot; ${esc(p.env)} &middot; ${esc(p.engine)} ${pill(p.status)}</div>${flowHtml(p.layers || ["Source", "Bronze", "Silver", "Gold", "Product"], p.engine)}`).join("") || '<div class="empty">No pipelines yet</div>'}</div>
        <div class="grid section" style="grid-template-columns: 340px 1fr"><div class="card"><h3>Pipeline Designer</h3><input type="hidden" id="plProd" value="${cur.id}"/>
          <label>Pipeline name</label><input id="plName" placeholder="${esc(P.name.toLowerCase())}_refresh"/><label>Engine</label><select id="plEngine">${opts(PIPE_ENGINES)}</select>
          <label>Target environment</label><select id="plEnv">${ENVS.map((e) => `<option value="${e}">${envName(e)}</option>`).join("")}</select>
          <label>Layers</label>${["Source", "Bronze", "Silver", "Gold", "Product"].map((l) => `<label style="display:inline-flex;gap:4px;margin-right:10px;color:var(--ink)"><input type="checkbox" class="plLayer" value="${l}" checked/>${l}</label>`).join("")}
          <div id="plFlow" class="section">${flowHtml(["Source", "Bronze", "Silver", "Gold", "Product"], PIPE_ENGINES[0])}</div><div class="section"><button class="btn primary" id="plSave">Create pipeline</button></div></div>
        ${genOut([["sql", "SQL"], ["pyspark", "PySpark"], ["dbt", "DBT"]].map(([k, l]) => `<button class="btn sm" data-gen="${k}">Generate ${l}</button>`).join(""))}</div>`;
    }
    if (sub === "business" || sub === "quality") {
      const kind = sub === "business" ? "Business" : "Quality", rows = kind === "Business" ? b : q;
      const results = kind === "Quality" ? `<div class="card section"><h3>Latest DEV Quality Results</h3>${table(d.dq_results, [["Rule", (r) => esc(r.rule)], ["Dimension", (r) => esc(r.dimension)], ["Pass rate", (r) => r.pass_rate + "%"], ["Status", (r) => pill(r.status)]])}</div>` : "";
      return `${top}<div class="grid section" style="grid-template-columns: 1fr 300px"><div class="card"><h3>${kind === "Business" ? "Calculations, Transformations, Standardization and Aggregation" : "Null, Duplicate, Threshold, Reference and Business Rule Checks"}</h3>
        ${table(rows, [["Category", (r) => `<span class="tag">${esc(r.category)}</span>`], ["Rule", (r) => `<b>${esc(r.name)}</b>`], ["Expression", (r) => `<code class="small">${esc(r.expression)}</code>`], ...(kind === "Quality" ? [["Threshold", (r) => esc(r.threshold || "-")]] : []), ["Status", (r) => pill(r.status)]], { empty: "No rules" })}</div>
        <div class="card"><h3>Add ${kind} Rule</h3><label>Category</label><select id="brCat">${opts(d.rule_categories[kind])}</select><label>Name</label><input id="brName"/><label>Expression</label><textarea id="brExpr"></textarea>
          ${kind === "Quality" ? '<label>Threshold</label><input id="brThr" placeholder="99%"/>' : ""}<div class="section"><button class="btn primary" id="brSave" data-kind="${kind}">Add rule</button></div></div></div>${results}`;
    }
    if (sub === "docs") {
      return `${top}<div class="grid g2 section"><div class="card"><h3>Business Description</h3><div>${esc(P.description)}</div><div class="small muted section">Use cases: ${esc(P.use_cases || "not documented")}</div></div>
        <div class="card"><h3>Ownership</h3><div class="small" style="line-height:1.9">Domain: <b>${esc(P.domain)}</b><br>Owner: <b>${esc(P.owner)}</b><br>Steward: <b>${esc(P.steward)}</b><br>Classification: <b>${esc(P.classification || "-")}</b></div></div>
        <div class="card"><h3>Glossary Terms</h3>${table(d.glossary, [["Term", (r) => `<b>${esc(r.term)}</b>`], ["Definition", (r) => small(r.definition)]])}</div>
        <div class="card"><h3>Technical Lineage</h3><div class="flow">${tags(d.upstream)}<span class="arrow">&rarr;</span><div class="node product"><div class="t">${esc(P.name)}</div></div><span class="arrow">&rarr;</span>${tags(d.downstream)}</div></div></div>
        <div class="section">${genOut('<button class="btn sm" data-gen="docs">Documentation</button><button class="btn sm" data-gen="contract">Data Contract</button><button class="btn sm" data-runbook="1">Runbook</button>')}</div>`;
    }
    const by = (s, st) => d.tests.filter((t) => t.suite === s && t.status === st).length;
    return `${top}<div class="grid g5 section">${d.suites.map((s) => `<div class="card"><h3>${s} <button class="btn sm" data-btest="${s}">Run</button></h3><div class="btnrow">${pill("Passed")} ${by(s, "Passed")} ${pill("Failed")} ${by(s, "Failed")} ${pill("Not Run")} ${by(s, "Not Run")}</div></div>`).join("")}</div>
      <div class="card section"><h3>Test Execution <button class="btn sm primary" data-btest="All">Run all tests</button></h3>${table(d.tests, [["Suite", (r) => `<span class="tag">${esc(r.suite)}</span>`], ["Test", (r) => `<code class="small">${esc(r.name)}</code>`], ["Status", (r) => pill(r.status)], ["Duration", (r) => (r.status === "Not Run" ? "-" : r.duration_s + " s")], ["Last run", (r) => ago(r.last_run)]])}</div>`;
  },

  async publish(sub) {
    const [list, cur] = await pickProduct();
    const d = await api(`/api/build/products/${cur.id}/publish`);
    const top = prodPicker(list, cur);
    const ready = d.checks.every((c) => c.status === "Passed");
    const open = d.releases.find((r) => r.status === "In Approval");
    if (sub === "readiness") return `${top}<div class="card section"><h3>Publish Readiness ${pill(ready ? "Ready to Publish" : "Not Ready")}</h3>${checkTable(d.checks)}</div>`;
    if (sub === "package") {
      return `${top}<div class="grid g3 section">${Object.entries(d.package).map(([k, v]) => `<div class="card"><h3>${k} <span class="tag">${v.length}</span></h3>${v.map((x) => `<div class="small"><code>${esc(x)}</code></div>`).join("") || '<div class="empty">None</div>'}</div>`).join("")}</div>
        <div class="grid section" style="grid-template-columns: 300px 1fr"><div class="card"><h3>Create Release Package</h3><label>Version</label><input id="brelVer" placeholder="v1.0"/><label>Release notes</label><textarea id="brelNotes"></textarea><div class="section"><button class="btn primary" id="brelSave">Package and submit</button></div></div>
        <div class="card"><h3>Releases</h3>${table(d.releases, [["Version", (r) => `<b>${esc(r.version)}</b>`], ["Status", (r) => pill(r.status)], ["Stage", (r) => esc(r.stage)], ["Artifacts", (r) => Object.entries(r.artifacts || {}).map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join("")], ["By", (r) => small(r.created_by)], ["When", (r) => ago(r.created_at)]], { empty: "No releases" })}</div></div>`;
    }
    if (sub === "promotion") {
      return `${top}<div class="card section"><h3>Promotion Pipeline</h3><div class="flow">${ENVS.map((e, i) => {
        const s = d.states[e], nxt = ENVS[i + 1], next = d.states[nxt];
        const canPromote = s && nxt && (!next || next.version !== s.version);
        return `${i ? '<span class="arrow">&rarr;</span>' : ""}<div class="node ${s ? "ok" : ""}" style="min-width:170px"><div class="t">${envName(e)}</div><div class="s">${s ? `${esc(s.version)} ${pill(s.status)}` : "not deployed"}</div>
          ${canPromote ? `<button class="btn sm primary section" data-promote="1" data-name="${esc(cur.name)}" data-ver="${esc(s.version)}" data-to="${nxt}">Promote to ${nxt}${nxt === "PROD" ? " (gated)" : ""}</button>` : ""}</div>`;
      }).join("")}</div></div>
        <div class="card section"><h3>Promotion History</h3>${table(d.deployments, [["Version", (r) => esc(r.version)], ["Env", (r) => esc(envName(r.env))], ["Status", (r) => pill(r.status)], ["By", (r) => small(r.requested_by)], ["Notes", (r) => small(r.notes)], ["When", (r) => ago(r.created_at)]], { empty: "No promotions yet" })}</div>`;
    }
    if (sub === "approval") {
      return `${top}<div class="card section"><h3>Approval Workflow ${open ? `<span class="small muted">${esc(open.version)}</span>` : ""}</h3>${open ? `${steps(d.stages, open.stage)}<div class="btnrow section"><button class="btn primary" data-brel="${open.id}" data-dec="approve">Approve as ${esc(open.stage)}</button><button class="btn danger" data-brel="${open.id}" data-dec="reject">Reject</button></div>` : '<div class="empty">No release awaiting approval. Create one in Release Package.</div>'}</div>
        <div class="card section"><h3>Release Approvals</h3>${table(d.releases, [["Version", (r) => `<b>${esc(r.version)}</b>`], ["Workflow", (r) => steps(d.stages, r.stage, ["Approved", "Published"].includes(r.status))], ["Status", (r) => pill(r.status)], ["Updated", (r) => ago(r.updated_at)]], { empty: "No releases" })}</div>`;
    }
    const approved = d.releases.filter((r) => r.status === "Approved");
    return `${top}<div class="card section"><h3>Publish Execution ${pill(ready ? "Ready to Publish" : "Not Ready")}</h3>${table(approved, [["Version", (r) => `<b>${esc(r.version)}</b>`], ["Approved", (r) => ago(r.updated_at)], ["", (r) => `<button class="btn sm primary" data-bpub="${r.id}">Publish to Production</button>`]], { empty: "No approved releases waiting to publish" })}
      ${ready ? "" : '<div class="small muted section">Publishing is blocked until all Publish Readiness checks pass.</div>'}</div>
      <div class="card section"><h3>Published Releases</h3>${table(d.releases.filter((r) => r.status === "Published"), [["Version", (r) => `<b>${esc(r.version)}</b>`], ["By", (r) => small(r.created_by)], ["Published", (r) => ago(r.updated_at)]], { empty: "Not yet published" })}</div>`;
  },

  async validation(sub) {
    const [list, cur] = await pickProduct();
    const d = await api(`/api/build/products/${cur.id}/validation?env=${E()}`);
    const top = prodPicker(list, cur);
    if (sub === "artifacts") {
      const e = d.artifacts.reduce((a, x) => a + x.expected, 0), p = d.artifacts.reduce((a, x) => a + x.published, 0);
      return `${top}<div class="grid g3 section">${kpi("Expected", e)}${kpi("Published", p)}${kpi("Validation", pill(d.artifacts_status))}</div>
        <div class="card section"><h3>Artifact Validation <span class="small muted">${esc(envName(d.env))}</span></h3>${table(d.artifacts, [["Artifact", (r) => `<b>${r.type}</b>`], ["Expected", (r) => r.expected], ["Published", (r) => r.published], ["Status", (r) => pill(r.status)]])}</div>`;
    }
    if (sub === "schema") {
      return `${top}<div class="card section"><h3>Published Schema vs Approved Schema ${pill(d.schema_status)}</h3>${d.has_snapshot ? table(d.schema, [["Column", (r) => `<code>${esc(r.column)}</code>`], ["Approved type", (r) => esc(r.approved || "-")], ["Published type", (r) => esc(r.published || "-")], ["Result", (r) => pill(r.status)]]) : `<div class="empty">No published schema snapshot in ${esc(envName(d.env))}</div>`}</div>`;
    }
    if (sub === "data") {
      return `${top}<div class="card section"><h3>Data Validation <button class="btn sm primary" data-brecon="1">Run reconciliation</button></h3>${table(d.data, [["Check", (r) => `<b>${esc(r.check_type)}</b>`], ["Metric", (r) => small(r.metric)], ["Source", (r) => num(r.source_value, 2)], ["Target", (r) => num(r.target_value, 2)],
        ["Difference", (r) => (r.source_value ? (Math.round((10000 * (r.target_value - r.source_value)) / r.source_value) / 100) + "%" : "-")], ["Status", (r) => pill(r.status)], ["Checked", (r) => ago(r.checked_at)]], { empty: `No validation evidence in ${esc(envName(d.env))}` })}</div>`;
    }
    if (sub === "quality") {
      const qd = d.quality;
      return `${top}<div class="grid g4 section">${kpi("Quality Rules Active", qd.active)}${kpi("Thresholds Met", `${qd.thresholds_met}/${qd.active}`)}${kpi("Critical Violations", `<span style="color:${qd.critical.length ? "var(--red)" : "inherit"}">${qd.critical.length}</span>`)}${kpi("Result", pill(qd.status))}</div>
        <div class="card section"><h3>Quality Validation</h3>${table(qd.rules, [["Rule", (r) => esc(r.rule)], ["Dimension", (r) => esc(r.dimension)], ["Pass rate", (r) => r.pass_rate + "%"], ["Status", (r) => pill(r.status)]], { empty: "No quality rules in this environment" })}</div>`;
    }
    if (sub === "lineage") {
      const l = d.lineage;
      return `${top}<div class="card section"><h3>Lineage Validation ${pill(l.status)}</h3><div class="flow">
        <div class="node source"><div class="t">Source</div><div class="s">${l.sources.map(esc).join("<br>") || "none"}</div></div><span class="arrow">&rarr;</span>
        <div class="node silver"><div class="t">Transformations</div><div class="s">${l.transformations.map((t) => `${esc(t.name)} (${esc(t.engine)})`).join("<br>") || "none"}</div></div><span class="arrow">&rarr;</span>
        <div class="node product"><div class="t">${esc(d.product.name)}</div><div class="s">Published product</div></div></div>
        <div class="small section" style="line-height:2"><b>Upstream products:</b> ${tags(l.upstream)}<br><b>Downstream products:</b> ${tags(l.downstream)}</div></div>`;
    }
    const c = d.certification;
    return `${top}<div class="grid g5 section">${kpi("Certification", c.status ? pill(c.status) : "-")}${kpi("Level", esc(c.level || "-"))}${kpi("Readiness", pill(c.compliant ? "Complete" : "Incomplete"))}${kpi("Quality", `${num(c.quality, 1)} / ${c.threshold}`)}${kpi("Validation", pill(c.result))}</div>
      <div class="small muted section">Certification lifecycle is managed in <a data-href="#/manage/governance/certification">Manage &rsaquo; Governance &rsaquo; Certification</a>.</div>`;
  },

  async iam(sub) {
    const [list, cur] = await pickProduct();
    const d = await api(`/api/build/products/${cur.id}/iam?env=${E()}`);
    const top = `${prodPicker(list, cur)}<div class="small muted section">Environment: <b>${esc(envName(d.env))}</b> &middot; Handover: ${pill(d.handover)}</div>`;
    const grantBtn = (r) => (r.status === "Failed" && r.principal && !r.principal.includes(",") ? `<button class="btn sm primary" data-bgrant="${esc(r.principal)}" data-role="${r.required}">Grant ${r.required}</button>` : "");
    const accessCols = [["Party", (r) => `<b>${esc(r.party)}</b>`], ["Principal", (r) => small(r.principal)], ["Required", (r) => pill(r.required)], ["Effective", (r) => (r.effective ? pill(r.effective) : "-")], ["Status", (r) => pill(r.status)], ["", grantBtn]];
    if (sub === "access") return `${top}<div class="card section"><h3>Access Review</h3>${table(d.access, accessCols)}</div>`;
    if (sub === "roles") return `${top}<div class="card section"><h3>RBAC Role Mapping</h3>${table(d.roles, accessCols)}</div>`;
    if (sub === "security") return `${top}<div class="card section"><h3>Data Security Validation <span class="small muted">classification ${esc(d.product.classification || "-")}</span></h3>${table(d.security, [["Control", (r) => `<b>${esc(r.control)}</b>`], ["Required", (r) => (r.required ? "Yes" : "No")], ["Status", (r) => pill(r.status)], ["Detail", (r) => small(r.detail)]])}</div>`;
    if (sub === "consumer") return `${top}<div class="card section"><h3>Consumer Access Validation <button class="btn sm primary" data-bcons="1">Run automated tests</button></h3>${table(d.consumer, [["Test", (r) => `<b>${esc(r.test)}</b>`], ["Result", (r) => pill(r.status)], ["Evidence", (r) => small(r.detail)], ["Run", (r) => ago(r.checked_at)]])}</div>`;
    if (sub === "policy") return `${top}<div class="card section"><h3>Policy Validation</h3>${checkTable(d.policies)}</div>`;
    return `${top}<div class="grid section" style="grid-template-columns: 1fr 1fr"><div class="card"><h3>Security Signoff</h3>${checkTable(d.signoffs)}</div>
      <div class="card"><h3>Handover to Operate</h3><ul class="checklist">${[["Access review", d.access.every((x) => x.status === "Passed")], ["Role validation", d.roles.every((x) => x.status !== "Failed")], ["Data security", d.security.every((x) => x.status !== "Missing")],
        ["Consumer access tests", d.consumer.every((x) => x.status === "Passed")], ["Policies attached", d.policies.every((x) => x.status === "Passed")], ["Signoffs", d.signoffs.every((x) => x.status === "Passed")]]
        .map(([l, ok]) => `<li class="${ok ? "done" : ""}"><span>${ok ? "&#10003;" : "&#10007;"} ${l}</span>${pill(ok ? "Passed" : "Failed")}</li>`).join("")}</ul>
        <div class="section">${pill(d.handover)} ${d.handover.startsWith("Ready") ? '<a class="btn sm" data-href="#/operate/dashboard">Open Operate</a>' : ""}</div></div></div>`;
  },

  async deployments() {
    const [prods, deps] = await Promise.all([api("/api/build/products"), api("/api/deployments")]);
    return `<div class="grid" style="grid-template-columns: 340px 1fr"><div class="card"><h3>Deploy</h3>
      <label>Object type</label><select id="dType"><option>Product</option><option>Pipeline</option><option>Contract</option></select>
      <label>Object</label><select id="dObj">${prods.map((p) => `<option>${esc(p.name)}</option>`).join("")}</select><label>Version</label><input id="dVer" value="v1.0"/>
      <label>Target environment</label><div class="flow">${ENVS.map((e, i) => `${i ? '<span class="arrow">&rarr;</span>' : ""}<label class="node" style="margin:0;cursor:pointer;color:var(--ink)"><input type="radio" name="dEnv" value="${e}" ${i === 0 ? "checked" : ""}/> ${envName(e)}</label>`).join("")}</div>
      <p class="muted small">Production releases require approval. All deployment state is tracked in the state store.</p><button class="btn primary" id="dGo">Deploy</button></div>
      <div class="card"><h3>Deployment History</h3>${table(deps, [["Object", (r) => `${esc(r.object_name)}<div class="small muted">${esc(r.object_type)}</div>`], ["Version", (r) => esc(r.version)], ["Env", (r) => esc(envName(r.env))], ["Status", (r) => pill(r.status)], ["By", (r) => small(r.requested_by)], ["When", (r) => ago(r.created_at)], ["", (r) => (r.status === "Succeeded" ? `<button class="btn sm" data-rollback="${r.id}">Rollback</button>` : "")]])}</div></div>`;
  },

  async releases() {
    const rows = await api("/api/build/releases");
    const n = (s) => rows.filter((r) => r.status === s).length;
    return `<div class="grid g4">${["In Approval", "Approved", "Published", "Rejected"].map((s) => kpi(s, n(s))).join("")}</div>
      <div class="card section"><h3>Release Management</h3>${table(rows, [["Product", (r) => `<a data-prod="${r.product_id}"><b>${esc(r.product)}</b></a><div class="small muted">${esc(r.domain)}</div>`], ["Version", (r) => esc(r.version)], ["Workflow", (r) => steps(RELEASE_STAGES_UI, r.stage, ["Approved", "Published"].includes(r.status))], ["Status", (r) => pill(r.status)], ["By", (r) => small(r.created_by)], ["Updated", (r) => ago(r.updated_at)],
        ["", (r) => `<a class="btn sm" data-bopen="${r.product_id}">Open</a>`]])}</div>`;
  },

  async docs() {
    const [list, cur] = await pickProduct();
    const m = await api("/api/mgmt/products");
    return `${prodPicker(list, cur)}<input type="hidden" id="aiProd" value="${cur.id}"/><div class="section">${genOut('<button class="btn sm" data-gen="docs">Documentation</button><button class="btn sm" data-gen="contract">Data Contract</button><button class="btn sm" data-runbook="1">Runbook</button>')}</div>
      <div class="card section"><h3>Documentation Completeness</h3>${table(m.products, [["Product", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.domain)}</div>`], ["Metadata", (r) => pill(r.metadata_status)], ["Missing", (r) => r.missing_metadata.map((x) => `<span class="tag">${esc(x)}</span>`).join("") || "-"], ["Undocumented columns", (r) => r.undocumented_columns.length], ["", (r) => `<a class="btn sm" data-bopen="${r.id}">Open</a>`]])}</div>`;
  },
};
const RELEASE_STAGES_UI = ["Product Owner", "Data Steward", "Platform Team", "Release Manager", "Publish"];

document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-bchk],[data-btest],[data-runbook],[data-brel],[data-bpub],[data-brecon],[data-bgrant],[data-bcons],[data-bopen],#bmSave,#brSave,#brelSave");
  if (!el) return;
  const ds = el.dataset, pid = () => document.querySelector("[data-opsf='bprod']").value;
  const done = (msg) => { toast(msg); return route(); };
  if (ds.bchk) { const [area, item] = ds.bchk.split("|"); await post(`/api/build/products/${pid()}/checks`, { area, item, status: ds.st }); return done(`${item}: ${ds.st}`); }
  if (ds.btest) { const r = await post(`/api/build/products/${pid()}/tests/run`, { suite: ds.btest }); return done(`${r.Passed} passed, ${r.Failed} failed`); }
  if (ds.runbook) { $("#aiOut").textContent = (await api(`/api/build/products/${pid()}/runbook`)).code; return; }
  if (ds.brel) { const r = await post(`/api/build/releases/${ds.brel}/decision`, { decision: ds.dec }); return done(r.status === "Approved" ? "Release approved - ready to publish" : `Release ${r.status.toLowerCase()} (${r.stage})`); }
  if (ds.bpub) { const r = await post(`/api/build/releases/${ds.bpub}/publish`); return done(`Published ${r.published} to Production`); }
  if (ds.brecon) { const r = await post(`/api/build/products/${pid()}/validation/reconcile`, { env: S.env }); return done(r.reconciled ? "Reconciliation passed" : "Blocked by failed pipeline - re-run it in Operate"); }
  if (ds.bgrant) {
    const p = ds.bgrant, type = p.startsWith("sp-") ? "Service Principal" : p.includes("@") ? "User" : "Group";
    await post(`/api/build/products/${pid()}/iam/grant`, { principal: p, principal_type: type, role: ds.role, env: S.env }); return done(`${ds.role} granted to ${p}`);
  }
  if (ds.bcons) { const r = await post(`/api/build/products/${pid()}/iam/consumer-tests`, { env: S.env }); return done(`${Object.values(r).filter((x) => x === "Passed").length}/3 consumer tests passed`); }
  if (ds.bopen) { S.opsF.bprod = ds.bopen; location.hash = "#/build/publish/readiness"; return; }
  switch (el.id) {
    case "bmSave": await post(`/api/build/products/${pid()}/models`, { name: $("#bmName").value, kind: $("#bmKind").value, layer: $("#bmLayer").value, model_type: $("#bmType").value, column_count: Number($("#bmCols").value) }); return done("Model added");
    case "brSave": await post(`/api/build/products/${pid()}/rules`, { kind: ds.kind, category: $("#brCat").value, name: $("#brName").value, expression: $("#brExpr").value, threshold: $("#brThr") ? $("#brThr").value : null }); return done("Rule added");
    case "brelSave": await post(`/api/build/products/${pid()}/releases`, { version: $("#brelVer").value, notes: $("#brelNotes").value }); return done("Release package submitted for approval");
  }
});
function flowHtml(layers, engine, healthFn) {
  return `<div class="flow">${layers.map((l, i) => `${i ? '<span class="arrow">&darr;</span>'.replace("darr", "rarr") : ""}<div class="node ${healthFn ? healthFn(l) : l.toLowerCase()}"><div class="t">${l}</div><div class="s">${i === 0 ? "ingest" : i === layers.length - 1 ? "serve" : engine}</div></div>`).join("")}</div>`;
}

// ------------------------------------------------------------------ OPERATE (Foundry-style operations center)
const ENVS = ["DEV", "SIT", "UAT", "PROD"];
const OPS_NAV = [
  ["dashboard", "&#128202;", "Operational Dashboard"],
  ["pipelines", "&#128260;", "Pipeline Operations", [["catalog", "Pipeline Catalog"], ["monitoring", "Monitoring"], ["scheduling", "Scheduling"], ["backfill", "Backfill"], ["recovery", "Recovery"]]],
  ["availability", "&#9989;", "Data Availability", [["health", "Product Health"], ["freshness", "Freshness"], ["sla", "SLA Status"], ["impact", "Consumer Impact"]]],
  ["access", "&#128273;", "Access Operations", [["review", "User Access Review"], ["requests", "Access Requests"], ["permissions", "Effective Permissions"], ["groups", "Group Management"], ["audit", "Access Audit"]]],
  ["budget", "&#128176;", "Budget &amp; Quota Management", [["cost", "Cost Dashboard"], ["chargeback", "Chargeback"], ["usage", "Usage Monitoring"], ["quota", "Quota Management"], ["forecast", "Forecasting"], ["optimize", "Optimization"]]],
  ["artifacts", "&#128230;", "Published Artifact Management", [["catalog", "Artifact Catalog"], ["releases", "Release Tracking"], ["versions", "Version Management"], ["rollback", "Rollback"], ["retirement", "Retirement"]]],
  ["monitoring", "&#128276;", "Monitoring &amp; Alerting"],
  ["incidents", "&#128680;", "Incident Management"],
  ["environments", "&#127760;", "Environment Operations"],
  ["sla", "&#9201;", "SLA Management"],
];
const OPS_DESC = {
  dashboard: "Day-to-day landing page for build and operations teams once products are in production",
  pipelines: "Monitor and manage ingestion, transformation and publication pipelines",
  availability: "Keep data products available and within SLA targets",
  access: "Production IAM operations for data products",
  budget: "FinOps visibility and guardrails against uncontrolled platform growth",
  artifacts: "Manage all deployed and production-ready assets",
  monitoring: "Central operational monitoring and alerting",
  incidents: "Resolve operational issues from detection to post-mortem",
  environments: "Operate DEV, SIT, UAT and Production environments",
  sla: "Track service commitments",
};
const RUN_STATES = ["Running", "Succeeded", "Delayed", "Queued", "Failed"];
const RUN_COLORS = { Running: "#2272b4", Succeeded: "#1f9d55", Delayed: "#d38b00", Queued: "#9aa3ab", Failed: "#d0342c" };
const RANK = { Reader: 1, Contributor: 2, Owner: 3 };
const maxRole = (roles) => roles.filter(Boolean).sort((a, b) => (RANK[b] || 0) - (RANK[a] || 0))[0] || "-";
const opsF = (k, d = "") => S.opsF[k] || d;
const more = (path) => `<a class="small" data-href="#/operate/${path}">View all</a>`;
const tags = (arr) => (arr.length ? arr.map((x) => `<span class="tag">${esc(x)}</span>`).join("") : '<span class="muted small">none</span>');
const fmtTime = (ts) => (ts ? new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-");
const fmtMin = (m) => (m >= 1440 ? m / 1440 + "d" : m >= 60 ? m / 60 + "h" : m + "m");
const avgOf = (arr) => (arr.length ? Math.round((100 * arr.reduce((a, b) => a + b, 0)) / arr.length) / 100 : 0);
function until(ts) {
  if (!ts) return "-";
  const s = (new Date(ts).getTime() - Date.now()) / 1000;
  if (s <= 0) return ago(ts);
  return s < 3600 ? `in ${Math.ceil(s / 60)}m` : s < 86400 ? `in ${Math.round(s / 3600)}h` : `in ${Math.round(s / 86400)}d`;
}
function chips(key, values, cur) {
  return `<div class="chips">${values.map(([v, l]) => `<span class="chip ${v === cur ? "on" : ""}" data-opsf="${key}" data-opsv="${esc(v)}">${l}</span>`).join("")}</div>`;
}
function sel(key, values, cur, all = "All") {
  return `<select data-opsf="${key}">${all ? `<option value="">${all}</option>` : ""}${values.map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
}
function steps(stages, cur, allDone) {
  const i = stages.indexOf(cur);
  return `<div class="steps">${stages.map((s, k) => `<span class="${allDone || k < i ? "done" : k === i ? "cur" : ""}">${esc(s)}</span>`).join("&rsaquo;")}</div>`;
}
function stackChart(rows, labelFn, keys, colors, h = 160) {
  if (!rows.length) return '<div class="empty">No data</div>';
  const w = 560, pad = 24, bw = (w - pad * 2) / rows.length;
  const max = Math.max(1, ...rows.map((r) => keys.reduce((a, k) => a + (r[k] || 0), 0)));
  const bars = rows.map((r, i) => {
    let y = h - 22;
    const x = pad + i * bw + bw * 0.15;
    const segs = keys.map((k, j) => { const bh = ((h - 40) * (r[k] || 0)) / max; y -= bh; return `<rect x="${x}" y="${y}" width="${bw * 0.7}" height="${bh}" fill="${colors[j]}"><title>${k}: ${r[k]}</title></rect>`; });
    return segs.join("") + `<text x="${x + bw * 0.35}" y="${h - 6}" text-anchor="middle" font-size="10" fill="#5f6b7a">${esc(labelFn(r))}</text>`;
  });
  const legend = keys.map((k, j) => `<span><span class="dot" style="background:${colors[j]}"></span>${k}</span>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">${bars.join("")}</svg><div class="legend">${legend}</div>`;
}
function runStrip(c) {
  const total = RUN_STATES.reduce((a, s) => a + (c[s] || 0), 0) || 1;
  return `<div class="stack">${RUN_STATES.map((s) => `<span style="width:${(100 * (c[s] || 0)) / total}%;background:${RUN_COLORS[s]}" title="${s}"></span>`).join("")}</div>
    <div class="grid g5 section">${RUN_STATES.map((s) => `<div><div class="small muted">${s}</div><div style="font-size:20px;font-weight:600;color:${RUN_COLORS[s]}">${c[s] || 0}</div></div>`).join("")}</div>`;
}

function navResolve(area, sec, sub) {
  const items = NAVS[area].items;
  const n = items.find((x) => x[0] === sec) || items[0];
  return [n, n[3] ? (n[3].find((x) => x[0] === sub) || n[3][0])[0] : undefined];
}
function renderSideNav(r, sec, sub) {
  const nav = $("#sideNav"), cfg = NAVS[r];
  $(".layout").classList.toggle("ops", !!cfg);
  if (!cfg) return nav.classList.add("hidden");
  const [n, s] = navResolve(r, sec, sub);
  nav.classList.remove("hidden");
  nav.innerHTML = `<div class="snhead">${cfg.title}</div>` + cfg.items.map(([k, icon, label, kids]) => {
    const active = k === n[0];
    return `<a class="snitem ${active ? "active" : ""}" data-href="#/${r}/${k}${kids ? "/" + kids[0][0] : ""}"><span class="ic">${icon}</span><span class="lb">${label}</span>${kids ? `<span class="chev">${active ? "&#9662;" : "&#9656;"}</span>` : ""}</a>` +
      (active && kids ? `<div class="snkids">${kids.map(([c, l]) => `<a class="snsub ${c === s ? "active" : ""}" data-href="#/${r}/${k}/${c}">${l}</a>`).join("")}</div>` : "");
  }).join("");
}
async function pageNav(area, sec, sub) {
  const cfg = NAVS[area], [n, s] = navResolve(area, sec, sub);
  const kid = n[3] && n[3].find((x) => x[0] === s);
  const body = await cfg.pages[n[0]](s);
  const crumbs = `<div class="crumbs"><a data-href="#/${area}">${cfg.title}</a> &rsaquo; ${kid ? `<a data-href="#/${area}/${n[0]}">${n[2]}</a> &rsaquo; ${kid[1]}` : n[2]}</div>`;
  view().innerHTML = `${crumbs}${head(kid ? kid[1] : n[2], cfg.desc[n[0]])}${envBanner()}${cfg.banner ? cfg.banner(n[0]) : ""}${body}`;
}

const OPS = {
  async dashboard() {
    const d = await api(`/api/ops/dashboard?env=${E()}`), k = d.kpis;
    const av = [...d.availability].sort((a, b) => a.availability_pct - b.availability_pct).slice(0, 6);
    return `<div class="grid g4">${kpi("Active Products", k.active_products)}${kpi("Healthy Pipelines", k.healthy_pipelines_pct + "%")}${kpi("Open Incidents", `<span style="color:${k.open_incidents ? "var(--red)" : "inherit"}">${k.open_incidents}</span>`)}${kpi("SLA Compliance", k.sla_compliance + "%", `avg availability ${k.availability}%`)}</div>
      <div class="grid g2 section">
        <div class="card"><h3>Pipeline Health ${more("pipelines/monitoring")}</h3>${runStrip(d.pipeline_counts)}</div>
        <div class="card"><h3>Availability Status ${more("availability/health")}</h3>${table(av, [["Product", (r) => `<span class="tl ${r.light}"></span>${esc(r.name)}`], ["Availability", (r) => r.availability_pct + "%"], ["Last refresh", (r) => ago(r.last_refresh)], ["SLA", (r) => pill(r.sla_status)]])}</div>
        <div class="card"><h3>Cost &amp; Budget Trends ${more("budget/cost")}</h3>${colChart(d.cost_trend, monthLbl, "amount")}<div class="small muted">Monthly budget across all domains: <b>${money(d.budget)}</b></div></div>
        <div class="card"><h3>Access Requests ${more("access/requests")}</h3>${table(d.access_requests, [["Request", (r) => `<b>${esc(r.object_name)}</b><div class="small muted">${esc(r.requester)}</div>`], ["Stage", (r) => pill(r.stage || "Steward Approval")], ["Env", (r) => esc(r.env)], ["When", (r) => ago(r.created_at)]], { empty: "No pending requests" })}</div>
      </div>
      <div class="grid g2 section">
        <div class="card"><h3>Recent Deployments ${more("artifacts/releases")}</h3>${table(d.deployments, [["Object", (r) => esc(r.object_name)], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)], ["When", (r) => ago(r.created_at)]])}</div>
        <div class="card"><h3>Failed Jobs ${more("pipelines/recovery")}</h3>${table(d.failed_jobs, [["Pipeline", (r) => `<b>${esc(r.name)}</b>`], ["Product", (r) => esc(r.product)], ["Last run", (r) => ago(r.last_run)], ["", (r) => `<button class="btn sm" data-rerun="${r.id}">Re-run</button>`]], { empty: "No failed jobs" })}</div>
        <div class="card"><h3>Quota Alerts ${more("budget/quota")}</h3>${table(d.quota_alerts, [["Domain", (r) => esc(r.domain)], ["Resource", (r) => esc(r.resource)], ["Used", (r) => `${num(r.used, 1)} / ${num(r.allocated, 1)} ${esc(r.unit)}`], ["", (r) => pill(r.status)]], { empty: "All quotas healthy" })}</div>
        <div class="card"><h3>Product Health Alerts ${more("availability/impact")}</h3>${table(d.product_alerts, [["Product", (r) => `<span class="tl ${r.light}"></span><a data-prod="${r.id}">${esc(r.name)}</a>`], ["Freshness", (r) => pill(r.freshness_state)], ["Quality", (r) => num(r.quality_score, 1)], ["SLA", (r) => pill(r.sla_status)]], { empty: "All products healthy" })}</div>
      </div>`;
  },

  async pipelines(sub) {
    const d = await api(`/api/ops/pipelines?env=${E()}`);
    const envP = d.pipelines.filter((p) => p.env === S.env);
    const pipeCol = ["Pipeline", (r) => `${dot(r.health)}<b>${esc(r.name)}</b>`];
    const prodCol = ["Product", (r) => `<a data-prod="${r.product_id}">${esc(r.product)}</a>`];
    if (sub === "catalog") {
      const uniq = (k) => [...new Set(d.pipelines.map((p) => p[k]))].sort();
      const f = { domain: opsF("domain"), product: opsF("product"), env: opsF("penv"), engine: opsF("engine") };
      const rows = d.pipelines.filter((p) => (!f.domain || p.domain === f.domain) && (!f.product || p.product === f.product) && (!f.env || p.env === f.env) && (!f.engine || p.engine === f.engine));
      return `<div class="card"><div class="filters"><div><label>Domain</label>${sel("domain", uniq("domain"), f.domain)}</div><div><label>Data Product</label>${sel("product", uniq("product"), f.product)}</div>
        <div><label>Environment</label>${sel("penv", ENVS, f.env)}</div><div><label>Technology</label>${sel("engine", uniq("engine"), f.engine)}</div></div>
        <h3>${rows.length} pipelines</h3>${table(rows, [pipeCol, prodCol, ["Domain", (r) => esc(r.domain)], ["Env", (r) => esc(r.env)], ["Technology", (r) => esc(r.engine)], ["Schedule", (r) => (r.paused ? pill("Paused") : esc(r.frequency || "-"))], ["Status", (r) => pill(r.run_state)], ["Last run", (r) => ago(r.last_run)]])}</div>`;
    }
    if (sub === "monitoring") {
      const c = {};
      envP.forEach((p) => (c[p.run_state] = (c[p.run_state] || 0) + 1));
      return `<div class="grid g5">${RUN_STATES.map((s) => kpi(s, `<span style="color:${RUN_COLORS[s]}">${c[s] || 0}</span>`)).join("")}</div>
        <div class="grid g4 section">${kpi("Success Rate (14d)", d.success_rate + "%")}${kpi("Avg Execution Duration", d.avg_duration + " min")}${kpi("Data Processed (14d)", compact(d.rows_processed) + " rows")}${kpi("Failed Runs (14d)", d.trend.reduce((a, t) => a + t.failed, 0))}</div>
        <div class="grid g2 section"><div class="card"><h3>Failure Trends <span class="small muted">runs per day</span></h3>${stackChart(d.trend, (r) => r.day.slice(8), ["succeeded", "failed"], ["#1f9d55", "#d0342c"])}</div>
        <div class="card"><h3>Execution Duration <span class="small muted">avg minutes per day</span></h3>${colChart(d.trend, (r) => r.day.slice(8), "avg_duration")}</div></div>
        <div class="card section"><h3>Pipelines in ${esc(envName(S.env))}</h3>${table(envP, [pipeCol, prodCol, ["Technology", (r) => esc(r.engine)], ["Status", (r) => pill(r.run_state)], ["Last run", (r) => ago(r.last_run)], ["Duration", (r) => r.duration_min + " min"], ["Rows/h", (r) => compact(r.rows_per_hour)],
          ["", (r) => (["Failed", "Delayed", "Queued"].includes(r.run_state) ? `<button class="btn sm" data-rerun="${r.id}">Re-run</button>` : "")]])}</div>`;
    }
    if (sub === "scheduling") {
      return `<div class="grid g5">${d.frequencies.map((fq) => kpi(fq, envP.filter((p) => p.frequency === fq && !p.paused).length, `${envP.filter((p) => p.frequency === fq && p.paused).length} paused`)).join("")}</div>
        <div class="card section"><h3>Schedules</h3>${table(envP, [pipeCol, prodCol,
          ["Frequency", (r) => `<select data-freq="${r.id}" style="width:150px">${d.frequencies.map((fq) => `<option ${fq === r.frequency ? "selected" : ""}>${fq}</option>`).join("")}</select>`],
          ["State", (r) => pill(r.paused ? "Paused" : "Active")], ["Next run", (r) => (r.paused ? "-" : until(r.next_run))],
          ["Actions", (r) => `<div class="btnrow">${r.paused ? `<button class="btn sm primary" data-sched="${r.id}" data-act="resume">Resume</button>` : `<button class="btn sm" data-sched="${r.id}" data-act="pause">Pause</button>`}<button class="btn sm" data-sched="${r.id}" data-act="reschedule">Reschedule</button></div>`]])}</div>`;
    }
    if (sub === "backfill") {
      const pre = opsF("bfPipe");
      return `<div class="grid" style="grid-template-columns: 340px 1fr"><div class="card"><h3>New Backfill</h3>
        <label>Pipeline</label><select id="bfPipe">${envP.map((p) => `<option value="${p.id}" ${String(p.id) === pre ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
        <label>Operation</label><select id="bfKind">${d.backfill_kinds.map((k) => `<option>${k}</option>`).join("")}</select>
        <label>Start date</label><input id="bfStart" type="date"/><label>End date</label><input id="bfEnd" type="date"/>
        <label>Partition (Partition Reload)</label><input id="bfPart" placeholder="business_date=2026-10-01"/>
        <div class="section"><button class="btn primary" id="bfSave">Submit backfill</button></div></div>
        <div class="card"><h3>Backfill Operations</h3>${table(d.backfills, [["Pipeline", (r) => `<b>${esc(r.pipeline)}</b>`], ["Env", (r) => esc(r.env)], ["Operation", (r) => esc(r.kind)], ["Range", (r) => esc([r.start_date, r.end_date].filter(Boolean).join(" to ") || "-")],
          ["Partition", (r) => esc(r.partition_key || "-")], ["Status", (r) => pill(r.status)], ["By", (r) => `<span class="small">${esc(r.requested_by)}</span>`], ["When", (r) => ago(r.created_at)]], { empty: "No backfills submitted" })}</div></div>`;
    }
    const failed = envP.filter((p) => p.status === "Failed"), delayed = envP.filter((p) => p.run_state === "Delayed");
    return `<div class="grid g3">${kpi("Failed Jobs", `<span style="color:var(--red)">${failed.length}</span>`)}${kpi("Delayed Jobs", delayed.length)}${kpi("Success Rate (14d)", d.success_rate + "%")}</div>
      <div class="card section"><h3>Failed Jobs</h3>${table(failed, [pipeCol, prodCol, ["Technology", (r) => esc(r.engine)], ["Last run", (r) => ago(r.last_run)],
        ["Recovery Actions", (r) => `<div class="btnrow"><button class="btn sm primary" data-rerun="${r.id}">Re-run</button><button class="btn sm" data-bf="${r.id}">Backfill</button><button class="btn sm" data-mkinc="${r.id}" data-pid="${r.product_id}" data-name="${esc(r.name)}">Open incident</button></div>`]], { empty: "No failed jobs" })}</div>
      <div class="card section"><h3>Delayed Jobs</h3>${table(delayed, [pipeCol, prodCol, ["Frequency", (r) => esc(r.frequency)], ["Last run", (r) => ago(r.last_run)], ["", (r) => `<button class="btn sm" data-rerun="${r.id}">Trigger now</button>`]], { empty: "No delayed jobs" })}</div>`;
  },

  async availability(sub) {
    const d = await api(`/api/ops/availability?env=${E()}`), P = d.products;
    const cnt = (l) => P.filter((p) => p.light === l).length;
    const top = `<div class="grid g4">${kpi("Avg Availability", avgOf(P.map((p) => p.availability_pct)) + "%")}${kpi("On Time", `<span style="color:var(--green)">${cnt("Green")}</span>`)}${kpi("Delayed", `<span style="color:var(--amber)">${cnt("Amber")}</span>`)}${kpi("Breached", `<span style="color:var(--red)">${cnt("Red")}</span>`)}</div>`;
    const prodCol = ["Data Product", (r) => `<span class="tl ${r.light}"></span><a data-prod="${r.id}">${esc(r.name)}</a>`];
    if (sub === "health") {
      return `${top}<div class="card section"><h3>Availability Dashboard</h3>${table(P, [prodCol, ["Domain", (r) => esc(r.domain)], ["Current Status", (r) => pill(r.sla_status)], ["Last Refresh", (r) => ago(r.last_refresh)],
        ["Availability %", (r) => `<div class="bar" style="width:90px;display:inline-block"><span style="width:${r.availability_pct}%;background:${r.availability_pct >= 99 ? "var(--green)" : r.availability_pct >= 97 ? "var(--amber)" : "var(--red)"}"></span></div> ${r.availability_pct}%`],
        ["Quality", (r) => num(r.quality_score, 1)], ["Pipeline", (r) => (r.pipeline_status ? pill(r.pipeline_status) : "-")]])}</div>`;
    }
    if (sub === "freshness") {
      return `${top}<div class="legend"><span><span class="tl Green"></span>Green = On Time</span><span><span class="tl Amber"></span>Amber = Delayed</span><span><span class="tl Red"></span>Red = Breached</span></div>
        <div class="grid g6">${P.map((p) => `<div class="card tlcard ${p.light}" data-prod="${p.id}"><div class="small muted">${esc(p.domain)}</div><b>${esc(p.name)}</b><div class="small">${esc(p.freshness_state)} &middot; ${num(p.freshness_min)} min old</div></div>`).join("")}</div>
        <div class="card section"><h3>Freshness Monitoring</h3>${table(P, [prodCol, ["SLA", (r) => esc(r.sla)], ["Actual Refresh", (r) => fmtTime(r.last_refresh)], ["Expected Refresh", (r) => fmtTime(r.expected_refresh)], ["Data Delay", (r) => (r.delay_min ? `<b style="color:var(--red)">${num(r.delay_min)} min</b>` : "0 min")], ["State", (r) => pill(r.freshness_state)]])}</div>`;
    }
    if (sub === "sla") {
      return `${top}<div class="grid g2 section"><div class="card"><h3>Availability Report by Domain</h3>${table(d.report, [["Domain", (r) => `<b>${esc(r.domain)}</b>`], ["Products", (r) => r.products], ["Availability", (r) => r.availability + "%"], ["On time", (r) => r.on_time], ["Breaches", (r) => (r.breaches ? `<b style="color:var(--red)">${r.breaches}</b>` : 0)]])}</div>
        <div class="card"><h3>SLA Status</h3>${table(P, [prodCol, ["SLA target", (r) => esc(r.sla)], ["Refresh every", (r) => fmtMin(r.expected_min)], ["Availability", (r) => r.availability_pct + "%"], ["Status", (r) => pill(r.sla_status)]])}</div></div>`;
    }
    return `${top}<div class="grid g2 section">${d.impact.map((i) => {
      const p = P.find((x) => x.id === i.product_id) || {};
      return `<div class="card"><h3><span><span class="tl ${p.light}"></span><a data-prod="${i.product_id}">${esc(i.product)}</a></span>${pill(p.sla_status)}</h3>
        <div class="grid g4">${kpi("Products", i.downstream.length)}${kpi("Dashboards", i.dashboards.length)}${kpi("APIs", i.apis.length)}${kpi("Consumers", i.teams.length)}</div>
        <div class="small section" style="line-height:2"><b>Affected products:</b> ${tags(i.downstream)}<br><b>Affected dashboards:</b> ${tags(i.dashboards)}<br><b>Affected APIs:</b> ${tags(i.apis)}<br><b>Affected consumers:</b> ${tags(i.teams)}</div></div>`;
    }).join("") || '<div class="card"><div class="empty">All data products are on time - no consumer impact</div></div>'}</div>`;
  },

  async access(sub) {
    const d = await api(`/api/ops/access?env=${E()}`);
    if (sub === "review") {
      const ptype = opsF("ptype"), q = opsF("pq").toLowerCase();
      const list = d.principals.filter((x) => (!ptype || x.type === ptype) && (!q || x.name.toLowerCase().includes(q)));
      const who = opsF("principal", list[0]?.name || "");
      const p = d.principals.find((x) => x.name === who) || { name: who, type: "User" };
      const myGroups = d.groups.filter((g) => g.member_list.includes(who)).map((g) => g.name);
      const direct = d.grants.filter((g) => g.principal === who), inherited = d.grants.filter((g) => myGroups.includes(g.principal));
      const envs = [...new Set(d.env_access.filter((e) => e.principal === who || myGroups.includes(e.principal)).map((e) => e.env))];
      const products = {};
      [...direct, ...inherited].forEach((g) => (products[g.product] = maxRole([products[g.product], g.role])));
      return `<div class="grid" style="grid-template-columns: 280px 1fr"><div class="card"><h3>Identities</h3><input data-opsf="pq" value="${esc(opsF("pq"))}" placeholder="Search user, group, service principal"/>
        <div class="section">${chips("ptype", [["", "All"], ["User", "Users"], ["Group", "Groups"], ["Service Principal", "SPs"]], ptype)}</div>
        <ul class="selectlist">${list.map((x) => `<li data-opsf="principal" data-opsv="${esc(x.name)}" class="${x.name === who ? "sel" : ""}"><span class="small">${esc(x.name)}</span><span class="tag">${esc(x.type)}</span></li>`).join("")}</ul></div>
        <div><div class="card"><h3><span>${esc(p.name)} <span class="tag">${esc(p.type)}</span></span></h3><div class="small" style="line-height:2"><b>Groups:</b> ${tags(myGroups)}<br><b>Environment access:</b> ${tags(envs)}</div></div>
        <div class="grid g2 section"><div class="card"><h3>Current Roles <span class="small muted">direct</span></h3>${table(direct, [["Product", (r) => esc(r.product)], ["Role", (r) => pill(r.role)], ["Last access", (r) => ago(r.last_access)], ["", (r) => `<button class="btn sm danger" data-revoke="${r.id}">Revoke</button>`]], { empty: "No direct roles" })}</div>
        <div class="card"><h3>Inherited Roles <span class="small muted">via groups</span></h3>${table(inherited, [["Product", (r) => esc(r.product)], ["Role", (r) => pill(r.role)], ["Via", (r) => `<span class="tag">${esc(r.principal)}</span>`]], { empty: "No inherited roles" })}</div></div>
        <div class="card section"><h3>Product Access <span class="small muted">${esc(envName(S.env))}</span></h3>${table(Object.entries(products), [["Product", (r) => esc(r[0])], ["Effective role", (r) => pill(r[1])]], { empty: "No product access" })}</div></div></div>`;
    }
    if (sub === "requests") {
      const st = opsF("reqstate", "Pending");
      const n = (s) => d.requests.filter((r) => r.state === s).length;
      const rows = d.requests.filter((r) => r.state === st);
      return `<div class="card"><h3>Workflow</h3>${steps(d.stages, null, true)}<div class="small muted section">Each approval stage is recorded in the state store; the final stage provisions a Reader grant.</div></div>
        <div class="section">${chips("reqstate", ["Pending", "Approved", "Rejected", "Expired"].map((s) => [s, `${s} (${n(s)})`]), st)}</div>
        <div class="card">${table(rows, [["Request", (r) => `<b>${esc(r.object_name)}</b><div class="small muted">${esc(r.justification || "")}</div>`], ["Requester", (r) => `<span class="small">${esc(r.requester)}</span>`], ["Env", (r) => esc(r.env)],
          ["Workflow", (r) => (r.status === "Pending" ? steps(d.stages, r.stage) : r.status === "Approved" ? steps(d.stages, "Provision Access", true) : "-")], ["Status", (r) => pill(r.state)], ["When", (r) => ago(r.created_at)],
          ["Actions", (r) => (r.status === "Pending" ? `<div class="btnrow">${r.state === "Expired" ? "" : `<button class="btn sm primary" data-areq="${r.id}">Approve ${esc(r.stage)}</button>`}<button class="btn sm danger" data-reject="${r.id}">Reject</button></div>` : `<span class="small muted">${esc(r.decided_by || "")}</span>`)]], { empty: `No ${st.toLowerCase()} requests` })}</div>`;
    }
    if (sub === "permissions") {
      const who = opsF("eprincipal", "john.doe@corp.com");
      const e = await api(`/api/ops/access/effective?principal=${encodeURIComponent(who)}&env=${E()}`);
      const dr = maxRole(e.permissions.map((p) => p.direct)), ir = maxRole(e.permissions.flatMap((p) => p.inherited.map((i) => i.role)));
      return `<div class="card"><div class="filters" style="grid-template-columns: 360px"><div><label>Identity</label>${sel("eprincipal", d.principals.map((x) => x.name), who, "")}</div></div>
        <div class="grid g4">${kpi("Identity", `<span style="font-size:15px">${esc(who)}</span>`, esc(e.type))}${kpi("Direct Role", dr)}${kpi("Inherited Role", ir, e.groups.length ? "via " + e.groups.map(esc).join(", ") : "no groups")}${kpi("Effective Access", `<span style="color:var(--blue)">${maxRole([dr, ir])}</span>`)}</div></div>
        <div class="card section"><h3>Effective Permissions by Product</h3>${table(e.permissions, [["Product", (r) => `<b>${esc(r.product)}</b>`], ["Direct Role", (r) => (r.direct ? pill(r.direct) : "-")],
          ["Inherited Role", (r) => (r.inherited.length ? r.inherited.map((i) => `${pill(i.role)} <span class="small muted">via ${esc(i.via)}</span>`).join("<br>") : "-")], ["Effective Access", (r) => `<b>${esc(r.effective)}</b>`]], { empty: "No permissions in this environment" })}</div>`;
    }
    if (sub === "groups") {
      return `<div class="card"><h3>Group Management</h3>${table(d.groups, [["Group", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.team)} &middot; ${esc(r.permissions)}</div>`],
        ["Members", (r) => r.member_list.map((m) => `<span class="tag">${esc(m)} <a data-grm="${esc(r.name)}" data-who="${esc(m)}" title="Remove">&times;</a></span>`).join(" ") || '<span class="muted small">none</span>'],
        ["Grants", (r) => r.grants], ["Last review", (r) => esc(r.last_review)], ["Review", (r) => pill(r.review_status)],
        ["Add member", (r) => `<div class="btnrow" style="flex-wrap:nowrap"><input data-gin="${esc(r.name)}" placeholder="user@corp.com" style="width:170px"/><button class="btn sm" data-gadd="${esc(r.name)}">Add</button></div>`],
        ["", (r) => (r.review_status !== "Completed" ? `<button class="btn sm primary" data-review="${r.id}">Complete review</button>` : "")]])}</div>`;
    }
    const reads = d.audit.filter((a) => a.action === "READ"), changes = d.audit.filter((a) => a.action !== "READ");
    const last = {};
    d.grants.filter((g) => g.principal_type !== "Group").forEach((g) => {
      const cur = last[g.principal];
      if (!cur || (g.last_access && (!cur.last_access || g.last_access > cur.last_access))) last[g.principal] = g;
    });
    return `<div class="grid g4">${kpi("Access Events", d.audit.length)}${kpi("Distinct Principals", new Set(d.audit.map((a) => a.principal)).size)}${kpi("Dormant Grants (90d+)", `<span style="color:var(--amber)">${d.dormant.length}</span>`)}${kpi("Permission Changes", changes.length)}</div>
      <div class="grid g2 section"><div class="card"><h3>Who Accessed What</h3>${table(reads.slice(0, 15), [["Principal", (r) => `<span class="small">${esc(r.principal)}</span>`], ["Object", (r) => esc(r.object_name)], ["Detail", (r) => `<span class="small">${esc(r.detail)}</span>`], ["When", (r) => ago(r.created_at)]])}</div>
      <div class="card"><h3>Last Access Time</h3>${table(Object.values(last), [["Principal", (r) => `<span class="small">${esc(r.principal)}</span>`], ["Type", (r) => esc(r.principal_type)], ["Last access", (r) => (r.last_access ? ago(r.last_access) : "never")]])}</div></div>
      <div class="grid g2 section"><div class="card"><h3>Dormant Accounts</h3>${table(d.dormant, [["Principal", (r) => `<span class="small">${esc(r.principal)}</span>`], ["Product", (r) => esc(r.product)], ["Role", (r) => pill(r.role)], ["Last access", (r) => (r.last_access ? ago(r.last_access) : "never")], ["", (r) => `<button class="btn sm danger" data-revoke="${r.id}">Revoke</button>`]], { empty: "No dormant accounts" })}</div>
      <div class="card"><h3>Permission Changes</h3>${table(changes, [["Action", (r) => pill(r.action)], ["Principal", (r) => `<span class="small">${esc(r.principal)}</span>`], ["Object", (r) => esc(r.object_name)], ["Detail", (r) => `<span class="small">${esc(r.detail)}</span>`], ["When", (r) => ago(r.created_at)]])}</div></div>`;
  },

  async budget(sub) {
    const d = await api(`/api/ops/budget?env=${E()}`);
    if (sub === "cost") {
      const prodTotal = d.by_product.reduce((a, b) => a + b.amount, 0);
      return `<div class="grid g5">${kpi(`Total Cost (${esc(envName(S.env))})`, money(d.total), "latest month")}${Object.entries(d.breakdown).map(([k, v]) => kpi(k + " Cost", money(v), Math.round(d.split[k] * 100) + "% allocation")).join("")}${kpi("Data Product Cost", money(prodTotal), "usage-weighted")}</div>
        <div class="grid g2 section"><div class="card"><h3>By Domain</h3>${hbars(d.by_domain, "name", "amount", money)}</div><div class="card"><h3>By Environment</h3>${hbars(d.by_env.map((x) => ({ ...x, env: envName(x.env) })), "env", "amount", money, "#8e5bd0")}</div>
        <div class="card"><h3>By Team</h3>${hbars(d.by_team, "name", "amount", money, "#00a3b4")}</div><div class="card"><h3>By Data Product</h3>${hbars(d.by_product, "name", "amount", money, "#ff6a3d")}</div></div>
        <div class="card section"><h3>Domain Cost Trend</h3>${costTrend(d.domain_trend)}</div>`;
    }
    if (sub === "chargeback") {
      return `<div class="card"><h3>Domain Chargeback <span class="small muted">latest month, all environments</span></h3>${table(d.chargeback, [["Domain", (r) => `<b>${esc(r.domain)}</b>`], ["Team", (r) => `<span class="small">${esc(r.team)}</span>`],
        ...ENVS.map((e) => [e, (r) => money(r[e])]), ["Total", (r) => `<b>${money(r.spend)}</b>`], ["Budget", (r) => money(r.budget)], ["Variance", (r) => `<b style="color:${r.variance < 0 ? "var(--red)" : "var(--green)"}">${money(r.variance)}</b>`], ["Share", (r) => r.share + "%"]])}</div>`;
    }
    if (sub === "usage") {
      const last = d.usage[d.usage.length - 1] || {};
      return `<div class="grid g4">${kpi("Compute (DBU)", compact(last.dbu))}${kpi("Storage", num(last.storage_tb, 1) + " TB")}${kpi("API Calls", compact(last.api_calls))}${kpi("Query Volume", compact(last.queries))}</div>
        <div class="card section"><h3>Workspace Usage</h3>${table(d.workspaces, [["Environment", (r) => `<b>${esc(r.name)}</b>`], ["Workspace", (r) => `<code>${esc(r.workspace)}</code>`], ["Compute (DBU)", (r) => num(r.dbu)], ["Storage (TB)", (r) => num(r.storage_tb, 1)]])}</div>
        <div class="grid g2 section"><div class="card"><h3>Compute Consumption</h3>${colChart(d.usage, monthLbl, "dbu")}</div><div class="card"><h3>Storage Growth (TB)</h3>${colChart(d.usage, monthLbl, "storage_tb")}</div>
        <div class="card"><h3>API Calls</h3>${colChart(d.usage, monthLbl, "api_calls")}</div><div class="card"><h3>Query Volume</h3>${colChart(d.usage, monthLbl, "queries")}</div></div>
        <div class="card section"><h3>Usage by Domain</h3>${table(d.usage_domain, [["Domain", (r) => `<b>${esc(r.domain)}</b>`], ["DBU", (r) => num(r.dbu)], ["Storage (TB)", (r) => num(r.storage_tb, 1)], ["API calls", (r) => compact(r.api_calls)], ["Queries", (r) => compact(r.queries)]])}</div>`;
    }
    if (sub === "quota") {
      const storage = d.quotas.filter((q) => q.resource === "Storage");
      return `<div class="grid g5">${storage.map((q) => `<div class="card"><h3>${esc(q.domain)} ${pill(q.status)}</h3><div class="small" style="line-height:1.8">Allocated: <b>${num(q.allocated)} TB</b><br>Used: <b>${num(q.used, 1)} TB</b><br>Remaining: <b>${num(q.remaining, 1)} TB</b></div><div class="bar section"><span style="width:${Math.min(100, q.pct)}%;background:${q.pct >= 90 ? "var(--red)" : q.pct >= 75 ? "var(--amber)" : "var(--blue)"}"></span></div></div>`).join("")}</div>
        <div class="card section"><h3>Quota Management <span class="small muted">Storage, Compute, Catalogs, Workspaces, Pipelines, Budget</span></h3>${table(d.quotas, [["Domain", (r) => `<b>${esc(r.domain)}</b>`], ["Resource", (r) => esc(r.resource)],
          ["Allocated", (r) => `<input data-qin="${r.id}" type="number" min="0" value="${r.allocated}" style="width:110px"/> <span class="small muted">${esc(r.unit)}</span>`], ["Used", (r) => num(r.used, 1)], ["Remaining", (r) => num(r.remaining, 1)],
          ["Utilisation", (r) => `<div class="bar" style="width:100px;display:inline-block"><span style="width:${Math.min(100, r.pct)}%;background:${r.pct >= 90 ? "var(--red)" : r.pct >= 75 ? "var(--amber)" : "var(--blue)"}"></span></div> ${r.pct}%`],
          ["Status", (r) => pill(r.status)], ["", (r) => `<button class="btn sm" data-qsave="${r.id}">Save</button>`]])}</div>`;
    }
    if (sub === "forecast") {
      const tot = d.forecast.reduce((a, f) => a + f.forecast, 0), bud = d.forecast.reduce((a, f) => a + f.budget, 0);
      return `<div class="grid g4">${kpi("Forecast Monthly Spend", money(tot), "all environments")}${kpi("Monthly Budget", money(bud))}${kpi("Budget Breach Risk", d.forecast.filter((f) => f.risk === "High").length + " domains", d.forecast.filter((f) => f.risk === "Medium").length + " at medium risk")}${kpi("Storage Next Month", num(d.forecast.reduce((a, f) => a + f.storage_next, 0), 1) + " TB")}</div>
        <div class="card section"><h3>Forecast by Domain <span class="small muted">linear projection of the last 6 months</span></h3>${table(d.forecast, [["Domain", (r) => `<b>${esc(r.domain)}</b>`], ["Current spend", (r) => money(r.current)], ["Forecast spend", (r) => `<b>${money(r.forecast)}</b>`], ["Budget", (r) => money(r.budget)], ["Breach risk", (r) => pill(r.risk)],
          ["Storage growth", (r) => `${num(r.storage_now, 1)} &rarr; ${num(r.storage_next, 1)} TB <span class="small muted">(${r.storage_growth_pct}%/mo)</span>`], ["Compute growth", (r) => `${num(r.compute_now)} &rarr; ${num(r.compute_next)} DBU <span class="small muted">(${r.compute_growth_pct}%/mo)</span>`]])}</div>`;
    }
    const save = d.recommendations.reduce((a, r) => a + r.saving, 0);
    return `<div class="grid g3">${kpi("Recommendations", d.recommendations.length)}${kpi("Estimated Monthly Savings", money(save))}${kpi("Budget Risks", d.forecast.filter((f) => f.risk !== "Low").length)}</div>
      <div class="card section"><h3>Optimization Recommendations</h3>${table(d.recommendations, [["Area", (r) => `<span class="tag">${esc(r.area)}</span>`], ["Target", (r) => `<b>${esc(r.target)}</b>`], ["Recommendation", (r) => esc(r.text)], ["Est. saving / month", (r) => money(r.saving)]], { empty: "No recommendations" })}</div>`;
  },

  async artifacts(sub) {
    const d = await api(`/api/ops/artifacts?env=${E()}`);
    if (sub === "catalog") {
      const types = ["Data Product", "Pipeline", "Schema", "Contract", "Policy", "Dashboard", "API"], t = opsF("atype");
      const rows = d.catalog.filter((a) => !t || a.type === t);
      return `<div class="grid" style="grid-template-columns: repeat(7, minmax(0,1fr)); gap:10px">${types.map((x) => kpi(x + "s", d.catalog.filter((a) => a.type === x).length)).join("")}</div>
        <div class="section">${chips("atype", [["", "All"], ...types.map((x) => [x, x])], t)}</div>
        <div class="card">${table(rows, [["Type", (r) => `<span class="tag">${esc(r.type)}</span>`], ["Name", (r) => `<b>${esc(r.name)}</b>`], ["Domain", (r) => esc(r.domain)], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)]])}</div>`;
    }
    if (sub === "releases") {
      const c = (s) => d.releases.filter((r) => r.status === s).length;
      return `<div class="grid g5">${["Succeeded", "Pending", "In Progress", "Failed", "Rolled Back"].map((s) => kpi(s, c(s))).join("")}</div>
        <div class="card section"><h3>Release Tracking</h3>${table(d.releases, [["Object", (r) => `<b>${esc(r.object_name)}</b>`], ["Type", (r) => esc(r.object_type)], ["Version", (r) => esc(r.version)], ["Status", (r) => pill(r.status)], ["Requested by", (r) => `<span class="small">${esc(r.requested_by)}</span>`], ["Notes", (r) => `<span class="small">${esc(r.notes)}</span>`], ["When", (r) => ago(r.created_at)]])}</div>`;
    }
    if (sub === "versions") {
      const names = [...new Set(d.versions.map((v) => v.name))];
      const prod = opsF("aprod", names[0]);
      const list = d.versions.filter((v) => v.name === prod), vs = list.map((v) => v.version);
      const va = vs.includes(opsF("va")) ? opsF("va") : vs[0], vb = vs.includes(opsF("vb")) ? opsF("vb") : vs[vs.length - 1];
      const [ia, ib] = [vs.indexOf(va), vs.indexOf(vb)].sort((a, b) => a - b);
      const diff = list.slice(ia + 1, ib + 1);
      const col = (k) => diff.map((v) => `<li><b>${esc(v.version)}</b> ${esc(v[k])}</li>`).join("") || '<li class="muted">No changes</li>';
      return `<div class="card"><div class="filters" style="grid-template-columns: 260px 160px 160px"><div><label>Data Product</label>${sel("aprod", names, prod, "")}</div><div><label>Compare from</label>${sel("va", vs, va, "")}</div><div><label>Compare to</label>${sel("vb", vs, vb, "")}</div></div>
        <div class="versions">${vs.map((v) => `<span class="ver ${v === d.current[prod] ? "cur" : ""}">${esc(v)}${v === d.current[prod] ? " (current)" : ""}</span>`).join("&rarr;")}</div></div>
        <div class="grid g3 section"><div class="card"><h3>Schema Changes</h3><ul class="small">${col("schema_changes")}</ul></div><div class="card"><h3>Quality Rule Changes</h3><ul class="small">${col("quality_changes")}</ul></div><div class="card"><h3>Contract Changes</h3><ul class="small">${col("contract_changes")}</ul></div></div>
        <div class="card section"><h3>Version History</h3>${table([...list].reverse(), [["Version", (r) => `<b>${esc(r.version)}</b> ${r.version === d.current[prod] ? pill("Current") : ""}`], ["Released", (r) => ago(r.released_at)], ["By", (r) => `<span class="small">${esc(r.released_by)}</span>`], ["Schema", (r) => `<span class="small">${esc(r.schema_changes)}</span>`], ["Quality", (r) => `<span class="small">${esc(r.quality_changes)}</span>`], ["Contract", (r) => `<span class="small">${esc(r.contract_changes)}</span>`]])}</div>`;
    }
    if (sub === "rollback") {
      return `<div class="card"><h3>Rollback Management <span class="small muted">successful releases in ${esc(envName(S.env))}</span></h3>${table(d.rollback, [["Type", (r) => `<span class="tag">${esc(r.object_type)}</span>`], ["Object", (r) => `<b>${esc(r.object_name)}</b>`], ["Version", (r) => esc(r.version)], ["Deployed", (r) => ago(r.created_at)], ["By", (r) => `<span class="small">${esc(r.requested_by)}</span>`], ["", (r) => `<button class="btn sm danger" data-rollback="${r.id}">Rollback ${esc(r.object_type)}</button>`]], { empty: "Nothing to roll back" })}</div>`;
    }
    const c = (s) => d.retirement.filter((r) => r.artifact_state === s).length;
    return `<div class="card"><h3>Artifact Lifecycle</h3><div class="lifecycle">${d.states.map((s) => `<div class="st"><b>${c(s)}</b>${s}</div>`).join('<span class="arrow" style="align-self:center">&rarr;</span>')}</div></div>
      <div class="card section"><h3>Artifact Retirement</h3>${table(d.retirement, [["Data Product", (r) => `<b>${esc(r.name)}</b>`], ["Domain", (r) => esc(r.domain)], ["Version", (r) => esc(r.version || "-")], ["State", (r) => pill(r.artifact_state)],
        ["Move to", (r) => `<div class="btnrow">${d.states.filter((s) => s !== r.artifact_state).map((s) => `<button class="btn sm ${s === "Retired" ? "danger" : ""}" data-astate="${r.id}" data-st="${s}">${s}</button>`).join("")}</div>`]])}</div>`;
  },

  async monitoring() {
    const d = await api(`/api/ops/monitoring?env=${E()}`);
    return `<div class="grid g5">${d.tiles.map((t) => `<div class="card tile t-${TONE[t.status] || "neutral"}"><div class="small muted">${t.name}</div><div style="margin:8px 0">${pill(t.status)}</div><div class="small">${esc(t.metric)}</div></div>`).join("")}</div>
      <div class="grid g4 section">${Object.entries(d.severity).map(([s, n]) => kpi(s, `<span class="sev-${s}">${n}</span>`, "open alerts")).join("")}</div>
      <div class="card section"><h3>Alerts</h3>${table(d.alerts, [["Severity", (r) => pill(r.severity)], ["Category", (r) => esc(r.category)], ["Source", (r) => `<code class="small">${esc(r.source)}</code>`], ["Message", (r) => esc(r.message)], ["Status", (r) => pill(r.status)], ["When", (r) => ago(r.created_at)],
        ["", (r) => (r.status === "Resolved" ? "" : `<div class="btnrow">${r.status === "Open" ? `<button class="btn sm" data-alert="${r.id}" data-act="acknowledge">Acknowledge</button>` : ""}<button class="btn sm primary" data-alert="${r.id}" data-act="resolve">Resolve</button></div>`)]], { empty: "No alerts" })}</div>`;
  },

  async incidents() {
    const d = await api(`/api/ops/incidents?env=${E()}`);
    S.opsInc = d.incidents;
    const open = d.incidents.filter((i) => i.status !== "Resolved");
    return `<div class="grid g4">${kpi("Open Incidents", `<span style="color:var(--red)">${open.length}</span>`)}${kpi("Critical / High", open.filter((i) => ["Critical", "High"].includes(i.severity)).length)}${kpi("Escalated", open.filter((i) => i.status === "Escalated").length)}${kpi("Resolved", d.incidents.length - open.length)}</div>
      <div class="grid section" style="grid-template-columns: 1fr 300px"><div class="card"><h3>Incidents</h3>${table(d.incidents, [
        ["Incident", (r) => `<a data-incview="${r.id}"><b>${esc(r.title)}</b></a><div class="small muted">${esc(r.kind)} &middot; ${esc(r.product || "")} &middot; ${ago(r.created_at)}</div>`], ["Severity", (r) => pill(r.severity)],
        ["Remediation", (r) => steps(["Open", "Investigating", "Escalated", "Resolved"], r.status, r.status === "Resolved")], ["Owner", (r) => `<span class="small">${esc(r.owner || "Unassigned")}</span>`],
        ["Actions", (r) => `<div class="btnrow"><button class="btn sm" data-incview="${r.id}">${r.status === "Resolved" ? "Post-mortem" : "Impact"}</button>${r.status === "Resolved" ? "" : `<button class="btn sm" data-inc="${r.id}" data-act="assign">Assign</button><button class="btn sm" data-inc="${r.id}" data-act="escalate">Escalate</button><button class="btn sm primary" data-inc="${r.id}" data-act="resolve">Resolve</button>`}</div>`]], { empty: "No incidents in this environment" })}</div>
      <div class="card"><h3>Create Incident</h3><label>Type</label><select id="incKind">${d.types.map((t) => `<option>${t}</option>`).join("")}</select><label>Title</label><input id="incTitle"/>
        <label>Severity</label><select id="incSev"><option>Low</option><option selected>Medium</option><option>High</option><option>Critical</option></select>
        <label>Data product</label><select id="incProd"><option value="">(none)</option>${d.products.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
        <div class="section"><button class="btn primary" id="incSave">Create incident</button></div></div></div>`;
  },

  async environments() {
    const d = await api("/api/ops/environments");
    return `<div class="grid g4">${d.environments.map((e) => `<div class="card ${e.code === S.env ? "envsel" : ""}"><h3>${esc(e.name)} ${pill(e.health)}</h3><div class="small muted">${esc(e.region)} &middot; <code>${esc(e.workspace)}</code></div>
        <div class="small section" style="line-height:1.9">Succeeded: <b>${e.deployments.Succeeded || 0}</b> &middot; Pending: <b>${e.deployments.Pending || 0}</b> &middot; Failed: <b>${e.deployments.Failed || 0}</b><br>Configuration drift: <b style="color:${e.drift ? "var(--red)" : "inherit"}">${e.drift}</b><br>Last deployment: ${e.last_deployment ? `${esc(e.last_deployment.object_name)} ${esc(e.last_deployment.version)} (${ago(e.last_deployment.created_at)})` : "-"}</div></div>`).join("")}</div>
      <div class="card section"><h3>Environment Comparison</h3>${table(d.comparison, [["Data Product", (r) => `<b>${esc(r.product)}</b>`], ["Domain", (r) => esc(r.domain)], ...ENVS.map((e) => [e, (r) => (r[e] ? `<span class="${r[e] !== r.PROD ? "diff" : ""}">${esc(r[e])}</span>` : '<span class="muted">-</span>')])])}</div>
      <div class="grid g2 section"><div class="card"><h3>Release Promotion</h3>${table(d.promotions, [["Data Product", (r) => `<b>${esc(r.product)}</b>`], ["Promotion", (r) => `${r.from} &rarr; ${r.to}`], ["Version", (r) => `${esc(r.version)} <span class="small muted">(target: ${esc(r.target_version || "absent")})</span>`],
        ["", (r) => `<button class="btn sm primary" data-promote="1" data-name="${esc(r.product)}" data-ver="${esc(r.version)}" data-to="${r.to}">Promote${r.to === "PROD" ? " (gated)" : ""}</button>`]], { empty: "All environments aligned" })}</div>
      <div class="card"><h3>Configuration Drift</h3>${table(d.drift, [["Object", (r) => `<b>${esc(r.name)}</b>`], ["Type", (r) => esc(r.object_type)], ["Env", (r) => esc(r.env)], ["Current", (r) => esc(r.current_state)], ["Desired", (r) => esc(r.desired_state)], ["Status", (r) => pill(r.status)], ["", (r) => `<button class="btn sm" data-sync="${r.id}">Reconcile</button>`]], { empty: "No drift" })}</div></div>`;
  },

  async sla() {
    const by = opsF("slaby", "product");
    const d = await api(`/api/ops/sla?env=${E()}&by=${by}`), o = d.overall;
    const h = (v, unit = "") => (v === null || v === undefined ? "-" : v + unit);
    return `<div class="grid g6">${kpi("Availability %", h(o.availability))}${kpi("Freshness %", o.freshness_pct)}${kpi("Pipeline Success %", o.pipeline_success)}${kpi("Response Time", h(o.response_time, " min"), "avg end-to-end latency")}${kpi("MTTR", h(o.mttr_h, " h"), "mean time to restore")}${kpi("MTBF", h(o.mtbf_h, " h"), "mean time between failures")}</div>
      <div class="section">${chips("slaby", [["product", "By Product"], ["domain", "By Domain"], ["team", "By Team"], ["environment", "By Environment"]], by)}</div>
      <div class="card">${table(d.rows, [[by[0].toUpperCase() + by.slice(1), (r) => `<b>${esc(by === "environment" ? envName(r.key) : r.key)}</b>`], ["Products", (r) => r.products], ["Availability %", (r) => h(r.availability)], ["Freshness %", (r) => r.freshness_pct], ["Pipeline Success %", (r) => r.pipeline_success],
        ["Response Time", (r) => h(r.response_time, " min")], ["MTTR", (r) => h(r.mttr_h, " h")], ["MTBF", (r) => h(r.mtbf_h, " h")], ["SLA Breaches", (r) => (r.breaches ? `<b style="color:var(--red)">${r.breaches}</b>` : 0)]])}</div>`;
  },
};

function incidentDrawer(i) {
  const im = i.impact || { downstream: [], dashboards: [], apis: [], teams: [] };
  S.pmId = i.id;
  openDrawer(`<h1>${esc(i.title)}</h1><div class="btnrow">${pill(i.severity)} ${pill(i.status)} <span class="muted small">${esc(i.kind)} &middot; ${esc(i.product || "")} &middot; opened ${ago(i.created_at)}</span></div>
    <h3 class="section">View Impact</h3><div class="grid g4">${kpi("Products", im.downstream.length)}${kpi("Dashboards", im.dashboards.length)}${kpi("APIs", im.apis.length)}${kpi("Consumers", im.teams.length)}</div>
    <div class="small section" style="line-height:2"><b>Downstream products:</b> ${tags(im.downstream)}<br><b>Dashboards:</b> ${tags(im.dashboards)}<br><b>APIs:</b> ${tags(im.apis)}<br><b>Consumers:</b> ${tags(im.teams)}</div>
    <h3 class="section">Remediation Tracking</h3>${steps(["Open", "Investigating", "Escalated", "Resolved"], i.status, i.status === "Resolved")}<div class="small muted section">Owner: ${esc(i.owner || "Unassigned")} &middot; Ticket: ${esc(i.ticket || "-")}</div>
    <h3 class="section">Post-Mortem Review</h3><label>Summary</label><input id="pmSummary" value="${esc(i.pm_summary || "")}"/><label>Root cause</label><textarea id="pmRoot">${esc(i.pm_root_cause || "")}</textarea>
    <label>Corrective actions</label><textarea id="pmActions">${esc(i.pm_actions || "")}</textarea>${i.pm_author ? `<div class="small muted">Last updated by ${esc(i.pm_author)}</div>` : ""}
    <div class="section"><button class="btn primary" id="pmSave">Save post-mortem</button></div>`);
}

document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-opsv],[data-sched],[data-qsave],[data-areq],[data-revoke],[data-alert],[data-astate],[data-incview],[data-mkinc],[data-promote],[data-bf],[data-gadd],[data-grm],#bfSave,#incSave,#pmSave");
  if (!el) return;
  const ds = el.dataset;
  if (ds.opsv !== undefined) { S.opsF[ds.opsf] = ds.opsv; return route(); }
  if (ds.sched) {
    const body = { action: ds.act };
    if (ds.act === "reschedule") body.frequency = document.querySelector(`[data-freq="${ds.sched}"]`).value;
    await post(`/api/ops/pipelines/${ds.sched}/schedule`, body); toast("Schedule updated"); return route();
  }
  if (ds.qsave) {
    await api(`/api/ops/quotas/${ds.qsave}`, { method: "PUT", body: { allocated: Number(document.querySelector(`[data-qin="${ds.qsave}"]`).value) } });
    toast("Quota updated"); return route();
  }
  if (ds.areq) { const r = await post(`/api/ops/access/requests/${ds.areq}/advance`); toast(`Moved to ${r.stage}`); return route(); }
  if (ds.revoke) { if (!confirm("Revoke this access?")) return; await post(`/api/ops/access/grants/${ds.revoke}/revoke`); toast("Access revoked"); return route(); }
  if (ds.alert) { await post(`/api/ops/alerts/${ds.alert}/action`, { action: ds.act }); toast("Alert updated"); return route(); }
  if (ds.astate) { await post(`/api/ops/artifacts/${ds.astate}/state`, { state: ds.st }); toast(`Artifact set to ${ds.st}`); return route(); }
  if (ds.incview) return incidentDrawer(S.opsInc.find((i) => i.id === Number(ds.incview)));
  if (ds.mkinc) { await post("/api/ops/incidents", { kind: "Pipeline Failure", title: `${ds.name} failed`, severity: "High", product_id: Number(ds.pid), env: S.env }); return toast("Incident opened"); }
  if (ds.promote) {
    const r = await post("/api/deployments", { object_type: "Product", object_name: ds.name, version: ds.ver, target_env: ds.to });
    toast(r.status === "Pending" ? "Production promotion submitted for approval" : `Promoted to ${envName(ds.to)}`); return route();
  }
  if (ds.bf) { S.opsF.bfPipe = ds.bf; location.hash = "#/operate/pipelines/backfill"; return; }
  if (ds.gadd) {
    const v = document.querySelector(`[data-gin="${ds.gadd}"]`).value.trim();
    if (!v) return toast("Enter a user or service principal", true);
    await post(`/api/ops/groups/${encodeURIComponent(ds.gadd)}/members`, { principal: v }); toast("Member added"); return route();
  }
  if (ds.grm) { await post(`/api/ops/groups/${encodeURIComponent(ds.grm)}/members`, { principal: ds.who, remove: true }); toast("Member removed"); return route(); }
  switch (el.id) {
    case "bfSave":
      await post("/api/ops/backfills", { pipeline_id: Number($("#bfPipe").value), kind: $("#bfKind").value, start_date: $("#bfStart").value, end_date: $("#bfEnd").value, partition_key: $("#bfPart").value });
      toast("Backfill queued"); return route();
    case "incSave":
      await post("/api/ops/incidents", { kind: $("#incKind").value, title: $("#incTitle").value, severity: $("#incSev").value, product_id: $("#incProd").value ? Number($("#incProd").value) : null, env: S.env });
      toast("Incident created"); return route();
    case "pmSave":
      await post(`/api/ops/incidents/${S.pmId}/postmortem`, { summary: $("#pmSummary").value, root_cause: $("#pmRoot").value, actions: $("#pmActions").value });
      toast("Post-mortem saved"); closeDrawer(); return route();
  }
});
function costTrend(rows) {
  const months = [...new Set(rows.map((r) => r.month))], names = [...new Set(rows.map((r) => r.name))];
  const colors = ["#2272b4", "#ff6a3d", "#1f9d55", "#d38b00", "#8e5bd0", "#00a3b4"];
  const W = 900, H = 220, pad = 40, max = Math.max(1, ...rows.map((r) => r.amount));
  const x = (i) => pad + (i * (W - pad * 2)) / Math.max(1, months.length - 1), y = (v) => H - 25 - ((H - 50) * v) / max;
  const lines = names.map((n, k) => {
    const pts = months.map((m, i) => { const r = rows.find((z) => z.month === m && z.name === n); return `${x(i)},${y(r ? r.amount : 0)}`; });
    return `<polyline points="${pts.join(" ")}" fill="none" stroke="${colors[k % 6]}" stroke-width="2"/><text x="${W - pad + 4}" y="${pts[pts.length - 1].split(",")[1]}" style="font-size:11px" fill="${colors[k % 6]}">${esc(n)}</text>`;
  });
  const labels = months.map((m, i) => `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" font-size="11" fill="#5f6b7a">${monthLbl({ month: m })}</text>`);
  return `<svg viewBox="0 0 ${W + 60} ${H}" width="100%" height="${H}">${lines.join("")}${labels.join("")}</svg>`;
}

// ------------------------------------------------------------------ MANAGE (Foundry-style administration center)
const MGMT_NAV = [
  ["teams", "&#128101;", "New Team Onboarding", [["registration", "Team Registration"], ["roles", "Role Assignment"], ["provisioning", "Workspace Provisioning"], ["readiness", "Readiness Checklist"], ["health", "Team Health"]]],
  ["products", "&#128230;", "New Data Product Onboarding", [["registration", "Product Registration"], ["classification", "Data Classification"], ["contracts", "Data Contracts"], ["approval", "Approval Workflow"], ["certification", "Certification"]]],
  ["governance", "&#9878;", "Governance", [["policies", "Policies"], ["standards", "Standards"], ["metadata", "Metadata Management"], ["quality", "Data Quality"], ["compliance", "Compliance"], ["lineage", "Lineage"], ["certification", "Certification"]]],
  ["platform", "&#129513;", "Platform Services", [["ingestion", "Data Ingestion Services"], ["storage", "Storage Services"], ["compute", "Compute Services"], ["catalog", "Catalog Services"], ["monitoring", "Monitoring Services"], ["ai", "AI Services"], ["marketplace", "Service Marketplace"]]],
  ["security", "&#128274;", "Access &amp; Security"],
  ["cost", "&#128176;", "Cost &amp; Chargeback"],
  ["environments", "&#127760;", "Environment Management"],
  ["config", "&#9881;", "Platform Configuration"],
];
const MGMT_DESC = {
  teams: "Onboard a new domain team into the Data Mesh",
  products: "Governed self-service creation and certification of data products",
  governance: "Central governance command center",
  platform: "Operate reusable platform capabilities provided to all domains",
  security: "Access controls, roles, groups and access reviews",
  cost: "Domain cost visibility, chargeback and quotas",
  environments: "Environments, releases and Lakebase desired-state management",
  config: "Platform-wide configuration settings",
};
const REFRESH = ["Near real-time", "Hourly", "Daily", "Weekly"];
const FRESH_MIN = { "Near real-time": 15, Hourly: 60, Daily: 1440, Weekly: 10080 };
const RETENTION = ["1 Year", "3 Years", "7 Years", "10 Years"];
const ACCESS_POLICIES = ["Open within domain", "Request & approve", "Restricted - steward approval"];
const PROV_DETAIL = {
  "Databricks Workspace Access": "Workspace entitlement for the team account group",
  "Unity Catalog Permissions": "USE CATALOG and CREATE SCHEMA on the domain catalog",
  "Git Repository": "data-products/{team} repository from the product template",
  "CI/CD Pipeline": "Build, test and deploy with Databricks Asset Bundles",
  "Monitoring Dashboard": "Operational dashboard and alert routing for the team",
};
const CERT_ACTIONS = { null: ["request"], Expired: ["request"], Revoked: ["request"], Requested: ["review", "revoke"], "Under Review": ["certify", "revoke"], Certified: ["expire", "revoke"] };
const small = (v) => `<span class="small">${esc(v || "-")}</span>`;
const opts = (values, cur) => values.map((v) => `<option ${v === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
const readinessCols = [["Metadata", (r) => pill(r.metadata_status)], ["Contract", (r) => pill(r.contract_status)], ["Security", (r) => pill(r.security_status)], ["Quality", (r) => pill(r.quality_status)], ["Approval", (r) => pill(r.approval_status)]];
function teamPicker(teams, cur) {
  return `<div class="filters" style="grid-template-columns: 320px"><div><label>Team</label><select data-opsf="mteam">${teams.map((t) => `<option value="${t.id}" ${t === cur ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select></div></div>`;
}
function domainRoles(domains) {
  return table(domains, [["Domain", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.description)}</div>`], ["Products", (r) => r.products],
    ["Domain Owner", (r) => `<input data-dom="${r.id}" data-k="owner" value="${esc(r.owner || "")}"/>`], ["Steward", (r) => `<input data-dom="${r.id}" data-k="steward" value="${esc(r.steward || "")}"/>`],
    ["Custodian", (r) => `<input data-dom="${r.id}" data-k="custodian" value="${esc(r.custodian || "")}"/>`], ["", (r) => `<button class="btn sm" data-savedom="${r.id}">Assign</button>`]]);
}
function svcTiles(tiles) {
  return `<div class="grid g5">${tiles.map((t) => `<div class="card tile t-${TONE[t.status] || "neutral"}"><div class="small muted">${t.name}</div><div style="margin:8px 0">${pill(t.status)}</div><div class="small">${esc(t.metric)}</div></div>`).join("")}</div>`;
}

const MGMT = {
  async teams(sub) {
    const d = await api("/api/mgmt/teams");
    const t = d.teams.find((x) => String(x.id) === opsF("mteam")) || d.teams.find((x) => x.status !== "Active") || d.teams[0];
    if (sub === "registration") {
      return `<div class="grid" style="grid-template-columns: 330px 1fr"><div class="card"><h3>Register Team</h3>
        <label>Team name</label><input id="mtName" placeholder="Customer Analytics"/><label>Business unit</label><input id="mtBU" placeholder="Retail Banking"/>
        <label>Domain</label><select id="mtDomain"><option value="">(assign later)</option>${d.domains.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}<option value="new">+ New domain...</option></select>
        <input id="mtNewDomain" placeholder="New domain name" style="display:none;margin-top:8px"/>
        <label>Domain owner</label><input id="mtOwner" placeholder="john.smith@corp.com"/><label>Data steward</label><input id="mtSteward"/><label>Technical lead</label><input id="mtLead"/><label>Product owner</label><input id="mtPO"/>
        <div class="section"><button class="btn primary" id="mtSave">Register team</button></div></div>
        <div><div class="card"><h3>Domain Teams</h3>${table(d.teams, [["Team", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.business_unit || "")}</div>`],
          ["Domain", (r) => `<select data-mtdomain="${r.id}" style="width:130px"><option value="">-</option>${d.domains.map((x) => `<option value="${x.id}" ${x.id === r.domain_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>`],
          ["Owner", (r) => small(r.owner)], ["Steward", (r) => small(r.steward)], ["Tech lead", (r) => small(r.tech_lead)], ["Product owner", (r) => small(r.product_owner)], ["Status", (r) => pill(r.status)],
          ["", (r) => (r.status !== "Active" ? `<button class="btn sm primary" data-mtact="${r.id}">Activate</button>` : "")]])}</div>
        <div class="card section"><h3>Domains <span class="small muted">assign domain roles</span></h3>${domainRoles(d.domains)}</div></div></div>`;
    }
    if (sub === "roles") {
      const by = (p) => t.members.filter((m) => m.persona === p).length;
      return `${teamPicker(d.teams, t)}<div class="grid g6">${d.personas.map((p) => kpi(p, by(p), "members")).join("")}</div>
        <div class="grid section" style="grid-template-columns: 1fr 300px"><div class="card"><h3>${esc(t.name)} members</h3>${table(t.members, [["Member", (r) => `<b>${esc(r.member)}</b>`], ["Persona", (r) => `<span class="tag">${esc(r.persona)}</span>`], ["Added", (r) => ago(r.added_at)], ["", (r) => `<button class="btn sm danger" data-mtrm="${r.id}">Remove</button>`]], { empty: "No members" })}</div>
        <div class="card"><h3>Assign Role</h3><label>Member</label><input id="mtMember" placeholder="user@corp.com"/><label>Persona</label><select id="mtPersona">${opts(d.personas)}</select><div class="section"><button class="btn primary" id="mtAddMember">Add member</button></div></div></div>`;
    }
    if (sub === "provisioning") {
      const done = Object.values(t.provisioning).filter((s) => s === "Provisioned").length, n = d.provision_items.length;
      const slug = t.name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
      return `${teamPicker(d.teams, t)}<div class="card"><h3>Automated Workspace Setup <span class="btnrow"><span class="small muted">${done} / ${n} provisioned</span>${done < n ? '<button class="btn sm primary" data-mtprov="all">Provision all</button>' : ""}</span></h3>
        <div class="bar" style="margin-bottom:12px"><span style="width:${(100 * done) / n}%;background:var(--green)"></span></div>
        ${table(d.provision_items.map((i) => ({ item: i, status: t.provisioning[i] })), [["Capability", (r) => `<b>${esc(r.item)}</b>`], ["Details", (r) => small(PROV_DETAIL[r.item].replace("{team}", slug))], ["Status", (r) => pill(r.status)],
          ["", (r) => (r.status !== "Provisioned" ? `<button class="btn sm" data-mtprov="${esc(r.item)}">Provision</button>` : "")]])}</div>`;
    }
    if (sub === "readiness") {
      const items = d.checklist_items;
      return `${teamPicker(d.teams, t)}<div class="grid g2"><div class="card"><h3>${esc(t.name)} ${pill(t.status)}</h3>
        <ul class="checklist">${items.map((i) => `<li class="${t.checklist[i] ? "done" : ""}"><span>${t.checklist[i] ? "&#10003;" : "&#9675;"} ${i}</span><button class="btn sm" data-mtchk="${esc(i)}" data-done="${t.checklist[i] ? 0 : 1}">${t.checklist[i] ? "Reopen" : "Mark done"}</button></li>`).join("")}</ul>
        <div class="section">${t.status === "Active" ? '<span class="muted small">Team is active</span>' : `<button class="btn primary" data-mtact="${t.id}">Activate team</button>`}</div></div>
        <div class="card"><h3>All Teams</h3>${table(d.teams, [["Team", (r) => `<b>${esc(r.name)}</b>`], ["Readiness", (r) => {
          const k = items.filter((i) => r.checklist[i]).length;
          return `<div class="bar" style="width:100px;display:inline-block"><span style="width:${(100 * k) / items.length}%;background:var(--green)"></span></div> ${k}/${items.length}`;
        }], ["Status", (r) => pill(r.status)]])}</div></div>`;
    }
    const comp = d.teams.map((x) => x.health.compliance).filter((x) => x !== null);
    return `<div class="grid g4">${kpi("Teams", d.teams.length)}${kpi("Active Teams", d.teams.filter((x) => x.status === "Active").length)}${kpi("Members", d.teams.reduce((a, x) => a + x.health.active_members, 0))}${kpi("Avg Governance Compliance", avgOf(comp) + "%")}</div>
      <div class="card section"><h3>Team Health</h3>${table(d.teams, [["Team", (r) => `<b>${esc(r.name)}</b>`], ["Domain", (r) => esc(r.domain || "-")], ["Active Members", (r) => r.health.active_members], ["Products Owned", (r) => r.health.products],
        ["SLA Performance", (r) => (r.health.sla === null ? "-" : r.health.sla + "%")], ["SLA Breaches", (r) => (r.health.breaches ? `<b style="color:var(--red)">${r.health.breaches}</b>` : 0)],
        ["Governance Compliance", (r) => (r.health.compliance === null ? "-" : `<div class="bar" style="width:90px;display:inline-block"><span style="width:${r.health.compliance}%;background:${r.health.compliance >= 80 ? "var(--green)" : "var(--amber)"}"></span></div> ${r.health.compliance}%`)],
        ["Status", (r) => pill(r.status)]])}</div>`;
  },

  async products(sub) {
    const d = await api("/api/mgmt/products"), P = d.products;
    S.mgmtProducts = P;
    const prodCol = ["Data Product", (r) => `<a data-prod="${r.id}"><b>${esc(r.name)}</b></a><div class="small muted">${esc(r.domain)}</div>`];
    if (sub === "registration") {
      return `<div class="grid" style="grid-template-columns: 340px 1fr"><div class="card"><h3>Register Product</h3><div class="small muted">Business information</div>
        <label>Product name</label><input id="mpName"/><label>Domain</label><select id="mpDomain">${d.domains.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select>
        <label>Description</label><textarea id="mpDesc"></textarea><label>Use cases</label><input id="mpUse"/><label>Consumers</label><input id="mpCons" placeholder="Finance BI, Risk"/>
        <div class="small muted section">Technical information</div><label>Source systems (comma separated)</label><input id="mpSources" placeholder="erp.gl_entries, crm.accounts"/>
        <label>Target tables</label><input id="mpTarget" placeholder="finance.gold.my_product"/><label>Refresh frequency</label><select id="mpRefresh">${opts(REFRESH, "Daily")}</select>
        <label>Retention policy</label><select id="mpRet">${opts(RETENTION, "3 Years")}</select><div class="section"><button class="btn primary" id="mpSave">Register product</button></div></div>
        <div class="card"><h3>Product Readiness Dashboard</h3>${table(P, [prodCol, ...readinessCols])}</div></div>`;
    }
    if (sub === "classification") {
      return `<div class="grid" style="grid-template-columns: repeat(8, minmax(0,1fr)); gap:10px">${d.classifications.map((c) => kpi(c, P.filter((p) => p.classification === c).length)).join("")}${kpi("Unclassified", `<span style="color:var(--red)">${P.filter((p) => !p.classification).length}</span>`)}</div>
        <div class="card section"><h3>Data Classification</h3>${table(P, [prodCol, ["Tags", (r) => (r.tags || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("")], ["Retention", (r) => esc(r.retention_policy || "-")],
          ["Classification", (r) => `<select data-mpclass="${r.id}" style="width:190px"><option value="">(unclassified)</option>${opts(d.classifications, r.classification)}</select>`]])}</div>`;
    }
    if (sub === "contracts") {
      const sel_ = P.find((p) => String(p.id) === opsF("mcprod")) || P[0];
      return `<div class="card"><div class="filters" style="grid-template-columns: 300px"><div><label>Data product</label><select id="mcProd" data-opsf="mcprod">${P.map((p) => `<option value="${p.id}" ${p === sel_ ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></div></div>
        <div class="grid g2"><div><h3>Producer Contract</h3><div class="small muted">Schema: ${((sel_.schema_def || {}).columns || []).length} columns &middot; Owner: ${esc(sel_.owner)} &middot; Status: ${pill(sel_.contract_status)}</div>
          <label>SLA</label><input id="mcSla" value="${esc(sel_.sla || "")}"/><label>Refresh schedule</label><select id="mcRefresh">${opts(REFRESH, sel_.refresh_frequency)}</select></div>
        <div><h3>Consumer Contract</h3><label>Expected volume</label><input id="mcVol" value="${esc(sel_.expected_volume || "")}" placeholder="10M rows/day"/><label>Usage limits</label><input id="mcLimits" value="${esc(sel_.usage_limits || "")}" placeholder="1000 queries/day"/>
          <label>Access policy</label><select id="mcPolicy">${opts(ACCESS_POLICIES, sel_.access_policy)}</select></div></div>
        <div class="section"><button class="btn primary" id="mcSave">Save contract</button> <span class="small muted">A producer contract is created when none exists.</span></div></div>
        <div class="card section"><h3>Data Contracts</h3>${table(P, [prodCol, ["Producer", (r) => pill(r.contract_status)], ["Contracts", (r) => r.contracts.map((c) => `<span class="tag">${esc(c.kind)}</span>`).join("")], ["SLA", (r) => esc(r.sla)], ["Refresh", (r) => esc(r.refresh_frequency || "-")],
          ["Expected volume", (r) => small(r.expected_volume)], ["Usage limits", (r) => small(r.usage_limits)], ["Access policy", (r) => small(r.access_policy)]])}</div>`;
    }
    if (sub === "approval") {
      return `<div class="card"><h3>Approval Workflow</h3>${steps(d.stages, null, true)}<div class="small muted section">Owner &rarr; Data Steward &rarr; Security &rarr; Governance review, then Publish. Security review requires a classification.</div></div>
        <div class="card section">${table(P, [prodCol, ["Lifecycle", (r) => pill(r.lifecycle)], ["Workflow", (r) => steps(d.stages, r.review_stage, r.review_stage === "Published")],
          ["Actions", (r) => (r.review_stage === "Published" ? '<span class="small muted">Published</span>' : `<div class="btnrow"><button class="btn sm primary" data-mprev="${r.id}" data-dec="approve">Approve ${esc(r.review_stage)}</button><button class="btn sm danger" data-mprev="${r.id}" data-dec="reject">Reject</button></div>`)]])}</div>`;
    }
    return `<div class="grid g4">${d.cert_levels.map((l) => kpi(l, P.filter((p) => p.cert_status === "Certified" && p.cert_level === l).length, "certified")).join("")}</div>
      <div class="card section"><h3>Product Certification <span class="small muted">certification reviews are managed in Governance &rsaquo; Certification</span></h3>${table(P, [prodCol, ["Readiness", (r) => pill(r.compliant ? "Complete" : "Incomplete")], ["Quality", (r) => num(r.quality, 1)],
        ["Level", (r) => `<select data-mpcl="${r.id}" style="width:210px">${opts(d.cert_levels, r.cert_level)}</select>`], ["Status", (r) => (r.cert_status ? pill(r.cert_status) : '<span class="muted small">Not requested</span>')],
        ["", (r) => ((CERT_ACTIONS[r.cert_status] || []).includes("request") ? `<button class="btn sm primary" data-mpcert="${r.id}" data-act="request">Request certification</button>` : "")]])}</div>`;
  },

  async governance(sub) {
    const d = await api(`/api/mgmt/governance?env=${E()}`);
    const ruleCards = (kind) => d.areas[kind].map((a) => {
      const rows = d.rules.filter((r) => r.kind === kind && r.area === a);
      return `<div class="card"><h3>${a}</h3>${rows.map((r) => `<div class="rule"><div><b>${esc(r.name)}</b> ${r.value ? `<span class="pill info">${esc(r.value)}</span>` : ""}</div><div class="small muted">${esc(r.rule)}</div></div>`).join("") || '<div class="empty">No rules</div>'}</div>`;
    }).join("");
    const ruleForm = (kind) => `<div class="card"><h3>New ${kind}</h3><label>Area</label><select id="grArea">${opts(d.areas[kind])}</select><label>Name</label><input id="grName"/><label>Value</label><input id="grValue" placeholder="${kind === "Policy" ? "7 Years" : "v1"}"/><label>Rule</label><textarea id="grRule"></textarea><div class="section"><button class="btn primary" id="grSave" data-kind="${kind}">Add ${kind.toLowerCase()}</button></div></div>`;
    const prodCol = ["Data Product", (r) => `<a data-prod="${r.id}"><b>${esc(r.name)}</b></a>`];
    if (sub === "policies") {
      return `<div class="grid" style="grid-template-columns: 1fr 300px"><div class="grid g2">${ruleCards("Policy")}</div>${ruleForm("Policy")}</div>
        <div class="card section"><h3>Policy Lifecycle</h3>${table(d.policies, [["Name", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.description)}</div>`], ["Category", (r) => esc(r.category)], ["Lifecycle", (r) => pill(r.lifecycle)], ["Owner", (r) => small(r.owner)], ["", (r) => (r.lifecycle !== "Retired" ? `<button class="btn sm" data-advance="${r.id}">Advance</button>` : "")]])}</div>`;
    }
    if (sub === "standards") return `<div class="grid" style="grid-template-columns: 1fr 300px"><div class="grid g2">${ruleCards("Standard")}</div>${ruleForm("Standard")}</div>`;
    if (sub === "metadata") {
      const m = d.metadata;
      return `<div class="grid g4">${kpi("Products Missing Metadata", m.missing_metadata.length)}${kpi("Missing Owners", m.missing_owners.length)}${kpi("Missing Classifications", m.missing_classification.length)}${kpi("Incomplete Documentation", m.incomplete_docs.length)}</div>
        <div class="grid g2 section"><div class="card"><h3>Products Missing Metadata</h3>${table(m.missing_metadata, [prodCol, ["Missing", (r) => r.missing_metadata.map((x) => `<span class="tag">${esc(x)}</span>`).join("")]], { empty: "All products have complete metadata" })}</div>
        <div class="card"><h3>Missing Owners</h3>${table(m.missing_owners, [prodCol, ["Owner", (r) => small(r.owner)], ["Steward", (r) => small(r.steward)]], { empty: "All products have owners and stewards" })}</div>
        <div class="card"><h3>Missing Classifications <a class="small" data-href="#/manage/products/classification">Classify</a></h3>${table(m.missing_classification, [prodCol, ["Domain", (r) => esc(r.domain)]], { empty: "All products classified" })}</div>
        <div class="card"><h3>Incomplete Documentation</h3>${table(m.incomplete_docs, [prodCol, ["Use cases", (r) => (r.use_cases ? "&#10003;" : '<span style="color:var(--red)">missing</span>')], ["Undocumented columns", (r) => r.undocumented_columns.length]], { empty: "Documentation complete" })}</div></div>`;
    }
    if (sub === "quality") {
      return `<div class="grid g4">${Object.entries(d.dimensions).map(([k, v]) => kpi(k, v + "%")).join("")}</div>
        <div class="card section"><h3>Data Quality Management <span class="small muted">${esc(envName(S.env))}</span></h3>${table(d.quality, [prodCol, ["Domain", (r) => esc(r.domain)], ["Quality Score", (r) => `<b>${r.score}</b>`],
          ["Trend", (r) => (r.trend === null ? "-" : `<span style="color:${r.trend >= 0 ? "var(--green)" : "var(--red)"}">${r.trend >= 0 ? "&#9650;" : "&#9660;"} ${Math.abs(r.trend)}</span>`)],
          ["Violations", (r) => (r.violations ? `<b style="color:var(--red)">${r.violations}</b>` : 0)], ...Object.keys(d.dimensions).map((k) => [k, (r) => num(r.dimensions[k], 1)])], { empty: "No quality rules in this environment" })}</div>`;
    }
    if (sub === "compliance") {
      const fw = [...new Set(d.compliance.map((c) => c.framework))];
      return `<div class="grid g3">${d.compliance_states.map((s) => kpi(s, `<span class="sev-${s.replace(/\W/g, "")}">${d.compliance.filter((c) => c.status === s).length}</span>`)).join("")}</div>
        ${fw.map((f) => `<div class="card section"><h3>${esc(f)}</h3>${table(d.compliance.filter((c) => c.framework === f), [["Control", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.requirement)}</div>`], ["Owner", (r) => small(r.owner)], ["Status", (r) => pill(r.status)],
          ["Assess", (r) => `<select data-cpl="${r.id}" style="width:150px">${opts(d.compliance_states, r.status)}</select>`], ["Last assessed", (r) => ago(r.last_assessed)]])}</div>`).join("")}`;
    }
    if (sub === "lineage") {
      const cross = d.lineage.filter((l) => l.kind === "cross-domain").length;
      return `<div class="grid g4">${kpi("Lineage Edges", d.lineage.length)}${kpi("Cross-domain", cross)}${kpi("Intra-domain", d.lineage.length - cross)}${kpi("Products with Lineage", new Set(d.lineage.flatMap((l) => [l.source, l.target])).size)}</div>
        <div class="card section"><h3>Data Lineage <a class="btn sm" data-href="#/topology">Open Mesh Topology</a></h3>${table(d.lineage, [["Source", (r) => `<b>${esc(r.source)}</b><div class="small muted">${esc(r.source_domain)}</div>`], ["", () => "&rarr;"], ["Target", (r) => `<b>${esc(r.target)}</b><div class="small muted">${esc(r.target_domain)}</div>`], ["Kind", (r) => pill(r.kind === "cross-domain" ? "Cross-domain" : "Intra-domain")]])}</div>`;
    }
    const C = d.certification;
    return `<div class="card"><h3>Certification Lifecycle</h3><div class="lifecycle">${d.cert_states.map((s) => `<div class="st"><b>${C.filter((c) => c.cert_status === s).length}</b>${s}</div>`).join('<span class="arrow" style="align-self:center">&rarr;</span>')}</div></div>
      <div class="card section"><h3>Certification Management</h3>${table(C, [prodCol, ["Level", (r) => esc(r.cert_level || "-")], ["Status", (r) => (r.cert_status ? pill(r.cert_status) : '<span class="muted small">Not requested</span>')], ["Readiness", (r) => pill(r.compliant ? "Complete" : "Incomplete")], ["Quality", (r) => num(r.quality, 1)],
        ["Actions", (r) => `<div class="btnrow">${(CERT_ACTIONS[r.cert_status] || []).map((a) => `<button class="btn sm ${a === "certify" ? "primary" : a === "revoke" ? "danger" : ""}" data-mpcert="${r.id}" data-act="${a}">${a[0].toUpperCase() + a.slice(1)}</button>`).join("")}</div>`]])}</div>`;
  },

  async platform(sub) {
    const d = await api("/api/mgmt/platform");
    S.mgmtTeams = d.teams;
    const svc = (c) => d.services.filter((s) => s.category === c);
    if (sub === "ingestion") {
      const C = svc("Ingestion");
      const onTime = (r) => r.details.last_sync && (Date.now() - new Date(r.details.last_sync).getTime()) / 60000 <= r.details.sla_min;
      return `<div class="grid g4">${kpi("Connectors", C.length)}${kpi("Healthy", C.filter((c) => c.status === "Healthy").length)}${kpi("Warning / Error", C.filter((c) => c.status !== "Healthy").length)}${kpi("Records (24h)", compact(C.reduce((a, c) => a + (c.details.records_24h || 0), 0)))}</div>
        <div class="grid section" style="grid-template-columns: 1fr 300px"><div class="card"><h3>Connectors</h3>${table(C, [["Connector", (r) => `<b>${esc(r.name)}</b>`], ["Source", (r) => `<span class="tag">${esc(r.details.source_type)}</span>`], ["Schedule", (r) => esc(r.details.schedule)],
          ["Last sync", (r) => ago(r.details.last_sync)], ["SLA", (r) => `${fmtMin(r.details.sla_min)} ${pill(onTime(r) ? "On Time" : "Breached")}`], ["Records (24h)", (r) => compact(r.details.records_24h)], ["Status", (r) => pill(r.status)],
          ["", (r) => `<button class="btn sm" data-psvc="${r.id}" data-act="sync">Sync now</button>`]])}</div>
        <div class="card"><h3>Create Connector</h3><label>Name</label><input id="pcName" placeholder="HubSpot Connector"/><label>Source type</label><select id="pcType">${opts(d.connector_types)}</select>
          <label>Schedule</label><select id="pcSched">${opts(["15 Minutes", "Hourly", "Daily", "Weekly", "Event Driven", "Streaming"], "Daily")}</select><label>SLA (minutes)</label><input id="pcSla" type="number" value="1440"/>
          <div class="section"><button class="btn primary" id="pcSave">Create connector</button></div></div></div>`;
    }
    if (sub === "storage") {
      const C = svc("Storage");
      return `<div class="grid g4">${kpi("Capacity", num(C.reduce((a, c) => a + c.details.capacity_tb, 0)) + " TB")}${kpi("Used", num(C.reduce((a, c) => a + c.details.used_tb, 0), 1) + " TB")}${kpi("Avg Growth", avgOf(C.map((c) => c.details.growth_pct)) + "%/mo")}${kpi("Monthly Cost", money(C.reduce((a, c) => a + c.details.cost_month, 0)))}</div>
        <div class="grid g5 section">${C.map((s) => {
          const p = (100 * s.details.used_tb) / s.details.capacity_tb;
          return `<div class="card"><h3>${esc(s.name)} ${pill(s.status)}</h3><div class="small" style="line-height:1.8">Capacity: <b>${num(s.details.used_tb, 1)} / ${num(s.details.capacity_tb)} TB</b><br>Retention: ${esc(s.details.retention)}<br>Growth: <b>${s.details.growth_pct}%/mo</b><br>Cost: <b>${money(s.details.cost_month)}/mo</b></div><div class="bar section"><span style="width:${p}%;background:${p > 85 ? "var(--amber)" : "var(--blue)"}"></span></div></div>`;
        }).join("")}</div>`;
    }
    if (sub === "compute") {
      const C = svc("Compute"), run = C.filter((c) => c.details.state === "Running");
      return `<div class="grid g4">${kpi("Compute Services", C.length)}${kpi("Running", run.length)}${kpi("Stopped", C.length - run.length)}${kpi("Daily Cost (running)", money(run.reduce((a, c) => a + c.details.cost_day, 0)))}</div>
        <div class="card section"><h3>Clusters, SQL Warehouses, Serverless Pools, Workflows and Jobs</h3>${table(C, [["Name", (r) => `<b>${esc(r.name)}</b>`], ["Type", (r) => `<span class="tag">${esc(r.details.type)}</span>`], ["Size", (r) => small(r.details.size)],
          ["Auto Scaling", (r) => (r.details.autoscale ? `${pill("Active")} <span class="small muted">${r.details.min_workers}-${r.details.max_workers}</span>` : pill("Paused"))], ["State", (r) => pill(r.details.state)], ["Cost / day", (r) => money(r.details.cost_day)],
          ["Actions", (r) => `<div class="btnrow">${r.details.state === "Running" ? `<button class="btn sm" data-psvc="${r.id}" data-act="stop">Stop</button>` : `<button class="btn sm primary" data-psvc="${r.id}" data-act="start">Start</button>`}<button class="btn sm" data-psvc="${r.id}" data-act="autoscale">${r.details.autoscale ? "Disable" : "Enable"} autoscale</button></div>`]])}
        <div class="small muted section">Cost optimization: stop idle interactive clusters and enable autoscaling on shared compute.</div></div>`;
    }
    if (sub === "catalog") {
      return `<div class="card"><h3>Catalog Services</h3>${table(svc("Catalog"), [["Service", (r) => `<b>${esc(r.name)}</b>`], ["Objects", (r) => num(r.details.objects)], ["Coverage", (r) => `<div class="bar" style="width:100px;display:inline-block"><span style="width:${r.details.coverage_pct}%"></span></div> ${r.details.coverage_pct}%`],
        ["Last sync", (r) => ago(r.details.last_sync)], ["Status", (r) => pill(r.status)], ["", (r) => `<button class="btn sm" data-psvc="${r.id}" data-act="sync">Sync now</button>`]])}</div>`;
    }
    if (sub === "monitoring") return `${svcTiles(d.monitoring)}<div class="section small muted">Platform-wide health. Drill into <a data-href="#/operate/monitoring">Operate &rsaquo; Monitoring &amp; Alerting</a> for alerts.</div>`;
    if (sub === "ai") {
      const C = svc("AI");
      return `<div class="grid g4">${kpi("Requests (24h)", compact(C.reduce((a, c) => a + c.details.requests_24h, 0)))}${kpi("Avg Response Time", Math.round(avgOf(C.map((c) => c.details.latency_ms))) + " ms")}${kpi("Monthly Cost", money(C.reduce((a, c) => a + c.details.cost_month, 0)))}${kpi("Tokens (24h)", compact(C.reduce((a, c) => a + c.details.tokens_24h, 0)))}</div>
        <div class="card section"><h3>AI Services</h3>${table(C, [["Service", (r) => `<b>${esc(r.name)}</b>`], ["Requests (24h)", (r) => num(r.details.requests_24h)], ["Response Time", (r) => r.details.latency_ms + " ms"], ["Cost / month", (r) => money(r.details.cost_month)], ["Tokens (24h)", (r) => compact(r.details.tokens_24h)], ["Status", (r) => pill(r.status)]])}</div>`;
    }
    const cats = [...new Set(d.marketplace.map((m) => m.category))];
    return `${cats.map((c) => `<h3 class="section">${esc(c)}</h3><div class="grid g3">${d.marketplace.filter((m) => m.category === c).map((m) => `<div class="card offer"><div class="title">${esc(m.item)}</div><div class="small muted">${esc(m.description)}</div><div class="btnrow section"><span class="tag">SLA ${esc(m.sla)}</span><button class="btn sm primary" data-mkt="${esc(m.item)}">Request</button></div></div>`).join("")}</div>`).join("")}
      <div class="card section"><h3>Service Requests</h3>${table(d.requests, [["Item", (r) => `<b>${esc(r.item)}</b><div class="small muted">${esc(r.category)}</div>`], ["Team", (r) => esc(r.team || "-")], ["Requester", (r) => small(r.requester)], ["Justification", (r) => small(r.justification)], ["Status", (r) => pill(r.status)], ["When", (r) => ago(r.created_at)],
        ["", (r) => `<div class="btnrow">${r.status === "Submitted" ? `<button class="btn sm primary" data-mreq="${r.id}" data-act="approve">Approve</button>` : ""}${r.status === "Approved" ? `<button class="btn sm primary" data-mreq="${r.id}" data-act="fulfil">Fulfil</button>` : ""}${["Submitted", "Approved"].includes(r.status) ? `<button class="btn sm danger" data-mreq="${r.id}" data-act="reject">Reject</button>` : ""}</div>`]])}</div>`;
  },

  async security() {
    const d = await api(`/api/manage?env=${E()}`);
    return `<div class="grid g4">${["RBAC", "ABAC", "Row Security", "Column Security"].map((k) => kpi(k, d.security.filter((s) => s.kind === k).length + " controls")).join("")}</div>
      <div class="grid g2 section"><div class="card"><h3>Access Controls</h3>${table(d.security, [["Control", (r) => `<b>${esc(r.name)}</b>`], ["Type", (r) => esc(r.kind)], ["Target", (r) => `<code>${esc(r.target)}</code>`], ["Rule", (r) => `<code class="small">${esc(r.rule)}</code>`], ["Status", (r) => pill(r.status)]])}</div>
      <div class="card"><h3>Roles</h3>${table(d.roles, [["Role", (r) => `<b>${esc(r.name)}</b><div class="small muted">${esc(r.description)}</div>`], ["Members", (r) => r.members], ["Privileges", (r) => small(r.privileges)]])}</div></div>
      <div class="card section"><h3>Groups and Access Reviews <a class="small" data-href="#/operate/access/review">Production IAM in Operate</a></h3>${table(d.groups, [["Group", (r) => `<b>${esc(r.name)}</b>`], ["Team", (r) => esc(r.team)], ["Members", (r) => r.members], ["Permissions", (r) => `<code class="small">${esc(r.permissions)}</code>`], ["Last review", (r) => esc(r.last_review)], ["Review", (r) => pill(r.review_status)], ["", (r) => (r.review_status !== "Completed" ? `<button class="btn sm primary" data-review="${r.id}">Complete review</button>` : "")]])}</div>`;
  },

  async cost() {
    const [cost, chargeback, quota] = await Promise.all([OPS.budget("cost"), OPS.budget("chargeback"), OPS.budget("quota")]);
    return `${cost}<div class="section">${chargeback}</div><div class="section">${quota}</div>`;
  },

  async environments() {
    const [d, st] = await Promise.all([api(`/api/manage?env=${E()}`), api(`/api/state?env=${E()}`)]);
    const byEnv = {};
    st.summary.forEach((s) => ((byEnv[s.env] = byEnv[s.env] || {})[s.status] = s.n));
    return `<div class="grid g4">${d.environments.map((e) => `<div class="card ${e.code === S.env ? "envsel" : ""}"><h3>${esc(e.name)} ${pill(e.health)}</h3><div class="small muted">${esc(e.region)} &middot; ${esc(e.workspace)}</div><div class="grid g2 section">${kpi("Active", e.active)}${kpi("Pending", e.pending)}${kpi("Succeeded", e.succeeded)}${kpi("Out of sync", e.drift)}</div>
        <div class="btnrow">${pill("Synced")} ${byEnv[e.code]?.Synced || 0} ${pill("Pending")} ${byEnv[e.code]?.Pending || 0} ${pill("Drift")} ${byEnv[e.code]?.Drift || 0}</div></div>`).join("")}</div>
      <div class="grid g2 section"><div class="card"><h3>Active Deployments and Pending Releases</h3>${table(d.active_deployments, [["Object", (r) => esc(r.object_name)], ["Version", (r) => esc(r.version)], ["Env", (r) => esc(envName(r.env))], ["Status", (r) => pill(r.status)], ["When", (r) => ago(r.created_at)]])}</div>
      <div class="card"><h3>Rollback History</h3>${table(d.rollbacks, [["Object", (r) => esc(r.object_name)], ["Version", (r) => esc(r.version)], ["Env", (r) => esc(envName(r.env))], ["By", (r) => small(r.requested_by)], ["When", (r) => ago(r.created_at)]], { empty: "No rollbacks" })}</div></div>
      <div class="card section"><h3>State Management: Current vs Desired (${esc(envName(S.env))}) <span class="btnrow"><button class="btn sm" id="stDrift">Run drift analysis</button><button class="btn sm primary" id="stSync">Sync environment</button></span></h3>
      ${table(st.objects, [["Object", (r) => `<b>${esc(r.name)}</b>`], ["Type", (r) => esc(r.object_type)], ["Current", (r) => esc(r.current_state)], ["Desired", (r) => esc(r.desired_state)], ["Status", (r) => pill(r.status)], ["Updated", (r) => ago(r.updated_at)], ["", (r) => (r.status !== "Synced" ? `<button class="btn sm" data-sync="${r.id}">Reconcile</button>` : "")]])}
      <p class="muted small">Desired state is written by Build and Deployment Hub; current state is reconciled from runtime. Both are persisted in the state store (schema <code>mesh</code>).</p></div>`;
  },

  async config() {
    const d = await api("/api/mgmt/config");
    const cats = [...new Set(d.map((c) => c.category))];
    return `<div class="grid g2">${cats.map((c) => `<div class="card"><h3>${esc(c)}</h3>${table(d.filter((x) => x.category === c), [["Setting", (r) => `<b>${esc(r.setting)}</b><div class="small muted">${esc(r.description)}</div>`],
      ["Value", (r) => `<input data-cfgin="${esc(r.setting)}" value="${esc(r.value)}" style="width:170px"/>`], ["Updated", (r) => `<span class="small">${ago(r.updated_at)} &middot; ${esc(r.updated_by || "")}</span>`], ["", (r) => `<button class="btn sm" data-cfgsave="${esc(r.setting)}">Save</button>`]])}</div>`).join("")}</div>`;
  },
};

const NAVS = {
  build: { title: "Build", items: BUILD_NAV, desc: BUILD_DESC, pages: BUILD, banner: buildBanner },
  operate: { title: "Operate", items: OPS_NAV, desc: OPS_DESC, pages: OPS },
  manage: { title: "Manage", items: MGMT_NAV, desc: MGMT_DESC, pages: MGMT },
};

document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-mtrm],[data-mtprov],[data-mtchk],[data-mtact],[data-mprev],[data-mpcert],[data-psvc],[data-mkt],[data-mreq],[data-cfgsave],#mtSave,#mtAddMember,#mpSave,#mcSave,#grSave,#pcSave,#mkSave");
  if (!el) return;
  const ds = el.dataset, tid = () => document.querySelector("[data-opsf='mteam']").value;
  const done = (msg) => { toast(msg); return route(); };
  if (ds.mtrm) { await post(`/api/mgmt/teams/${tid()}/members/${ds.mtrm}/remove`); return done("Member removed"); }
  if (ds.mtprov) { await post(`/api/mgmt/teams/${tid()}/provision`, { item: ds.mtprov }); return done("Provisioned"); }
  if (ds.mtchk) { await post(`/api/mgmt/teams/${tid()}/checklist`, { item: ds.mtchk, done: ds.done === "1" }); return done("Checklist updated"); }
  if (ds.mtact) { await post(`/api/mgmt/teams/${ds.mtact}/activate`); return done("Team activated"); }
  if (ds.mprev) { const r = await post(`/api/mgmt/products/${ds.mprev}/review`, { decision: ds.dec }); return done(r.stage === "Published" ? "Product published" : `Moved to ${r.stage}`); }
  if (ds.mpcert) {
    const lvl = document.querySelector(`[data-mpcl="${ds.mpcert}"]`);
    const r = await post(`/api/mgmt/products/${ds.mpcert}/certification`, { action: ds.act, level: lvl ? lvl.value : undefined });
    return done(`Certification ${r.cert_status.toLowerCase()}`);
  }
  if (ds.psvc) { await post(`/api/mgmt/platform/services/${ds.psvc}/action`, { action: ds.act }); return done("Service updated"); }
  if (ds.mkt) {
    S.mkItem = ds.mkt;
    return openDrawer(`<h1>Request: ${esc(ds.mkt)}</h1><label>Team</label><select id="mkTeam">${opts(S.mgmtTeams || [])}</select><label>Justification</label><textarea id="mkJust"></textarea><div class="section"><button class="btn primary" id="mkSave">Submit request</button></div>`);
  }
  if (ds.mreq) { await post(`/api/mgmt/platform/requests/${ds.mreq}/action`, { action: ds.act }); return done("Request updated"); }
  if (ds.cfgsave) {
    await api(`/api/mgmt/config/${encodeURIComponent(ds.cfgsave)}`, { method: "PUT", body: { value: document.querySelector(`[data-cfgin="${ds.cfgsave}"]`).value } });
    return done("Setting saved");
  }
  switch (el.id) {
    case "mtSave": {
      let domainId = $("#mtDomain").value;
      if (domainId === "new") {
        const nm = $("#mtNewDomain").value.trim();
        if (!nm) return toast("Enter the new domain name", true);
        domainId = (await post("/api/domains", { name: nm, owner: $("#mtOwner").value, steward: $("#mtSteward").value })).id;
      }
      await post("/api/mgmt/teams", { name: $("#mtName").value, business_unit: $("#mtBU").value, domain_id: domainId ? Number(domainId) : null,
        owner: $("#mtOwner").value, steward: $("#mtSteward").value, tech_lead: $("#mtLead").value, product_owner: $("#mtPO").value });
      return done("Team registered");
    }
    case "mtAddMember": await post(`/api/mgmt/teams/${tid()}/members`, { member: $("#mtMember").value, persona: $("#mtPersona").value }); return done("Member added");
    case "mpSave": {
      const name = $("#mpName").value.trim();
      if (!name) return toast("Product name is required", true);
      const p = await post("/api/products", { domain_id: Number($("#mpDomain").value), name, description: $("#mpDesc").value, sources: $("#mpSources").value.split(",").map((s) => s.trim()).filter(Boolean), columns: [], sla: $("#mpRefresh").value, tags: [] });
      await api(`/api/mgmt/products/${p.id}/onboarding`, { method: "PUT", body: { use_cases: $("#mpUse").value, consumers: $("#mpCons").value, target_tables: $("#mpTarget").value, refresh_frequency: $("#mpRefresh").value, retention_policy: $("#mpRet").value } });
      return done(`Product ${p.name} registered`);
    }
    case "mcSave": {
      const pid = Number($("#mcProd").value), p = S.mgmtProducts.find((x) => x.id === pid);
      await api(`/api/mgmt/products/${pid}/onboarding`, { method: "PUT", body: { refresh_frequency: $("#mcRefresh").value, expected_volume: $("#mcVol").value, usage_limits: $("#mcLimits").value, access_policy: $("#mcPolicy").value } });
      if (p.contract_status === "Missing") await post("/api/contracts", { product_id: pid, kind: "Producer", sla: $("#mcSla").value, freshness_minutes: FRESH_MIN[$("#mcRefresh").value], completeness: ">= 99%", terms: $("#mcPolicy").value });
      return done("Contract saved");
    }
    case "grSave": await post("/api/mgmt/governance/rules", { kind: ds.kind, area: $("#grArea").value, name: $("#grName").value, value: $("#grValue").value, rule: $("#grRule").value }); return done(`${ds.kind} added`);
    case "pcSave": await post("/api/mgmt/platform/services", { name: $("#pcName").value, source_type: $("#pcType").value, schedule: $("#pcSched").value, sla_min: Number($("#pcSla").value) }); return done("Connector created");
    case "mkSave": await post("/api/mgmt/platform/requests", { item: S.mkItem, team: $("#mkTeam").value, justification: $("#mkJust").value }); closeDrawer(); return done("Request submitted");
  }
});

// ------------------------------------------------------------------ router
const ROUTES = { command: pageCommand, home: pageHome, discover: pageDiscover, topology: pageTopology,
  build: (a, b) => pageNav("build", a, b), operate: (a, b) => pageNav("operate", a, b), manage: (a, b) => pageNav("manage", a, b) };
async function route() {
  if (!S.ctx) return;
  const [r, sub, sub2] = (location.hash.replace(/^#\/?/, "") || "command").split("/");
  const fn = ROUTES[r] || pageCommand;
  document.querySelectorAll("#mainnav a").forEach((a) => a.classList.toggle("active", a.dataset.route === r));
  renderSideNav(r, sub, sub2);
  try { await fn(sub, sub2); } catch (e) { view().innerHTML = `<div class="card"><h3>Unable to load</h3><div class="muted">${esc(e.message)}</div></div>`; }
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ event delegation
document.addEventListener("click", async (ev) => {
  const el = ev.target.closest("[data-route],[data-go],[data-href],[data-env],[data-region],[data-source],[data-prod],[data-reqaccess],[data-approve],[data-reject],[data-pnode],[data-dom],[data-uc],[data-gen],[data-rerun],[data-inc],[data-rollback],[data-advance],[data-review],[data-sync],[data-savedom],button[id],#drawer");
  if (!el) return;
  const ds = el.dataset;
  if (el.id === "drawer" && ev.target.id === "drawer") return closeDrawer();
  if (ds.route) return (location.hash = "#/" + ds.route);
  if (ds.go) return (location.hash = "#/" + ds.go);
  if (ds.href) return (location.hash = ds.href);
  if (ds.env) { S.env = ds.env; return savePrefs(); }
  if (ds.region) { S.region = ds.region; return savePrefs(); }
  if (ds.source) { S.source = ds.source; return savePrefs(); }
  if (ds.reqaccess) return requestAccess(ds.reqaccess);
  if (ds.prod && !el.closest("#topoSvg")) return openProduct(ds.prod);
  if (ds.approve || ds.reject) {
    await post(`/api/approvals/${ds.approve || ds.reject}/decision`, { decision: ds.approve ? "Approved" : "Rejected" });
    toast(ds.approve ? "Approved" : "Rejected"); S.ctx = await api("/api/context"); $("#notifBadge").textContent = S.ctx.notifications.approvals + S.ctx.notifications.incidents; return route();
  }
  if (ds.pnode) return topoSelect(Number(ds.pnode));
  if (ds.dom && el.closest("#topoSvg")) return topoSelect(null, Number(ds.dom));
  if (ds.uc !== undefined) return loadUC(ds.uc || undefined, ds.ucs);
  if (ds.gen) { const r = await post("/api/generate", { product_id: Number($("#aiProd").value), kind: ds.gen }); $("#aiOut").textContent = r.code; return; }
  if (ds.rerun) { await post(`/api/pipelines/${ds.rerun}/rerun`); toast("Pipeline re-run triggered"); return route(); }
  if (ds.inc) {
    let body = { action: ds.act };
    if (ds.act === "assign") { const o = prompt("Assign to (email):", S.ctx.user); if (!o) return; body.owner = o; }
    await post(`/api/incidents/${ds.inc}/action`, body); toast("Incident updated"); return route();
  }
  if (ds.rollback) { if (!confirm("Roll back this deployment?")) return; await post(`/api/deployments/${ds.rollback}/rollback`); toast("Rolled back"); return route(); }
  if (ds.advance) { await post(`/api/policies/${ds.advance}/advance`); toast("Lifecycle advanced"); return route(); }
  if (ds.review) { await post(`/api/groups/${ds.review}/review`); toast("Access review completed"); return route(); }
  if (ds.sync) { await post("/api/state/sync", { id: Number(ds.sync), env: S.env }); toast("Object reconciled"); return route(); }
  if (ds.savedom) {
    const v = (k) => document.querySelector(`[data-dom="${ds.savedom}"][data-k="${k}"]`).value;
    await api(`/api/domains/${ds.savedom}`, { method: "PUT", body: { owner: v("owner"), steward: v("steward"), custodian: v("custodian") } }); toast("Domain roles assigned"); return;
  }
  switch (el.id) {
    case "drawerClose": return closeDrawer();
    case "helpBtn": return openDrawer(`<h1>Help</h1><p>The Data Mesh Control Plane follows a Home, Discover, Build, Operate, Manage navigation model. Use the left panel to switch environment, region and state source. All state (domains, products, deployments, approvals, contracts, lineage) is persisted in Lakebase schema <code>mesh</code>.</p><p>Mesh Topology shows domains, products, contracts and cross-domain consumption. State Management compares current vs desired state across environments.</p>`);
    case "notifBtn": {
      const [a, h] = await Promise.all([api("/api/approvals?status=Pending"), api(`/api/home?env=${E()}`)]);
      return openDrawer(`<h1>Notifications</h1><h3>Pending approvals</h3>${approvalList(a)}<h3 class="section">Recent events</h3>${table(h.events, [["Event", (r) => esc(r.message)], ["When", (r) => ago(r.created_at)]])}`);
    }
    case "prodSearchBtn": S.filters.q = $("#prodSearch").value; return loadProducts();
    case "cSave": await post("/api/contracts", { product_id: Number($("#cProd").value), kind: $("#cKind").value, consumer_domain_id: $("#cCons").value ? Number($("#cCons").value) : null, sla: $("#cSla").value, freshness_minutes: Number($("#cFresh").value), completeness: $("#cComp").value, terms: $("#cTerms").value }); toast("Contract created"); return route();
    case "plSave": {
      const name = $("#plName").value.trim(); if (!name) return toast("Pipeline name is required", true);
      await post("/api/pipelines", { name, product_id: Number($("#plProd").value), env: $("#plEnv").value, engine: $("#plEngine").value, layers: [...document.querySelectorAll(".plLayer:checked")].map((x) => x.value) });
      toast("Pipeline created and desired state recorded"); return route();
    }
    case "aiCopy": navigator.clipboard.writeText($("#aiOut").textContent); return toast("Copied");
    case "dGo": {
      const env = document.querySelector("input[name=dEnv]:checked").value;
      const r = await post("/api/deployments", { object_type: $("#dType").value, object_name: $("#dObj").value, version: $("#dVer").value, target_env: env });
      toast(r.status === "Pending" ? "Production release submitted for approval" : `Deployed to ${envName(env)}`); return route();
    }
    case "stDrift": { const r = await post("/api/state/detect-drift", { env: S.env }); toast(`${r.drift} drift(s) detected`); return route(); }
    case "stSync": { const r = await post("/api/state/sync", { env: S.env }); toast(`${r.synced} object(s) reconciled`); return route(); }
    case "topoReset": return pageTopology();
  }
});
document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.dataset.opsf !== undefined && t.dataset.opsv === undefined) { S.opsF[t.dataset.opsf] = t.value; return route(); }
  if (t.id === "mtDomain") { $("#mtNewDomain").style.display = t.value === "new" ? "" : "none"; return; }
  if (t.dataset.mtdomain && t.value) { post(`/api/mgmt/teams/${t.dataset.mtdomain}/domain`, { domain_id: Number(t.value) }).then(() => toast("Domain assigned")); return; }
  if (t.dataset.mpclass !== undefined) { api(`/api/mgmt/products/${t.dataset.mpclass}/onboarding`, { method: "PUT", body: { classification: t.value } }).then(() => { toast("Classification saved"); route(); }); return; }
  if (t.dataset.cpl) { post(`/api/mgmt/governance/compliance/${t.dataset.cpl}`, { status: t.value }).then(() => { toast("Assessment recorded"); route(); }); return; }
  if (t.dataset.facet !== undefined) { S.filters.domains = [...document.querySelectorAll("[data-facet]:checked")].map((x) => x.dataset.facet); return loadProducts(); }
  if (t.name === "cert") { S.filters.certified = t.value === "" ? null : t.value === "true"; return loadProducts(); }
  if (t.id === "plEngine" || t.classList.contains("plLayer")) { $("#plFlow").innerHTML = flowHtml([...document.querySelectorAll(".plLayer:checked")].map((x) => x.value), $("#plEngine").value); }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter") return;
  if (ev.target.id === "prodSearch") { S.filters.q = ev.target.value; loadProducts(); }
  if (ev.target.id === "globalSearch") { S.filters = { q: ev.target.value, domains: [], certified: null }; location.hash = "#/discover/catalog"; route(); }
});

(async () => { if (await loadContext()) route(); })();

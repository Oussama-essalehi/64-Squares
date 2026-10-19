/* 64 Squares — tableau de bord web.
 * The data file holds counts at the finest grain the filters need; every rate is computed here,
 * after summing the selected cells, and hidden when the group has fewer games than the minimum.
 */
"use strict";

const state = { tc: 0, band: 0, side: "white", min: 1000, page: "overview", family: null, data: null };
const PAGES = ["overview", "openings", "elo", "activity"];
const fmtPct = (v, d = 1) => (v == null || !isFinite(v) ? "—" : (v * 100).toFixed(d).replace(".", ",") + " %");
const fmtPts = (v, d = 1) => (v == null || !isFinite(v) ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(d).replace(".", ",") + " pts");
const fmtInt = (v) => Math.round(v).toLocaleString("fr-FR");

// ---------------------------------------------------------------------------------------
// Data helpers
// ---------------------------------------------------------------------------------------
function rows(name) {
  const cols = state.data.columns[name];
  return state.data.tables[name].map((r) => Object.fromEntries(cols.map((c, i) => [c, r[i]])));
}
const cache = {};
function table(name) { return (cache[name] ||= rows(name)); }
const inFilter = (r, { band = true, tc = true } = {}) =>
  (!band || state.band === 0 || r.b === state.band) && (!tc || state.tc === 0 || r.t === state.tc);

function groupSum(list, keyFn, fields) {
  const out = new Map();
  for (const r of list) {
    const k = keyFn(r);
    const acc = out.get(k) || Object.fromEntries(fields.map((f) => [f, 0]));
    for (const f of fields) acc[f] += r[f] || 0;
    out.set(k, acc);
  }
  return out;
}
const enough = (n) => n >= state.min;

// ---------------------------------------------------------------------------------------
// Theme and plotting
// ---------------------------------------------------------------------------------------
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function baseLayout(extra = {}) {
  return Object.assign({
    paper_bgcolor: css("--surface"), plot_bgcolor: css("--surface"),
    font: { family: "system-ui, -apple-system, Segoe UI, sans-serif", size: 13, color: css("--ink") },
    margin: { l: 56, r: 16, t: 16, b: 48 },
    xaxis: { gridcolor: css("--grid"), linecolor: css("--axis"), zeroline: false, tickfont: { color: css("--ink-2") } },
    yaxis: { gridcolor: css("--grid"), linecolor: css("--axis"), zeroline: false, tickfont: { color: css("--ink-2") } },
    legend: { orientation: "h", y: 1.12, x: 0, font: { color: css("--ink-2") } },
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--border"), font: { color: css("--ink") } },
    bargap: 0.3,
  }, extra);
}
const CONFIG = { displayModeBar: false, responsive: true };

function card(id) { return document.querySelector(`[data-chart="${id}"]`); }
function draw(id, traces, layout, tableData) {
  const el = card(id);
  const chart = el.querySelector(".chart");
  if (!traces.length) {
    Plotly.purge(chart);
    chart.innerHTML = "";
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = `Pas assez de parties pour cette sélection (minimum ${fmtInt(state.min)}).`;
    chart.appendChild(p);
  } else {
    if (chart.querySelector(".empty")) chart.innerHTML = "";
    Plotly.react(chart, traces, baseLayout(layout), CONFIG);
  }
  if (tableData) renderTable(el.querySelector(".table-wrap"), tableData.head, tableData.body);
}

function renderTable(wrap, head, body, onPick) {
  wrap.textContent = "";
  const t = document.createElement("table");
  t.className = "data";
  const thead = t.createTHead().insertRow();
  const textCols = new Set([0, ...(body[0]?.txt || [])]);
  head.forEach((h, i) => { const th = document.createElement("th"); th.textContent = h; if (textCols.has(i)) th.className = "txt"; thead.appendChild(th); });
  const tb = t.createTBody();
  body.forEach((row) => {
    const tr = tb.insertRow();
    row.cells.forEach((v, i) => { const td = tr.insertCell(); td.textContent = v; if (i === 0 || row.txt?.includes(i)) td.className = "txt"; if (row.cls?.[i]) td.classList.add(row.cls[i]); });
    if (onPick) { tr.classList.add("pick"); tr.tabIndex = 0; tr.addEventListener("click", () => onPick(row.key)); tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onPick(row.key); }); if (row.key === state.family) tr.classList.add("active"); }
  });
  wrap.appendChild(t);
}

// ---------------------------------------------------------------------------------------
// Page 1 — overview
// ---------------------------------------------------------------------------------------
function renderOverview() {
  const { bands, time_controls: tcs } = state.data.meta;
  const res = table("results");
  const sel = res.filter((r) => inFilter(r));
  const tot = sel.reduce((a, r) => ({ n: a.n + r.n, ww: a.ww + r.ww, d: a.d + r.d, bw: a.bw + r.bw, lot: a.lot + r.lot, e: a.e + r.e }), { n: 0, ww: 0, d: 0, bw: 0, lot: 0, e: 0 });
  const ok = enough(tot.n);
  const kpis = [
    ["Parties analysées", fmtInt(tot.n), "après nettoyage"],
    ["Score moyen des Blancs", ok ? fmtPct((tot.ww + 0.5 * tot.d) / tot.n) : "—", ok ? `${fmtPts((tot.ww + 0.5 * tot.d - tot.e) / tot.n)} au-delà du classement` : ""],
    ["Parties nulles", ok ? fmtPct(tot.d / tot.n) : "—", ""],
    ["Défaites au temps", ok ? fmtPct(tot.lot / tot.n) : "—", "chute du drapeau"],
  ];
  const box = document.getElementById("kpis");
  box.textContent = "";
  kpis.forEach(([label, value, sub]) => {
    const d = document.createElement("div"); d.className = "kpi";
    for (const [cls, txt] of [["label", label], ["value", value], ["sub", sub]]) { const s = document.createElement("div"); s.className = cls; s.textContent = txt; d.appendChild(s); }
    box.appendChild(d);
  });

  // Results by band (100 % stacked), respecting the time-control filter
  const byBand = groupSum(res.filter((r) => inFilter(r, { band: false })), (r) => r.b, ["n", "ww", "d", "bw"]);
  const bandIdx = [...byBand.keys()].sort().filter((b) => enough(byBand.get(b).n));
  const x = bandIdx.map((b) => bands[b - 1]);
  const parts = [["ww", "Victoire Blancs", "--white-pole"], ["d", "Nulle", "--draw"], ["bw", "Victoire Noirs", "--black-pole"]];
  const traces = bandIdx.length ? parts.map(([k, name, color]) => ({
    type: "bar", name, x, y: bandIdx.map((b) => byBand.get(b)[k] / byBand.get(b).n),
    marker: { color: css(color), line: { color: css("--surface"), width: 2 } },
    text: k === "d" ? [] : bandIdx.map((b) => fmtPct(byBand.get(b)[k] / byBand.get(b).n)), textposition: "inside",
    insidetextfont: { color: k === "d" ? css("--ink") : "#ffffff" },
    hovertemplate: `${name}<br>%{x} : %{y:.1%}<extra></extra>`,
  })) : [];
  draw("results-band", traces, { barmode: "stack", legend: { ...baseLayout().legend, traceorder: "normal" }, yaxis: { ...baseLayout().yaxis, tickformat: ".0%" }, uniformtext: { minsize: 11, mode: "show" } }, {
    head: ["Tranche", "Parties", "Victoires Blancs", "Nulles", "Victoires Noirs"],
    body: bandIdx.map((b) => { const v = byBand.get(b); return { cells: [bands[b - 1], fmtInt(v.n), fmtPct(v.ww / v.n), fmtPct(v.d / v.n), fmtPct(v.bw / v.n)] }; }),
  });

  // Games by time control, respecting the band filter
  const byTc = groupSum(res.filter((r) => inFilter(r, { tc: false })), (r) => r.t, ["n"]);
  const tcIdx = [...byTc.keys()].sort();
  draw("games-tc", [{
    type: "bar", x: tcIdx.map((t) => tcs[t - 1]), y: tcIdx.map((t) => byTc.get(t).n),
    marker: { color: tcIdx.map((t) => (state.tc === 0 || state.tc === t ? css("--accent") : css("--grid"))), line: { color: css("--surface"), width: 2 } },
    text: tcIdx.map((t) => fmtInt(byTc.get(t).n)), textposition: "outside", textfont: { color: css("--ink-2") },
    hovertemplate: "%{x} : %{y:,} parties<extra></extra>",
  }], { yaxis: { ...baseLayout().yaxis, title: "Parties", range: [0, Math.max(1, ...tcIdx.map((t) => byTc.get(t).n)) * 1.15] } }, {
    head: ["Cadence", "Parties"], body: tcIdx.map((t) => ({ cells: [tcs[t - 1], fmtInt(byTc.get(t).n)] })),
  });

  // White score heatmap band x time control (all cells, ignoring filters so the grid stays complete)
  const z = [], text = [], body = [];
  for (let b = 1; b <= bands.length; b++) {
    const zr = [], tr = [];
    for (let t = 1; t <= tcs.length; t++) {
      const r = res.find((q) => q.b === b && q.t === t);
      const v = r && enough(r.n) ? (r.ww + 0.5 * r.d) / r.n : null;
      zr.push(v); tr.push(v == null ? "n < min" : `<b>${fmtPct(v)}</b><br>n = ${fmtInt(r.n)}`);
      if (v != null) body.push({ cells: [bands[b - 1], tcs[t - 1], fmtInt(r.n), fmtPct(v)], txt: [1] });
    }
    z.push(zr); text.push(tr);
  }
  const spread = Math.max(0.01, ...z.flat().filter((v) => v != null).map((v) => Math.abs(v - 0.5)));
  draw("white-score", [{
    type: "heatmap", z, x: tcs, y: bands, text, texttemplate: "%{text}", textfont: { color: css("--ink"), size: 13 },
    colorscale: [[0, css("--black-pole")], [0.5, css("--mid")], [1, css("--white-pole")]], zmin: 0.5 - spread, zmax: 0.5 + spread,
    xgap: 2, ygap: 2, colorbar: { tickformat: ".0%", outlinewidth: 0, tickfont: { color: css("--ink-2") } },
    hovertemplate: "%{y} · %{x}<br>score des Blancs %{z:.1%}<extra></extra>",
  }], { margin: { l: 90, r: 16, t: 10, b: 40 } }, { head: ["Tranche", "Cadence", "Parties", "Score des Blancs"], body });
}

// ---------------------------------------------------------------------------------------
// Page 2 — openings
// ---------------------------------------------------------------------------------------
function openingStats() {
  const list = table("openings").filter((r) => inFilter(r) && r.c === state.side);
  const byFam = groupSum(list, (r) => r.f, ["n", "w", "d", "p", "e"]);
  const total = [...byFam.values()].reduce((a, v) => a + v.n, 0);
  return [...byFam.entries()].map(([f, v]) => ({ f, ...v, share: v.n / total })).sort((a, b) => b.n - a.n);
}

function renderOpenings() {
  const stats = openingStats();
  const ranked = stats.filter((s) => enough(s.n));
  const top = ranked.slice(0, 10);
  if (!state.family || !ranked.some((s) => s.f === state.family)) state.family = top[0]?.f ?? null;
  const side = state.side === "white" ? "Blancs" : "Noirs";
  draw("top-openings", top.length ? [{
    type: "bar", orientation: "h", y: top.map((s) => s.f).reverse(), x: top.map((s) => s.share).reverse(),
    marker: { color: top.map((s) => (s.f === state.family ? css("--accent") : css("--b1"))).reverse(), line: { color: css("--surface"), width: 2 } },
    text: top.map((s) => fmtPct(s.share)).reverse(), textposition: "outside", textfont: { color: css("--ink-2") },
    customdata: top.map((s) => [fmtInt(s.n), fmtPct(s.p / s.n)]).reverse(),
    hovertemplate: `%{y}<br>%{x:.1%} des parties · %{customdata[0]} parties<br>score des ${side} %{customdata[1]}<extra></extra>`,
  }] : [], { margin: { l: 190, r: 40, t: 10, b: 40 }, xaxis: { ...baseLayout().xaxis, tickformat: ".0%", range: [0, Math.max(0.01, ...top.map((s) => s.share)) * 1.2] } }, {
    head: ["Famille", "Parties", "Part"], body: top.map((s) => ({ cells: [s.f, fmtInt(s.n), fmtPct(s.share)] })),
  });

  const info = state.data.openings;
  renderTable(document.getElementById("opening-table"),
    ["Rang", "Famille", "Choisie par", "Parties", "Part", "% victoires", `Score des ${side}`, "Score − attendu", "Marge 95 %"],
    ranked.map((s, i) => {
      const perf = (s.p - s.e) / s.n, ci = 1.96 * 0.5 / Math.sqrt(s.n);
      return { key: s.f, txt: [1, 2], cls: { 7: Math.abs(perf) > ci ? "sig" : "" },
        cells: [String(i + 1), s.f, info[s.f]?.chosen_by ?? "—", fmtInt(s.n), fmtPct(s.share), fmtPct(s.w / s.n), fmtPct(s.p / s.n), fmtPts(perf), "± " + fmtPts(ci).replace("+", "")] };
    }),
    (fam) => { state.family = fam; renderOpenings(); });
  renderBoard(ranked.find((s) => s.f === state.family));
}

function renderBoard(s) {
  const panel = document.getElementById("board-panel");
  panel.textContent = "";
  if (!s) return;
  const info = state.data.openings[s.f];
  if (info) {
    const img = document.createElement("img");
    img.src = `boards/${info.board}.svg`; img.alt = `Position après ${info.moves}`; img.width = 200; img.height = 200;
    panel.appendChild(img);
  }
  const meta = document.createElement("div"); meta.className = "meta";
  const title = document.createElement("b"); title.textContent = s.f; meta.appendChild(title);
  const lines = [
    info ? `Coups : ${info.moves}` : "",
    info ? `Ouverture choisie par les ${info.chosen_by} (dernier coup de la position)` : "",
    `${fmtInt(s.n)} parties dans la sélection · ${fmtPct(s.share)} des parties`,
    `Score du camp choisi : ${fmtPct(s.p / s.n)} (${fmtPts((s.p - s.e) / s.n)} vs classement)`,
  ];
  lines.filter(Boolean).forEach((l) => { const p = document.createElement("p"); p.textContent = l; p.style.margin = "6px 0"; meta.appendChild(p); });
  panel.appendChild(meta);
}

// ---------------------------------------------------------------------------------------
// Page 3 — Elo & clock
// ---------------------------------------------------------------------------------------
function renderElo() {
  const { bands } = state.data.meta;
  const cal = groupSum(table("calibration").filter((r) => inFilter(r)), (r) => r.g, ["n", "p", "e"]);
  const gaps = [...cal.keys()].sort((a, b) => a - b).filter((g) => enough(cal.get(g).n));
  const curve = Array.from({ length: 121 }, (_, i) => -600 + i * 10);
  draw("calibration", gaps.length ? [
    { type: "scatter", mode: "lines", name: "Formule Elo (attendu)", x: curve, y: curve.map((g) => 1 / (1 + 10 ** (-g / 400))), line: { color: css("--muted"), dash: "dash", width: 2 }, hovertemplate: "écart %{x}<br>attendu %{y:.1%}<extra></extra>" },
    { type: "scatter", mode: "lines+markers", name: "Score réel des Blancs", x: gaps, y: gaps.map((g) => cal.get(g).p / cal.get(g).n), line: { color: css("--s1"), width: 2 }, marker: { size: 8, line: { color: css("--surface"), width: 2 } }, hovertemplate: "écart %{x}<br>réel %{y:.1%}<extra></extra>" },
  ] : [], { xaxis: { ...baseLayout().xaxis, title: "Écart Elo (Blancs − Noirs)", dtick: 100 }, yaxis: { ...baseLayout().yaxis, tickformat: ".0%", range: [0, 1] } }, {
    head: ["Écart", "Parties", "Score réel", "Score attendu", "Écart réel − attendu"],
    body: gaps.map((g) => { const v = cal.get(g); return { cells: [String(g), fmtInt(v.n), fmtPct(v.p / v.n), fmtPct(v.e / v.n), fmtPts((v.p - v.e) / v.n)] }; }),
  });

  const clk = groupSum(table("clock").filter((r) => inFilter(r)), (r) => r.k, ["n", "p", "lot"]);
  const bins = [...clk.keys()].sort((a, b) => a - b).filter((k) => enough(clk.get(k).n));
  const clockTrace = (field, color, label) => bins.length ? [{
    type: "scatter", mode: "lines+markers", x: bins.map((k) => k + 2.5), y: bins.map((k) => clk.get(k)[field] / clk.get(k).n),
    line: { color: css(color), width: 2 }, marker: { size: 8, line: { color: css("--surface"), width: 2 } },
    hovertemplate: `%{x:.0f} % du temps utilisé<br>${label} %{y:.1%}<extra></extra>`,
  }] : [];
  const clockAxes = { xaxis: { ...baseLayout().xaxis, title: "Part du temps de base utilisée (%)", ticksuffix: " %" }, yaxis: { ...baseLayout().yaxis, tickformat: ".0%" }, showlegend: false };
  const clockTable = { head: ["Temps utilisé", "Parties-joueur", "Score", "Perdues au temps"], body: bins.map((k) => { const v = clk.get(k); return { cells: [`${k}–${k + 5} %`, fmtInt(v.n), fmtPct(v.p / v.n), fmtPct(v.lot / v.n)] }; }) };
  draw("clock-score", clockTrace("p", "--s1", "score"), clockAxes, clockTable);
  draw("clock-flag", clockTrace("lot", "--s2", "perdues au temps"), clockAxes, clockTable);

  const byBand = groupSum(table("results").filter((r) => inFilter(r, { band: false })), (r) => r.b, ["n", "lot"]);
  const bIdx = [...byBand.keys()].sort().filter((b) => enough(byBand.get(b).n));
  draw("flag-band", bIdx.length ? [{
    type: "bar", x: bIdx.map((b) => bands[b - 1]), y: bIdx.map((b) => byBand.get(b).lot / byBand.get(b).n),
    marker: { color: bIdx.map((b) => css(`--b${b}`)), line: { color: css("--surface"), width: 2 } },
    text: bIdx.map((b) => fmtPct(byBand.get(b).lot / byBand.get(b).n)), textposition: "outside", textfont: { color: css("--ink-2") },
    hovertemplate: "%{x} : %{y:.1%} perdues au temps<extra></extra>",
  }] : [], { yaxis: { ...baseLayout().yaxis, tickformat: ".0%", range: [0, Math.max(0.01, ...bIdx.map((b) => byBand.get(b).lot / byBand.get(b).n)) * 1.15] } }, {
    head: ["Tranche", "Parties", "Perdues au temps"], body: bIdx.map((b) => ({ cells: [bands[b - 1], fmtInt(byBand.get(b).n), fmtPct(byBand.get(b).lot / byBand.get(b).n)] })),
  });
}

// ---------------------------------------------------------------------------------------
// Page 4 — activity
// ---------------------------------------------------------------------------------------
function renderActivity() {
  const { weekdays, days_per_weekday: days } = state.data.meta;
  const act = table("activity").filter((r) => inFilter(r));
  const cells = groupSum(act, (r) => `${r.w}-${r.h}`, ["n"]);
  const z = weekdays.map((_, w) => Array.from({ length: 24 }, (_, h) => (cells.get(`${w + 1}-${h}`)?.n || 0) / days[w]));
  draw("heatmap", [{
    type: "heatmap", z, x: [...Array(24).keys()], y: weekdays, xgap: 2, ygap: 2,
    colorscale: [[0, css("--seq-0")], [0.35, css("--seq-1")], [0.7, css("--seq-2")], [1, css("--seq-3")]],
    colorbar: { outlinewidth: 0, tickfont: { color: css("--ink-2") } },
    hovertemplate: "%{y} %{x}h<br>%{z:,.0f} parties par jour<extra></extra>",
  }], { xaxis: { ...baseLayout().xaxis, title: "Heure (UTC)", dtick: 1 }, yaxis: { ...baseLayout().yaxis, autorange: "reversed" }, margin: { l: 50, r: 16, t: 10, b: 48 } }, {
    head: ["Jour", ...Array.from({ length: 24 }, (_, h) => `${h}h`)],
    body: weekdays.map((d, w) => ({ cells: [d, ...z[w].map((v) => fmtInt(v))] })),
  });

  const byHour = groupSum(act, (r) => r.h, ["n", "p", "lot"]);
  const hours = [...byHour.keys()].sort((a, b) => a - b).filter((h) => enough(byHour.get(h).n));
  const hourTrace = (field, color, label) => hours.length ? [{
    type: "scatter", mode: "lines+markers", x: hours, y: hours.map((h) => byHour.get(h)[field] / byHour.get(h).n),
    line: { color: css(color), width: 2 }, marker: { size: 8, line: { color: css("--surface"), width: 2 } },
    hovertemplate: `%{x}h : ${label} %{y:.1%}<extra></extra>`,
  }] : [];
  const hourTable = { head: ["Heure", "Parties", "Perdues au temps", "Score des Blancs"], body: hours.map((h) => { const v = byHour.get(h); return { cells: [`${h}h`, fmtInt(v.n), fmtPct(v.lot / v.n), fmtPct(v.p / v.n)] }; }) };
  const xh = { ...baseLayout().xaxis, title: "Heure (UTC)", dtick: 2, range: [-0.5, 23.5] };
  draw("flag-hour", hourTrace("lot", "--s2", "perdues au temps"), { xaxis: xh, yaxis: { ...baseLayout().yaxis, tickformat: ".0%" }, showlegend: false }, hourTable);
  draw("score-hour", hourTrace("p", "--white-pole", "score des Blancs"), { xaxis: xh, yaxis: { ...baseLayout().yaxis, tickformat: ".0%", range: [0.45, 0.55] }, showlegend: false }, hourTable);
}

// ---------------------------------------------------------------------------------------
// Static key findings (from reports/findings.md) and wiring
// ---------------------------------------------------------------------------------------
const FINDINGS = [
  ["×1,44", "chances de victoire pour +100 points d'écart Elo — mais le favori marque 67,9 % au lieu de 75,7 % à +200 en blitz"],
  ["43,6 % vs 52,3 %", "score en blitz des joueurs les plus lents vs les plus rapides sur leurs 10 premiers coups"],
  ["51,6 %", "score des Blancs : +1,6 point au-delà de ce que prédit le classement"],
  ["V ≤ 0,03", "lien ouverture × résultat : significatif, mais effet négligeable"],
];

function render() {
  ({ overview: renderOverview, openings: renderOpenings, elo: renderElo, activity: renderActivity })[state.page]();
}

function setPage(page) {
  state.page = page;
  PAGES.forEach((p) => {
    document.getElementById(`p-${p}`).hidden = p !== page;
    document.getElementById(`t-${p}`).setAttribute("aria-selected", String(p === page));
  });
  document.getElementById("side-filter").hidden = page !== "openings";
  try { localStorage.setItem("64sq-page", page); } catch (_) { /* storage unavailable */ }
  render();
  window.dispatchEvent(new Event("resize"));
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", mode);
  document.getElementById("theme-toggle").textContent = `Thème : ${{ auto: "auto", light: "clair", dark: "sombre" }[mode]}`;
  try { localStorage.setItem("64sq-theme", mode); } catch (_) { /* storage unavailable */ }
}

async function init() {
  const res = await fetch("data/dashboard.json");
  state.data = await res.json();
  const { meta } = state.data;
  document.getElementById("subtitle").textContent = `${fmtInt(meta.games)} parties classées Lichess (septembre 2026, échantillon aléatoire nettoyé)`;
  const tcSel = document.getElementById("f-tc"), bandSel = document.getElementById("f-band");
  meta.time_controls.forEach((t, i) => tcSel.add(new Option(t, String(i + 1))));
  meta.bands.forEach((b, i) => bandSel.add(new Option(`Elo ${b}`, String(i + 1))));
  const box = document.getElementById("findings");
  FINDINGS.forEach(([big, txt]) => { const d = document.createElement("div"); d.className = "finding"; const b = document.createElement("b"); b.textContent = big; d.appendChild(b); d.appendChild(document.createTextNode(txt)); box.appendChild(d); });

  tcSel.addEventListener("change", (e) => { state.tc = +e.target.value; render(); });
  bandSel.addEventListener("change", (e) => { state.band = +e.target.value; render(); });
  document.getElementById("f-side").addEventListener("change", (e) => { state.side = e.target.value; state.family = null; render(); });
  document.getElementById("f-min").addEventListener("change", (e) => { state.min = +e.target.value; render(); });
  PAGES.forEach((p) => document.getElementById(`t-${p}`).addEventListener("click", () => setPage(p)));
  document.querySelectorAll(".toggle").forEach((btn) => btn.addEventListener("click", () => {
    const c = btn.closest(".card"), wrap = c.querySelector(".table-wrap"), chart = c.querySelector(".chart");
    const showTable = wrap.hidden; wrap.hidden = !showTable; chart.hidden = showTable; btn.textContent = showTable ? "Graphique" : "Tableau";
    if (!showTable) window.dispatchEvent(new Event("resize"));
  }));
  const modes = ["auto", "light", "dark"];
  let theme = "auto";
  try { theme = localStorage.getItem("64sq-theme") || "auto"; } catch (_) { /* storage unavailable */ }
  applyTheme(theme);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    theme = modes[(modes.indexOf(theme) + 1) % modes.length]; applyTheme(theme); render();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => render());
  let page = "overview";
  try { page = localStorage.getItem("64sq-page") || "overview"; } catch (_) { /* storage unavailable */ }
  setPage(PAGES.includes(page) ? page : "overview");
}

document.addEventListener("DOMContentLoaded", () => init().catch((err) => {
  const main = document.querySelector("main");
  const p = document.createElement("p"); p.className = "empty";
  p.textContent = `Impossible de charger les données (${err.message}). Ouvrez la page via un serveur web (python -m http.server).`;
  main.prepend(p);
}));

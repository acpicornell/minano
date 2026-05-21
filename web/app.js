// Miñano Balears — static web, vanilla JS.
// One fetch of data.json, then everything happens in memory.

const state = {
  entries: [],
  filtered: [],
  search: "",
  island: "",
  regime: "",
  mayor: "",
  municipality: "",
  type: "",
  vol: "",
  conf: "",
  sort_col: "title",
  sort_dir: "asc",
};

const COLS = ["title", "place_type", "island", "seigneurial_regime",
              "mayor_type", "municipality", "vol", "page_printed", "confidence"];

function esc(s) {
  if (s == null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function $(id) { return document.getElementById(id); }
function fmt(n) { return Number(n).toLocaleString("ca-ES"); }
function norm(s) {
  if (!s) return "";
  return s.toString().toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "");
}

// === TABS ===
function gotoTab(t) {
  document.querySelectorAll(".tabs .tab").forEach(b =>
    b.classList.toggle("active", b.dataset.toptab === t));
  document.querySelectorAll(".tab-content").forEach(sec =>
    sec.classList.toggle("active", sec.dataset.toptab === t));
  if (t === "stats") renderStats();
  if (t === "map") renderMap();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function initTabs() {
  document.querySelectorAll(".tabs .tab").forEach(btn => {
    btn.addEventListener("click", () => gotoTab(btn.dataset.toptab));
  });
  document.querySelectorAll("[data-goto]").forEach(el => {
    el.addEventListener("click", ev => {
      ev.preventDefault();
      gotoTab(el.dataset.goto);
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

// === FILTERS ===
const FILTER_DEFS = [
  { id: "f-island",       stateKey: "island",       field: "island",             allLabel: "— Totes —" },
  { id: "f-regime",       stateKey: "regime",       field: "seigneurial_regime", allLabel: "— Tots —" },
  { id: "f-mayor",        stateKey: "mayor",        field: "mayor_type",         allLabel: "— Tots —" },
  { id: "f-municipality", stateKey: "municipality", field: "municipality",       allLabel: "— Tots —" },
  { id: "f-type",         stateKey: "type",         field: "place_type",         allLabel: "— Tots —" },
  { id: "f-vol",          stateKey: "vol",          field: "vol",                allLabel: "— Tots —" },
  { id: "f-conf",         stateKey: "conf",         field: "confidence",         allLabel: "— Totes —" },
];

function matchesExcept(e, exceptKey) {
  for (const f of FILTER_DEFS) {
    if (f.stateKey === exceptKey) continue;
    const v = state[f.stateKey];
    if (v && e[f.field] !== v) return false;
  }
  if (state.search) {
    const hay = norm((e.title || "") + " " + (e.description || ""));
    if (!hay.includes(norm(state.search))) return false;
  }
  return true;
}

function refillFilters() {
  for (const f of FILTER_DEFS) {
    const counts = new Map();
    for (const e of state.entries) {
      if (!matchesExcept(e, f.stateKey)) continue;
      const v = e[f.field];
      if (v == null || v === "") continue;
      counts.set(v, (counts.get(v) || 0) + 1);
    }
    const arr = [...counts.entries()];
    if (f.id === "f-vol" || f.id === "f-municipality") {
      arr.sort((a, b) => a[0].localeCompare(b[0], "ca", { numeric: true }));
    } else if (f.id === "f-conf") {
      const order = { high: 0, medium: 1, low: 2 };
      arr.sort((a, b) => (order[a[0]] ?? 9) - (order[b[0]] ?? 9));
    } else {
      arr.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    }
    const cur = state[f.stateKey];
    if (cur && !counts.has(cur)) state[f.stateKey] = "";

    const labelMap = f.id === "f-conf"
      ? { high: "Alta", medium: "Mitjana", low: "Baixa" }
      : null;
    const opts = arr.map(([v, n]) => {
      const label = labelMap ? (labelMap[v] || v) : v;
      return `<option value="${esc(v)}">${esc(label)} (${n})</option>`;
    }).join("");
    const sel = $(f.id);
    sel.innerHTML = `<option value="">${f.allLabel}</option>` + opts;
    sel.value = state[f.stateKey] || "";
  }
}

function applyFilters() {
  state.filtered = state.entries.filter(e => matchesExcept(e, null));
  sortFiltered();
}

function sortFiltered() {
  const k = state.sort_col;
  const dir = state.sort_dir === "desc" ? -1 : 1;
  state.filtered.sort((a, b) => {
    let av = a[k], bv = b[k];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
    return String(av).localeCompare(String(bv), "ca", { numeric: true }) * dir;
  });
}

// === TABLE ===
function renderTable() {
  applyFilters();
  const tbody = $("tbody-minano");
  const total = state.filtered.length;
  $("count").textContent = `${fmt(total)} entrades`;
  if (!total) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">No s'han trobat entrades que satisfacin els filtres seleccionats.</td></tr>`;
    return;
  }
  const slice = state.filtered.slice(0, 500);
  const dot = c => c === "high" ? "●" : c === "medium" ? "◐" : c === "low" ? "○" : "—";
  // Compact regime/mayor for the table column (full label appears in the
  // expanded row).
  const regimeShort = r => ({
    "Realengo": "R.", "Señorial": "S.", "Abadengo": "Ab.",
    "de Órdenes": "Ord.", "Eclesiástico": "Ecl.",
    "Mixto": "Mix.", "Otro": "?",
  }[r] || "—");
  const mayorShort = m => ({
    "Alcalde Ordinario": "A.O.", "Alcalde Pedáneo": "A.P.",
    "Alcalde Mayor": "A.M.", "Sin alcalde": "—",
    "Otro": "?",
  }[m] || "—");
  tbody.innerHTML = slice.map(e => {
    const volLeaf = e.ia_url
      ? `<a href="${esc(e.ia_url)}" target="_blank" rel="noopener" class="ia-link" title="Obre el facsímil a Internet Archive (pàgina sencera)">${esc(e.vol)}/${esc(e.leaf)} ↗</a>`
      : `${esc(e.vol)}/${esc(e.leaf)}`;
    return `<tr data-id="${e.id}" class="minano-row">
      <td><strong>${esc(e.title)}</strong></td>
      <td>${esc(e.place_type || "—")}</td>
      <td>${esc(e.island || "—")}</td>
      <td title="${esc(e.seigneurial_regime || '')}">${esc(regimeShort(e.seigneurial_regime))}</td>
      <td title="${esc(e.mayor_type || '')}">${esc(mayorShort(e.mayor_type))}</td>
      <td>${esc(e.municipality || "—")}</td>
      <td>${volLeaf}</td>
      <td>${esc(e.page_printed || "—")}</td>
      <td class="conf-${esc(e.confidence || "")}">${dot(e.confidence)}</td>
    </tr>`;
  }).join("") + (total > 500
    ? `<tr><td colspan="9" class="empty">Es visualitzen 500 de ${fmt(total)} entrades. Refineu els filtres per restringir el resultat.</td></tr>`
    : "");
  tbody.querySelectorAll("tr.minano-row").forEach(tr =>
    tr.addEventListener("click", ev => {
      if (ev.target.closest("a")) return;
      toggleExpand(tr);
    }));
}

function toggleExpand(tr) {
  const next = tr.nextElementSibling;
  if (next && next.classList.contains("minano-expand")) {
    next.remove(); tr.classList.remove("expanded"); return;
  }
  document.querySelectorAll(".minano-expand").forEach(el => el.remove());
  document.querySelectorAll(".minano-row.expanded").forEach(el => el.classList.remove("expanded"));
  const id = Number(tr.dataset.id);
  const e = state.entries.find(x => x.id === id);
  if (!e) return;

  let statsHtml = "";
  if (e.stats && typeof e.stats === "object") {
    const items = Object.entries(e.stats).filter(([_, v]) => v != null && v !== "");
    if (items.length) {
      statsHtml = `<div class="entry-stats"><strong>Estadístiques:</strong> ` +
        items.map(([k, v]) =>
          `<span class="stat-pill">${esc(k)}: <strong>${esc(typeof v === "number" ? fmt(v) : v)}</strong></span>`
        ).join(" ") + `</div>`;
    }
  }
  let crefsHtml = "";
  if (e.cross_references && e.cross_references.length) {
    crefsHtml = `<div class="entry-crefs"><strong>Referències creuades:</strong> ` +
      e.cross_references.map(c => `<code>${esc(c)}</code>`).join(", ") + `</div>`;
  }
  const adminBits = [];
  if (e.seigneurial_regime) adminBits.push(`Règim: <strong>${esc(e.seigneurial_regime)}</strong>`);
  if (e.mayor_type) adminBits.push(`Alcalde: <strong>${esc(e.mayor_type)}</strong>`);
  const adminHtml = adminBits.length
    ? `<div class="entry-admin">${adminBits.join(" · ")}</div>` : "";

  const exp = document.createElement("tr");
  exp.className = "minano-expand";
  exp.innerHTML = `<td colspan="9">
    <div class="minano-article">
      ${adminHtml}
      <p class="minano-body">${esc(e.description || "")}</p>
      ${statsHtml}
      ${crefsHtml}
      <p class="minano-source">
        <span>Tom ${esc(e.vol)} · full ${esc(e.leaf)} · pàg. ${esc(e.page_printed || "?")}</span>
        ${e.ia_url ? `· <a href="${esc(e.ia_url)}" target="_blank" rel="noopener">Veure facsímil a Internet Archive →</a>` : ""}
      </p>
    </div>
  </td>`;
  tr.classList.add("expanded");
  tr.insertAdjacentElement("afterend", exp);
}

function initSort() {
  document.querySelectorAll("#table-minano th").forEach((th, i) => {
    const col = COLS[i];
    if (!col) return;
    th.classList.add("sortable");
    th.addEventListener("click", () => {
      if (state.sort_col === col) state.sort_dir = state.sort_dir === "asc" ? "desc" : "asc";
      else { state.sort_col = col; state.sort_dir = "asc"; }
      document.querySelectorAll("#table-minano th").forEach(x => x.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(`sort-${state.sort_dir}`);
      renderTable();
    });
  });
}

function update() { refillFilters(); renderTable(); }

function bindFilters() {
  let t;
  $("f-search").addEventListener("input", e => {
    clearTimeout(t);
    t = setTimeout(() => { state.search = e.target.value.trim(); update(); }, 180);
  });
  const sel = (id, key) => $(id).addEventListener("change", e => { state[key] = e.target.value; update(); });
  sel("f-island", "island"); sel("f-regime", "regime"); sel("f-mayor", "mayor");
  sel("f-municipality", "municipality"); sel("f-type", "type");
  sel("f-vol", "vol"); sel("f-conf", "conf");
  $("f-clear").addEventListener("click", () => {
    Object.assign(state, {
      search: "", island: "", regime: "", mayor: "",
      municipality: "", type: "", vol: "", conf: "",
    });
    $("f-search").value = "";
    update();
  });
  $("f-export").addEventListener("click", exportCSV);
}

function exportCSV() {
  const fields = ["vol", "leaf", "page_printed", "title", "place_type", "island",
                  "seigneurial_regime", "mayor_type", "municipality",
                  "confidence", "description"];
  const cell = v => {
    if (v == null) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [fields.join(",")];
  for (const e of state.filtered) lines.push(fields.map(f => cell(e[f])).join(","));
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `minano_balears_${state.filtered.length}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// === HOME / INICI ===
function renderHome() {
  const total = state.entries.length;
  $("home-stat-entries").textContent = fmt(total);
  // Distinct tomos with entries.
  const vols = new Set(state.entries.map(e => e.vol).filter(Boolean));
  $("home-stat-tomos-done").textContent = vols.size;
  // Top place type.
  const typeCounts = new Map();
  for (const e of state.entries) {
    if (!e.place_type) continue;
    typeCounts.set(e.place_type, (typeCounts.get(e.place_type) || 0) + 1);
  }
  const topType = [...typeCounts.entries()].sort((a, b) => b[1] - a[1])[0];
  if (topType) {
    $("home-stat-toptype").textContent = fmt(topType[1]);
    $("home-stat-toptype-label").textContent = `${topType[0]} (tipus més freqüent)`;
  }

  // Per-island cards.
  const islandCounts = new Map();
  for (const e of state.entries) {
    if (!e.island) continue;
    islandCounts.set(e.island, (islandCounts.get(e.island) || 0) + 1);
  }
  const setIsland = (id, key) => {
    const el = $(id);
    if (el) el.textContent = fmt(islandCounts.get(key) || 0);
  };
  setIsland("home-src-mallorca", "Mallorca");
  setIsland("home-src-menorca", "Menorca");
  setIsland("home-src-ibiza", "Ibiza");
  setIsland("home-src-formentera", "Formentera");
  setIsland("home-src-cabrera", "Cabrera");

  // Featured entry — pick a random high-confidence one for the splash.
  const highs = state.entries.filter(e => e.confidence === "high" && e.description);
  const featured = highs.length
    ? highs[Math.floor(Math.random() * highs.length)]
    : state.entries.find(e => e.description);
  if (featured) {
    const card = $("home-featured");
    if (card) card.hidden = false;
    $("featured-title").textContent = featured.title;
    const meta = [
      featured.place_type, featured.island,
      featured.seigneurial_regime,
      featured.municipality && `Contr. ${featured.municipality}`,
      `Tom ${featured.vol} · pàg. ${featured.page_printed || "?"}`,
    ].filter(Boolean).join(" · ");
    $("featured-meta").textContent = meta;
    const excerpt = featured.description.length > 320
      ? featured.description.slice(0, 320).trimEnd() + "…"
      : featured.description;
    $("featured-excerpt").textContent = excerpt;
    $("featured-open").addEventListener("click", () => {
      gotoTab("explore");
      requestAnimationFrame(() => {
        const tr = document.querySelector(`tr[data-id="${featured.id}"]`);
        if (tr) {
          tr.scrollIntoView({ behavior: "smooth", block: "center" });
          toggleExpand(tr);
        }
      });
    });
  }
}

// === EXPLORE STATS BAR ===
function renderStatsBar() {
  $("stat-text").textContent = fmt(state.entries.length);
  $("stat-volumes").textContent = new Set(
    state.entries.map(e => e.vol).filter(Boolean)
  ).size;
  $("stat-islands").textContent = new Set(
    state.entries.map(e => e.island).filter(Boolean)
  ).size;
  $("stat-types").textContent = new Set(
    state.entries.map(e => e.place_type).filter(Boolean)
  ).size;
}

// === BOOTSTRAP ===
async function boot() {
  initTabs();
  initSort();
  bindFilters();
  let payload;
  try {
    const r = await fetch("data.json");
    payload = await r.json();
  } catch (e) {
    console.error(e);
    $("tbody-minano").innerHTML =
      `<tr><td colspan="9" class="empty">Error en la càrrega de data.json.</td></tr>`;
    return;
  }
  state.entries = payload.entries || [];
  renderHome();
  renderStatsBar();
  update();
}

// ===========================================================================
// === ESTADÍSTIQUES TAB =====================================================
// ===========================================================================

let statsRendered = false;

function fmtCompact(n) {
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

// Inline horizontal-bar chart. `rows` is [[label, value, sub?], ...]
// sorted descending. `fmtVal` formats the numeric value for display.
function svgBars(rows, opts = {}) {
  // Drop rows whose value isn't a finite number — one stray "11,???" would
  // otherwise NaN-poison Math.max and collapse every bar to width 0.
  rows = rows.filter(r => typeof r[1] === "number" && isFinite(r[1]));
  if (!rows.length) return '<p class="empty">Sense dades.</p>';
  const fmtVal = opts.fmt || fmt;
  const colour = opts.colour || "var(--accent)";
  const labelW = opts.labelW ?? 160;
  const barH = opts.barH ?? 18;
  const gap = opts.gap ?? 6;
  const valueW = opts.valueW ?? 110;
  const width = 720;
  const innerW = width - labelW - valueW - 20;
  const max = Math.max(...rows.map(r => r[1])) || 1;
  const height = rows.length * (barH + gap);
  const lines = rows.map((r, i) => {
    const [label, val, sub] = r;
    const w = max > 0 ? Math.max(1, (val / max) * innerW) : 0;
    const y = i * (barH + gap);
    return (
      `<g transform="translate(0,${y})">` +
      `<text x="${labelW - 6}" y="${barH * 0.72}" text-anchor="end" class="bar-label">${esc(label)}</text>` +
      `<rect x="${labelW}" y="0" width="${w}" height="${barH}" rx="2" fill="${colour}"/>` +
      `<text x="${labelW + w + 6}" y="${barH * 0.72}" class="bar-value">${esc(fmtVal(val))}${sub ? ` <tspan class="bar-sub">${esc(sub)}</tspan>` : ""}</text>` +
      `</g>`
    );
  }).join("");
  return `<svg viewBox="0 0 ${width} ${height}" class="bars-svg" preserveAspectRatio="xMinYMin meet" role="img">${lines}</svg>`;
}

function statsOf(e) {
  return (e.stats && typeof e.stats === "object") ? e.stats : null;
}

// Exclude island aggregates ("MALLORCA", "MENORCA", "BALEARES", "FORMENTERA")
// from per-entry charts because their habitantes/vecinos figures are the
// sum of all the entries in our table — they'd dwarf everything.
function isIslandAggregate(e) {
  return e.place_type === "isla" || e.place_type === "islas";
}

function isPlaceEntry(e) {
  return !isIslandAggregate(e);
}

function renderStats() {
  if (statsRendered) return;
  statsRendered = true;

  const total = state.entries.length;
  // Strict numeric filter — OCR garbled some stats as strings (e.g.
  // "11,???") which would poison Math.max and break the bar layout.
  const numOf = (e, k) => {
    const v = statsOf(e)?.[k];
    return typeof v === "number" && isFinite(v) ? v : null;
  };
  const withHab = state.entries.filter(e => isPlaceEntry(e) && numOf(e, "habitantes") != null);
  const withVec = state.entries.filter(e => isPlaceEntry(e) && numOf(e, "vecinos") != null);
  const withRiq = state.entries.filter(e => isPlaceEntry(e) && numOf(e, "riqueza_liquida_libras") != null);
  $("stats-coverage").innerHTML =
    `<strong>Cobertura de dades:</strong> de ${total} entrades, ` +
    `${withHab.length} tenen <em>habitantes</em>, ${withVec.length} <em>vecinos</em>, ` +
    `${withRiq.length} <em>riqueza líquida</em>. ` +
    `Les entrades sense xifres pròpies (suplements del Tom XI, aldees agregades a la matriu, etc.) queden fora dels gràfics.`;

  // === Top 20 by habitants ===
  const byHab = withHab
    .map(e => [
      e.title,
      statsOf(e).habitantes,
      statsOf(e).vecinos ? `${fmt(statsOf(e).vecinos)} vec.` : null,
    ])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20);
  $("stats-chart-hab").innerHTML = svgBars(byHab, { labelW: 200 });

  // === Top 20 by vecinos ===
  const byVec = withVec
    .map(e => [e.title, statsOf(e).vecinos, statsOf(e).habitantes ? `${fmt(statsOf(e).habitantes)} hab.` : null])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20);
  $("stats-chart-vec").innerHTML = svgBars(byVec, { labelW: 200, colour: "#0f766e" });

  // === Top 15 by riqueza líquida (libras) ===
  const byRiq = withRiq
    .map(e => [e.title, statsOf(e).riqueza_liquida_libras, "lib."])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15);
  $("stats-chart-riq").innerHTML = svgBars(byRiq, {
    labelW: 200,
    colour: "#c2410c",
    fmt: v => fmtCompact(v),
  });

  // === Population aggregated per island ===
  // For per-island totals, we INCLUDE the island-aggregate entries
  // (the "MALLORCA isla" entry from Tomo V has 191,805 hab — that's
  // the canonical figure for the whole island c. 1826).
  const islandTotals = new Map();
  for (const e of state.entries) {
    const s = statsOf(e);
    if (!s || s.habitantes == null) continue;
    if (!isIslandAggregate(e)) continue;
    const key = e.title || e.island || "(altres)";
    islandTotals.set(key, (islandTotals.get(key) || 0) + s.habitantes);
  }
  const byIsla = [...islandTotals.entries()]
    .map(([k, v]) => [k, v, "hab."])
    .sort((a, b) => b[1] - a[1]);
  $("stats-chart-illa").innerHTML = svgBars(byIsla, {
    labelW: 140,
    colour: "#0f766e",
  });

  // === Seigneurial regime distribution ===
  const regCounts = new Map();
  for (const e of state.entries) {
    if (!e.seigneurial_regime) continue;
    regCounts.set(e.seigneurial_regime, (regCounts.get(e.seigneurial_regime) || 0) + 1);
  }
  const byReg = [...regCounts.entries()]
    .map(([k, v]) => [k, v, "entr."])
    .sort((a, b) => b[1] - a[1]);
  $("stats-chart-reg").innerHTML = svgBars(byReg, {
    labelW: 160,
    colour: "#7c3aed",
  });

  // === Household size (habitants / vecinos) ===
  const ratioRows = state.entries
    .filter(e => isPlaceEntry(e) && statsOf(e)?.habitantes && statsOf(e)?.vecinos && statsOf(e).vecinos > 0)
    .map(e => {
      const s = statsOf(e);
      return [e.title, +(s.habitantes / s.vecinos).toFixed(2), `${fmt(s.vecinos)} → ${fmt(s.habitantes)}`];
    })
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20);
  $("stats-chart-ratio").innerHTML = svgBars(ratioRows, {
    labelW: 200,
    colour: "#0891b2",
    fmt: v => v.toFixed(2),
  });

  // === Place type distribution ===
  const typeCounts = new Map();
  for (const e of state.entries) {
    if (!e.place_type) continue;
    typeCounts.set(e.place_type, (typeCounts.get(e.place_type) || 0) + 1);
  }
  const byType = [...typeCounts.entries()]
    .map(([k, v]) => [k, v, "entr."])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12);
  $("stats-chart-types").innerHTML = svgBars(byType, {
    labelW: 130,
    colour: "#65a30d",
  });

  // === Coverage per tomo ===
  const volCounts = new Map();
  for (const e of state.entries) {
    if (!e.vol) continue;
    volCounts.set(e.vol, (volCounts.get(e.vol) || 0) + 1);
  }
  const VOL_ROMAN = {
    "01": "I", "02": "II", "03": "III", "04": "IV", "05": "V", "06": "VI",
    "07": "VII", "08": "VIII", "09": "IX", "10": "X", "11": "XI",
  };
  const VOL_RANGE = {
    "01": "A — AZ",
    "02": "BAB — CAS",
    "03": "CAS — ESPADILLO",
    "04": "ESP — HIT",
    "05": "HIT — MEMBRIVE",
    "06": "MEM — PALMA",
    "07": "PALMA — SAN",
    "08": "SAN — TEMPLE",
    "09": "TOR — VIL",
    "10": "VIL — VIZ",
    "11": "Suplement",
  };
  const byVol = [...volCounts.entries()]
    .map(([k, v]) => [`Tom ${VOL_ROMAN[k] || k}`, v, VOL_RANGE[k] || ""])
    .sort((a, b) => {
      const ai = Object.values(VOL_ROMAN).indexOf(a[0].replace("Tom ", ""));
      const bi = Object.values(VOL_ROMAN).indexOf(b[0].replace("Tom ", ""));
      return ai - bi;
    });
  $("stats-chart-vol").innerHTML = svgBars(byVol, {
    labelW: 110,
    colour: "#0891b2",
  });

  // === Ecclesiastical infrastructure aggregated ===
  const ECCL_KEYS = [
    ["parroquias",         "Parròquies"],
    ["conventos",          "Convents"],
    ["conventos_frailes",  "Convents de frares"],
    ["conventos_monjas",   "Convents de monges"],
    ["ermitas",            "Ermites"],
    ["hospitales",         "Hospitals"],
    ["molinos_viento",     "Molins de vent"],
    ["cartujas",           "Cartoixes"],
    ["santuarios",         "Santuaris"],
    ["fabricas_jabon",     "Fàbriques de sabó"],
  ];
  const ecclTotals = ECCL_KEYS.map(([key, label]) => {
    let sum = 0, n = 0;
    for (const e of state.entries) {
      const s = statsOf(e);
      if (s && typeof s[key] === "number") { sum += s[key]; n++; }
    }
    return [label, sum, n > 0 ? `en ${n} entrades` : ""];
  }).filter(r => r[1] > 0)
    .sort((a, b) => b[1] - a[1]);
  $("stats-chart-eccl").innerHTML = svgBars(ecclTotals, {
    labelW: 200,
    colour: "#92400e",
  });

  // === Sunburst (island → regime → place_type) =========================
  $("stats-chart-sunburst").innerHTML = renderSunburst(state.entries);
  wireSunburstHover();
}

const SUNB_NO_REG = "(sense règim)";
const SUNB_NO_TYP = "(sense tipus)";

// ===========================================================================
// === SUNBURST (island → regime → place_type) ==============================
// ===========================================================================

const ISLAND_HUE = {
  "Mallorca":   "#0070b8",
  "Menorca":    "#0f766e",
  "Ibiza":      "#c2410c",
  "Eivissa":    "#c2410c",
  "Formentera": "#a04545",
  "Cabrera":    "#7c3aed",
  "Baleares":   "#475569",
};

const REGIME_TINT = {
  "Realengo":     0.95,
  "Señorial":     0.75,
  "Eclesiástico": 0.55,
  "Otro":         0.40,
};

function lighten(hex, t) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const f = c => Math.round(c + (255 - c) * (1 - t));
  return `rgb(${f(r)},${f(g)},${f(b)})`;
}

function arcPath(cx, cy, rInner, rOuter, a0, a1) {
  const x0 = cx + rInner * Math.cos(a0), y0 = cy + rInner * Math.sin(a0);
  const x1 = cx + rOuter * Math.cos(a0), y1 = cy + rOuter * Math.sin(a0);
  const x2 = cx + rOuter * Math.cos(a1), y2 = cy + rOuter * Math.sin(a1);
  const x3 = cx + rInner * Math.cos(a1), y3 = cy + rInner * Math.sin(a1);
  const large = (a1 - a0) > Math.PI ? 1 : 0;
  return `M${x0},${y0} L${x1},${y1} A${rOuter},${rOuter} 0 ${large} 1 ${x2},${y2} ` +
         `L${x3},${y3} A${rInner},${rInner} 0 ${large} 0 ${x0},${y0} Z`;
}

function renderSunburst(entries) {
  const hier = new Map();
  for (const e of entries) {
    const isl = e.island || "(altres)";
    const reg = e.seigneurial_regime || SUNB_NO_REG;
    const typ = e.place_type || SUNB_NO_TYP;
    if (!hier.has(isl)) hier.set(isl, new Map());
    const rm = hier.get(isl);
    if (!rm.has(reg)) rm.set(reg, new Map());
    const tm = rm.get(reg);
    tm.set(typ, (tm.get(typ) || 0) + 1);
  }
  const islandTotals = [...hier.entries()].map(([k, v]) => {
    let n = 0; for (const rm of v.values()) for (const tn of rm.values()) n += tn;
    return [k, v, n];
  }).sort((a, b) => b[2] - a[2]);
  const grandTotal = islandTotals.reduce((s, [, , n]) => s + n, 0);
  if (grandTotal === 0) return '<p class="empty">Sense dades.</p>';

  const W = 720, H = 540;
  const cx = W / 2, cy = H / 2;
  const r1 = 60, r2 = 130, r3 = 220;
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="sunburst-svg" preserveAspectRatio="xMidYMid meet" role="img">`;
  const labels = [];

  let a = -Math.PI / 2;
  const TAU = 2 * Math.PI;
  for (const [isl, regMap, islN] of islandTotals) {
    const islSpan = (islN / grandTotal) * TAU;
    const a0 = a, a1 = a + islSpan;
    const hue = ISLAND_HUE[isl] || "#475569";
    const islPct = (islN / grandTotal * 100).toFixed(1);
    svg += `<path d="${arcPath(cx, cy, r1, r2, a0, a1)}" fill="${hue}" stroke="#fff" stroke-width="1.5" opacity="0.95"` +
           ` class="sunb-seg" data-level="1" data-island="${esc(isl)}" data-count="${islN}" data-pct="${islPct}">` +
           `<title>${esc(isl)}: ${islN} entrades (${islPct}%)</title></path>`;
    if (islSpan > 0.25) {
      const mid = (a0 + a1) / 2, lr = (r1 + r2) / 2;
      labels.push(`<text x="${cx + lr * Math.cos(mid)}" y="${cy + lr * Math.sin(mid)}" class="sunb-label-island" text-anchor="middle" dominant-baseline="middle">${esc(isl)}</text>`);
    }

    const regs = [...regMap.entries()].map(([k, v]) => {
      let n = 0; for (const tn of v.values()) n += tn;
      return [k, v, n];
    }).sort((a, b) => b[2] - a[2]);

    let ar = a0;
    for (const [reg, typeMap, regN] of regs) {
      const regSpan = (regN / islN) * islSpan;
      const ar0 = ar, ar1 = ar + regSpan;
      const tint = REGIME_TINT[reg] ?? 0.6;
      const regPct = (regN / islN * 100).toFixed(0);
      svg += `<path d="${arcPath(cx, cy, r2, r3 - 50, ar0, ar1)}" fill="${lighten(hue, tint)}" stroke="#fff" stroke-width="1"` +
             ` class="sunb-seg" data-level="2" data-island="${esc(isl)}" data-regime="${esc(reg)}" data-count="${regN}" data-pct="${regPct}">` +
             `<title>${esc(isl)} · ${esc(reg)}: ${regN}</title></path>`;

      const types = [...typeMap.entries()].sort((a, b) => b[1] - a[1]);
      let at = ar0;
      for (const [typ, n] of types) {
        const tSpan = (n / regN) * regSpan;
        const at0 = at, at1 = at + tSpan;
        const tPct = (n / regN * 100).toFixed(0);
        svg += `<path d="${arcPath(cx, cy, r3 - 50, r3, at0, at1)}" fill="${lighten(hue, Math.max(0.2, tint - 0.3))}" stroke="#fff" stroke-width="0.6"` +
               ` class="sunb-seg" data-level="3" data-island="${esc(isl)}" data-regime="${esc(reg)}" data-type="${esc(typ)}" data-count="${n}" data-pct="${tPct}">` +
               `<title>${esc(isl)} · ${esc(reg)} · ${esc(typ)}: ${n}</title></path>`;
        at = at1;
      }
      ar = ar1;
    }
    a = a1;
  }

  svg += labels.join("");
  svg += `<text x="${cx}" y="${cy - 4}" text-anchor="middle" class="sunb-total">${fmt(grandTotal)}</text>`;
  svg += `<text x="${cx}" y="${cy + 14}" text-anchor="middle" class="sunb-total-label">entrades</text>`;
  svg += "</svg>";
  return svg;
}

// Attach hover/click listeners to the freshly rendered sunburst so users
// can see what each segment represents (the static <title> tooltip works
// but is browser-specific and slow to appear).
function wireSunburstHover() {
  const host = $("stats-chart-sunburst");
  const panel = $("stats-sunburst-info");
  if (!host || !panel) return;
  const segs = host.querySelectorAll(".sunb-seg");
  if (!segs.length) return;

  const show = (el) => {
    const lvl = el.dataset.level;
    const isl = el.dataset.island;
    const reg = el.dataset.regime;
    const typ = el.dataset.type;
    const n = el.dataset.count;
    const pct = el.dataset.pct;
    const islHTML = `<span class="sunb-info-isl" style="color:${ISLAND_HUE[isl] || '#475569'}">${esc(isl)}</span>`;
    let path;
    if (lvl === "1") path = `${islHTML}`;
    else if (lvl === "2") path = `${islHTML} <span class="sunb-info-sep">›</span> ${esc(reg)}`;
    else path = `${islHTML} <span class="sunb-info-sep">›</span> ${esc(reg)} <span class="sunb-info-sep">›</span> <strong>${esc(typ)}</strong>`;
    panel.innerHTML =
      `<span class="sunb-info-path">${path}</span>` +
      `<span class="sunb-info-count"><strong>${fmt(n)}</strong> entrades · ${pct}%</span>`;
  };
  const reset = () => {
    panel.innerHTML = '<span class="sunb-info-prompt">Passa el cursor per sobre d\'un segment per veure\'n el detall ↑</span>';
  };
  for (const el of segs) {
    el.addEventListener("mouseenter", () => show(el));
    el.addEventListener("focus", () => show(el));
    el.addEventListener("click", () => show(el));
  }
  host.addEventListener("mouseleave", reset);
}

// ===========================================================================
// === MAPA TAB ===============================================================
// ===========================================================================

let mapInstance = null;
let mapMarkersAll = [];
let mapLeafletLoading = null;

const ISLAND_COLOUR = {
  "Mallorca":   "#0070b8",
  "Menorca":    "#0f766e",
  "Ibiza":      "#c2410c",
  "Eivissa":    "#c2410c",
  "Formentera": "#a04545",
  "Cabrera":    "#7c3aed",
  "Baleares":   "#475569",
};

// Lazy-load Leaflet's JS bundle from the CDN. Returns a promise that
// resolves once window.L is available. Subsequent calls reuse the same
// promise so we don't fetch twice.
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (mapLeafletLoading) return mapLeafletLoading;
  mapLeafletLoading = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    s.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
    s.crossOrigin = "";
    s.onload = resolve;
    s.onerror = () => reject(new Error("Leaflet failed to load"));
    document.head.appendChild(s);
  });
  return mapLeafletLoading;
}

function radiusForVecinos(v) {
  if (!v || v <= 0) return 4;
  // sqrt scaling so a 7,000-vec Palma isn't 1000× a 50-vec aldea.
  return Math.max(4, Math.min(28, Math.sqrt(v) * 0.45));
}

function buildPopupHTML(e) {
  const stats = e.stats || {};
  const bits = [];
  if (e.place_type) bits.push(e.place_type);
  if (e.island) bits.push(e.island);
  if (e.seigneurial_regime) bits.push(e.seigneurial_regime);
  if (stats.vecinos) bits.push(`${fmt(stats.vecinos)} vec.`);
  if (stats.habitantes) bits.push(`${fmt(stats.habitantes)} hab.`);
  const meta = bits.join(" · ");
  const desc = (e.description || "").slice(0, 600);
  const more = (e.description || "").length > 600 ? "…" : "";
  const matched = e.matched_toponym
    ? ` <span class="map-popup-meta">↔ ${esc(e.matched_toponym)}</span>` : "";
  const fbLabel = {
    "ambiguous-homonym": "topònim ambigu — ubicació indeterminada",
    "island-centroid":   "ubicació aproximada al centre de l'illa",
  }[e.coord_fallback];
  const fb = fbLabel
    ? ` <em style="color:#94a3b8">(${esc(fbLabel)})</em>` : "";
  return (
    `<h3 class="map-popup-title">${esc(e.title)}${matched}</h3>` +
    `<p class="map-popup-meta">${esc(meta)} · Tom ${e.vol} · pàg. ${e.page_printed || "?"}${fb}</p>` +
    `<p class="map-popup-desc">${esc(desc)}${more}</p>` +
    (e.ia_url
      ? `<a class="map-popup-link" href="${e.ia_url}" target="_blank" rel="noopener">↗ Facsímil a IA</a>`
      : "")
  );
}

async function renderMap() {
  await loadLeaflet();
  const el = $("map-canvas");
  if (!el) return;

  if (!mapInstance) {
    // Fit-bounds for Balearic archipelago
    mapInstance = L.map(el, {
      center: [39.7, 2.9],
      zoom: 8,
      zoomControl: true,
      scrollWheelZoom: true,
    });
    // CARTO light basemap — no API key required, very legible for thematic overlays
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 19,
      subdomains: "abcd",
    }).addTo(mapInstance);

    // Build markers (only once — Leaflet keeps them in layers).
    for (const e of state.entries) {
      if (typeof e.lon !== "number" || typeof e.lat !== "number") continue;
      const r = radiusForVecinos(e.stats?.vecinos);
      const colour = ISLAND_COLOUR[e.island] || "#475569";
      const m = L.circleMarker([e.lat, e.lon], {
        radius: r,
        color: "#fff",
        weight: 1.2,
        fillColor: colour,
        fillOpacity: e.coord_fallback ? 0.35 : 0.78,
      });
      m._minano_entry = e;
      m.bindPopup(() => buildPopupHTML(e), { maxWidth: 360, minWidth: 280 });
      mapMarkersAll.push(m);
    }

    // Wire fallback toggle
    const toggle = $("map-toggle-fallback");
    if (toggle) {
      toggle.addEventListener("change", () => syncMapMarkers(toggle.checked));
    }
    syncMapMarkers(toggle ? toggle.checked : true);

    // Fit bounds to all visible (non-fallback) markers
    const real = mapMarkersAll.filter(m => !m._minano_entry.coord_fallback);
    if (real.length) {
      const group = L.featureGroup(real);
      mapInstance.fitBounds(group.getBounds().pad(0.08));
    }
  } else {
    // Leaflet needs a kick when the container becomes visible again
    setTimeout(() => mapInstance.invalidateSize(), 60);
  }
}

function syncMapMarkers(showFallback) {
  if (!mapInstance) return;
  for (const m of mapMarkersAll) {
    const fb = m._minano_entry.coord_fallback;
    if (fb && !showFallback) {
      if (mapInstance.hasLayer(m)) mapInstance.removeLayer(m);
    } else {
      if (!mapInstance.hasLayer(m)) m.addTo(mapInstance);
    }
  }
}

boot();

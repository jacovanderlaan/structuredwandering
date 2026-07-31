/* ============================================================================
   browse.js — faceted browse over content_item.parquet, in the reader's browser.

   Shared by every site. Generated in by sync_tokens.py; do not edit a site copy.

   Best of both, per Jaco (31 Jul 2026):
     * from jacovanderlaan.com (Annemarie's WordPress filter): a faceted sidebar
       with live COUNTS per facet, free-text search, and the hero image beside
       the item.
     * from the Beacon app: a VIEW SWITCHER — List · Cards · Grid — and the
       compact card density with type/tag chips.

   ⚠️ ADR-129 — why this is safe: every row carries `url`, never `body`. This
   filter emits LINKS to pages that already exist as static HTML. A crawler that
   runs no JavaScript still reaches every item through the sitemap and the
   static listing; this is a faster route for humans, never the only route.
   ============================================================================ */

const DUCKDB_CDN = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.28.0/+esm";

export async function initBrowse(mount, opts = {}) {
  const dataUrl = opts.data || "../data/content_item.parquet";
  const base = opts.base || "../";
  const assets = opts.assets || "../assets/";

  const el = typeof mount === "string" ? document.querySelector(mount) : mount;
  if (!el) return;
  el.innerHTML = `<div class="bw-loading">Loading…</div>`;

  let rows;
  try {
    rows = await loadRows(dataUrl);
  } catch (err) {
    // ⚠️ THROW, do not return. The caller does
    //     .then(() => document.body.classList.add("bw-ready"))
    // and `.bw-ready .bw-fallback{display:none}` hides the static list. Returning
    // normally resolved that promise, so a failed filter hid the very fallback
    // it was supposed to fall back to — an empty page with the data sitting in
    // the HTML. Throwing keeps the fallback visible and lets .catch() log it.
    el.innerHTML = "";
    console.warn("browse: falling back to the static list —", err);
    throw err;
  }

  // ⭐ The page type IS the filter. A Skills page shows skills — the reader
  // should never have to tick "skill" to see them, and must not be able to
  // untick it into showing concepts. Rows outside the scope are dropped before
  // anything else runs, so facets and counts only ever describe this page.
  const scope = opts.itemTypes || [];
  if (scope.length) rows = rows.filter((r) => scope.includes(r.type));

  const state = fromHash(opts.defaults || {});
  let lastSet = [];
  el.innerHTML = shell();
  const $ = (s) => el.querySelector(s);

  const wireFacets = () => {
    el.querySelectorAll("[data-facet]").forEach((cb) => {
      cb.onchange = () => {
        const set = state[cb.dataset.facet];
        cb.checked ? set.add(cb.value) : set.delete(cb.value);
        render();
      };
    });
  };

  const render = () => {
    const out = apply(rows, state);
    // Hand the CURRENT filtered set to the detail page, so prev/next steps
    // through what the reader was actually looking at — not a global ordering.
    lastSet = out.map((r) => ({ slug: r.slug, title: r.title, url: r.url }));
    $(".bw-facets").innerHTML = facets(rows, state, scope);
    $(".bw-results").innerHTML = results(out, state, base, assets);
    $(".bw-count").textContent =
      `${out.length} of ${rows.length}` + (out.length === 1 ? " item" : " items");
    wireFacets();
    history.replaceState(null, "", location.pathname + toHash(state));
  };


  // remember the set + the clicked position on the way out (detail.js reads it)
  el.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || !lastSet.length) return;
    const slug = a.getAttribute("href").split("/").pop().replace(/\.html$/, "");
    const idx = lastSet.findIndex((x) => x.slug === slug);
    if (idx < 0) return;
    try {
      sessionStorage.setItem("bw:lastQuery", JSON.stringify(
        { slugs: lastSet, index: idx,
          // the hash carries the FILTER, so "back to list" returns the reader
          // to the set they were looking at — not to an unfiltered page
          listUrl: location.pathname + toHash(state) }));
    } catch { /* private mode — the stepper just will not appear */ }
  });

  $(".bw-search").oninput = (e) => { state.q = e.target.value.toLowerCase(); render(); };
  $(".bw-sort").onchange = (e) => { state.sort = e.target.value; render(); };
  el.querySelectorAll("[data-view]").forEach((b) => {
    b.onclick = () => {
      state.view = b.dataset.view;
      el.querySelectorAll("[data-view]").forEach((x) => x.classList.toggle("on", x === b));
      render();
    };
  });
  $(".bw-clear").onclick = () => {
    state.q = ""; state.type.clear(); state.category.clear(); state.topic.clear();
    $(".bw-search").value = ""; render();
  };

  render();
}

/* ---- filter state in the URL --------------------------------------------
   So a filtered view is linkable, survives a reload, and can be returned to
   from a detail page. The hash is the state; nothing is stored server-side. */

function toHash(s) {
  const p = new URLSearchParams();
  if (s.q) p.set("q", s.q);
  if (s.type.size) p.set("type", [...s.type].join("|"));
  if (s.category.size) p.set("cat", [...s.category].join("|"));
  if (s.topic.size) p.set("topic", [...s.topic].join("|"));
  if (s.view !== "list") p.set("view", s.view);
  if (s.sort !== "title") p.set("sort", s.sort);
  const q = p.toString();
  return q ? "#" + q : "";
}

function fromHash(defaults) {
  const p = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  const split = (v) => new Set(v ? v.split("|").filter(Boolean) : []);
  return {
    q: p.get("q") || "",
    // ⚠️ Every FACET key must exist here as a Set. Adding "topic" to the facet
    // list without adding it here made facets() read undefined.has() and the
    // whole render threw — the chrome painted, the results never did.
    type: split(p.get("type")),
    category: split(p.get("cat")),
    topic: split(p.get("topic")),
    view: p.get("view") || defaults.view || "list",
    sort: p.get("sort") || defaults.sort || "title",
  };
}

/* ---- data ---------------------------------------------------------------- */

async function loadRows(url) {
  // ⚠️ Copied verbatim from structuredmetadata/browser.html, which has worked in
  // production since June. Correction to an earlier note here: duckdb.createWorker
  // DOES exist in the 1.28 ESM build — that was not the bug. The real failure was
  // registerFileURL below. When a working implementation already exists in the
  // repo, copy it instead of writing a second one from memory.
  const duckdb = await import(DUCKDB_CDN);
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerUrl = URL.createObjectURL(new Blob(
    [`importScripts("${bundle.mainWorker}");`], { type: "text/javascript" }));
  const worker = new Worker(workerUrl);
  const db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  const conn = await db.connect();
  // ⚠️ fetch + registerFileBuffer, NOT registerFileURL. The working
  // implementation (structuredmetadata/browser.html, in production since June)
  // fetches the bytes and hands them over; registerFileURL with the HTTP
  // protocol handler failed silently here. Copy what works.
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${resp.status} fetching ${url}`);
  const buf = new Uint8Array(await resp.arrayBuffer());
  await db.registerFileBuffer("content.parquet", buf);
  const res = await conn.query("SELECT * FROM read_parquet('content.parquet')");
  const rows = res.toArray().map((r) => JSON.parse(JSON.stringify(r)));
  await conn.close();
  return rows;
}

/* ---- filtering ----------------------------------------------------------- */

function apply(rows, s) {
  let out = rows.filter((r) => {
    if (s.type.size && !s.type.has(r.type)) return false;
    if (s.category.size && !s.category.has(r.category || "—")) return false;
    if (s.topic.size && !s.topic.has(r.topic || "—")) return false;
    if (s.q) {
      const hay = `${r.title} ${r.excerpt} ${r.category} ${r.topic}`.toLowerCase();
      if (!hay.includes(s.q)) return false;
    }
    return true;
  });
  const by = {
    title: (a, b) => (a.title || "").localeCompare(b.title || ""),
    newest: (a, b) => String(b.created || "").localeCompare(String(a.created || "")),
    longest: (a, b) => (b.word_count || 0) - (a.word_count || 0),
  }[s.sort];
  return out.sort(by);
}

/* ---- markup -------------------------------------------------------------- */

function shell() {
  return `
  <div class="bw">
    <aside class="bw-side">
      <div class="bw-side-h">Filter <button class="bw-clear" type="button">clear</button></div>
      <input class="bw-search" type="search" placeholder="Search…" aria-label="Search" />
      <div class="bw-facets"></div>
    </aside>
    <div class="bw-main">
      <div class="bw-bar">
        <span class="bw-count"></span>
        <span class="bw-spacer"></span>
        <select class="bw-sort" aria-label="Sort">
          <option value="title">A–Z</option>
          <option value="newest">Newest</option>
          <option value="longest">Longest</option>
        </select>
        <div class="bw-views" role="group" aria-label="View">
          <button type="button" data-view="list" class="on">List</button>
          <button type="button" data-view="cards">Cards</button>
          <button type="button" data-view="grid">Grid</button>
        </div>
      </div>
      <div class="bw-results"></div>
    </div>
  </div>`;
}

function facets(rows, s, scope = []) {
  const group = (key, label) => {
    const counts = {};
    for (const r of rows) {
      // count against everything EXCEPT this facet, so a count never reads zero
      // for an option you can still usefully pick (Annemarie's filter does this)
      const probe = { ...s, [key]: new Set() };
      if (!apply([r], probe).length) continue;
      const v = r[key] || "—";
      counts[v] = (counts[v] || 0) + 1;
    }
    const items = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    if (!items.length) return "";
    return `<div class="bw-fgroup"><div class="bw-flabel">${label}</div>` +
      items.map(([v, n]) => `
        <label class="bw-f">
          <input type="checkbox" data-facet="${key}" value="${esc(v)}"
                 ${s[key].has(v) ? "checked" : ""} />
          <span>${esc(v)}</span><span class="bw-n">${n}</span>
        </label>`).join("") + "</div>";
  };
  // A Type facet listing one option is noise: the page already IS that type.
  // With a mixed scope (concepts + activities + anti-patterns) it still helps.
  const typeFacet = scope.length === 1 ? "" : group("type", "Type");
  return typeFacet + group("category", "Category") + group("topic", "Topic");
  // group() already returns "" when a facet has no values, so an empty
  // Topic section never renders.
}

function results(out, s, base, assets) {
  if (!out.length) return `<p class="bw-empty">Nothing matches. <button class="bw-clear" type="button">Clear filters</button></p>`;
  return `<div class="bw-${s.view}">` + out.map((r) => item(r, s.view, base, assets)).join("") + "</div>";
}

function item(r, view, base, assets) {
  const href = base + r.url;
  const img = r.hero_image
    ? `<img class="bw-img" src="${assets}${esc(r.hero_image)}" alt="" loading="lazy" />`
    : "";
  const chips = [r.type, r.category].filter(Boolean)
    .map((c) => `<span class="bw-chip">${esc(c)}</span>`).join("");
  const meta = [r.created, r.word_count ? `${Math.max(1, Math.round(r.word_count / 200))} min` : ""]
    .filter(Boolean).map(esc).join(" · ");

  if (view === "grid") {
    return `<a class="bw-cell" href="${href}">${img}
      <strong>${esc(r.title)}</strong><span class="bw-chips">${chips}</span></a>`;
  }
  // list and cards share the shape jacovanderlaan.com uses: image beside the text
  return `<article class="bw-item">
    <div class="bw-body">
      <h3><a href="${href}">${esc(r.title)}</a></h3>
      <div class="bw-meta">${meta}</div>
      <div class="bw-chips">${chips}</div>
      <p>${esc(r.excerpt || "")}</p>
      <a class="bw-more" href="${href}">Read more</a>
    </div>
    ${img}
  </article>`;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ============================================================================
   detail.js — the item-detail behaviour, shared by every site.

   Jaco (31 Jul 2026): "When you click on an article or concept the left menu is
   replaced by a TOC menu to navigate in the document. In the top row you can
   skip forward and backward through the data set and the form is refreshed."

   Two behaviours, both borrowed from the Beacon app:

     1. TOC-IN-PLACE — the left column carries the browse facets on a listing
        page and the document's own TOC on a detail page. Same slot, different
        job, so the reader's eye does not have to move.

     2. PREV / NEXT over the FILTERED SET — stepping through the same list you
        were just looking at, in the same order, not through some global
        alphabetical ordering that ignores what you filtered.

   ⚠️ ADR-129: this is progressive enhancement. The page is complete static HTML
   before this runs; the TOC and the stepper are conveniences layered on top. If
   the script fails, the reader loses navigation aids, never content.
   ============================================================================ */

const KEY = "bw:lastQuery";   // the filtered set, handed over from the listing

/* Called by browse.js when the reader follows a link, so the detail page knows
   which set it is being read within. */
export function rememberSet(slugs, index, listUrl) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ slugs, index, listUrl }));
  } catch { /* private mode: the stepper simply will not appear */ }
}

export function initDetail(opts = {}) {
  buildToc(opts);
  buildStepper(opts);
}

/* ---- 1 · TOC in the left column ------------------------------------------ */

function buildToc({ body = "main, .pagebody, section.wrap", slot = ".toc, #toc" } = {}) {
  const main = document.querySelector(body);
  if (!main) return;

  const heads = [...main.querySelectorAll("h2, h3")].filter((h) => h.textContent.trim());
  if (heads.length < 2) return;          // one heading is not a table of contents

  const seen = {};
  const items = heads.map((h) => {
    if (!h.id) {
      let s = h.textContent.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48);
      seen[s] = (seen[s] || 0) + 1;
      h.id = seen[s] === 1 ? s : `${s}-${seen[s]}`;
    }
    return { id: h.id, text: h.textContent.trim(), level: h.tagName === "H3" ? 3 : 2 };
  });

  let host = document.querySelector(slot);
  if (!host) {
    // no dedicated slot on this template — create one beside the content
    host = document.createElement("aside");
    host.className = "toc";
    main.parentNode.insertBefore(host, main);
    main.parentNode.classList.add("pagewrap");
  }
  host.innerHTML = `
    <button class="toc-toggle" aria-expanded="true" aria-controls="toc-list"
            title="Show or hide the contents" aria-label="Show or hide the contents"
            onclick="var o=document.body.classList.toggle('toc-off');
                     this.setAttribute('aria-expanded', String(!o));">&#9776;</button>
    <div class="toc-inner" id="toc-list">
      <div class="toc-h">On this page</div>
      <ul>${items.map((i) =>
        `<li class="l${i.level}"><a href="#${i.id}">${esc(i.text)}</a></li>`).join("")}</ul>
    </div>`;

  // highlight the section the reader is actually in
  const links = [...host.querySelectorAll("a")];
  const obs = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      links.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === `#${e.target.id}`));
    }
  }, { rootMargin: "-70px 0px -70% 0px" });
  heads.forEach((h) => obs.observe(h));
}

/* ---- 2 · prev / next through the filtered set ---------------------------- */

function buildStepper({ mount = ".pagebody, main" } = {}) {
  let set;
  try { set = JSON.parse(sessionStorage.getItem(KEY) || "null"); } catch { return; }
  if (!set || !Array.isArray(set.slugs) || set.slugs.length < 2) return;

  const here = location.pathname.split("/").pop().replace(/\.html$/, "");
  let i = set.slugs.findIndex((s) => s.slug === here || s === here);
  if (i < 0) i = Number.isInteger(set.index) ? set.index : -1;
  if (i < 0) return;

  const at = (n) => set.slugs[n];
  const href = (x) => (typeof x === "string" ? `${x}.html` : x.url.split("/").pop());
  const label = (x) => (typeof x === "string" ? x.replace(/-/g, " ") : x.title);

  const bar = document.createElement("nav");
  bar.className = "bw-stepper";
  bar.setAttribute("aria-label", "Item navigation");
  bar.innerHTML = `
    ${i > 0 ? `<a class="bw-prev" href="${href(at(i - 1))}" rel="prev">&larr; ${esc(label(at(i - 1)))}</a>`
            : `<span class="bw-prev bw-off"></span>`}
    <span class="bw-pos">${i + 1} / ${set.slugs.length}${
      set.listUrl ? ` &middot; <a href="${set.listUrl}">back to list</a>` : ""}</span>
    ${i < set.slugs.length - 1
      ? `<a class="bw-next" href="${href(at(i + 1))}" rel="next">${esc(label(at(i + 1)))} &rarr;</a>`
      : `<span class="bw-next bw-off"></span>`}`;

  const host = document.querySelector(mount);
  if (host) host.insertBefore(bar, host.firstChild);

  // keyboard: ← / → step, the way the app does
  document.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    if (e.key === "ArrowLeft" && i > 0) location.href = href(at(i - 1));
    if (e.key === "ArrowRight" && i < set.slugs.length - 1) location.href = href(at(i + 1));
  });
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

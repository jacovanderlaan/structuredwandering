# Structured Wandering — deliberate travel site

The **personal, on-the-road sibling** of [Structure Beats Magic](https://structurebeatsmagic.com).
A travel-curation site where every place, route and read is pulled from curated
sources and intelligent systems — chosen, not scrolled.

> The best trips aren't found. They're chosen.
> **Structure + Taste + Sources → Journeys worth taking.**

## Role in the brand architecture

This is a **spoke** of the Structure Beats Magic world, pointed at a consumer
interest (travel). It proves the engine works on a topic anyone cares about, and
routes readers who want the *method* back to the SBM hub / the enterprise lane.

```
structuredwandering.com   ← THIS SITE (deliberate-travel curation)
  ├─ The idea        (why "structured wandering" isn't a contradiction)
  ├─ How it's built  (sources → structure → taste → journeys)
  ├─ What's curated  (trips · places · reading · gear)
  │    └─ Live now — Sicily: /palermo /ortigia /cefalu /agrigento
  ├─ Writing         (essays, built from markdown)
  └─ → structurebeatsmagic.com   (the method behind it)
```

**Who we are:** Jaco **and Annemarie** — the Structured Wanderers. Pages are
written "we"; the footer credits both. (Sibling site: Annemarie publishes our
actual trips, narrated, at keepwandering.com — different purpose, not merged.)

Affiliate links, where present, are a **quiet, tasteful layer** — only for things
actually used, always flagged. Taste over algorithm; the whole point is that a
person chose it.

## Stack

Static-first, mirroring SBM (ADR-046): plain HTML + shared `assets/site.css` /
`article.css` / `curated.css`, no framework, no runtime. `index.html` is
hand-authored. Three sibling Python builders generate the rest — they import each
other's helpers so they never drift:

| Builder | Source | Output |
|---|---|---|
| `build_articles.py` | markdown drafts (`W:/travel/products/structuredwandering/articles/`) | `articles/*.html` + `writing/index.html` + `sitemap.xml` |
| `build_curated.py` | the travelbrain DuckDB brain, via `curated/content.json` | `/<destination>/index.html` (ADR-085) |
| `build_books.py` | book folder-notes (`W:/travel/books/`) | book pages (0 published — scaffolds await content) |

Brand palette is the SBM family (off-white / navy / gold) with a **travel-teal
accent** (`#0d7d7d`) instead of SBM blue — same system, its own identity.

## Build (articles + sitemap)

The homepage needs no build. Articles do:

```bash
python build_articles.py
# SW_ARTICLES_ROOT="W:/.../articles" python build_articles.py   # override source
```

Renders allow-listed markdown drafts (folder-per-article, from
`W:/travel/products/structuredwandering/articles/`) into `articles/*.html`,
injects the newest cards into the homepage between the `ARTICLE-CARDS` markers,
writes `writing/index.html`, and regenerates `sitemap.xml`. Add slugs to the
`ARTICLES` allow-list as you publish them. Run before committing when a draft
changes.

## Build (curated destinations) — the engine → showcase (ADR-085)

The destination pages are **generated from the travelbrain curation engine**, not
hand-written. The brain is the source of truth; this repo is the showcase.

```
travelbrain/brain/curation.duckdb        source-canon → evidence → versioned taste
      │                                  rubric → hard-exclude gate → decisions
      │  travelbrain/site/scripts/export_content.py     (SQL → JSON bridge)
      ▼
   curated/content.json                  (gitignored — a build input, not source)
      │  build_curated.py                (THIS repo — Structured Wandering chrome)
      ▼
   /palermo/ /ortigia/ /cefalu/ ...      the showcase
```

```bash
# 1. in the travelbrain repo — build the brain + export
python brain/build_db.py --reset                      # ⚠️ --reset wipes dim_content
python pipeline/draft_page.py --destination Palermo --draft-file pipeline/palermo_draft.json
python site/scripts/export_content.py                 # → site/src/content.json

# 2. here — copy the export in, render the pages
cp <travelbrain>/site/src/content.json curated/content.json
python build_curated.py                # --draft to include status=draft pages
```

**Why not Astro:** travelbrain's own site is Astro; running it alongside SW's
plain-HTML builders would mean two build systems and two visual languages on one
domain. So Astro is out of the publishing path — the brain stays the source of
truth, `build_curated.py` renders it in SW's chrome (ADR-085 "Considered
alternatives").

**What the pages must show** (the differentiator — not a listicle): the versioned
taste profile that scored each venue, **what the rules ruled out** (anti-interests
are part of the model), the published evidence per pick, the human approve step,
and honest links — affiliate **only** where the brain holds a real provider
mapping, otherwise it falls back to the venue's own site. Never a fabricated URL.

**Publish gate** (mirrors ADR-068 §1b): a destination renders only with a real
body + venues + a header image; anything else is held back with a printed reason.

⚠️ **Photos are copied, not linked.** The brain references images by root-relative
path (`/photos/…`) and the files live in `travelbrain/site/public/` — its Astro
site serves them from there, **this repo must hold its own copy**. `build_curated.py`
copies them in (`SW_PHOTO_SRC` to override) and then **resolves every `<img src>`
it just wrote; any dead reference fails the build.** Skipping that shipped 11
broken images to production on 2026-07-15.

⚠️ **CSS namespace:** `site.css` owns `.fit` (the homepage two-column comparison
grid). `curated.css` must not redefine it — doing so broke the live homepage on
2026-07-15. The taste badge is `.taste-score`. Check before adding selectors:

```bash
python - <<'PY'
import re
sels=lambda p:set(re.findall(r'(?m)^\s*(\.[a-zA-Z][\w-]*)',re.sub(r'/\*.*?\*/','',open(p,encoding='utf-8').read(),flags=re.S)))
print(sorted(sels('assets/site.css') & sels('assets/curated.css')) or 'no collisions')
PY
```

## Preview

```bash
python -m http.server 8000   # then open http://localhost:8000
```

Open `http://localhost:8000/palermo/` — **not** the folder via `file://`, which
just shows a directory listing (there's no index resolution without a server).

## Deploy

GitHub Pages via Actions (`.github/workflows/deploy.yml`) on push to `main`,
publishing the repo root. Custom domain `structuredwandering.com` (registered at
Dynadot 2026-07-12, CNAME present, apex A-records → GitHub Pages
185.199.108–111.153, `www` CNAME → `jacovanderlaan.github.io`).

`build_articles.py` / `build_books.py` run locally before commit — no host-side
build. Still TODO: set the real GA4 property id (currently a `G-XXXXXXXXXX`
placeholder in the builders).

## Status (2026-07-15)

🟢 **Live** at http://structuredwandering.com — landing page + **4 curated Sicily
destinations** (`/palermo` 7 venues · `/ortigia` 4 · `/cefalu` · `/agrigento`),
generated from the travelbrain brain and linked from the homepage's *Live now*
block under `#curation`.

🔴 **HTTPS is NOT working — and it's GitHub's side.** The Pages cert has been
stuck at `state: new` since the CNAME went in on 12 Jul; re-adding the custom
domain on 15 Jul re-triggered it and it stalled again at the same first step.
Our side is verified clean: apex A-records → 185.199.108–111.153, `www` aliased,
**no CAA record, no stale AAAA**, `CNAME` present locally and on the remote. HTTP
serves 200; HTTPS fails `SEC_E_WRONG_PRINCIPAL`. Enforce-HTTPS **cannot** be
enabled until the cert issues. GitHub's docs allow up to 24h — if it's still
`new` after that, open a Support ticket citing both stalled requests.

⚪ **Not yet:** 0 articles published (first draft written: *"How We Decide Who to
Trust"* — the curated-sources method as an SBM use case, in
`W:/travel/products/structuredwandering/articles/`), 0 books, no public sources
directory yet, no affiliate mappings (so every venue link is an honest fallback
to the venue's own site), and the GA4 property id in `build_articles.py` is still
the `G-XXXXXXXXXX` placeholder.

⚠️ **Known bug (latent):** `build_articles.py`'s page template still carries **SBM
chrome** — brand header "Structure Beats Magic", footer crediting only Jaco. It's
invisible today because 0 articles are built, but it will ship the moment one is.
`build_curated.py` deliberately uses the correct SW chrome ("Structured
Wandering", "Jaco & Annemarie") — fix `build_articles.py` before publishing an
article.

Decisions: ADR-085 (engine → showcase) in `D:/vault/system/1-plan/6-decisions/`;
domain/brand: `decision_deliberate-interest-sites-domains.md` in the vault
calendar (12 Jul).

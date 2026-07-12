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
  ├─ Writing         (essays, built from markdown)
  └─ → structurebeatsmagic.com   (the method behind it)
```

Affiliate links, where present, are a **quiet, tasteful layer** — only for things
actually used, always flagged. Taste over algorithm; the whole point is that a
person chose it.

## Stack

Static-first, mirroring SBM (ADR-046): plain HTML + a shared `assets/site.css` /
`article.css`, no framework, no runtime. `index.html` is hand-authored. The
**articles** are the one built part: markdown drafts → `build_articles.py` →
styled `articles/*.html` + `writing/index.html` + `sitemap.xml`.

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

## Preview

```bash
python -m http.server 8000   # then open http://localhost:8000
```

## Deploy (not wired yet)

Intended: GitHub Pages via Actions on push to `main`, custom domain
`structuredwandering.com` (CNAME present). **Domain not yet registered / DNS not
cut over** — this is a local scaffold. Before going live: register the domain,
add the GitHub remote + Pages workflow, and set the real GA4 property id
(currently a `G-XXXXXXXXXX` placeholder in `build_articles.py`).

## Status

🚧 **Scaffold — pre-launch.** Landing page + article pipeline are in place and the
build runs green with zero articles. No domain, no remote, no analytics yet.
See the decision record in the vault:
`D:/vault/calendar/2026/Q3/07 - Jul/.../decision_deliberate-interest-sites-domains.md`.

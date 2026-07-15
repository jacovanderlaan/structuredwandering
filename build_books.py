#!/usr/bin/env python3
"""
Build Structure-Beats-Magic book-reference pages from the folder-per-book markdown
under BOOKS_ROOT -> books/<slug>.html, plus a books/index.html library landing page.

Sibling of build_articles.py (ADR-068 references-layer, SBM/systems route). Same
conventions: folder-per-unit source of truth, YAML frontmatter, and the shared
md->html renderer + private-section stripping + concept auto-linking are imported
from build_articles so the two builders never drift. This is the SBM twin of
jacovanderlaan-site/build_books.py — same data, SBM chrome.

A book page is a *reference*, not an article: no full book contents (copyright),
just Jaco's curated take — why it's in the collection, the AI/MDDE-SBM-lens
highlights, what he did with it, related concepts/writing, and an (optional)
affiliate link with disclosure.

Source of truth = W:/systems/books/<slug>/<slug>.md (the SBM route of ADR-068).
Only books whose status is in PUBLISH_STATUS (default: pilot,ready) publish, so
scaffolds stay private until their personal pass is written.
Override with SW_BOOK_STATUS="pilot,ready,scaffold" or SW_BOOKS="slug1,slug2".

Usage:
    python build_books.py
    SW_BOOKS_ROOT="W:/..." python build_books.py         # override source
    SW_BOOK_STATUS="pilot,ready,scaffold" python build_books.py  # widen gate
"""
from __future__ import annotations

import os
import re
import html
import json
import shutil
from pathlib import Path

# Reuse the SBM article builder's helpers + brand config so the two never drift.
import build_articles as A
from build_articles import (
    split_frontmatter,
    md_to_html,
    strip_private_sections,
    _norm_reflist,
    _load_concept_map,
    autolink_concepts,
    BASE_URL,
    CSS,
)

HERE = Path(__file__).parent
BOOKS_ROOT = Path(os.environ.get("SW_BOOKS_ROOT", "W:/travel/books"))
OUT = HERE / "books"             # books/<slug>.html + books/index.html
ASSETS = HERE / "assets"
CONCEPTS_URL = "../concepts"     # SBM has per-concept pages

PUBLISH_STATUS = {
    s.strip().lower()
    for s in os.environ.get("SW_BOOK_STATUS", "pilot,ready").split(",")
    if s.strip()
}
_ALLOW = [s.strip() for s in os.environ.get("SW_BOOKS", "").split(",") if s.strip()]

# Private author notes live inline as HTML comments (<!-- TODO: Jaco … -->).
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_html_comments(body: str) -> str:
    body = _HTML_COMMENT.sub("", body)
    return re.sub(r"\n{3,}", "\n\n", body)


def strip_placeholder_sections(body: str) -> str:
    """Drop any ## section whose body is only a scaffold placeholder.

    Scaffold notes carry stub sections — a lone italic "_To write…_" line, or the
    "Get the book" affiliate stub before any real affiliate link exists. Those must
    never reach a published page. Sections with real prose, bullets, or a blockquote
    stay; a section whose only non-blank lines all start with "_" is dropped.
    """
    parts = re.split(r"(?m)^(## .+)$", body)
    out = [parts[0]]
    for i in range(1, len(parts), 2):
        head, sec = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        lines = [l for l in sec.strip().split("\n") if l.strip()]
        if not lines or all(l.strip().startswith("_") for l in lines):
            continue  # drop heading + its stub body
        out.append(head + sec.rstrip() + "\n")
    joined = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", joined).strip() + "\n"


def _fm_str(meta: dict, key: str, default: str = "") -> str:
    # A present-but-null YAML value (e.g. "year:" with nothing after it) parses
    # to None; without this guard str(None) -> "None" leaks into bylines.
    val = meta.get(key, default)
    if val is None:
        val = default
    return str(val).strip().strip("'\"")


def _authors(meta: dict) -> str:
    a = meta.get("authors")
    if isinstance(a, list):
        return ", ".join(str(x).strip().strip("'\"") for x in a)
    return _fm_str(meta, "authors") or _fm_str(meta, "author")


def _meta_line(meta: dict) -> str:
    bits = [_authors(meta)]
    y = _fm_str(meta, "year")
    if y:
        bits.append(y)
    cl = _fm_str(meta, "cluster")
    if cl:
        bits.append(cl.replace("-", " "))
    return " · ".join(b for b in bits if b)


def _has_real_highlights(body: str) -> bool:
    """True only if the Highlights section has real content — not the scaffold
    stub. A book whose highlights are still '_To write: …_' must NOT publish."""
    m = re.search(r"##\s*Highlights(.*?)(?=\n##\s|\Z)", body, re.S)
    if not m:
        return False
    sec = m.group(1)
    if "To write:" in sec:
        return False
    # require some real prose beyond the "AI-assisted." preamble
    real = [l for l in sec.strip().split("\n")
            if l.strip() and not l.strip().strip("*_").lower().startswith("ai-assisted")]
    return any(len(l.strip()) > 20 for l in real)


def _has_cover(folder: Path) -> bool:
    return any((folder / n).is_file() for n in ("cover.jpg", "cover.jpeg", "cover.png"))


def discover_books() -> list[str]:
    if _ALLOW:
        return _ALLOW
    slugs, skipped = [], 0
    if not BOOKS_ROOT.is_dir():
        print(f"  ! books root not found: {BOOKS_ROOT}")
        return slugs
    for folder in sorted(BOOKS_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        note = folder / f"{folder.name}.md"
        if not note.exists():
            continue
        meta, body = split_frontmatter(note.read_text(encoding="utf-8"))
        if _fm_str(meta, "status").lower() not in PUBLISH_STATUS:
            continue
        # Publish gate (2026-07-12): a book goes live ONLY with real highlights
        # AND a cover image. Stubs ("_To write…_") and cover-less books are held
        # back until filled in — "generate content + image first, then publish".
        if not _has_real_highlights(body) or not _has_cover(folder):
            skipped += 1
            continue
        slugs.append(folder.name)
    if skipped:
        print(f"  (held back {skipped} incomplete book(s): missing real highlights or cover)")
    return slugs


def copy_cover(folder: Path, slug: str) -> str:
    for name in ("cover.jpg", "cover.jpeg", "cover.png"):
        src = folder / name
        if src.is_file():
            ASSETS.mkdir(exist_ok=True)
            dest_name = f"book-{slug}{src.suffix.lower()}"
            shutil.copy2(src, ASSETS / dest_name)
            return dest_name
    return ""


def build_stars(rating) -> str:
    try:
        r = int(rating)
    except (TypeError, ValueError):
        return ""
    r = max(0, min(5, r))
    return "★" * r + "☆" * (5 - r)


def build_related(meta: dict, book_titles: dict, concept_names: dict) -> str:
    """Related concepts (../concepts/<slug>.html) + related writing/books."""
    rc = _norm_reflist(meta.get("related_concepts"))
    ra = _norm_reflist(meta.get("related_articles"))
    blocks = []
    if rc:
        lis = []
        for c in rc:
            key = str(c).strip()
            bare = key[len("concept-"):] if key.startswith("concept-") else key
            label = concept_names.get(bare) or bare.replace("-", " ").title()
            lis.append(f'<li><a href="{CONCEPTS_URL}/{html.escape(bare, quote=True)}.html">{html.escape(label)}</a></li>')
        blocks.append(f"<h3>Related concepts</h3><ul>{''.join(lis)}</ul>")
    if ra:
        lis = []
        for a in ra:
            if isinstance(a, dict) and a.get("url"):
                lis.append(f'<li><a href="{html.escape(a["url"], quote=True)}">{html.escape(a.get("title") or a["url"])}</a></li>')
            else:
                aslug = str(a).strip()
                if aslug in book_titles:
                    lis.append(f'<li><a href="{html.escape(aslug, quote=True)}.html">{html.escape(book_titles[aslug])}</a></li>')
                else:
                    lis.append(f'<li><a href="../writing/{html.escape(aslug, quote=True)}.html">{html.escape(aslug.replace("-", " ").title())}</a></li>')
        if lis:
            blocks.append(f"<h3>Related writing</h3><ul>{''.join(lis)}</ul>")
    if not blocks:
        return ""
    return f'<aside class="article-related"><h2>Related</h2>{"".join(blocks)}</aside>'


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} — Books — Structured Wandering</title>
<meta name="description" content="{meta_desc}"/>
<meta name="author" content="Jaco van der Laan"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{meta_desc}"/>
<meta property="og:type" content="book"/>
<meta property="og:url" content="{canonical}"/>
<meta property="og:site_name" content="Structured Wandering"/>
<meta property="og:image" content="{og_image_abs}"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:image" content="{og_image_abs}"/>
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg"/>
<link rel="icon" type="image/png" sizes="32x32" href="../assets/favicon-32.png"/>
<link rel="icon" type="image/png" sizes="16x16" href="../assets/favicon-16.png"/>
<link rel="apple-touch-icon" sizes="180x180" href="../assets/favicon-180.png"/>
<link rel="stylesheet" href="{css}"/>
<script type="application/ld+json">
{json_ld}
</script>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', 'G-XXXXXXXXXX');
</script>
</head>
<body>
<header class="site"><div class="wrap">
  <a class="brand" href="../">Structured&nbsp;<span>Wandering</span></a>
  <a class="back" href="index.html">← The library</a>
</div></header>
<main class="wrap article">
  <p class="eyebrow">My library · a curated source</p>
  <h1>{title}</h1>
  <p class="subtitle">{meta_line}</p>
  <div class="byline">{rating}</div>
  {cover}
  <article>
  {body}
  </article>
  <div class="article-cta">
    <p class="formula-mini">Structure + Data + AI + Rules + Skills → Systems</p>
    <a class="btn" href="index.html">← The whole library</a>
    <a class="btn btn-ghost" href="https://jacovanderlaan.com">Work with Jaco →</a>
  </div>
</main>
<footer><div class="wrap">Structured Wandering — deliberate travel by
  <a href="https://jacovanderlaan.com">Jaco van der Laan</a></div></footer>
</body></html>
"""


INDEX_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>My library — Structured Wandering</title>
<meta name="description" content="The books behind the method — a curated shelf on knowledge, systems and thinking, each read through the Structure-Beats-Magic lens."/>
<meta name="author" content="Jaco van der Laan"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:title" content="My library — Structured Wandering"/>
<meta property="og:description" content="The books behind the method — a curated shelf, each read through the Structure-Beats-Magic lens."/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{canonical}"/>
<meta property="og:site_name" content="Structured Wandering"/>
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg"/>
<link rel="stylesheet" href="../assets/site.css"/>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', 'G-XXXXXXXXXX');
</script>
</head>
<body>
<header class="site"><div class="wrap">
  <a class="brand" href="../">Structured&nbsp;<span>Wandering</span></a>
  <a class="back" href="../">← Home</a>
</div></header>
<main class="wrap">
  <p class="eyebrow">My library</p>
  <h1>The books that shape how I travel.</h1>
  <p class="subtitle" style="max-width:46rem">A curated shelf, not a reading list — each one earned its place. Here's why it's in my collection, the ideas worth stealing, and where it's taken me. {count} books and counting.</p>
  {sections}
</main>
<footer><div class="wrap">Structured Wandering — deliberate travel by
  <a href="https://jacovanderlaan.com">Jaco van der Laan</a></div></footer>
</body></html>
"""


def build_jsonld_book(title, authors, meta_desc, canonical, image, year, isbn):
    data = {
        "@context": "https://schema.org", "@type": "Book",
        "name": title, "description": meta_desc, "url": canonical,
    }
    if image:
        data["image"] = image
    if authors:
        data["author"] = [{"@type": "Person", "name": a.strip()} for a in authors.split(",") if a.strip()]
    if year:
        data["datePublished"] = str(year)
    if isbn:
        data["isbn"] = isbn
    data["review"] = {"@type": "Review",
                      "author": {"@type": "Person", "name": "Jaco van der Laan", "url": "https://jacovanderlaan.com"}}
    return json.dumps(data, indent=2, ensure_ascii=False)


def _book_titles(slugs: list[str]) -> dict:
    titles = {}
    for slug in slugs:
        src = BOOKS_ROOT / slug / f"{slug}.md"
        if src.exists():
            meta, _ = split_frontmatter(src.read_text(encoding="utf-8"))
            titles[slug] = _fm_str(meta, "title") or slug
    return titles


# Privacy gate: the book source lives on W: and is scanned by the pipeline's
# check_book_privacy.py before we publish anything public. A leak (employer name,
# biographical vendor tool, own-corpus figure, decision-record id, personal name)
# in a published section aborts the build. Override with SW_SKIP_PRIVACY=1.
PRIVACY_CHECK = "W:/systems/code/scripts/books/check_book_privacy.py"


def privacy_gate(site: str) -> None:
    if os.environ.get("SW_SKIP_PRIVACY") == "1":
        print("  (privacy gate skipped via SW_SKIP_PRIVACY=1)")
        return
    import importlib.util
    if not Path(PRIVACY_CHECK).is_file():
        print(f"  ! privacy check not found ({PRIVACY_CHECK}) — proceeding WITHOUT gate")
        return
    spec = importlib.util.spec_from_file_location("check_book_privacy", PRIVACY_CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = mod.ROOTS.get(site)
    files = [str(f) for f in Path(root).glob("*/*.md")
             if f.name not in ("notes.md", "books.md")] if root and Path(root).is_dir() else []
    total = 0
    for f in sorted(files):
        hits = mod.scan_note(f)
        if hits:
            total += len(hits)
            print(f"  PRIVACY LEAK in {os.path.basename(os.path.dirname(f))}:")
            for label, match, line in hits:
                print(f"    [{label}] {match!r}  … {line[:100]}")
    if total:
        raise SystemExit(
            f"\nBUILD ABORTED: {total} private detail(s) in published book sections. "
            f"Generalize them, or set SW_SKIP_PRIVACY=1 to override.")
    print(f"  privacy gate OK ({len(files)} book pages clean)")


def prune_orphans(live_slugs: set) -> None:
    """Delete published book pages whose source no longer passes the gate. The
    generator writes but never used to clean up, so scaffold pages published under
    an older (looser) gate lingered live. Only touches books/<slug>.html (never
    index.html); git-tracked so any deletion is recoverable."""
    removed = 0
    for pg in OUT.glob("*.html"):
        if pg.name == "index.html":
            continue
        if pg.stem not in live_slugs:
            pg.unlink()
            removed += 1
    if removed:
        print(f"  - pruned {removed} orphaned book page(s) no longer passing the gate")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    slugs = discover_books()
    if not slugs:
        print("  (no books to publish — check status gate / allow-list)")
        # Deliberately do NOT prune here: a zero-result gate is ambiguous (misconfig
        # or wrong CWD), and prune-all would wipe every live page. Prune only runs
        # after a successful build with a real cards set (below).
        return
    # Site of this builder = 'systems' (SBM). Gate before writing any HTML.
    privacy_gate("systems")
    book_titles = _book_titles(slugs)
    concept_map, concept_names = _load_concept_map(), {}
    # _load_concept_map returns a list; derive slug->name for related labels
    try:
        concept_names = {slug: name for (name, slug, _pat) in concept_map}
    except Exception:
        concept_names = {}
    cards = []
    for slug in slugs:
        folder = BOOKS_ROOT / slug
        src = folder / f"{slug}.md"
        if not src.exists():
            print(f"  ! missing folder-note: {src}")
            continue
        meta, body = split_frontmatter(src.read_text(encoding="utf-8"))
        body = strip_private_sections(body)
        body = strip_html_comments(body)
        body = strip_placeholder_sections(body)
        body = autolink_concepts(body, concept_map, slug)
        title = _fm_str(meta, "title") or slug
        authors = _authors(meta)
        meta_line = _meta_line(meta)
        year = _fm_str(meta, "year")
        isbn = _fm_str(meta, "isbn")
        cluster = _fm_str(meta, "cluster")
        curated = _fm_str(meta, "curated_score")
        meta_desc = f"{title} by {authors} — why it's in Jaco van der Laan's Structure-Beats-Magic library, the ideas worth stealing, and what he built with it."[:300]
        canonical = f"{BASE_URL}/books/{slug}.html"
        cover_file = copy_cover(folder, slug)
        og_image_abs = f"{BASE_URL}/assets/{cover_file}" if cover_file else f"{BASE_URL}/assets/sbm-og-card.svg"
        cover_html = (
            f'<figure class="book-cover"><img src="../assets/{cover_file}" alt="{html.escape(title, quote=True)} cover"/></figure>'
            if cover_file else ""
        )
        stars = build_stars(meta.get("my_rating"))
        rating_html = f'<span class="book-rating" title="My rating">{stars}</span>' if stars else ""
        json_ld = build_jsonld_book(title, authors, meta_desc, canonical, og_image_abs, year, isbn)
        rendered = md_to_html(body) + build_related(meta, book_titles, concept_names)
        # Subtle AI-attribution footer, only when the page carries a Highlights section.
        if re.search(r"(?m)^## Highlights\b", body):
            rendered += ('<p class="ai-note"><em>Highlights on this page are '
                         'generated with the help of AI.</em></p>')
        (OUT / f"{slug}.html").write_text(PAGE.format(
            title=html.escape(title, quote=True),
            meta_desc=html.escape(meta_desc, quote=True),
            meta_line=html.escape(meta_line, quote=True),
            rating=rating_html, cover=cover_html,
            canonical=canonical, og_image_abs=og_image_abs, json_ld=json_ld,
            css=CSS, body=rendered,
        ), encoding="utf-8")
        print(f"  + books/{slug}.html  ({'cover' if cover_file else 'no cover'})")
        cards.append({"slug": slug, "title": title, "authors": authors, "year": year,
                      "cluster": cluster, "curated": curated, "stars": stars,
                      "cover": cover_file})

    write_library_index(cards)
    prune_orphans({c["slug"] for c in cards})


# Human-readable cluster labels (raw .title() mangles acronyms).
CLUSTER_LABELS = {
    "data-modeling": "Data modeling", "data-vault": "Data Vault",
    "data-architecture": "Data architecture", "data-engineering": "Data engineering",
    "data-warehousing": "Data warehousing", "data-quality-governance": "Data quality & governance",
    "business-rules-requirements": "Business rules & requirements", "bi-viz": "BI & visualization",
    "software-craft": "Software craft", "pkm-notes": "PKM & note-taking",
    "productivity": "Productivity", "mental-models": "Mental models",
    "business-positioning": "Business & positioning", "communication": "Communication",
    "minimalism": "Minimalism", "psychology-wellbeing": "Psychology & wellbeing",
    "learning-language": "Learning & language", "travel": "Travel",
}


def cluster_label(cluster: str) -> str:
    return CLUSTER_LABELS.get(cluster, cluster.replace("-", " ").capitalize())


def write_library_index(cards: list) -> None:
    """Write books/index.html — the SBM library landing page, grouped by cluster."""
    from collections import defaultdict
    by_cluster = defaultdict(list)
    for c in cards:
        by_cluster[c["cluster"] or "other"].append(c)

    def cur(c):
        try:
            return int(c["curated"])
        except (TypeError, ValueError):
            return 0

    sections = []
    for cluster in sorted(by_cluster):
        rows = sorted(by_cluster[cluster], key=lambda c: (-cur(c), c["title"].lower()))
        cards_html = []
        for c in rows:
            meta_bits = " · ".join(b for b in [c["authors"], str(c["year"]) if c["year"] else ""] if b)
            stars = f'<span class="book-rating">{c["stars"]}</span> ' if c["stars"] else ""
            thumb = (
                f'        <figure class="lib-thumb"><img loading="lazy" src="../assets/{c["cover"]}" '
                f'alt="{html.escape(c["title"], quote=True)} cover"/></figure>\n'
                if c.get("cover") else
                '        <figure class="lib-thumb lib-thumb--none" aria-hidden="true"></figure>\n'
            )
            cards_html.append(
                f'      <a class="lib-card" href="{c["slug"]}.html">\n'
                f'{thumb}'
                f'        <div class="lib-card-body">\n'
                f'          <h3>{html.escape(c["title"])}</h3>\n'
                f'          <p class="muted">{stars}{html.escape(meta_bits)}</p>\n'
                f'        </div>\n'
                f'      </a>'
            )
        title = cluster_label(cluster)
        sections.append(
            f'  <section class="lib-section">\n'
            f'    <h2>{html.escape(title)} <span class="muted">({len(rows)})</span></h2>\n'
            f'    <div class="lib-grid">\n' + "\n".join(cards_html) + '\n    </div>\n  </section>'
        )

    (OUT / "index.html").write_text(INDEX_PAGE.format(
        canonical=f"{BASE_URL}/books/",
        count=len(cards),
        sections="\n".join(sections),
    ), encoding="utf-8")
    print(f"  + books/index.html ({len(cards)} books, {len(by_cluster)} clusters)")


if __name__ == "__main__":
    main()

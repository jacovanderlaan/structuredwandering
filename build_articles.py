#!/usr/bin/env python3
"""
Build SBM article pages from markdown drafts -> articles/*.html + a writing index.

Source of truth = the markdown drafts (you keep writing in markdown). This script
renders them into styled static HTML that matches the hub. "A brain that publishes
itself", applied to the hub's own writing.

Usage:
    python build_articles.py
    SW_DRAFTS="W:/.../drafts" python build_articles.py   # override source

Drafts must have YAML frontmatter with at least `title`; optional `subtitle`,
`face`, `created`. Only files listed in ARTICLES (or, if empty, all dated drafts
matching the SBM series) are published — so unrelated drafts in the folder stay
private.
"""
from __future__ import annotations

import os
import re
import html
import json
import shutil
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

HERE = Path(__file__).parent
# SBM article source home. Folder-per-article (2026-07-04): each published article
# is a folder under ARTICLES_ROOT whose name is the slug, containing:
#   <slug>/<slug>.md      the folder-note = the article source (frontmatter + body)
#   <slug>/assets/*       this article's images (hero + infographics)
#   <slug>/notes|actions|comments.md   private working files (NOT published)
# The builder copies each article's assets/ into the repo assets/ at build time,
# so repo assets/ is a build output — no more hand-managed drift.
ARTICLES_ROOT = Path(os.environ.get(
    "SW_ARTICLES_ROOT",
    "W:/travel/products/structuredwandering/articles",
))
OUT = HERE / "articles"
ASSETS = HERE / "assets"

# Private-section convention: the folder-note is one markdown document. Everything
# publishes EXCEPT a fixed set of working sections at the bottom. As soon as the
# builder hits the first of these (case-insensitive ## heading), it stops
# publishing — the rest is a private notes/actions/comments summary. Mirrors the
# vault's protected manual-sections rule.
PRIVATE_SECTIONS = {"notes", "actions", "comments", "briefs"}

# Explicit allow-list of article slugs (folder names). Only these publish.
ARTICLES = [
    # Add published article slugs (folder names under ARTICLES_ROOT) here,
    # one per line, as you write them. Empty = nothing publishes yet.
    # e.g. "the-slow-route-through-portugal",
]

CSS = "../assets/article.css"

# Canonical base for sitemap URLs. DNS cutover completed 2026-06-30: the custom
# domain structurebeatsmagic.com now resolves directly to GitHub Pages (apex
# A-records 185.199.108-111.153 + www CNAME), so it is the live canonical home.
BASE_URL = os.environ.get(
    "SW_BASE_URL",
    "https://structuredwandering.com",
).rstrip("/")


def split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm_raw = text[3:end].strip()
            body = text[end + 4:].lstrip("\n")
            meta = {}
            if yaml:
                try:
                    meta = yaml.safe_load(fm_raw) or {}
                except Exception:
                    meta = {}
            return meta, body
    return {}, text


def strip_private_sections(body: str) -> str:
    """Cut the body at the first private working section.

    The folder-note is one markdown document; everything publishes except the
    trailing working sections (## Notes, ## Actions, ## Comments, ## Briefs).
    We stop at the first such ## heading so those never reach the published HTML.
    """
    lines = body.split("\n")
    for i, ln in enumerate(lines):
        st = ln.strip()
        if st.startswith("## "):
            name = st[3:].strip().rstrip(":").lower()
            if name in PRIVATE_SECTIONS:
                return "\n".join(lines[:i]).rstrip() + "\n"
    return body


def md_to_html(md: str) -> str:
    """Minimal, dependency-free markdown -> HTML for our article style.

    Supports: # ## ### headings, **bold**, *italic*, [text](url), --- rules,
    paragraphs. Deliberately small — our drafts use a narrow markdown subset.
    """
    # strip the leading H1 (we render title from frontmatter) + leading italic lede
    lines = md.split("\n")
    out: list[str] = []
    para: list[str] = []
    bullets: list[str] = []
    quote: list[str] = []  # accumulated blockquote lines (already stripped of "> ")
    table: list[str] = []  # accumulated GFM table rows (raw "| a | b |" lines)

    def flush_bullets():
        if bullets:
            items = "".join(f"<li>{inline(b)}</li>" for b in bullets)
            out.append(f"<ul>{items}</ul>")
            bullets.clear()

    def _row_cells(row: str) -> list:
        # split a "| a | b |" row into cells, ignoring the leading/trailing pipes
        s = row.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    def flush_table():
        if not table:
            return
        rows = table[:]
        table.clear()
        # a GFM table needs a header row + a separator row (|---|---|)
        is_sep = lambda r: bool(re.fullmatch(r"\s*\|?[\s:\-|]+\|?\s*", r)) and "-" in r
        header, body_rows = None, rows
        if len(rows) >= 2 and is_sep(rows[1]):
            header, body_rows = rows[0], rows[2:]
        cells_html = []
        if header is not None:
            ths = "".join(f"<th>{inline(c)}</th>" for c in _row_cells(header))
            cells_html.append(f"<thead><tr>{ths}</tr></thead>")
        trs = "".join(
            "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in _row_cells(r)) + "</tr>"
            for r in body_rows if r.strip()
        )
        cells_html.append(f"<tbody>{trs}</tbody>")
        out.append(f'<div class="table-wrap"><table>{"".join(cells_html)}</table></div>')

    def flush_quote():
        if quote:
            # group into paragraphs: a blank entry (bare ">") separates <p>s
            paras: list[list[str]] = [[]]
            for q in quote:
                if q == "":
                    if paras[-1]:
                        paras.append([])
                else:
                    paras[-1].append(q)
            body = "".join(
                f"<p>{inline(' '.join(p).strip())}</p>" for p in paras if p
            )
            out.append(f"<blockquote>{body}</blockquote>")
            quote.clear()

    def flush():
        flush_bullets()
        flush_quote()
        flush_table()
        if para:
            joined = " ".join(para).strip()
            if joined:
                out.append(f"<p>{inline(joined)}</p>")
            para.clear()

    def inline(s: str) -> str:
        # Pull inline-code spans (`code`) out first so their contents are never
        # touched by the bold/italic/link passes, then restore as <code>.
        spans: list[str] = []

        def _stash(m: "re.Match") -> str:
            spans.append(html.escape(m.group(1), quote=False))
            return f"\x00{len(spans) - 1}\x00"

        s = re.sub(r"`([^`]+)`", _stash, s)
        s = html.escape(s, quote=False)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        # Bold first (non-greedy, so a paragraph that is entirely **bold** and
        # contains *italic* inside still matches), then italic on what remains.
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        s = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{spans[int(m.group(1))]}</code>", s)
        return s

    first_h1_skipped = False
    lede_checked = False
    in_code = False
    code: list[str] = []
    for ln in lines:
        st = ln.strip()
        # fenced code block: ``` ... ``` — capture lines verbatim, preserving
        # whitespace/newlines (ASCII diagrams, CLI output). No inline formatting.
        if st.startswith("```"):
            if in_code:
                code_html = html.escape("\n".join(code), quote=False)
                out.append(f"<pre><code>{code_html}</code></pre>")
                code.clear()
                in_code = False
            else:
                flush()
                lede_checked = True
                in_code = True
            continue
        if in_code:
            code.append(ln)
            continue
        if not st:
            flush()
            continue
        if st.startswith("# ") and not first_h1_skipped:
            first_h1_skipped = True
            continue
        # Skip a leading italic lede paragraph (`*...*` on its own) right after the
        # H1 — it duplicates the frontmatter subtitle, which we render separately.
        if (first_h1_skipped and not lede_checked and not out and not para
                and st.startswith("*") and st.endswith("*")
                and not st.startswith("**")):
            lede_checked = True
            continue
        lede_checked = True
        if st == "---":
            flush()
            out.append("<hr/>")
            continue
        # figure shortcode:  [[figure: filename.png | optional caption]]
        if st.startswith("[[figure:") and st.endswith("]]"):
            flush()
            inner = st[len("[[figure:"):-2].strip()
            fn, _, cap = inner.partition("|")
            fn = fn.strip()
            cap = cap.strip()
            cap_html = f"<figcaption>{inline(cap)}</figcaption>" if cap else ""
            out.append(f'<figure class="article-fig"><img src="../assets/{fn}" '
                       f'alt="{cap or fn}" loading="lazy"/>{cap_html}</figure>')
            continue
        if st.startswith("### "):
            flush(); out.append(f"<h3>{inline(st[4:])}</h3>"); continue
        if st.startswith("## "):
            flush(); out.append(f"<h2>{inline(st[3:])}</h2>"); continue
        if st.startswith("# "):
            flush(); out.append(f"<h2>{inline(st[2:])}</h2>"); continue
        # blockquote: "> text" (consecutive lines group; a bare ">" is a paragraph
        # break inside the quote). Renders as <blockquote> — NOT a literal ">".
        if st == ">" or st.startswith("> "):
            if para:
                flush()  # close any open paragraph before the quote
            flush_bullets()
            quote.append("" if st == ">" else st[2:].strip())
            continue
        flush_quote()  # a non-quote line ends any open blockquote
        # GFM table row: a line starting with "|". Consecutive such lines group
        # into one <table>; flush_table() decides header/separator/body.
        if st.startswith("|"):
            if para:
                flush()
            flush_bullets()
            table.append(st)
            continue
        flush_table()  # a non-table line ends any open table
        # bullet list item: "- text" or "* text" (not "**bold**")
        if (st.startswith("- ") or (st.startswith("* ") and not st.startswith("**"))):
            if para:
                flush()  # close any open paragraph before starting the list
            bullets.append(st[2:].strip())
            continue
        flush_bullets()  # a non-bullet line ends any open list
        para.append(st)
    if in_code:  # unclosed fence — emit what we captured rather than drop it
        code_html = html.escape("\n".join(code), quote=False)
        out.append(f"<pre><code>{code_html}</code></pre>")
    flush()
    return "\n".join(out)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} — Structured Wandering</title>
<meta name="description" content="{subtitle}"/>
<meta name="author" content="Jaco van der Laan"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{subtitle}"/>
<meta property="og:type" content="article"/>
<meta property="og:url" content="{canonical}"/>
<meta property="og:site_name" content="Structured Wandering"/>
<meta property="og:image" content="{og_image_abs}"/>
<meta property="article:author" content="Jaco van der Laan"/>{published_meta}
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{title}"/>
<meta name="twitter:description" content="{subtitle}"/>
<meta name="twitter:image" content="{og_image_abs}"/>
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg"/>
<link rel="icon" type="image/png" sizes="32x32" href="../assets/favicon-32.png"/>
<link rel="icon" type="image/png" sizes="16x16" href="../assets/favicon-16.png"/>
<link rel="apple-touch-icon" sizes="180x180" href="../assets/favicon-180.png"/>
<link rel="stylesheet" href="{css}"/>
<script type="application/ld+json">
{json_ld}
</script>
<!-- Google Analytics (GA4) — shared property with jacovanderlaan.com -->
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
  <a class="brand" href="../">Structure&nbsp;Beats&nbsp;<span>Magic</span></a>
  <a class="back" href="../writing/">← All writing</a>
</div></header>
<main class="wrap article">
  <p class="eyebrow">{face}</p>
  <h1>{title}</h1>
  <p class="subtitle">{subtitle}</p>
  <div class="byline">By Jaco van der Laan{date}</div>
  {hero}
  <article>
  {body}
  </article>
  <div class="article-cta">
    <p class="formula-mini">Structure + Taste + Sources → Journeys worth taking</p>
    <a class="btn" href="../writing/">← More writing</a>
    <a class="btn btn-ghost" href="https://structurebeatsmagic.com">The method behind it →</a>
  </div>
</main>
<footer><div class="wrap">Structured Wandering — deliberate travel by
  <a href="https://jacovanderlaan.com">Jaco van der Laan</a></div></footer>
</body></html>
"""


def build_article_jsonld(title: str, subtitle: str, canonical: str,
                         image_abs: str, created: str) -> str:
    """Build a JSON-LD Article schema block.

    The author is a Person entity linked (via sameAs) to Jaco's other public
    profiles, so Google can unify "Jaco van der Laan" across sites and rank
    these articles for name searches. publisher = the SBM brand. datePublished
    is emitted only when known.
    """
    author = {
        "@type": "Person",
        "name": "Jaco van der Laan",
        "url": "https://jacovanderlaan.com",
        "sameAs": [
            "https://jacovanderlaan.com",
            "https://www.linkedin.com/in/jacovanderlaan",
            "https://medium.com/@jacovanderlaan",
        ],
    }
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": subtitle,
        "image": image_abs,
        "author": author,
        "publisher": {
            "@type": "Organization",
            "name": "Structured Wandering",
            "url": BASE_URL,
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "url": canonical,
    }
    if created:
        data["datePublished"] = created
        data["dateModified"] = created
    return json.dumps(data, indent=2, ensure_ascii=False)


def face_label(meta: dict) -> str:
    f = str(meta.get("face", ""))
    if f.lower().startswith("b2c"):
        return "For knowledge workers"
    if f.lower().startswith("b2b"):
        return "For builders &amp; teams"
    return "Structured Wandering"


def copy_article_assets(slug: str) -> int:
    """Copy an article folder's assets/* into the repo assets/ (build output).

    Makes repo assets/ a derived artifact — the source of truth for an article's
    images is <slug>/assets/. Returns the number of files copied.
    """
    folder = resolve_article_folder(slug)
    src_dir = (folder / "assets") if folder else None
    if not src_dir or not src_dir.is_dir():
        return 0
    ASSETS.mkdir(exist_ok=True)
    n = 0
    for f in sorted(src_dir.iterdir()):
        if f.is_file():
            shutil.copy2(f, ASSETS / f.name)
            n += 1
    return n


def resolve_article_folder(slug: str) -> Path | None:
    """Find an article's source folder by slug.

    Articles live either top-level (ARTICLES_ROOT/<slug>/) or, when part of a
    series (ADR-067), as a numbered subfolder ARTICLES_ROOT/series/*/NN_<slug>/.
    Returns the folder Path, or None if not found. Top-level wins if both exist.
    """
    top = ARTICLES_ROOT / slug
    if (top / f"{slug}.md").exists():
        return top
    series_root = ARTICLES_ROOT / "series"
    if series_root.is_dir():
        for series_dir in series_root.iterdir():
            if not series_dir.is_dir():
                continue
            for part_dir in series_dir.iterdir():
                # numbered subfolder NN_<slug>
                if part_dir.is_dir() and re.match(rf"^\d+_{re.escape(slug)}$", part_dir.name):
                    if (part_dir / f"{slug}.md").exists():
                        return part_dir
    return None


def _norm_reflist(v) -> list:
    """Normalise a frontmatter related-list to a list of plain strings/dicts."""
    if not v:
        return []
    if isinstance(v, list):
        return v
    return [v]


# URL base for linking to concept detail pages from an article's Related section.
# Concept pages are built by build_concepts.py into ./concepts/<slug>.html.
CONCEPTS_URL = "../concepts"

# Curated synonym map for inline auto-linking: variant words/phrases that should
# link to a concept page even though they aren't the concept's exact display name
# (the auto-linker matches exact names; a reader writes "atomicity", not "Atomic
# Documents"). Keyed by concept SLUG -> list of extra phrases to match. Keep this
# CONSERVATIVE and specific — only high-confidence, unambiguous variants, or the
# body turns into a sea of links. Case-insensitive, whole-word, first-mention-only
# (same rules as exact-name matching). A synonym for the article's own concept is
# skipped automatically. If a slug here doesn't exist as a concept, it's ignored.
CONCEPT_SYNONYMS = {
    "atomic-documents": ["atomicity", "atomic note", "atomic notes", "atomic unit", "atomic units"],
    "rent-the-ai-own-the-structure": ["tool-agnostic", "tool agnostic", "vendor lock-in", "vendor-agnostic"],
    "the-validation-loop": ["flag, don't guess", "flag don't guess", "validation loop"],
    "map-of-content-moc": ["map of content", "maps of content", "MOC"],
    "knowledge-graph": ["zettelkasten"],
    "the-calendar-is-the-spine": ["calendar-as-spine", "calendar as spine"],
    "derived-insight": ["derived insight", "data you never typed"],
    "the-missing-system": ["system of intelligence", "intelligence layer"],
    "the-rear-view-mirror-problem": ["rear-view mirror", "rear view mirror"],
}


def _load_concept_map() -> list:
    """Concept display-name (+ curated synonyms) -> slug, from concepts/index.html.

    Returns a list of (name, slug, compiled_pattern) sorted longest-name-first so
    a longer concept ("Structure Beats Magic") is matched before a shorter one it
    contains. Includes CONCEPT_SYNONYMS entries (variant words) pointing at the same
    slug. Empty list if the index isn't built yet (auto-linking is then a no-op).
    """
    idx = HERE / "concepts" / "index.html"
    if not idx.exists():
        return []
    txt = idx.read_text(encoding="utf-8")
    pairs = re.findall(r'href="([a-z0-9-]+)\.html">\s*<div class="c-name">([^<]+)</div>', txt)
    valid_slugs = {s for s, _ in pairs}
    # extend the (slug, phrase) pairs with curated synonyms for slugs that exist
    syn_pairs = [(slug, phrase)
                 for slug, phrases in CONCEPT_SYNONYMS.items() if slug in valid_slugs
                 for phrase in phrases]
    out = []
    # exact concept names: case-SENSITIVE (a proper-noun name; avoids "structure"
    # matching "Structure Beats Magic"). curated synonyms: case-INSENSITIVE
    # (a reader writes "atomicity" mid-sentence or at a sentence start).
    for is_syn, (slug, raw) in ([(False, p) for p in pairs] + [(True, p) for p in syn_pairs]):
        name = html.unescape(raw).strip()
        if len(name) < 3:
            continue
        # word-boundary match on the literal name; \b won't fire next to a trailing
        # '.' (e.g. "…Personalizes.") so anchor on start-boundary + optional trailing
        # word-char guard instead of a bare \b at both ends.
        flags = re.IGNORECASE if is_syn else 0
        pat = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", flags)
        out.append((name, slug, pat))
    # exact names first, then by length: an exact multi-word name beats a short
    # synonym; among same kind, the longer phrase wins.
    out.sort(key=lambda t: len(t[0]), reverse=True)
    return out


def autolink_concepts(body: str, concept_map: list, self_slug: str) -> str:
    """Link the FIRST mention of each concept name to its concept page.

    - First occurrence per concept only (kept subtle; avoids a sea of links).
    - Skips the article's own concept, fenced code, inline `code`, existing
      [markdown](links), headings, and the leading H1/italic lede.
    - Operates on the markdown body before md_to_html, emitting a normal
      [name](../concepts/slug.html) link the existing inline parser renders.
    """
    if not concept_map:
        return body
    linked: set = set()
    out_lines = []
    in_code = False
    for ln in body.split("\n"):
        st = ln.strip()
        if st.startswith("```"):
            in_code = not in_code
            out_lines.append(ln); continue
        # never touch code blocks, headings, figure/blockquote/list-marker lines
        if in_code or st.startswith(("#", ">", "[[figure:")):
            out_lines.append(ln); continue
        # protect existing inline links + `code` spans by stashing them out
        stash: list = []
        def _hold(m):
            stash.append(m.group(0)); return f"\x00{len(stash)-1}\x00"
        safe = re.sub(r"\[[^\]]+\]\([^)]+\)|`[^`]+`", _hold, ln)
        for name, slug, pat in concept_map:
            if slug in linked or slug == self_slug:
                continue
            m = pat.search(safe)
            if not m:
                continue
            safe = safe[:m.start()] + f"[{m.group(0)}]({CONCEPTS_URL}/{slug}.html)" + safe[m.end():]
            linked.add(slug)
        # restore stashed links/code
        safe = re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], safe)
        out_lines.append(safe)
    return "\n".join(out_lines)


def build_related_section(meta: dict, article_titles: dict, concept_names: dict | None = None) -> str:
    """Render a 'Related' section from article frontmatter.

    related_concepts: [<concept-slug>]        -> links to ../concepts/<slug>.html
    related_articles: [<article-slug>] or [{title,url}] -> links to sibling articles

    Concept slugs may carry the vault 'concept-' prefix; we strip it for the URL.
    The concept's real display name is used when known (concept_names: slug->name,
    from the built concepts index); otherwise we fall back to title-casing the slug.
    Unknown article slugs are skipped silently (kept out of the graph, not broken).
    """
    concept_names = concept_names or {}
    rc = _norm_reflist(meta.get("related_concepts"))
    ra = _norm_reflist(meta.get("related_articles"))
    if not rc and not ra:
        return ""
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
                if aslug in article_titles:
                    lis.append(f'<li><a href="{html.escape(aslug, quote=True)}.html">{html.escape(article_titles[aslug])}</a></li>')
        if lis:
            blocks.append(f"<h3>Related writing</h3><ul>{''.join(lis)}</ul>")
    if not blocks:
        return ""
    return f'<aside class="article-related"><h2>Related</h2>{"".join(blocks)}</aside>'


def _article_titles() -> dict:
    """slug -> title for every published article (for related_articles linking)."""
    titles = {}
    for slug in ARTICLES:
        folder = resolve_article_folder(slug)
        if folder is None:
            continue
        meta, _ = split_frontmatter((folder / f"{slug}.md").read_text(encoding="utf-8"))
        titles[slug] = str(meta.get("title", slug)).strip().strip('"')
    return titles


def main() -> None:
    OUT.mkdir(exist_ok=True)
    article_titles = _article_titles()
    concept_map = _load_concept_map()  # name -> concept page; for inline auto-linking
    # slug -> display name for the Related section. concept_map is sorted longest-
    # first and mixes exact names with synonyms; keep the FIRST (longest) as the
    # label but prefer a real (non-synonym) name — synonym phrases live in
    # CONCEPT_SYNONYMS values, so exclude those from becoming a display label.
    _synonym_phrases = {p.lower() for phrases in CONCEPT_SYNONYMS.values() for p in phrases}
    concept_names = {}
    for name, slug, _ in concept_map:
        if name.lower() in _synonym_phrases:
            continue
        concept_names.setdefault(slug, name)
    cards = []
    for slug in ARTICLES:
        folder = resolve_article_folder(slug)
        if folder is None:
            print(f"  ! missing folder-note for slug: {slug}")
            continue
        src = folder / f"{slug}.md"
        copied = copy_article_assets(slug)
        meta, body = split_frontmatter(src.read_text(encoding="utf-8"))
        body = strip_private_sections(body)
        # auto-link the first mention of each concept name to its concept page
        body = autolink_concepts(body, concept_map, slug)
        title = str(meta.get("title", slug)).strip().strip('"')
        subtitle = str(meta.get("subtitle", "")).strip().strip('"')
        created = str(meta.get("created", "")).strip().strip("'\"")
        date = f" · {created}" if created else ""
        out_path = OUT / f"{slug}.html"
        # optional hero image: frontmatter `hero_image:` (filename in assets/),
        # with optional `hero_caption:`. Rendered after the byline.
        hero = ""
        hi = str(meta.get("hero_image", "")).strip().strip("'\"")
        if hi:
            cap = str(meta.get("hero_caption", "")).strip().strip("'\"")
            cap_html = f'<figcaption>{html.escape(cap)}</figcaption>' if cap else ""
            hero = (f'<figure class="article-hero"><img src="../assets/{hi}" '
                    f'alt="{html.escape(title, quote=True)}" loading="eager"/>{cap_html}</figure>')
        # SEO: canonical URL, absolute OG image, author + publish-date metadata,
        # and JSON-LD Article schema. The canonical is what makes syndication
        # (Medium etc.) safe — it tells Google this site is the original home.
        canonical = f"{BASE_URL}/articles/{slug}.html"
        og_image_abs = (f"{BASE_URL}/assets/{hi}" if hi
                        else f"{BASE_URL}/assets/sw-og-card.svg")
        published_meta = (f'\n<meta property="article:published_time" content="{created}"/>'
                          if created else "")
        json_ld = build_article_jsonld(title, subtitle, canonical, og_image_abs, created)
        out_path.write_text(PAGE.format(
            title=html.escape(title, quote=True),
            subtitle=html.escape(subtitle, quote=True),
            face=face_label(meta),
            date=date,
            hero=hero,
            canonical=canonical,
            og_image_abs=og_image_abs,
            published_meta=published_meta,
            json_ld=json_ld,
            body=md_to_html(body) + build_related_section(meta, article_titles, concept_names),
            css=CSS,
        ), encoding="utf-8")
        print(f"  + articles/{slug}.html  ({copied} assets)")
        cards.append((created, title, subtitle, f"articles/{slug}.html", face_label(meta)))

    # write a snippet the homepage can include (manual paste or future include)
    cards.sort(reverse=True)
    snip = []
    for _d, title, subtitle, href, face in cards:
        snip.append(
            f'      <a class="post" href="{href}">'
            f'<span class="post-face">{face}</span>'
            f'<h3>{html.escape(title)}</h3>'
            f'<p>{html.escape(subtitle)}</p></a>'
        )
    (OUT / "_cards.html").write_text("\n".join(snip), encoding="utf-8")
    print(f"  + articles/_cards.html ({len(cards)} cards)")

    inject_homepage_cards(snip)

    write_writing_index(cards)

    write_sitemap(cards)


WRITING_INDEX = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Writing · Structured Wandering</title>
<meta name="description" content="Practical pieces on structure, knowledge and AI — each takes one real, working system and shows the method behind it, so you can build your own."/>
<meta name="author" content="Jaco van der Laan"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:title" content="Writing · Structured Wandering"/>
<meta property="og:description" content="Practical pieces on structure, knowledge and AI — the recipe, free."/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{canonical}"/>
<meta property="og:site_name" content="Structured Wandering"/>
<meta property="og:image" content="{og_image_abs}"/>
<meta name="twitter:card" content="summary_large_image"/>
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg"/>
<link rel="stylesheet" href="{css}"/>
<!-- Google Analytics (GA4) — shared property with jacovanderlaan.com -->
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
  <a class="brand" href="../">Structure&nbsp;Beats&nbsp;<span>Magic</span></a>
  <a class="back" href="../">← Home</a>
</div></header>

<div class="hero wrap">
  <div class="eyebrow">Writing</div>
  <h1>Practical pieces on structure, knowledge &amp; AI</h1>
  <p class="lede">The recipe, free. Each piece takes one real, working system and shows the method behind it — so you can build your own. Newest first.</p>
</div>

<section id="writing">
  <div class="wrap">
    <div class="posts">
{cards}
    </div>
  </div>
</section>

<footer><div class="wrap">Structured Wandering — deliberate travel by
  <a href="https://jacovanderlaan.com">Jaco van der Laan</a></div></footer>
</body></html>
"""


def write_writing_index(cards: list) -> None:
    """Write a standalone writing/index.html — the collection page for all
    articles (ADR-078: collections are their own pages, not homepage anchors).
    Source of truth is the same `cards` list that feeds the homepage teaser and
    the sitemap; here it becomes a rankable page with its own <title>/canonical.
    One level deep, so article hrefs (articles/...) get a ../ prefix."""
    out_dir = HERE / "writing"
    out_dir.mkdir(exist_ok=True)
    rows = []
    for _d, title, subtitle, href, face in cards:  # already sorted newest-first
        rows.append(
            f'      <a class="post" href="../{href}">'
            f'<span class="post-face">{html.escape(face)}</span>'
            f'<h3>{html.escape(title)}</h3>'
            f'<p>{html.escape(subtitle)}</p></a>'
        )
    page = WRITING_INDEX.format(
        canonical=f"{BASE_URL}/writing/",
        og_image_abs=f"{BASE_URL}/assets/sw-og-card.svg",
        css="../assets/site.css",
        cards="\n".join(rows),
    )
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    print(f"  + writing/index.html ({len(cards)} articles)")


# The homepage is a manifest (ADR-078): it teases the newest writing and links
# to the full collection at /writing/. Cap the homepage cards to this many.
HOMEPAGE_TEASER_COUNT = 9


def inject_homepage_cards(snip: list) -> None:
    """Inject a teaser of the freshly-built article cards into index.html.

    The homepage used to carry a hand-maintained copy of the full card list,
    which drifted out of sync. Now the cards live in exactly one place — the
    article frontmatter — and the newest HOMEPAGE_TEASER_COUNT are projected
    into the homepage at build time between the ARTICLE-CARDS:START/END markers,
    followed by an "All writing →" link to the full /writing/ collection page.
    Same one-source, one-direction rule the site argues for. No markers -> no-op.
    """
    index = OUT.parent / "index.html"
    if not index.exists():
        return
    html_txt = index.read_text(encoding="utf-8")
    start = "<!-- ARTICLE-CARDS:START"
    end = "<!-- ARTICLE-CARDS:END -->"
    i = html_txt.find(start)
    j = html_txt.find(end)
    if i == -1 or j == -1 or j < i:
        print("  ! index.html: ARTICLE-CARDS markers not found — homepage cards NOT updated")
        return
    teaser = snip[:HOMEPAGE_TEASER_COUNT]
    more_link = ('      <a class="post post-more" href="writing/">'
                 '<span class="post-face">All writing</span>'
                 f'<h3>See all {len(snip)} pieces →</h3>'
                 '<p>The full collection — structure, knowledge and AI, newest first.</p></a>')
    # keep the START marker comment line intact, replace everything up to END
    start_line_end = html_txt.find("-->", i) + len("-->")
    block = (
        html_txt[i:start_line_end]
        + "\n" + "\n".join(teaser) + "\n" + more_link + "\n      "
        + end
    )
    new_html = html_txt[:i] + block + html_txt[j + len(end):]
    if new_html != html_txt:
        index.write_text(new_html, encoding="utf-8")
        print(f"  + index.html (injected {len(snip)} homepage cards)")
    else:
        print("  = index.html (cards already current)")


def write_sitemap(cards: list) -> None:
    """Regenerate sitemap.xml from the published pages, so it stays current.

    Lists the hub + section pages + every published article. Excludes 404.html
    and the _cards.html fragment. Article lastmod uses its `created` date.
    """
    # known article lastmod by relative href
    art_dates = {href: (d or "") for d, _t, _s, href, _f in cards}
    urls: list[tuple[str, str]] = []  # (relative path, lastmod)

    # top-level + collection/section pages (no reliable date -> omit lastmod).
    # Only list sections that actually exist on this site (extend as it grows).
    for rel in ["", "writing/"]:
        urls.append((rel, ""))

    # published articles, sorted newest first
    for href in sorted(art_dates, key=lambda h: art_dates[h], reverse=True):
        urls.append((href, art_dates[href]))

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for rel, lastmod in urls:
        loc = f"{BASE_URL}/{rel}" if rel else f"{BASE_URL}/"
        parts.append("  <url>")
        parts.append(f"    <loc>{html.escape(loc)}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{html.escape(lastmod)}</lastmod>")
        parts.append("  </url>")
    parts.append("</urlset>")
    (HERE / "sitemap.xml").write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"  + sitemap.xml ({len(urls)} urls, base {BASE_URL})")


if __name__ == "__main__":
    main()

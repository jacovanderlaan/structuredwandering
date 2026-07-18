#!/usr/bin/env python3
"""
Build Structured Wandering's /sources/ and /method/ pages from the public
sources register -> sources/index.html + method/index.html.

    W:/travel/products/structuredwandering/sources/sources.md   (publication view)
          |  build_sources.py  (THIS FILE)
          v
    structuredwandering.com/sources/  +  /method/

The register on W: is the publication VIEW, not the brain: the full curated-
sources register (W:/travel/curated-sources/, 38 sources incl. the ones we
evaluated and passed on) stays private. Only sources listed in the "Trusted
sources" section of sources.md are rendered — being curated internally is not
the same as being recommended publicly.

PRIVACY GATE (mirrors the how-we-decide-who-to-trust publish_prep gate): the
build refuses to ship if the rendered HTML contains private profile markers —
ages, the travel window, shortlist terms. Verdicts must describe the OPERATOR,
never the travellers.

PUBLISH GATE: sources.md frontmatter `status: draft` builds only with --draft.
Flip to `status: active` to build by default.

Usage:
    python build_sources.py             # build when status: active
    python build_sources.py --draft     # build regardless (preview)
    SW_SOURCES_MD=... python build_sources.py
"""
from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
SRC = Path(os.environ.get(
    "SW_SOURCES_MD",
    "W:/travel/products/structuredwandering/sources/sources.md"))
BASE_URL = os.environ.get("SW_BASE_URL", "https://structuredwandering.com").rstrip("/")

# Words that must never appear in the rendered pages (privacy gate). Lowercase.
# NOTE: "jaco" as byline/footer author is public by design — the gate guards
# PROFILE details (who travels, when, what's on the list), not authorship.
PRIVATE_MARKERS = [
    "annemarie", "~59", "shortlist", "august window", "augustus",
    "ensuite: yes", "wishlist", "travel window", "comfortregel", "comfort rule",
]


def split_frontmatter(text: str) -> tuple[dict, str]:
    meta: dict = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for ln in text[3:end].strip().split("\n"):
                if ":" in ln and not ln.startswith(" "):
                    k, v = ln.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            return meta, text[end + 4:].lstrip("\n")
    return meta, text


def parse_register(md: str) -> tuple[list[dict], list[dict], str, str]:
    """-> (steps, groups, why_html, caveat_html)
    groups = [{title, sources: [{name, url, best_for, why}]}]"""
    # --- method copy ---
    def section(title: str) -> str:
        m = re.search(rf"### {re.escape(title)}\n(.*?)(?=\n###|\n## )", md, re.S)
        return m.group(1).strip() if m else ""

    why = section("Why we curate")
    caveat = section("The honest caveat")

    steps: list[dict] = []
    steps_md = section("The steps")
    for m in re.finditer(r"^\d+\.\s+\*\*(.+?)\*\*\s+—\s+(.*?)(?=^\d+\.|\Z)",
                         steps_md, re.S | re.M):
        steps.append({"name": m.group(1).strip(),
                      "text": re.sub(r"\s+", " ", m.group(2)).strip()})

    # --- trusted sources, grouped by ### heading ---
    # Each bullet: - **Name** — url: X — best_for: "…" — why: "…"
    #   [— reviews: "…"] [— comfort: "…"]  (last two optional, any order)
    def field(bullet: str, key: str) -> str:
        m = re.search(rf'{key}:\s*"(.*?)"', bullet, re.S)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    trusted = re.search(r"## Trusted sources.*?\n(.*?)(?=\n## |\Z)", md, re.S)
    groups: list[dict] = []
    if trusted:
        for gm in re.finditer(r"### (.+?)\n(.*?)(?=\n### |\Z)", trusted.group(1), re.S):
            sources = []
            for bm in re.finditer(
                    r"- \*\*(.+?)\*\*\s+—\s+url:\s*(\S+)\s+—\s+(.*?)(?=\n- \*\*|\Z)",
                    gm.group(2), re.S):
                rest = bm.group(3)
                bf = field(rest, "best_for")
                if not bf:  # a bullet without best_for isn't a source line
                    continue
                sources.append({
                    "name": bm.group(1).strip(),
                    "url": bm.group(2).strip().rstrip(".,"),
                    "best_for": bf,
                    "why": field(rest, "why"),
                    "reviews": field(rest, "reviews"),
                    "comfort": field(rest, "comfort"),
                })
            if sources:
                groups.append({"title": gm.group(1).strip(), "sources": sources})
    return steps, groups, why, caveat


def esc(s: str) -> str:
    return html.escape(s, quote=False)


def paras(text: str) -> str:
    """Markdown-ish paragraphs -> <p>, with *italic* and **bold**."""
    out = []
    for p in re.split(r"\n\s*\n", text.strip()):
        p = esc(re.sub(r"\s+", " ", p).strip())
        p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
        p = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", p)
        out.append(f"<p>{p}</p>")
    return "\n".join(out)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} — Structured Wandering</title>
<meta name="description" content="{description}"/>
<meta name="author" content="Jaco van der Laan"/>
<link rel="canonical" href="{canonical}"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{description}"/>
<meta property="og:type" content="website"/>
<meta property="og:url" content="{canonical}"/>
<meta property="og:site_name" content="Structured Wandering"/>
<meta name="twitter:card" content="summary"/>
<meta name="twitter:title" content="{title}"/>
<meta name="twitter:description" content="{description}"/>
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg"/>
<link rel="stylesheet" href="../assets/site.css"/>
<style>
  .tight {{ padding: 2.5rem 0 3.5rem; }}
  .source-card {{ border:1px solid var(--line,#e2e8f0); border-radius:12px;
    padding:1.1rem 1.3rem; margin:0 0 1rem; background:#fff; }}
  .source-card h3 {{ margin:0 0 .35rem; font-size:1.15rem; }}
  .source-card h3 a {{ text-decoration:none; }}
  .source-card h3 a:hover {{ text-decoration:underline; }}
  .source-best {{ margin:.15rem 0; color:var(--ink-soft,#475569); font-size:.95rem; }}
  .source-why {{ margin:.35rem 0; }}
  .source-meta {{ margin:.25rem 0 0; font-size:.85rem; color:var(--ink-faint,#64748b); }}
  .source-label {{ display:inline-block; min-width:4.2rem; font-weight:600;
    color:var(--ink,#0f172a); text-transform:uppercase; letter-spacing:.03em;
    font-size:.72rem; }}
  .method-steps li {{ margin:0 0 .8rem; line-height:1.6; }}
</style>
</head>
<body>
<header class="site"><div class="wrap">
  <a class="brand" href="../">Structured&nbsp;Wandering</a>
  <a class="back" href="../">← Home</a>
</div></header>

<section class="hero"><div class="wrap" style="max-width:760px">
  <p class="eyebrow">{eyebrow}</p>
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
</div></section>

<section class="tight"><div class="wrap" style="max-width:760px">
{body}
</div></section>

<footer class="site"><div class="wrap">
  <p>© Jaco van der Laan · <a href="../">structuredwandering.com</a> ·
     built from a structured brain, published one way</p>
</div></footer>
</body>
</html>
"""


def render_method(steps, why, caveat) -> str:
    body = ['<h2>Why we curate</h2>', paras(why), '<h2>The steps</h2>', '<ol class="method-steps">']
    for s in steps:
        body.append(f'<li><strong>{esc(s["name"])}</strong> — {esc(s["text"])}</li>')
    body.append('</ol>')
    body.append('<h2>The honest caveat</h2>')
    body.append(paras(caveat))
    body.append('<p class="method-links">'
                '<a href="../sources/">See the sources this produced →</a><br/>'
                '<a href="../articles/how-we-decide-who-to-trust.html">Read the full story: How We Decide Who to Trust →</a>'
                '</p>')
    return PAGE.format(
        title="How we curate",
        description="Why Structured Wandering curates its travel sources deliberately, and the four steps: collect, score, decide, revisit.",
        canonical=f"{BASE_URL}/method/",
        eyebrow="The method",
        h1="How we curate",
        lead="Deliberately chosen sources beat an algorithm's firehose. Here's the door policy.",
        body="\n".join(body),
    )


def render_sources(groups) -> str:
    body = []
    total = sum(len(g["sources"]) for g in groups)
    body.append(paras(
        "These are the sources that cleared our bar — weighed against a written "
        "taste rubric, decided by a human, revisited on a rhythm. The full register "
        "is larger: it also holds the sources we evaluated and passed on, and that "
        "judgement stays private. Listing here is a recommendation; see "
        "*[how we curate](../method/)* for the method."))
    for g in groups:
        body.append(f'<h2>{esc(g["title"])}</h2>')
        for s in g["sources"]:
            meta_rows = ""
            if s.get("reviews"):
                meta_rows += (f'<p class="source-meta"><span class="source-label">Reviews</span> '
                              f'{esc(s["reviews"])}</p>')
            if s.get("comfort"):
                meta_rows += (f'<p class="source-meta"><span class="source-label">Comfort</span> '
                              f'{esc(s["comfort"])}</p>')
            body.append(
                f'<div class="source-card">'
                f'<h3><a href="{html.escape(s["url"], quote=True)}" rel="noopener">{esc(s["name"])}</a></h3>'
                f'<p class="source-best"><strong>Best for:</strong> {esc(s["best_for"])}</p>'
                f'<p class="source-why">{esc(s["why"])}</p>'
                f'{meta_rows}'
                f'</div>')
    # honest-links note (no affiliate mappings exist yet)
    body.append(paras(
        "Every link above goes straight to the source's own site. No affiliate "
        "arrangements exist for any of them today; if that ever changes it will "
        "be disclosed here, per link."))
    return PAGE.format(
        title=f"Sources we trust ({total})",
        description="The travel operators, walking specialists and editorial guides that cleared Structured Wandering's curation bar — and why.",
        canonical=f"{BASE_URL}/sources/",
        eyebrow="Curated sources",
        h1="Sources we trust",
        lead="Chosen deliberately, weighed for taste, revisited on a rhythm — not aggregated blindly.",
        body="\n".join(body),
    )


def privacy_check(pages: dict[str, str]) -> list[str]:
    hits = []
    for name, htm in pages.items():
        low = htm.lower()
        for marker in PRIVATE_MARKERS:
            if marker in low:
                hits.append(f"{name}: contains private marker '{marker}'")
    return hits


def main() -> None:
    draft_ok = "--draft" in sys.argv
    if not SRC.is_file():
        raise SystemExit(f"source register not found: {SRC}")
    meta, body = split_frontmatter(SRC.read_text(encoding="utf-8"))
    status = (meta.get("status") or "draft").lower()
    if status != "active" and not draft_ok:
        raise SystemExit(
            f"sources register is status:{status} — publish gate holds. "
            f"Flip to 'status: active' in {SRC.name}, or preview with --draft.")

    steps, groups, why, caveat = parse_register(body)
    if not groups:
        raise SystemExit("no trusted sources parsed — check the bullet format in sources.md")
    if not steps:
        raise SystemExit("no method steps parsed — check '### The steps' in sources.md")

    pages = {
        "method/index.html": render_method(steps, why, caveat),
        "sources/index.html": render_sources(groups),
    }
    problems = privacy_check(pages)
    if problems:
        for p in problems:
            print(f"  ! PRIVACY GATE: {p}")
        raise SystemExit("privacy gate failed — nothing written.")

    for rel, htm in pages.items():
        out = HERE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(htm, encoding="utf-8")
    n = sum(len(g["sources"]) for g in groups)
    print(f"  /method/ ({len(steps)} steps) + /sources/ ({n} sources in {len(groups)} groups) -> built")
    if status != "active":
        print("  NOTE: register is still status:draft — built via --draft, do not deploy.")


if __name__ == "__main__":
    main()

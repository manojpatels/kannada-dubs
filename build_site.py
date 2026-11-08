"""Build the public website into ./site from the same data the dashboard uses.

    python3 build_site.py

Pages: home (all films), one page per original language, report form, about,
plus sitemap.xml, robots.txt and CSV/JSON downloads. Everything is plain HTML,
so the lists are readable by search engines without running JavaScript.
Settings (site address, Formspree form ID) live in site_config.json.
"""
import csv
import html
import json
import os
import re
import shutil
from datetime import date

import dashboard_export as data

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "site")
CONFIG = json.load(open(os.path.join(HERE, "site_config.json"), encoding="utf-8"))
SITE = CONFIG["site_url"].rstrip("/")
TODAY = date.today().isoformat()

LANGS = {   # page slug, page heading, colour (same as the dashboard)
    "English":   ("english",   "Hollywood and English movies dubbed in Kannada", "#2F5D8A"),
    "Hindi":     ("hindi",     "Hindi movies dubbed in Kannada",                "#D8792A"),
    "Telugu":    ("telugu",    "Telugu movies dubbed in Kannada",               "#F2C200"),
    "Tamil":     ("tamil",     "Tamil movies dubbed in Kannada",                "#B3122E"),
    "Malayalam": ("malayalam", "Malayalam movies dubbed in Kannada",            "#3E8E6E"),
}
ISO = {"English": "en", "Hindi": "hi", "Telugu": "te", "Tamil": "ta", "Malayalam": "ml"}
e = html.escape


def clean_title(t):
    return re.sub(r"\s*\((?:\d{4} )?(?:[\w-]+ )*film\)$", "", t)


def names(s, n=4):
    return [x.strip() for x in (s or "").split(";") if x.strip()][:n]


def sort_key(r):
    return (-(int(r["year"]) if r["year"].isdigit() else 0), clean_title(r["title"]).lower())


# ---------------------------------------------------------------- page pieces
def head(title, desc, path, extra=""):
    url = SITE + path
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(CONFIG['site_name'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#F6F7F4">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anek+Kannada:wdth,wght@75..125,300..800&display=swap">
<link rel="stylesheet" href="/style.css">
{extra}</head>
<body>
<a class="skip" href="#main">Skip to the list</a>
<div class="wrap">
<nav class="top" aria-label="Site">{nav(path)}</nav>
"""


def nav(path):
    items = [("/", "All films")] + [(f"/{s}/", l) for l, (s, _, _) in LANGS.items()] + [("/about/", "About"), ("/report/", "Report")]
    cur = ' aria-current="page"'
    return "".join(f'<a href="{p}"{cur if p == path else ""}>{n}</a>' for p, n in items)


def masthead(h1, lede, sub="", small=False):
    """Same masthead as the dashboard: ಕನ್ನಡ with the last letter in red over a yellow rule."""
    return f"""<header class="mast{' small' if small else ''}">
  <a class="kn" href="/" lang="kn" aria-label="Kannada Dubbed Movies, home">ಕನ್ನ<span>ಡ</span></a>
  <div>
    <h1>{e(h1)}</h1>
    <p>{lede}</p>{f'{chr(10)}    <p class="kn-sub" lang="kn">{sub}</p>' if sub else ''}
  </div>
</header>
"""


DARK = {"#B3122E", "#2F5D8A", "#3E8E6E"}


def split_bar(by_lang, mode, current=None):
    """The dashboard's language bar. mode='filter' -> buttons; mode='link' -> links to language pages."""
    counts = {l: len([r for r in by_lang[l] if not r["unconfirmed"]]) for l in LANGS}
    total = sum(counts.values()) or 1
    bar, legend = [], []
    for l, (slug, _, colour) in LANGS.items():
        w = counts[l] / total * 100
        fg = "#fff" if colour in DARK else "#1B2230"
        label = f"{l}<span>{counts[l]} films</span>" if w > 4 else ""
        style = f'style="flex:{w:.2f} 1 0;background:{colour};color:{fg}"'
        if mode == "filter":
            bar.append(f'<button type="button" {style} data-filter="{l}" aria-pressed="false" title="{l}: {counts[l]}">{label}</button>')
            legend.append(f'<button type="button" data-filter="{l}" aria-pressed="false"><i style="background:{colour}"></i>{l} {counts[l]}</button>')
        else:
            cur = ' aria-current="page"' if l == current else ""
            bar.append(f'<a href="/{slug}/" {style}{cur} title="{l}: {counts[l]}">{label}</a>')
            legend.append(f'<a href="/{slug}/"{cur}><i style="background:{colour}"></i>{l} {counts[l]}</a>')
    group = 'role="group" aria-label="Filter by original language"' if mode == "filter" else 'aria-label="Original languages"'
    return f"""<section class="split">
  <h2>By original language</h2>
  <div class="bar" {group}>{''.join(bar)}</div>
  <div class="legend">{''.join(legend)}</div>
</section>
"""


def foot():
    return f"""</div>
<footer class="site">
  <p>Every film is listed with the source that shows its Kannada version. This site lists where films were released. It doesn't host or link to copies of films.</p>
  <p>Sentences credited to Wikipedia are quoted under <a href="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA 4.0</a>. The full list is free to download as <a href="/data/kannada-dubbed-movies.csv">CSV</a> or <a href="/data/kannada-dubbed-movies.json">JSON</a> under the same licence.</p>
  <p><a href="/about/">How this list is made</a> · <a href="/report/">Report a mistake or a missing film</a> · Updated {TODAY}</p>
</footer>
<script src="/app.js" defer></script>
</body>
</html>
"""


def film_row(r):
    t = clean_title(r["title"])
    people = []
    if r["director"]:
        people.append(f'<span class="who">Directed by {e(", ".join(names(r["director"], 2)))}</span>')
    if r["starring"]:
        people.append(f'<span class="who">With {e(", ".join(names(r["starring"])))}</span>')
    srcs = ", ".join(f'<a href="{e(s["url"])}" rel="nofollow noopener">{e(s["name"])}</a>'
                     for s in r["sources"] if s.get("url"))
    tag = f'<span class="tag">{e(r["release_type"])}</span>' if r.get("release_type") else ""
    if r["unconfirmed"]:
        tag = '<span class="flag-tag">Not confirmed</span>' + tag
    report = f'/report/?film={e(t)}&amp;year={e(r["year"])}'
    search = " ".join([t, r["director"], r["starring"]]).lower()
    return f"""<tr data-search="{e(search)}" data-year="{e(r['year'] or '0')}" data-title="{e(t.lower())}">
<td class="yr">{e(r['year']) or '—'}</td>
<th scope="row" class="film">{e(t)}</th>
<td class="people">{''.join(people) or '<span class="who">—</span>'}</td>
<td class="proof">{tag}{e(r['evidence'])}<span class="src">Source: {srcs}</span><a class="report-link" href="{report}">Report a problem</a></td>
</tr>"""


def table(rows, caption):
    body = "\n".join(film_row(r) for r in rows)
    return f"""<table>
<caption class="vh">{e(caption)}</caption>
<thead><tr><th scope="col">Year</th><th scope="col">Film</th><th scope="col">Director and cast</th><th scope="col">Kannada version</th></tr></thead>
<tbody>
{body}
</tbody>
</table>"""


def lang_section(lang, rows, heading_level="h2", show_heading=True):
    slug, heading, colour = LANGS[lang]
    done = sorted([r for r in rows if not r["unconfirmed"]], key=sort_key)
    maybe = sorted([r for r in rows if r["unconfirmed"]], key=sort_key)
    out = [f'<section class="group lang" id="{slug}" data-lang="{lang}" style="--c:{colour}">']
    if show_heading:
        out.append(f'<{heading_level}><i></i><a href="/{slug}/">{e(heading)}</a> <em>{len(done)} films</em></{heading_level}>')
    else:
        out.append(f'<{heading_level}><i></i>{len(done)} films <em>newest first</em></{heading_level}>')
    out.append(table(done, heading))
    if maybe:
        out.append(f"""<details class="maybe"><summary>Announced, not yet confirmed ({len(maybe)})</summary>
<p>A Kannada version of these films was planned or announced, but no source we found confirms it came out. If you know it did, <a href="/report/">tell us where</a>.</p>
{table(maybe, heading + ', announced')}</details>""")
    out.append("</section>")
    return "\n".join(out)


def search_box():
    return """<div class="controls" role="search">
  <input id="q" type="search" autocomplete="off" placeholder="Search title, director or cast" aria-label="Search films">
  <label>Sort <select id="sort">
    <option value="year-desc">Newest first</option>
    <option value="year-asc">Oldest first</option>
    <option value="title">Title A–Z</option>
  </select></label>
  <button class="clear" id="clear" type="button" hidden>Clear filters</button>
</div>
<p id="count" class="count" aria-live="polite"></p>"""


def item_list(rows, name):
    items = []
    for i, r in enumerate(sorted(rows, key=sort_key), 1):
        m = {"@type": "Movie", "name": clean_title(r["title"])}
        if r["year"].isdigit():
            m["dateCreated"] = r["year"]
        if r["director"]:
            m["director"] = [{"@type": "Person", "name": n} for n in names(r["director"], 2)]
        if r["starring"]:
            m["actor"] = [{"@type": "Person", "name": n} for n in names(r["starring"])]
        if r["lang"] in ISO:
            m["inLanguage"] = ISO[r["lang"]]
        items.append({"@type": "ListItem", "position": i, "item": m})
    ld = {"@context": "https://schema.org", "@type": "ItemList", "name": name,
          "numberOfItems": len(items), "itemListElement": items}
    return '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n"


def breadcrumbs(trail):
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i, "name": n, "item": SITE + p} for i, (n, p) in enumerate(trail, 1)]}
    return '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>\n"


# ---------------------------------------------------------------- pages
def write(path, text):
    full = os.path.join(OUT, path.strip("/"), "index.html") if not path.endswith(".html") else os.path.join(OUT, path.strip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def home(rows, by_lang):
    confirmed = [r for r in rows if not r["unconfirmed"]]
    n = len(confirmed)
    counts = ", ".join(f"{len([r for r in by_lang[l] if not r['unconfirmed']])} {l}" for l in LANGS)
    title = f"Kannada Dubbed Movies: Full List of {n} Films by Language"
    desc = (f"{n} films dubbed into Kannada from English, Hindi, Telugu, Tamil and Malayalam, "
            f"each with a source for its Kannada release in theatres or on OTT.")
    site_ld = ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "WebSite", "name": CONFIG["site_name"],
        "alternateName": "ಕನ್ನಡಕ್ಕೆ ಡಬ್ ಆದ ಚಿತ್ರಗಳು", "url": SITE + "/", "inLanguage": "en"},
        ensure_ascii=False) + "</script>\n")
    sections = "\n".join(lang_section(l, by_lang[l]) for l in LANGS)
    page = head(title, desc, "/", site_ld + item_list(confirmed, "Movies dubbed in Kannada")) + masthead(
        "Movies dubbed into Kannada",
        f"{n} films first made in English, Hindi, Telugu, Tamil or Malayalam that came out in a Kannada version, "
        "in theatres or on streaming. Each one links to the source that shows it.",
        "ಕನ್ನಡಕ್ಕೆ ಡಬ್ ಆದ ಚಿತ್ರಗಳ ಪಟ್ಟಿ") + split_bar(by_lang, "filter") + f"""<main id="main">
{search_box()}
{sections}
<p id="none" class="none" hidden>No film matches that search. <a href="/report/">Tell us about a missing film.</a></p>
</main>
""" + foot()
    write("/", page)


def lang_page(lang, rows, by_lang):
    slug, heading, colour = LANGS[lang]
    confirmed = [r for r in rows if not r["unconfirmed"]]
    n = len(confirmed)
    recent = " and ".join(clean_title(r["title"]) for r in sorted(confirmed, key=sort_key)[:2])
    short = "Hollywood movies dubbed in Kannada" if lang == "English" else heading
    title = f"{short[0].upper() + short[1:]}: Full List ({n} Films)"
    desc = f"All {n} {lang} films with a Kannada version, including {recent}, with year, cast and a source for each."
    ld = item_list(confirmed, heading) + breadcrumbs([("Home", "/"), (heading, f"/{slug}/")])
    page = head(title, desc, f"/{slug}/", ld) + masthead(
        heading[0].upper() + heading[1:],
        f"{n} {lang} films that came out in a Kannada version, each with the source that shows it.",
        small=True) + split_bar(by_lang, "link", lang) + f"""<main id="main">
{search_box()}
{lang_section(lang, rows, show_heading=False)}
<p id="none" class="none" hidden>No film matches that search. <a href="/report/">Tell us about a missing film.</a></p>
</main>
""" + foot()
    write(f"/{slug}/", page)


def report_page():
    fid = CONFIG.get("formspree_id", "").strip()
    action = f"https://formspree.io/f/{fid}" if fid else ""
    note = "" if fid else '<p class="warn">The form isn\'t connected yet, so submissions won\'t be delivered.</p>'
    opts = "".join(f"<option>{l}</option>" for l in LANGS) + "<option>Other</option>"
    page = head("Report a mistake or a missing Kannada dubbed film",
                "Tell us about a film listed by mistake, wrong details, or a film dubbed into Kannada that's missing from the list.",
                "/report/") + masthead("Report a mistake or a missing film",
                "Every report is checked against a source before the list changes. A link to a news report, "
                "a streaming page or a Wikipedia article helps us confirm it quickly.", small=True) + f"""<main id="main" class="page">
{note}
<form id="report" method="POST" action="{action}">
  <fieldset>
    <legend>What would you like to report?</legend>
    <label class="opt"><input type="radio" name="type" value="Missing film" required> A film dubbed into Kannada is missing</label>
    <label class="opt"><input type="radio" name="type" value="Listed by mistake"> A film is listed by mistake</label>
    <label class="opt"><input type="radio" name="type" value="Wrong details"> A film's details are wrong</label>
    <label class="opt"><input type="radio" name="type" value="Other"> Something else</label>
  </fieldset>
  <label for="film">Film title</label>
  <input id="film" name="film" required maxlength="200">
  <div class="pair">
    <div><label for="year">Year</label><input id="year" name="year" inputmode="numeric" maxlength="4" pattern="[0-9]{{4}}"></div>
    <div><label for="lang">Original language</label><select id="lang" name="original_language"><option value="">Not sure</option>{opts}</select></div>
  </div>
  <label for="link">Link to a source <span class="opt-note">(optional)</span></label>
  <input id="link" name="source_link" type="url" placeholder="https://">
  <label for="details">Details</label>
  <textarea id="details" name="details" rows="5" maxlength="2000" required placeholder="For example: released in Kannada on Netflix on 9 July 2026."></textarea>
  <label for="email">Your email <span class="opt-note">(optional, only if you'd like a reply)</span></label>
  <input id="email" name="email" type="email" autocomplete="email">
  <input type="text" name="_gotcha" class="vh" tabindex="-1" autocomplete="off" aria-hidden="true">
  <button type="submit">Send report</button>
  <p id="status" role="status"></p>
</form>
</main>
""" + foot()
    write("/report/", page)


def about_page(rows):
    n = len([r for r in rows if not r["unconfirmed"]])
    page = head("How the Kannada dubbed movies list is made",
                "Where the list of films dubbed into Kannada comes from, how each entry is checked, and how often it updates.",
                "/about/") + masthead("How this list is made",
                f"The list has {n} confirmed films. A film is included only when a source says its Kannada "
                "version was released in theatres or on a streaming service.", small=True) + f"""<main id="main" class="page">
<h2>Where the films come from</h2>
<p>Most entries come from Wikipedia. A script reads every film article that uses Wikipedia's film infobox and keeps those that say the film was dubbed into, or released in, Kannada. Others come from news reports of theatrical and streaming releases, and from the language listings on Sacnilk. Films first made in Kannada, or shot in Kannada alongside another language, aren't included.</p>
<h2>How entries are checked</h2>
<p>Each film shows the sentence that puts it on the list and links to where that sentence comes from. When a source only says a Kannada version was planned or announced, the film goes under "Announced, not yet confirmed" until another source confirms it. Duplicate spellings of the same film are merged, keeping every source.</p>
<h2>How often it updates</h2>
<p>A scheduled job checks Wikipedia and streaming news every week. New Wikipedia matches are added automatically; news reports are checked by hand before they're added.</p>
<h2>Dubbing into Kannada</h2>
<p>For decades the Kannada film industry kept an informal ban on dubbed films. In 2017 the Competition Commission of India ruled that dubbed films can't be blocked, and Fast &amp; Furious 8 was released in Kannada as one of the first in over four decades. Since 2020, streaming services have added Kannada audio to many Telugu, Tamil, Malayalam, Hindi and Hollywood films.</p>
<p>Spotted a mistake? <a href="/report/">Report it here</a>.</p>
</main>
""" + foot()
    write("/about/", page)


def not_found():
    page = head("Page not found", "This page doesn't exist.", "/404.html") + masthead(
        "Page not found", 'This page doesn\'t exist. <a href="/">Go to the full list</a> and search for a film there.',
        small=True) + """<main id="main" class="page"></main>
""" + foot()
    write("/404.html", page.replace('<link rel="canonical" href="' + SITE + '/404.html">\n', ""))


def downloads(rows):
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    cols = ["title", "year", "original_language", "director", "starring", "status", "evidence", "sources"]
    out = []
    for r in sorted(rows, key=lambda r: (r["lang"], sort_key(r))):
        out.append({"title": clean_title(r["title"]), "year": r["year"], "original_language": r["lang"],
                    "director": r["director"], "starring": r["starring"],
                    "status": "announced" if r["unconfirmed"] else "confirmed", "evidence": r["evidence"],
                    "sources": " | ".join(s["url"] for s in r["sources"] if s.get("url"))})
    with open(os.path.join(OUT, "data", "kannada-dubbed-movies.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    with open(os.path.join(OUT, "data", "kannada-dubbed-movies.json"), "w", encoding="utf-8") as fh:
        json.dump({"updated": TODAY, "licence": "CC BY-SA 4.0", "films": out}, fh, ensure_ascii=False, indent=1)


def seo_files():
    paths = ["/"] + [f"/{s}/" for s, _, _ in LANGS.values()] + ["/about/", "/report/"]
    urls = "\n".join(f"  <url><loc>{SITE}{p}</loc><lastmod>{TODAY}</lastmod></url>" for p in paths)
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n')
    with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")


def main():
    built = data.build_rows()
    if built is None:
        raise SystemExit("Data files are being written; run again in a moment.")
    rows = built[0]
    by_lang = {l: [r for r in rows if r["lang"] == l] for l in LANGS}
    if os.path.isdir(OUT):
        for name in os.listdir(OUT):                      # keep the folder, replace generated pages
            p = os.path.join(OUT, name)
            if name in ("style.css", "app.js", "favicon.svg", "_headers"):
                continue
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(OUT, exist_ok=True)
    home(rows, by_lang)
    for l in LANGS:
        lang_page(l, by_lang[l], by_lang)
    report_page()
    about_page(rows)
    not_found()
    downloads(rows)
    seo_files()
    n = len([r for r in rows if not r["unconfirmed"]])
    print(f"Built {OUT}: {n} confirmed films, {len(rows) - n} announced, {len(LANGS) + 4} pages")


if __name__ == "__main__":
    main()

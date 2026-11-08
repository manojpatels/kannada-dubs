"""Fill empty director / cast / language / year fields from each film's Wikipedia infobox.

Covers the rows that didn't come from Wikipedia: press_dubs.csv and sacnilk_dubs.csv.
A page is only used when it's a film article whose title matches ours, whose infobox
year is within a year of ours, and whose infobox language includes our original
language. Anything else is listed as unmatched, not guessed.

Run:  python3 fill_details.py        ->  writes details_cache.json
Then: python3 dashboard_export.py    ->  dashboard picks the details up
"""
import csv
import json
import os
import re
import time
import unicodedata

import kannada_dubs as kd   # reuses api_get, infobox_field, parse_languages, year_of

OUT = "details_cache.json"
SOURCES = [("press_dubs.csv", "original_language"), ("sacnilk_dubs.csv", "original_language")]


def key(title):
    t = unicodedata.normalize("NFKD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s*\((?:\d{4} )?(?:[\w-]+ )*film\)$", "", t, flags=re.I).lower().replace("&", " and ")
    t = re.sub(r"^(the|a|an) ", "", t)
    return re.sub(r"[^0-9a-z]+", "", t)


def targets():
    rows = []
    for path, lang_col in SOURCES:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    rows.append({"title": r["title"], "year": r.get("year", ""), "lang": r.get(lang_col, "")})
    return rows


def api(params, tries=5):
    """Fast GET: short retries (1, 2, 4, 8 s) instead of the scraper's 15 s+ backoff.
    Still waits if Wikipedia sends Retry-After, so it isn't rate-limited harder."""
    for n in range(tries):
        r = kd.session.get(kd.WIKI_API, params={**params, "format": "json", "formatversion": 2}, timeout=30)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(max(2 ** n, int(r.headers.get("Retry-After", "0") or 0)))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Wikipedia kept failing (HTTP {r.status_code}); progress is saved, run again")


def candidates(t):
    """Likely page titles: the usual disambiguation forms plus the top search hits."""
    names = [f"{t['title']} ({t['year']} film)", f"{t['title']} (film)", t["title"]]
    hits = api({"action": "query", "list": "search", "srsearch": f"{t['title']} {t['year']} film",
                "srlimit": 5, "srnamespace": 0})
    names += [h["title"] for h in hits["query"]["search"]]
    return names


def fetch_pages(names):
    """Wikitext for many titles, 50 per request (redirects followed)."""
    names = list(dict.fromkeys(names))
    for i in range(0, len(names), 50):
        data = api({"action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                    "titles": "|".join(names[i:i + 50]), "redirects": 1})
        for p in data["query"]["pages"]:
            if p.get("revisions"):
                yield p["title"], p["revisions"][0]["slots"]["main"]["content"]


def confirmed(t, page, text):
    if not re.search(r"\{\{\s*Infobox film", text, re.I):
        return None
    if key(page) != key(t["title"]):
        return None
    year = kd.year_of(text)
    if year and t["year"] and abs(int(year) - int(t["year"])) > 1:
        return None
    langs = kd.parse_languages(kd.infobox_field(text, "language"))
    if t["lang"].lower() not in " ".join(langs).lower():
        return None
    return {
        "page": page,
        "url": "https://en.wikipedia.org/wiki/" + page.replace(" ", "_"),
        "year": year,
        "langs": "; ".join(langs),
        "director": "; ".join(kd.parse_languages(kd.infobox_field(text, "director"))[:3]),
        "starring": "; ".join(kd.parse_languages(kd.infobox_field(text, "starring"))[:4]),
    }


def main():
    cache = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fh:
            cache = json.load(fh)
    todo = [t for t in targets() if f"{key(t['title'])}|{t['year']}" not in cache]
    names = []
    for n, t in enumerate(todo, 1):
        names += candidates(t)
        print(f"\rSearching {n}/{len(todo)}", end="", flush=True)
    print(f"\nFetching {len(set(names))} pages...")
    pages = list(fetch_pages(names))
    unmatched = []
    for t in todo:
        found = next((c for page, text in pages if (c := confirmed(t, page, text))), None)
        if found:
            cache[f"{key(t['title'])}|{t['year']}"] = found
            print(f"  {t['title']} -> {found['page']}")
        else:
            unmatched.append(t["title"])
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"\nDone: {len(cache)} films have details; {len(unmatched)} unmatched")
    for u in unmatched:
        print("  unmatched:", u)


if __name__ == "__main__":
    main()

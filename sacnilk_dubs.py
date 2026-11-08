#!/usr/bin/env python3
"""
sacnilk_dubs.py - films with a Kannada version, from Sacnilk's film pages.

How it works (follows https://www.sacnilk.com/robots.txt):
  1. Reads the official film list, sitemap-movies.xml.
  2. Opens each film page (one request every 1.5 s) and reads its
     "Languages:" field.
  3. Keeps a film when Kannada is listed AND the page shows the original
     language is something else ("Here is the English movie ...").
     Films whose original language the page doesn't state are written to
     sacnilk_unresolved.csv for review instead of being guessed, because
     a Kannada original dubbed into other languages (e.g. KGF) looks the same.

Output: sacnilk_dubs.csv (read by dashboard_export.py, which merges it with
the Wikipedia list and removes duplicates). Progress is saved every 25 films;
if it stops, run the same command again to continue.

Usage:
  python3 sacnilk_dubs.py --probe   # fetch sitemap + 3 pages, show parsing, save nothing
  python3 sacnilk_dubs.py           # full run
"""
import csv
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import requests

BASE = "https://www.sacnilk.com"
SITEMAP = BASE + "/sitemap-movies.xml"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sacnilk_dubs.csv")
UNRESOLVED = os.path.join(HERE, "sacnilk_unresolved.csv")
PROGRESS = os.path.join(HERE, "sacnilk_progress.json")
DELAY = 1.5                                   # seconds between page requests
LANGS = "English|Hindi|Tamil|Telugu|Malayalam|Kannada|Marathi|Bengali|Punjabi|Gujarati|Japanese|Korean|Chinese|Spanish|French"

session = requests.Session()
session.headers.update({"User-Agent": "KannadaDubScraper/1.0 (personal research script; python-requests)"})


class Blocked(Exception):
    pass


def get(url):
    for attempt in range(5):
        try:
            r = session.get(url, timeout=60)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(10 * (attempt + 1))
            continue
        if "<title>Just a moment" in r.text[:2000]:
            raise Blocked(url)                 # Cloudflare challenge: stop, don't try to get around it
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
    raise RuntimeError(f"Sacnilk kept failing for {url}")


def sitemap_urls(url=SITEMAP):
    """All film page URLs, following nested sitemap indexes."""
    root = ET.fromstring(get(url).encode("utf-8"))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    if root.tag.endswith("sitemapindex"):
        urls = []
        for loc in root.findall("s:sitemap/s:loc", ns):
            urls += sitemap_urls(loc.text.strip())
        return urls
    return [loc.text.strip() for loc in root.findall("s:url/s:loc", ns)]


def film_urls():
    """Only individual film pages; the sitemap also lists hub pages like /recent-movies."""
    # Sub-pages (e.g. /movie/X/something) are reduced to the film's main page, once.
    seen, out = set(), []
    for u in sitemap_urls():
        m = re.match(r"(https?://(?:www\.)?sacnilk\.com/(?:movie|tag)/[^/?#]+)", u)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse(page, url):
    fields = {text(k).rstrip(":"): text(v) for k, v in re.findall(
        r'<span class="font-medium text-gray-700">(.*?)</span>\s*<span class="text-right">(.*?)</span>', page, re.S)}
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    title = text(h1.group(1)) if h1 else ""
    langs = [l.strip() for l in fields.get("Languages", "").split(",") if l.strip() and l.strip() != "N/A"]
    release = fields.get("Theatrical Release", "")
    y = re.search(r"\b(?:19|20)\d{2}\b", release) or re.search(r"_((?:19|20)\d{2})$", url.rstrip("/"))
    year = (y.group(1) if y.re.groups else y.group(0)) if y else ""
    # Original language: Sacnilk's own article line "Here is the English movie <title> ..."
    orig = ""
    m = re.search(rf"Here is the ({LANGS}) (?:movie|film) {re.escape(title)}", text(page)) if title else None
    if m:
        orig = m.group(1)
    director = re.search(r"Director:(?:&nbsp;|\s)*</span>\s*(.*?)</", page, re.S)
    return {
        "title": title, "year": year,
        "languages": ", ".join(langs), "original_language": orig,
        "director": text(director.group(1)) if director else "", "release": release, "source": url,
    }


def load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as fh:
            return json.load(fh)
    return {"urls": None, "next": 0, "dubs": [], "unresolved": []}


def save(state):
    tmp = PROGRESS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, PROGRESS)
    cols = ["title", "year", "original_language", "director", "starring", "evidence", "source"]
    for path, rows in ((OUT, state["dubs"]), (UNRESOLVED, state["unresolved"])):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(dict(r, starring="", evidence=f"Sacnilk languages: {r['languages']}"))


def main():
    if "--probe" in sys.argv:
        raw = sitemap_urls()
        os.makedirs(os.path.join(HERE, "samples"), exist_ok=True)
        with open(os.path.join(HERE, "samples", "sitemap_urls.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(raw))
        urls = film_urls()
        print(f"sitemap-movies.xml: {len(raw)} URLs, {len(urls)} distinct film pages. First few:")
        for u in urls[:5]:
            print("  ", u)
        os.makedirs(os.path.join(HERE, "samples"), exist_ok=True)
        for n, u in enumerate(urls[:3]):
            time.sleep(DELAY)
            page = get(u)
            if page and n == 0:
                with open(os.path.join(HERE, "samples", "movie_page.html"), "w", encoding="utf-8") as fh:
                    fh.write(page)
            print("\n", json.dumps(parse(page, u) if page else {"url": u, "error": "404"}, ensure_ascii=False, indent=1))
        return

    state = load_progress()
    if state["urls"] is None:
        state["urls"] = film_urls()
        print(f"{len(state['urls'])} film pages in the sitemap", flush=True)
    urls = state["urls"]
    try:
        for i in range(state["next"], len(urls)):
            page = get(urls[i])
            if page:
                f = parse(page, urls[i])
                langs = [l.lower() for l in f["languages"].split(", ")]
                if "kannada" in langs and len(langs) > 1:
                    if f["original_language"] and f["original_language"] != "Kannada":
                        state["dubs"].append(f)
                    elif not f["original_language"]:
                        state["unresolved"].append(f)
            state["next"] = i + 1
            if state["next"] % 25 == 0 or state["next"] == len(urls):
                save(state)
                print(f"checked {state['next']}/{len(urls)}  dubs {len(state['dubs'])}  "
                      f"unresolved {len(state['unresolved'])}", flush=True)
            time.sleep(DELAY)
    except Blocked as b:
        save(state)
        sys.exit(f"Sacnilk showed a bot check at {b}. Progress saved; try again later.")
    save(state)
    print(f"Done: {len(state['dubs'])} dubs -> {OUT}; {len(state['unresolved'])} unresolved -> {UNRESOLVED}")


if __name__ == "__main__":
    main()

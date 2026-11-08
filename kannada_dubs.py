#!/usr/bin/env python3
"""
kannada_dubs.py - find films dubbed INTO Kannada, grouped by original language.

Sources:
  1. English Wikipedia: full-text search for dub phrases + Infobox film parsing.
  2. Wikidata (optional, --no-wikidata to skip): films whose "language of work"
     includes Kannada but whose "original language" is not Kannada.

Output:
  kannada_dubs.csv  - one row per film, with the sentence that proves the dub
  kannada_dubs.md   - same list, grouped by original language

Usage:
  pip install requests
  python kannada_dubs.py
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict

import requests

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "KannadaDubScraper/1.0 (personal research script; python-requests)"}

# Phrases searched on Wikipedia. Each is an exact-phrase search.
SEARCH_PHRASES = [
    '"dubbed into Kannada"',
    '"dubbed in Kannada"',
    '"Kannada dubbed"',
    '"Kannada-dubbed"',
    '"dubbed version in Kannada"',
    '"dubbed versions in Kannada"',
    '"Kannada dubbed version"',
    '"Kannada dub"',
    'Kannada dubbed insource:/[Dd]ubbed/ hastemplate:"Infobox film"',
]

session = requests.Session()
session.headers.update(HEADERS)


def api_get(params, url=WIKI_API, retries=8):
    """GET with patient retries. Honours Wikipedia's Retry-After and reports what went wrong."""
    last = ""
    for attempt in range(retries):
        wait = min(15 * 2 ** attempt, 300)              # 15 s, 30 s, 1 min ... capped at 5 min
        try:
            r = session.get(url, params=params, timeout=90)
        except (requests.ConnectionError, requests.Timeout) as e:
            last = f"{type(e).__name__}"
        else:
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                wait = max(wait, int(r.headers.get("Retry-After", "0") or 0))
            else:
                r.raise_for_status()
                return r.json()
        print(f"  Wikipedia: {last}; retrying in {wait} s (attempt {attempt + 1}/{retries})",
              file=sys.stderr, flush=True)
        time.sleep(wait)
    raise RuntimeError(f"Wikipedia API kept failing ({last}); nothing was overwritten, run again later")


def all_film_titles():
    """Every article that uses Infobox film (the full-sweep set)."""
    titles, cont = set(), {}
    while True:
        data = api_get({
            "action": "query", "list": "embeddedin", "eititle": "Template:Infobox film",
            "einamespace": 0, "eilimit": 500, "format": "json", **cont,
        })
        titles.update(p["title"] for p in data["query"]["embeddedin"])
        if len(titles) % 10000 < 500:
            print(f"  listed {len(titles)} film pages...", file=sys.stderr)
        if "continue" not in data:
            return titles
        cont = data["continue"]
        time.sleep(0.2)


# ---------------------------------------------------------------- Wikipedia
def search_titles(phrase):
    """All article titles matching a search phrase (MediaWiki caps at 10,000)."""
    titles, offset = set(), 0
    while True:
        data = api_get({
            "action": "query", "list": "search", "srsearch": phrase,
            "srnamespace": 0, "srlimit": 500, "sroffset": offset,
            "srprop": "", "format": "json",
        })
        titles.update(hit["title"] for hit in data["query"]["search"])
        if "continue" not in data or data["continue"]["sroffset"] >= 10000:
            if len(titles) >= 10000:
                print(f"  WARNING: {phrase!r} hit the 10,000-result search cap; some pages skipped",
                      file=sys.stderr)
            return titles
        offset = data["continue"]["sroffset"]
        time.sleep(0.5)


def fetch_batches(titles, start=0):
    """Yield (next_index, [(title, wikitext), ...]) for batches of 50 sorted titles."""
    for i in range(start, len(titles), 50):
        data = api_get({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": "|".join(titles[i:i + 50]),
            "redirects": 1, "format": "json", "formatversion": 2,
        })
        pages = [(p["title"], p["revisions"][0]["slots"]["main"]["content"])
                 for p in data["query"]["pages"] if p.get("revisions")]
        yield i + 50, pages
        time.sleep(0.3)                                   # be gentle between batches


def strip_markup(text):
    text = re.sub(r"<ref[^>/]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", ", ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)   # [[a|b]] -> b
    text = re.sub(r"\{\{(?:lang|langx|transl)\|[^|]*\|([^}|]+)[^}]*\}\}", r"\1", text, flags=re.I)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)                        # drop simple templates
    text = re.sub(r"'{2,}", "", text)
    return text


def infobox_field(wikitext, field):
    """Raw value of an Infobox film field, or ''."""
    m = re.search(r"\{\{\s*Infobox film", wikitext, re.I)
    if not m:
        return ""
    box = wikitext[m.start():]
    fm = re.search(
        rf"^\s*\|\s*{field}\s*=(.*?)(?=^\s*\|\s*[\w ]+?\s*=|^\s*\}}\}})",
        box, re.M | re.S | re.I,
    )
    return fm.group(1).strip() if fm else ""


LANG_SPLIT = re.compile(r"[,\n*/]|\band\b|&", re.I)


def parse_languages(raw):
    raw = re.sub(r"\{\{\s*(?:plain ?list|ubl|unbulleted list|flatlist|hlist)\s*\|", "", raw, flags=re.I)
    raw = raw.replace("|", ",")
    text = strip_markup(raw)
    langs = []
    for part in LANG_SPLIT.split(text):
        part = re.sub(r"\(.*?\)", "", part)
        part = re.sub(r"\blanguage\b", "", part, flags=re.I).strip(" .;:-}{")
        if part and len(part) < 40 and part not in langs:
            langs.append(part)
    return langs


def year_of(wikitext):
    raw = re.sub(r"<ref[^>]*>.*?</ref>", "", infobox_field(wikitext, "released"), flags=re.S)
    m = re.search(r"\b(?:18|19|20)\d{2}\b", raw)        # search raw: {{Film date|2015|..}} keeps the year
    if m:
        return m.group(0)
    m = re.search(r"\[\[Category:((?:18|19|20)\d{2}) films\]\]", wikitext)
    return m.group(1) if m else ""



L = r"(?:English|Hindi|Tamil|Telugu|Malayalam|Marathi|Bengali|Bhojpuri|Odia|Punjabi)"
SEP = r"(?:\s*,\s*(?:and\s+)?(?:the\s+)?|\s+and\s+(?:the\s+)?|\s+)"
CLAUSE_END = r"\b(?:remade|remakes?|remaking|whereas|but|which|records?|held by|after|unlike)\b|;|\.\s"
VERB = r"\b(released|releasing|releases?|streaming|streamed|premiered|premiere|available)\b"
BAD = (r"\b(remakes?|remade|remaking|reprised?|reprising|adapted|adaptation|reshot|shooting|"
       r"directed|role|actor|actress|portray\w*|music|songs?|soundtrack|tunes|music rights|motion poster|trailer|subtitles?|"
       r"considered|never|library|curated|filmed|inspired|based on|simultaneously|bilingual|trilingual|multilingual|"
       r"ratings|certificate)\b|\bkannada (original|film|version (featured|was commercially))|\boriginal kannada\b|(?<!originally )\bmade in\b")

def dubbed_into_kannada(s):
    if re.search(r"\bdubbed version of (?:the )?Kannada\b|\bKannada (?:film|movie|original)\b", s, re.I):
        return False                                    # a Kannada original dubbed into something else
    if re.search(rf"\bKannada{SEP}(?:{L}{SEP})*(?:dubbed|dubbing|dub)\b", s, re.I):
        return True                                     # "Kannada dubbed", "Telugu, Kannada and Malayalam dubbed versions"
    for m in re.finditer(r"\bdub(?:bed|bing|s)?\b", s, re.I):
        tail = re.split(CLAUSE_END, s[m.end():m.end() + 250], maxsplit=1, flags=re.I)[0]
        if re.search(r"\bKannada\b", tail):
            return True                                 # "dubbed into Hindi, Tamil and Kannada"
    return False

def released_in_kannada(s):
    return bool(re.search(VERB, s, re.I)) and not re.search(BAD, s, re.I)


def dub_evidence(wikitext):
    """(sentence, kind) proving a Kannada version of a non-Kannada film, or ('', '').

    kind 'dub'     : the sentence says the film was dubbed INTO Kannada
                     ("dubbed into Tamil and Kannada", "Kannada-dubbed version").
                     "Dubbed in Telugu and remade in Kannada" does not count.
    kind 'release' : the sentence lists Kannada among release/streaming languages
                     ("released in English, Hindi, Tamil, Telugu and Kannada") and
                     isn't about remakes, cast, music rights or the like. For a film
                     whose original language isn't Kannada, that is a dubbed version.
    """
    body = strip_markup(wikitext)
    release_hit = ""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        if "kannada" not in sentence.lower():
            continue
        clean = re.sub(r"\s+", " ", sentence).strip()[:400]
        if dubbed_into_kannada(clean):
            return clean, "dub"
        if not release_hit and released_in_kannada(clean):
            release_hit = clean
    return (release_hit, "release") if release_hit else ("", "")


CHECKPOINT = "sweep_progress.json"


def check_page(title, text):
    """Return a film record if this page documents a Kannada dub, else None."""
    if not re.search(r"\{\{\s*Infobox film", text, re.I):
        return None                                    # not a film article
    langs = parse_languages(infobox_field(text, "language"))
    if not langs or "kannada" in " ".join(langs).lower():
        return None                                    # Kannada original or multilingual shoot
    evidence, kind = dub_evidence(text)
    if not evidence:
        return None
    return {
            "title": title,
            "year": year_of(text),
            "original_language": langs[0],
            "all_original_languages": "; ".join(langs),
            "director": "; ".join(parse_languages(infobox_field(text, "director"))[:3]),
            "starring": "; ".join(parse_languages(infobox_field(text, "starring"))[:4]),
            "evidence": evidence,
            "evidence_type": kind,
            "source": "https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
    }


MENTION_QUERIES = [
    f'hastemplate:"Infobox film" Kannada {lang} {word}'
    for lang in ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]
    for word in ["released", "version", "languages"]
]


def previous_results(csv_path):
    """Films already found: the finished CSV if present, else the sweep checkpoint."""
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as fh:
            return {r["title"]: dict(r, evidence_type=r.get("evidence_type") or "dub")
                    for r in csv.DictReader(fh)}
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, encoding="utf-8") as fh:
            return {t: dict(f, evidence_type=f.get("evidence_type") or "dub")
                    for t, f in json.load(fh)["films"].items()}
    return {}


def from_wikipedia(full_sweep=False, queries=None, extra_titles=()):
    """Check candidate pages. Full sweep saves progress so a crash can resume."""
    state = {"titles": None, "next": 0, "films": {}}
    if full_sweep and os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, encoding="utf-8") as fh:
            state = json.load(fh)
        print(f"  resuming at page {state['next']}/{len(state['titles'])}, "
              f"{len(state['films'])} dubs so far", file=sys.stderr)

    if state["titles"] is None:
        if full_sweep:
            titles = all_film_titles()
        else:
            titles = set()
            for phrase in (queries or SEARCH_PHRASES):
                found = search_titles(phrase)
                print(f"  search {phrase!r}: {len(found)} hits", file=sys.stderr)
                titles |= found
            titles |= set(extra_titles)
        state["titles"] = sorted(titles)
    titles, films = state["titles"], state["films"]
    print(f"  {len(titles)} unique pages to check", file=sys.stderr)

    for nxt, pages in fetch_batches(titles, state["next"]):
        for title, text in pages:
            rec = check_page(title, text)
            if rec:
                films[title] = rec
        state["next"] = nxt
        if full_sweep and (nxt // 50) % 20 == 0:          # save every 1,000 pages
            with open(CHECKPOINT + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(CHECKPOINT + ".tmp", CHECKPOINT)
        if nxt % 5000 == 0:
            print(f"  checked {min(nxt, len(titles))}/{len(titles)} pages, "
                  f"{len(films)} dubs so far", file=sys.stderr)
    return films


# ---------------------------------------------------------------- Wikidata
SPARQL = """
SELECT DISTINCT ?film ?filmLabel ?origLabel (MIN(YEAR(?date)) AS ?year) ?article WHERE {
  ?film wdt:P31/wdt:P279* wd:Q11424 ;
        wdt:P407 wd:Q33673 ;
        wdt:P364 ?orig .
  FILTER(?orig != wd:Q33673)
  FILTER NOT EXISTS { ?film wdt:P364 wd:Q33673 }
  OPTIONAL { ?film wdt:P577 ?date }
  OPTIONAL { ?article schema:about ?film ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
GROUP BY ?film ?filmLabel ?origLabel ?article
"""


def from_wikidata():
    r = session.get(WIKIDATA_SPARQL, params={"query": SPARQL, "format": "json"}, timeout=120)
    r.raise_for_status()
    films = {}
    for b in r.json()["results"]["bindings"]:
        title = b["filmLabel"]["value"]
        films.setdefault(title, {
            "title": title,
            "year": b.get("year", {}).get("value", ""),
            "original_language": b["origLabel"]["value"].replace(" language", ""),
            "all_original_languages": b["origLabel"]["value"].replace(" language", ""),
            "director": "", "starring": "", "evidence_type": "wikidata",
            "evidence": "Wikidata: language of work includes Kannada; original language differs",
            "source": b.get("article", b["film"])["value"],
        })
    return films


# ---------------------------------------------------------------- output
def write_outputs(films, csv_path, md_path):
    rows = sorted(films.values(), key=lambda f: (f["original_language"], f["year"], f["title"]))
    fields = ["original_language", "title", "year", "director", "starring",
              "all_original_languages", "evidence_type", "evidence", "source"]
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    groups = defaultdict(list)
    for f in rows:
        groups[f["original_language"]].append(f)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(f"# Films dubbed into Kannada ({len(rows)} found)\n\n")
        for lang in sorted(groups, key=lambda l: (-len(groups[l]), l)):
            fh.write(f"## {lang} ({len(groups[lang])})\n\n")
            for f in groups[lang]:
                fh.write(f"- [{f['title']}]({f['source']}) ({f['year'] or 'year ?'})\n")
            fh.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-wikidata", action="store_true", help="skip the Wikidata query")
    ap.add_argument("--full-sweep", action="store_true",
                    help="check every Wikipedia film article (several hours; resumable) instead of phrase search")
    ap.add_argument("--mentions", "--recheck", dest="mentions", action="store_true",
                    help="quick rebuild (~10 min): re-read every candidate page (found so far, phrase "
                         "matches, and pages naming Kannada with another language) with current rules")
    ap.add_argument("--csv", default="kannada_dubs.csv")
    ap.add_argument("--md", default="kannada_dubs.md")
    args = ap.parse_args()

    print("Searching Wikipedia...", file=sys.stderr)
    if args.mentions:
        # Recheck only film pages that mention Kannada next to another language
        # name, with the wider rule, and merge into what the sweep already found.
        # Re-read every candidate page with the current rules and rebuild the
        # Wikipedia list from scratch, so entries the old rules let in drop out.
        prev = previous_results(args.csv)
        films = {t: f for t, f in prev.items() if f.get("evidence_type") == "wikidata"}
        films.update(from_wikipedia(queries=MENTION_QUERIES + SEARCH_PHRASES, extra_titles=prev.keys()))
        args.no_wikidata = True
    else:
        films = from_wikipedia(full_sweep=args.full_sweep)
    if args.full_sweep:                                 # also merge phrase-search hits
        for title, f in from_wikipedia().items():
            films.setdefault(title, f)
    if not args.no_wikidata:
        print("Querying Wikidata...", file=sys.stderr)
        try:
            for title, f in from_wikidata().items():
                films.setdefault(title, f)          # Wikipedia evidence wins on overlap
        except requests.RequestException as e:
            print(f"  Wikidata failed, continuing without it: {e}", file=sys.stderr)

    write_outputs(films, args.csv, args.md)
    print(f"Done: {len(films)} films -> {args.csv}, {args.md}", file=sys.stderr)


if __name__ == "__main__":
    main()

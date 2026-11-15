#!/usr/bin/env python3
"""Download French immigration circulars and instructions addressed to prefectures.

    ./download_fr.py            download everything into fr/ and write fr/index.tsv
    ./download_fr.py --list     only enumerate (reads the listing pages, downloads nothing)

France has no single manual: guidance is issued as "circulaires", "instructions" and
"notes" (mainly Ministere de l'Interieur / DGEF).  The official sites (legifrance.gouv.fr,
immigration.interieur.gouv.fr, interieur.gouv.fr) answer scripts with a 403 bot check, so
this script uses the topical index kept by the NGO GISTI (gisti.org, "Reglementation"),
which hosts copies of the texts, and falls back to the Internet Archive's copy of the
Legifrance PDF when GISTI only links to Legifrance.

Layout:  fr/<topic>/...           texts GISTI does not flag as repealed
         fr/abroges/<topic>/...   texts GISTI shows under "Textes abroges ou caducs"
                                  (repealed or lapsed; kept because they are still cited)
         fr/index.tsv             file, title, date, source URL
         fr/not-downloaded.tsv    listed texts for which no copy could be fetched
         fr/_articles.json        cache of which documents each GISTI page links to

Files already downloaded are skipped, so the script can be re-run.
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "fr"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
BASE = "https://www.gisti.org/"
DELAY = 1.0                       # seconds between requests
MAX_BYTES = 1_000_000_000         # stop at roughly 1 GB ...
MAX_FILES = 3000                  # ... or 3,000 files

# GISTI "Reglementation" rubrics that are in scope
TOPICS = {
    "sejour": 110,
    "travail": 128,               # work authorisation, passeport talent, salaried workers
    "famille": 106,               # regroupement familial, marriage, parents of French children
    "etudiants": 129,
    "eloignement": 109,
    "asile": 112,
    "nationalite": 113,
}

CIRC_HEADING = re.compile(r"circulaire|notes minist", re.I)
SKIP_HEADING = re.compile(r"union europ|de l.UE|internationa|jurisprudence|rapports|documents", re.I)
ABROGATED = re.compile(r"abrog|caduc", re.I)
# outside a "Circulaires" section, keep only items whose own title says they are guidance
CIRC_TITLE = re.compile(r"^\W*(circulaire|instruction|note\b|t[ée]l[ée]gramme|information|lettre|"
                        r"d[ée]p[êe]che|kit|message|courrier|directive (du|de la|minist))", re.I)
DOC_LINK = re.compile(r"""(?:href|src)=["']((?:https?://www\.gisti\.org/)?IMG/"""
                      r"""(?:pdf|doc|docx|rtf|odt|zip|xls|xlsx|ppt|pptx)/[^"'#?]+)""", re.I)
LEGI_CIRC = re.compile(r"legifrance\.gouv\.fr/(?:circulaire/id/|download/pdf/circ\?id=)(\d+)")
MONTHS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
          "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
          "decembre": 12, "décembre": 12}

blocked_hosts = {}                # host -> reason; once a host refuses us we leave it alone
last_request = [0.0]


def get(url):
    """Polite GET. Returns bytes or None. A 403/429 marks the host as blocked: no retries."""
    host = urllib.parse.urlsplit(url).netloc
    if host in blocked_hosts:
        return None
    for attempt in range(2):
        wait = DELAY - (time.time() - last_request[0])
        if wait > 0:
            time.sleep(wait)
        last_request[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                blocked_hosts[host] = f"HTTP {e.code}"
                print(f"  BLOCKED by {host} (HTTP {e.code}) - not retrying this host")
                return None
            if e.code in (404, 410):
                print(f"  {e.code} {url}")
                return None
            err = e
        except Exception as e:                      # noqa: BLE001 - report and retry once
            err = e
        time.sleep(5)
    print(f"  FAILED {url}: {err}")
    return None


def clean(markup):
    t = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return re.sub(r"\s+", " ", t.replace("\xa0", " ")).strip()


def slug(s, n=110):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "x"
    if len(s) > n:                                   # shorten but keep the extension
        ext = re.search(r"\.[A-Za-z0-9]{2,5}$", s)
        ext = ext.group(0) if ext else ""
        s = s[:n - len(ext)] + ext
    return s


def find_date(title):
    m = re.search(r"(\d{1,2})\s*(?:er)?\s+([a-zéûô]+)\s+((?:19|20)\d\d)", title, re.I)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b([a-zéûô]+)\s+((?:19|20)\d\d)\b", title, re.I)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    return ""


def enumerate_items():
    """Read the topic pages and return the list of guidance items they list."""
    items = []
    for topic, rub in TOPICS.items():
        start = len(items)
        page = get(f"{BASE}spip.php?rubrique{rub}")
        if page is None:
            print(f"  could not read the listing for {topic}")
            continue
        t = page.decode("utf-8", "replace")
        parts = re.split(r'(<h[3-6][^>]*class="menu-titre".*?</h[3-6]>)', t, flags=re.S)
        stack = {}                                   # heading level -> heading text
        for i in range(1, len(parts), 2):
            level = int(parts[i][2])
            stack = {k: v for k, v in stack.items() if k < level}
            stack[level] = clean(parts[i])
            path = " / ".join(stack[k] for k in sorted(stack))
            abrogated = bool(ABROGATED.search(path))
            in_circ = bool(CIRC_HEADING.search(path))
            if SKIP_HEADING.search(path) and not in_circ:
                continue
            for attrs, li in re.findall(r"<li([^>]*)>(.*?)</li>", parts[i + 1], flags=re.S):
                # The page holds every text twice: in its thematic section and under "Textes
                # abroges ou caducs", one of the two copies being hidden (display: none).
                # A text is repealed/lapsed when the hidden copy is the thematic one.
                hidden = "none" in attrs
                if abrogated and hidden:
                    continue
                m = re.search(r'<a href="([^"]+)"[^>]*>\s*<strong>(.*?)</strong>', li, flags=re.S)
                if not m:
                    continue
                name = clean(m.group(2))
                if not in_circ and not CIRC_TITLE.search(name):
                    continue
                rest = re.sub(r'<a [^>]*title="modif".*?</a>', " ", li[m.end():], flags=re.S)
                title = (name + " - " + clean(rest)).strip(" -")
                art = re.search(r"id_article=(\d+)", li)
                items.append({
                    "topic": topic, "abrogated": abrogated or hidden, "in_rebus": abrogated, "title": title[:400],
                    "date": find_date(name) or find_date(title),
                    "href": urllib.parse.urljoin(BASE, html.unescape(m.group(1))),
                    "article": art.group(1) if art else "",
                })
        # keep one entry per text: the thematic one, flagged if it also shows as repealed
        found, items[start:] = items[start:], []
        repealed = {x["href"] for x in found if x["in_rebus"]}
        thematic = [x for x in found if not x["in_rebus"]]
        listed = {x["href"] for x in thematic}
        for x in thematic:
            x["abrogated"] = x["abrogated"] or x["href"] in repealed
        items += thematic + [x for x in found if x["in_rebus"] and x["href"] not in listed]
    return items


def article_docs(art_id, cache):
    """Documents attached to a GISTI article page: {'docs': [urls], 'legi': id or ''}."""
    if art_id in cache:
        return cache[art_id]
    url = f"{BASE}spip.php?article{art_id}"
    page = get(url)
    if page is None:
        return None
    t = page.decode("utf-8", "replace")
    docs = []
    for d in DOC_LINK.findall(t):
        d = urllib.parse.urljoin(BASE, html.unescape(d))
        if d not in docs:
            docs.append(d)
    legi = LEGI_CIRC.search(t)
    cache[art_id] = {"docs": docs, "legi": legi.group(1) if legi else ""}
    return cache[art_id]


def wayback(url):
    """Closest Internet Archive capture of url, as a raw-content URL, or None."""
    api = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe="")
    data = get(api)
    if data is None:
        return None
    try:
        snap = json.loads(data)["archived_snapshots"]["closest"]
    except (ValueError, KeyError):
        return None
    if not snap.get("available") or snap.get("status") != "200":
        return None
    return f"https://web.archive.org/web/{snap['timestamp']}id_/{url}"


def main():
    list_only = "--list" in sys.argv
    OUT.mkdir(exist_ok=True)
    cache_file = OUT / "_articles.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}

    items = enumerate_items()
    print(f"{len(items)} guidance items listed "
          f"({sum(1 for x in items if not x['abrogated'])} in force, "
          f"{sum(1 for x in items if x['abrogated'])} repealed/lapsed)")
    items.sort(key=lambda x: x["abrogated"])         # texts in force first (the sort is stable)
    if list_only:
        for x in items:
            print("\t".join([x["topic"], "abroge" if x["abrogated"] else "", x["date"], x["title"][:100], x["href"]]))
        return

    rows, missing, seen_urls = [], [], {}
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    nfiles = 0
    stopped = False

    def fetch_to(url, folder, item, name=None, must_be_pdf=False):
        """Save url under folder. Returns 'ok', 'fail' or 'limit'."""
        nonlocal total, nfiles
        if url in seen_urls:                         # same text listed under several topics
            return "ok"
        base = name or urllib.parse.unquote(url.rsplit("/", 1)[-1])
        fname = (item["date"] + "_" if item["date"] and not base.startswith(item["date"]) else "") + slug(base)
        dest = folder / fname
        if not dest.exists():                        # status changed since an earlier run: move it
            topic_dir = folder.name
            for other in (OUT / topic_dir / fname, OUT / "abroges" / topic_dir / fname):
                if other != dest and other.exists():
                    folder.mkdir(parents=True, exist_ok=True)
                    other.rename(dest)
                    break
        if not (dest.exists() and dest.stat().st_size > 0):
            if total >= MAX_BYTES or nfiles >= MAX_FILES:
                return "limit"
            data = get(url)
            if data is None:
                return "fail"
            if must_be_pdf and not data.startswith(b"%PDF"):
                print(f"  not a PDF, discarded: {url}")
                return "fail"
            if data[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                print(f"  HTML instead of a document, discarded: {url}")
                return "fail"
            folder.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            total += len(data)
            print(f"  saved {dest.relative_to(OUT)} ({len(data) // 1024} KB)")
        nfiles += 1
        seen_urls[url] = dest
        rows.append((str(dest.relative_to(OUT)), item["title"], item["date"], url))
        return "ok"

    for n, item in enumerate(items, 1):
        folder = OUT / "abroges" / item["topic"] if item["abrogated"] else OUT / item["topic"]
        href = item["href"]
        docs, legi = [], ""
        m = LEGI_CIRC.search(href)
        if m:
            legi = m.group(1)
        if "/IMG/" in href:
            docs = [href]
        elif item["article"] or "spip.php?article" in href:
            art = item["article"] or re.search(r"article(\d+)", href).group(1)
            info = article_docs(art, cache)
            if info:
                docs, legi = info["docs"], legi or info["legi"]
        results = [fetch_to(d, folder, item) for d in docs]
        if "limit" in results:
            stopped = True
        got = "ok" in results
        if not got and not stopped:
            # GISTI holds no copy: try the Internet Archive's copy of the official PDF
            official = None
            if legi:
                official = f"https://www.legifrance.gouv.fr/download/pdf/circ?id={legi}"
            elif re.search(r"circulaires?\.(?:legifrance\.)?gouv\.fr/pdf/.*\.pdf", href):
                official = href
            if official:
                wb = wayback(official)
                if wb:
                    name = f"legifrance-circ-{legi}.pdf" if legi else None
                    r = fetch_to(wb, folder, item, name=name, must_be_pdf=True)
                    got = r == "ok"
                    stopped = stopped or r == "limit"
        if not got:
            why = "size/file limit reached" if stopped else (
                "no downloadable copy (text only on a GISTI web page, or only linked on an official site)")
            missing.append((item["topic"] + ("/abroge" if item["abrogated"] else ""), item["title"], item["date"],
                            f"{BASE}spip.php?article{item['article']}" if item["article"] else href, why))
        if n % 25 == 0:
            cache_file.write_text(json.dumps(cache, indent=0))
            print(f"[{n}/{len(items)}] {nfiles} files, {total / 1e6:.0f} MB")

    cache_file.write_text(json.dumps(cache, indent=0))
    tsv = lambda cells: "\t".join(re.sub(r"\s+", " ", c) for c in cells) + "\n"     # noqa: E731
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write(tsv(["file", "title", "date", "source URL"]))
        for r in sorted(set(rows)):
            f.write(tsv(r))
    with open(OUT / "not-downloaded.tsv", "w", encoding="utf-8") as f:
        f.write(tsv(["topic", "title", "date", "listing URL", "reason"]))
        for r in missing:
            f.write(tsv(r))
    print(f"done: {len(set(rows))} files indexed, {total / 1e6:.0f} MB in fr/, "
          f"{len(missing)} listed items not downloaded (see fr/not-downloaded.tsv)")
    if blocked_hosts:
        print("blocked hosts:", blocked_hosts)
    if stopped:
        print("STOPPED at the size/file limit; the rest is listed in not-downloaded.tsv")


if __name__ == "__main__":
    main()

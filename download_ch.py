#!/usr/bin/env python3
"""Download Switzerland's published immigration directives (SEM "Weisungen und Kreisschreiben").

    ./download_ch.py

Source: State Secretariat for Migration (SEM), https://www.sem.admin.ch/de/weisungen-und-kreisschreiben
German versions only (the same pages exist under /fr/ and /it/). The listing pages below
are read, every document linked from them (sem.admin.ch/dam/...) is saved into ch/<part>/,
and ch/index.tsv is rewritten. Files already downloaded are skipped, so the script can be re-run.
Standard library only; requests are sequential with a pause between them.
"""
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ch"
BASE = "https://www.sem.admin.ch"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 1.5                      # seconds between requests
MAX_BYTES = 1_000_000_000        # stop at roughly 1 GB
MAX_FILES = 3000

# (subfolder, listing page). Order matters: a document linked from several pages
# is stored under the first page that lists it.
PAGES = [
    ("1-auslaenderbereich", "/de/i-auslaenderbereich"),
    ("1-auslaenderbereich/chronologie", "/de/chronologie"),
    ("1-auslaenderbereich/anhaenge-kap00", "/de/0-rechtsgrundlagen"),
    ("1-auslaenderbereich/anhaenge-kap00", "/de/niederlassungsvereinbarungen"),
    ("1-auslaenderbereich/anhaenge-kap01", "/de/1-verfahren-und-zustaendigkeiten"),
    ("1-auslaenderbereich/anhaenge-kap02", "/de/2-einreise-in-die-schweiz"),
    ("1-auslaenderbereich/anhaenge-kap03", "/de/3-aufenthaltsregelung"),
    ("1-auslaenderbereich/anhaenge-kap04", "/de/4-aufenthalt-mit-erwerbstaetigkeit"),
    ("1-auslaenderbereich/anhaenge-kap05", "/de/5-aufenthalt-ohne-erwerbstaetigkeit"),
    ("1-auslaenderbereich/anhaenge-kap06", "/de/6-familiennachzug"),
    ("1-auslaenderbereich/anhaenge-kap07", "/de/7-angehoerige-von-diplomatischen-vertretungen-etc"),
    ("1-auslaenderbereich/anhaenge-kap08", "/de/8-entfernungs-und-fernhaltemassnahmen"),
    ("1-auslaenderbereich/anhaenge-kap09", "/de/9-ausschaffung-und-zwangsmassnahmen"),
    ("1-auslaenderbereich/anhaenge-kap10", "/de/10-rechtsschutz"),
    ("1-auslaenderbereich/anhaenge-kap11", "/de/11-eu-informationssysteme"),
    ("2-freizuegigkeitsabkommen", "/de/ii-freizuegigkeitsabkommen"),
    ("3-asylgesetz", "/de/iii-asylgesetz"),
    ("3-asylgesetz/1-asylverfahren", "/de/1-asylverfahren"),
    ("3-asylgesetz/2-wegweisung-vollzug", "/de/2-wegweisung-und-vollzug"),
    ("3-asylgesetz/3-kantonsverteilung", "/de/3-verteilung-auf-die-kantone"),
    ("3-asylgesetz/4-rueckkehrhilfe", "/de/4-rueckkehr-und-wiedereingliederungshilfe"),
    ("3-asylgesetz/5-ausserordentliche-verfahren", "/de/5-mehrfachgesuche-ausserordentliche-verfahren-etc"),
    ("3-asylgesetz/6-rechtliche-stellung", "/de/6-rechtliche-stellung"),
    ("3-asylgesetz/7-sozial-nothilfe", "/de/7-sozial-und-nothilfe"),
    ("3-asylgesetz/8-sonderabgabe", "/de/8-sonderabgabe"),
    ("3-asylgesetz/handbuch-asyl-und-rueckkehr", "/de/handbuch-asyl-und-rueckkehr"),
    ("4-integration", "/de/iv-integration"),
    ("5-buergerrecht", "/de/v-buergerrecht"),
    ("6-datenschutz", "/de/vi-datenschutz-und-offentlichkeitsgesetz"),
    ("7-visa", "/de/vii-visa"),
    ("7-visa", "/de/aufenthalt-bis-90-tage"),
    ("7-visa", "/de/aufenthalt-ueber-90-tage"),
    ("weitere-weisungen", "/de/weitere-weisungen-und-rundschreiben-des-sem"),
    ("weitere-weisungen/laendermerkblaetter", "/de/laendermerkblaetter"),
]

MONTHS = {m: i + 1 for i, m in enumerate(
    "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split())}
MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK", ".doc": b"\xd0\xcf\x11\xe0", ".xls": b"\xd0\xcf\x11\xe0"}


class Blocked(Exception):
    pass


streak = 0                        # fetches in a row that failed on the connection


def get(url, tries=2):
    """Fetch url. 403/429 are never retried: the site is saying no, so we stop.
    Transfers that arrive incomplete (the connection is sometimes cut on large
    files; the server ignores Range requests, so they cannot be resumed) count
    as failures: the file is not saved and a later run tries it again.
    The site also resets connections for minutes at a time; after three failed
    fetches in a row we wait five minutes, and if it still refuses we stop."""
    global streak
    err = None
    for attempt in range(tries):
        time.sleep(PAUSE)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                expected = r.headers.get("Content-Length", "")
                if expected.isdigit() and len(data) != int(expected):
                    raise OSError(f"incomplete: {len(data)} of {expected} bytes")
                streak = 0
                return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} for {url}")
            err = e
            if e.code == 404:
                break
        except Exception as e:                      # noqa: BLE001 - timeouts, cut transfers: wait and retry
            err = e
        time.sleep(20)
    print(f"  FAILED {url}: {str(err)[:200]}")
    if not isinstance(err, urllib.error.HTTPError):
        streak += 1
        if streak == 3:
            print("  three failures in a row, waiting 5 minutes")
            time.sleep(300)
        elif streak >= 6:
            raise Blocked(f"connections keep failing ({str(err)[:80]}); run again later")
    return None


def text_of(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def documents(page_html):
    """Yield (url, title, date) for every document link in the page's main content."""
    m = re.search(r"<main.*?</main>", page_html, flags=re.S)
    for href, inner in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', m.group(0) if m else page_html, flags=re.S):
        url = urllib.parse.urljoin(BASE, html.unescape(href))
        if not url.startswith(BASE + "/dam/"):
            continue
        label, date = text_of(inner), ""
        # link text ends with "<type> <size> <d. Monat yyyy>"
        d = re.search(r"\s+(\d{1,2})\.\s*([A-Za-zä]+)\s+(\d{4})$", label)
        if d and d.group(2) in MONTHS:
            date = f"{d.group(3)}-{MONTHS[d.group(2)]:02d}-{int(d.group(1)):02d}"
            label = label[:d.start()]
        label = re.sub(r"\s+[A-Za-z]{3,5}\s+[\d.,']+\s*[kMG]?B$", "", label)
        yield url, label.strip(), date


def main():
    OUT.mkdir(exist_ok=True)
    seen, rows, failed = {}, [], []
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file() and f.name != "index.tsv" and "coi" not in f.relative_to(OUT).parts[:1])
    count = new = 0
    try:
        for folder, page in PAGES:
            print(f"{page}")
            data = get(BASE + page)
            if data is None:
                failed.append(BASE + page)
                continue
            for url, title, date in documents(data.decode("utf-8", "replace")):
                if url in seen:
                    continue
                name = re.sub(r"[^A-Za-z0-9._-]+", "-", urllib.parse.unquote(url.rsplit("/", 1)[1])) or "x"
                dest = OUT / folder / name
                if dest in seen.values():           # same file name, different document
                    dest = dest.with_name(f"{dest.stem}-{url.split('/')[-2]}{dest.suffix}")
                seen[url] = dest
                if not (dest.exists() and dest.stat().st_size > 0):
                    if count >= MAX_FILES or total >= MAX_BYTES:
                        failed.append(url + "  (size/file limit reached)")
                        continue
                    body = get(url)
                    magic = MAGIC.get(dest.suffix.lower())
                    if body is None or (magic and not body.startswith(magic)) or body[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                        if body is not None:
                            print(f"  NOT A DOCUMENT {url}")
                        failed.append(url)
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(body)
                    total += len(body)
                    new += 1
                    print(f"  saved {dest.relative_to(OUT)} ({len(body):,} bytes)")
                count += 1
                rows.append((str(dest.relative_to(OUT)), title, date, url))
    except Blocked as e:
        print(f"BLOCKED, stopping: {e}")
        failed.append(str(e))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\n")
        for row in rows:
            f.write("\t".join(c.replace("\t", " ") for c in row) + "\n")
    print(f"\n{count} documents in index ({new} new), {total / 1e6:.1f} MB in {OUT}")
    if failed:
        print(f"{len(failed)} not saved:")
        for u in failed:
            print("  " + u)
        sys.exit(1)


if __name__ == "__main__":
    main()

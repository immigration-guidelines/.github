#!/usr/bin/env python3
"""Download UDI's own case-handling guidance (Norway) into ./no/.

    ./download_no.py            find captures, download, write no/index.tsv
    ./download_no.py --reindex  also re-ask Common Crawl indexes that had no hits / failed before

Target: "UDI Regelverk" (https://www.udiregelverk.no), UDI's own documents only:
UDI retningslinjer (formerly UDI rundskriv "RS", interne meldinger "IM",
praksisnotater "PN"), prosedyrer/veiledninger and archived retningslinjer.
Laws, regulations, ministry instructions, court decisions and international
sources are separate categories on the site and are not fetched.

udiregelverk.no itself answers scripts with an Azure WAF JavaScript challenge
(HTTP 403) and the Wayback Machine's replay answered 429, so neither is used.
The pages are taken from Common Crawl's public archive instead:
  1. the per-crawl URL indexes at https://index.commoncrawl.org/ list captures;
  2. each capture is one gzip member of a WARC file on https://data.commoncrawl.org/,
     read with an HTTP Range request.
For every document URL the newest capture is kept. Files already present are
skipped, so the script can be re-run (index answers are cached in no/_cc_index/).
"""
import gzip
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
OUT = ROOT / "no"
CACHE = OUT / "_cc_index"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 0.5
FIRST_YEAR = 2017               # Common Crawl crawls older than this are not asked
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000

# path segments that hold UDI's own guidance (current and earlier site layouts)
WANT = re.compile(
    r"/(udi-retningslinjer|arkiverte-retningslinjer|udi-rundskriv|udi-interne-meldinger|"
    r"udi-praksisnotater|udi-praksisdokumenter|prosedyrer-veiledninger|prosedyrer-og-veiledninger|"
    r"udi%20rundskriv|udi%20interne%20meldinger|udi%20praksisnotater)(/|$)", re.I)


MONTHS = ["jan", "feb", "mar", "apr", "mai", "jun", "jul", "aug", "sep", "okt", "nov", "des"]


class Blocked(Exception):
    pass


def fetch(url, headers=None, tries=3):
    """GET url. Returns (status, bytes). 5xx/timeouts are retried slowly; 403/429 stop the run."""
    err = None
    for attempt in range(tries):
        time.sleep(PAUSE)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"{e.code} from {url}")
            if e.code == 404:
                return 404, b""
            err = e
        except Exception as e:                      # noqa: BLE001 - report and retry
            err = e
        time.sleep(15 * (attempt + 1))
    print(f"  FAILED {url}: {err}")
    return None, b""


def crawl_ids():
    status, data = fetch("https://index.commoncrawl.org/collinfo.json")
    if status != 200:
        sys.exit("cannot read the Common Crawl crawl list")
    ids = [c["id"] for c in json.loads(data)]
    return [i for i in ids if re.match(r"CC-MAIN-(\d{4})-\d+$", i) and int(i[8:12]) >= FIRST_YEAR]


def complete(data):
    """True if an index answer is whole: ends with a newline and every line is JSON."""
    if data and not data.endswith(b"\n"):
        return False
    try:
        for line in data.decode("utf-8").splitlines():
            json.loads(line)
    except ValueError:
        return False
    return True


def ask_index(cid):
    """One crawl's captures of udiregelverk.no as JSON lines; None if the index did not answer properly."""
    base = (f"https://index.commoncrawl.org/{cid}-index?url=udiregelverk.no"
            "&matchType=domain&output=json&filter=status:200")
    status, data = fetch(base)
    if status == 404:                               # no captures in that crawl
        return b""
    if status == 200 and complete(data):
        return data
    if status != 200:
        return None
    # long answers get cut off: ask again page by page
    status, info = fetch(base + "&showNumPages=true")
    if status != 200:
        return None
    out = b""
    for page in range(json.loads(info)["pages"]):
        status, data = fetch(f"{base}&page={page}")
        if status != 200 or not complete(data):
            return None
        out += data
    return out


def captures(reindex=False):
    """All 200-status captures of udiregelverk.no in Common Crawl, as dicts."""
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = []
    for cid in crawl_ids():
        f = CACHE / f"{cid}.jsonl"
        if not f.exists() or (reindex and f.stat().st_size == 0):
            data = ask_index(cid)
            if data is None:
                print(f"  index {cid}: no complete answer, will be asked again on the next run")
                continue
            f.write_bytes(data)
            print(f"  index {cid}: {data.count(b'filename')} captures")
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("{"):
                rows.append(json.loads(line))
    return rows


def key_of(url):
    """Normalised document path: no host, no query, lower case, no trailing slash."""
    p = urllib.parse.urlsplit(url).path
    return urllib.parse.unquote(p).lower().rstrip("/")


def slug(s, n=150):
    s = s.replace("æ", "ae").replace("ø", "o").replace("å", "a")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:n] or "x"


def warc_body(row):
    """Fetch one WARC record and return the HTTP response body."""
    start, length = int(row["offset"]), int(row["length"])
    status, data = fetch("https://data.commoncrawl.org/" + row["filename"],
                         {"Range": f"bytes={start}-{start + length - 1}"})
    if status not in (200, 206) or not data:
        return None
    rec = gzip.decompress(data)
    parts = rec.split(b"\r\n\r\n", 2)               # WARC headers, HTTP headers, body
    if len(parts) < 3 or not parts[1].startswith(b"HTTP/"):
        return None
    return parts[2].rstrip(b"\r\n") + b"\n"


def text_of(markup):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def describe(page):
    """(title, date) from a saved page."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) or re.search(r"<title[^>]*>(.*?)</title>", page, re.S)
    title = text_of(m.group(1)) if m else ""
    # newest entry of the page's own change log ("Siste endringer for ..."): year heading, then "2. jun."
    date = ""
    m = re.search(r'class="list-year[^"]*">\s*(\d{4})\s*</div>.*?class="date-box">\s*<div>\s*(\d{1,2})\.\s*([a-zæøå]{3})',
                  page, re.S)
    if m and m.group(3) in MONTHS:
        date = f"{m.group(1)}-{MONTHS.index(m.group(3)) + 1:02d}-{int(m.group(2)):02d}"
    if not date:                                    # pre-2019 layout: "Sist endret : 01.01.2014"
        m = re.search(r"(?:Sist endret|Dokumentdato)\s*:?\s*(\d{2})\.(\d{2})\.(\d{4})", text_of(page))
        if m:
            date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return title, date


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        rows = captures("--reindex" in sys.argv)
    except Blocked as e:
        sys.exit(f"blocked, stopping: {e}")
    newest = {}
    for r in rows:
        if "html" not in r.get("mime", "") + r.get("mime-detected", ""):
            continue
        k = key_of(r["url"])
        if not WANT.search(k + "/") or k.startswith("/en/"):
            continue
        if k not in newest or r["timestamp"] > newest[k]["timestamp"]:
            newest[k] = r
    print(f"{len(rows)} captures of udiregelverk.no, {len(newest)} distinct UDI guidance pages")

    total = sum(f.stat().st_size for f in OUT.glob("*.html"))
    count = len(list(OUT.glob("*.html")))
    left = 0
    for k in sorted(newest):
        r = newest[k]
        dest = OUT / (slug(k.strip("/").replace("/", "__")) + ".html")
        r["_file"] = dest
        if dest.exists() and dest.stat().st_size > 0:
            continue
        if count >= MAX_FILES or total >= MAX_BYTES:
            left += 1
            continue
        try:
            body = warc_body(r)
        except Blocked as e:
            print(f"blocked, stopping downloads: {e}")
            break
        if not body:
            print(f"  no usable record for {r['url']}")
            continue
        dest.write_bytes(body)
        count += 1
        total += len(body)
        print(f"  {dest.name}  {len(body)} bytes  (capture {r['timestamp'][:8]})")
    if left:
        print(f"limit reached: {left} pages not downloaded")

    lines = ["file\ttitle\tdate\tsource_url\tcapture\tarchive_record"]
    for k in sorted(newest):
        r = newest[k]
        dest = r["_file"]
        if not dest.exists():
            continue
        title, date = describe(dest.read_text(encoding="utf-8", errors="replace"))
        ts = r["timestamp"]
        rec = f"https://data.commoncrawl.org/{r['filename']}#bytes={r['offset']}+{r['length']}"
        lines.append("\t".join([dest.name, title.replace("\t", " "), date, r["url"],
                                f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", rec]))
    (OUT / "index.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines) - 1} documents listed in {OUT / 'index.tsv'}, {total / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

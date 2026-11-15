#!/usr/bin/env python3
"""Download Immigration New Zealand's Operational Manual and its circulars.

    ./download_nz.py            everything
    ./download_nz.py manual     only the Operational Manual (current instructions)
    ./download_nz.py circulars  only Amendment Circulars and Internal Administration Circulars

Sources
  * Operational Manual: https://www.immigration.govt.nz/opsmanual/ (an Author-it web help;
    toc.json enumerates every topic). Only topics visible in the table of contents are
    taken; the ~4,500 topics flagged "hidden" are superseded versions ("previous
    immigration instructions") and are skipped.
  * Circulars: INZ now lists them only through its site search, which sits behind a bot
    check, so the PDFs are taken from the Internet Archive's copies of
    immigration.govt.nz/documents/... (old site) and /assets/inz/documents/... (new site).

Files already downloaded are skipped, so the script can be re-run.
Output goes to nz/ next to this script; nz/index.tsv lists everything saved.
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
OUT = ROOT / "nz"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
OPS = "https://www.immigration.govt.nz/opsmanual/"
CDX = ("https://web.archive.org/cdx/search/cdx?url={}*&filter=statuscode:200"
       "&collapse=urlkey&fl=original,timestamp,mimetype,length&limit=5000")
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000

# (folder, label, URL prefixes on immigration.govt.nz as archived by the Wayback Machine)
CIRCULARS = [
    ("amendment-circulars", "Amendment Circular",
     ["immigration.govt.nz/documents/amendment-circulars/",
      "immigration.govt.nz/assets/inz/documents/amendment-circulars/"]),
    ("internal-administration-circulars", "Internal Administration Circular",
     ["immigration.govt.nz/documents/internal-administration-circulars/",
      "immigration.govt.nz/assets/inz/documents/internal-administration-circulars/"]),
]

last_request = {}
blocked = set()          # hosts that answered 403/429 or a bot check: no further requests
failed = []


class Blocked(Exception):
    pass


def get(url, delay=0.4, tries=3):
    """Fetch url politely. Returns bytes, or None on failure. Never retries a 403/429."""
    host = urllib.parse.urlsplit(url).netloc
    if host in blocked:
        return None
    err = None
    for attempt in range(tries):
        wait = last_request.get(host, 0) + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            last_request[host] = time.time()
            if len(data) < 5000 and b"_Incapsula_Resource" in data:
                raise Blocked("bot check")
            return data
        except Blocked as e:
            last_request[host] = time.time()
            blocked.add(host)
            print(f"  BLOCKED ({e}) {url} - no further requests to {host}")
            return None
        except urllib.error.HTTPError as e:
            last_request[host] = time.time()
            err = e
            if e.code in (403, 429):
                blocked.add(host)
                print(f"  BLOCKED (HTTP {e.code}) {url} - no further requests to {host}")
                return None
            if e.code == 404:
                break
        except Exception as e:                      # noqa: BLE001 - report and retry
            last_request[host] = time.time()
            err = e
        time.sleep(5 * (attempt + 1))
    print(f"  FAILED {url}: {err}")
    failed.append(url)
    return None


def totals():
    files = [p for p in OUT.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


class Budget:
    def __init__(self):
        self.files, self.bytes = totals()
        self.hit = False

    def ok(self):
        if self.files >= MAX_FILES or self.bytes >= MAX_BYTES:
            if not self.hit:
                print(f"  CAP reached ({self.files} files, {self.bytes / 1e6:.0f} MB) - stopping downloads")
            self.hit = True
        return not self.hit

    def add(self, n):
        self.files += 1
        self.bytes += n


def save(url, dest, budget, delay=0.4, check=None):
    """Download url to dest unless present. Returns True if the file exists afterwards."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    if not budget.ok():
        return False
    data = get(url, delay)
    if data is None:
        return False
    if check and not check(data):
        print(f"  NOT A VALID DOCUMENT, skipped: {url}")
        failed.append(url)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    budget.add(len(data))
    return True


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


# ---------------------------------------------------------------- Operational Manual

def is_topic(data):
    return b"<html" in data[:400].lower() and b"Page not found" not in data[:3000]


def manual(budget):
    rows = []
    mdir = OUT / "manual"
    mdir.mkdir(parents=True, exist_ok=True)
    toc_file = mdir / "toc.json"
    data = get(OPS + "toc.json")                 # always refresh: it is the list of current topics
    if data:
        toc_file.write_bytes(data)
    elif not toc_file.exists():
        print("  could not get the manual's table of contents")
        return rows
    toc = json.loads(toc_file.read_text(encoding="utf-8-sig"))

    current, hidden = [], 0

    def walk(nodes, parent_hidden):
        nonlocal hidden
        for n in nodes:
            h = parent_hidden or n.get("hidden", False)
            if h:
                hidden += 1
            else:
                current.append(n)
            walk(n.get("children", []), h)

    walk(toc, False)
    print(f"manual: {len(current)} current topics, {hidden} hidden (superseded) topics skipped")

    issue = ""
    assets = set()
    for i, n in enumerate(current, 1):
        name = n["url"].split("#")[0]
        dest = mdir / name
        if not save(OPS + name, dest, budget, check=is_topic):
            continue
        page = dest.read_text(encoding="utf-8-sig", errors="replace")
        m = re.search(r'class="effectivedate"[^>]*>(.*?)</p>', page, re.S)
        date = clean(m.group(1)) if m else ""
        if not issue:
            m = re.search(r"Manual updated on:\s*(?:<[^>]+>\s*)*([^<]+)", page)
            issue = clean(m.group(1)) if m else ""
        rows.append((f"manual/{name}", n["text"].strip(), date, OPS + "#" + name))
        # files the topic itself uses: styles, pictures, attached documents (not other topics)
        for ref in re.findall(r'(?:href|src)="([^"#?]+)"', page):
            if re.match(r"(?i)[a-z]+:|/|\.\.", ref) or not re.search(
                    r"(?i)\.(css|gif|png|jpe?g|svg|pdf|docx?|xlsx?|pptx?)$", ref):
                continue
            assets.add(html.unescape(ref))
        if i % 200 == 0:
            print(f"  {i}/{len(current)} topics")

    for ref in sorted(assets):
        dest = mdir / ref
        if mdir.resolve() not in dest.resolve().parents:
            continue
        ok = save(OPS + urllib.parse.quote(ref), dest, budget)
        if ok and re.search(r"(?i)\.(pdf|docx?|xlsx?|pptx?)$", ref):
            rows.append((f"manual/{ref}", f"Attachment {Path(ref).name}", "", OPS + urllib.parse.quote(ref)))
    if issue:
        rows.insert(0, ("manual/toc.json", "Operational Manual - table of contents (includes hidden superseded topics)",
                        f"Manual updated on {issue}", OPS + "toc.json"))
    print(f"manual: {len(rows)} files indexed")
    return rows


# ---------------------------------------------------------------- circulars (Wayback Machine)

def cdx_list(prefix):
    """Wayback Machine's list of archived URLs under prefix (cached in nz/_sources/)."""
    cache = OUT / "_sources" / ("cdx_" + re.sub(r"[^a-z0-9]+", "_", prefix).strip("_") + ".txt")
    if not (cache.exists() and cache.stat().st_size > 0):
        data = get(CDX.format(urllib.parse.quote(prefix, safe="/")), delay=3)
        if data is None or data.lstrip()[:1] == b"<":
            print(f"  Wayback index unavailable for {prefix}")
            return []
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    out = []
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(" ")
        if len(parts) >= 3 and parts[0].startswith("http"):
            out.append((parts[0], parts[1], parts[2]))
    return out


def circulars(budget):
    rows = []
    for folder, label, prefixes in CIRCULARS:
        docs = {}
        for prefix in prefixes:
            for original, ts, mime in cdx_list(prefix):
                path = urllib.parse.urlsplit(original).path
                name = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
                if "@@" in path or mime != "application/pdf" or not name:
                    continue                      # thumbnails, listing pages
                if not name.lower().endswith(".pdf"):
                    name += ".pdf"
                clean_url = original.split("?")[0]
                # later prefixes (new site) do not replace a copy already found on the old site
                docs.setdefault(name.lower(), (name.lower(), clean_url, ts))
        print(f"{folder}: {len(docs)} PDFs known to the Wayback Machine")
        for key in sorted(docs):
            name, url, ts = docs[key]
            wb = f"https://web.archive.org/web/{ts}id_/{url}"
            dest = OUT / folder / name
            if not save(wb, dest, budget, delay=1.5, check=lambda d: d[:5] == b"%PDF-"):
                continue
            m = re.search(r"(?<!\d)((?:19|20)?\d\d)[-_ ]?(\d\d)(?!\d)", name.replace("iac", " "))
            title = label
            if m:
                year = m.group(1) if len(m.group(1)) == 4 else "20" + m.group(1)
                title = f"{label} {year}-{m.group(2)}"
            extra = re.sub(r"(?i)\.pdf$|amendment[-_ ]?circular|^copy_of_|^iac|no-", "", name)
            extra = re.sub(r"[-_ ]*(?:19|20)?\d\d[-_ ]?\d\d[-_ ]*", " ", extra, count=1)
            extra = re.sub(r"[-_ ]+", " ", extra).strip()
            if extra:
                title += f" ({extra})"
            rows.append((f"{folder}/{name}", title,
                         f"archived {ts[:4]}-{ts[4:6]}-{ts[6:8]}", f"{url} (via {wb})"))
    return rows


def main():
    what = sys.argv[1:] or ["manual", "circulars"]
    OUT.mkdir(parents=True, exist_ok=True)
    budget = Budget()
    index = OUT / "index.tsv"
    old = {}
    if index.exists():                           # keep rows for parts not refreshed in this run
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) == 4:
                old[parts[0]] = tuple(parts)
    rows = []
    if "manual" in what:
        rows += manual(budget)
    else:
        rows += [r for f, r in old.items() if f.startswith("manual/")]
    if "circulars" in what:
        rows += circulars(budget)
    else:
        rows += [r for f, r in old.items() if not f.startswith("manual/")]
    with index.open("w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\n")
        for r in rows:
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in r) + "\n")
    n, size = totals()
    print(f"nz/: {n} files, {size / 1e6:.1f} MB; index.tsv has {len(rows)} rows; "
          f"{len(failed)} failed; cap hit: {budget.hit}; blocked hosts: {sorted(blocked) or 'none'}")
    for u in failed:
        print("  failed:", u)


if __name__ == "__main__":
    main()

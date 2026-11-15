#!/usr/bin/env python3
"""Download IRCC's "Operational instructions and guidelines" (Canada) into ./ca/.

    ./download_ca.py                  program delivery instructions (HTML), operational
                                      bulletins (HTML) and the legacy manual chapters (PDF)
    ./download_ca.py --with-updates   also the ~1,300 individual "update" notices (change log)

What is fetched: every English page under
    https://www.canada.ca/en/immigration-refugees-citizenship/corporate/publications-manuals/operational-bulletins-manuals...
found by following links from that index page, plus the manual PDFs it links to
(/content/dam/ircc/.../manuals/...). Nothing outside that section is followed.

www.canada.ca does not answer scripted requests from this machine (the connection is
accepted and then left hanging), so every page is read from the Internet Archive's
Wayback Machine instead: the most recent capture of each URL, unmodified ("id_" form).
The capture date of each file is recorded in ca/index.tsv.

Files already downloaded are skipped, so the script can be re-run; a re-run re-reads the
saved pages to find links, retries anything that failed and rewrites ca/index.tsv
(columns: file, title, date modified, source URL, Wayback capture).
"""
import gzip
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ca"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"

SITE = "https://www.canada.ca"
SECTION = "/en/immigration-refugees-citizenship/corporate/publications-manuals/operational-bulletins-manuals"
WAYBACK = "https://web.archive.org/web/%sid_/%s"
STAMP = time.strftime("%Y%m%d%H%M%S")     # "closest to now" = the latest capture

DELAY = 2.0                # seconds between requests (sequential)
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000

WITH_UPDATES = "--with-updates" in sys.argv


class Blocked(Exception):
    pass


def fetch(path):
    """Latest Wayback capture of canada.ca<path>. Returns (bytes, capture stamp) or (None, reason)."""
    url = WAYBACK % (STAMP, SITE + urllib.parse.quote(path, safe="/%()-_.~"))
    err = "?"
    for attempt in range(3):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                m = re.search(r"/web/(\d{14})", r.geturl())
                data = r.read()
                if data[:2] == b"\x1f\x8b":        # the archive passes on canada.ca's gzip encoding
                    data = gzip.decompress(data)
                fetch.misses = 0
                return data, (m.group(1) if m else "")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} from web.archive.org") from e
            if e.code == 404:
                return None, "not archived (404)"
            err = f"HTTP {e.code}"
        except Exception as e:                      # noqa: BLE001 - report and retry
            err = str(e)
        print(f"  retry {attempt + 1} ({err}) {path}", flush=True)
        time.sleep(60 * (attempt + 1))              # the archive refuses connections when busy: wait
    fetch.misses += 1
    if fetch.misses >= 5:                           # it keeps refusing: give up rather than hammer it
        raise Blocked("web.archive.org failed 5 URLs in a row; " + err)
    return None, err


fetch.misses = 0


def dest_for(path):
    if path.lower().endswith(".pdf"):
        if "/publications-manuals/" in path:
            return OUT / "attachments" / path.rsplit("/", 1)[-1]
        m = re.search(r"/manuals/(.+)$", path)
        return OUT / "manuals" / (m.group(1) if m else path.rsplit("/", 1)[-1])
    rel = path[len(SECTION):].lstrip("/")
    return OUT / (rel if "/" in path[len(SECTION):] else "operational-instructions-and-guidelines.html")


def wanted(path):
    """Is this link part of the operational-instructions section?"""
    low = path.lower()
    if low.endswith(".pdf"):
        # manual chapters, and attachments to the instructions; application forms (kits/forms) are left out
        return (path.startswith("/content/dam/ircc/") and "/english/" in low
                and ("/manuals/" in low or "/publications-manuals/" in low))
    if not (path.startswith(SECTION) and low.endswith(".html")):
        return False
    if not WITH_UPDATES and path.startswith(SECTION + "/updates/"):
        return False
    return True


def links(page):
    m = re.search(r"<main.*?</main>", page, re.S)
    out = []
    for href in re.findall(r'<a\b[^>]*?\bhref="([^"]+)"', m.group(0) if m else page):
        href = html.unescape(href).strip()
        u = urllib.parse.urlsplit(urllib.parse.urljoin(SITE + SECTION + ".html", href))
        if u.netloc in ("www.canada.ca", "canada.ca") and u.path not in out:
            out.append(u.path)
    return out


def meta(page):
    t = re.search(r"<title>(.*?)</title>", page, re.S)
    title = html.unescape(re.sub(r"\s+", " ", t.group(1))).strip() if t else ""
    title = re.sub(r"\s*[-–—]\s*Canada\.ca$", "", title)
    d = re.search(r'name="dcterms\.modified"[^>]*content="([^"]+)"', page)
    return title, (d.group(1) if d else "")


def looks_ok(path, data):
    if path.lower().endswith(".pdf"):
        return data[:5] == b"%PDF-"
    head = data[:4000].lower()
    return b"<html" in head and b"<main" in data and b"we couldn't find that web page" not in data.lower()


def write_index(rows):
    lines = ["file\ttitle\tdate modified\tsource URL\twayback capture"]
    for path in sorted(rows, key=lambda p: str(dest_for(p))):
        title, mod, cap = rows[path]
        lines.append("\t".join([str(dest_for(path).relative_to(OUT)), title.replace("\t", " "), mod, SITE + path, cap]))
    (OUT / "index.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    captures = {}                                  # source URL -> capture stamp, from the last run
    if (OUT / "index.tsv").exists():
        for line in (OUT / "index.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 5:
                captures[c[3]] = c[4]

    start = SECTION + ".html"
    queue, later, seen = deque([start]), deque(), {start}
    rows, failed, skipped_pdf = {}, [], set()
    files = nbytes = new = 0
    stopped = ""
    try:
        while queue or later:
            path = queue.popleft() if queue else later.popleft()
            dest = dest_for(path)
            if dest.exists() and dest.stat().st_size > 0:
                data, cap = dest.read_bytes(), captures.get(SITE + path, "")
            else:
                if files >= MAX_FILES or nbytes >= MAX_BYTES:
                    stopped = "cap reached"
                    failed.append((path, "not fetched: cap reached"))
                    continue
                data, cap = fetch(path)
                if data is None:
                    failed.append((path, cap))
                    print(f"  FAILED {path}: {cap}", flush=True)
                    continue
                if not looks_ok(path, data):
                    failed.append((path, "capture is not a real page/PDF"))
                    print(f"  BAD CONTENT {path}", flush=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                new += 1
                if new % 25 == 0:
                    print(f"  {files + 1} files, {nbytes / 1e6:.0f} MB, {len(queue) + len(later)} queued", flush=True)
                    write_index(rows)
            files += 1
            nbytes += len(data)
            if path.lower().endswith(".pdf"):
                rows[path] = (dest.name, "", cap)
                continue
            page = data.decode("utf-8", "replace")
            rows[path] = (*meta(page), cap)
            for link in links(page):
                if link in seen:
                    continue
                seen.add(link)
                if wanted(link) and "/bulletins-" in link:
                    later.append(link)             # old operational bulletins: after the PDIs
                elif wanted(link):
                    queue.append(link)
                elif link.lower().endswith(".pdf"):
                    skipped_pdf.add(link)
    except Blocked as e:
        stopped = f"stopped: {e}"
        failed.extend((p, "not fetched: " + stopped) for p in [*queue, *later])
    except KeyboardInterrupt:
        stopped = "interrupted"

    write_index(rows)
    (OUT / "failed.tsv").write_text(
        "".join(f"{SITE + p}\t{why}\n" for p, why in failed), encoding="utf-8")
    (OUT / "skipped-pdf-links.txt").write_text(
        "".join(SITE + p + "\n" for p in sorted(skipped_pdf)), encoding="utf-8")
    print(f"ca: {files} files ({nbytes / 1e6:.1f} MB), {new} new, {len(failed)} failed, "
          f"{len(skipped_pdf)} out-of-scope PDF links not followed. {stopped}")


if __name__ == "__main__":
    main()

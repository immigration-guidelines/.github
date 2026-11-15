#!/usr/bin/env python3
"""Download the Finnish Immigration Service's published application guidelines.

    ./download_fi.py

Finland: Maahanmuuttovirasto (Migri) "Soveltamisohjeet" - the internal guidelines
on applying the law that Migri publishes at https://migri.fi/soveltamisohjeet
(Finnish only; Migri states they are not translated).

The listing page itself sits behind a Cloudflare browser check, which this script
does not try to get around: if the live page refuses, the most recent Internet
Archive (Wayback Machine) copy of the listing is used instead. The PDFs are
fetched from migri.fi directly; any that migri.fi refuses are taken from the
Wayback Machine if it has them, and otherwise reported.

Files already downloaded are skipped, so the script can be re-run. fi/index.tsv
lists what was saved and where it came from.
"""
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "fi"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
LISTING = "https://migri.fi/soveltamisohjeet"
PAUSE = 0.5
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000


def get(url, retry=True):
    """One polite request. Returns (bytes, None) or (None, reason). Never retries a refusal."""
    time.sleep(PAUSE)
    # non-ASCII characters in the path must be percent-encoded
    url = urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read(), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"                # a refusal is final
    except Exception as e:                          # noqa: BLE001 - broken transfer: one more go
        if retry:
            time.sleep(5)
            return get(url, retry=False)
        return None, str(e)


def fetch_file(url, dest, tries=4):
    """Download url to dest via dest.part, resuming a broken transfer with a Range request.
    Returns None on success or the reason for failure. A refusal (HTTP error) is final."""
    part = dest.with_name(dest.name + ".part")
    quoted = urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")
    why = "?"
    for attempt in range(tries):
        time.sleep(PAUSE if attempt == 0 else 10)
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": UA}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(quoted, headers=headers), timeout=120) as r:
                if have and r.status != 206:        # server ignored the range: start over
                    have = 0
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                length = r.headers.get("Content-Length")
                if length is not None and part.stat().st_size != have + int(length):
                    why = "transfer cut short"
                    continue
            with open(part, "rb") as f:
                if dest.suffix == ".pdf" and f.read(4) != b"%PDF":
                    part.unlink()
                    return "response is not a PDF"
            part.replace(dest)
            return None
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}"
        except Exception as e:                      # noqa: BLE001 - broken transfer: resume
            why = str(e)
    return why


def slug(s, n=110):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n] or "x"


def listing():
    """Return (html text, where it came from)."""
    data, why = get(LISTING)
    if data is not None and b"/documents/" in data:
        return data.decode("utf-8", "replace"), LISTING
    print(f"live listing not usable ({why or 'no document links / bot check'}); using the Wayback Machine")
    data, why = get("https://archive.org/wayback/available?url=migri.fi/soveltamisohjeet&timestamp="
                    + datetime.now(timezone.utc).strftime("%Y%m%d"))
    if data is None:
        sys.exit(f"Wayback availability lookup failed: {why}")
    snap = json.loads(data)["archived_snapshots"].get("closest")
    if not snap:
        sys.exit("no Wayback snapshot of the listing")
    src = f"https://web.archive.org/web/{snap['timestamp']}id_/{LISTING}"
    data, why = get(src)
    if data is None:
        sys.exit(f"Wayback listing fetch failed: {why}")
    return data.decode("utf-8", "replace"), src


def documents(page):
    """Yield (title, date, url) for each document link in the listing's content area."""
    seen = set()
    for href, label in re.findall(r'<a[^>]+href="([^"]*/documents/[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        url = urllib.parse.urljoin(LISTING, html.unescape(href))
        url = re.sub(r"^https?://web\.archive\.org/web/[^/]+/", "", url)
        path = urllib.parse.urlsplit(url).path
        if not re.search(r"\.(pdf|docx?|rtf|odt)/", path + "/", re.I):
            continue                                # images, icons and the like
        if path in seen:
            continue
        seen.add(path)
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", label))).strip()
        title = re.sub(r"\s*(\(pdf\))?\s*(\.pdf)?$", "", title, flags=re.I)
        t = re.search(r"[?&]t=(\d{13})", url)       # Liferay: last-modified time in ms
        date = datetime.fromtimestamp(int(t.group(1)) / 1000, timezone.utc).strftime("%Y-%m-%d") if t else ""
        yield title, date, url


def main():
    OUT.mkdir(exist_ok=True)
    page, listing_src = listing()
    print(f"listing: {listing_src}")
    rows, failed, total, live_refused = [], [], 0, False
    docs = list(documents(page))
    names = [slug(title) for title, _, _ in docs]
    for (title, date, url), name in zip(docs, names):
        if len(rows) >= MAX_FILES or total >= MAX_BYTES:
            failed.append((title, url, "not attempted: file/size limit reached"))
            continue
        path = urllib.parse.urlsplit(url).path
        if names.count(name) > 1:                   # same link text twice: tell them apart by document id
            name += "_" + path.rsplit("/", 1)[-1][:8]
        ext = re.search(r"\.(\w{3,4})/[^/]*$", path)
        dest = OUT / f"{name}.{ext.group(1).lower() if ext else 'pdf'}"
        src = url
        if not (dest.exists() and dest.stat().st_size > 0):
            why = "migri.fi refused earlier" if live_refused else fetch_file(url, dest)
            if why in ("HTTP 403", "HTTP 429", "migri.fi refused earlier"):
                live_refused = True                 # do not keep knocking; use the archive
                src = "https://web.archive.org/web/2id_/" + url.split("?")[0]
                why2 = fetch_file(src, dest)
                why = why2 and f"migri.fi: {why}; Wayback: {why2}"
            if why:
                print(f"  FAILED {title}: {why}")
                failed.append((title, url, why))
                continue
            print(f"  saved {dest.name} ({dest.stat().st_size:,} bytes)")
        total += dest.stat().st_size
        rows.append((dest.name, title, date, src))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource URL\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"{len(rows)} documents, {total:,} bytes in {OUT}; {len(failed)} failed")
    for title, url, why in failed:
        print(f"  missing: {title}\t{url}\t{why}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download Migrationsverket's (Sweden) published legal guidance from Lifos.

    ./download_se.py                  scan document numbers 44000..newest (about 2020 onwards)
    ./download_se.py --low 30000      scan further back (each number is one request, ~1.5 s)
    ./download_se.py --index-only     just rebuild se/index.tsv from what is already scanned

What is kept: documents whose Lifos subject words include "Rättsliga ställningstaganden
och kommentarer" or "Styrsignal", or whose title starts with "Rättsligt ställningstagande",
"Rättslig kommentar" etc. Country-of-origin reports, court decisions and everything else
are looked at (the page has to be read to know what it is) but not downloaded.

Why a number scan: Lifos' robots.txt disallows /sokning* (the search pages) for scripts,
so the documents are enumerated through /dokument?documentSummaryId=N, which is allowed.
Numbers already looked at are remembered in se/.cache/scan.jsonl and files already
downloaded are skipped, so the script can be stopped and re-run. It stops at once on
HTTP 403/429.
"""
import argparse
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "se"
CACHE = OUT / ".cache"
SCAN = CACHE / "scan.jsonl"
BASE = "https://lifos.migrationsverket.se"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 0.4
MAX_BYTES = 1_000_000_000
MAX_FILES = 3000
# Lifos' certificate chains to Let's Encrypt "Root YR", which older trust stores lack.
# Let's Encrypt publishes that root cross-signed by ISRG Root X1; it is fetched (over
# normally verified TLS) and added as an extra CA. Verification is never switched off.
CROSS_ROOT = "https://letsencrypt.org/certs/gen-y/root-yr-by-x1.pem"

SUBJECTS = ("Rättsliga ställningstaganden och kommentarer", "Styrsignal")
TITLE_RE = re.compile(r"^\s*(Rättsligt ställningstagande|Rättslig kommentar|Rättschefens rättsliga"
                      r"|Rättslig styrning|Styrsignal|Handbok i migrationsärenden)", re.I)
NOT_SOURCE = ("Migrationsanalys",)        # the country-information unit


class Blocked(Exception):
    pass


_ctx = ssl.create_default_context()
_last = [0.0]


def fetch(url, tries=2):
    """Return (status, bytes, headers). Raises Blocked on 403/429."""
    err = None
    for attempt in range(tries):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120, context=_ctx) as r:
                data = r.read()
                _last[0] = time.time()
                return r.status, data, r.headers
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} for {url}")
            if e.code == 404:
                return 404, b"", e.headers
            err = e
        except Exception as e:                      # noqa: BLE001 - report and retry
            _last[0] = time.time()
            err = e
        time.sleep(5 * (attempt + 1))
    print(f"  FAILED {url}: {err}", flush=True)
    return None, b"", None


def setup_tls():
    try:
        urllib.request.urlopen(urllib.request.Request(BASE + "/robots.txt", headers={"User-Agent": UA}),
                               timeout=60, context=_ctx).read()
        return
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} for {BASE}")
        return
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
    pem = CACHE / "root-yr-by-x1.pem"
    if not pem.exists():
        time.sleep(DELAY)
        req = urllib.request.Request(CROSS_ROOT, headers={"User-Agent": UA})
        data = urllib.request.urlopen(req, timeout=60).read()      # system trust store
        if b"BEGIN CERTIFICATE" not in data:
            sys.exit("could not get Let's Encrypt cross-signed root")
        pem.write_bytes(data)
    _ctx.load_verify_locations(cafile=str(pem))


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse(page):
    t = page.decode("utf-8", "replace")
    g = lambda rx: (re.search(rx, t, re.S) or [None, ""])[1]      # noqa: E731
    return {
        "title": clean(g(r'class="DocumentHeader">(.*?)</div>')),
        "date": clean(g(r'Upphovsdat: </div><div class="metadataDisplayRightColumn">([^<]*)')),
        "source": clean(g(r"Referens:.*?<b>(.*?)<div")).rstrip(", "),
        "subjects": clean(g(r'id="metadataDisplaySubjectword">(.*?)</div>')),
        "att": [[int(a), clean(n)] for a, n in
                re.findall(r'href="/dokument\?documentAttachmentId=(\d+)"[^>]*>([^<]*)', t)],
    }


def wanted(rec):
    if rec.get("status") != 200 or any(rec["source"].startswith(s) for s in NOT_SOURCE):
        return False
    subj = [s.strip() for s in rec["subjects"].split(",")]
    return any(s in subj for s in SUBJECTS) or bool(TITLE_RE.match(rec["title"]))


def slug(s, n=100):
    s = s.translate(str.maketrans("åäöÅÄÖé", "aaoAAOe"))
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n].rstrip("-.") or "x"


def ext_of(data, name):
    if data[:5] == b"%PDF-":
        return ".pdf"
    if data[:2] == b"PK":
        m = re.search(r"\.(docx|xlsx|pptx|zip)$", name, re.I)
        return "." + m.group(1).lower() if m else ".zip"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return ".doc"
    return None


def existing(doc, att):
    hits = sorted(OUT.glob(f"lifos-{doc}-{att}-*"))
    return hits[0] if hits and hits[0].stat().st_size > 0 else None


def load_scan():
    recs = {}
    if SCAN.exists():
        for line in SCAN.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                recs[r["id"]] = r
    return recs


def newest_id():
    st, data, _ = fetch(BASE + "/lifos-aktuellt.html")
    ids = [int(x) for x in re.findall(rb"documentSummaryId=(\d+)", data)]
    if not ids:
        sys.exit("could not find the newest document number on lifos-aktuellt.html")
    return max(ids)


def write_index(recs):
    rows = []
    for i in sorted(recs, reverse=True):
        r = recs[i]
        if not wanted(r):
            continue
        for att, _name in r["att"]:
            f = existing(i, att)
            if f:
                rows.append((f.name, r["title"], r["date"], f"{BASE}/dokument?documentAttachmentId={att}"))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as fh:
        fh.write("file\ttitle\tdate\tsource URL\n")
        for row in rows:
            fh.write("\t".join(c.replace("\t", " ") for c in row) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--low", type=int, default=44000, help="lowest document number to look at")
    ap.add_argument("--high", type=int, default=0, help="highest document number (default: newest)")
    ap.add_argument("--index-only", action="store_true")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    recs = load_scan()
    if a.index_only:
        print(len(write_index(recs)), "files in index.tsv")
        return
    files = [p for p in OUT.glob("lifos-*") if p.is_file()]
    nfiles, nbytes = len(files), sum(p.stat().st_size for p in files)
    try:
        setup_tls()
        high = a.high or newest_id() + 30            # a little headroom for brand-new numbers
        print(f"scanning document numbers {high} down to {a.low}", flush=True)
        with open(SCAN, "a", encoding="utf-8") as log:
            for i in range(high, a.low - 1, -1):
                r = recs.get(i)
                # numbers above the newest known one may be filled later: look again
                if r is None or (r["status"] == 404 and i > high - 60):
                    st, data, _ = fetch(f"{BASE}/dokument?documentSummaryId={i}")
                    if st is None:
                        continue
                    r = {"id": i, "status": st}
                    if st == 200:
                        r.update(parse(data))
                    recs[i] = r
                    log.write(json.dumps(r, ensure_ascii=False) + "\n")
                    log.flush()
                if not wanted(r):
                    continue
                for att, name in r["att"]:
                    if existing(i, att):
                        continue
                    if nfiles >= MAX_FILES or nbytes >= MAX_BYTES:
                        print(f"limit reached at document {i}; stopping", flush=True)
                        raise StopIteration
                    st, data, _ = fetch(f"{BASE}/dokument?documentAttachmentId={att}")
                    ext = ext_of(data, name) if st == 200 else None
                    if not ext:
                        print(f"  SKIPPED {i}/{att}: status {st}, not a document ({data[:20]!r})", flush=True)
                        continue
                    dest = OUT / f"lifos-{i}-{att}-{slug(r['title'])}{ext}"
                    dest.write_bytes(data)
                    nfiles += 1
                    nbytes += len(data)
                    print(f"  {r['date']} {dest.name} ({len(data) // 1024} kB)", flush=True)
                if not r["att"]:
                    print(f"  NO ATTACHMENT (access-restricted?) {i}: {r['title']}", flush=True)
    except Blocked as e:
        print(f"BLOCKED: {e} - stopping, not retrying", flush=True)
    except (StopIteration, KeyboardInterrupt):
        pass
    rows = write_index(recs)
    done = [i for i in recs if i >= a.low]
    print(f"{len(rows)} files, {nbytes / 1e6:.1f} MB in {OUT}; "
          f"{len(done)} document numbers looked at down to {min(done) if done else '-'}")


if __name__ == "__main__":
    main()

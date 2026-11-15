#!/usr/bin/env python3
"""Download the United States' published immigration adjudication manuals into us/.

    ./download_us.py            everything below
    ./download_us.py uscis      USCIS Policy Manual: the site's own full-manual HTML export
                                (uscis.gov/book/export/html/68600), table of contents, Updates list
    ./download_us.py afm        retired Adjudicator's Field Manual: the chapter PDFs USCIS still hosts
    ./download_us.py fam        State Department 9 FAM (Visas): every section listed by fam.state.gov's
                                table-of-contents API, plus the change-transmittal list
    ./download_us.py alerts     USCIS policy-alert PDFs linked from the Policy Manual's Updates list
                                (the uscis step saves that list first)

Files already downloaded are skipped, so the script can be re-run; delete a file to refresh it.
us/index.tsv is rewritten on every run. Requests are sequential: 10 s apart for uscis.gov
(its robots.txt asks for Crawl-delay: 10), 1 s apart for fam.state.gov. A 403/429 answer stops
that site's download instead of retrying.
"""
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
US = ROOT / "us"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
MAX_FILES, MAX_BYTES = 3000, 1_000_000_000

USCIS = "https://www.uscis.gov"
FAM = "https://fam.state.gov"
DELAY = {"www.uscis.gov": 10.0, "fam.state.gov": 1.0}
last_request = {}
contexts = {}
rows = []          # (file, title, date, url)
problems = []


class Blocked(Exception):
    pass


def fam_context():
    """fam.state.gov does not send its intermediate certificate, so normal verification fails.
    Do what a browser does: read the "CA Issuers" URL from the server certificate, fetch that
    intermediate and add it to the default trust store. The chain is still verified up to a
    root this machine already trusts; verification is never switched off."""
    ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(urllib.request.Request(FAM + "/", headers={"User-Agent": UA}),
                               timeout=60, context=ctx).close()
        return ctx
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
    time.sleep(1)
    leaf = ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate(("fam.state.gov", 443)))
    m = re.search(rb"http://[\x21-\x7e]+?\.(?:crt|cer)", leaf)
    if not m:
        raise Blocked("fam.state.gov: certificate chain incomplete and no CA Issuers URL found")
    issuer = urllib.request.urlopen(m.group().decode(), timeout=60).read()
    if not issuer.startswith(b"-----BEGIN"):
        issuer = ssl.DER_cert_to_PEM_cert(issuer).encode()
    ctx.load_verify_locations(cadata=issuer.decode())
    return ctx


def get(url, tries=2):
    host = urllib.parse.urlsplit(url).hostname
    if host == "fam.state.gov" and host not in contexts:
        contexts[host] = fam_context()
    err = None
    for attempt in range(tries):
        wait = DELAY.get(host, 1.0) - (time.time() - last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300, context=contexts.get(host)) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"{host} answered {e.code} for {url}")
            err = e
            if e.code == 404:
                break
        except Exception as e:                      # noqa: BLE001 - report and retry once
            err = e
        finally:
            last_request[host] = time.time()
        time.sleep(5)
    print(f"  FAILED {url}: {err}")
    problems.append(f"{url}: {err}")
    return None


def over_cap():
    files = [p for p in US.rglob("*") if p.is_file() and "coi" not in p.relative_to(US).parts[:1]]
    return len(files) >= MAX_FILES or sum(p.stat().st_size for p in files) >= MAX_BYTES


def save(url, dest, check=None):
    """Download url to dest unless it is already there. check(data) must be true for the
    content to be kept (guards against error/challenge pages). Returns the bytes or None."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes()
    if over_cap():
        problems.append(f"{url}: not downloaded, size/file cap reached")
        return None
    data = get(url)
    if data is None:
        return None
    if check and not check(data):
        print(f"  UNEXPECTED CONTENT, not saved: {url}")
        problems.append(f"{url}: unexpected content (error or challenge page?)")
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  saved {dest.relative_to(ROOT)} ({len(data):,} bytes)")
    return data


def add(dest, title, date, url):
    rows.append((str(dest.relative_to(US)), " ".join(title.split()), date, url))


def text_of(markup):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", t)).split())


def is_pdf(data):
    return data[:5] == b"%PDF-"


# ---------------------------------------------------------------- USCIS Policy Manual

def uscis():
    out = US / "uscis-policy-manual"
    print("USCIS Policy Manual")
    # The manual is a Drupal "book"; the printer-friendly export of its root node holds every
    # volume, part and chapter (with footnotes) in one HTML file.
    front = get(USCIS + "/policy-manual")
    export = "/book/export/html/68600"
    if front:
        m = re.search(r'href="(/book/export/html/\d+)"', front.decode("utf-8", "replace"))
        if m:
            export = m.group(1)
    dest = out / "policy-manual-full.html"
    data = save(USCIS + export, dest, lambda d: d.count(b"book-node-depth") > 400)
    if data:
        m = re.search(r"Current as of</span>\s*<span[^>]*>\s*([^<]+)<", data.decode("utf-8", "replace"))
        add(dest, "USCIS Policy Manual - full text, all volumes (printer-friendly export)",
            m.group(1).strip() if m else "", USCIS + export)
    for name, title in (("table-of-contents", "USCIS Policy Manual - Table of Contents"),
                        ("updates", "USCIS Policy Manual - Updates (list of policy alerts)")):
        dest = out / f"{name}.html"
        if save(f"{USCIS}/policy-manual/{name}", dest, lambda d: b"policy-manual" in d and len(d) > 50000):
            add(dest, title, "", f"{USCIS}/policy-manual/{name}")


def alerts():
    """Policy-alert PDFs linked from the Policy Manual's Updates list."""
    out = US / "uscis-policy-manual" / "policy-alerts"
    print("USCIS policy alerts")
    src = US / "uscis-policy-manual" / "updates.html"
    if not src.exists():
        problems.append("alerts: updates.html missing (run the uscis step first)")
        return
    markup = src.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(
        r'update_header[^>]*>([^<]+)</div>.*?'
        r'<time datetime="([^"]+)"[^>]*>.*?'
        r'<a href="(https://www\.uscis\.gov/sites/default/files/document/policy-manual-updates/[^"]+\.pdf)"',
        re.S)
    seen = set()
    for title, stamp, url in pattern.findall(markup):
        if url in seen:
            continue
        seen.add(url)
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        dest = out / name
        if save(url, dest, is_pdf):
            add(dest, html.unescape(title).strip(), stamp[:10], url)
    if not seen:
        problems.append("alerts: no policy-alert PDF links found in updates.html")


def afm():
    """The Adjudicator's Field Manual was retired in 2020; USCIS keeps the not-yet-superseded
    chapters as PDFs, linked from the Policy Manual pages."""
    out = US / "afm-retired"
    print("Adjudicator's Field Manual (retired)")
    pages = b""
    for name in ("policy-manual-full.html", "table-of-contents.html", "updates.html"):
        p = US / "uscis-policy-manual" / name
        if p.exists():
            pages += p.read_bytes()
    names = sorted(set(re.findall(rb"/sites/default/files/document/policy-manual-afm/([A-Za-z0-9_.-]+\.pdf)", pages)))
    if not names:
        problems.append("AFM: no PDF links found (run the uscis step first)")
    for n in names:
        n = n.decode()
        url = f"{USCIS}/sites/default/files/document/policy-manual-afm/{n}"
        dest = out / n
        if save(url, dest, is_pdf):
            m = re.match(r"afm(\d+)-external", n)
            title = f"Adjudicator's Field Manual (retired) - Chapter {m.group(1)}" if m else \
                "AFM to Policy Manual crosswalk" if "crosswalk" in n else n
            add(dest, title, "", url)


# ---------------------------------------------------------------- 9 FAM

def fam():
    out = US / "9fam"
    print("9 FAM (Visas)")
    tree_url = FAM + "/api/Tree/GetTreeByVolumeId?Id=09FAM"
    dest = out / "toc-tree.json"
    data = save(tree_url, dest, lambda d: d.lstrip()[:1] == b"[")
    if not data:
        return
    add(dest, "9 FAM Visas - table of contents (JSON tree)", "", tree_url)

    sections = []

    def walk(items):
        for it in items:
            if it.get("url"):
                sections.append((it["url"], it.get("text") or ""))
            walk(it.get("items") or [])
    walk(json.loads(data))

    seen = set()
    for path, title in sections:
        if path in seen:
            continue
        seen.add(path)
        url = urllib.parse.urljoin(FAM, path)
        dest = out / Path(path).name
        page = save(url, dest, lambda d: b"FAM" in d[:3000] and b"<html" in d[:500].lower())
        if not page:
            continue
        txt = page.decode("cp1252", "replace")
        m = re.search(r"\(CT:[A-Z]+-\d+;[^)]*?(\d{2}-\d{2}-\d{4})\)", text_of(txt))
        date = ""
        if m:                                   # MM-DD-YYYY -> YYYY-MM-DD
            mm, dd, yy = m.group(1).split("-")
            date = f"{yy}-{mm}-{dd}"
        add(dest, "9 FAM " + title, date, url)
        # pictures embedded in a section (flow charts, sample documents)
        for src in sorted(set(re.findall(r'<img[^>]+src="([^"]+)"', txt, flags=re.I))):
            if src.startswith(("http:", "https:", "data:", "//")):
                continue
            iurl = urllib.parse.urljoin(url, src)
            idest = out / urllib.parse.unquote(urllib.parse.urlsplit(iurl).path).split("/FAM/09FAM/")[-1]
            if out.resolve() in idest.resolve().parents and save(iurl, idest, lambda d: b"<html" not in d[:200].lower()):
                add(idest, f"9 FAM {title.split(' ')[0]} - image", "", iurl)

    url = FAM + "/Volumes/Changes/09FAM"
    dest = out / "changes.html"
    if save(url, dest, lambda d: b"Change Transmittals" in d):
        add(dest, "9 FAM Visas - recent change transmittals", "", url)


def main():
    steps = {"uscis": uscis, "alerts": alerts, "afm": afm, "fam": fam}
    todo = sys.argv[1:] or list(steps)
    for name in todo:
        if name not in steps:
            sys.exit(__doc__)
    US.mkdir(exist_ok=True)
    for name in todo:
        try:
            steps[name]()
        except Blocked as e:
            print(f"  BLOCKED: {e}")
            problems.append(f"blocked: {e}")
    # keep index rows of steps that were not run this time
    index = US / "index.tsv"
    have = {r[0] for r in rows}
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if len(f) == 4 and f[0] not in have and (US / f[0]).exists():
                rows.append(tuple(f))
    with index.open("w", encoding="utf-8") as fh:
        fh.write("file\ttitle\tdate\tsource URL\n")
        for r in sorted(rows):
            fh.write("\t".join(c.replace("\t", " ") for c in r) + "\n")
    print(f"{len(rows)} files indexed in {index}")
    if problems:
        print(f"{len(problems)} problem(s):")
        for p in problems:
            print("  " + p)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download the Executive Office for Immigration Review's guidance to immigration judges and the
Board of Immigration Appeals into us/eoir/.

    python3 download_us_eoir.py                 everything
    python3 download_us_eoir.py manual memos    one or both sources

  manual   The EOIR Policy Manual, every chapter page, saved as .html as served:
             Part I    general EOIR policies (introduction, chapters 1-9)
             Part II   Immigration Court Practice Manual
             Part III  Board of Immigration Appeals Practice Manual
             Part VI   Uniform Docketing System Manual
             Part VII  appendices
           Part IV (OCAHO Practice Manual: employer-sanctions and related cases before the Office of
           the Chief Administrative Hearing Officer, not cases of individual immigrants) is left out.
  memos    Part V of the Policy Manual: the lists of Policy Memoranda (PM), Operating Policies and
           Procedures Memoranda (OPPM) and memoranda by topic, and every memorandum they link
           (PDF, as published).

Source: https://www.justice.gov/eoir/policy-manual-eoir. robots.txt of www.justice.gov asks for
Crawl-delay: 10 and excludes ?page= / &page= addresses (not used here). Sequential, 10 s between
requests, files already present are skipped. us/eoir/index.tsv and us/eoir/not-obtained.tsv are
rewritten on every run. HTTP 403/429 or three connection failures in a row end the run.
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
OUT = ROOT / "us" / "eoir"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
BASE = "https://www.justice.gov"
PM = "/eoir/policy-manual-eoir"
PAUSE = 10.0                         # robots.txt Crawl-delay
MAX_FILES, MAX_BYTES = 1500, 500_000_000
HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "part", "date_basis", "listed_on"]
PARTS = {"part-I": "part-I-general", "part-II": "part-II-immigration-court-practice-manual",
         "part-III": "part-III-bia-practice-manual", "part-V": "part-V-memoranda",
         "part-VI": "part-VI-uniform-docketing-system-manual", "part-VII": "part-VII-appendices"}
MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}

last_request = [0.0]
fails = [0]
failed = []
rows = {}


class Blocked(Exception):
    pass


def get(url):
    wait = PAUSE - (time.time() - last_request[0])
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
            ctype = r.headers.get("Content-Type", "")
            disp = r.headers.get("Content-Disposition", "")
        fails[0] = 0
        return data, ctype, disp, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} for {url}")
        fails[0] = 0
        return None, "", "", f"HTTP {e.code}"
    except Exception as e:                              # noqa: BLE001
        fails[0] += 1
        if fails[0] >= 3:
            raise Blocked(f"three connection failures in a row, last {e!r} for {url}")
        return None, "", "", f"connection failed: {e!r}"
    finally:
        last_request[0] = time.time()


def clean(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def main_part(text):
    m = re.search(r"<main.*?</main>", text, re.S)
    return m.group(0) if m else text


def page_date(text):
    m = re.search(r'(?:Updated|Last updated|Revised)\s*:?\s*(?:<[^>]*>\s*)*([A-Z][a-z]+ \d{1,2}, \d{4})', text)
    if not m:
        m = re.search(r'<time[^>]*datetime="(\d{4}-\d\d-\d\d)', text)
        return (m.group(1), "page time element") if m else ("", "")
    mo, d, y = re.match(r"(\w+) (\d+), (\d+)", m.group(1)).groups()
    if mo.lower() not in MONTHS:
        return "", ""
    return f"{y}-{MONTHS[mo.lower()]:02d}-{int(d):02d}", "page 'Updated' date"


def doc_date(title):
    m = re.search(r"\b(%s)\s+(\d{1,2}),\s+((?:19|20)\d\d)\b" % "|".join(MONTHS), title, re.I)
    if m:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}", "stated in link text"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/((?:19|20)\d\d)\b", title)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", "stated in link text"
    m = re.search(r"\b(?:PM|OPPM)\s*(\d\d)-\d\d", title)
    if m:
        y = int(m.group(1))
        return (f"{1900 + y if y > 80 else 2000 + y}", "year of memorandum number")
    return "", ""


def load_index():
    have = {}
    idx = OUT / "index.tsv"
    if idx.exists():
        lines = idx.read_text(encoding="utf-8").splitlines()
        head = lines[0].split("\t")
        for line in lines[1:]:
            row = dict(zip(head, line.split("\t")))
            if (OUT / row["file"]).is_file():
                have[row["source_url"]] = row
    return have


def total():
    files = [p for p in OUT.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def part_of(path):
    m = re.match(re.escape(PM) + r"/(part-[IVX]+)", path)
    return m.group(1) if m else ""


def save(rel, data):
    dest = OUT / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  saved {rel} ({len(data):,} bytes)", flush=True)


def run(todo, have):
    data, _, _, why = (None, "", "", None)
    start = BASE + PM
    queue, seen = [(start, "", "")], set()
    docs = {}
    while queue:
        url, label, parent = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        path = urllib.parse.urlsplit(url).path
        part = part_of(path)
        want = (part == "part-V" and "memos" in todo) or (part and part != "part-V" and part in PARTS and "manual" in todo) \
            or url == start
        if not want:
            continue
        old = have.get(url)
        if old:
            data = (OUT / old["file"]).read_bytes()
            rows[old["file"]] = old
        else:
            n, size = total()
            if n >= MAX_FILES or size >= MAX_BYTES:
                failed.append((label, "", url, "not downloaded: size/file cap reached"))
                continue
            data, ctype, _, why = get(url)
            if data is None:
                print(f"  FAILED {url}: {why}", flush=True)
                failed.append((label or "policy manual page", "", url, why))
                continue
            text = data.decode("utf-8", "replace")
            if "text/html" not in ctype or "<main" not in text or "Page not found" in text[:5000]:
                failed.append((label, "", url, "unexpected content (error page?)"))
                continue
            m = re.search(r"<title>(.*?)</title>", text, re.S)
            title = clean(m.group(1)).replace(" | United States Department of Justice", "") if m else label
            date, basis = page_date(main_part(text))
            sub = PARTS.get(part, "")
            stem = path[len(PM):].strip("/").replace("/", "_") or "index"
            if sub:
                stem = stem.split("_", 1)[-1] if "_" in stem else "index"
            rel = f"policy-manual/{sub + '/' if sub else ''}{stem}.html"
            save(rel, data)
            rows[rel] = {"file": rel, "title": title, "date": date, "source_url": url, "kind": "guidance",
                         "title_en": "", "part": part or "contents", "date_basis": basis, "listed_on": parent}
            have[url] = rows[rel]
        text = data.decode("utf-8", "replace")
        body = main_part(text)
        for href, lab in re.findall(r'<a\b[^>]*?href="([^"#]+)"[^>]*>(.*?)</a>', body, re.S):
            link = urllib.parse.urljoin(url, html.unescape(href).strip())
            p = urllib.parse.urlsplit(link)
            if p.hostname not in ("www.justice.gov", "justice.gov"):
                continue
            if re.search(r"[?&]page=", link):
                continue                                # excluded by robots.txt
            lpath = p.path
            if lpath.startswith(PM + "/") and not p.query:
                queue.append((BASE + lpath.rstrip("/"), clean(lab), url))
            elif part == "part-V" and (re.match(r"/(eoir/)?media/\d+/dl", lpath) or lpath.lower().endswith(".pdf")):
                docs.setdefault(BASE + lpath, (clean(lab), url))
    if "memos" not in todo:
        return
    print(f"  {len(docs)} memoranda linked", flush=True)
    for link, (label, parent) in docs.items():
        old = have.get(link)
        if old:
            rows[old["file"]] = old
            continue
        n, size = total()
        if n >= MAX_FILES or size >= MAX_BYTES:
            failed.append((label, "", link, "not downloaded: size/file cap reached"))
            continue
        data, ctype, disp, why = get(link)
        if data is None:
            print(f"  FAILED {link}: {why}", flush=True)
            failed.append((label, "", link, f"{why} (listed on {parent})"))
            continue
        if data[:5] != b"%PDF-":
            failed.append((label, "", link, f"not a PDF ({ctype}) (listed on {parent})"))
            continue
        m = re.search(r'filename="?([^";]+)', disp)
        name = m.group(1) if m else (Path(urllib.parse.urlsplit(link).path).name if link.lower().endswith(".pdf")
                                     else "media-" + re.search(r"/media/(\d+)", link).group(1) + ".pdf")
        date, basis = doc_date(label)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", urllib.parse.unquote(name)).strip("-")
        if not stem.lower().endswith(".pdf"):
            stem += ".pdf"
        mid = re.search(r"/media/(\d+)", link)
        rel = f"memoranda/{date + '_' if date else ''}{(mid.group(1) + '_') if mid else ''}{stem}"
        save(rel, data)
        rows[rel] = {"file": rel, "title": label, "date": date, "source_url": link, "kind": "guidance",
                     "title_en": "", "part": "part-V", "date_basis": basis, "listed_on": parent}
        have[link] = rows[rel]


def write_tsv(path, header, lines):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for line in lines:
            fh.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in line) + "\n")


def main():
    todo = sys.argv[1:] or ["manual", "memos"]
    for name in todo:
        if name not in ("manual", "memos"):
            sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    have = load_index()
    try:
        run(todo, have)
    except Blocked as e:
        print(f"BLOCKED, stopping: {e}")
        failed.append(("(run stopped)", "", BASE, f"host refused or kept failing: {e}"))
    for row in have.values():
        if row["file"] not in rows:
            rows[row["file"]] = row
    write_tsv(OUT / "index.tsv", HEADER, [[r.get(h, "") for h in HEADER] for _, r in sorted(rows.items())])
    got = {r["source_url"] for r in rows.values()}
    entries = {}
    no = OUT / "not-obtained.tsv"
    if no.exists():
        for line in no.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if len(f) == 4 and f[2] not in got:
                entries[f[2]] = f
    for t, d, u, why in failed:
        if u not in got:
            entries[u] = [t, d, u, why]
    write_tsv(no, ["title", "date", "url", "reason"], entries.values())
    n, size = total()
    print(f"{len(rows)} files indexed; folder holds {n} files, {size / 1e6:.1f} MB; {len(entries)} not obtained")


if __name__ == "__main__":
    main()

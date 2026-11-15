#!/usr/bin/env python3
"""Download the Immigration and Refugee Board of Canada's guidance for its members into ca/irb/.

    python3 download_ca_irb.py              everything
    python3 download_ca_irb.py guidelines   one or more sources: guidelines, jurisprudential-guides,
                                            instructions, policies, procedures, legal-resources

Source: https://www.irb-cisr.gc.ca/en/legal-policy/ (robots.txt is empty: nothing excluded).
The IRB publishes these instruments as web pages, so the pages are saved as .html exactly as
served; documents (PDF and the like) linked from them are saved next to them.

  guidelines              Chairperson's Guidelines (IRPA s. 159(1)(h))
  jurisprudential-guides  jurisprudential guides: policy notes, the designated decisions, revocations
  instructions            Chairperson's Instructions
  policies                IRB policies
  procedures              procedures and practice notices
  legal-resources         papers of IRB Legal Services used by members (refugee definition,
                          credibility, weighing evidence, removal order and sponsorship appeals,
                          Refugee Appeal Division handbook), every chapter

Sequential, 2 s between requests, files already present are skipped (delete a file to refresh
it). ca/irb/index.tsv and ca/irb/not-obtained.tsv are rewritten on every run. HTTP 403/429 or
three connection resets in a row end the run for the host; nothing is retried around a refusal.
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
OUT = ROOT / "ca" / "irb"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
BASE = "https://www.irb-cisr.gc.ca"
PAUSE = 2.0
MAX_FILES, MAX_BYTES = 1500, 500_000_000
HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "section", "first_issued", "linked_from"]

LP = "/en/legal-policy/"
SOURCES = {
    # name: (listing pages, path prefixes that may be followed, depth)
    "guidelines": ([LP + "policies/Pages/chairperson-guideline.aspx"], [LP + "policies/"], 2),
    "jurisprudential-guides": ([LP + "policies/Pages/jurisprudential-guides.aspx"],
                               [LP + "policies/", "/en/decisions/"], 1),
    "instructions": ([LP + "policies/Pages/chairperson-instructions.aspx"], [LP + "policies/"], 2),
    "policies": ([LP + "policies/Pages/policies.aspx"], [LP + "policies/"], 2),
    "procedures": ([LP + "procedures/Pages/index.aspx"],
                   [LP + "procedures/", "/en/members/Pages/MemComCode.aspx"], 2),
    "legal-resources": ([LP + "legal-concepts/Pages/index.aspx"],
                        [LP + "legal-concepts/", "/en/designated-representant/Pages/designated-representative-guide.aspx"], 4),
}
# Not guidance to decision-makers (complaints, public information, lists, forms): never followed.
SKIP = re.compile(r"(file_complaint|InterpretComPla|legal-aid-office|BondCaution|GloLex|/forms/|"
                  r"/act-rules-regulations/|spsdisco|/_layouts/|/_vti_bin/)", re.I)
# Listing/navigation pages: read for links, saved, but they are indexes not instruments.
DOC_EXT = (".pdf", ".doc", ".docx", ".rtf", ".xls", ".xlsx")

last_request = [0.0]
resets = [0]
rows = {}            # file -> row dict
failed = []          # (title, date, url, reason)


class Blocked(Exception):
    pass


def get(url):
    """One request. Returns bytes or None. Raises Blocked on a refusal or repeated resets."""
    wait = PAUSE - (time.time() - last_request[0])
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        resets[0] = 0
        return data, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} for {url}")
        resets[0] = 0
        return None, f"HTTP {e.code}"
    except Exception as e:                              # noqa: BLE001
        resets[0] += 1
        if resets[0] >= 3:
            raise Blocked(f"three connection failures in a row, last: {e!r} for {url}")
        return None, f"connection failed: {e!r}"
    finally:
        last_request[0] = time.time()


def norm(href, page_url):
    href = html.unescape(href).strip()
    if href.startswith(("mailto:", "javascript:", "tel:", "#")):
        return None
    url = urllib.parse.urljoin(page_url, href)
    parts = urllib.parse.urlsplit(url)
    if parts.hostname not in ("www.irb-cisr.gc.ca", "irb-cisr.gc.ca", "irb.gc.ca", "www.irb.gc.ca"):
        return None
    path = re.sub(r"/{2,}", "/", parts.path)
    return BASE + urllib.parse.quote(urllib.parse.unquote(path), safe="/()-_.~")


def key(url):
    return urllib.parse.unquote(urllib.parse.urlsplit(url).path).lower().rstrip("/")


def meta(text, name):
    m = re.search(r'<meta name="%s"[^>]*content="([^"]*)"' % re.escape(name), text)
    return html.unescape(html.unescape(m.group(1))).strip() if m else ""


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return " ".join(s.replace("​", "").split())


def main_part(text):
    m = re.search(r"<main.*?</main>", text, re.S)
    return m.group(0) if m else text


def is_page(data):
    return len(data) > 15000 and b"dcterms.title" in data and b"<main" in data


def is_doc(data, ext):
    if ext == ".pdf":
        return data[:5] == b"%PDF-"
    return b"<html" not in data[:1000].lower() and len(data) > 2000


def total():
    files = [p for p in OUT.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def load_index():
    """source_url key -> existing row, so that nothing is fetched twice."""
    have = {}
    idx = OUT / "index.tsv"
    if idx.exists():
        lines = idx.read_text(encoding="utf-8").splitlines()
        head = lines[0].split("\t")
        for line in lines[1:]:
            row = dict(zip(head, line.split("\t")))
            if (OUT / row["file"]).is_file():
                have[key(row["source_url"])] = row
    return have


def crawl(name, have):
    listings, prefixes, max_depth = SOURCES[name]
    print(f"== {name}")
    queue = [(BASE + p, 0, "", "") for p in listings]
    seen = set()
    while queue:
        url, depth, anchor, parent = queue.pop(0)
        k = key(url)
        if k in seen:
            continue
        seen.add(k)
        ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        old = have.get(k)
        if old and old.get("section") != name and depth > 0:
            continue                                    # already filed under another source
        if old:
            row = dict(old)
            data = (OUT / row["file"]).read_bytes()
        else:
            n, size = total()
            if n >= MAX_FILES or size >= MAX_BYTES:
                failed.append((anchor, "", url, "not downloaded: size/file cap reached"))
                continue
            data, why = get(url)
            if data is None:
                print(f"  FAILED {url}: {why}")
                failed.append((anchor, "", url, why))
                continue
            if ext in DOC_EXT:
                if not is_doc(data, ext):
                    failed.append((anchor, "", url, "server returned something that is not the document"))
                    continue
                stem = re.sub(r"[^A-Za-z0-9._-]+", "-", urllib.parse.unquote(Path(url).name))
                row = {"file": f"{name}/{stem}", "title": anchor or stem, "date": "", "first_issued": ""}
            else:
                if not is_page(data):
                    print(f"  UNEXPECTED CONTENT, not saved: {url}")
                    failed.append((anchor, "", url, "unexpected content (error page?)"))
                    continue
                text = data.decode("utf-8", "replace")
                date = meta(text, "dcterms.modified")
                stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(urllib.parse.unquote(url)).stem)
                sub = name
                m = re.search(r"/legal-concepts/([^/]+)/Pages/", url, re.I)
                if m:
                    sub = f"{name}/{m.group(1).lower()}"
                row = {"file": f"{sub}/{date + '_' if date else ''}{stem}.html",
                       "title": meta(text, "dcterms.title") or anchor,
                       "date": date, "first_issued": meta(text, "dcterms.issued")}
            row.update({"source_url": url, "kind": "guidance", "title_en": "", "section": name,
                        "linked_from": parent})
            dest = OUT / row["file"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            print(f"  saved {row['file']} ({len(data):,} bytes)")
        if depth == 0:
            row["title"] = row["title"] + " (listing page)" if "(listing page)" not in row["title"] else row["title"]
        rows[row["file"]] = row
        have[k] = row
        if ext in DOC_EXT or depth >= max_depth:
            continue
        body = main_part(data.decode("utf-8", "replace"))
        for href, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
            link = norm(href, url)
            if not link or SKIP.search(link):
                continue
            path = urllib.parse.urlsplit(link).path
            lext = Path(path).suffix.lower()
            follow = lext in DOC_EXT or (lext == ".aspx" and any(path.lower().startswith(p.lower()) for p in prefixes))
            if "/pages/index.aspx" in path.lower() and "/legal-concepts/" not in path.lower():
                follow = False                          # other sections' listings
            if follow and key(link) not in seen:
                queue.append((link, depth + 1, clean(label), url))


def write_tsv(path, header, lines):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for line in lines:
            fh.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in line) + "\n")


def main():
    todo = sys.argv[1:] or list(SOURCES)
    for name in todo:
        if name not in SOURCES:
            sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    have = load_index()
    try:
        for name in todo:
            crawl(name, have)
    except Blocked as e:
        print(f"BLOCKED, stopping: {e}")
        failed.append(("(run stopped)", "", BASE, f"host refused or kept resetting: {e}"))
    for row in have.values():                           # rows of sources not run this time
        if row["file"] not in rows and row.get("section") not in todo:
            rows[row["file"]] = row
    write_tsv(OUT / "index.tsv", HEADER,
              [[r.get(h, "") for h in HEADER] for _, r in sorted(rows.items())])
    # not-obtained.tsv: keep earlier entries that are still not on disk, add this run's failures
    got = {key(r["source_url"]) for r in rows.values()}
    entries = {}
    no = OUT / "not-obtained.tsv"
    if no.exists():
        for line in no.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if len(f) == 4 and key(f[2]) not in got:
                entries[f[2]] = f
    for t, d, u, why in failed:
        if key(u) not in got:
            entries[u] = [t, d, u, why]
    write_tsv(no, ["title", "date", "url", "reason"], entries.values())
    n, size = total()
    print(f"{len(rows)} files indexed; folder holds {n} files, {size / 1e6:.1f} MB; "
          f"{len(entries)} not obtained")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download the guidance of Australia's Administrative Review Tribunal (ART; until 14 October 2024 the
Administrative Appeals Tribunal, AAT, whose Migration and Refugee Division replaced the MRT-RRT in
2015) for its members into au/tribunal/.

    python3 download_au_tribunal.py

Wanted: the Guide to Refugee Law in Australia (contents, introduction, chapters 1-12), the
President's practice directions (Common Procedures Practice Direction; Migration and Refugee
Division / Migration and Refugee jurisdictional area practice direction), and member guidelines
(credibility, vulnerable persons, gender, decision-making).

How it works: robots.txt of www.art.gov.au is read first (Disallow rules for * are obeyed), then
the sitemap it names; pages whose address mentions practice directions, guidelines, the Guide to
Refugee Law or the President's directions are read, and every PDF/Word document under
/sites/default/files/ they link is saved unmodified.

In November 2026 www.art.gov.au, art.gov.au and www.aat.gov.au did not answer this machine at all
(read time-outs, even for robots.txt), so this script has not yet saved anything; when the host
does not answer, it writes au/tribunal/not-obtained.tsv with the known documents and stops.
Its page-selection logic has therefore not been tried against the live site: check the result.

Sequential, 3 s between requests, files already present are skipped, index.tsv and
not-obtained.tsv are rewritten on every run. HTTP 403/429 or three connection failures in a row
end the run; a refusal is never retried.
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
OUT = ROOT / "au" / "tribunal"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
BASE = "https://www.art.gov.au"
PAUSE = 3.0
MAX_FILES, MAX_BYTES = 1500, 500_000_000
HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "listed_on"]
PAGE_RE = re.compile(r"practice-direction|guideline|guide-to-refugee-law|refugee-law|presidential-direction|"
                     r"president-s-direction|member-guid|jurisdictional-area|migration-and-refugee", re.I)
DOC_RE = re.compile(r"practice[- _%20]*direction|guideline|guide|chapter|contents|introduction|direction", re.I)
DOC_EXT = (".pdf", ".doc", ".docx", ".rtf")
AAT_GUIDE = "https://www.aat.gov.au/AAT/media/AAT/Files/MRD%20documents/Guide%20to%20Refugee%20Law/"
KNOWN = [  # (title, date, url a person can open) - from the AAT's "Guide to Refugee Law in Australia" page
    ("Guide to Refugee Law in Australia: Contents", "", AAT_GUIDE + "Contents.pdf"),
    ("Guide to Refugee Law in Australia: Introduction", "", AAT_GUIDE + "Introduction.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 1 Protection visas", "", AAT_GUIDE + "Chapter1_ProtectionVisas.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 2 Country of reference", "", AAT_GUIDE + "Chapter2_CountryofReference.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 3 Well-founded fear", "", AAT_GUIDE + "Chapter3_WFF.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 4 Persecution", "", AAT_GUIDE + "Chapter4_Persecution.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 5 Refugee grounds and nexus", "", AAT_GUIDE + "Chapter5_GroundsNexus.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 6 Relocation", "", AAT_GUIDE + "Chapter6_Relocation.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 7 Exclusion and cessation", "", AAT_GUIDE + "Chapter7_Exclusion.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 8 State protection", "", AAT_GUIDE + "Chapter8_StateProtection.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 9 Third country protection", "", AAT_GUIDE + "Chapter9_ThirdCountry.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 10 Complementary protection", "", AAT_GUIDE + "Chapter10_ComplementaryProtection.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 11 Application of Refugees Convention in particular situations", "", AAT_GUIDE + "Chapter11_ParticularSituations.pdf"),
    ("Guide to Refugee Law in Australia: Chapter 12 Merits review of protection related decisions", "", AAT_GUIDE + "Chapter12_MeritsReview.pdf"),
    ("ART practice directions (Common Procedures Practice Direction 2024 and the Migration and Refugee practice direction) and President's directions", "2024-10", BASE + "/"),
    ("ART / former AAT Migration and Refugee Division member guidelines (e.g. Guidelines on Gender, on Vulnerable Persons, on the Assessment of Credibility)", "", BASE + "/"),
]
KNOWN_REASON = ("not fetched: www.art.gov.au, art.gov.au and www.aat.gov.au gave read time-outs to every "
                "request from this machine (even robots.txt); web.archive.org could not be used (three "
                "connection refusals in a row), webarchive.nla.gov.au answers with an Anubis bot check, "
                "api.prod.legislation.gov.au refused robots.txt (HTTP 403)")

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
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        fails[0] = 0
        return data, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} for {url}")
        fails[0] = 0
        return None, f"HTTP {e.code}"
    except Exception as e:                              # noqa: BLE001
        fails[0] += 1
        if fails[0] >= 3:
            raise Blocked(f"three connection failures in a row, last {e!r} for {url}")
        return None, f"connection failed: {e!r}"
    finally:
        last_request[0] = time.time()


def clean(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())


def disallowed(robots):
    rules, applies = [], False
    for line in robots.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        if k.lower() == "user-agent":
            applies = v == "*" or re.search(r"claude|anthropic|gpt|ai", v, re.I) is not None
        elif k.lower() == "disallow" and applies and v:
            rules.append(re.compile(re.escape(v).replace(r"\*", ".*").replace(r"\$", "$")))
    return rules


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


def crawl(have):
    robots, why = get(BASE + "/robots.txt")
    if robots is None:
        raise Blocked(f"robots.txt not available ({why}); nothing else requested")
    robots = robots.decode("utf-8", "replace")
    rules = disallowed(robots)
    ok = lambda u: not any(r.match(urllib.parse.urlsplit(u).path) for r in rules)   # noqa: E731
    sitemaps = re.findall(r"(?im)^sitemap:\s*(\S+)", robots) or [BASE + "/sitemap.xml"]
    pages, queue = [], list(sitemaps)
    while queue:
        sm = queue.pop(0)
        data, why = get(sm)
        if data is None:
            failed.append(("sitemap", "", sm, why))
            continue
        for loc in re.findall(r"<loc>([^<]+)</loc>", data.decode("utf-8", "replace")):
            loc = html.unescape(loc).strip()
            if loc.endswith(".xml") or "sitemap" in loc.rsplit("/", 1)[-1]:
                queue.append(loc)
            elif PAGE_RE.search(loc) and ok(loc):
                pages.append(loc)
    print(f"{len(pages)} pages to read", flush=True)
    for page in pages:
        data, why = get(page)
        if data is None:
            failed.append(("page", "", page, why))
            continue
        text = data.decode("utf-8", "replace")
        m = re.search(r"<main.*?</main>", text, re.S)
        body = m.group(0) if m else text
        for href, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
            link = urllib.parse.urljoin(page, html.unescape(href).strip())
            p = urllib.parse.urlsplit(link)
            ext = Path(p.path).suffix.lower()
            if p.hostname not in ("www.art.gov.au", "art.gov.au") or ext not in DOC_EXT or not ok(link):
                continue
            label = clean(label)
            if not (DOC_RE.search(label) or DOC_RE.search(p.path)):
                continue
            if link in have:
                rows[have[link]["file"]] = have[link]
                continue
            n, size = total()
            if n >= MAX_FILES or size >= MAX_BYTES:
                failed.append((label, "", link, "not downloaded: size/file cap reached"))
                continue
            doc, why = get(link)
            if doc is None:
                failed.append((label, "", link, why))
                continue
            if ext == ".pdf" and doc[:5] != b"%PDF-" or b"<html" in doc[:1000].lower():
                failed.append((label, "", link, "server returned something that is not the document"))
                continue
            m = re.search(r"/files/((?:19|20)\d\d)-(\d\d)/", p.path)
            date = f"{m.group(1)}-{m.group(2)}" if m else ""
            stem = re.sub(r"[^A-Za-z0-9._-]+", "-", urllib.parse.unquote(Path(p.path).name)).strip("-")
            rel = f"{date + '_' if date else ''}{stem}"
            (OUT / rel).write_bytes(doc)
            print(f"  saved {rel} ({len(doc):,} bytes)", flush=True)
            rows[rel] = {"file": rel, "title": label, "date": date, "source_url": link, "kind": "guidance",
                         "title_en": "", "listed_on": page}
            have[link] = rows[rel]


def write_tsv(path, header, lines):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for line in lines:
            fh.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in line) + "\n")


def main():
    if sys.argv[1:]:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    have = load_index()
    reached = True
    try:
        crawl(have)
    except Blocked as e:
        print(f"STOPPED: {e}")
        reached = bool(rows)
        failed.append(("(run stopped)", "", BASE, f"host refused or did not answer: {e}"))
    for row in have.values():
        rows.setdefault(row["file"], row)
    write_tsv(OUT / "index.tsv", HEADER, [[r.get(h, "") for h in HEADER] for _, r in sorted(rows.items())])
    got = {r["source_url"] for r in rows.values()}
    entries = {}
    if not reached or not rows:
        for t, d, u in KNOWN:
            entries[(t, u)] = [t, d, u, KNOWN_REASON]
    for t, d, u, why in failed:
        if u not in got:
            entries[(t, u)] = [t, d, u, why]
    write_tsv(OUT / "not-obtained.tsv", ["title", "date", "url", "reason"], entries.values())
    n, size = total()
    print(f"{len(rows)} files indexed; folder holds {n} files, {size / 1e6:.1f} MB; {len(entries)} not obtained")


if __name__ == "__main__":
    main()

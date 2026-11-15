#!/usr/bin/env python3
"""Download UNHCR's guidance to refugee-status decision-makers into unhcr/.

    python3 download_unhcr.py            everything
    python3 download_unhcr.py country    one or more sources (only "country" fetches anything; see below)

What UNHCR publishes for decision-makers falls in two groups:

  country   Country-specific guidance: Eligibility Guidelines, International Protection
            Considerations, Guidance Notes on international protection needs, Positions on Returns
            and return advisories, related cessation / internal-flight notes. English only.
            Source: ecoi.net (Austrian Red Cross / ACCORD), which keeps unmodified copies of the PDFs
            UNHCR published, at /en/file/local/<ecoi-id>/<file name>. ecoi.net's robots.txt allows
            everything. Listing: ecoi.net search, source 11525 (UNHCR), document type 11597
            ("Expert Opinion or Position"), language English, plus title searches for the same
            document families in other document types. Titles are then filtered by THE_RE / NOT_RE.

  thematic  The Handbook on Procedures and Criteria (all reissues), Guidelines on International
            Protection Nos 1-13, Procedural Standards for RSD under UNHCR's mandate (2003, 2020),
            the Resettlement Handbook, the Handbook on Protection of Stateless Persons and the
            Guidelines on Statelessness, the Detention Guidelines (1999, 2012). Not fetched: every
            host that carries them refused this machine in November 2026 (www.unhcr.org: HTTP 429;
            www.refworld.org: Cloudflare JavaScript challenge, even for robots.txt; web.archive.org:
            three connection refusals in a row; data.unhcr.org: "Search is temporarily unavailable
            to automated clients"). They are listed in unhcr/not-obtained.tsv with the address a
            person can open in a browser; THEMATIC below holds that list.

Sequential, 2 s between requests, files already present are skipped. unhcr/index.tsv and
unhcr/not-obtained.tsv are rewritten on every run. HTTP 403/429 or three connection failures in a
row end the run; a refusal is never retried. Cap: 1 GB, 1500 files.
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
OUT = ROOT / "unhcr"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
ECOI = "https://www.ecoi.net"
PAUSE = 2.0
MAX_FILES, MAX_BYTES = 1500, 1_000_000_000
HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "category", "country", "ecoi_id", "ecoi_page"]
SEARCH = ECOI + "/en/document-search/search-v2?"
UNHCR_SRC = "11525"
POSITION_TYPE = "11597"
TITLE_SEARCHES = ['origTitle:"Eligibility Guidelines"', 'origTitle:"International Protection Considerations"',
                  'origTitle:"International Protection Needs"', 'origTitle:"Position on Returns"',
                  'origTitle:"Position on Return"', 'origTitle:"Guidance Note"', 'origTitle:"Return Advisory"',
                  'origTitle:"Protection Considerations"', 'origTitle:"Advisory on the Return"']
# Country guidance families (title must match THE_RE and not NOT_RE)
THE_RE = re.compile(r"eligibility guidelines|protectio\w* considerations|international protection response|"
                    r"position paper on protection and return|considerations relating to the return|conditions for return|"
                    r"international protection needs|protection needs of|position on (the )?(voluntary )?returns?\b|"
                    r"position on deportations|return advisory|advisory (on|regarding) the return|"
                    r"guidance note on (the )?(international protection|outflow|eritrea|afghanistan|guinea)|"
                    r"guidelines relating to the eligibility|security update relating to complementary|"
                    r"ceased circumstances|cessation clauses|internal flight|relocation alternative|"
                    r"clarification on the assessment of applications|basic considerations regarding returns|"
                    r"position on (the )?(continued )?(international )?protection needs|"
                    r"position on categories of persons|position regarding asylum-seekers and refugees from|"
                    r"position on return of rejected|position on the return of the rejected|"
                    r"position on international protection needs|position on sudanese asylum-seekers|"
                    r"voluntary return to ukraine of refugee children|position on the international protection",
                    re.I)
NOT_RE = re.compile(r"recommendations? (to|on|by)\b|^unhcr recommendations|comments? on|observations|stellungnahme|analyse|analysis of|evaluation|"
                    r"fact finding|draft law|law no\.|council regulation|greece|malta|safe third country|"
                    r"designation of bosnia|infiltrators|kenyan government|dublin|news|appeal or news", re.I)

THEMATIC = [
    # (title, date, url a person can open)
    ("Handbook on Procedures and Criteria for Determining Refugee Status under the 1951 Convention and the 1967 Protocol (original edition)", "1979-09", "https://www.refworld.org/docid/3ae6b3314.html"),
    ("Handbook on Procedures and Criteria for Determining Refugee Status (re-edited)", "1992-01", "https://www.refworld.org/docid/3ae6b3314.html"),
    ("Handbook on Procedures and Criteria for Determining Refugee Status and Guidelines on International Protection (reissued)", "2011-12", "https://www.refworld.org/docid/4f33c8d92.html"),
    ("Handbook on Procedures and Criteria for Determining Refugee Status and Guidelines on International Protection (reissued), HCR/1P/4/ENG/REV. 4", "2019-02", "https://www.unhcr.org/media/handbook-procedures-and-criteria-determining-refugee-status-under-1951-convention-and-1967"),
    ("Guidelines on International Protection No. 1: Gender-Related Persecution", "2002-05-07", "https://www.unhcr.org/media/guidelines-international-protection-no-1-gender-related-persecution-within-context-article-1a"),
    ("Guidelines on International Protection No. 2: Membership of a Particular Social Group", "2002-05-07", "https://www.unhcr.org/media/guidelines-international-protection-no-2-membership-particular-social-group-within-context"),
    ("Guidelines on International Protection No. 3: Cessation of Refugee Status under Article 1C(5) and (6)", "2003-02-10", "https://www.unhcr.org/media/guidelines-international-protection-no-3-cessation-refugee-status-under-article-1c5-and-6"),
    ("Guidelines on International Protection No. 4: Internal Flight or Relocation Alternative", "2003-07-23", "https://www.unhcr.org/media/guidelines-international-protection-no-4-internal-flight-or-relocation-alternative-within"),
    ("Guidelines on International Protection No. 5: Application of the Exclusion Clauses: Article 1F", "2003-09-04", "https://www.unhcr.org/media/guidelines-international-protection-no-5-application-exclusion-clauses-article-1f-1951"),
    ("Guidelines on International Protection No. 6: Religion-Based Refugee Claims", "2004-04-28", "https://www.unhcr.org/media/guidelines-international-protection-no-6-religion-based-refugee-claims-under-article-1a-2"),
    ("Guidelines on International Protection No. 7: Victims of Trafficking and Persons at Risk of Being Trafficked", "2006-04-07", "https://www.unhcr.org/media/guidelines-international-protection-no-7-application-article-1a2-1951-convention-and/or-1967"),
    ("Guidelines on International Protection No. 8: Child Asylum Claims", "2009-12-22", "https://www.unhcr.org/media/guidelines-international-protection-no-8-child-asylum-claims-under-articles-1a2-and-1f-1951"),
    ("Guidelines on International Protection No. 9: Claims to Refugee Status based on Sexual Orientation and/or Gender Identity", "2012-10-23", "https://www.unhcr.org/media/guidelines-international-protection-no-9-hcr-gip-06-07-23-october-2012"),
    ("Guidelines on International Protection No. 10: Claims to Refugee Status related to Military Service", "2013-11-12", "https://www.unhcr.org/media/guidelines-international-protection-no-10-claims-refugee-status-related-military-service"),
    ("Guidelines on International Protection No. 11: Prima Facie Recognition of Refugee Status", "2015-06-24", "https://www.unhcr.org/media/guidelines-international-protection-no-11-prima-facie-recognition-refugee-status-5-june-2015"),
    ("Guidelines on International Protection No. 12: Claims for refugee status related to situations of armed conflict and violence", "2016-12-02", "https://www.unhcr.org/media/unhcr-guidelines-international-protection-no-12-hcr-gip-16-12-02-december-2016"),
    ("Guidelines on International Protection No. 13: Applicability of Article 1D to Palestinian Refugees", "2017-12", "https://www.unhcr.org/media/guidelines-international-protection-no-13-applicability-article-1d-1951-convention-relating"),
    ("Procedural Standards for Refugee Status Determination under UNHCR's Mandate", "2003-09-01", "https://www.refworld.org/docid/42d66dd84.html"),
    ("Procedural Standards for Refugee Status Determination under UNHCR's Mandate (revised, all units)", "2020-08-26", "https://www.unhcr.org/media/procedural-standards-refugee-status-determination-under-unhcrs-mandate"),
    ("UNHCR Resettlement Handbook (complete publication, and country chapters)", "2011", "https://www.unhcr.org/media/unhcr-resettlement-handbook-complete-publication"),
    ("UNHCR Resettlement Handbook (earlier editions 1997, 2004)", "2004-11", "https://www.refworld.org/docid/3d464e842.html"),
    ("Handbook on Protection of Stateless Persons under the 1954 Convention", "2014-06-30", "https://www.unhcr.org/media/handbook-protection-stateless-persons"),
    ("Guidelines on Statelessness No. 1: The definition of 'Stateless Person' in Article 1(1) of the 1954 Convention (superseded by the 2014 Handbook)", "2012-02-20", "https://www.refworld.org/docid/4f4371b82.html"),
    ("Guidelines on Statelessness No. 2: Procedures for Determining whether an Individual is a Stateless Person (superseded by the 2014 Handbook)", "2012-04-05", "https://www.refworld.org/docid/4f7dafb52.html"),
    ("Guidelines on Statelessness No. 3: The Status of Stateless Persons at the National Level (superseded by the 2014 Handbook)", "2012-07-17", "https://www.refworld.org/docid/5005520f2.html"),
    ("Guidelines on Statelessness No. 4: Ensuring Every Child's Right to Acquire a Nationality through Articles 1-4 of the 1961 Convention", "2012-12-21", "https://www.unhcr.org/media/guidelines-statelessness-nr-4-ensuring-every-childs-right-acquire-nationality-through"),
    ("Guidelines on Statelessness No. 5: Loss and Deprivation of Nationality under Articles 5-9 of the 1961 Convention", "2020-05", "https://www.refworld.org/docid/5ec5640c4.html"),
    ("UNHCR's Revised Guidelines on Applicable Criteria and Standards relating to the Detention of Asylum-Seekers", "1999-02-26", "https://www.unhcr.org/media/unhcr-revised-guidelines-applicable-criteria-and-standards-relating-detention-asylum-seekers"),
    ("Detention Guidelines: Guidelines on the Applicable Criteria and Standards relating to the Detention of Asylum-Seekers and Alternatives to Detention", "2012", "https://www.unhcr.org/media/unhcr-detention-guidelines"),
]
THEMATIC_REASON = ("not fetched: www.unhcr.org answered HTTP 429 and www.refworld.org a Cloudflare JavaScript "
                   "challenge (even for robots.txt); the web.archive.org copy could not be used (three "
                   "connection refusals in a row); no other UNHCR host offers it to scripts")
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


def iso(d):
    d = d.strip()
    m = re.match(r"(\d{1,2}) (\w+) (\d{4})$", d)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.match(r"(\w+) (\d{4})$", d)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    m = re.match(r"(\d{4})$", d)
    return m.group(1) if m else ""


def search(params):
    """All result pages of one ecoi.net search; yields parsed list items."""
    page, pages = 1, 1
    while page <= pages:
        q = params + ([("page", str(page))] if page > 1 else [])
        data, why = get(SEARCH + urllib.parse.urlencode(q))
        if data is None:
            failed.append(("ecoi.net search", "", SEARCH + urllib.parse.urlencode(q), why))
            return
        d = json.loads(data)
        pages = d.get("pages", 0)
        for li in d["content"].split('<li class="doc-listelement"')[1:]:
            o = re.search(r'doc-origtitle"><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*(?:<small>\((.*?)\)</small>)?', li, re.S)
            did = re.search(r'data-ecoi-id="(\d+)"', li)
            meta = re.findall(r'<p class="doc-metadata">(.*?)</p>', li, re.S)
            if not (o and did and meta):
                continue
            first = clean(meta[0])
            yield {"id": did.group(1), "href": urllib.parse.urljoin(ECOI, html.unescape(o.group(1))),
                   "title": clean(o.group(2)), "type": clean(o.group(3) or ""),
                   "date": iso(first.split("|")[0]), "author": first.split("|", 1)[-1].strip(),
                   "country": clean(meta[1]) if len(meta) > 1 else ""}
        page += 1


def total():
    files = [p for p in OUT.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def load_index():
    have = {}
    idx = OUT / "index.tsv"
    if idx.exists():
        lines = idx.read_text(encoding="utf-8").splitlines()
        head = lines[0].split("\t")
        for line in lines[1:]:
            row = dict(zip(head, line.split("\t")))
            if (OUT / row["file"]).is_file():
                have[row["ecoi_id"]] = row
    return have


def slug(s, n=90):
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:n].strip("-")


def country_source(have):
    print("== country (ecoi.net)")
    base = [("srcId[]", UNHCR_SRC), ("srcIdOperator", "should"), ("lang[]", "en"), ("langOperator", "should"),
            ("sort_by", "origPublicationDate"), ("sort_order", "desc")]
    found = {}
    for it in search(base + [("documentTypeId[]", POSITION_TYPE), ("documentTypeIdOperator", "should")]):
        found.setdefault(it["id"], it)
    for q in TITLE_SEARCHES:
        for it in search([("content", q)] + base):
            found.setdefault(it["id"], it)
    print(f"  {len(found)} UNHCR items listed")
    seen_titles = {}
    for it in sorted(found.values(), key=lambda x: x["date"], reverse=True):
        t = it["title"]
        if not THE_RE.search(t) or NOT_RE.search(t) or "English" not in it["type"] or "UNHCR" not in it["author"] \
                or "News" in it["type"]:
            continue
        if "/file/local/" not in it["href"]:
            failed.append((t, it["date"], it["href"], f"ecoi.net only links to another site (ecoi.net document "
                           f"{ECOI}/en/document/{it['id']}.html); that site was not used"))
            continue
        k = (t.lower(), it["date"])
        if k in seen_titles:                    # ecoi.net sometimes holds the same document twice
            continue
        seen_titles[k] = it["id"]
        old = have.get(it["id"])
        if old:
            rows[old["file"]] = old
            continue
        n, size = total()
        if n >= MAX_FILES or size >= MAX_BYTES:
            failed.append((t, it["date"], it["href"], "not downloaded: size/file cap reached"))
            continue
        data, why = get(it["href"])
        if data is None:
            print(f"  FAILED {it['href']}: {why}")
            failed.append((t, it["date"], it["href"], why))
            continue
        name = urllib.parse.unquote(it["href"].rsplit("/", 1)[-1])
        ext = Path(name).suffix.lower() or ".pdf"
        if ext == ".pdf" and data[:5] != b"%PDF-" or ext != ".pdf" and b"<html" in data[:1000].lower():
            failed.append((t, it["date"], it["href"], "server returned something that is not the document"))
            continue
        rel = f"country/{it['date'] + '_' if it['date'] else ''}{slug(t)}_{it['id']}{ext}"
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  saved {rel} ({len(data):,} bytes)")
        rows[rel] = {"file": rel, "title": t, "date": it["date"], "source_url": it["href"], "kind": "guidance",
                     "title_en": "", "category": "country guidance", "country": it["country"],
                     "ecoi_id": it["id"], "ecoi_page": f"{ECOI}/en/document/{it['id']}.html"}


def write_tsv(path, header, lines):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for line in lines:
            fh.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in line) + "\n")


def main():
    todo = sys.argv[1:] or ["country", "thematic"]
    for name in todo:
        if name not in ("country", "thematic"):
            sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    have = load_index()
    try:
        if "country" in todo:
            country_source(have)
    except Blocked as e:
        print(f"BLOCKED, stopping: {e}")
        failed.append(("(run stopped)", "", ECOI, f"host refused or kept failing: {e}"))
    for row in have.values():
        if row["file"] not in rows and ("country" not in todo or failed):
            rows[row["file"]] = row
    write_tsv(OUT / "index.tsv", HEADER, [[r.get(h, "") for h in HEADER] for _, r in sorted(rows.items())])
    got = {r["source_url"] for r in rows.values()}
    entries = {}
    no = OUT / "not-obtained.tsv"
    broken = any(f[0] in ("ecoi.net search", "(run stopped)") for f in failed)
    if no.exists() and ("country" not in todo or broken):    # a complete listing replaces old entries
        for line in no.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if len(f) == 4 and f[2] not in got and f[3] != THEMATIC_REASON:
                entries[(f[0], f[2])] = f
    for t, d, u in THEMATIC:
        entries[(t, u)] = [t, d, u, THEMATIC_REASON]
    for t, d, u, why in failed:
        if u not in got:
            entries[(t, u)] = [t, d, u, why]
    write_tsv(no, ["title", "date", "url", "reason"], entries.values())
    n, size = total()
    print(f"{len(rows)} files indexed; folder holds {n} files, {size / 1e6:.1f} MB; {len(entries)} not obtained")


if __name__ == "__main__":
    main()

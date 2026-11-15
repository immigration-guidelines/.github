#!/usr/bin/env python3
"""Download the guidance and practice directions of the United Kingdom's immigration tribunals
into uk/tribunal/.

    python3 download_uk_tribunal.py            everything
    python3 download_uk_tribunal.py utiac      one or more of: utiac, fttiac, joint

Bodies: Upper Tribunal (Immigration and Asylum Chamber) and First-tier Tribunal (Immigration and
Asylum Chamber): presidential guidance notes, practice directions and practice statements of the
Senior President of Tribunals and the chamber presidents, protocols, and the guidance notes of the
former Asylum and Immigration Tribunal that are still applied.

Source: www.judiciary.uk (robots.txt allows everything). The site's two "guidance" sitemaps are
read, the pages about the two chambers are picked by their address, and every document
(PDF, Word) those pages offer is saved unmodified. A page that carries its text itself and offers
no document is saved as .html. Pages that are user guides, news, reports or consultations are
left out (see SKIP).

  utiac/    documents found only on Upper Tribunal pages
  fttiac/   documents found only on First-tier Tribunal pages
  joint/    documents on pages of both chambers, joint guidance, Senior President's directions
            that apply to both

Sequential, 2 s between requests, existing files are skipped. uk/tribunal/index.tsv and
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
OUT = ROOT / "uk" / "tribunal"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
BASE = "https://www.judiciary.uk"
PAUSE = 2.0
MAX_FILES, MAX_BYTES = 1500, 500_000_000
HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "chamber", "date_basis", "listed_on", "page_title"]
SITEMAPS = [BASE + "/guidance-sitemap.xml", BASE + "/guidance-sitemap2.xml"]
SUBJECTS = {"utiac": BASE + "/subjects/immigration-and-asylum-chamber-upper/",
            "fttiac": BASE + "/subjects/immigration-and-asylum-chamber-first-tier/"}
WANT = re.compile(r"immigration|asylum|utiac|fttiac|-iac(-|/|$)|former-ait")
# General directions of the Senior President of Tribunals that bind both chambers but do not name
# them in the page address.
EXTRA = [
    BASE + "/guidance-and-resources/practice-direction-from-the-senior-president-of-tribunals-reasons-for-decisions/",
    BASE + "/guidance-and-resources/practice-direction-from-the-senior-president-of-tribunals-panel-composition/",
    BASE + "/guidance-and-resources/pilot-practice-direction-contingency-arrangements-in-the-first-tier-tribunal-and-the-upper-tribunal/",
    BASE + "/guidance-and-resources/amended-practice-statement-issued-by-senior-president-of-tribunals/",
    BASE + "/guidance-and-resources/two-practice-statements-issued-by-the-senior-president-of-tribunals-sir-ernest-ryder/",
    BASE + "/guidance-and-resources/joint-lord-lady-chief-justice-and-senior-president-of-tribunals-guidance/",
]
# Not guidance for or binding on the tribunal's judges: other bodies, public user guides, news.
SKIP = re.compile(r"special-immigration-appeals|siac|court-of-appeal|family-proceedings|social-entitlement|"
                  r"interview|in-conversation|why-i-became|whos-who|annual-report|consultation|responses-|"
                  r"correspondence-between|help-for-users|user-guide|users-group|tribunals-journal|"
                  r"understanding-the-impact|message-from")
# Documents offered on IAC pages that are not IAC guidance: other jurisdictions' versions of the
# cross-jurisdictional remote-participation guidance, Family Division and criminal-court guidance,
# public user guides, a career article; and second uploads of files already saved from another
# address (identical bytes).
DROP_DOC = re.compile(r"Live-Links-in-Criminal|Employment-Tribunals-Scotland|Civil-Remote-Guidance|"
                      r"General-Regulatory-Chamber|PG-mode-and-listing|Property-Remote|Family-Jurisdiction|"
                      r"Remote-Participation-EAT|Guidance-SEC-|Tax-Chamber-|WPAFCC|UT-Lands|UTAAC-Remote|"
                      r"UTTCC-Remote|Presidents-Practice-Guidance-on-Case-Management|IAC-User-Guide|"
                      r"knowles-lane|PD-Panel-Composition-FtT-SEC|Guide\+for\+Unrep|Guide-for-Unrep|"
                      r"/uploads/2022/08/(AITGuidanceNoteChecklist|GuidanceNote1|GuideNoteNo\d)\.pdf$|"
                      r"/uploads/2022/07/practice-directions-iac-dated-18-dec-2018\.pdf$", re.I)
DOC_EXT = (".pdf", ".doc", ".docx", ".rtf", ".odt")
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


def quote(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(urllib.parse.unquote(p.path), safe="/+()-_.~,"), p.query, ""))


def find_date(*texts):
    """A date stated in the title or file name: full date, else a year."""
    for t in texts:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s-]+(%s)[\s-]+((?:19|20)\d\d)\b" % "|".join(MONTHS), t, re.I)
        if m:
            return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}", "stated in title"
    for t in texts:
        m = re.search(r"\b(%s)[\s-]+((?:19|20)\d\d)\b" % "|".join(MONTHS), t, re.I)
        if m:
            return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}", "stated in title"
    for t in texts:
        m = re.search(r"(?<!\d)((?:19|20)\d\d)(?!\d)", t)
        if m:
            return m.group(1), "year in title"
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


def chamber_of(url, text):
    s = (url + " " + text).lower()
    up = bool(re.search(r"utiac|upper[- ]tribunal|chamber-upper", s))
    ft = bool(re.search(r"fttiac|first[- ]tier|chamber-first-tier|former-ait", s))
    if "joint" in url or (up and ft):
        return "joint"
    return "utiac" if up else "fttiac" if ft else "joint"


def pages_to_visit():
    """Guidance pages about the two chambers: from the sitemaps, the subject listings and EXTRA."""
    found = {}
    for sm in SITEMAPS:
        data, why = get(sm)
        if data is None:
            failed.append(("guidance sitemap", "", sm, why))
            continue
        for loc in re.findall(r"<loc>([^<]+)</loc>", data.decode("utf-8", "replace")):
            slug = loc.rstrip("/").rsplit("/", 1)[-1]
            if "/guidance-and-resources/" in loc and WANT.search(slug) and not SKIP.search(slug):
                found[loc] = ""
    for name, start in SUBJECTS.items():
        url, n = start, 0
        while url and n < 15:
            n += 1
            data, why = get(url)
            if data is None:
                failed.append((f"subject listing {name}", "", url, why))
                break
            text = data.decode("utf-8", "replace")
            for loc in re.findall(r'href="(https://www\.judiciary\.uk/guidance-and-resources/[^"#?]+)"', text):
                slug = loc.rstrip("/").rsplit("/", 1)[-1]
                if not SKIP.search(slug):
                    found.setdefault(loc if loc.endswith("/") else loc + "/", name)
            m = re.search(r'<a[^>]+class="[^"]*next[^"]*"[^>]+href="([^"]+)"', text) or \
                re.search(r'<a[^>]+href="([^"]+)"[^>]+class="[^"]*next[^"]*"', text) or \
                re.search(r'<link rel="next" href="([^"]+)"', text)
            url = html.unescape(m.group(1)) if m else None
    for loc in EXTRA:
        found.setdefault(loc, "joint")
    return found


def main():
    todo = sys.argv[1:] or ["utiac", "fttiac", "joint"]
    for name in todo:
        if name not in ("utiac", "fttiac", "joint"):
            sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    have = load_index()
    docs = {}       # document url -> info ; a document offered on several pages is saved once
    try:
        pages = pages_to_visit()
        print(f"{len(pages)} guidance pages to read")
        queue, seen = list(pages), set()
        while queue:
            page = queue.pop(0)
            if page in seen:
                continue
            seen.add(page)
            data, why = get(page)
            if data is None:
                print(f"  FAILED {page}: {why}")
                failed.append(("guidance page", "", page, why))
                continue
            text = data.decode("utf-8", "replace")
            m = re.search(r"<title>(.*?)</title>", text, re.S)
            ptitle = clean(m.group(1)).replace(" - Courts and Tribunals Judiciary", "") if m else ""
            m = re.search(r"<main.*?</main>", text, re.S)
            body = m.group(0) if m else text
            chamber = chamber_of(page, " ".join(re.findall(r'href="https://www\.judiciary\.uk/subjects/([^"]+)"', body)))
            n_docs = 0
            for href, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
                link = urllib.parse.urljoin(page, html.unescape(href).strip())
                p = urllib.parse.urlsplit(link)
                if p.hostname != "www.judiciary.uk":
                    continue
                ext = Path(p.path).suffix.lower()
                if "/wp-content/uploads/" in p.path and ext in DOC_EXT:
                    n_docs += 1
                    if DROP_DOC.search(link):
                        continue
                    link = quote(link)
                    label = clean(label)
                    name = urllib.parse.unquote_plus(Path(p.path).name)
                    if re.match(r"Download .* file$", label) or not label:
                        label = ptitle + " - " + name if n_docs > 1 or True else ptitle
                    label = re.sub(r"\s*\((PDF|Word)[^)]*\)\s*$", "", label)
                    d = docs.setdefault(link, {"title": label, "pages": [], "chambers": set(), "ptitle": ptitle, "name": name})
                    d["pages"].append(page)
                    d["chambers"].add(chamber)
                elif "/guidance-and-resources/" in p.path:
                    slug = p.path.rstrip("/").rsplit("/", 1)[-1]
                    loc = BASE + p.path.rstrip("/") + "/"
                    if loc not in seen and not SKIP.search(slug) and (WANT.search(slug) or page in pages):
                        if loc not in pages:
                            pages[loc] = "linked"
                        queue.append(loc)
            if n_docs == 0 and len(clean(body)) > 3000 and not re.search(r"/subjects/|sitemap", page):
                # the page is the document
                slug = page.rstrip("/").rsplit("/", 1)[-1]
                m = re.search(r'article:published_time" content="(\d{4}-\d\d-\d\d)', text) or \
                    re.search(r'article:modified_time" content="(\d{4}-\d\d-\d\d)', text)
                date = m.group(1) if m else ""
                if chamber in todo:
                    rel = f"{chamber}/{date + '_' if date else ''}{slug[:120]}.html"
                    old = have.get(page)
                    if old:
                        rel = old["file"]
                    else:
                        (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
                        (OUT / rel).write_bytes(data)
                        print(f"  saved {rel}")
                    rows[rel] = {"file": rel, "title": ptitle, "date": date, "source_url": page, "kind": "guidance",
                                 "title_en": "", "chamber": chamber, "date_basis": "page date", "listed_on": page,
                                 "page_title": ptitle}

        print(f"{len(docs)} documents offered")
        for link, d in docs.items():
            chamber = "joint" if len(d["chambers"]) > 1 else next(iter(d["chambers"]))
            if chamber not in todo:
                continue
            date, basis = find_date(d["title"], d["name"].replace("_", " ").replace("-", " "), d["ptitle"])
            if not date:
                m = re.search(r"/uploads/((?:19|20)\d\d)/(\d\d)/", link)
                if m:
                    date, basis = f"{m.group(1)}-{m.group(2)}", "upload folder (not the document's date)"
            old = have.get(link)
            if old:
                rel = old["file"]
            else:
                n, size = total()
                if n >= MAX_FILES or size >= MAX_BYTES:
                    failed.append((d["title"], date, link, "not downloaded: size/file cap reached"))
                    continue
                data, why = get(link)
                if data is None:
                    print(f"  FAILED {link}: {why}")
                    failed.append((d["title"], date, link, f"{why} (listed on {d['pages'][0]})"))
                    continue
                ext = Path(d["name"]).suffix.lower()
                ok = data[:5] == b"%PDF-" if ext == ".pdf" else b"<html" not in data[:1000].lower()
                if not ok:
                    failed.append((d["title"], date, link, "server returned something that is not the document"))
                    continue
                stem = re.sub(r"[^A-Za-z0-9._-]+", "-", d["name"]).strip("-")
                rel = f"{chamber}/{date + '_' if date else ''}{stem}"
                if (OUT / rel).exists() and rel in rows:
                    rel = f"{chamber}/{date + '_' if date else ''}{len(rows)}-{stem}"
                (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
                (OUT / rel).write_bytes(data)
                print(f"  saved {rel} ({len(data):,} bytes)")
            rows[rel] = {"file": rel, "title": d["title"], "date": date, "source_url": link, "kind": "guidance",
                         "title_en": "", "chamber": chamber, "date_basis": basis,
                         "listed_on": " ".join(dict.fromkeys(d["pages"])), "page_title": d["ptitle"]}
    except Blocked as e:
        print(f"BLOCKED, stopping: {e}")
        failed.append(("(run stopped)", "", BASE, f"host refused or kept failing: {e}"))

    for row in have.values():
        if row["file"] not in rows and (row.get("chamber") not in todo or failed):
            rows[row["file"]] = row
    with (OUT / "index.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join(HEADER) + "\n")
        for _, r in sorted(rows.items()):
            fh.write("\t".join(str(r.get(h, "")).replace("\t", " ") for h in HEADER) + "\n")
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
    with no.open("w", encoding="utf-8") as fh:
        fh.write("title\tdate\turl\treason\n")
        for f in entries.values():
            fh.write("\t".join(str(c).replace("\t", " ") for c in f) + "\n")
    n, size = total()
    print(f"{len(rows)} files indexed; folder holds {n} files, {size / 1e6:.1f} MB; {len(entries)} not obtained")


if __name__ == "__main__":
    main()

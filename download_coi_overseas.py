#!/usr/bin/env python3
"""Download official country-of-origin information (COI) from Canada, the US and Australia.

    ./download_coi_overseas.py ca   Canada: Immigration and Refugee Board, Research Directorate.
                                    ca/coi/rir/  Responses to Information Requests (English; the
                                                 IRB keeps a seven-year archive online)
                                    ca/coi/ndp/  latest National Documentation Package list per
                                                 country (the list only, not the documents in it)
    ./download_coi_overseas.py us   United States: State Department.
                                    us/coi/hrp-YYYY/  Country Reports on Human Rights Practices
                                    us/coi/irf-YYYY/  Report on International Religious Freedom
    ./download_coi_overseas.py au   Australia: DFAT Country Information Reports (PDF).
                                    NOTE: on 2026-11-14 dfat.gov.au refused scripted requests
                                    (connection reset), so this part is untested and saved nothing.
    ./download_coi_overseas.py      all three

Files already present are skipped, so the script can be re-run. Each source folder gets an
index.tsv (file, country, title, date, source URL), newest first. Each source stops at
CAP_BYTES or CAP_FILES, whichever comes first. Requests are sequential and spaced out
(state.gov's robots.txt asks for a 5 s crawl delay). A 403/429 answer stops that source:
the script does not retry or try to get around a block.
"""
import html
import http.cookiejar
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # reports go to <country>/coi/
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
CAP_BYTES = 500 * 1024 * 1024
CAP_FILES = 1500
DELAY = {"www.state.gov": 5.0}          # seconds between requests; default below
DEFAULT_DELAY = 1.0

# US editions, in download priority order: (folder, report slug on state.gov, title, year)
US_EDITIONS = [
    ("hrp-2024", "2024-country-reports-on-human-rights-practices",
     "2024 Country Reports on Human Rights Practices", "2024"),
    ("irf-2023", "2023-report-on-international-religious-freedom",
     "2023 Report on International Religious Freedom", "2023"),
    ("hrp-2023", "2023-country-reports-on-human-rights-practices",
     "2023 Country Reports on Human Rights Practices", "2023"),
    ("hrp-2022", "2022-country-reports-on-human-rights-practices",
     "2022 Country Reports on Human Rights Practices", "2022"),
]


class Blocked(Exception):
    pass


_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
_last = {}


def get(url, data=None, tries=2, timeout=120):
    """Fetch url politely. Raises Blocked on 403/429; returns None on other failures."""
    host = urllib.parse.urlsplit(url).netloc
    err = None
    for attempt in range(tries):
        wait = DELAY.get(host, DEFAULT_DELAY) - (time.time() - _last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
            with _opener.open(req, timeout=timeout) as r:
                body = r.read()
            _last[host] = time.time()
            return body
        except urllib.error.HTTPError as e:
            _last[host] = time.time()
            if e.code in (403, 429):
                raise Blocked(f"{host} answered HTTP {e.code} for {url}")
            err = e
            if e.code == 404:
                break
        except Exception as e:                      # noqa: BLE001 - report and retry once
            _last[host] = time.time()
            err = e
        time.sleep(5 * (attempt + 1))
    print(f"  FAILED {url}: {err}", flush=True)
    return None


def slug(s, n=90):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:n] or "x"


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def iso(d):
    """'7 October 2026' -> '2026-10-07' (unchanged if it does not parse)."""
    try:
        return datetime.strptime(d.strip(), "%d %B %Y").strftime("%Y-%m-%d")
    except ValueError:
        return d.strip()


class Budget:
    """Tracks the per-source cap, counting files already on disk."""

    def __init__(self):
        self.files = 0
        self.bytes = 0
        self.skipped = 0

    def fetch(self, url, dest, check):
        """Make sure dest exists (download if needed and the cap allows). True if it exists."""
        if dest.exists() and dest.stat().st_size > 0:
            self.files += 1
            self.bytes += dest.stat().st_size
            return True
        if self.files >= CAP_FILES or self.bytes >= CAP_BYTES:
            self.skipped += 1
            return False
        body = get(url)
        if body is None:
            return False
        if not check(body):
            print(f"  NOT SAVED (does not look like the expected document): {url}", flush=True)
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(body)
        tmp.rename(dest)
        self.files += 1
        self.bytes += len(body)
        if self.files % 25 == 0:
            print(f"  {self.files} files, {self.bytes / 1e6:.0f} MB", flush=True)
        return True


def write_index(out, rows):
    with open(out / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\tcountry\ttitle\tdate\tsource_url\n")
        for row in rows:
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in row) + "\n")


def summary(name, out, rows, budget, total):
    print(f"{name}: {len(rows)} of {total} listed documents on disk, "
          f"{budget.bytes / 1e6:.0f} MB, index at {out / 'index.tsv'}"
          + (f"; {budget.skipped} left out by the cap" if budget.skipped else ""), flush=True)


# --- Canada: Immigration and Refugee Board ------------------------------------------------

CA_RIR = "https://www.irb-cisr.gc.ca/en/country-information/rir/Pages/index.aspx"
CA_NDP = "https://www.irb-cisr.gc.ca/en/country-information/ndp/Pages/index.aspx"


def hidden_fields(page):
    """All hidden inputs of an ASP.NET form (view state etc.), needed to submit it."""
    f = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', page):
        n = re.search(r'name="([^"]*)"', m.group(0))
        v = re.search(r'value="([^"]*)"', m.group(0))
        if n:
            f[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return f


def ca_rir_listing():
    """Search the RIR database (English, all years offered) and page through the results."""
    page = get(CA_RIR)
    if page is None:
        return []
    page = page.decode("utf-8", "replace")
    prefix = re.search(r'name="([^"]*)\$txtFulltext"', page).group(1)
    years = [int(y) for y in re.findall(
        r'<option[^>]*value="(\d{4})"', re.search(r'\$ddlFrom".*?</select>', page, re.S).group(0))]
    search = {prefix + "$txtFulltext": "", prefix + "$ddlFulltext": "0",
              prefix + "$txtTitle": "", prefix + "$ddlTitle": "0",
              prefix + "$ddlLanguage": "1",                      # English
              prefix + "$ddlFrom": str(min(years)), prefix + "$ddlTo": str(max(years)),
              prefix + "$ddlResultsperpage": "100"}
    form = hidden_fields(page)
    form.update(search)
    form[prefix + "$btnSubmit"] = "Submit"
    found, seen_pages = {}, 0
    while True:
        res = get(CA_RIR, urllib.parse.urlencode(form).encode())
        if res is None:
            break
        res = res.decode("utf-8", "replace")
        seen_pages += 1
        hits = re.findall(
            r"<a href='index\.aspx\?doc=(\d+)&(?:amp;)?pls=1'[^>]*>\s*([^<]+?)\s*</a>\s*-\s*([^<]+?)"
            r"<br\s*/>\s*<span[^>]*>(.*?)</span>", res, re.S)
        for doc, code, date, title in hits:
            found[doc] = (doc, code.strip(), iso(date), clean(title))
        m = re.search(r"Displaying <strong>\s*\d+ - (\d+)</strong> of (\d+)", res)
        if m:
            print(f"  RIR listing: {m.group(1)} of {m.group(2)}", flush=True)
        if not hits or not m or int(m.group(1)) >= int(m.group(2)) or seen_pages > 60:
            break
        form = hidden_fields(res)
        form.update(search)
        form["__EVENTTARGET"] = prefix + "$LinkButton3"          # the "Next>" link
    return sorted(found.values(), key=lambda r: (r[2], r[1]), reverse=True)


def ca_ndp_listing():
    """Latest National Documentation Package of every country (form option 'All Countries')."""
    page = get(CA_NDP)
    if page is None:
        return []
    page = page.decode("utf-8", "replace")
    prefix = re.search(r'name="([^"]*)\$ddlCountry"', page).group(1)
    form = hidden_fields(page)
    form.update({prefix + "$ddlCountry": "0", prefix + "$btnGo": "Go"})
    res = get(CA_NDP, urllib.parse.urlencode(form).encode())
    if res is None:
        return []
    res = res.decode("utf-8", "replace")
    hits = re.findall(r"Latest National Documentation Package:</strong>\s*<a href='\?pid=(\d+)' "
                      r"title='National Documentation Package, (.*?), from ([^']*)'", res)
    archived = len(set(re.findall(r"\?pid=(\d+)", res))) - len(hits)
    print(f"  NDP listing: {len(hits)} countries (plus {archived} archived older packages, "
          "not downloaded)", flush=True)
    return sorted(((pid, html.unescape(c), iso(d)) for pid, c, d in hits),
                  key=lambda r: r[2], reverse=True)


def ca():
    out = ROOT / "ca" / "coi"
    out.mkdir(parents=True, exist_ok=True)
    budget, rows = Budget(), []
    rirs = ca_rir_listing()
    ndps = ca_ndp_listing()
    for doc, code, date, title in rirs:                           # newest first
        rel = f"rir/{date}_{slug(code)}.html"
        url = f"{CA_RIR}?doc={doc}&pls=1"
        country = title.split(":")[0].strip() if ":" in title else ""
        if budget.fetch(url, out / rel, lambda b, c=code: c.encode() in b):
            rows.append((rel, country, f"{code} - {title}", date, url))
    for pid, country, date in ndps:
        rel = f"ndp/{slug(country)}_{date}.html"
        url = f"{CA_NDP}?pid={pid}"
        if budget.fetch(url, out / rel, lambda b: b"National Documentation Package" in b
                        and b.count(b"<a ") > 80):
            rows.append((rel, country, f"National Documentation Package (list of documents), "
                         f"{country}", date, url))
    write_index(out, rows)
    summary("Canada", out, rows, budget, len(rirs) + len(ndps))


# --- United States: State Department ------------------------------------------------------

def us():
    out = ROOT / "us" / "coi"
    out.mkdir(parents=True, exist_ok=True)
    budget, rows, total = Budget(), [], 0
    for folder, rslug, rtitle, year in US_EDITIONS:               # newest / most wanted first
        base = f"https://www.state.gov/reports/{rslug}/"
        toc = get(base)
        if toc is None:
            continue
        toc = toc.decode("utf-8", "replace")
        if "Page not found" in toc[:5000]:
            print(f"  {rtitle}: not published at {base}", flush=True)
            continue
        names = {}
        for path, text in re.findall(                 # the site's own links vary: http/https,
                r'<a[^>]*href="https?://www\.state\.gov/reports/' + re.escape(rslug)
                + r'/([^"#?]+)/?\??"[^>]*>(.*?)</a>', toc, re.S):   # with or without final slash
            path = path.strip("/") + "/"
            if clean(text) or path not in names:
                names.setdefault(path, clean(text))
                names[path] = names[path] or clean(text)
        print(f"  {rtitle}: {len(names)} country pages", flush=True)
        total += len(names)
        for path in sorted(names):
            country = names[path] or path.strip("/").replace("-", " ").title()
            rel = f"{folder}/{slug(path.strip('/').replace('/', '_'))}.html"
            url = base + path
            ok = budget.fetch(url, out / rel, lambda b: b"type-state_report" in b
                              and b"Page not found" not in b[:5000])
            if ok:
                rows.append((rel, country, f"{rtitle}: {country}", year, url))
    write_index(out, rows)
    summary("United States", out, rows, budget, total)


# --- Australia: DFAT ----------------------------------------------------------------------

AU_LIST = "https://www.dfat.gov.au/about-us/publications/country-information-reports"


def au():
    """Untested: dfat.gov.au reset every scripted connection when this was written."""
    out = ROOT / "au" / "coi"
    out.mkdir(parents=True, exist_ok=True)
    page = get(AU_LIST, tries=1, timeout=45)
    if page is None:
        print("Australia: dfat.gov.au did not answer (the site appears to refuse scripts). "
              "Nothing downloaded.", flush=True)
        return
    page = page.decode("utf-8", "replace")
    budget, rows, seen = Budget(), [], set()
    links = re.findall(r'<a[^>]*href="([^"]*country-information-report[^"]*\.pdf)"[^>]*>(.*?)</a>',
                       page, re.S | re.I)
    for href, text in links:
        url = urllib.parse.urljoin(AU_LIST, html.unescape(href))
        if url in seen:
            continue
        seen.add(url)
        name = slug(urllib.parse.unquote(url.rsplit("/", 1)[1]))
        title = clean(text)
        country = re.sub(r"(?i)dfat|country information report|\[.*?\]|\(.*?\)|-|\d{1,2} \w+ \d{4}",
                         " ", title).strip()
        date = re.search(r"\d{1,2} \w+ \d{4}", title)
        if budget.fetch(url, out / name, lambda b: b.startswith(b"%PDF")):
            rows.append((name, re.sub(r"\s+", " ", country), title,
                         iso(date.group(0)) if date else "", url))
    rows.sort(key=lambda r: r[3], reverse=True)
    write_index(out, rows)
    summary("Australia", out, rows, budget, len(seen))


SOURCES = {"ca": ca, "us": us, "au": au}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SOURCES)
    for w in wanted:
        if w not in SOURCES:
            sys.exit(__doc__)
    for w in wanted:
        print(f"== {w} ==", flush=True)
        try:
            SOURCES[w]()
        except Blocked as e:
            print(f"BLOCKED, stopping this source: {e}", flush=True)

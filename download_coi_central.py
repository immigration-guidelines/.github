#!/usr/bin/env python3
"""Download official country-of-origin information (COI) reports published by
the asylum authorities of Germany, the Netherlands, Belgium, Austria and Switzerland.

    ./download_coi_central.py de   Germany: BAMF Länderreporte, Länderkurzinformationen, Briefing Notes (bamf.de)
    ./download_coi_central.py nl   Netherlands: Foreign Ministry ambtsberichten (rijksoverheid.nl)
    ./download_coi_central.py be   Belgium: CGVS/CGRS Cedoca "COI Focus" reports + country policy notes (cgvs.be)
    ./download_coi_central.py at   Austria: BFA Staatendokumentation, as published on ecoi.net (source 10998 only)
    ./download_coi_central.py ch   Switzerland: SEM Länderanalyse Focus reports / notes (sem.admin.ch)
    ./download_coi_central.py      all of them, one after the other

Files go to <source>/coi/ (the EU asylum agency: eu/coi/), newest first, until a source reaches MAX_BYTES or
MAX_FILES. Files already present are skipped, so the script can be re-run.
Each folder gets index.tsv (file, country, title, date, source URL) and a
state.json remembering what was looked up, so re-runs make few requests.
Add --list to only show what would be fetched.

A 403 or 429 answer stops that source at once; nothing is retried around it.
Five failed downloads in a row also stop a source (re-run later to continue).
"""
import hashlib
import html
import http.client
import json
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # reports go to <source>/coi/
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 0.6                      # seconds between requests
MAX_BYTES = 3000 * 1024 * 1024   # per source (raised from 500 MB on 14 Nov 2026)
MAX_FILES = 6000                 # per source (raised from 1500)
LIST_ONLY = "--list" in sys.argv

_last = [0.0]


class Blocked(Exception):
    pass


def get(url, data=None, headers=None, tries=3):
    """Fetch url politely. Returns bytes, or None on failure. Raises Blocked on 403/429."""
    err = None
    for attempt in range(tries):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            h = {"User-Agent": UA}
            h.update(headers or {})
            # A slow link can get cut off mid-file; carry on from where it stopped (plain HTTP resume).
            buf, cuts = b"", 0
            while True:
                if buf:
                    h["Range"] = f"bytes={len(buf)}-"
                req = urllib.request.Request(url, data=data, headers=h)
                try:
                    with urllib.request.urlopen(req, timeout=180) as r:
                        if buf and r.status != 206:      # server ignores Range and starts over
                            buf, cuts = b"", 99          # so allow just this one more go
                        buf += r.read()
                    break
                except http.client.IncompleteRead as e:
                    cuts += 1
                    if cuts > 15 or not e.partial:
                        raise
                    buf += e.partial
                    time.sleep(DELAY)
            _last[0] = time.time()
            return buf
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} for {url}")
            err = e
            if e.code in (404, 410):
                break
        except Exception as e:                      # noqa: BLE001 - report and retry
            _last[0] = time.time()
            err = e
        time.sleep(4 * (attempt + 1))
    print(f"  FAILED {url}: {err}", flush=True)
    return None


def page(url, **kw):
    b = get(url, **kw)
    return None if b is None else b.decode("utf-8", "replace")


def slug(s, n=110):
    s = urllib.parse.unquote(s)
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue")):
        s = s.replace(a, b)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n] or "x"


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


MONTHS = {}
for i, names in enumerate([
        "januar january januari jan", "februar february februari feb", "märz maerz march maart mrt mar",
        "april apr", "mai may mei", "juni june jun", "juli july jul", "august augustus aug",
        "september sept sep", "oktober october okt oct", "november nov", "dezember december dec dez"], 1):
    for n in names.split():
        MONTHS[n] = i


def parse_date(s):
    """'10.11.2026', '11. November 2026', 'Mai 2008', '2008', ISO -> 'YYYY-MM-DD' (missing parts = 01)."""
    s = (s or "").strip()
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", s)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(?:(\d{1,2})\.?\s+)?([A-Za-zäÄ]+)\.?\s+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1) or 1):02d}"
    m = re.search(r"(19|20)\d\d", s)
    return f"{m.group(0)}-01-01" if m else "0000-00-00"


CURRENT = []

MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".odt": b"PK", ".doc": b"\xd0\xcf\x11\xe0", ".zip": b"PK"}


class Source:
    """One output folder: applies the caps, skips existing files, writes index.tsv."""

    def __init__(self, name):
        self.name = name
        self.dir = ROOT / name / "coi"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / "state.json"
        self.state = {"files": {}, "resolved": {}}
        if self.state_file.exists():
            self.state.update(json.loads(self.state_file.read_text(encoding="utf-8")))
        self.rows = []
        self.bytes = 0
        self.new = 0
        self.failed = 0
        self.streak = 0
        self.skipped_cap = []        # dates of items left out because of the cap
        CURRENT[:] = [self]

    def save_state(self):
        self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=0), encoding="utf-8")

    def full(self):
        return self.bytes >= MAX_BYTES or len(self.rows) >= MAX_FILES

    def fetch(self, url, date, country, title, name_hint=None, ext=None, index_url=None):
        """Download one file (unless present). Returns True if it is on disk afterwards."""
        if LIST_ONLY:
            print(f"  {date}\t{country}\t{title[:90]}\t{url}")
            self.rows.append(("", country, title, date, index_url or url))
            return True
        fname = self.state["files"].get(url)
        if not fname:
            base = name_hint or urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
            stem, dot, e = base.rpartition(".")
            if not dot or len(e) > 5:
                stem, e = base, ""
            e = (ext or ("." + e.lower() if e else ".pdf"))
            stem = slug(stem)
            if not stem.startswith(date[:4]):
                stem = f"{date}_{stem}"
            fname = stem + e
            taken = set(self.state["files"].values())
            k = 2
            while fname in taken:
                fname = f"{stem}_{k}{e}"
                k += 1
        dest = self.dir / fname
        if not (dest.exists() and dest.stat().st_size > 0):
            data = get(url, tries=2)
            if data is None:
                self.failed += 1
                self.streak += 1
                if self.streak >= 5:        # the site or the link is not cooperating: stop, do not hammer
                    raise Blocked("5 downloads in a row failed; re-run later to continue")
                return False
            self.streak = 0
            magic = MAGIC.get(dest.suffix.lower())
            if magic and magic not in data[:1024]:
                print(f"  NOT A {dest.suffix} FILE, skipped: {url}", flush=True)
                self.failed += 1
                return False
            dest.write_bytes(data)
            self.new += 1
            print(f"  [{self.name}] {date} {fname} ({len(data) // 1024} kB)", flush=True)
        self.state["files"][url] = fname
        self.bytes += dest.stat().st_size
        self.rows.append((fname, country, title, date, index_url or url))
        if self.new % 10 == 0:
            self.save_state()
            self.write_index()
        return True

    def write_index(self):
        if LIST_ONLY:
            return
        with open(self.dir / "index.tsv", "w", encoding="utf-8") as f:
            f.write("file\tcountry\ttitle\tdate\tsource_url\n")
            for r in self.rows:
                f.write("\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r) + "\n")

    def finish(self, note=""):
        self.save_state()
        self.write_index()
        dates = sorted(r[3] for r in self.rows if r[3] > "0001")
        span = f"{dates[0]} .. {dates[-1]}" if dates else "-"
        left = ""
        if self.skipped_cap:
            s = sorted(self.skipped_cap)
            left = f"; cap reached, {len(s)} older items not fetched ({s[0]} .. {s[-1]})"
        print(f"== {self.name}: {len(self.rows)} files, {self.bytes / 1e6:.0f} MB, {self.new} new, "
              f"{self.failed} failed, dates {span}{left}. {note}", flush=True)


# --- Germany: BAMF ------------------------------------------------------------

BAMF_SEARCH = ("https://www.bamf.de/SiteGlobals/Forms/Suche/Expertensuche_Formular.html"
               "?cl2Categories_Bereich=behoerde&cl2Categories_Typ={typ}&sortOrder=dateOfIssue_dt+desc&pageLocale=de")
BAMF_TYPES = {"laenderreport": "Länderreport", "laenderkurzinformation": "Länderkurzinformation",
              "briefingnotes": "Briefing Notes"}


def bamf_country(typ, title):
    if typ == "briefingnotes":
        m = re.search(r"Zusammenfassung\s*[-–]\s*(.+?)\s+(?:I{1,2}|[12]\.?\s*Halbjahr|Januar|Juli)\b", title)
        return m.group(1) if m else "(various)"
    t = re.sub(r"^Länder(report|kurzinformation)\s*", "", title)
    t = re.sub(r"^\d+\s*[-–:]?\s*", "", t)
    t = re.split(r"\s+\d{1,2}/\d{2,4}|\s*[:(–]|\s+-\s+", t)[0]
    return t.strip() or "(various)"


def de():
    src = Source("de")
    items = []
    for typ in BAMF_TYPES:
        n = 1
        while True:
            url = BAMF_SEARCH.format(typ=typ) + (f"&gtp=296874_list%253D{n}" if n > 1 else "")
            t = page(url)
            if t is None:
                break
            blocks = t.split('class="l-results__result')[1:]
            for b in blocks:
                a = re.search(r'<a href="([^"]+)"\s+class="c-teaser__link[^>]*>(.*?)</a>', b, flags=re.S)
                d = re.search(r'Datum:&#32;</span><span class="c-meta__item">([\d.]+)', b)
                pdfs = re.findall(r'href="([^"]+\.pdf[^"]*)"', b)
                if not (a and pdfs):
                    continue
                title = clean(a.group(2))
                items.append((parse_date(d.group(1) if d else ""), bamf_country(typ, title), title,
                              html.unescape(pdfs[0]).replace("www.BAMF.de", "www.bamf.de"),
                              html.unescape(a.group(1)).replace("www.BAMF.de", "www.bamf.de")))
            m = re.search(r"von (\d+) Ergebnissen", t)
            total = int(m.group(1)) if m else 0
            print(f"  bamf {typ} page {n}: {len(blocks)} results of {total}", flush=True)
            if not blocks or n * 50 >= total:
                break
            n += 1
    items.sort(key=lambda x: x[0], reverse=True)
    seen = set()
    for date, country, title, pdf, pg in items:
        if pdf in seen:
            continue
        seen.add(pdf)
        if src.full():
            src.skipped_cap.append(date)
            continue
        src.fetch(pdf, date, country, title, index_url=pdf)
    src.finish()


# --- Netherlands: ambtsberichten on rijksoverheid.nl --------------------------

NL_BASE = "https://www.rijksoverheid.nl"


def nl_search(pageno, size=100):
    """The site's own search endpoint (what the /documenten page calls), filtered to type Ambtsbericht."""
    body = json.dumps({
        "requestState": {"current": pageno, "resultsPerPage": size, "searchTerm": "", "sortDirection": "",
                         "sortField": "", "sortList": [],
                         "filters": [{"field": "information_type", "values": ["Ambtsbericht"], "type": "any"}]},
        "queryConfig": {
            "filters": [{"field": "content_type", "values": ["pro:downloadDocument"], "type": "any"}],
            "result_fields": {"url": {"raw": {}}, "page_title": {"raw": {}}, "sort_date": {"raw": {}},
                              "information_type": {"raw": {}}},
            "disjunctiveFacets": ["information_type"],
            "facets": {"information_type": {"type": "value", "size": 100}},
            "sortList": [{"field": "sort_date", "direction": "desc"}]}}, separators=(",", ":")).encode()
    h = hashlib.sha256(body).hexdigest()
    b = get(f"{NL_BASE}/api/search?hash={h}", data=body, headers={"Content-Type": "application/json"})
    return None if b is None else json.loads(b)


NL_COUNTRIES = [c.split("|") for c in (
    "Afghanistan,Albanië,Algerije,Angola,Armenië,Azerbeidzjan,Bangladesh,Belarus|Wit-Rusland,Burundi,China|Oeigoeren|Tibet,"
    "Colombia,Democratische Republiek Congo|Congo|DRC,Egypte,Eritrea,Ethiopië|Ogaden,Georgië,Griekenland,Guinee,India,"
    "Irak,Iran,Ivoorkust,Jemen,Jordanië,Kazachstan,Kirgizië,Koeweit,Libanon,Libië,Mali,Marokko,Mauritanië,Moldavië,"
    "Mongolië,Myanmar,Nepal,Nigeria,Oeganda,Oekraïne,Oezbekistan,Pakistan,Palestijnse gebieden|Palestijnen|Palestijnse,"
    "Russische Federatie|Rusland,Rwanda,Senegal,Sierra Leone,Somalië,Sri Lanka,Zuid-Sudan|Zuid-Soedan,Sudan|Soedan,"
    "Suriname,Syrië|Syrische|Syriërs,Tadzjikistan,Tunesië,Turkije,Turkmenistan,Venezuela,Vietnam,"
    "Verenigde Arabische Emiraten|VAE").split(",")]
_FOLD = str.maketrans("ëïéèöü", "eieeou")


def nl_country(title, url=""):
    hay = (title + " " + url.rsplit("/", 1)[-1].replace("-", " ")).lower().translate(_FOLD)
    found = []
    for variants in NL_COUNTRIES:
        for v in variants:
            m = re.search(r"(?<![a-z])" + re.escape(v.lower().translate(_FOLD)) + r"(?![a-z])", hay)
            if m:
                hay = hay[:m.start()] + " " * (m.end() - m.start()) + hay[m.end():]   # "zuid-sudan" is not also "sudan"
                found.append(variants[0])
                break
    return " / ".join(found) or "(see title)"


NL_SKIP = re.compile(r"(?i)terms? of reference|paragon|fichebundel|ambtseed|\bRRF\b|digital currency|openbaar te maken|"
                     r"persbericht|\bUHT\b|wet transparantie|rappel|strafbeschikking|kamerbrief|raad justitie|hoge raad")


def nl():
    src = Source("nl")
    items, n, pages = [], 1, 1
    while n <= pages:
        d = nl_search(n)
        if d is None:
            break
        pages = d["rawResponse"]["rawInfo"]["meta"]["page"]["total_pages"]
        for r in d["rawResponse"]["rawResults"]:
            title, url = r["page_title"]["raw"], r["url"]["raw"]
            m = re.search(r"/(\d{4})/(\d\d)/(\d\d)/", url)
            date = "-".join(m.groups()) if m else r["sort_date"]["raw"][:10]
            items.append((date, title, urllib.parse.urljoin(NL_BASE, url)))
        n += 1
    items.sort(reverse=True)
    # open.overheid.nl's robots.txt is "User-agent: * / Disallow: /", so its files are not fetched by this
    # script: starting the counter at 3 makes every such file be listed as skipped (see MISSING.md).
    oo_down, oo_skipped = 3, 0
    for date, title, url in items:
        # only the Foreign Ministry's country reports; the type also holds a few unrelated papers
        if NL_SKIP.search(title) or re.match(r"(ek|tk|bijlage)-", url.rsplit("/", 1)[-1]) \
                or re.search(r"terms?-of-reference|/tor-", url):
            print(f"  nl: skipped (not a country report): {date} {title}", flush=True)
            continue
        if src.full():
            src.skipped_cap.append(date)
            continue
        links = src.state.setdefault("pages", {}).get(url)
        if links is None:
            t = page(url)
            if t is None:
                src.failed += 1
                continue
            # Attachments sit either on rijksoverheid.nl itself or (most of them) on open.overheid.nl
            links = []
            for m in re.finditer(r'<a[^>]*href="(https://(?:open\.overheid\.nl/(?:documenten|repository)|'
                                 r'www\.rijksoverheid\.nl/site/binaries)/[^"]+)"[^>]*>(.*?)</a>', t, flags=re.S):
                u, label = html.unescape(m.group(1)), clean(m.group(2))
                label = re.sub(r"^Download:\s*|\s*Ambtsbericht \d\d-\d\d-\d{4}.*$", "", label)
                if u not in [x[0] for x in links]:
                    links.append([u, label])
            src.state["pages"][url] = links
        cand = []
        for u, label in links:
            base = urllib.parse.unquote_plus(u.rsplit("/", 1)[-1])
            what = label + " " + (base if "/documenten/" not in u else "")
            if re.search(r"(?i)terms?\W*(of\W*)?reference|(^|[\W_])tor([\W_]|$)", what):
                continue                              # not the terms of reference
            english = bool(re.search(r"(?i)country[\W_]*of[\W_]*origin|\breport\b|[\W_](en|eng|english)[\W_]", what))
            m = re.match(r"https://open\.overheid\.nl/(?:documenten|repository)/([^/]+)", u)
            if m:                                     # both forms end up at /documenten/<id>/pdf
                cand.append((english, f"https://open.overheid.nl/documenten/{m.group(1)}/pdf",
                             slug(label or base, 90) + ".pdf", label))
            else:
                cand.append((english, u, None, label))
        dutch = [c for c in cand if not c[0]]         # Dutch original, not the English translation
        for _, u, hint, label in dutch or cand:
            t2 = title if not label or label.lower() in title.lower() else f"{title} - {label}"
            oo = u.startswith("https://open.overheid.nl/")
            if oo and oo_down >= 3 and u not in src.state["files"]:
                oo_skipped += 1                       # open.overheid.nl is not answering: leave it for a re-run
                continue
            ok = src.fetch(u, date, nl_country(title, url), t2, name_hint=hint)
            if oo:
                oo_down = 0 if ok else oo_down + 1
                src.streak = 0
    if oo_skipped:
        print(f"  nl: {oo_skipped} files on open.overheid.nl were not fetched (robots.txt disallows scripts); use a browser.",
              flush=True)
    src.finish()


# --- Belgium: CGVS / Cedoca COI Focus ------------------------------------------

BE_BASE = "https://www.cgvs.be"
BE_THIRD = re.compile(r"(?i)^(euaa|easo|sem\b|landinfo|ofpra|unhcr|udi|dis\b|migrationsverket|lifos|bamf|"
                      r"home office|ukho|irb|ind\b|bfa|accord|dfat|drc|danish|norwegian|swedish|finnish)")


def be():
    src = Source("be")
    items, country, n, last = [], "", 0, 0
    while n <= last:
        t = page(f"{BE_BASE}/nl/landeninfo?page={n}")
        if t is None:
            break
        nums = [int(x) for x in re.findall(r'href="/nl/landeninfo\?page=(\d+)"', t)]
        last = max(nums + [last])
        i = t.find("Alle rapporten")
        body = t[i:]
        for m in re.finditer(r"<h3>\s*([^<]+?)\s*</h3>|views-alle-rapporten-grouped.*?<a href=\"([^\"]+)\">(.*?)</a>"
                             r".*?content=\"(\d{4}-\d\d-\d\d)", body, flags=re.S):
            if m.group(1):
                country = clean(m.group(1))
            else:
                items.append((m.group(4), country, clean(m.group(3)), urllib.parse.urljoin(BE_BASE, m.group(2))))
        if n % 10 == 0:
            print(f"  cgvs listing page {n}/{last}: {len(items)} reports so far", flush=True)
        n += 1
    items = sorted(set(items), reverse=True)
    notes_done, third = set(), 0
    for date, country, title, url in items:
        if BE_THIRD.search(title):
            third += 1
            continue
        if src.full():
            src.skipped_cap.append(date)
            continue
        res = src.state["resolved"].get(url)
        if res is None:
            t = page(url)
            if t is None:
                src.failed += 1
                continue
            rep = re.search(r"href='([^']+/files/rapporten/[^']+)'", t)
            note = re.search(r"href='([^']+/files/beleidsnotas/[^']+)'", t)
            c = re.search(r'field-name-field-rapport-country">.*?</div>\s*([^<]+)<', t, flags=re.S)
            res = {"report": rep and html.unescape(rep.group(1)), "note": note and html.unescape(note.group(1)),
                   "country": clean(c.group(1)) if c else country}
            src.state["resolved"][url] = res
            if len(src.state["resolved"]) % 25 == 0:
                src.save_state()
        country = res.get("country") or country
        rep = res.get("report")
        if not rep:
            continue
        base = rep.rsplit("/", 1)[-1].lower()
        if not base.startswith(("coi_focus", "coif", "coi-focus")):
            # a report of another body (EUAA, SEM, ...) that CGVS merely lists
            third += 1
            print(f"  be: skipped (not a Cedoca COI Focus): {date} {country}: {title} [{base}]", flush=True)
            continue
        src.fetch(rep, date, country, "COI Focus " + country + ": " + title, index_url=rep)
        note = res.get("note")
        if note and country not in notes_done and not src.full():
            notes_done.add(country)
            m = re.search(r"_(\d{4})(\d\d)(\d\d)", note)
            ndate = "-".join(m.groups()) if m else date
            src.fetch(note, ndate, country, f"Beleidsnota {country} (CGVS policy note)",
                      name_hint=f"beleidsnota_{slug(country)}_{ndate}.pdf")
    src.finish(f"{third} listed reports of other bodies (EUAA etc.) left out.")


# --- Austria: BFA Staatendokumentation via ecoi.net ----------------------------

ECOI = "https://www.ecoi.net"
ECOI_BFA = "10998"       # ecoi.net source id of "BFA Staatendokumentation"


def at():
    src = Source("at")
    items, n, pages = [], 1, 1
    while n <= pages:
        b = get(f"{ECOI}/de/dokumentensuche/search-v2?srcId%5B%5D={ECOI_BFA}&srcIdOperator=should"
                f"&sort_by=origPublicationDate&sort_order=desc&useSynonyms=Y&page={n}")
        if b is None:
            break
        d = json.loads(b)
        pages = d.get("pages", pages)
        for li in d["content"].split('<li class="doc-listelement"')[1:]:
            if f"/quelle/{ECOI_BFA}.html" not in li:          # strictly BFA documents only
                continue
            meta = re.findall(r'<p class="doc-metadata">(.*?)</p>', li, flags=re.S)
            h4 = re.search(r"<h4>(.*?)</h4>", li, flags=re.S)
            o = re.search(r'<p class="doc-origtitle"><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*(?:<small>\((.*?)\)</small>)?',
                          li, flags=re.S)
            did = re.search(r'data-ecoi-id="(\d+)"', li)
            if not (o and did):
                continue
            title = clean(o.group(2))
            if h4 and clean(h4.group(1)) and clean(h4.group(1)) != title:
                title = f"{title} [{clean(h4.group(1))}]"
            if o.group(3):
                title += f" ({clean(o.group(3))})"
            items.append((parse_date(clean(meta[0]).split("|")[0]) if meta else "0000-00-00",
                          clean(meta[1]) if len(meta) > 1 else "", title,
                          urllib.parse.urljoin(ECOI, html.unescape(o.group(1))), did.group(1)))
        if n % 5 == 0:
            print(f"  ecoi listing page {n}/{pages}", flush=True)
        n += 1
    items.sort(key=lambda x: x[0], reverse=True)
    for date, country, title, url, did in items:
        if src.full():
            src.skipped_cap.append(date)
            continue
        permalink = f"{ECOI}/de/dokument/{did}.html"
        if "/file/local/" in url:
            src.fetch(url, date, country, title, index_url=permalink,
                      name_hint=f"{did}_{url.rsplit('/', 1)[-1]}")
        elif url.startswith(ECOI + "/de/dokument/"):
            # full text is the ecoi.net page itself (exports from the BFA's COI-CMS)
            src.fetch(url, date, country, title, name_hint=f"{did}_{slug(title, 70)}.html", ext=".html")
        else:
            print(f"  at: skipped, held on another site: {date} {title} {url}", flush=True)
    src.finish()


# --- Switzerland: SEM Länderanalyse ---------------------------------------------

CH_PAGE = "https://www.sem.admin.ch/de/herkunftslaenderinformationen"


def ch():
    src = Source("ch")
    t = page(CH_PAGE)
    if t is None:
        return src.finish("listing page not available")
    items, country = [], ""
    for m in re.finditer(r'<h([23])[^>]*>(.*?)</h\1>|<a class="download-item"[^>]*href="([^"]+)"[^>]*>.*?'
                         r'<h4 class="download-item__title">(.*?)</h4>(.*?)</a>', t, flags=re.S):
        if m.group(1):
            country = clean(m.group(2))
            continue
        title = clean(m.group(4))
        meta = [clean(x) for x in re.findall(r'<span class="meta-info__item">(.*?)</span>', m.group(5))]
        date = parse_date(meta[-1] if meta else "")
        d2 = re.findall(r"\((\d{1,2}\.\d{1,2}\.\d{4})", title)
        if d2 and "1990" < parse_date(d2[-1]) <= time.strftime("%Y-%m-%d"):   # the title date is the report's own
            date = parse_date(d2[-1])
        items.append((date, country, title, html.unescape(m.group(3))))
    items.sort(key=lambda x: x[0], reverse=True)
    seen = {}
    for date, country, title, url in items:
        if re.search(r"(?i)leitlinien|guidelines", title) or \
                (re.match(r"(?i)\s*(easo|euaa)", title) and not re.search(r"SEM", title)):
            print(f"  ch: skipped (not an SEM report): {title}", flush=True)
            continue
        if url in seen:              # reports on two countries are listed under both
            for r in src.rows:
                if r[4] == url and country not in r[1]:
                    src.rows[src.rows.index(r)] = (r[0], r[1] + " / " + country, r[2], r[3], r[4])
            continue
        seen[url] = 1
        if src.full():
            src.skipped_cap.append(date)
            continue
        src.fetch(url, date, country, title)
    src.finish()


SOURCES = {"de": de, "nl": nl, "be": be, "at": at, "ch": ch}

def _term(*_):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _term)
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SOURCES)
    for w in wanted:
        if w not in SOURCES:
            sys.exit(f"unknown source {w!r}; choose from {', '.join(SOURCES)}")
    for w in wanted:
        print(f"== {w} ==", flush=True)
        try:
            SOURCES[w]()
        except Blocked as e:
            print(f"== {w}: STOPPED: {e}", flush=True)
            if CURRENT and CURRENT[0].name == w:
                CURRENT[0].finish("Stopped early (site refused a request or downloads kept failing).")
        except KeyboardInterrupt:
            if CURRENT and CURRENT[0].name == w:
                CURRENT[0].finish("Interrupted; index.tsv lists what was saved so far.")
            sys.exit(1)

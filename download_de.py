#!/usr/bin/env python3
"""Download published administrative guidance on residence law that German
authorities (other than Berlin) issue to their immigration offices.

    ./download_de.py            everything
    ./download_de.py bund ni    only the named sources

Sources (one subfolder of de/ each):
    bund  AVwV AufenthG etc. (verwaltungsvorschriften-im-internet.de), BMI Anwendungshinweise
          (bmi.bund.de), Visumhandbuch (auswaertiges-amt.de), BMI circulars republished by Lower Saxony
    ni    Lower Saxony: "Niedersaechsische Erlasse" list of the interior ministry
    nw    North Rhine-Westphalia: MKJFGFI "Erlasse zum Aufenthalts- und Asylrecht"
    bw    Baden-Wuerttemberg: JuM "Erlasse und Anwendungshinweise"
    bb    Brandenburg: "Allgemeine Weisungen im Auslaenderrecht" in BRAVORS (current + archive), as HTML
    hh    Hamburg: Weisungen / Fachanweisungen / Anordnungen of the Amt fuer Migration
    hb    Bremen: Erlasse zum Auslaenderrecht + naturalisation Erlasse
    sh    Schleswig-Holstein: Erlasse zum Aufenthalts-, Asyl- und Staatsangehoerigkeitsrecht
    rp    Rhineland-Palatinate: residence-law items of "Rundschreiben zur Fluechtlingspolitik"
    th    Thuringia: Erlasse indexed by Fluechtlingsrat Thueringen (via Wayback Machine snapshot)
    by    Bavaria: IMS / Vollzugshinweise formerly on stmi.bayern.de (via Wayback Machine)
    he    Hesse: a few Erlasse mirrored by the Hessischer Fluechtlingsrat
    sn    Saxony: the handful of VwV / Erlasse in REVOSax
    (mv, sl, st: no systematic publication found)

Files already present are skipped, so the script can be re-run. de/index.tsv is rewritten
on every run from the listings (columns: file, jurisdiction, title, date, source URL).
Requests are sequential with a pause between them; a 403/429 answer stops that host for the run.
"""
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "de"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 0.5                                   # seconds between requests
SLOW = {"www.bmi.bund.de": 4.0, "www.schleswig-holstein.de": 3.0, "dokumente.hamburg.de": 2.0,"web.archive.org": 5.0}   # hosts that rate-limit quickly
MAX_FILES, MAX_BYTES = 3000, 1_000_000_000

# Cookies are kept like a normal browser would (bmi.bund.de refuses clients without them).
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
OPENER.addheaders = [("User-Agent", UA)]
BLOCKED = {}                                  # host -> reason
RESETS = {}                                   # host -> consecutive dropped connections
CACHE_FILE = ROOT / ".landing-cache.json"     # landing page -> [file url, page title, extra], so re-runs skip those pages
CACHE = {}
ROWS = []                                     # index rows
STATS = {"new": 0, "bytes": 0}
_last = [0.0]


def get(url, data=None, tries=2):
    """Return (bytes, final_url) or (None, None). Never retries a 403/429."""
    host = urllib.parse.urlsplit(url).netloc
    if host in BLOCKED:
        return None, None
    body = bytearray()                        # kept across attempts: a dropped transfer is resumed, not restarted
    for attempt in range(tries + 3):
        wait = SLOW.get(host, PAUSE) - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(quote(url), data)
            if body:
                req.add_header("Range", f"bytes={len(body)}-")
            with OPENER.open(req, timeout=180) as r:
                if body and r.status != 206:  # server ignored the Range header: start again
                    body.clear()
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    body += chunk
                total = r.headers.get("Content-Length")
                if r.status == 200 and total and int(total) > len(body):
                    raise OSError(f"short read {len(body)}/{total}")
                _last[0] = time.time()
                RESETS[host] = 0
                return bytes(body), r.geturl()
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code in (403, 429):
                BLOCKED[host] = f"HTTP {e.code}"
                print(f"  BLOCKED {host}: HTTP {e.code} - skipping this host for the rest of the run")
                return None, None
            err = e
            if e.code in (404, 410, 416) or attempt + 1 >= tries:
                break
        except Exception as e:                # noqa: BLE001 - report and retry / resume
            _last[0] = time.time()
            err = e
            if not body and attempt + 1 >= tries:
                break
            if "refused" in str(e) or "reset" in str(e):     # busy server: give it a real pause before the one retry
                time.sleep(30)
        time.sleep(3)
    print(f"  FAILED {url}: {err}")
    if "refused" in str(err) or "reset" in str(err):
        RESETS[host] = RESETS.get(host, 0) + 1
        if RESETS[host] >= 3:                 # the server keeps dropping us: treat it like a 429 and back off
            BLOCKED[host] = "repeated connection resets"
            print(f"  BLOCKED {host}: repeated connection resets - skipping this host for the rest of the run")
    return None, None


def quote(url):
    """Percent-encode non-ASCII characters and spaces without touching existing escapes."""
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def page(url, data=None):
    body, final = get(url, data)
    if body is None:
        return "", url
    return body.decode("utf-8", "replace"), final


def resolve(landing, pattern, extra=None):
    """Find the file a download page points to: (file url, page title, extra regex group) or None. Cached."""
    if landing not in CACHE:
        markup, base = page(landing)
        hit = next(iter(links(markup, base, pattern)), None)
        if not hit:
            return None
        t = re.search(r"<title>(.*?)</title>", markup, flags=re.S)
        x = re.search(extra, markup) if extra else None
        CACHE[landing] = [hit[0], clean(t.group(1)) if t else "", clean(x.group(1)) if x else ""]
        CACHE_FILE.write_text(json.dumps(CACHE, indent=0, ensure_ascii=False), encoding="utf-8")
    return CACHE[landing]


def slug(s, n=110):
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = s.replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue").replace("§", "Par")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n].strip("-.") or "x"


def clean(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).replace("\u00ad", "").split())


MONTHS = {m: i + 1 for i, m in enumerate(
    "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split())}


def find_date(*texts):
    """Best-effort ISO date from a title or file name."""
    for t in texts:
        t = urllib.parse.unquote(t or "")
        m = re.search(r"(?<!\d)(20\d\d|19\d\d)[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)", t)
        if m:
            return "-".join(m.groups())
        m = re.search(r"(?<!\d)(0?[1-9]|[12]\d|3[01])\.\s?(0?[1-9]|1[0-2])\.\s?((?:19|20)?\d\d)(?!\d)", t)
        if m:
            d, mo, y = m.groups()
            y = y if len(y) == 4 else ("20" if int(y) < 50 else "19") + y
            return f"{y}-{int(mo):02d}-{int(d):02d}"
        m = re.search(r"(?<!\d)(0?[1-9]|[12]\d|3[01])\.\s*(" + "|".join(MONTHS) + r")\s+((?:19|20)\d\d)", t)
        if m:
            return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
        m = re.search(r"(?:^|[/_ ])([012]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[_-]", t)   # YYMMDD_ prefix
        if m:
            return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


GENERIC = re.compile(r"^(Erlass des Minist|RdErl\.? des|Runderlass des|PDF herunterladen|hier$|Download|Erlass (Übersendung|Anwendungshinweise)$)", re.I)


def links(markup, base, pattern):
    """Yield (absolute url, title) for <a> elements whose href matches pattern.
    Generic link texts ("PDF herunterladen") are prefixed with the text just before the link."""
    seen = set()
    for m in re.finditer(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', markup, flags=re.S):
        href = urllib.parse.urljoin(base, html.unescape(m.group(1)))
        if not re.search(pattern, href, flags=re.I) or href in seen:
            continue
        seen.add(href)
        text = clean(m.group(2))
        if not text or GENERIC.search(text):
            # the nearest non-empty block of text in front of the link (same paragraph, else the one before)
            blocks = re.split(r"</p>|</li>|</h\d>|</div>|</td>|</a>", markup[max(0, m.start() - 1500):m.start()])
            before = next((c for c in map(clean, reversed(blocks[1:] or blocks)) if c), "")[-220:]
            text = f"{before} - {text}".strip(" -") if before else text
        yield href, text


class Source:
    def __init__(self, code, jurisdiction):
        self.code, self.jur = code, jurisdiction
        self.dir = ROOT / code
        self.dir.mkdir(parents=True, exist_ok=True)
        self.names = {}                       # file name -> url, to keep names unique
        self.count = 0

    def name(self, url, title, date, ext):
        base = slug(f"{date}_{title}" if date and date not in title else title)
        name, i = f"{base}{ext}", 2
        while self.names.get(name, url) != url:
            name, i = f"{base}-{i}{ext}", i + 1
        self.names[name] = url
        return name

    def save(self, url, title, date="", ext=".pdf", source_url=None, fetch_url=None):
        """Download url (unless present) as <date>_<title><ext> and add an index row."""
        title = title.strip() or urllib.parse.unquote(url.rsplit("/", 1)[-1])
        date = date or find_date(title, url.rsplit("/", 1)[-1])
        dest = self.dir / self.name(url, title, date, ext)
        if not (dest.exists() and dest.stat().st_size > 0):
            if STATS["new"] >= MAX_FILES or STATS["bytes"] >= MAX_BYTES:
                print("  limit reached, not downloading more")
                return False
            body, _ = get(fetch_url or url)
            if body is None:
                return False
            if ext == ".pdf" and not body[:1024].lstrip().startswith(b"%PDF"):
                print(f"  NOT A PDF, skipped: {url}")
                return False
            if ext == ".pdf" and b"%%EOF" not in body[-4096:]:
                print(f"  TRUNCATED PDF, skipped: {fetch_url or url}")
                return False
            dest.write_bytes(body)
            STATS["new"] += 1
            STATS["bytes"] += len(body)
        self.count += 1
        ROWS.append((f"{self.code}/{dest.name}", self.jur, title, date, source_url or url))
        return True

    def done(self):
        size = sum(f.stat().st_size for f in self.dir.iterdir() if f.is_file())
        print(f"{self.code}: {self.count} documents indexed, folder holds {size / 1e6:.1f} MB")


# --- Federal level ----------------------------------------------------------

VVBUND = "https://www.verwaltungsvorschriften-im-internet.de/"
VVBUND_DOCS = [
    ("bsvwvbund_26102009_MI31284060.htm", "Allgemeine Verwaltungsvorschrift zum Aufenthaltsgesetz (AVwV AufenthG)", "2009-10-26"),
    ("bsvwvbund_03022016_MI12100972.htm", "Allgemeine Verwaltungsvorschrift zum Freizuegigkeitsgesetz/EU (AVV zum FreizuegG/EU)", "2016-02-03"),
    ("bsvwvbund_26102009_MI6936050300.htm", "Allgemeine Verwaltungsvorschrift zum AZR-Gesetz und zur AZRG-DV", "2009-10-26"),
    ("bsvwvbund_20062013_MI612000582.htm", "AVV Visa-Warndatei", "2013-06-20"),
]
BMI = "https://www.bmi.bund.de/SharedDocs/downloads/DE/"
BMI_DOCS = [
    "veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.html",
    *[f"veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/{a}.html" for a in
      ("anlage1_neu", "anlage2_neu", "anlage3", "anlage7_neu", "anlage8_neu", "anlage9", "anlage10", "anlage11")],
    "veroeffentlichungen/themen/migration/anwendungshinweise-zum-gesetz-ueber-duldung-bei-ausbildung.html",
    "veroeffentlichungen/themen/migration/anwendungshinweise-duldungsregelung.html",
    "veroeffentlichungen/themen/migration/anwendungshinweise-assoziationsrecht-ewg-tuerkei.html",
    "veroeffentlichungen/themen/migration/arbeitshinweise-umsetzung-aufenhaltsrechtliche-richtlinien-zur-arbeitsmigration.html",
    "veroeffentlichungen/themen/migration/brexit-rundschreiben.html",
    "veroeffentlichungen/themen/verfassung/anwendungshinweise-umsetzung-freizuegigkeitsgesetz.html",
    "veroeffentlichungen/themen/verfassung/staatsangehoerigkeit/2505_anwendungshinweise-staatsangehoerigkeit.html",
    "veroeffentlichungen/themen/verfassung/staatsangehoerigkeit/laenderRS-persoenlVorsprachenStAG2025.html",
    "publikationen/themen/migration/BMI23002-Handlungsleitfaden-rueckkehrberatung.html",
    "publikationen/BMI25075.html",
    "publikationen/BMI26019.html",
]
AA_DOCS = [
    ("https://www.auswaertiges-amt.de/resource/blob/207816/9c44508ca517f266c6ea950e44e41b87/visumhandbuch-data.pdf",
     "Visumhandbuch des Auswaertigen Amts", ""),
    ("https://www.auswaertiges-amt.de/resource/blob/2666740/2fddb25ac21779d9659ab9008192167e/240711-handreichung-studierendenvisa-data.pdf",
     "Handreichung Studierendenvisa (Auswaertiges Amt)", "2024-07-11"),
]
NI_LIST = ("https://www.mi.niedersachsen.de/startseite/themen/auslanderangelegenheiten/zahlen_daten_fakten/"
           "niedersachsische_erlasse/niedersachsische-erlasse-139998.html")
NI_FEDERAL = re.compile(r"^\S+\s+(ANLAGE|Anlage)?[ _\d]*(BMI|BMAS|BAMF|AA)\b|^\S+\s+Aktualisierte Anwendungshinweise des BMI")
NI_SKIP = re.compile(r"AufnG|Aufnahmegesetz|Kostenabgeltung|Landesaufnahmeeinrichtung|AsylbLG|Asylbewerberleistung|"
                     r"Aufnahmequote|Verteilung|Vordruck|Unterbringung", re.I)


def ni_items():
    markup, base = page(NI_LIST)
    for href, text in links(markup, base, r"/download/\d+/.*\.pdf$"):      # the few .docx/.xlsx items are forms
        title = re.sub(r"\s*-\s*Download.*$", "", text).strip()
        if not NI_SKIP.search(title):
            yield href, title


def bund():
    s = Source("bund", "Bund")
    for doc, title, date in VVBUND_DOCS:
        markup, base = page(VVBUND + doc)
        pdfs = [h for h, _ in links(markup, base, r"pdf/[^/]+\.pdf$")]
        for i, href in enumerate(pdfs):
            s.save(href, title if i == 0 else f"{title} - Teil {i + 1}", date)
        if markup and not pdfs:
            s.save(VVBUND + doc, title, date, ext=".html")
    for url, title, date in AA_DOCS:
        s.save(url, title, date)
    for doc in BMI_DOCS:
        hit = resolve(BMI + doc, r"\.pdf\?__blob=publicationFile")
        if hit:
            title = re.sub(r"^BMI\s*-\s*(Publikationen|Downloads|Homepage)?\s*-?\s*", "", hit[1]) or doc
            s.save(hit[0], title, source_url=BMI + doc) or CACHE.pop(BMI + doc, None)
    for href, title in ni_items():            # federal circulars republished by Lower Saxony
        if NI_FEDERAL.search(title):
            s.save(href, title)
    s.done()


# --- Laender with a listing page -------------------------------------------

def ni():
    s = Source("ni", "Niedersachsen")
    for href, title in ni_items():
        if not NI_FEDERAL.search(title):
            s.save(href, title)
    s.done()


NW_LIST = "https://www.mkjfgfi.nrw/erlasse-zum-aufenthalts-und-asylrecht"
NW_SKIP = re.compile(r"AsylbLG|Fl(ü|ue)AG|Fl(ü|ue)chtlingsaufnahmegesetz|Taxikosten|Gesundheits(untersuchung|versorgung|kontrolle)|Bargeld|"
                     r"Integrationskurs|Zuweisungspraxis|Bezahlkarte", re.I)


def nw():
    s = Source("nw", "Nordrhein-Westfalen")
    markup, base = page(NW_LIST)
    main = markup[markup.find("<main"):] if "<main" in markup else markup
    for href, title in links(main, base, r"\.pdf$|/dokument/"):   # (old recht.nrw.de links on the page are dead)
        if NW_SKIP.search(title):
            continue
        if "/dokument/" in href:
            hit = resolve(href, r"/files/.*\.pdf$")
            if hit:
                s.save(hit[0], title, source_url=href) or CACHE.pop(href, None)
        elif href.lower().endswith(".pdf"):
            # the ministry's former host name no longer resolves; its files are on the current host
            s.save(href, title, fetch_url=href.replace("//www.mkffi.nrw/", "//www.mkjfgfi.nrw/"))
    s.done()


BW_LIST = "https://jum.baden-wuerttemberg.de/de/migration/erlasse-und-anwendungshinweise"
BW_SKIP = re.compile(r"Fl(ü|ue|%C3%BC)AG|Bezahlkarte|Belegung|Pauschale|Liquidit|Statistik|AsylbLG|Anschlussversicherung|OAV", re.I)


def bw():
    s = Source("bw", "Baden-Wuerttemberg")
    markup, base = page(BW_LIST)
    for href, title in links(markup, base, r"/Erlasse_und_Anwendungshinweise/.*\.pdf$"):
        if not BW_SKIP.search(title + href):
            s.save(href, title)
    s.done()


BB = "https://bravors.brandenburg.de"


def bb_search(form, term, max_pages=6):
    """BRAVORS quick search (a session form); returns {path: title}."""
    data = urllib.parse.urlencode({"search[art_vorschrift]": "alle", "search[searchterm]": term,
                                   "suchen": "Suchen"}).encode()
    markup, _ = page(f"{BB}/de/{form}", data)
    out, n = {}, 1
    while markup:
        before = len(out)
        for path, title in re.findall(r'<a href="(/verwaltungsvorschriften/[^"]+)"[^>]*title="([^"]*)" target', markup):
            out.setdefault(path, clean(html.unescape(title)))
        n += 1
        if len(out) == before or n > max_pages or f'/ergebnis/page/{n}"' not in markup:
            break
        markup, _ = page(f"{BB}/de/{form}/ergebnis/page/{n}")
    return out


def bb():
    s = Source("bb", "Brandenburg")
    found = {}
    for form, status in (("vorschriften_schnellsuche", ""), ("archiv_schnellsuche", "Archiv: ")):
        for path, title in bb_search(form, "AW-AuslR").items():
            found.setdefault(path, status + title)
    # older "Erlass Nr. x/2017 im Auslaenderrecht" documents: relevance-sorted full-text search, first pages only
    for path, title in bb_search("vorschriften_schnellsuche", "Erlass im Ausländerrecht", max_pages=4).items():
        if re.search(r"im Ausländerrecht|Aufenthaltsrecht|Rückführung|Abschiebung", title):
            found.setdefault(path, title)
    for path, title in found.items():
        m = re.search(r"aw_+(?:auslr_+)?(?:nr_+)?(\d{4})|_(\d{4})$|_(\d\d)$", path)
        year = next((g for g in m.groups() if g), "") if m else ""
        year = year if len(year) == 4 else ("20" + year if year else "")
        # dates inside these titles usually refer to other documents, so only the year of issue is recorded
        m = None if year else re.search(r"(?:Erlass|Weisung) Nr\. ?\d+[a-z]?\s?/\s?(\d{4})", title)
        s.save(BB + path, title, year or (m.group(1) if m else ""), ext=".html")
    s.done()


HH = ("https://www.hamburg.de/politik-und-verwaltung/behoerden/behoerde-fuer-inneres-und-sport/aemter/amt-fuer-migration/"
      "zentrale-auslaenderangelegenheiten/allgemeines-aufenthaltsrecht-und-zentraler-service/")
HH_PAGES = ["eza-weisungen-auslaenderrecht-39300", "aufenthaltsrechtliche-anordnungen-91900", "archiv-91978"]


def hh():
    s = Source("hh", "Hamburg")
    for p in HH_PAGES:
        markup, base = page(HH + p)
        main = markup[markup.find("<main"):] if "<main" in markup else markup
        for href, title in links(main, base, r"dokumente\.hamburg\.de/resource/blob/.*\.pdf$"):
            fname = href.rsplit("/", 1)[-1]
            m = re.search(r"(?:weisung|anordnung)-(\d+)-(\d{4})|anordnung-(\d{4})-(\d+)", fname)
            title = re.sub(r"\s*-?\s*PDF herunterladen.*$", "", title).strip()
            if not title or title == "hier":
                title = fname[:-9] if fname.endswith("-data.pdf") else fname
            year = (m.group(2) or m.group(3)) if m else ""
            # Anordnungen carry expiry dates in their titles, so only their year of issue is recorded
            date = year if "anordnung" in fname else (find_date(title) or year)
            s.save(href, ("Archiv: " if p.startswith("archiv") else "") + title[:200], date)
    s.done()


HB = "https://www.inneres.bremen.de/inneres/buerger-und-staat/"
HB_PAGES = ["auslaenderangelegenheiten/erlasse-zum-auslaenderrecht-2422", "staatsangehoerigkeit-und-einbuergerung-2117"]


def hb():
    s = Source("hb", "Bremen")
    for p in HB_PAGES:
        markup, base = page(HB + p)
        for href, title in links(markup, base, r"/sixcms/media\.php/.*\.pdf$"):
            title = re.sub(r"\s*\(pdf,[^)]*\)\s*$", "", title)
            fname = urllib.parse.unquote(href.rsplit("/", 1)[-1])
            m = re.search(r"e(\d\d)-(\d\d)-\d\d", fname)       # Erlass number eYY-MM-NN
            date = f"20{m.group(1)}-{m.group(2)}" if m else ""
            s.save(href, (f"Erlass {m.group(0)} " if m else "") + title, date)
    s.done()


SH_LIST = "https://www.schleswig-holstein.de/DE/fachinhalte/I/integration/erlasse.html"
SH_SKIP = re.compile(r"Bezahlkarte|AsylbLG|Asylbewerberleistung|Unterbringung", re.I)


def sh():
    s = Source("sh", "Schleswig-Holstein")
    markup, base = page(SH_LIST)
    for href, title in links(markup, base, r"/_downloads/erlasse/"):
        if SH_SKIP.search(title):
            continue
        landing = href.split("?")[0]
        hit = resolve(landing, r"\.pdf\?__blob=publicationFile")
        if hit:
            d = re.match(r"(\d\d)(\d\d)(\d\d)_", landing.rsplit("/", 1)[-1])       # file names start YYMMDD_
            date = f"20{d.group(1)}-{d.group(2)}-{d.group(3)}" if d else ""
            s.save(hit[0], title, date, source_url=landing) or CACHE.pop(landing, None)   # failed: resolve afresh next time
    s.done()


RP_LIST = "https://mdi.rlp.de/themen/integration/rundschreiben-zur-fluechtlingspolitik-1"
RP_KEEP = re.compile(r"aufenth|duld|fiktion|dublin|ausreise|r(ü|ue)ckkehr|abschieb|pass|visum|einreise|h(ä|ae)rtefall", re.I)
RP_SKIP = re.compile(r"AsylbLG|Asylbewerberleistung|Leistungss|Landesaufnahmegesetz|Verteil|Statistik|F(ö|oe)rder|Bezahlkarte", re.I)


def rp():
    s = Source("rp", "Rheinland-Pfalz")
    markup, base = page(RP_LIST)
    for href, title in links(markup, base, r"/fileadmin/.*\.pdf$"):
        both = title + " " + urllib.parse.unquote(href)
        if RP_KEEP.search(both) and not RP_SKIP.search(both):
            s.save(href, title)
    s.done()


# --- Laender without a usable official listing ------------------------------

WB = "https://web.archive.org/web/"
TH_SNAPSHOT = "20260616221922"
TH_LIST = "https://www.fluechtlingsrat-thr.de/arbeitshilfen/gesetze-verordnungen-u-erlasse"
TH_SKIP = re.compile(r"AsylbLG|AsylblG|Fahrtkosten|Maskenschutz|Unterbringung", re.I)


def th():
    """Fluechtlingsrat Thueringen's index of state Erlasse; the live site only served a placeholder,
    so the list and the files come from a Wayback Machine snapshot."""
    s = Source("th", "Thueringen")
    markup, base = page(f"{WB}{TH_SNAPSHOT}/{TH_LIST}")
    for href, title in links(markup, base, r"gesetze_verordnungen/thueringen/.*\.pdf$"):
        orig = href[href.find("http", 10):]                      # strip the Wayback prefix
        if TH_SKIP.search(title + urllib.parse.unquote(orig)):
            continue
        s.save(orig, title, find_date(urllib.parse.unquote(orig.rsplit("/", 1)[-1]), title),
               fetch_url=f"{WB}{TH_SNAPSHOT}id_/{orig}", source_url=f"{WB}{TH_SNAPSHOT}/{orig}")
    s.done()


BY_OLD = "https://www.stmi.bayern.de/assets/stmi/mui/"
BY_DOCS = [   # (Wayback timestamp, path under BY_OLD, title, date); the ministry's relaunched site dropped these files
    ("20190918035941", "asylmigration/190308_vollzugshinweise_zur_beschäftigung_und_berufsausbildung_von_asylbewerbern_und_geduldeten.pdf",
     "IMS Vollzugshinweise zur Beschaeftigung und Berufsausbildung von Asylbewerbern und Geduldeten", "2019-03-08"),
    ("20190918000000", "asylmigration/190308_vollzugshinweise_zur_vorfeldregelung_beschäftigungsduldung.pdf",
     "IMS Vollzugshinweise zur Vorfeldregelung Beschaeftigungsduldung", "2019-03-08"),
    ("20200927105838", "vollzugshinweise_zur_beschäftigung_und_berufsausbildung_von_asylbewerbern_und_geduldeten_vom_13.07.2020.pdf",
     "IMS Vollzugshinweise zur Beschaeftigung und Berufsausbildung von Asylbewerbern und Geduldeten", "2020-07-13"),
    ("20230308014523", "asylsozialpolitik/vollzugshinweise_zur_beschäftigung_und_berufsausbildung_von_asylbewerbern_und_geduldeten_mit_§_61_asylg.pdf",
     "IMS Vollzugshinweise zur Beschaeftigung und Berufsausbildung von Asylbewerbern und Geduldeten (mit Par 61 AsylG)", "2022-03-24"),
    ("20240703203542", "asylsozialpolitik/2024-04-02-vollzugshinweise_zur_beschäftigung_und_berufsausbildung_von_asylbewerbern_und_geduldeten.pdf",
     "IMS Vollzugshinweise zur Beschaeftigung und Berufsausbildung von Asylbewerbern und Geduldeten", "2024-04-02"),
    ("20230308014534", "integrationspolitik/ims_vollzug_chancen-aufenthaltsrecht.pdf",
     "IMS Vollzug des Chancen-Aufenthaltsrechts", "2022-12-22"),
    ("20240613144219", "f2-2082-1-79-8_ims_zu_25a_25b_aufenthg.pdf", "IMS zu Par 25a und 25b AufenthG", ""),
]


def by():
    s = Source("by", "Bayern")
    for ts, path, title, date in BY_DOCS:
        s.save(BY_OLD + path, title, date, fetch_url=f"{WB}{ts}id_/{BY_OLD}{path}", source_url=f"{WB}{ts}/{BY_OLD}{path}")
    s.done()


HE_DOCS = [   # copies kept by the Hessischer Fluechtlingsrat; the ministry itself publishes no collection
    ("https://fr-hessen.de/wp-content/uploads/2022/07/2022-07-19_Vorgriffserlass_Chancen-Aufenthaltsrecht.pdf",
     "HMdIS Vorgriffserlass Chancen-Aufenthaltsrecht", "2022-07-19"),
    ("https://fr-hessen.de/wp-content/uploads/2022/01/2021-12-21_Petitionserlass.pdf",
     "HMdIS Petitionserlass (aufenthaltsrechtliche Petitionen)", "2021-12-21"),
]


def he():
    s = Source("he", "Hessen")
    for url, title, date in HE_DOCS:
        s.save(url, title, date)
    s.done()


SN_IDS = [2958, 1645, 10643, 5417, 11244, 9411, 9523, 20988]   # REVOSax numbers of Auslaenderrecht VwV / Erlasse


def sn():
    s = Source("sn", "Sachsen")
    for i in SN_IDS:
        url = f"https://www.revosax.sachsen.de/vorschrift/{i}"
        hit = resolve(url, r"vorschrift_gesamt/\d+/\d+\.pdf$", r"Fassung gültig ab:\s*([^<]+)")
        if hit:
            title = re.sub(r"^REVOSax Landesrecht Sachsen - ", "", hit[1]) or f"REVOSax {i}"
            s.save(hit[0], title, find_date(hit[2]), source_url=url) or CACHE.pop(url, None)
    s.done()


SOURCES = {"bund": bund, "ni": ni, "nw": nw, "bw": bw, "bb": bb, "hh": hh, "hb": hb, "sh": sh,
           "rp": rp, "th": th, "by": by, "he": he, "sn": sn}


def write_index():
    """Rewrite de/index.tsv: fresh rows from this run; an old row is kept when its file still exists
    and this run did not list it again (source not run, or its listing could not be fetched)."""
    index = ROOT / "index.tsv"
    new = {r[0]: tuple(c.replace("\t", " ").replace("\n", " ") for c in r) for r in ROWS}
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) == 5 and cols[0] not in new and (ROOT / cols[0]).is_file():
                new[cols[0]] = tuple(cols)
    rows = [new[k] for k in sorted(new)]
    with index.open("w", encoding="utf-8") as f:
        f.write("file\tjurisdiction\ttitle\tdate\tsource_url\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"index.tsv: {len(rows)} rows")


def main():
    wanted = sys.argv[1:] or list(SOURCES)
    unknown = [w for w in wanted if w not in SOURCES]
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(unknown)}; choose from {', '.join(SOURCES)}")
    ROOT.mkdir(exist_ok=True)
    if CACHE_FILE.exists():
        CACHE.update(json.loads(CACHE_FILE.read_text(encoding="utf-8")))
    for w in wanted:
        print(f"== {w}")
        SOURCES[w]()
    write_index()
    print(f"downloaded {STATS['new']} new files, {STATS['bytes'] / 1e6:.1f} MB")
    for host, why in BLOCKED.items():
        print(f"blocked: {host} ({why})")


if __name__ == "__main__":
    main()

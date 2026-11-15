#!/usr/bin/env python3
"""Download the directives that Swiss cantonal migration and naturalisation authorities publish
for deciding residence, family-reunification, settlement-permit and naturalisation cases
(Weisungen, Praxisfestlegungen, Handbuecher, directives, circulaires, direttive).

    ./download_ch_cantons.py            every canton that publishes something
    ./download_ch_cantons.py zh vd      only the named cantons

Files go to ch/cantons/<canton code>/, unmodified, named <date>_<title>.<ext> where a date
(Stand / etat au) is known.  ch/cantons/index.tsv (file, canton, title, date, source_url) is
rewritten on every run; rows of cantons that were not run, or whose listing could not be
fetched, are kept.  What each canton publishes (and the cantons that publish nothing
systematic) is described in ch/cantons/NOTES.txt, which this script does not touch.

Rules the script keeps:
  * robots.txt of every host is read first and obeyed for the generic user agent
    (including Crawl-delay); a disallowed URL is reported and not fetched;
  * one request at a time, at least PAUSE seconds between requests to the same host;
  * HTTP 403/429 stops the use of that host for the rest of the run, as do three
    dropped connections in a row;
  * files already present are not fetched again (ch/cantons/.manifest.json remembers which
    URL became which file), so the script is safe to re-run;
  * only the Python standard library is used.  If the `pdftotext` program is installed it is
    used to read the Stand date from the first pages of a new PDF; without it such files
    simply get no date prefix.
"""
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "ch" / "cantons"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 1.5                                   # seconds between requests to one host
SLOW = {"web.archive.org": 4.0}
MAX_FILES, MAX_BYTES = 3000, 1_000_000_000



class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if robots.txt of the target allows it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise urllib.error.URLError(f"redirect target not allowed by robots.txt: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(CheckedRedirect())
OPENER.addheaders = [("User-Agent", UA), ("Accept-Language", "de,fr,it,en;q=0.5")]
BLOCKED = {}                                  # host -> reason
RESETS = {}                                   # host -> consecutive dropped connections
ROBOTS = {}                                   # host -> Robots (None: could not be read)
LAST = {}                                     # host -> time of last request
MANIFEST_FILE = ROOT / ".manifest.json"
MANIFEST = {}                                 # url -> {"file", "canton", "title", "date"}
ROWS = []                                     # index rows of this run
LISTED = set()                                # canton codes whose listing worked in this run
MISSED = []                                   # (canton, title, url, reason)
STATS = {"new": 0, "bytes": 0}
PDFTOTEXT = shutil.which("pdftotext")


def quote(url):
    """Percent-encode non-ASCII characters and spaces without touching existing escapes."""
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def _open(url, host, data=None):
    wait = max(SLOW.get(host, PAUSE), getattr(ROBOTS.get(host), "delay", 0) or 0) - (time.time() - LAST.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        with OPENER.open(urllib.request.Request(quote(url), data), timeout=180) as r:
            body = r.read()
            total = r.headers.get("Content-Length")
            if total and int(total) > len(body):
                raise OSError(f"short read {len(body)}/{total}")
            return body, r.geturl()
    finally:
        LAST[host] = time.time()


class Robots:
    """robots.txt rules for the generic user agent, with the * and $ wildcards that
    urllib.robotparser ignores. The longest matching rule wins; Allow wins a tie."""

    def __init__(self, text):
        groups, agents, rules, fresh = [], [], [], True
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not fresh:                 # a new group starts after the rules of the previous one
                    agents, rules, fresh = [], [], True
                    groups.append((agents, rules))
                elif not groups or groups[-1][0] is not agents:
                    groups.append((agents, rules))
                agents.append(value.lower())
            elif key in ("allow", "disallow", "crawl-delay"):
                fresh = False
                rules.append((key, value))
        # Rules for "*" plus any group addressed to Claude/Anthropic agents: this collection has been
        # run by such an agent, and a site that shuts those out by name is left alone.
        mine = [r for ag, rs in groups if any(a == "*" or "claude" in a or "anthropic" in a for a in ag) for r in rs]
        self.rules, self.delay = [], 0.0
        for key, value in mine:
            if key == "crawl-delay":
                try:
                    self.delay = float(value)
                except ValueError:
                    pass
            elif value:
                rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in value.rstrip("$"))
                self.rules.append((len(value), key == "allow", re.compile(rx + ("$" if value.endswith("$") else ""))))

    def can_fetch(self, url):
        parts = urllib.parse.urlsplit(url)
        path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        best = (0, True)
        for path_form in {path, urllib.parse.unquote(path), quote(urllib.parse.unquote(path))}:
            for length, allow, rx in self.rules:
                if rx.match(path_form) and (length, allow) > best:
                    best = (length, allow)
            if not best[1]:
                return False
        return best[1]


BOTCHECK = re.compile(r"captcha|TSPD|enable JavaScript|cf-challenge|Access Denied|unusual traffic", re.I)


def allowed(url):
    """Read the host's robots.txt once; True if the generic user agent may fetch url."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host not in ROBOTS:
        rp = None
        try:
            body, _ = _open(f"{parts.scheme}://{host}/robots.txt", host)
            text = body.decode("utf-8", "replace")
            if "<html" in text[:2000].lower() and BOTCHECK.search(text):
                BLOCKED[host] = "bot check instead of robots.txt"
                print(f"  BLOCKED {host}: bot-check page served - host not used")
            else:                             # an ordinary HTML page here means: no robots.txt
                rp = Robots("" if "<html" in text[:2000].lower() else text)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):          # refused already at robots.txt: leave the host alone
                BLOCKED[host] = f"HTTP {e.code} on robots.txt"
                print(f"  BLOCKED {host}: HTTP {e.code} on robots.txt")
            elif 400 <= e.code < 500:         # no robots.txt: nothing is disallowed
                rp = Robots("")
            else:
                print(f"  robots.txt of {host}: HTTP {e.code} - host not used in this run")
        except Exception as e:                # noqa: BLE001
            print(f"  robots.txt of {host} unreadable ({e}) - host not used in this run")
        ROBOTS[host] = rp
    rp = ROBOTS[host]
    return bool(rp) and rp.can_fetch(url)


def get(url, data=None):
    """Return (bytes, final_url) or (None, reason). Never retries a 403/429."""
    host = urllib.parse.urlsplit(url).netloc
    if host in BLOCKED:
        return None, f"host blocked ({BLOCKED[host]})"
    if not allowed(url):
        why = BLOCKED.get(host) or ("robots.txt unreadable" if ROBOTS.get(host) is None else "disallowed by robots.txt")
        print(f"  NOT FETCHED ({why}): {url}")
        return None, why
    err = None
    for attempt in range(2):
        try:
            body, final = _open(url, host, data)
            RESETS[host] = 0
            return body, final
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                BLOCKED[host] = f"HTTP {e.code}"
                print(f"  BLOCKED {host}: HTTP {e.code} - skipping this host for the rest of the run")
                return None, f"HTTP {e.code}"
            err = f"HTTP {e.code}"
            if e.code in (404, 410):
                break
        except Exception as e:                # noqa: BLE001 - report, one retry
            err = str(e)
            if "refused" in err or "reset" in err:
                RESETS[host] = RESETS.get(host, 0) + 1
                if RESETS[host] >= 3:
                    BLOCKED[host] = "repeated connection resets"
                    print(f"  BLOCKED {host}: repeated connection resets - skipping this host for the rest of the run")
                    return None, err
                time.sleep(20)
        time.sleep(3)
    print(f"  FAILED {url}: {err}")
    return None, err


def page(url, data=None):
    body, final = get(url, data)
    if body is None:
        return "", url
    return body.decode("utf-8", "replace"), final


def clean(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).replace("­", "").split())


def slug(s, n=110):
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"),
                 ("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("â", "a"), ("ç", "c"), ("î", "i"), ("ô", "o"),
                 ("ù", "u"), ("û", "u"), ("œ", "oe"), ("É", "E"), ("È", "E"), ("À", "A"), ("ì", "i"), ("ò", "o"), ("§", "Par")):
        s = s.replace(a, b)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n].strip("-.") or "x"


MONTHS = {}
for _names in ("Januar Februar März April Mai Juni Juli August September Oktober November Dezember",
               "janvier février mars avril mai juin juillet août septembre octobre novembre décembre",
               "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre"):
    for _i, _m in enumerate(_names.split()):
        MONTHS[_m.lower()] = _i + 1
MONTHS.update({"fevrier": 2, "aout": 8, "decembre": 12, "maerz": 3})
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_RES = [
    (re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])(?:er|\.)?\s*(" + _MONTH_RE + r")\s+((?:19|20)\d\d)", re.I),
     lambda m: (m.group(3), MONTHS[m.group(2).lower()], m.group(1))),
    (re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])\.\s?(0?[1-9]|1[0-2])\.\s?((?:19|20)\d\d)(?!\d)"),
     lambda m: (m.group(3), m.group(2), m.group(1))),
    (re.compile(r"(?<!\d)((?:19|20)\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)"),
     lambda m: (m.group(1), m.group(2), m.group(3))),
]
_MONTH_YEAR = re.compile(r"\b(" + _MONTH_RE + r")\s+((?:19|20)\d\d)\b", re.I)


def find_date(text, month_ok=False):
    """First date in text as YYYY-MM-DD ('' if none). With month_ok, 'Januar 2024' gives 2024-01."""
    best = None
    for rx, conv in _DATE_RES:
        m = rx.search(text or "")
        if m and (best is None or m.start() < best[0]):
            y, mo, d = conv(m)
            best = (m.start(), f"{y}-{int(mo):02d}-{int(d):02d}")
    if best:
        return best[1]
    if month_ok:
        m = _MONTH_YEAR.search(text or "")
        if m:
            return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    return ""


STAND = re.compile(r"(Stand|Stand per|Version(?: vom)?|Fassung vom|g[üu]ltig ab|in Kraft (?:seit|ab)|Ausgabe|"
                   r"[ée]tat au|[ée]tat|valable d[èe]s(?: le)?|version du|mise [àa] jour(?: le| du)?|"
                   r"Inkrafttreten|genehmigt im|stato(?: al)?|aggiornat[oa](?: al)?|valida dal)\s*:?\s*(?:den |le |du |au |vom |per |il )?(.{0,40})", re.I)


def pdf_date(path, pages=2):
    """Stand date from the first pages of a PDF (needs pdftotext): a date after a keyword such as
    'Stand' / 'etat au', else the first full date on those pages."""
    if not PDFTOTEXT:
        return ""
    try:
        text = subprocess.run([PDFTOTEXT, "-l", str(pages), "-layout", str(path), "-"], capture_output=True,
                              timeout=60).stdout.decode("utf-8", "replace")
    except Exception:                         # noqa: BLE001
        return ""
    for m in STAND.finditer(" ".join(text.split())):
        d = find_date(m.group(2), month_ok=True)
        if d:
            return d
    return find_date(text)


MAGIC = {".pdf": (b"%PDF",), ".docx": (b"PK",), ".xlsx": (b"PK",), ".doc": (b"\xd0\xcf\x11\xe0",),
         ".html": (b"<",)}


def links(markup, base, pattern=r"\.pdf(\?|$)"):
    """Yield (absolute url, link text) for <a> elements whose href matches pattern, in page order."""
    seen = set()
    for m in re.finditer(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', markup, flags=re.S | re.I):
        href = urllib.parse.urljoin(base, html.unescape(m.group(1)).strip())
        if href in seen or not re.search(pattern, href, flags=re.I):
            continue
        seen.add(href)
        yield href, clean(m.group(2))


def section(markup, start, end=None):
    """The part of markup between the first match of start and the next match of end."""
    m = re.search(start, markup, flags=re.S | re.I)
    if not m:
        return ""
    rest = markup[m.end():]
    e = re.search(end, rest, flags=re.S | re.I) if end else None
    return rest[:e.start()] if e else rest


class Canton:
    def __init__(self, code, name):
        self.code, self.name = code, name
        self.dir = ROOT / code
        self.count = 0
        self.taken = {v["file"] for v in MANIFEST.values()}

    def save(self, url, title, date="", ext=None, source_url=None, date_from_pdf=True, date_in_title=True):
        """Download url (unless present) and add an index row. date: known Stand date, else it is
        looked for in the title and then inside the PDF."""
        title = clean(title) or urllib.parse.unquote(url.rsplit("/", 1)[-1])
        ext = ext or (re.search(r"\.(pdf|docx?|xlsx|html?)(?=$|\?)", url.lower()) or [".pdf"])[0]
        old = MANIFEST.get(url)
        if old and (ROOT / old["file"]).is_file() and (ROOT / old["file"]).stat().st_size > 0:
            self.count += 1
            ROWS.append((old["file"], self.name, title, old["date"], source_url or url))
            return True
        if STATS["new"] >= MAX_FILES or STATS["bytes"] >= MAX_BYTES:
            print("  limit reached, not downloading more")
            return False
        body, final = get(url)
        if body is None:
            MISSED.append((self.code, title, url, final))
            return False
        head = body[:2048].lstrip()
        if not any(head.startswith(sig) for sig in MAGIC.get(ext, (b"",))) or \
                (ext == ".pdf" and b"%%EOF" not in body[-4096:]):
            print(f"  NOT A VALID {ext} FILE, skipped: {url}")
            MISSED.append((self.code, title, url, f"answer is not a valid {ext} file"))
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / ".download.tmp"
        tmp.write_bytes(body)
        date = date or (find_date(title, True) if date_in_title else "")
        if not date and ext == ".pdf" and date_from_pdf:
            date = pdf_date(tmp)
        if not date:                          # upload folder of the file, e.g. /sites/default/files/2026-09/
            m = re.search(r"/(20\d\d)-(0[1-9]|1[0-2])/", final)
            date = f"{m.group(1)}-{m.group(2)}" if m else ""
        base = slug(f"{date}_{title}" if date else title)
        name, i = f"{self.code}/{base}{ext}", 2
        while name in self.taken or (ROOT / name).exists():
            name, i = f"{self.code}/{base}-{i}{ext}", i + 1
        tmp.rename(ROOT / name)
        self.taken.add(name)
        MANIFEST[url] = {"file": name, "canton": self.name, "title": title, "date": date}
        MANIFEST_FILE.write_text(json.dumps(MANIFEST, indent=0, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        STATS["new"] += 1
        STATS["bytes"] += len(body)
        self.count += 1
        ROWS.append((name, self.name, title, date, source_url or url))
        print(f"  + {name}")
        return True

    def done(self, listed=True):
        if listed:
            LISTED.add(self.code)
        print(f"  {self.code}: {self.count} files")


# --------------------------------------------------------------------------- Zuerich

ZH_PAGE = "https://www.zh.ch/de/sicherheitsdirektion/migrationsamt/formulare-broschueren-weisungen-des-migrationsamts.html"
ZH_NAT = "https://www.zh.ch/de/migration-integration/einbuergerung.html"


def zh_downloads(markup, base):
    """(url, title) of the download-list entries of a zh.ch page."""
    for m in re.finditer(r'<a class="atm-linklist_item[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', markup, flags=re.S):
        t = re.search(r'<span class="atm-linklist_item__text">\s*<span>(.*?)</span>', m.group(2), flags=re.S)
        yield urllib.parse.urljoin(base, html.unescape(m.group(1))), clean(t.group(1) if t else m.group(2))


def zh():
    """Migrationsamt: section 'Weisungen' of the forms/brochures/directives page (the forms that sit
    between the directives are left out). Gemeindeamt: the three editions of 'Handbuch Einbuergerungen'."""
    c = Canton("zh", "Zürich")
    markup, base = page(ZH_PAGE)
    part = section(markup, r"<h2[^>]*>\s*Weisungen\s*</h2>", r"<h3[^>]*>\s*Weisungen des SEM")
    ok = bool(part)
    for url, title in zh_downloads(part, base):
        if "/weisungen/" in url and not re.search(r"Liste.*Schulreise|formular", url, re.I):
            c.save(url, f"Weisung Migrationsamt: {title}", source_url=url)
    markup, base = page(ZH_NAT)
    ok = ok and bool(markup)
    seen = set()
    for url, title in zh_downloads(markup, base):
        if re.search(r"handbuch_einbuergerungen", url) and url not in seen:
            seen.add(url)
            c.save(url, re.sub(r"^Download\s*", "", title), date_in_title=False)   # "Altes Recht bis ..." is not the Stand
    c.done(ok)


# --------------------------------------------------------------------------- Solothurn

SO_NAT = "https://so.ch/verwaltung/volkswirtschaftsdepartement/amt-fuer-gemeinden/buergerrecht/informationen-rechtsgrundlagen-und-formulare/"
SO_EWK = "https://so.ch/verwaltung/volkswirtschaftsdepartement/amt-fuer-gemeinden/gemeindeorganisation/publikationen/einwohnerkontrolle/"
SO_SKIP = r"Informationen_zur|hb-bueg|eidg\.|VO_bund|kant\.|[Rr]eglement|Gesuchsformular|Fragebogen|Sprachnachweis|Meldung_"


def so():
    """Amt fuer Gemeinden: circulars and working aids for the communal naturalisation authorities
    (statutes, forms and the applicant information sheet are left out), and the chapters of the
    'Handbuch Einwohnerkontrolle' on foreign nationals, residence and citizenship.
    The Migrationsamt itself publishes only applicant leaflets and forms."""
    c = Canton("so", "Solothurn")
    markup, base = page(SO_NAT)
    ok = bool(markup)
    for url, title in links(markup, base, r"/Buergerrecht/[^/]+\.pdf$"):
        if not re.search(SO_SKIP, url):
            title = re.sub(r"\s*\(pdf, [^)]*\).*$", "", title)
            c.save(url, f"Bürgerrecht: {title}", find_date(title, True) or (re.search(r"(20\d\d)", title + url) or [""])[0])
    markup, base = page(SO_EWK)
    ok = ok and bool(markup)
    for url, title in links(markup, base, r"/Handbuch_EWK/.*/(03|05|10)-[^/]+\.pdf$"):
        c.save(url, re.sub(r"\s*\(pdf, [^)]*\).*$", "", title), "2023", date_from_pdf=False)
    c.done(ok)


# --------------------------------------------------------------------------- Aargau

AG_NAT = "https://www.ag.ch/de/themen/migration-integration/einbuergerung/ordentliche-einbuergerung"
AG_MIKA = "https://www.ag.ch/de/themen/migration-integration/merkblaetter-formulare/merkblaetter/erwerbstaetigkeit"


def ag():
    """Abteilung Register und Personenstand: the electronic handbook for the ordinary naturalisation
    procedure with its annexes. Amt fuer Migration und Integration (MIKA): of its numbered Merkblaetter
    only the 'Bewilligungspraxis' paper is officer guidance; the rest are applicant/employer leaflets
    and the circulars to communes sit in a login-only extranet."""
    c = Canton("ag", "Aargau")
    markup, base = page(AG_NAT)
    ok = bool(markup)
    for url, title in links(markup, base, r"/handbuch-ordentliche-einbuergerungen/[^/]+\.pdf$"):
        title = re.sub(r"\s*\(PDF, [^)]*\)\s*$", "", title)
        c.save(url, title if title.startswith("Elektron") else f"Handbuch ordentliche Einbürgerung, {title}")
    markup, base = page(AG_MIKA)
    ok = ok and bool(markup)
    for url, title in links(markup, base, r"bewilligungspraxis[^/]*\.pdf$"):
        c.save(url, re.sub(r"\s*\(PDF, [^)]*\)\s*$", "", title))
    c.done(ok)


# --------------------------------------------------------------------------- Graubuenden

GR_PAGE = "https://www.gr.ch/DE/institutionen/verwaltung/djsg/afm/dokumente/asyl/Seiten/default.aspx"
GR_WANT = r"HFK_Richtlinien|Weisungen und Handlungsrichtlinien|Wegleitung Arbeitseins"


def gr():
    """Amt fuer Migration und Zivilrecht: guidelines of the hardship commission, directives on support
    of persons in the asylum sector, guide on work assignments. Everything else on the document pages
    is forms and information sheets; the 'Weisungen' page only links to the SEM."""
    c = Canton("gr", "Graubünden")
    markup, base = page(GR_PAGE)
    for url, title in links(markup, base, r"\.pdf$"):
        if re.search(GR_WANT, urllib.parse.unquote(url)):
            m = re.search(r"/(\d\d)_(\d\d)(\d\d)_", url)
            c.save(url, title, f"20{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "")
    c.done(bool(markup))


# --------------------------------------------------------------------------- Geneve

GE_DOCS = [   # OCPM publishes no directives; these two "syntheses" state the practice it applies (publication date)
    ("https://www.ge.ch/document/criteres-integration-requis-au-sens-art-58a-lei-octroi-ordinaire-anticipe-permis-c", "2026-01-19"),
    ("https://www.ge.ch/document/modes-preuve-annees-sejour-0", "2025-11-03"),
]


def ge():
    c = Canton("ge", "Genève")
    ok = True
    for landing, published in GE_DOCS:
        markup, base = page(landing)
        hit = next(iter(links(markup, base, r"/document/\d+/telecharger$")), None)
        if not markup:
            ok = False
            continue
        t = re.search(r"<h1[^>]*>(.*?)</h1>", markup, flags=re.S)
        d = re.search(r'<time datetime="(\d{4}-\d\d-\d\d)', markup)
        title, date = (f"OCPM: {clean(t.group(1))}" if t else landing), (d.group(1) if d else published)
        if hit:
            c.save(hit[0], title, "" if PDFTOTEXT else date, ext=".pdf", source_url=landing)   # Stand is in the PDF
        else:                                 # the text is the web page itself
            c.save(landing, title, date, ext=".html")
    c.done(ok)


# --------------------------------------------------------------------------- Fribourg

FR_PAGES = [("https://www.fr.ch/vie-quotidienne/permis-de-sejour-et-naturalisation/la-naturalisation", r"Guide pratique"),
            ("https://www.fr.ch/de/alltag/aufenthaltsbewilligungen-und-einbuergerung/die-einbuergerung", r"Praxisleitfaden")]


def fr():
    """Naturalisation service: practical guide on ordinary naturalisation for the communes (French and
    German). The migration office (SPoMi) publishes no directives."""
    c = Canton("fr", "Fribourg")
    ok = True
    for landing, want in FR_PAGES:
        markup, base = page(landing)
        hits = [(urllib.parse.urljoin(base, html.unescape(m.group(1))), html.unescape(m.group(2)))
                for m in re.finditer(r'<a href="([^"]*/document/\d+)"[^>]*title="([^"]*)"', markup)
                if re.search(want, html.unescape(m.group(2)))]
        ok = ok and bool(hits)
        for url, title in hits[:1]:
            c.save(url, f"Naturalisation ordinaire / Ordentliche Einbürgerung: {title}", ext=".pdf", source_url=url)
    c.done(ok)


# --------------------------------------------------------------------------- Bern

BE_PAGE = "https://www.migration.sid.be.ch/de/start/gemeinde-informationen/weisungen.html"
BE_NAT = "https://www.einbuergerung.sid.be.ch/content/dam/einbuergerung_sid/dokumente/de/bsig-einbuergerungsverfahren-de.pdf"
BE_NAT_PAGE = "https://www.einbuergerung.sid.be.ch/de/start/einbuergerung/rechtliche-grundlagen.html"


def be():
    """Amt fuer Bevoelkerungsdienste: the BSIG directives (Bernische Systematische Information
    Gemeinden) on the migration pages, and the BSIG 'Wegleitung Einbuergerungsverfahren'.
    robots.txt of the be.ch hosts asks for 10 s between requests. Further material for the communes
    is on login-only platforms; the BSIG database itself (ktbe.jaxforms.com) is not read."""
    c = Canton("be", "Bern")
    markup, base = page(BE_PAGE)
    for url, title in links(markup, base, r"/dokumente/de/bsig/[^/]+\.pdf$"):
        c.save(url, f"BSIG-Weisung: {title}" if "BSIG" not in title else title, date_in_title=False)
    c.save(BE_NAT, "Wegleitung Einbürgerungsverfahren (BSIG Nr. 1/121.1/1.2)", source_url=BE_NAT_PAGE)
    c.done(bool(markup))


# --------------------------------------------------------------------------- Obwalden

OW_DOCS = [   # publication id on www.ow.ch/publikationen, date in that list; notes of the Amt fuer Justiz to the communes
    (1443, "2013-01-01", "Einbürgerung: Checkliste für Gemeinden (altes Recht)"),
    (1686, "2007-08-31", "Einbürgerung: Wohnsitzdauer vor Gesuchseinreichung (altes Recht)"),
    (3050, "2010", "Einbürgerung: Wohnsitzwechsel innerhalb des Kantons OW (altes Recht)"),
    (6540, "2013", "Diagramm Verfahrensablauf ordentliche Einbürgerung (altes Recht)"),
    (7879, "2015", "Gleichstellung der eingetragenen Partnerschaft und der Ehe im Einbürgerungsverfahren")]


def ow():
    c = Canton("ow", "Obwalden")
    ok = True
    for pid, date, title in OW_DOCS:
        landing = f"https://www.ow.ch/_rte/publikation/{pid}"
        markup, base = page(landing)
        hit = next(iter(links(markup, base, r"/_doc/\d+$")), None)
        if not hit:
            ok = False
            continue
        c.save(hit[0], title, date, ext=".pdf", source_url=landing)
    c.done(ok)


# --------------------------------------------------------------------------- via the Wayback Machine

WAYBACK = "https://web.archive.org/web/2id_/"   # "2" = closest capture to the year 2xxx start; id_ = original bytes


def archived(c, original, title, date="", **kw):
    """Save the Wayback Machine's unmodified copy of a file whose own site may not be read by script."""
    return c.save(WAYBACK + original, title, date, source_url=WAYBACK + original, **kw)


# --------------------------------------------------------------------------- Vaud

VD_BASE = "https://www.vd.ch/uploads/tx_vdfilesdbsecri/"
VD_DOCS = [   # (file name in the "courriers aux communes" database, title, date)
    ("spop_110324.pdf", "Circulaire 11/02 aux Contrôles des habitants: Mise en œuvre de l'initiative Neirynck - admission des étrangers diplômés d'une haute école suisse", "2011-03-24"),
    ("14-02_Visas_de_retour-nouveaux_tarifs.pdf", "Circulaire 14/02 aux Contrôles des habitants: Visa de retour pour les ressortissants des Etats tiers en attente d'un titre de séjour", "2014-02-10"),
    ("14-04_Octroi_automatique_du_permis_C_et_Procédure_commune__B_en_C.pdf", "Circulaire 14/04 aux Contrôles des habitants: Examen systématique de l'octroi du permis C et procédure commune B en C", "2014-05-02"),
    ("Directive_Fiche_pratique_NAT-1801_Le_test_de_connaissances.pdf", "Directive - fiche pratique NAT-1801: Naturalisation ordinaire, le test de connaissances élémentaires", "2018-06-18"),
    ("NAT-1803_Le_rapport_d_enquête.pdf", "Directive - fiche pratique NAT-1803: Naturalisation ordinaire, le rapport d'enquête", "2018-07-25"),
    ("Rapport_d_enquête_exemple_commune.pdf", "Rapport d'enquête relatif aux demandes de naturalisation ordinaire (modèle pour les communes, annexe à NAT-1803)", "2018-07-20"),
    ("19-02_Mise_en_oeuvre_nouvelle_LEI__Version_complète_.pdf", "Directive 19/02 aux Contrôles des habitants: Mise en œuvre de la LEI", "2019-02-14"),
]


def vd():
    """Service de la population (SPOP): numbered directives and circulars to the communal residents'
    offices, and the naturalisation 'directives / fiches pratiques'. They sit in the canton's database
    of letters to the communes, whose listing robots.txt closes to scripts (Disallow: /*&cHash=*) and
    whose old file addresses are dead; the copies below are the ones the Wayback Machine holds."""
    c = Canton("vd", "Vaud")
    for name, title, date in VD_DOCS:
        archived(c, VD_BASE + name, f"SPOP Vaud, {title or name[:-4].replace('_', ' ')}", date)
    c.done()


# --------------------------------------------------------------------------- Glarus, Ticino (archive copies only)

def gl():
    """gl.ch shuts out Claude/Anthropic agents by name in robots.txt, so only an archive copy is tried."""
    c = Canton("gl", "Glarus")
    archived(c, "https://www.gl.ch/public/upload/assets/44606/Richtlinien%20Erteilung%20der%20Niederlassungsbewilligung.pdf?fp=1",
             "Abteilung Migration: Richtlinien / Praxis Erteilung der Niederlassungsbewilligung", "2022-09", ext=".pdf")
    c.done()


def ti():
    """The ti.ch hosts answer scripts with a bot check, so only an archive copy is tried."""
    c = Canton("ti", "Ticino")
    archived(c, "https://www4.ti.ch/fileadmin/CAN/SGCDS/ICPD/PDF/DIRITTO_TI/13luglio2009.pdf",
             "Direttive per l'ottenimento dell'attinenza comunale, della cittadinanza ticinese e della cittadinanza "
             "svizzera da parte di cittadini stranieri (Sezione degli enti locali)", "2009-05", ext=".pdf")
    c.done()


CANTONS = {"zh": zh, "be": be, "so": so, "ag": ag, "gr": gr, "ow": ow, "fr": fr, "ge": ge, "vd": vd, "gl": gl, "ti": ti}


def write_index():
    """Rewrite index.tsv: fresh rows for the cantons listed in this run; old rows are kept for the
    other cantons, and for files this run did not list again only if the canton's listing failed."""
    index = ROOT / "index.tsv"
    new = {r[0]: tuple(c.replace("\t", " ").replace("\n", " ") for c in r) for r in ROWS}
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) == 5 and cols[0] not in new and (ROOT / cols[0]).is_file() \
                    and cols[0].split("/")[0] not in LISTED:
                new[cols[0]] = tuple(cols)
    rows = [new[k] for k in sorted(new)]
    with index.open("w", encoding="utf-8") as f:
        f.write("file\tcanton\ttitle\tdate\tsource_url\n")
        for r in rows:
            f.write("\t".join(r) + "\n")
    print(f"index.tsv: {len(rows)} rows")


def main():
    wanted = [w.lower() for w in sys.argv[1:]] or list(CANTONS)
    unknown = [w for w in wanted if w not in CANTONS]
    if unknown:
        sys.exit(f"unknown canton(s): {', '.join(unknown)}; choose from {', '.join(CANTONS)}")
    ROOT.mkdir(parents=True, exist_ok=True)
    if MANIFEST_FILE.exists():
        MANIFEST.update(json.loads(MANIFEST_FILE.read_text(encoding="utf-8")))
    for w in wanted:
        print(f"== {w}")
        CANTONS[w]()
    write_index()
    print(f"downloaded {STATS['new']} new files, {STATS['bytes'] / 1e6:.1f} MB")
    for canton, title, url, why in MISSED:
        print(f"not obtained: {canton}\t{title}\t{url}\t{why}")
    for host, why in BLOCKED.items():
        print(f"blocked: {host} ({why})")


if __name__ == "__main__":
    main()

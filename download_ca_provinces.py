#!/usr/bin/env python3
"""Download the guidance that Canadian provinces and territories publish for, or apply in, deciding
their immigration selection cases: Quebec's officers' manual (Guide des procedures d'immigration,
its update notes and management directives, current and archived versions) and, elsewhere, the
programme guides, policies and procedure manuals of the provincial nominee programmes.

    ./download_ca_provinces.py            every province that has a usable source
    ./download_ca_provinces.py qc bc      only the named provinces (two-letter codes)

Files go to ca/provinces/<code>/, unmodified, named <date>_<name>.<ext> where a date is known.
ca/provinces/index.tsv (file, province, title, date, source_url, kind, title_en) and
ca/provinces/not-obtained.tsv are rewritten on every run from ca/provinces/.manifest.json, which
remembers which URL became which file; rows of provinces that were not run are kept.
What each province publishes is described in ca/provinces/NOTES.txt, which this script does not touch.

Rules the script keeps:
  * robots.txt of every host is read first and obeyed, for the generic user agent and for any group
    that names an AI agent (including Crawl-delay); a disallowed URL is reported and not fetched;
  * one request at a time, at least PAUSE seconds between requests to the same host;
  * HTTP 403/429 or a bot-check page stops the use of that host for the rest of the run, as do
    three dropped connections in a row; the Wayback Machine is given up after three failures in a row;
  * files already present are not fetched again, so the script is safe to re-run (to refresh a
    document whose URL is stable, delete the file and run again);
  * only the Python standard library is used.  If `pdftotext` / `pdfinfo` (poppler) are installed
    they are used to read dates and titles from new PDFs and to check them.

Provinces whose sites refuse scripts (robots.txt answered 403, a bot check, or robots.txt shuts out
AI agents by name) are not fetched at all; what is known to exist there is listed in STATIC_MISSED
and ends up in not-obtained.tsv.
"""
import base64
import hashlib
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

ROOT = Path(__file__).resolve().parent / "ca" / "provinces"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 1.5                                   # seconds between requests to one host
SLOW = {"web.archive.org": 5.0}
MAX_FILES, MAX_BYTES = 1500, 500_000_000

NAMES = {"qc": "Quebec", "on": "Ontario", "bc": "British Columbia", "ab": "Alberta", "sk": "Saskatchewan",
         "mb": "Manitoba", "ns": "Nova Scotia", "nb": "New Brunswick", "pe": "Prince Edward Island",
         "nl": "Newfoundland and Labrador", "yt": "Yukon", "nt": "Northwest Territories", "nu": "Nunavut"}

AI_AGENT = re.compile(r"claude|anthropic|gptbot|chatgpt|oai-|ccbot|perplexity|google-extended|bytespider|cohere|"
                      r"ai2bot|diffbot|amazonbot|applebot-extended|meta-external|omgili", re.I)


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only if robots.txt of the target allows it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise urllib.error.URLError(f"redirect target not allowed by robots.txt: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(CheckedRedirect())
OPENER.addheaders = [("User-Agent", UA), ("Accept-Language", "en,fr;q=0.8")]
BLOCKED = {}                                  # host -> reason
RESETS = {}                                   # host -> consecutive failures
ROBOTS = {}                                   # host -> Robots (None: could not be read)
LAST = {}                                     # host -> time of last request
MANIFEST_FILE = ROOT / ".manifest.json"
MANIFEST = {"files": {}, "missed": {}}        # files: key -> row dict; missed: code -> [[title, date, url, reason]]
STATS = {"new": 0, "bytes": 0}
PDFTOTEXT = shutil.which("pdftotext")
PDFINFO = shutil.which("pdfinfo")


def quote(url):
    """Percent-encode non-ASCII characters and spaces without touching existing escapes."""
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")


def _open(url, host):
    wait = max(SLOW.get(host, PAUSE), getattr(ROBOTS.get(host), "delay", 0) or 0) - (time.time() - LAST.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        with OPENER.open(urllib.request.Request(quote(url)), timeout=180) as r:
            body = r.read()
            total = r.headers.get("Content-Length")
            if total and int(total) > len(body):
                raise OSError(f"short read {len(body)}/{total}")
            return body, r.geturl()
    finally:
        LAST[host] = time.time()


class Robots:
    """robots.txt rules for the generic user agent and for groups naming AI agents, with the * and $
    wildcards that urllib.robotparser ignores. The longest matching rule wins; Allow wins a tie."""

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
        mine = [r for ag, rs in groups if any(a == "*" or AI_AGENT.search(a) for a in ag) for r in rs]
        self.rules, self.delay = [], 0.0
        for key, value in mine:
            if key == "crawl-delay":
                try:
                    self.delay = max(self.delay, float(value))
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


BOTCHECK = re.compile(r"captcha|TSPD|enable JavaScript|cf-challenge|Access Denied|unusual traffic|Radware|"
                      r"Verifying your browser|securitypage|Just a moment", re.I)


def is_botcheck(body):
    head = body[:6000].decode("utf-8", "replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", head, flags=re.S | re.I)
    return bool(title and re.search(r"Radware|Just a moment|Access Denied|Attention Required|Probl[èe]me technique|"
                                    r"Request Rejected|Captcha", title.group(1), re.I))


def allowed(url):
    """Read the host's robots.txt once; True if the URL may be fetched."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host not in ROBOTS:
        rp = None
        try:
            body, _ = _open(f"{parts.scheme}://{host}/robots.txt", host)
            text = body.decode("utf-8", "replace")
            if "<html" in text[:3000].lower() and (BOTCHECK.search(text) or is_botcheck(body)):
                BLOCKED[host] = "bot check instead of robots.txt"
                print(f"  BLOCKED {host}: bot-check page served - host not used")
            else:                             # an ordinary HTML page here means: no robots.txt
                rp = Robots("" if "<html" in text[:3000].lower() else text)
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


def get(url):
    """Return (bytes, final_url) or (None, reason). Never retries a refusal; no retry at all for the
    Wayback Machine, one retry elsewhere for a dropped connection."""
    host = urllib.parse.urlsplit(url).netloc
    if host in BLOCKED:
        return None, f"host blocked ({BLOCKED[host]})"
    if not allowed(url):
        why = BLOCKED.get(host) or ("robots.txt unreadable" if ROBOTS.get(host) is None else "disallowed by robots.txt")
        print(f"  NOT FETCHED ({why}): {url}")
        return None, why
    archive = host == "web.archive.org"
    err = None
    for attempt in range(1 if archive else 2):
        try:
            body, final = _open(url, host)
            if body[:1] == b"<" and is_botcheck(body):
                BLOCKED[host] = "bot-check page"
                print(f"  BLOCKED {host}: bot-check page - skipping this host for the rest of the run")
                return None, "bot-check page"
            RESETS[host] = 0
            return body, final
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code in (403, 429):
                BLOCKED[host] = err
                print(f"  BLOCKED {host}: {err} - skipping this host for the rest of the run")
                return None, err
            if e.code in (404, 410):
                if archive:
                    RESETS[host] = 0
                break
        except Exception as e:                # noqa: BLE001
            err = str(e)
        if archive or "refused" in err or "reset" in err:
            RESETS[host] = RESETS.get(host, 0) + 1
            if RESETS[host] >= 3:
                BLOCKED[host] = "three failures in a row"
                print(f"  BLOCKED {host}: three failures in a row ({err}) - skipping it for the rest of the run")
                return None, err
        if not archive and attempt == 0:
            time.sleep(15)
    print(f"  FAILED {url}: {err}")
    return None, err


def page(url):
    body, final = get(url)
    if body is None:
        return "", url
    return body.decode("utf-8", "replace"), final


def clean(markup):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup or "")).replace("\xad", "").replace("\xa0", " ").split())


_TRANSLIT = str.maketrans({"é": "e", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a", "ç": "c", "î": "i", "ï": "i",
                           "ô": "o", "ù": "u", "û": "u", "œ": "oe", "É": "E", "È": "E", "Ê": "E", "À": "A", "Ç": "C",
                           "Œ": "OE", "’": "", "'": "", "–": "-", "—": "-"})


def slug(s, n=100):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s.translate(_TRANSLIT)).strip("-.")[:n].strip("-.") or "x"


MONTHS = {}
for _names in ("january february march april may june july august september october november december",
               "janvier février mars avril mai juin juillet août septembre octobre novembre décembre"):
    for _i, _m in enumerate(_names.split()):
        MONTHS[_m] = _i + 1
MONTHS.update({"fevrier": 2, "aout": 8, "decembre": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
               "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12, "novmbre": 11})
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_RES = [
    (re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])\s?(?:er|st|nd|rd|th)?\s+(" + _MONTH_RE + r")\.?,?\s+((?:19|20)\d\d)", re.I),
     lambda m: (m.group(3), MONTHS[m.group(2).lower()], m.group(1))),
    (re.compile(r"\b(" + _MONTH_RE + r")\.?\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?,?\s+((?:19|20)\d\d)", re.I),
     lambda m: (m.group(3), MONTHS[m.group(1).lower()], m.group(2))),
    (re.compile(r"(?<!\d)((?:19|20)\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)"),
     lambda m: (m.group(1), m.group(2), m.group(3))),
]
_MONTH_YEAR = re.compile(r"\b(" + _MONTH_RE + r")\.?,?\s+((?:19|20)\d\d)\b", re.I)


def find_date(text, month_ok=False):
    """First date in text as YYYY-MM-DD ('' if none). With month_ok, 'October 2026' gives 2026-10."""
    best = None
    for rx, conv in _DATE_RES:
        m = rx.search(text or "")
        if m and (best is None or m.start() < best[0]):
            y, mo, d = conv(m)
            best = (m.start(), f"{y}-{int(mo):02d}-{int(d):02d}")
    if month_ok:
        m = _MONTH_YEAR.search(text or "")
        if m and (best is None or m.start() < best[0]):
            return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    return best[1] if best else ""


def pdf_text(path, first=1, last=3):
    if not PDFTOTEXT:
        return ""
    try:
        return subprocess.run([PDFTOTEXT, "-f", str(first), "-l", str(last), "-layout", str(path), "-"],
                              capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
    except Exception:                         # noqa: BLE001
        return ""


VERSION = re.compile(r"(effective(?: date)?|version|updated?|last updated|revised|as of|mise [àa] jour(?: le| du)?|"
                     r"en vigueur(?: le)?|date de mise en (?:œ|oe)uvre)\s*:?\s*(.{0,45})", re.I)


def pdf_date(path, pages=2):
    """Version date from the first pages of a PDF: a date after a keyword such as 'Effective' or
    'Mise a jour', else the first date on those pages (a month and year is enough)."""
    text = " ".join(pdf_text(path, 1, pages).split())
    for m in VERSION.finditer(text):
        d = find_date(m.group(2), month_ok=True)
        if d:
            return d
    return find_date(text[:1500], month_ok=True)


def digest32(body):
    """SHA-1 in base32: the form in which the Wayback index gives the digest of a capture."""
    return base64.b32encode(hashlib.sha1(body).digest()).decode()


def links(markup, base, pattern=r"\.pdf(\?|$)"):
    """Yield (absolute url, link text) for <a> elements whose href matches pattern, in page order."""
    seen = set()
    for m in re.finditer(r'<a\b[^>]*?href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', markup, flags=re.S | re.I):
        href = urllib.parse.urljoin(base, html.unescape(m.group(1)).strip())
        if href in seen or not re.search(pattern, href, flags=re.I):
            continue
        seen.add(href)
        yield href, clean(m.group(2))


def save_manifest():
    ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(MANIFEST, indent=0, ensure_ascii=False, sort_keys=True), encoding="utf-8")


class Province:
    def __init__(self, code):
        self.code, self.name = code, NAMES[code]
        self.count = 0
        self.missed = []                      # [title, date, url, reason]
        self.ok = True

    def miss(self, title, url, reason, date=""):
        self.missed.append([title, date, url, reason])

    def have(self, key):
        old = MANIFEST["files"].get(key)
        return bool(old and (ROOT / old["file"]).is_file() and (ROOT / old["file"]).stat().st_size > 0)

    def save(self, url, title, date="", title_en="", sub="", name="", ext=None, source_url=None, key=None,
             fetch=None, inspect=None, date_pages=2, kind="guidance"):
        """Download url (unless present) and record it. key: manifest key (default: url); fetch: the URL
        actually requested if not url (a Wayback capture); inspect(path) -> dict may refine title,
        title_en, date and name from the downloaded file. Returns the manifest row or None."""
        key = key or url
        if self.have(key):
            self.count += 1
            return MANIFEST["files"][key]
        if STATS["new"] >= MAX_FILES or STATS["bytes"] >= MAX_BYTES:
            print("  limit reached, not downloading more")
            return None
        ext = ext or (re.search(r"\.(pdf|docx?|xlsx)(?=$|\?)", url.lower()) or [".pdf"])[0]
        body, final = get(fetch or url)
        if body is None:
            self.miss(title, source_url or url, final, date)
            return None
        head = body[:2048].lstrip()
        if ext == ".pdf" and head.startswith(b"<") and b"<html" in body[:4000].lower():
            # an HTML page where a PDF was expected: a landing page that links the file
            pdfs = [u for u, _ in links(body.decode("utf-8", "replace"), final, r"\.pdf(\?|$)")]
            self.miss(title, source_url or url, "page instead of a PDF" + (f" (links {pdfs[0]})" if pdfs else ""), date)
            return None
        good = {".pdf": head.startswith(b"%PDF") and b"%%EOF" in body[-4096:], ".html": head.startswith(b"<")
                and not is_botcheck(body) and len(body) > 2000}.get(ext, True)
        if not good:
            print(f"  NOT A VALID {ext} FILE, skipped: {fetch or url}")
            self.miss(title, source_url or url, f"answer is not a valid {ext} file", date)
            return None
        folder = ROOT / self.code / sub
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / ".download.tmp"
        tmp.write_bytes(body)
        if ext == ".pdf" and PDFINFO and subprocess.run([PDFINFO, str(tmp)], capture_output=True).returncode != 0:
            tmp.unlink()
            self.miss(title, source_url or url, "pdfinfo cannot read the file", date)
            return None
        if inspect:
            extra = inspect(tmp) or {}
            title, title_en = extra.get("title", title), extra.get("title_en", title_en)
            date, name = extra.get("date", date), extra.get("name", name)
        title = clean(title) or urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if not date and ext == ".pdf" and date_pages:
            date = pdf_date(tmp, date_pages)
        if not date:                          # upload folder of the file, e.g. /sites/default/files/2026-09/
            m = re.search(r"/(20\d\d)-(0[1-9]|1[0-2])/", final)
            date = f"{m.group(1)}-{m.group(2)}" if m else ""
        base = slug(f"{date}_{name or title}" if date else (name or title))
        rel = "/".join(x for x in (self.code, sub, base + ext) if x)
        i = 2
        while (ROOT / rel).exists():
            rel = "/".join(x for x in (self.code, sub, f"{base}-{i}{ext}") if x)
            i += 1
        tmp.rename(ROOT / rel)
        row = {"file": rel, "province": self.name, "title": title, "date": date, "source_url": source_url or url,
               "kind": kind, "title_en": title_en, "digest": digest32(body)}
        MANIFEST["files"][key] = row
        save_manifest()
        STATS["new"] += 1
        STATS["bytes"] += len(body)
        self.count += 1
        print(f"  + {rel}")
        return row

    def done(self):
        if self.ok or self.missed:
            MANIFEST["missed"][self.code] = self.missed
        save_manifest()
        print(f"  {self.code}: {self.count} files" + ("" if self.ok else " (a listing could not be read)"))


def html_date(markup):
    m = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d\d-\d\d)|property="article:modified_time"\s+content="(\d{4}-\d\d-\d\d)',
                  markup)
    return (m.group(1) or m.group(2)) if m else ""


# --------------------------------------------------------------------------- Quebec

QC_GPI = "https://www.quebec.ca/gouvernement/ministeres-organismes/immigration/publications/guide-procedures-immigration"
QC_NPI = QC_GPI + "/notes-procedures-immigration"
QC_DIR = QC_GPI + "/directives-gestion"
QC_CDN = "https://cdn-contenu.quebec.ca/cdn-contenu/adm/min/immigration/publications-adm/gpi/"
CDX = ("https://web.archive.org/cdx/search/cdx?url={}*&filter=statuscode:200&filter=mimetype:application/pdf"
       "&collapse=digest&fl=timestamp,original,length,digest&limit=30000")
QC_OLD = ("midi.gouv.qc.ca/publications/fr/gpi-npi/", "micc.gouv.qc.ca/publications/fr/gpi-npi/",
          "mifi.gouv.qc.ca/publications/fr/gpi-npi/", "cdn-contenu.quebec.ca/cdn-contenu/adm/min/immigration/publications-adm/gpi/")

QC_SECTIONS = {"Gestion de la demande": "Application management", "Immigration temporaire": "Temporary immigration",
               "Immigration permanente": "Permanent immigration", "Procédures d'immigration": "Immigration procedures"}
QC_CHAPTERS = {
    "SDI": "Immigration application management system based on the expression of interest",
    "PTET": "Temporary Foreign Worker Program", "PEE": "Foreign Student Program",
    "PSTTM": "Temporary Stay for Medical Treatment Program", "PSTQ": "Skilled Worker Selection Program",
    "PRTQ": "Regular Skilled Worker Program", "PEQ": "Québec Experience Program", "PI": "Investor Program",
    "PE": "Entrepreneur Program", "PTA": "Self-Employed Worker Program", "Regroupement_familial": "Family reunification",
    "PPRE": "Program for Refugees Abroad", "Selection_humanitaire": "Program for persons selected on humanitarian grounds",
    "Pouvoirs_derogatoires": "Derogation power", "Reexamen": "Review of a decision",
    "TAQ": "Administrative Tribunal of Québec", "Consultant": "Immigration consultant",
    "Relations_intermediaires": "Relations with intermediaries"}
QC_INDEXATION = "Indexation of the scales (schedules B, C and D of the Québec Immigration Regulation)"
QC_FEES = "Fees payable for processing an immigration application under the Québec Immigration Act"
QC_SUBJECTS = {            # English gloss of the subject of each note / directive listed on the live pages
    "npi 2023-003": "Letter attesting the issue of the Québec acceptance certificate (CAQ) for studies",
    "npi 2023-004": "Temporary exemption from the CAQ for studies for certain holders of a work permit or work authorisation",
    "npi 2022-003": "Mechanism for receiving undertaking applications from groups of 2 to 5 natural persons and from legal "
                    "persons under the Program for Refugees Abroad (collective sponsorship), 2021-2022 period",
    "npi 2022-005": "End of the issue of CAQs for studies carried out entirely online",
    "npi 2022-006": "Change to the requirement to obtain a new CAQ for studies when the foreign student's arrival is postponed",
    "npi 2021-001": "Electronic transmission of files under the Québec Experience Program",
    "npi 2021-002": "Electronic transmission of applications and documents to the Foreign Student Program",
    "npi 2021-005": "Permanent immigration pilot program for workers in food processing (new)",
    "npi 2021-006": "Permanent immigration pilot program for orderlies (new)",
    "npi 2021-007": "Permanent immigration pilot program for workers in artificial intelligence, information technologies "
                    "and visual effects (new)",
    "npi 2020-001": "Attestation of learning about democratic values and Québec values",
    "npi 2020-009": "Implementation of the Special Program for Asylum Seekers during the COVID-19 Period (PSDAPC)",
    "npi 2019-007": "Invitation to apply for permanent selection under the Regular Skilled Worker Program for foreign "
                    "nationals admitted under the Live-in Caregiver Program and eligible to apply for permanent residence",
    "npi 2019-011": "Entry into force of the 2019 List of areas of training, reflecting the updated labour-market needs of Québec",
    "npi 2018-009": "New immigration regulation: renewal and validity of a selection decision under the Québec Immigration Regulation",
    "npi 2018-010": "New immigration regulation: Entrepreneur Program",
    "npi 2018-011": "New immigration regulation: Self-Employed Worker Program",
    "npi 2018-012": "New immigration regulation: Investor Program",
    "dir 2017-001": "Québec Experience Program: no systematic application of the administrative sanction of refusing to "
                    "examine an application for having provided false or misleading information or documents",
    "dir 2013-001": "Renewal until 31 July 2013 of the suspension of receipt of certain selection-certificate applications "
                    "in the economic immigration class",
    "dir 2012-002": "Receipt of applications in the economic immigration class",
    "dir 2012-001": "Sanctions against Iran (economic immigration)",
    "dir 2011-003": "'Renewal' of a lapsed Québec selection certificate (economic immigration)",
    "dir 2011-002": "Rules on managing access for verifying the French and English language test results of skilled worker candidates",
    "dir 2011-001": "Processing of applications in the investor sub-class following the agreement between the immigration "
                    "ministry and Investissement Québec",
    "dir 2010-002": "New procedures for applying the international component of the online placement program (PELI)",
    "dir 2010-001": "Transitional provisions on the regulatory changes of 1 December 2010 in the investor sub-class",
    "dir 2009-002": "Transitional provisions on the regulatory changes of 14 October 2009 concerning skilled worker candidates",
    "dir 2009-001": "Transitional provisions on the regulatory changes of 14 October 2009 concerning business candidates",
    "dir 2007-001": "Operational arrangements for files of skilled worker candidates affected by the regulatory amendments of "
                    "16 October 2006, the updated lists of occupations in demand and of preferred training, and the transitional measures",
    "dir 2004-002": "Request for missing documents: independent business candidates",
    "dir 2004-001": "Children under guardianship from Morocco or Algeria (kafala)",
    "dir 2003-003": "Pilot project for learning French abroad: extension of directive 2003-002 to the Hong Kong immigration office",
    "dir 2003-002": "Pilot project for learning French abroad",
    "dir 2003-001": "Cancellation of CAQs for studies issued to persons enrolled in programmes or courses of six months or less",
    "dir 2002-005": "Opening of IVM files",
    "dir 2002-004": "Systematic attachment of the assessment sheet in the event of refusal or intended refusal",
    "dir 2002-003": "Transitional measures on processing undertaking applications: family reunification class",
    "dir 2002-002": "Transitional measures on the amendments to the regulation on the selection of foreign nationals and "
                    "the weighting regulation; changes to the occupation lists",
    "dir 2002-001": "Directive on processing selection-certificate applications submitted by foreign student candidates",
}
QC_COMPONENTS = {"1": ("Regroupement familial", "Family reunification"),
                 "2": ("Immigration humanitaire", "Humanitarian immigration"),
                 "3": ("Programme de recrutement et de sélection des candidats à l'immigration économique",
                       "Recruitment and selection of economic immigration candidates"),
                 "4": ("Séjour temporaire", "Temporary stay"),
                 "5": ("Manuel de référence", "Reference manual")}


def qc_number(text):
    m = re.search(r"((?:19|20)\d\d)[-_ ]?(\d{3})([a-z]?)", text, re.I)
    return f"{m.group(1)}-{m.group(2)}{m.group(3).lower()}" if m else ""


def qc_listing(c, url):
    """(pdf url, number, subject, date) of the notes or directives listed on a quebec.ca page."""
    markup, _ = page(url)
    if not markup:
        c.ok = False
    found = {}
    for m in re.finditer(r'<a href="(' + re.escape(QC_CDN) + r'[^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a href="' + re.escape(QC_CDN)
                         + r'|</div>)', markup, flags=re.S):
        href, number = html.unescape(m.group(1)), qc_number(clean(m.group(2)))
        rest = clean(m.group(3))
        subject = re.sub(r"\\r\\n.*", "", re.sub(r"^Objet\s*:\s*", "", re.split(r"Mise en (?:œ|oe)uvre", rest)[0])).strip(" .")
        when = find_date(rest.split("uvre", 1)[-1].replace(" er ", " "), month_ok=True) if "uvre" in rest else ""
        # one file is linked twice under two numbers: keep the number that the file name carries
        if href not in found or qc_number(href.rsplit("/", 1)[-1]) == number:
            found[href] = (number, subject, when)
    return [(u, *v) for u, v in found.items()]


def qc_subject_en(kind, number, subject):
    if subject.startswith("Indexation des barèmes"):
        return QC_INDEXATION
    if subject.startswith("Droits exigibles"):
        return QC_FEES
    return QC_SUBJECTS.get(f"{kind} {number}", "")


def qc_npi_inspect(number):
    """Subject and implementation date of an archived note, read from its first page."""
    def inspect(path):
        text = pdf_text(path, 1, 1)
        flat = " ".join(text.split())
        out = {}
        m = re.search(r"OBJET\s*:\s*(.+?)\s*(?:DATE DE MISE EN|R[ÉE]F[ÉE]RENCES? GPI|[ÉE]CH[ÉE]ANCE)", flat)
        if m and len(m.group(1)) < 500:
            subject = m.group(1).strip(" .")
            if subject.isupper():
                subject = subject[0] + subject[1:].lower()
            out["title"] = f"Note sur les procédures d'immigration {number} : {subject}"
        m = re.search(r"DATE DE MISE EN\s*(?:Œ|OE)UVRE\s*:\s*(.{0,60})", flat, flags=re.I)
        d = find_date(m.group(1).replace("1er", "1 "), month_ok=True) if m else ""
        if d:
            out["date"] = d
        return out
    return inspect


def qc_gpi_date(path):
    """Version of a current GPI section: a dated keyword on page 1, else the page footer
    'Guide des procedures d'immigration - <mois> <annee>' of the first pages, as YYYY-MM."""
    d = pdf_date(path, 1)
    if not d:
        m = re.search(r"Guide des proc[ée]dures d.immigration\s*[–-]\s*(" + _MONTH_RE + r")\s+((?:19|20)\d\d)",
                      pdf_text(path, 1, 4), flags=re.I)
        d = f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}" if m else ""
    return {"date": d} if d else {}


def qc_updates(path):
    """Latest 'Mise a jour <mois> <annee>' footer of an old GPI chapter, as YYYY-MM."""
    text = pdf_text(path, 1, 400)
    dates = [f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
             for m in re.finditer(r"Mise [àa] jour\s+(" + _MONTH_RE + r")\s+((?:19|20)\d\d)", text, flags=re.I)]
    return max(dates) if dates else ""


def qc():
    """Ministere de l'Immigration, de la Francisation et de l'Integration: the Guide des procedures
    d'immigration (all sections on the live page), the Notes sur les procedures d'immigration and the
    Directives de gestion; then, from the Wayback Machine, earlier versions of the sections, the
    chapters of the pre-2018 guide (composantes 1-5) and the notes that are no longer listed."""
    c = Province("qc")
    markup, base = page(QC_GPI)
    if not markup:
        c.ok = False
    chapters = {}                             # file name -> (title, title_en)
    for block in re.split(r"<h2", markup)[1:]:
        section = clean(re.match(r"[^>]*>(.*?)</h2>", block, flags=re.S).group(1)) if re.match(r"[^>]*>(.*?)</h2>", block, flags=re.S) else ""
        if section not in QC_SECTIONS:
            continue
        for url, text in links(block.split("</div></div></div>")[0], base, re.escape(QC_CDN)):
            text = re.sub(r"\s*\(PDF.*$", "", text)
            fname = url.rsplit("/", 1)[-1].split("?")[0]
            stem = re.sub(r"^(?:\d+_)?GPI_ch\d+_sect[-_\d]*", "", fname.rsplit(".", 1)[0])
            en = QC_CHAPTERS.get(stem, "")
            title = f"Guide des procédures d'immigration – {section} : {text}"
            title_en = f"Immigration Procedures Guide – {QC_SECTIONS[section]}: {en}" if en else \
                f"Immigration Procedures Guide – {QC_SECTIONS[section]} (section: {text})"
            chapters[fname.lower()] = (title, title_en)
            c.save(url, title, title_en=title_en, sub="gpi", name=fname.rsplit(".", 1)[0], source_url=url, date_pages=1,
                   inspect=qc_gpi_date)
    live_numbers = {"npi": set(), "dir": set()}
    for kind, url, sub, fr, en in (("npi", QC_NPI, "npi", "Note sur les procédures d'immigration", "Immigration procedures note"),
                                   ("dir", QC_DIR, "directives-gestion", "Directive de gestion", "Management directive")):
        for href, number, subject, when in qc_listing(c, url):
            live_numbers[kind].add(number)
            live_numbers[kind].add(qc_number(href.rsplit("/", 1)[-1]))
            subject_en = qc_subject_en(kind, number, subject)
            c.save(href, f"{fr} {number} : {subject}", date=when, sub=sub, name=f"{'NPI' if kind == 'npi' else 'dirges'}_{number}",
                   title_en=f"{en} {number}: {subject_en}" if subject_en else f"{en} {number}", source_url=href)
    qc_archive(c, chapters, live_numbers)
    c.done()


def qc_archive(c, chapters, live_numbers):
    held = {row.get("digest") for row in MANIFEST["files"].values()}
    captures, seen = [], set()
    for prefix in QC_OLD:
        text, _ = page(CDX.format(prefix))
        if not text.strip():
            c.miss(f"Archived copies under {prefix} (Wayback Machine capture list could not be read; not enumerated)",
                   "https://web.archive.org/web/*/" + prefix + "*", "Wayback Machine capture index not reachable in this run")
            if "web.archive.org" in BLOCKED:
                c.ok = False
                c.miss("Earlier versions of the Guide des procédures d'immigration and older notes (Wayback Machine)",
                       "https://web.archive.org/web/*/" + prefix + "*", "Wayback Machine not reachable in this run")
                return
            continue
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[3] not in seen:
                seen.add(parts[3])
                captures.append(parts)
    captures.sort(key=lambda p: (p[1].lower().split("/gpi", 1)[-1], p[0]))
    for stamp, original, _length, digest in captures:
        path = urllib.parse.urlsplit(original).path
        fname = urllib.parse.unquote(path.rsplit("/", 1)[-1])
        low = path.lower()
        when = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        wb = f"https://web.archive.org/web/{stamp}id_/{original}"
        shown = f"https://web.archive.org/web/{stamp}/{original}"
        key = "wayback:" + digest
        if digest in held and not c.have(key):
            continue                          # identical to a file already held (live copy or other host)
        m = re.search(r"/composantes?_(\d)/gpi[-_](\d)[-_](\d+)(.*)\.pdf$", low)
        if m:
            comp, chap, rest = m.group(1), m.group(3), m.group(4).strip("-_")
            fr, en = QC_COMPONENTS.get(comp, ("", ""))
            what = f", {rest.replace('_', ' ')}" if rest else ""
            title = (f"Guide des procédures d'immigration (version antérieure à 2018) – Composante {comp} : {fr}, "
                     f"chapitre {chap}{what} [copie archivée le {when}]")
            title_en = (f"Immigration Procedures Guide (pre-2018 edition) – Component {comp}: {en}, chapter {chap}{what} "
                        f"[copy archived on {when}]")

            def inspect(path_, title=title, title_en=title_en):
                d = qc_updates(path_)
                return {"date": d or when[:7]}
            c.save(original, title, title_en=title_en, sub="archive/gpi-composantes", key=key, fetch=wb, source_url=shown,
                   name=f"GPI-{comp}-{chap}{('-' + rest) if rest else ''}_wb{stamp[:8]}", inspect=inspect, date_pages=0)
            continue
        m = re.search(r"/npi[_/]((?:19|20)\d\d)/", low)
        if m:
            number = qc_number(fname)
            if not number or number in live_numbers["npi"]:
                continue
            c.save(original, f"Note sur les procédures d'immigration {number} [copie archivée le {when}]",
                   title_en=f"Immigration procedures note {number} (no longer listed; copy archived on {when})",
                   sub="archive/npi", key=key, fetch=wb, source_url=shown, name=f"NPI_{number}_wb{stamp[:8]}",
                   inspect=qc_npi_inspect(number), date_pages=1)
            continue
        if re.search(r"/dir(?:ectives)?[-_]gestion", low):
            number = qc_number(fname)
            if number and number not in live_numbers["dir"]:
                c.save(original, f"Directive de gestion {number} [copie archivée le {when}]",
                       title_en=f"Management directive {number} (no longer listed; copy archived on {when})",
                       sub="archive/directives-gestion", key=key, fetch=wb, source_url=shown,
                       name=f"dirges_{number}_wb{stamp[:8]}", date_pages=1)
            continue
        if re.search(r"/gpi/[^/]+\.pdf$", low):
            title, title_en = chapters.get(fname.lower(), (f"Guide des procédures d'immigration – {fname}",
                                                            f"Immigration Procedures Guide – {fname}"))
            c.save(original, f"{title} [version antérieure, copie archivée le {when}]",
                   title_en=f"{title_en} [earlier version, copy archived on {when}]", sub="archive/gpi", key=key, fetch=wb,
                   source_url=shown, name=f"{fname.rsplit('.', 1)[0]}_wb{stamp[:8]}", date_pages=1)
    if "web.archive.org" in BLOCKED:
        c.ok = False


# --------------------------------------------------------------------------- British Columbia

BC_DOCS = "https://www.welcomebc.ca/immigrate-to-b-c/about-the-bc-provincial-nominee-program/documents"
BC_ARCHIVE = "https://www.welcomebc.ca/immigrate-to-b-c/about-the-bc-provincial-nominee-program/archives"
BC_WANTED = re.compile(r"Program Guide|Post-Arrival Guide|Post-Nomination Guide", re.I)
BC_UNLISTED = [   # older editions that the archive page no longer lists (found by web search)
    ("https://www.welcomebc.ca/immigrate-to-b-c/bc-pnp-si-program-guide_aug28-2017-pdf",
     "Skills Immigration and Express Entry BC Program Guide", "2017-08-28"),
    ("https://www.welcomebc.ca/immigrate-to-b-c/bc-pnp-ei-program-guide_feb-1-2017-pdf",
     "Entrepreneur Immigration Program Guide", "2017-02-01"),
]


def bc():
    """WelcomeBC: the current BC PNP programme guides (Skills Immigration, Entrepreneur Immigration base
    and regional streams) with the post-nomination and post-arrival guides, and every dated earlier
    edition on the archive page. Application (portal) guides, forms, draw lists, news and statistics are
    left out."""
    c = Province("bc")
    archive, abase = page(BC_ARCHIVE)
    docs, dbase = page(BC_DOCS)
    if not archive or not docs:
        c.ok = False
    current = {}                              # title -> date from which the current edition applies
    old = []
    for m in re.finditer(r'<a\b[^>]*?href="([^"]+)"[^>]*>((?:(?!</?a\b).)*?)</a>\s*\(From ([^)]*?)\)', archive, flags=re.S):
        url, title = urllib.parse.urljoin(abase, html.unescape(m.group(1))), clean(m.group(2))
        span = clean(m.group(3))
        if not BC_WANTED.search(title):
            continue
        start = find_date(span)
        if "documents" in url.rsplit("/", 1)[-1]:
            current.setdefault(title.lower(), start)   # first listing (workers) wins over the students' one
        else:
            old.append((url, title, start, span))
    for url, text in links(docs, dbase, r"/immigrate-to-b-c/[^/]*pdf$"):
        title = re.sub(r"\s*\(PDF.*$", "", text)
        if BC_WANTED.search(title):
            c.save(url, f"BC PNP {title} (current edition)", date=current.get(title.lower(), ""), ext=".pdf",
                   name="BC-PNP-" + title)
    for url, title, start, span in old:
        c.save(url, f"BC PNP {title} (in effect {span})", date=start, ext=".pdf", name="BC-PNP-" + title)
    for url, title, start in BC_UNLISTED:
        if not c.have(url):
            n = len(c.missed)
            c.save(url, f"BC PNP {title} (edition of {start}, no longer listed on the archive page)", date=start, ext=".pdf",
                   name="BC-PNP-" + title)
            del c.missed[n:]                  # not listed by the site any more: no entry if it has gone
    c.done()


# --------------------------------------------------------------------------- Alberta

AB_PAGES = [   # (page, pattern of the PDF link, title)
    ("https://www.alberta.ca/aaip-resources", r"expression-of-interest-points-grid",
     "Alberta Advantage Immigration Program: Worker Stream Expression of Interest points grid"),
    ("https://www.alberta.ca/aaip-alberta-opportunity-stream-eligibility", r"alberta-opportunity-stream-criteria",
     "Alberta Advantage Immigration Program: Alberta Opportunity Stream criteria (NOC 2016 version, for applications made before 16 November 2022)"),
    ("https://www.alberta.ca/aaip-rural-entrepreneur-stream-eligibility", r"community-guide",
     "Alberta Advantage Immigration Program: Rural Entrepreneur Stream Community Guide"),
]


def ab():
    """alberta.ca: the AAIP has no programme guide; the criteria are web pages. Taken: the three
    documents that state selection criteria or guide the communities that endorse candidates."""
    c = Province("ab")
    for url, pattern, title in AB_PAGES:
        markup, base = page(url)
        if not markup:
            c.ok = False
            continue
        for href, _ in links(markup, base, pattern + r"[^/]*\.pdf"):
            c.save(href, title)
            break
    c.done()


# --------------------------------------------------------------------------- Manitoba

MB_POLICIES = "https://immigratemanitoba.com/mpnp/policies/"


def mb():
    """immigratemanitoba.com: the 'Policies and Guidelines' pages of the Manitoba Provincial Nominee
    Program (web pages; saved as HTML)."""
    c = Province("mb")
    markup, base = page(MB_POLICIES)
    if not markup:
        c.ok = False
    c.save(MB_POLICIES, "MPNP Policies and Guidelines (overview)", date=html_date(markup), ext=".html",
           name="MPNP-policies-overview")
    for url, text in links(markup, base, r"^https://immigratemanitoba\.com/mpnp/policies/[^/]+/$"):
        sub, _ = page(url) if not c.have(url) else ("", url)
        m = re.search(r"<h1[^>]*>(.*?)</h1>", sub, flags=re.S)
        title = clean(m.group(1)) if m else text
        c.save(url, f"MPNP Policies and Guidelines: {title or text}", date=html_date(sub), ext=".html",
               name="MPNP-policy-" + url.rstrip("/").rsplit("/", 1)[-1])
    c.done()


# --------------------------------------------------------------------------- Nova Scotia

NS_SITE = "https://liveinnovascotia.com/"
NS_PAGES = ["skilled-worker", "nova-scotia-graduate", "express-entry", "entrepreneur", "atlantic-immigration-program",
            "resources"]
NS_TEXT = re.compile(r"^Application Guide|Designation Guide|Endorsement Guide|Major Changes|Required Recruitment|"
                     r"Program Integrity Policy", re.I)
NS_URL = re.compile(r"/POLICY-|/Policy-", re.I)
NS_HTML = [("resources/nominee-program-priorities-nova-scotia", "Nominee Program Priorities in Nova Scotia"),
           ("resources/expression-interest-eoi-validity-period-and-transition-measures",
            "Expression of Interest (EOI) Validity Period and Transition Measures")]


def ns():
    """liveinnovascotia.com: the NSNP stream guides with their change logs, the programme policies
    (integrity, home-based businesses, telework, trucking), the Atlantic Immigration Program employer
    designation and endorsement guides, and the two pages stating selection priorities and EOI rules."""
    c = Province("ns")
    seen = set()
    for name in NS_PAGES:
        markup, base = page(NS_SITE + name)
        if not markup:
            c.ok = False
            continue
        stream = clean((re.search(r"<h1[^>]*>(.*?)</h1>", markup, flags=re.S) or [0, name])[1]) or name
        for url, text in links(markup, base, r"/sites/default/files/.*\.pdf$"):
            if url in seen or not (NS_TEXT.search(text) or NS_URL.search(url)):
                continue
            seen.add(url)
            if NS_URL.search(url):
                title = f"Nova Scotia Nominee Program policy: {text}"
            elif re.search(r"Program Integrity", text, re.I):
                title = "Nova Scotia Nominee Program and Atlantic Immigration Program: Program Integrity Policy"
            elif name == "atlantic-immigration-program":
                title = f"Atlantic Immigration Program (Nova Scotia): {text}"
            else:
                title = f"Nova Scotia Nominee Program, {stream}: {text}"
            c.save(url, title)
    for path, title in NS_HTML:
        url = NS_SITE + path
        markup, _ = page(url) if not c.have(url) else ("", url)
        c.save(url, title, date=find_date(clean(markup)[:6000]), ext=".html", name=path.rsplit("/", 1)[-1])
    c.done()


# --------------------------------------------------------------------------- Newfoundland and Labrador

NL_BASE = "https://www.gov.nl.ca/immigration/"
NL_INDEX = NL_BASE + "program-policies-and-procedures/"
NL_SECTIONS = [("general-policies-2/", "General Policies"), ("job-vacancy-assessment-2/", "Job Vacancy Assessment"),
               ("skilled-workers-category/", "Skilled Worker Category"),
               ("express-entry-skilled-worker-category/", "Express Entry Skilled Worker Category"),
               ("international-graduate-category/", "International Graduate Category"),
               ("in-canada-refugee-claimants/", "In-Canada Refugee Claimants"),
               ("excluded-positions/", "Positions Exempt from Labour Market Testing"),
               ("expression-of-interest-model-prioritization-criteria/", "Expression of Interest Model: Prioritization Criteria")]


def nl():
    """gov.nl.ca, Office of Immigration and Multiculturalism: 'Program Policies and Procedures' of the
    NLPNP, an officers' manual published as web pages (one page per numbered policy; saved as HTML),
    with the PDFs that the policy pages link."""
    c = Province("nl")
    index, base = page(NL_INDEX)
    if not index:
        c.ok = False
        c.done()
        return
    nav = {u.split("#")[0].rstrip("/") for u, _ in links(index, base, r".")}
    c.save(NL_INDEX, "NLPNP Program Policies and Procedures (overview)", date=html_date(index), ext=".html",
           name="NLPNP-policies-overview")
    seen = set()
    for path, section in NL_SECTIONS:
        url = NL_BASE + path
        markup, sbase = page(url)
        if not markup:
            c.ok = False
            continue
        c.save(url, f"NLPNP Program Policies and Procedures – {section} (contents)", date=html_date(markup), ext=".html",
               name="NLPNP-" + slug(section) + "-contents")
        for href, text in links(markup, sbase, r"gov\.nl\.ca/immigration/|\.pdf$"):
            plain = href.split("#")[0]
            if plain.rstrip("/") in nav or plain.rstrip("/") == url.rstrip("/") or plain in seen or not text \
                    or text in ("Français", "English"):
                continue
            seen.add(plain)
            title = f"NLPNP Program Policies and Procedures – {section}: {text}"
            if "?" in plain:
                c.miss(title, url, "the link on the contents page is a broken editor-preview link (" + plain + ")")
                continue
            if plain.lower().endswith(".pdf"):
                c.save(plain, title, name="NLPNP-" + slug(section, 40) + "-" + slug(text, 70))
                continue
            sub, _ = page(plain) if not c.have(plain) else ("", plain)
            c.save(plain, title, date=html_date(sub), ext=".html", name="NLPNP-" + slug(section, 40) + "-" + slug(text, 70))
    c.done()


# --------------------------------------------------------------------------- Northwest Territories

NT_SITE = "https://www.immigratenwt.ca/"
NT_PAGES = [("program-guidelines-skilled-worker-nwt-express-entry", "Employer-Driven Stream (Skilled Worker, NWT Express Entry, Entry Level/Semi-Skilled Occupations)"),
            ("program-guidelines-entry-level-semi-skilled-occupations", "Employer-Driven Stream"),
            ("program-guidelines-francophone-stream", "Francophone Stream"),
            ("files/northwest-territories-nominee-program-business-stream-guidelines", "Business Stream")]


def nt():
    """immigratenwt.ca: the Program Guidelines of the Northwest Territories Nominee Program (one PDF per
    stream) and the Employer-Driven Stream points grid. The host asks for 10 s between requests."""
    c = Province("nt")
    seen = set()
    for path, stream in NT_PAGES:
        markup, base = page(NT_SITE + path)
        if not markup:
            c.ok = False
            continue
        when = find_date(clean(markup).split("Publication date:", 1)[-1][:40], month_ok=True) if "Publication date:" in clean(markup) else ""
        for href, _ in links(markup, base, r"/sites/immigratenwt/files/.*\.pdf$"):
            if href not in seen:
                seen.add(href)
                c.save(href, f"Northwest Territories Nominee Program: Program Guidelines – {stream}", date=when,
                       name="NTNP-program-guidelines-" + stream.split(" (")[0])
    markup, base = page(NT_SITE + "forms-and-resources")
    if not markup:
        c.ok = False
    for href, text in links(markup, base, r"points_grid.*\.pdf$"):
        c.save(href, f"Northwest Territories Nominee Program: Employer-Driven Stream {text}", name="NTNP-EOI-points-grid")
    c.done()


# --------------------------------------------------------------------------- nothing fetched

STATIC_MISSED = {   # known to exist, on hosts that refuse scripts (see NOTES.txt); [title, date, url, reason]
    "sk": [
        ["Saskatchewan Immigrant Nominee Program: 'Procedures and Guidelines' pages of each category (International Skilled Worker, Saskatchewan Experience, Entrepreneur, Farm)", "",
         "https://www.saskatchewan.ca/residents/moving-to-saskatchewan/live-in-saskatchewan/by-immigrating/saskatchewan-immigrant-nominee-program",
         "robots.txt of www.saskatchewan.ca shuts out ClaudeBot and other AI agents by name; site not read"],
        ["SINP application guides in the provincial publications centre (for example products 89059 and 76095)", "",
         "https://publications.saskatchewan.ca/api/v1/products/89059/formats/145324/download",
         "publications.saskatchewan.ca: TLS certificate chain could not be verified from this machine; not fetched"],
    ],
    "nb": [
        [t, "", u, "robots.txt of www2.gnb.ca and of www.gnb.ca answered HTTP 403; hosts not used"] for t, u in (
            ("Your Guide to the New Brunswick Skilled Worker Stream", "https://www2.gnb.ca/content/dam/gnb/Corporate/Promo/Immigration/guide-to-nb-skilled-worker-stream.pdf"),
            ("New Brunswick Express Entry Stream program guide", "https://www2.gnb.ca/content/dam/gnb/Corporate/Promo/Immigration/express-entry-program-guide.pdf"),
            ("New Brunswick Strategic Initiative Stream guide", "https://www2.gnb.ca/content/dam/gnb/Corporate/Promo/Immigration/strategic_initiative_guide-e.pdf"),
            ("New Brunswick Business Immigration Stream guide", "https://www.gnb.ca/content/dam/GNB3/t/fhc-fmc/immigration/docs/nb-business-immigration-stream-guide.pdf"),
            ("New Brunswick Entrepreneurial Stream guide (closed stream)", "https://www2.gnb.ca/content/dam/gnb/Corporate/Promo/Immigration/nb-entrepreneurial-stream-guide.pdf"),
            ("NBPNP post-nomination guide", "https://www2.gnb.ca/content/dam/gnb/Corporate/Promo/Immigration/NBPNP-post-nomination-guide.pdf"),
            ("Other stream guides linked from the Provincial Nominee Program pages (Priority Occupations, Employment in New Brunswick, New Brunswick Interests; French versions)", "https://www.gnb.ca/en/topic/family-home-community/immigration/provincial-nominee-program.html"),
        )],
    "pe": [
        ["PEI PNP Business Impact Category Application Guide (Work Permit Stream)", "2025",
         "https://www.princeedwardisland.ca/sites/default/files/publications/business_impact_application_guide.pdf",
         "www.princeedwardisland.ca answers scripts with a Radware browser check; host not used"],
        ["PEI Office of Immigration pages on the Provincial Nominee Program (Labour Impact and Business Impact categories, expression-of-interest rules)", "",
         "https://www.princeedwardisland.ca/en/topic/office-of-immigration",
         "www.princeedwardisland.ca answers scripts with a Radware browser check; host not used"],
    ],
    "yt": [
        [t, d, u, "robots.txt of yukon.ca answered HTTP 403; host not used"] for t, d, u in (
            ("Yukon Nominee Program Policy", "", "https://yukon.ca/sites/default/files/ecdev/ecdev-yukon-nominee-program-policy_0.pdf"),
            ("Yukon Nominee Program 2026 operational guidance", "2026-07-03", "https://yukon.ca/sites/default/files/ecdev-ynp-2026-operational-guidance-2026-07-03.pdf"),
            ("Programme des candidats du Yukon : directives opérationnelles 2026 (French version)", "2026-07-03", "https://yukon.ca/sites/default/files/ecdev-ynp-2026-operational-guidance-2026-07-03_fr.pdf"),
            ("Yukon Nominee Program: Skilled Worker criteria", "", "https://yukon.ca/sites/yukon.ca/files/ecdev/ecdev-skilled-worker-criteria.pdf"),
            ("Yukon Nominee Program: Critical Impact Worker criteria", "", "https://yukon.ca/en/critical-impact-worker-criteria"),
            ("Yukon Community Program criteria", "", "https://yukon.ca/sites/yukon.ca/files/ecdev/ecdev-yukon-community-program-criteria.pdf"),
            ("Yukon Business Nominee Program policy", "", "https://yukon.ca/en/yukon-business-nominee-program-policy"),
            ("Yukon Business Nominee Program policy: appendix", "", "https://yukon.ca/sites/yukon.ca/files/ecdev/ecdev-yukon-business-nominee-policy-appendix_0.pdf"),
            ("Yukon Nominee Program application handbook", "2026-07-02", "https://yukon.ca/sites/default/files/ecdev-yukon-nominee-program-application-handbook__2026.07.02.pdf"),
        )],
    "ab": [
        [t, "", u, "robots.txt of open.alberta.ca answered HTTP 403; host not used"] for t, u in (
            ("AINP Employer-Driven Stream: Skilled Worker Category (reference information, expired stream)", "https://open.alberta.ca/publications/ainp-employer-driven-stream-skilled-worker-category"),
            ("AINP Employer-Driven Stream: International Graduate Category (reference information, expired stream)", "https://open.alberta.ca/publications/ainp-employer-driven-stream-international-graduate-category"),
            ("AINP Employer-Driven Stream: Semi-skilled Worker Category (reference information, expired stream)", "https://open.alberta.ca/publications/ainp-employer-driven-stream-semi-skilled-worker-category"),
            ("AINP Strategic Recruitment Stream (reference information, expired stream)", "https://open.alberta.ca/publications/ainp-strategic-recruitment-stream"),
            ("AINP frequently asked questions for the expired Employer-Driven Stream categories", "https://open.alberta.ca/publications/ainp-frequently-asked-questions"),
        )],
    "qc": [
        ["Guide des procédures d'immigration: deposit copies of the pre-2018 components (and older editions) at Bibliothèque et Archives nationales du Québec", "",
         "https://collections.banq.qc.ca/ark:/52327/bs1984905",
         "collections.banq.qc.ca redirects scripts to a security page (also for robots.txt); host not used"],
    ],
}

HANDLERS = {"qc": qc, "bc": bc, "ab": ab, "mb": mb, "ns": ns, "nl": nl, "nt": nt}
ORDER = ["qc", "on", "bc", "ab", "sk", "mb", "ns", "nb", "pe", "nl", "yt", "nt", "nu"]


def write_listings():
    rows = []
    for row in MANIFEST["files"].values():
        if (ROOT / row["file"]).is_file():
            rows.append(row)
    code_of = {v: k for k, v in NAMES.items()}
    rows.sort(key=lambda r: (ORDER.index(code_of[r["province"]]), r["file"]))
    tsv = lambda *cells: "\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in cells) + "\n"   # noqa: E731
    with open(ROOT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\tprovince\ttitle\tdate\tsource_url\tkind\ttitle_en\n")
        for r in rows:
            f.write(tsv(r["file"], r["province"], r["title"], r["date"], r["source_url"], r["kind"], r["title_en"]))
    with open(ROOT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\tprovince\n")
        for code in ORDER:
            for title, date, url, reason in STATIC_MISSED.get(code, []) + MANIFEST["missed"].get(code, []):
                f.write(tsv(title, date, url, reason, NAMES[code]))
    return len(rows)


def main():
    wanted = [a.lower() for a in sys.argv[1:]] or [c for c in ORDER if c in HANDLERS]
    unknown = [w for w in wanted if w not in NAMES]
    if unknown:
        sys.exit(f"unknown province code(s): {' '.join(unknown)}; known: {' '.join(ORDER)}")
    ROOT.mkdir(parents=True, exist_ok=True)
    if MANIFEST_FILE.exists():
        MANIFEST.update(json.loads(MANIFEST_FILE.read_text(encoding="utf-8")))
    for code in wanted:
        print(f"{code}  {NAMES[code]}")
        if code in HANDLERS:
            HANDLERS[code]()
        else:
            print("  nothing to fetch (see NOTES.txt and not-obtained.tsv)")
    n = write_listings()
    print(f"index.tsv: {n} files; {STATS['new']} new in this run ({STATS['bytes'] / 1e6:.1f} MB)")
    for host, why in BLOCKED.items():
        print(f"host given up in this run: {host} ({why})")


if __name__ == "__main__":
    main()

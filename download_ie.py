#!/usr/bin/env python3
"""Download Ireland's published immigration guidance and policy documents.

    python3 download_ie.py                 # every source
    python3 download_ie.py isd ipat        # only the named sources
    python3 download_ie.py coi --max-mb 800

Sources (each is one site; a site is fetched over one connection, one request at a time):

  isd   Immigration Service Delivery, Department of Justice (www.irishimmigration.ie):
        policy documents, scheme guidelines, programme criteria, notices to employers,
        plus a few policy texts that exist only as web pages (saved as .html).
  ipat  International Protection Appeals Tribunal (www.protectionappeals.ie):
        Chairperson's guidelines, guidance notes, administrative practice notes,
        case-law summaries.
  ipo   International Protection Office (ipo.irishimmigration.ie): the few procedural
        documents on the current site, and procedural notices of the former
        www.ipo.gov.ie taken from the Internet Archive.
  dete  Department of Enterprise, Tourism and Employment (enterprise.gov.ie):
        employment permit policy - information notes, checklists, occupations-list
        reviews, remuneration roadmap, user guide.
  coi   Country-of-origin information of the Refugee Documentation Centre (Legal Aid
        Board): query responses and country information packs, which the Centre
        publishes through the EU asylum agency's COI portal (coi.euaa.europa.eu).
        Goes to ie/coi/ with its own index.

Rules the script keeps:
  - robots.txt of every host is read first and obeyed (including Crawl-delay).
  - At least 1 second between requests to a host (10 s where robots.txt asks for it,
    3 s for the Internet Archive).
  - HTTP 403 or 429 from a host ends the use of that host for the run. Nothing is retried
    around a refusal.
  - Files that exist are skipped. Files are saved as published. Only the standard library.

Output: ie/index.tsv, ie/coi/index.tsv, ie/not-obtained.tsv.
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ie"
UA = "immigration-guidelines-collector/1.0 (python-urllib; public document archive)"
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000
COI_MAX_BYTES = 500_000_000

DOC_EXT = r"\.(pdf|docx?|xlsx?|rtf|pptx?)"


class Refused(Exception):
    """The host refused (403/429/robots.txt) or is no longer used in this run."""


class Site:
    """One host: robots.txt, pacing, and a stop on refusal."""

    def __init__(self, host, min_delay=1.0, max_errors=None):
        self.host = host
        self.delay = max(1.0, min_delay)
        self.last = 0.0
        self.blocked = None            # reason, once the host is given up for the run
        self.robots = None
        self.errors = 0
        self.streak = 0                # failed requests in a row
        self.max_errors = max_errors   # give up after this many failed requests (archive)

    def _wait(self):
        gap = self.last + self.delay - time.time()
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()

    def _load_robots(self):
        self.robots = urllib.robotparser.RobotFileParser()
        url = f"https://{self.host}/robots.txt"
        self._wait()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                self.blocked = f"robots.txt: HTTP {e.code}"
                raise Refused(self.blocked)
            text, ctype = "", "text/plain"          # 404 and the like: no rules
        except Exception as e:                      # noqa: BLE001
            self.blocked = f"robots.txt unreachable: {e}"
            raise Refused(self.blocked)
        if "html" in ctype.lower() or text.lstrip().lower().startswith("<!doctype"):
            text = ""                               # a web page, not a robots file: no rules
        self.robots.parse(text.splitlines())
        # Crawl-delay may stand outside any User-agent group; honour the largest one given
        # for everyone or unscoped.
        delays = [float(x) for x in re.findall(r"(?im)^\s*crawl-delay\s*:\s*([\d.]+)", text)]
        if delays:
            self.delay = max(self.delay, min(max(delays), 30.0))
        self.last = time.time()

    def allowed(self, url):
        if self.robots is None:
            self._load_robots()
        return self.robots.can_fetch(UA, url) and self.robots.can_fetch("*", url)

    def open(self, url, headers=None):
        """Return an open response. Raises Refused or OSError."""
        if self.blocked:
            raise Refused(self.blocked)
        if not self.allowed(url):
            raise Refused("disallowed by robots.txt")
        self._wait()
        h = {"User-Agent": UA}
        h.update(headers or {})
        try:
            r = urllib.request.urlopen(urllib.request.Request(quote(url), headers=h), timeout=180)
            self.streak = 0
            return r
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                self.blocked = f"HTTP {e.code} from {self.host}; host not used again in this run"
                raise Refused(f"HTTP {e.code}")
            self._count_error()
            raise OSError(f"HTTP {e.code}")
        except Exception as e:                      # noqa: BLE001
            self._count_error()
            raise OSError(str(e))
        finally:
            self.last = time.time()

    def _count_error(self):
        self.errors += 1
        self.streak += 1
        if (self.max_errors and self.errors >= self.max_errors) or self.streak >= 5:
            self.blocked = f"{self.streak} failed requests in a row to {self.host}; host not used again in this run"
        else:
            time.sleep(20 * self.streak)                # a dropped connection: slow down before the next one

    def get(self, url, headers=None):
        with self.open(url, headers) as r:
            return r.read(), r.headers

    def text(self, url):
        return self.get(url)[0].decode("utf-8", "replace")

    def save(self, url, dest):
        """Download url to dest (via dest.part). Returns None, or the reason it failed."""
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.open(url) as r, open(part, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                length = r.headers.get("Content-Length")
            if length is not None and part.stat().st_size != int(length):
                part.unlink()
                return "transfer cut short"
        except Refused as e:
            part.unlink(missing_ok=True)
            return f"refused: {e}"
        except OSError as e:
            part.unlink(missing_ok=True)
            return str(e)
        why = wrong_type(part, dest.suffix.lower())
        if why:
            part.unlink()
            return why
        part.replace(dest)
        self.last = time.time()
        return None


SITES = {}


def site(host, delay=1.0, max_errors=None):
    if host not in SITES:
        SITES[host] = Site(host, delay, max_errors)
    return SITES[host]


def quote(url):
    return urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")


def wrong_type(path, ext):
    """None if the file's first bytes fit its extension, else a reason."""
    with open(path, "rb") as f:
        head = f.read(2048)
    if ext == ".pdf":
        ok = b"%PDF" in head[:1024]
    elif ext in (".docx", ".xlsx", ".pptx"):
        ok = head[:2] == b"PK"
    elif ext in (".doc", ".xls", ".ppt"):
        ok = head[:4] == b"\xd0\xcf\x11\xe0"
    elif ext == ".rtf":
        ok = head[:5] == b"{\\rtf"
    elif ext == ".html":
        ok = b"<html" in head.lower() or b"<!doctype" in head.lower()
    else:
        ok = True
    return None if ok else f"response is not a {ext[1:]} file (error or bot-check page?)"


def slug(s, n=110):
    """A safe file name; a long name is cut in the stem so the extension survives."""
    s = urllib.parse.unquote(s)
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s.encode("ascii", "ignore").decode())
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    m = re.search(DOC_EXT + r"$", s, re.I)
    ext = m.group(0).lower() if m else ""
    stem = s[:len(s) - len(ext)] if ext else s
    return (stem[:n].rstrip("-._") or "x") + ext


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def links(page, base):
    """(absolute url, link text) for each <a> in the main part of a page."""
    m = re.search(r"<main.*?</main>", page, re.S)
    body = m.group(0) if m else page
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
    out = []
    for href, label in re.findall(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        href = html.unescape(href).strip()
        if href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        out.append((urllib.parse.urljoin(base, href), clean(label)))
    return out


# --- bookkeeping -----------------------------------------------------------------

class Run:
    def __init__(self, folder, header, max_files, max_bytes):
        self.folder = folder
        self.header = header
        self.max_files, self.max_bytes = max_files, max_bytes
        self.rows = {}                 # file -> row (list)
        self.missing = []              # (source, title, url, reason)
        self.new = 0
        folder.mkdir(parents=True, exist_ok=True)
        idx = folder / "index.tsv"
        if idx.exists():               # keep rows from earlier runs (a host may be down today)
            for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
                cells = line.split("\t")
                if len(cells) >= len(header) and (folder / cells[0]).exists():
                    self.rows[cells[0]] = cells[:len(header)]

    def size(self):
        return sum((self.folder / f).stat().st_size for f in self.rows if (self.folder / f).exists())

    def fetch(self, st, source, url, rel, row, title):
        """Fetch url into folder/rel unless present; record the index row or the failure."""
        dest = self.folder / rel
        if dest.exists() and dest.stat().st_size > 0:
            self.rows[rel] = [rel] + row
            return True
        if len(self.rows) >= self.max_files or self.size() >= self.max_bytes:
            self.missing.append((source, title, url, "not attempted: file/size limit reached"))
            return False
        why = st.save(url, dest)
        if why:
            print(f"  FAILED {rel}: {why}", flush=True)
            self.missing.append((source, title, url, why))
            return False
        self.new += 1
        self.rows[rel] = [rel] + row
        print(f"  saved {rel} ({dest.stat().st_size:,} bytes)", flush=True)
        return True

    def write(self):
        with open(self.folder / "index.tsv", "w", encoding="utf-8") as f:
            f.write("\t".join(self.header) + "\n")
            for rel in sorted(self.rows):
                f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in self.rows[rel]) + "\n")


def wp_media(st, base, source, run):
    """All document attachments of a WordPress site through its public REST listing."""
    items, page, pages = [], 1, 1
    while page <= pages:
        url = (f"{base}/wp-json/wp/v2/media?media_type=application&per_page=100&page={page}"
               "&_fields=id,date,title,source_url,mime_type")
        try:
            data, headers = st.get(url)
        except (Refused, OSError) as e:
            run.missing.append((source, f"media listing page {page}", url, str(e)))
            break
        pages = int(headers.get("X-WP-TotalPages") or 1)
        for r in json.loads(data):
            items.append((r["source_url"], clean(r["title"]["rendered"]), r["date"][:10]))
        page += 1
    return items


def page_docs(st, urls, source, run):
    """Document links found on the given pages: {url: (link text, page)}."""
    found = {}
    for u in urls:
        try:
            page = st.text(u)
        except (Refused, OSError) as e:
            run.missing.append((source, "listing page", u, str(e)))
            continue
        for href, label in links(page, u):
            if re.search(DOC_EXT + r"$", urllib.parse.urlsplit(href).path, re.I):
                found.setdefault(href, (label, u))
    return found


def upload_month(url):
    m = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def dated_name(date, url):
    name = slug(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
    return f"{date}_{name}" if date else name


# --- Immigration Service Delivery ------------------------------------------------

ISD = "https://www.irishimmigration.ie"
# Pages that carry or link policy documents (the media listing misses some older uploads).
ISD_PAGES = [
    "/immigration-legislation-and-policy-guidelines/",
    "/coming-to-join-family-in-ireland/policy-document-archive/",
    "/coming-to-join-family-in-ireland/joining-an-irish-national/join-family-visa/",
    "/coming-to-join-family-in-ireland/joining-your-uk-national-family-member/",
    "/coming-to-join-family-in-ireland/joining-an-eea-or-swiss-national/eu-treaty-rights/",
    "/coming-to-study-in-ireland/policy-on-non-eea-nationals/",
    "/coming-to-study-in-ireland/what-are-my-study-options/interim-list-of-eligible-programmes-ilep/",
    "/coming-to-live-in-ireland/i-want-to-invest-in-ireland/",
    "/coming-to-work-in-ireland/what-are-my-options-for-working-in-ireland/coming-to-work-for-more-than-90-days/start-up-entrepreneur-programme-step/",
    "/coming-to-work-in-ireland/what-are-my-options-for-working-in-ireland/coming-to-work-for-more-than-90-days/minister-of-religion/",
    "/coming-to-work-in-ireland/what-are-my-options-for-working-in-ireland/coming-to-work-for-more-than-90-days/volunteer/",
    "/my-situation-has-changed-since-i-arrived-in-ireland/immigration-guidelines-for-victims-of-domestic-abuse/",
    "/my-situation-has-changed-since-i-arrived-in-ireland/third-level-graduate-programme/",
    "/my-situation-has-changed-since-i-arrived-in-ireland/de-facto-partner-of-an-irish-or-non-eea-national/",
    "/my-situation-has-changed-since-i-arrived-in-ireland/reactivation-employment-permit-scheme/",
    "/registering-your-immigration-permission/how-to-renew-your-current-permission/notice-to-employers/",
    "/registering-your-immigration-permission/how-to-renew-your-current-permission/information-on-stamp-4-upgrades/",
    "/regularisation-of-long-term-undocumented-migrant-scheme/",
    "/the-afghan-admission-programme-information-page/",
    "/how-to-become-a-citizen/become-an-irish-citizen-by-naturalisation/proofs-of-identity-and-residence/",
    "/my-situation-has-changed-since-i-arrived-in-ireland/student-permission/",
    "/my-situation-has-changed-since-i-arrived-in-ireland/long-term-residency/",
    "/coming-to-join-family-in-ireland/joining-an-irish-national/de-facto-partner-of-an-irish-national/",
    "/coming-to-join-family-in-ireland/family-reunification-of-international-protection-holders/",
]
# Policy texts published only as web pages: saved as they are served.
ISD_HTML = [
    ("/registering-your-immigration-permission/information-on-registering/immigration-permission-stamps/",
     "Immigration permission stamps (stamp categories and conditions)"),
    ("/short-stay-visas-policy/", "Policy for consideration of short stay 'C' visas"),
    ("/coming-to-work-in-ireland/what-are-my-work-visa-options/applying-for-a-long-stay-employment-visa/van-der-elst-visa/van-der-elst-policy-document/",
     "Van der Elst policy document"),
    ("/coming-to-join-family-in-ireland/financial-thresholds/", "Family reunification: financial thresholds"),
    ("/registering-your-immigration-permission/information-on-registering/glossary-of-immigration-terms/",
     "Glossary of immigration terms"),
    ("/single-multiple-visas/", "Single and multiple entry visas"),
    ("/appeal-a-negative-decision/", "Appealing a negative visa decision"),
    ("/extension-of-visitor-permission/", "Extension of visitor permission"),
    ("/how-to-become-an-irish-citizen-guide/", "Citizenship by naturalisation: guide (conditions, residence, good character)"),
    ("/coming-to-join-family-in-ireland/joining-a-non-eea-non-swiss-national/join-non-eea-family-member/",
     "Joining a non-EEA family member"),
    ("/coming-to-join-family-in-ireland/joining-a-non-eea-non-swiss-national/dependent-adult-relative/",
     "Dependent adult relative (Stamp 0)"),
    ("/coming-to-join-family-in-ireland/joining-an-irish-national/de-facto-partner-of-an-irish-national/",
     "De facto partner of an Irish national"),
    ("/coming-to-join-family-in-ireland/joining-an-eea-or-swiss-national/de-facto-partner-of-a-critical-skills-employment-permit-holder-csep-or-hosting-agreement-holder-ha/",
     "De facto partner of a Critical Skills Employment Permit or Hosting Agreement holder"),
    ("/coming-to-join-family-in-ireland/joining-an-eea-or-swiss-national/eu-treaty-rights/", "EU Treaty Rights"),
    ("/coming-to-join-family-in-ireland/joining-your-uk-national-family-member/",
     "Joining a UK national family member (post-Brexit scheme)"),
    ("/coming-to-live-in-ireland/i-want-to-retire-to-ireland/", "Retirement (Stamp 0) conditions"),
    ("/coming-to-study-in-ireland/professional-training-accountancy/", "Immigration rules for accountancy students"),
    ("/coming-to-work-in-ireland/what-are-my-work-visa-options/applying-for-a-long-stay-employment-visa/atypical-working-scheme/",
     "Atypical Working Scheme"),
    ("/coming-to-work-in-ireland/what-are-my-options-for-working-in-ireland/coming-to-work-for-more-than-90-days/minister-of-religion/",
     "Minister of religion immigration permission"),
    ("/coming-to-work-in-ireland/what-are-my-options-for-working-in-ireland/coming-to-work-for-more-than-90-days/volunteer/",
     "Volunteer immigration permission"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/long-term-residency/", "Long-term residency"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/without-condition-as-to-time/", "Without condition as to time (Stamp 5)"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/student-permission/", "Student permission"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/family-dependents/", "Family dependants"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/spouse-civil-partner-of-irish-national-scheme/",
     "Spouse or civil partner of an Irish national scheme"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/the-parent-of-an-irish-citizen-child/", "Parent of an Irish citizen child"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/labour-market-access-permission/",
     "Labour market access permission (international protection applicants)"),
    ("/my-situation-has-changed-since-i-arrived-in-ireland/turkish-association-agreement/", "Turkish Association Agreement"),
    ("/regularisation-of-long-term-undocumented-migrant-scheme/", "Regularisation of long-term undocumented migrants scheme"),
]
ISD_KEEP = re.compile(
    r"polic(y|ies)|guideline|guidlines|criteria|family-?reunification|de-facto|minister-of-religion"
    r"|volunteering|5-year-workers|shos-and-registrars|reactivation|victims|notice-to-employers"
    r"|stamp-3|third-level-graduate|immigration-regime|short-term-language-students"
    r"|investor-programme-guidelines|iip-updatedfaq|faqs-closure-of-iip|undocumented"
    r"|afghan-admission-programme-guidance|panel-member-information|visa-decisions"
    r"|visa-waiver|brexit|british-citizens|annex-[abc]\b|internationalisation-register"
    r"|ia-guidance|irish-association-wording|citizenship-eligibility-guide|tco-booklet"
    r"|spc-amended-terms|checklist-for-directive|required-documents-reference-guide"
    r"|citizenship-guidance|investor-programme-enterprise", re.I)
ISD_DROP = re.compile(
    r"application-?form|-form\b|form-|\bform\d|foirm|editable|fillable|privacy|data[-_]protection"
    r"|feedback|closure-dates|photo|leaflet|how-to|portal|user-guide|open-call|reintegration"
    r"|declaration|affidavit|statistic|survey|workshop|roundtable|review|report|safeguarding"
    r"|money-laundering|unaccomp|travel-confirmation|letter-for-persons|country-?coverage"
    r"|\b(si|s\.i)[-.]|directive-\d{4}\d|council-decision|act-19|act-20|submissions|proposals"
    r"|arabic|cantonese|french|hindi|mandarin|portuguese|spanish|tagalog|urdu|[-_](cn|ga)[-_.]|treoir"
    r"|covid|ukraine|temporary-protection|e-vetting|helpdesk|-faqs?\b|^faqs?-|faq-", re.I)


def isd_wanted(url):
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    return bool(ISD_KEEP.search(name)) and not ISD_DROP.search(name)


def isd(run):
    st = site("www.irishimmigration.ie")
    src = "isd"
    docs = {}                                           # url -> (title, date)
    for url, title, date in wp_media(st, ISD, src, run):
        docs[url] = (title, date)
    for url, (label, page) in page_docs(st, [ISD + p for p in ISD_PAGES], src, run).items():
        if url.startswith(ISD) and url not in docs:
            docs[url] = (label, upload_month(url))
    kept = 0
    for url, (title, date) in sorted(docs.items(), key=lambda kv: kv[1][1], reverse=True):
        if not isd_wanted(url):
            continue
        kept += 1
        run.fetch(st, src, url, f"isd/{dated_name(date, url)}",
                  [title, date, url, "Immigration Service Delivery", "date = upload to the site"], title)
    today = time.strftime("%Y-%m-%d")
    for path, title in ISD_HTML:
        rel = f"isd/webpage_{slug(path.strip('/').rsplit('/', 1)[-1])}.html"
        run.fetch(st, src, ISD + path, rel,
                  [title, today, ISD + path, "Immigration Service Delivery", "web page; date = day saved"], title)
    print(f"isd: {len(docs)} documents listed, {kept} selected as policy/guidance", flush=True)


# --- International Protection Appeals Tribunal -----------------------------------

IPAT = "https://www.protectionappeals.ie"
IPAT_PAGES = ["/chairpersons-guidelines/", "/administrative-practice-note/", "/av-hearings-protocol-and-guidance/",
              "/other-practices-and-procedures/", "/other-publications/"]
IPAT_KEEP = re.compile(r"guideline|guidance[-_ ]note|practice[-_ ]note|av-hearings|clarification-of-arrangements"
                       r"|case-law|summary-of-judgments|protocol", re.I)
IPAT_DROP = re.compile(r"unhcr-eligibility-guidelines\.pdf$|pd_00\d|form", re.I)


def ipat(run):
    st = site("www.protectionappeals.ie")
    src = "ipat"
    docs = {}
    for url, title, date in wp_media(st, IPAT, src, run):
        docs[url] = (title, date)
    for url, (label, page) in page_docs(st, [IPAT + p for p in IPAT_PAGES], src, run).items():
        if url.startswith(IPAT) and url not in docs:
            docs[url] = (label, upload_month(url))
    kept = 0
    for url, (title, date) in sorted(docs.items(), key=lambda kv: kv[1][1], reverse=True):
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if not IPAT_KEEP.search(name) or IPAT_DROP.search(name):
            continue
        kept += 1
        run.fetch(st, src, url, f"ipat/{dated_name(date, url)}",
                  [title, date, url, "International Protection Appeals Tribunal", "date = upload to the site"], title)
    print(f"ipat: {len(docs)} documents listed, {kept} selected", flush=True)


# --- International Protection Office ---------------------------------------------

IPO = "https://ipo.irishimmigration.ie"
IPO_KEEP = re.compile(r"prioriti|panel[-_ ]member[-_ ]information|procedure|guidance|guideline|polic|code[-_ ]of[-_ ]conduct"
                      r"|safe[-_ ]countr|process[-_ ]overview|information[-_ ]note|designation", re.I)
IPO_DROP = re.compile(r"brochure|leaflet|form|privacy|cookie|eurodac|rcd_|booklet|data[-_ ]protection|preface|unhcr", re.I)
# Procedural notices of the former www.ipo.gov.ie, from the Internet Archive.
# (Wayback timestamp, original URL, title, date)
IPO_ARCHIVE = [
    ("2017", "http://www.ipo.gov.ie/en/IPO/Prioritisation_of_International_Protection_Applications_IPO_UNHCR_Notice_2017.pdf/Files/Prioritisation_of_International_Protection_Applications_IPO_UNHCR_Notice_2017.pdf",
     "Prioritisation of applications for international protection (IPO and UNHCR notice)", "2017"),
    ("2022", "http://www.ipo.gov.ie/en/IPO/International-Protection-Regularisation-Scheme-Policy-Paper.pdf/Files/International-Protection-Regularisation-Scheme-Policy-Paper.pdf",
     "International protection regularisation scheme: policy paper", "2022"),
    ("2023", "http://www.ipo.gov.ie/en/IPO/Case%20Processing%20Panel%20Member%20Information%20Note%202023.pdf/Files/Case%20Processing%20Panel%20Member%20Information%20Note%202023.pdf",
     "Case processing panel member information note 2023", "2023"),
    ("2022", "http://www.ipo.gov.ie/en/IPO/Case%20Processing%20Panel%20Member%20Information%20Note%20V2.0.pdf/Files/Case%20Processing%20Panel%20Member%20Information%20Note%20V2.0.pdf",
     "Case processing panel member information note, version 2.0", ""),
    ("2024", "http://www.ipo.gov.ie/en/IPO/Panel%20Member%20Information%20Booklet%202024.pdf/Files/Panel%20Member%20Information%20Booklet%202024.pdf",
     "Panel member information booklet 2024", "2024"),
    ("2018", "http://www.ipo.gov.ie/en/IPO/IP%20General%20Process%20Overview%20Chart.pdf/Files/IP%20General%20Process%20Overview%20Chart.pdf",
     "International protection: general process overview chart", ""),
    ("2017", "http://www.ipo.gov.ie/en/IPO/IPO%20INFORMATION%20NOTE%20JANUARY%202017.pdf/Files/IPO%20INFORMATION%20NOTE%20JANUARY%202017.pdf",
     "IPO information note, January 2017", "2017-01"),
    ("2017", "http://www.ipo.gov.ie/en/IPO/IPO%20TRANSITION%20INFO%20NOTE%20FINAL%20FOR%20WEBSITE.pdf/Files/IPO%20TRANSITION%20INFO%20NOTE%20FINAL%20FOR%20WEBSITE.pdf",
     "Transitional arrangements information note (International Protection Act 2015)", "2017"),
    ("2018", "http://www.ipo.gov.ie/en/IPO/SAFE%20COUNTRY%20OF%20ORIGIN%20INFORMATION%20NOTICE%20(APRIL%202018)%20ADDENDUM%202%20TO%20IPO.._%20(003).pdf/Files/SAFE%20COUNTRY%20OF%20ORIGIN%20INFORMATION%20NOTICE%20(APRIL%202018)%20ADDENDUM%202%20TO%20IPO.._%20(003).pdf",
     "Safe country of origin information notice (April 2018)", "2018-04"),
    ("2018", "http://www.ipo.gov.ie/en/IPO/Access%20to%20Labour%20Market%20-%20Addendum%20to%20IPO%20001.docx%20-%206%20FEB%202018.pdf/Files/Access%20to%20Labour%20Market%20-%20Addendum%20to%20IPO%20001.docx%20-%206%20FEB%202018.pdf",
     "Access to the labour market: addendum to IPO 1", "2018-02-06"),
    ("2017", "http://www.ipo.gov.ie/en/IPO/IPO%20(SP)%2005%20-%20SP%20INFORMATION%20NOTE%20(2017%20REGS)%20FOR%20APPLICANTS%20%20-%2022%20SEPTEMBER%202017.pdf/Files/IPO%20(SP)%2005%20-%20SP%20INFORMATION%20NOTE%20(2017%20REGS)%20FOR%20APPLICANTS%20%20-%2022%20SEPTEMBER%202017.pdf",
     "Subsidiary protection information note (2017 Regulations)", "2017-09-22"),
]


def ipo(run):
    src = "ipo"
    st = site("ipo.irishimmigration.ie")
    docs = {}
    for url, title, date in wp_media(st, IPO, src, run):
        docs[url] = (title, date)
    pages = []
    try:
        sm = st.text(IPO + "/wp-sitemap-posts-page-1.xml")
        pages = [u for u in re.findall(r"<loc>([^<]+)", sm) if "forms-information" in u or "about-ipo" in u]
    except (Refused, OSError) as e:
        run.missing.append((src, "page sitemap", IPO + "/wp-sitemap-posts-page-1.xml", str(e)))
    for url, (label, page) in page_docs(st, pages, src, run).items():
        if url.startswith(IPO) and url not in docs:
            docs[url] = (label, upload_month(url))
    kept = 0
    for url, (title, date) in sorted(docs.items(), key=lambda kv: kv[1][1], reverse=True):
        name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if not IPO_KEEP.search(name + " " + title) or IPO_DROP.search(name):
            continue
        kept += 1
        run.fetch(st, src, url, f"ipo/{dated_name(date, url)}",
                  [title, date, url, "International Protection Office", "date = upload to the site"], title)
    print(f"ipo: {len(docs)} documents listed on the current site, {kept} selected", flush=True)

    wb = site("web.archive.org", 3.0, max_errors=4)
    for stamp, orig, title, date in IPO_ARCHIVE:
        name = slug(orig.rsplit("/", 1)[-1])
        rel = f"ipo/archive/{date + '_' if date else ''}{name}"
        url = f"https://web.archive.org/web/{stamp}id_/{orig}"
        run.fetch(wb, src, url, rel,
                  [title, date, url, "International Protection Office (former www.ipo.gov.ie, via Internet Archive)", ""], title)


# --- Department of Enterprise: employment permits --------------------------------

DETE = "https://enterprise.gov.ie"
DETE_START = ["/en/what-we-do/workplace-and-skills/employment-permits/",
              "/en/what-we-do/workplace-and-skills/economic-migration-policy/"]
DETE_SECTION = re.compile(r"^/en/what-we-do/workplace-and-skills/(employment-permits|economic-migration-policy)/", re.I)
DETE_PUB = re.compile(r"^/en/publications/[^/]+\.html$", re.I)
DETE_PUB_KEEP = re.compile(r"employment-permit|occupation|economic-migration|remuneration|mar-|atypical|hosting", re.I)
DETE_SKIP = re.compile(r"statist|statisit|application-form|notification-of|data-security|trusted-partner.*slides"
                       r"|/forms?/|processing-dates", re.I)
DETE_DOC_DROP = re.compile(r"statist|-form\b|form-|form\.|^application-|notification|submission|response-|slides|privacy"
                           r"|compan\w*-issued|permits-(issued-)?(by|to)-", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}


def dete_date(page):
    m = re.search(r'class="article-date[^"]*">\s*(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})', page)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return ""


def dete(run, max_pages=250):
    st = site("enterprise.gov.ie")
    src = "dete"
    queue, seen, docs = list(DETE_START), set(), {}
    try:                                                # publication pages not linked from the section
        for u in re.findall(r"<loc>([^<]+)", st.text(DETE + "/sitemap.xml")):
            path = urllib.parse.urlsplit(u.strip()).path
            if DETE_PUB.match(path) and DETE_PUB_KEEP.search(path) and not DETE_SKIP.search(path):
                queue.append(path)
    except (Refused, OSError) as e:
        run.missing.append((src, "sitemap", DETE + "/sitemap.xml", str(e)))
    while queue and len(seen) < max_pages:
        path = queue.pop(0)
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            page = st.text(DETE + path)
        except Refused as e:
            run.missing.append((src, "section page", DETE + path, str(e)))
            break
        except OSError as e:
            if "404" not in str(e):
                run.missing.append((src, "section page", DETE + path, str(e)))
            continue
        date = dete_date(page) if DETE_PUB.match(path) else ""
        heading = clean((re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) or [None, ""])[1])
        for href, label in links(page, DETE + path):
            u = urllib.parse.urlsplit(href)
            if u.netloc.lower().removeprefix("www.") != "enterprise.gov.ie":
                continue
            if re.search(DOC_EXT + r"$", u.path, re.I):
                if "/publication-files/" not in u.path.lower():
                    continue
                url = DETE + u.path.lower()             # the site serves paths in any letter case
                label = re.sub(r"\s*(»|\((PDF|Word)[^)]*\))\s*$", "", label, flags=re.I)
                old = docs.get(url)
                if old is None or (date and not old[1]):
                    docs[url] = (label or heading, date, DETE + path)
            elif u.path.lower() not in seen and not DETE_SKIP.search(u.path) and (
                    DETE_SECTION.match(u.path) or (DETE_PUB.match(u.path) and DETE_PUB_KEEP.search(u.path))):
                queue.append(u.path)
    kept = 0
    for url, (title, date, page) in sorted(docs.items()):
        name = url.rsplit("/", 1)[-1]
        if DETE_DOC_DROP.search(name):
            continue
        kept += 1
        rel = f"dete/{dated_name(date, url)}"
        row = [title, date, url, "Department of Enterprise, Tourism and Employment", f"listed on {page}"]
        if not run.fetch(st, src, url, rel, row, title) and run.missing and run.missing[-1][3] == "HTTP 404":
            # a dead link on the live site: take the Internet Archive's copy if it has one
            wb = site("web.archive.org", 3.0, max_errors=4)
            row[2] = f"https://web.archive.org/web/2id_/{url}"
            row[4] += "; dead link on the site, copy from the Internet Archive"
            if run.fetch(wb, src, row[2], rel, row, title):
                run.missing = [m for m in run.missing if m[2] != url]
    print(f"dete: {len(seen)} pages read, {len(docs)} documents linked, {kept} selected", flush=True)


# --- Refugee Documentation Centre COI (through the EUAA COI portal) --------------

EUAA = "https://coi.euaa.europa.eu"


def coi(run):
    """The portal's own public search service (SharePoint search REST, anonymous template),
    filtered to the source 'Ireland' = Refugee Documentation Centre, Legal Aid Board."""
    st = site("coi.euaa.europa.eu")
    src = "coi"
    items, start, total = [], 0, None
    while total is None or start < total:
        url = (f"{EUAA}/_api/search/query?querytext='Source:%22Ireland%22'&rowlimit=250&startrow={start}"
               "&trimduplicates=false&selectproperties='Title,Path,Origin,Type,Language,PublicationDate,Size'"
               "&sortlist='PublicationDate:descending'"
               "&QueryTemplatePropertiesUrl='spfile://webroot/queryparametertemplate.xml'")
        try:
            data, _ = st.get(url, {"Accept": "application/json;odata=nometadata"})
            res = json.loads(data)["PrimaryQueryResult"]["RelevantResults"]
        except (Refused, OSError, KeyError, ValueError) as e:
            run.missing.append((src, f"search listing from row {start}", url, str(e)))
            break
        total = res["TotalRows"]
        rows = res["Table"]["Rows"]
        if not rows:
            break
        for r in rows:
            items.append({c["Key"]: c["Value"] for c in r["Cells"]})
        start += len(rows)
    print(f"coi: {len(items)} documents listed (portal reports {total})", flush=True)
    seen = set()
    for it in items:
        path = it.get("Path") or ""
        # the index names the back-office host; the public copy is on the portal host
        url = re.sub(r"^https?://[^/]+", EUAA, path)
        if not re.search(DOC_EXT + r"$", url, re.I) or url in seen:
            continue
        seen.add(url)
        date = ""
        try:                                            # stored as local midnight in UTC: round to the day
            stamp = datetime.strptime((it.get("PublicationDate") or "")[:19], "%Y-%m-%dT%H:%M:%S")
            date = (stamp + timedelta(hours=6)).strftime("%Y-%m-%d")
        except ValueError:
            pass
        title = clean(it.get("Title") or "")
        country = clean(it.get("Origin") or "").replace(";", "; ")
        kind = clean(it.get("Type") or "").split("  ")[0]
        run.fetch(st, src, url, dated_name(date, url), [country, title, date, url, kind], title)


# --- main ------------------------------------------------------------------------

SOURCES = {"isd": isd, "ipat": ipat, "ipo": ipo, "dete": dete, "coi": coi}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sources", nargs="*", choices=list(SOURCES) + [[]], help="default: all")
    ap.add_argument("--max-mb", type=int, help="size limit for the country-of-origin folder (default 500)")
    args = ap.parse_args()
    chosen = args.sources or list(SOURCES)
    guide = Run(OUT, ["file", "title", "date", "source_url", "publisher", "note"], MAX_FILES, MAX_BYTES)
    cdir = OUT / "coi"
    crun = Run(cdir, ["file", "country", "title", "date", "source_url", "type"], 5000,
               (args.max_mb * 1_000_000) if args.max_mb else COI_MAX_BYTES)
    for name in chosen:
        run = crun if name == "coi" else guide
        print(f"== {name}", flush=True)
        try:
            SOURCES[name](run)
        except Refused as e:
            run.missing.append((name, "whole source", "", f"refused: {e}"))
            print(f"  {name}: stopped - {e}", flush=True)
        (crun if name == "coi" else guide).write()
    # the guidance index must not list the country-of-origin folder
    guide.rows = {k: v for k, v in guide.rows.items() if not k.startswith("coi/")}
    guide.write()
    crun.write()

    # not-obtained.tsv: failures of this run, plus standing entries kept in the file by hand
    path = OUT / "not-obtained.tsv"
    keep = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            cells = line.split("\t")
            if cells and cells[0] not in chosen and len(cells) >= 4:
                keep.append(cells[:4])
            elif len(cells) >= 4 and cells[3].startswith("standing:"):
                keep.append(cells[:4])
    rows = keep + [list(m) for m in guide.missing + crun.missing]
    with open(path, "w", encoding="utf-8") as f:
        f.write("source\ttitle\turl\treason\n")
        done = set()
        for r in rows:
            if tuple(r) not in done:
                done.add(tuple(r))
                f.write("\t".join(c.replace("\t", " ") for c in r) + "\n")
    for st in SITES.values():
        if st.blocked:
            print(f"host given up: {st.host}: {st.blocked}")
    print(f"guidance: {len(guide.rows)} files, {guide.size() / 1e6:.1f} MB ({guide.new} new); "
          f"coi: {len(crun.rows)} files, {crun.size() / 1e6:.1f} MB ({crun.new} new); "
          f"{len(guide.missing) + len(crun.missing)} not obtained this run")


if __name__ == "__main__":
    main()

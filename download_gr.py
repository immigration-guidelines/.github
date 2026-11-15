#!/usr/bin/env python3
"""Download Greek circulars and instructions on residence permits and asylum.

    python3 download_gr.py                 # everything
    python3 download_gr.py --no-wayback    # ministry site only, plus the Diavgeia listing
    python3 download_gr.py --refresh-diavgeia   # re-list the closed ministries on Diavgeia too
    python3 download_gr.py --recheck       # ask the Wayback Machine again for items it lacked

Greece has no single case-officer manual. The Ministry of Migration and Asylum
(and before 2020 the Interior / Migration Policy ministries) issues circulars
(egkyklioi) and clarifying letters (dieukrinistika eggrafa) to the Aliens and
Migration Directorates of the Decentralised Administrations, to the Asylum
Service and to the Reception and Identification Service. This script saves them
into ./gr/ from three places:

  ministry  migration.gov.gr  legislation pages (circular sections only) and the
            per-permit "clarifications" pages; files under /wp-content/uploads/
  diavgeia  diavgeia.gov.gr   transparency portal. Only its open-data API
            (/opendata/...) is used, to LIST circulars (type A.3) of the migration
            ministries. Its robots.txt disallows /doc/*, which is where the PDFs
            are, so the PDFs are never fetched from Diavgeia by this script.
  wayback   web.archive.org   archived copies of those Diavgeia PDFs, where one exists.

Whatever is listed but not saved goes to gr/not-obtained.tsv with the address
to open in a browser and the file name to save it under; a file saved by hand
under that name is picked up by the next run.

Rules: robots.txt of every host is read first and obeyed; a host that answers
403 or 429 is not asked again in that run; one request at a time, 1.2 s apart
(4 s for the Internet Archive, which also stops after three refusals).
Existing files are skipped; gr/index.tsv is rebuilt on every run.
Standard library only.
"""
import argparse
import datetime
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
OUT = ROOT / "gr"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = {"default": 1.2, "archive.org": 4.0, "web.archive.org": 4.0}
MAX_BYTES = 1_000_000_000
MAX_FILES = 3000
TODAY = datetime.date.today().isoformat()

SITE = "https://migration.gov.gr"
DIAVGEIA = "https://diavgeia.gov.gr"

# ---- ministry pages --------------------------------------------------------------------
# (path, folder, mode). Modes:
#   guidance  every document on the page except statutes (laws, decrees, ministerial decisions)
#   circ      only rows that call themselves a circular (egkyklios)
#   pick:RE   only links whose label or file name matches RE
#   page      save the page itself (the guidance is published as page text only)
PAGES = [
    ("/nomothesia-1-2/nomothesia-ypiresia-nomimis-metanasteysis/", "residence", "guidance"),
    ("/migration-policy/metanasteusi-stin-ellada/dieukrinistika-dikaiom-ypoxr-diadik/", "residence", "guidance"),
    ("/eu-blue-card/", "residence", "guidance"),
    ("/adeia-epimakron-diamenontos/", "residence", "guidance"),
    ("/dieukrinistika-meli-oik-3xora/", "residence", "guidance"),
    ("/migration-policy/metanasteusi-stin-ellada/meli-oikogeneias-ellina/", "residence", "guidance"),
    ("/meli-politiee/", "residence", "guidance"),
    ("/polites-ee-meli-oikogeneias/", "residence", "guidance"),
    ("/polites-triton-xoron-melh-oikogeneias-politi-eu/", "residence", "guidance"),
    ("/dieukrinistika-golden-visa/", "residence", "guidance"),
    ("/golden-visa/", "residence", "guidance"),
    ("/ependytiki-drastiriotita/", "residence", "guidance"),
    ("/migration-policy/metanasteusi-stin-ellada/ergasia-metakliseis/", "residence", "guidance"),
    ("/prosorini-ergasia/", "residence", "guidance"),
    ("/prosorini-ergasia-13a-4251-2014/", "residence", "guidance"),
    ("/prosorini-ergasia-epochiakoi-ergazomenoi/", "residence", "guidance"),
    ("/prosorini-aliergates/", "residence", "guidance"),
    ("/exairetikoi-logoi-adeia-diamonis/", "residence", "guidance"),
    ("/adeia-diamonis-gia-anthropistikous-logous/", "residence", "guidance"),
    ("/adeia-diamonis-gia-epaggelmatiki-katartisi/", "residence", "guidance"),
    ("/adeia-diamonis-gia-oikonomika-anexartita-atoma/", "residence", "guidance"),
    ("/adeia-diamonis-gia-spoudes/", "residence", "guidance"),
    ("/adeia-diamonis-10etis/", "residence", "guidance"),
    ("/adeia-diamonis-deuteris-genias/", "residence", "guidance"),
    ("/adeia-diamonis-brexit/", "residence", "guidance"),
    ("/migration-policy/metanasteusi-stin-ellada/brexit/", "residence", "guidance"),
    ("/autotelis-adeia-diamonis/", "residence", "guidance"),
    ("/eidiki-vevaiosi-nom-diam/", "residence", "guidance"),
    ("/zitimata-asfalisis/", "residence", "guidance"),
    ("/prostima-paravola/", "residence", "guidance"),
    ("/nomothesia-1-2/nomothesia-ypiresia-asyloy/", "asylum", "circ"),
    ("/nomothesia-1-2/nomothesia-archi-prosfygon/", "asylum", "circ"),
    ("/nomothesia-1-2/nomothesia-prostasia-aitoynton-asylo/", "asylum", "circ"),
    ("/nomothesia-1-2/nomothesia-ypiresia-ypodochis-kai-taytopoiisis/", "asylum", "circ"),
    ("/nomothesia-1-2/nomothesia-eidiki-grammateia-prostasias-asynodeyton-anilikon/", "asylum", "circ"),
    ("/nomothesia-1-2/nomothesia-koinoniki-entaxi/", "asylum", "circ"),
    ("/gas/diadikasies/doyvlino-iii/", "asylum", r"pick:Best.Interest|Οδηγίες για τη συμπλήρωση"),
    ("/gas/diadikasies/diagrammata-rois-diadikasion-asyloy/", "asylum", "pick:."),
    ("/standard-procedures/", "asylum", "page"),
    ("/diadikasies-ypyt-new/", "asylum", "page"),
]
# The ministry's own lists of its circulars; every entry links to Diavgeia.
CIRCULAR_LISTS = [
    "/egkyklioi-yma/",
    "/egkyklioi-genikis-grammateias-metanasteytikis-politikis/",
    "/egkyklioi-nomikis-ypostirixis-asyloy-kai-ypodochis/",
    "/egkyklioi-genikis-grammateias-eyaloton-politon-kai-thesmikis-prostasias/",
    "/egkyklioi-ypiresiakis-grammateias/",
]

DOC_EXT = re.compile(r"\.(pdf|docx?|xlsx?|odt|rtf)$", re.I)
STATUTE_LABEL = re.compile(
    r"^\W*(Ν[όο]μος|N[όο]μος|Ν\.\s?\d|Προεδρικ|Π\.\s?Δ\.|ΠΔ\b|Κοινή Υπουργική|Kοινή Υπουργική|κοινή υπουργική"
    r"|Υπουργική [Αα]πόφαση|Yπουργική|Διόρθωση σφάλματος|Κώδικας Μετανάστευσης|Πράξη Νομοθετικού|Απόφαση|Aπόφαση"
    r"|Αποφάσεις|Οδηγίας? 20\d\d/|Κανονισμός|ΚΑΝΟΝΙΣΜΟΣ|Σύμβαση|Ευρωπαϊκή Σύμβαση|Συμφωνία|Law\b|Joint Ministerial"
    r"|\(?άρθρο 24 ΠΔ|υπ’ αριθ\. 4000)", re.I)
STATUTE_FILE = re.compile(
    r"(^|[-_/. ])(ΚΥΑ|KYA|ΥΑ|YA|κυα|υα)[-_ ]?\d|ΦΕΚ|FEK|fek_|^Ν\d{4}|^N\d{4}|nomos_|Νόμος|ν\.\d{4}|ΠΔ-?\d|Website-ΠΔ"
    r"|υα-παράτασης|ΟΔΗΓΙΑ-20|Directive_|ΠΙΝΑΚΑΣ-ΔΑΜ|^\d\.\d{2}\.pdf$|Κώδικας-Μετανάστευσης", re.I)
KEEP_FILE = re.compile(r"eggr|egg\d|Εγκ[υύ]κλ|ΕΓΚΥΚΛ|Διευκριν|ΔΙΕΥΚΡΙΝ|Έγγραφο", re.I)

# ---- Diavgeia --------------------------------------------------------------------------
# organisation uid -> (label, first year, last year, needs keyword filter)
ORGS = {
    "100056663": ("Ministry of Migration and Asylum", 2020, None, False),
    "100025902": ("Ministry of Migration Policy", 2016, 2020, False),
    "100054489": ("Ministry of Citizen Protection", 2019, 2020, True),
    "100042756": ("Ministry of Citizen Protection", 2018, 2020, True),
    "100025896": ("Ministry of Interior", 2016, 2019, True),
    "100010874": ("Ministry of Interior and Administrative Reconstruction", 2015, 2017, True),
    "30": ("Ministry of Interior", 2010, 2017, True),
    "12": ("Ministry of Interior, Decentralisation and e-Government", 2010, 2012, True),
    "19": ("Ministry of Citizen Protection", 2010, 2013, True),
}
ACTIVE_ORGS = {"100056663"}
MIGRATION_WORDS = re.compile(
    r"αλλοδαπ|μεταν[αά]στ|τρίτων χωρών|τρίτης χώρας|[αά]δει\w* διαμονής|[αά]δεια\w* διαμονής|τίτλ\w+ διαμονής"
    r"|δελτί\w+ διαμονής|μετ[αά]κλ[ηή]σ|ν\.\s?3386|ν\.\s?4251|ν\.\s?5038|ν\.\s?3907|ν\.\s?4375|ν\.\s?4636|ν\.\s?4939"
    r"|π\.?δ\.?\s?106/2007|π\.?δ\.?\s?131/2006|άσυλ|ασύλου|διεθν\w+ προστασ|πρόσφυγ|προσφύγ|προσφυγικ"
    r"|ασυν[όο]δευτ|επαν[εέ]νωσ|επί μακρόν|μπλε κάρτα|υψηλής ειδίκευσης|εποχι\w+ εργα|αλιεργ[αά]τ|επενδυτ"
    r"|ψηφιακ\w+ νομ[αά]δ|ομογεν[ώε]|βεβα[ιί]ωσ\w+ νόμιμης διαμονής|απ[εέ]λασ|επιστροφ\w+ .{0,40}(υπηκόων|πολιτών)"
    r"|απομ[αά]κρυνσ|δουβλ[ιί]ν|υποδοχής και ταυτοποίησης|εξαιρετικούς λόγους|ανθρωπιστικούς λόγους|θεώρησ\w+ εισόδου"
    r"|ιθαγ[εέ]ν\w+ .{0,30}τρίτ|ανιθαγεν|ουκραν|προσωριν\w+ προστασ|brexit|ηνωμένου βασιλείου", re.I)
ADMIN_WORDS = re.compile(
    r"ιριδα|πολιτικών ασφαλείας|μισθώσεις ακινήτων|προμ[ηή]θει|προϋπολογισμ|δαπαν|μισθοδοσ|προσωπικού|υπαλλ[ηή]λ"
    r"|αξιολ[οό]γησ\w+ (του )?προσωπικ|μετατ[αά]ξ|αποσπ[αά]σ|προσλ[ηή]ψ|ωρ[αά]ρι|τηλεργασ|αδειών (του )?προσωπικ"
    r"|εκλογ(?!έ)|εκλογικ|δημοτολ[οό]γ|ληξιαρχ|μητρώο αρρένων|κληροδ[οό]τ|δημοτικ\w+ (αρχ|εκλογ)|περιφερειακ\w+ εκλογ"
    r"|ιθαγένεια(?!ς τρίτ)|κτήση\w* της ελληνικής ιθαγ|πολιτογρ[αά]φ|οικονομικ\w+ (διαχείριση|έτους)|απογραφ"
    r"|δημόσι\w+ συμβάσ|διαγωνισμ|ΕΣΠΑ|χρηματοδ[οό]τ|επιχορ[ηή]γ|κατανομή .{0,20}(πιστώσ|ποσ)|ΚΑΠ\b|φόρο|τέλ(ος|η) "
    r"|καταστατικ\w+ θέση|πειθαρχ|υπηρεσιακ\w+ συμβο[υύ]λ|σύμβαση\w* της χάγης|επισημείωσ|οργανωμένη απομάκρυνση"
    r"|στελέχωση|θερινού σχολείου|του ΚΕΙ\b", re.I)
ASYLUM_WORDS = re.compile(
    r"άσυλ|ασύλου|διεθν\w+ προστασ|πρόσφυγ|προσφύγ|προσφυγικ|ασυν[όο]δευτ|υποδοχής|δουβλ[ιί]ν|ΔΑΔΠ|\bΑΚΑ\b|\bΠΓΑ\b"
    r"|επιτροπε[ιί]|προσωριν\w+ προστασ|ν\.\s?4375|ν\.\s?4636|ν\.\s?4939|ν\.\s?5307|μετεγκατ[αά]στ|νομικής καθοδήγησης"
    r"|κράτηση πολιτών τρίτων", re.I)

blocked = {}          # host -> reason
robots_cache = {}     # host -> list of (allow, regex) for User-agent: *
last_hit = {}         # site -> time of last request
failures = []
stats = {"new": 0, "bytes": 0, "files": 0}
ia_refusals = [0]


# ---- polite fetching ---------------------------------------------------------------------

def site_of(host):
    return "archive.org" if host.endswith("archive.org") else host


def raw_get(url, timeout=120):
    host = urllib.parse.urlsplit(url).netloc
    site = site_of(host)
    wait = DELAY.get(host, DELAY["default"]) - (time.time() - last_hit.get(site, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), r.headers.get("Content-Type", ""), r.geturl()
    finally:
        last_hit[site] = time.time()


def robots_for(host):
    """Rules for 'User-agent: *' as [(allow, compiled regex)]; None if the host must not be used."""
    if host in robots_cache:
        return robots_cache[host]
    rules = []
    try:
        data, _, _ = raw_get(f"https://{host}/robots.txt", timeout=60)
        groups, agents, body_seen = [], [], False
        for line in data.decode("utf-8", "replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if body_seen:
                    agents, body_seen = [], False
                agents.append(val.lower())
            elif key in ("allow", "disallow"):
                body_seen = True
                if "*" in agents and val:
                    rx = re.escape(val).replace(r"\*", ".*")
                    rx = rx[:-2] + "$" if rx.endswith(r"\$") else rx
                    groups.append((key == "allow", re.compile(rx), len(val)))
        rules = groups
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            blocked[host] = f"HTTP {e.code} on robots.txt"
            print(f"  BLOCKED by {host} (HTTP {e.code} on robots.txt)")
            rules = None
        elif 400 <= e.code < 500:
            rules = []                      # no robots.txt: nothing is disallowed
        else:
            blocked[host] = f"robots.txt unreadable (HTTP {e.code})"
            rules = None
    except Exception as e:                  # noqa: BLE001
        blocked[host] = f"robots.txt unreadable ({e})"
        rules = None
    robots_cache[host] = rules
    return rules


def allowed(url):
    parts = urllib.parse.urlsplit(url)
    rules = robots_for(parts.netloc)
    if rules is None:
        return False
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    best = (True, -1)
    for allow, rx, n in rules:
        if rx.match(path) and (n > best[1] or (n == best[1] and allow)):
            best = (allow, n)
    return best[0]


def get(url, tries=2):
    """Return (bytes, content_type, final_url) or (None, reason, None)."""
    host = urllib.parse.urlsplit(url).netloc
    if host in blocked or site_of(host) in blocked:
        return None, "host blocked earlier in this run: " + blocked.get(host, blocked.get(site_of(host), "")), None
    if not allowed(url):
        return None, "robots.txt disallows this path", None
    if host in blocked:
        return None, blocked[host], None
    err = None
    for _ in range(tries):
        try:
            return raw_get(url)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code in (403, 429):
                blocked[host] = blocked[site_of(host)] = f"HTTP {e.code} on {url}"
                print(f"  BLOCKED by {host} (HTTP {e.code}); not asking this host again in this run")
                return None, err, None
            if e.code in (404, 410):
                break
        except Exception as e:              # noqa: BLE001 - report and retry once
            err = str(e)
        time.sleep(4)
    failures.append((url, err))
    return None, err, None


def quote_url(u):
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(urllib.parse.unquote(p.path), safe="/"),
                                              query=urllib.parse.quote(p.query, safe="=&%+")))


def text_of(markup):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def looks_ok(data, name):
    """Reject error pages and bot checks: the bytes must be what the extension says."""
    ext = name.rsplit(".", 1)[-1].lower()
    head = data[:2048].lstrip()
    if ext == "pdf":
        return data[:1024].find(b"%PDF-") >= 0 and len(data) > 800
    if ext in ("docx", "xlsx", "odt"):
        return data[:2] == b"PK"
    if ext in ("doc", "xls"):
        return data[:4] == b"\xd0\xcf\x11\xe0"
    if ext == "rtf":
        return head[:5] == b"{\\rtf"
    if ext == "html":
        low = data[:200000].lower()
        return b"<html" in low and b"captcha" not in low and len(data) > 5000
    return False


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    stats["new"] += 1
    stats["bytes"] += len(data)
    stats["files"] += 1


def budget_left():
    return stats["files"] < MAX_FILES and stats["bytes"] < MAX_BYTES


# ---- dates, numbers, names ---------------------------------------------------------------

def iso(d, m, y):
    d, m, y = int(d), int(m), int(y)
    if y < 100:
        y += 2000 if y < 50 else 1900
    if 1 <= d <= 31 and 1 <= m <= 12 and 1990 <= y <= 2100:
        return "%04d-%02d-%02d" % (y, m, d)
    return ""


def date_in(s):
    """First valid d.m.y date in s (same separator twice), as YYYY-MM-DD."""
    s = s or ""
    pos = 0
    while True:
        m = re.compile(r"(?<!\d)(\d{1,2})\s?([./-])\s?(\d{1,2})\s?\2\s?((?:19|20)\d\d|\d\d)(?!\d)").search(s, pos)
        if not m:
            return ""
        d = iso(m.group(1), m.group(3), m.group(4))
        if d:
            return d
        pos = m.start() + 1


def date_in_filename(name):
    d = date_in(name)
    if d:
        return d
    m = re.search(r"(?<!\d)(20[0-2]\d)[._-]?([01]\d)[._-]?([0-3]\d)(?!\d)", name)      # 20200218, 2024.10.25
    if m and iso(m.group(3), m.group(2), m.group(1)):
        return iso(m.group(3), m.group(2), m.group(1))
    m = re.search(r"(?<!\d)([0-3]\d)([01]\d)(20[0-2]\d)(?!\d)", name)                  # 10022016
    if m and iso(*m.groups()):
        return iso(*m.groups())
    m = re.search(r"(?<!\d)([0-3]\d)([01]\d)(\d\d)(?!\d)", name)                        # 290915
    if m and iso(*m.groups()):
        return iso(*m.groups())
    m = re.search(r"[._](20[0-2]\d|19\d\d)\.pdf$", name)                                 # Α.Π.-78128.2018.pdf
    return m.group(1) if m else ""


def clean_name(s, n=90):
    s = re.sub(r"[\\/:*?\"<>|\x00-\x1f\s]+", "-", s).strip("-.")
    stem, dot, ext = s.rpartition(".")
    if dot and len(ext) <= 5:
        return stem[:n].rstrip("-.") + "." + ext.lower()
    return s[:n]


def first_number(s):
    m = re.search(r"\d{2,}", s or "")
    return m.group(0) if m else ""


# ---- ministry site -----------------------------------------------------------------------

def content_of(markup):
    i = markup.find('id="content"')
    j = markup.find("<footer", i)
    body = markup[i if i > 0 else 0: j if j > 0 else len(markup)]
    return re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)


def rows_with_links(body):
    """Yield (url, label, cells, cell_index) for every link; cells is the table row it sits in, or []."""
    for m in re.finditer(r'<a\s[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.S):
        url, label = html.unescape(m.group(1)).strip(), text_of(m.group(2))
        a = body.rfind("<tr", 0, m.start())
        closed = body.rfind("</tr>", 0, m.start())
        cells, idx = [], 0
        if a >= 0 and closed < a:
            b = body.find("</tr>", m.end())
            row = body[a: b if b > 0 else m.end()]
            off = m.start() - a
            pos = 0
            for i, c in enumerate(re.split(r"</td>", row)):
                if pos <= off < pos + len(c) + 5:
                    idx = i
                pos += len(c) + 5
                cells.append(text_of(c))
            cells = cells[:-1] if cells and not cells[-1] else cells
        # the link's own text: from the link to the next link in the same cell (cells can hold several circulars)
        end = body.find("</td>", m.end())
        nxt = body.find("<a ", m.end())
        stop = min(x for x in (end, nxt, m.end() + 3000) if x > 0)
        own = text_of(body[m.start():stop]) if cells else label
        yield url, label, cells, idx, own


def ministry_items(markup, page_url, folder, mode):
    items = []
    for url, label, cells, idx, own in rows_with_links(content_of(markup)):
        url = urllib.parse.urljoin(page_url, url)
        p = urllib.parse.urlsplit(url)
        fname = urllib.parse.unquote(p.path.rsplit("/", 1)[-1])
        if p.netloc != "migration.gov.gr" or "/wp-content/uploads/" not in p.path or not DOC_EXT.search(fname):
            continue
        if mode == "guidance":
            if (STATUTE_LABEL.search(own) or STATUTE_FILE.search(fname)) and not KEEP_FILE.search(fname):
                continue
        elif mode == "circ":
            if not re.search(r"Εγκ[υύ]κλ|ΕΓΚΥΚΛ", own + " " + fname):
                continue
        elif mode.startswith("pick:"):
            if not re.search(mode[5:], label + " " + fname, re.I):
                continue
        # date: a separate date cell, else the start of the link's own cell, else the file name
        date = ""
        for i, c in enumerate(cells):
            if i != idx and len(c) < 40 and date_in(c):
                date = date_in(c)
                break
        if not date:
            date = date_in(own[:len(label) + 30]) or date_in_filename(fname)
        # number: a separate numeric cell, else "Εγκύκλιος N/..." or "Αρ. Πρωτ. N", else the file name
        number = ""
        for i, c in enumerate(cells):
            if i != idx and re.fullmatch(r"(οικ\.?\s*)?\d{2,7}(\s*/\s*\d+)?", c.strip()):
                number = first_number(c)
                break
        if not number:
            m = re.search(r"Εγκύκλιος\s+(?:αρ\.?\s*)?(\d+)\s*[/–-]\s*\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", own)
            if m:
                number = ("egk" + m.group(1)) if int(m.group(1)) < 100 else m.group(1)
            else:
                m = (re.search(r"Πρωτ\.?:?\s*(?:οικ\.?\s*)?(\d{2,})", own)
                     or re.search(r"(?:Α\.?Π\.?|AΠ|ΑΠ|eggr?)[-_ .]?(\d{2,})", fname)
                     or re.search(r"(?:Εγκύκλιος|ΕΓΚΥΚΛΙΟΣ)[-_ ](\d{3,})", fname))
                number = m.group(1) if m else ""
        title = own if len(own) > len(label) else label
        if len(title.strip(" |")) < 6 and cells:
            title = " ".join(cells)
        if len(title.strip(" |")) < 6:
            title = fname
        title = title[:400]
        ada = re.search(r"(?<![0-9Α-ΩA-Z])([0-9Α-Ω]{4,5}46ΜΔΨΟ-[0-9Α-Ω]{3}|[0-9Α-Ω]{4}465ΧΘΕ-[0-9Α-Ω]{3})", fname)
        items.append({"folder": folder, "title": title.strip(), "date": date, "number": number, "weak": len(label) < 12,
                      "url": url, "page": page_url, "ada": ada.group(1) if ada else "", "origin": "migration.gov.gr",
                      "name": "_".join(x for x in (date or "nodate", number, clean_name(fname)) if x)})
    return items


def circular_list_items(markup):
    """Entries of the ministry's 'Εγκύκλιοι' pages: [(ada, title, date)]."""
    body = content_of(markup)
    out = []
    for m in re.finditer(r'<a\s[^>]*?href="https?://diavgeia\.gov\.gr/doc/([^"]+)"[^>]*>(.*?)</a>(?=(.{0,400}))', body, flags=re.S):
        ada = urllib.parse.unquote(html.unescape(m.group(1))).strip()
        out.append((ada, text_of(m.group(2)).strip('" '), date_in(text_of(m.group(3)))))
    return out


# ---- Diavgeia listing (metadata only) ------------------------------------------------------

def diavgeia_search(org, a, b):
    found, page = [], 0
    while True:
        q = urllib.parse.urlencode({"org": org, "type": "Α.3", "size": 500, "page": page,
                                    "from_issue_date": a, "to_issue_date": b})
        data, why, _ = get(f"{DIAVGEIA}/opendata/search.json?{q}")
        if data is None:
            print(f"  Diavgeia listing failed for org {org} {a}..{b}: {why}")
            return None
        d = json.loads(data)
        for x in d.get("decisions", []):
            found.append({"ada": x["ada"], "subject": (x.get("subject") or "").strip(),
                          "date": datetime.datetime.fromtimestamp(x["issueDate"] / 1000, datetime.timezone.utc)
                          .astimezone(datetime.timezone(datetime.timedelta(hours=3))).date().isoformat()
                          if x.get("issueDate") else "",
                          "protocol": x.get("protocolNumber") or "", "org": org})
        page += 1
        if page * 500 >= d.get("info", {}).get("total", 0):
            return found


def diavgeia_listing(refresh):
    """All type-A.3 decisions of the ministries in ORGS. Closed ministries are listed once and cached."""
    cache_file = OUT / "diavgeia-listing.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    this_year = datetime.date.today().year
    for org, (label, y0, y1, _) in ORGS.items():
        if org in cache and org not in ACTIVE_ORGS and not refresh:
            continue
        print(f"Diavgeia: listing circulars of {label} (uid {org})")
        rows, ok = {}, True
        for y in range(y0, (y1 or this_year) + 1):
            # the API returns at most 180 days per query
            for a, b in ((f"{y}-01-01", f"{y}-06-29"), (f"{y}-06-30", f"{y}-12-26"), (f"{y}-12-27", f"{y}-12-31")):
                if a > TODAY:
                    continue
                got = diavgeia_search(org, a, b)
                if got is None:
                    ok = False
                    break
                for r in got:
                    rows[r["ada"]] = r
            if not ok:
                break
        if ok:
            cache[org] = sorted(rows.values(), key=lambda r: (r["date"], r["ada"]))
            OUT.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
        elif org in ACTIVE_ORGS and org in cache:
            print("  using the listing saved by an earlier run")
    return cache


def diavgeia_items(cache, ministry_list):
    """Circulars to look for: the ministry's own list plus keyword-filtered API results."""
    listed = {ada: (title, date) for ada, title, date in ministry_list}
    items, seen = [], set()
    for org, rows in cache.items():
        label, _, _, need_kw = ORGS.get(org, (org, 0, 0, True))
        for r in rows:
            subj = r["subject"]
            if r["ada"] in seen:
                continue
            if need_kw and not MIGRATION_WORDS.search(subj):
                continue
            if ADMIN_WORDS.search(subj) and not (MIGRATION_WORDS.search(subj) and r["ada"] in listed and
                                                 not re.search(r"ιριδα|πολιτικών ασφαλείας|μισθώσεις", subj, re.I)):
                continue
            seen.add(r["ada"])
            items.append(dict(r, issuer=label))
    for ada, (title, date) in listed.items():           # anything the API listing missed
        if ada not in seen and not re.search(r"ιριδα|πολιτικών ασφαλείας|μισθώσεις", title, re.I):
            known = any(ada == r["ada"] for rows in cache.values() for r in rows)
            if not known:
                items.append({"ada": ada, "subject": title, "date": date, "protocol": "", "org": "100056663",
                              "issuer": ORGS["100056663"][0]})
    out = []
    for r in items:
        folder = "asylum" if ASYLUM_WORDS.search(r["subject"]) else "residence"
        number = first_number(r["protocol"])
        out.append({"folder": folder, "title": r["subject"], "date": r["date"], "number": number,
                    "protocol": r["protocol"], "ada": r["ada"], "issuer": r["issuer"],
                    "url": f"{DIAVGEIA}/doc/{r['ada']}", "page": f"{DIAVGEIA}/decision/view/{r['ada']}",
                    "origin": "diavgeia.gov.gr via web.archive.org",
                    "name": "_".join(x for x in (r["date"] or "nodate", number, "ADA-" + r["ada"]) if x) + ".pdf"})
    return out


# ---- Wayback Machine -----------------------------------------------------------------------

def wayback_fetch(item):
    """Return (bytes, snapshot_url) or (None, reason)."""
    if ia_refusals[0] >= 3:
        return None, "Internet Archive refused three times; not asked further in this run"
    target = quote_url(item["url"])
    data, why, _ = get("https://archive.org/wayback/available?url=" + urllib.parse.quote(target, safe=""), tries=1)
    if data is None:
        ia_refusals[0] += 1
        return None, "Wayback availability lookup failed: " + str(why)
    try:
        snap = json.loads(data).get("archived_snapshots", {}).get("closest") or {}
    except ValueError:
        ia_refusals[0] += 1
        return None, "Wayback availability lookup returned no JSON"
    if not snap.get("available") or snap.get("status") != "200":
        ia_refusals[0] = 0
        return None, "no Wayback copy"
    raw = f"https://web.archive.org/web/{snap['timestamp']}id_/{target}"
    data, why, _ = get(raw, tries=1)
    if data is None:
        ia_refusals[0] += 1
        return None, "Wayback copy could not be fetched: " + str(why)
    ia_refusals[0] = 0
    if not looks_ok(data, "x.pdf"):
        return None, "Wayback copy is not a PDF"
    return data, f"https://web.archive.org/web/{snap['timestamp']}/{item['url']}"


# ---- main ----------------------------------------------------------------------------------

def read_tsv(path):
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:] if ln.strip()]


def tsv(v):
    return re.sub(r"[\t\r\n]+", " ", str(v or "")).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--no-wayback", action="store_true", help="do not ask the Wayback Machine")
    ap.add_argument("--recheck", action="store_true", help="ask the Wayback Machine again for items it lacked before")
    ap.add_argument("--refresh-diavgeia", action="store_true", help="re-list closed ministries on Diavgeia as well")
    ap.add_argument("--max-wayback", type=int, default=600, help="Wayback lookups per run (default 600)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".pdf", ".doc", ".docx", ".html", ".xls", ".xlsx", ".rtf", ".odt"):
            stats["files"] += 1
            stats["bytes"] += f.stat().st_size
    old_index = {r.get("file", ""): r for r in read_tsv(OUT / "index.tsv")}
    old_missing = {r.get("save_as", ""): r for r in read_tsv(OUT / "not-obtained.tsv")}

    index, missing, done_urls, by_url = [], [], {}, {}

    def record(item, rel, fetched_from=""):
        index.append({"file": rel, "title": item["title"], "date": item["date"], "source_url": item["url"],
                      "protocol": item.get("protocol") or item.get("number", "").replace("egk", "Εγκύκλιος "),
                      "ada": item.get("ada", ""), "category": item["folder"],
                      "issuer": item.get("issuer", "Ministry of Migration and Asylum (as published on migration.gov.gr)"),
                      "listed_on": item.get("page", ""),
                      "fetched_from": fetched_from or old_index.get(rel, {}).get("fetched_from", "") or item["url"]})

    def miss(item, rel, reason):
        missing.append({"title": item["title"], "date": item["date"], "protocol": item.get("protocol") or item.get("number", ""),
                        "ada": item.get("ada", ""), "source_url": item["url"], "open_in_browser": item.get("page") or item["url"],
                        "reason": reason, "save_as": rel, "checked": TODAY})

    # 1. ministry pages
    print("migration.gov.gr: reading listing pages")
    ministry_list, local_adas = [], set()
    for path, folder, mode in PAGES:
        url = SITE + path
        if mode == "page":
            rel = f"{folder}/nodate_{path.strip('/').replace('/', '_')}.html"
            item = {"folder": folder, "title": "", "date": "", "url": url, "page": url, "number": ""}
            if (OUT / rel).exists():
                markup = (OUT / rel).read_text(encoding="utf-8", errors="replace")
            else:
                data, why, _ = get(url)
                if data is None or not looks_ok(data, "x.html"):
                    item["title"] = path
                    miss(item, rel, "page not fetched: " + str(why or "not an HTML page"))
                    continue
                save(OUT / rel, data)
                print("  saved", rel)
                markup = data.decode("utf-8", "replace")
            t = re.search(r"<title>(.*?)</title>", markup, re.S)
            item["title"] = (text_of(t.group(1)).split("|")[0].strip() if t else path) + \
                " (web page: summaries of the standard operating procedures in force; the procedures themselves are not published)"
            record(item, rel)
            continue
        data, why, _ = get(url)
        if data is None:
            print(f"  could not read {url}: {why}")
            continue
        for item in ministry_items(data.decode("utf-8", "replace"), url, folder, mode):
            if item["url"] in done_urls:
                first = by_url.get(item["url"])
                if first and first.get("weak") and not item["weak"]:      # a later page names it properly
                    first.update(title=item["title"], date=first["date"] or item["date"], weak=False)
                    for r in index:
                        if r["source_url"] == item["url"]:
                            r["title"], r["date"] = first["title"], first["date"]
                continue
            by_url[item["url"]] = item
            rel = f"{item['folder']}/{item['name']}"
            n = 2
            while rel in done_urls.values():                 # same name from two different addresses
                stem, ext = item["name"].rsplit(".", 1)
                rel = f"{item['folder']}/{stem}-{n}.{ext}"
                n += 1
            done_urls[item["url"]] = rel
            if item["ada"]:
                local_adas.add(item["ada"])
            if (OUT / rel).exists():
                record(item, rel)
                continue
            if not budget_left():
                miss(item, rel, "size or file cap reached")
                continue
            body, why, _ = get(quote_url(item["url"]))
            if body is None:
                miss(item, rel, "not fetched: " + str(why))
            elif not looks_ok(body, rel):
                miss(item, rel, "server did not return the document (wrong file type)")
            else:
                save(OUT / rel, body)
                record(item, rel)
                print("  saved", rel)
    for path in CIRCULAR_LISTS:
        data, why, _ = get(SITE + path)
        if data is None:
            print(f"  could not read {SITE + path}: {why}")
            continue
        for e in circular_list_items(data.decode("utf-8", "replace")):
            if e[0] not in [x[0] for x in ministry_list]:
                ministry_list.append(e)
    print(f"  the ministry's circular lists name {len(ministry_list)} Diavgeia documents")

    # 2. Diavgeia listing, 3. Wayback copies
    cache = diavgeia_listing(args.refresh_diavgeia)
    items = diavgeia_items(cache, ministry_list)
    print(f"Diavgeia: {len(items)} circulars on immigration and asylum listed")
    lookups = 0
    for item in sorted(items, key=lambda r: r["date"], reverse=True):
        rel = f"{item['folder']}/{item['name']}"
        other = f"{'residence' if item['folder'] == 'asylum' else 'asylum'}/{item['name']}"
        if (OUT / other).exists() and not (OUT / rel).exists():
            rel = other
        if (OUT / rel).exists():
            record(item, rel)
            continue
        if item["ada"] in local_adas:
            continue                                         # the ministry site has this very document
        robots_reason = "diavgeia.gov.gr robots.txt disallows /doc/* (the document address)"
        prev = old_missing.get(rel, {})
        if args.no_wayback:
            miss(item, rel, prev.get("reason") or robots_reason + "; Wayback Machine not asked")
        elif "no Wayback copy" in prev.get("reason", "") and not args.recheck:
            missing.append(dict(prev))
        elif lookups >= args.max_wayback or not budget_left():
            miss(item, rel, robots_reason + "; Wayback Machine not asked (per-run limit)")
        else:
            lookups += 1
            body, info = wayback_fetch(item)
            if body is None:
                miss(item, rel, robots_reason + "; " + info)
            else:
                save(OUT / rel, body)
                record(item, rel, info)
                print("  saved", rel, "(Wayback)")

    # 4. files added by hand (anything on disk that no listing accounts for)
    known = {r["file"] for r in index}
    for f in sorted(OUT.rglob("*")):
        rel = f.relative_to(OUT).as_posix()
        if f.is_file() and f.suffix.lower() in (".pdf", ".doc", ".docx", ".html") and rel not in known:
            o = old_index.get(rel, {})
            index.append({"file": rel, "title": o.get("title", ""), "date": o.get("date", "") or date_in_filename(f.name)[:10],
                          "source_url": o.get("source_url", ""), "protocol": o.get("protocol", ""), "ada": o.get("ada", ""),
                          "category": rel.split("/")[0] if "/" in rel else "", "issuer": o.get("issuer", ""),
                          "listed_on": o.get("listed_on", ""), "fetched_from": o.get("fetched_from", "added by hand")})

    cols = ["file", "title", "date", "source_url", "protocol", "ada", "category", "issuer", "listed_on", "fetched_from"]
    index.sort(key=lambda r: (r["category"], r["date"] or "0", r["file"]))
    with open(OUT / "index.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in index:
            fh.write("\t".join(tsv(r.get(c)) for c in cols) + "\n")
    mcols = ["title", "date", "protocol", "ada", "source_url", "open_in_browser", "reason", "save_as", "checked"]
    missing = [m for m in missing if not (OUT / m["save_as"]).exists()]
    missing.sort(key=lambda r: (r["date"] or "0"), reverse=True)
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(mcols) + "\n")
        for r in missing:
            fh.write("\t".join(tsv(r.get(c)) for c in mcols) + "\n")

    print(f"\n{stats['new']} new files this run; {len(index)} files indexed ({stats['bytes'] / 1e6:.0f} MB on disk); "
          f"{len(missing)} listed but not obtained (see gr/not-obtained.tsv)")
    for host, why in blocked.items():
        print(f"  blocked: {host}: {why}")
    for url, err in failures[:20]:
        print(f"  failed: {url}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

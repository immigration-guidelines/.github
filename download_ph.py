#!/usr/bin/env python3
"""Philippines: issuances of the Bureau of Immigration (BI) and related Department of Justice,
DOLE, DFA and PRA issuances that tell immigration officers how to decide cases.

    python3 download_ph.py                # all sources
    python3 download_ph.py naro archive   # only the named sources

Sources (see ph/NOTES.txt for what was checked and what is missing):

  naro     naro.law.upd.edu.ph  National Administrative Register Online (UP Law Center, Office of
           the National Administrative Register). Every BI issuance filed with ONAR (listing
           /agencies/bureau-of-immigration), minus purely organisational ones (EXCLUDE), plus a few
           issuances of other agencies (EXTRA). Each record page /issuances/<n> links the filed copy
           at /storage/<id>.pdf.
  onar     law.upd.edu.ph  the older ONAR issuance page: BI rules implementing EO 122 (advance
           passenger information).
  archive  web.archive.org  Internet Archive copies of Department of Justice circulars on visas,
           immigration appeals and refugee/stateless status determination. www.doj.gov.ph itself
           answers with a Cloudflare challenge and is not contacted.

immigration.gov.ph is not contacted and not taken from the Internet Archive either (see NOTES.txt).

Rules: robots.txt is read for each host and obeyed; one request at a time, 1.5 s apart (4 s for the
Internet Archive); a host that answers 403 or 429, or fails three times in a row, is not asked again
in that run. Files that exist are skipped; ph/index.tsv and ph/not-obtained.tsv are rebuilt on every
run. Standard library only.
"""
import datetime
import html
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ph"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"

NARO = "https://naro.law.upd.edu.ph"
BI_LIST = NARO + "/agencies/bureau-of-immigration?page={}"
BI = "Bureau of Immigration"

# BI issuances that only set up or rename units, or deal with HR, procurement or records keeping
EXCLUDE = {
    "7680": "HR development division",
    "7319": "document classification slip (records management)",
    "5559": "procurement unit reorganisation",
    "5558": "transfer of the INTERPOL unit",
    "3014": "transmission of records to the Records Section",
    "3161": "membership of the EXPATS steering committee",
    "2783": "Board of Commissioners agenda and records units (DOJ circular filed under BI)",
    "2605": "quality management unit",
    "2080": "reorganisation of the Alien Registration Division",
    "1668": "renaming of the APECO field office",
    "602": "communication and media relations unit",
    "2428": "reorganisation of the Port Operations Division",
    "1244": "planning division's review of operations manuals",
}
# BI issuances that are amending rules of procedure rather than instructions
PROCEDURAL = {"3788"}
# Register dates that are evidently mistyped (issue date after filing or decades early): use filing date
DATE_FROM_FILED = {"7681", "3788"}

# issuances of other agencies: id -> (agency label, issuer, kind)
EXTRA = {
    "374": ("DOJ", "Department of Justice", "guidance"),
    "7205": ("DOLE", "Department of Labor and Employment", "procedural act"),
    "6049": ("DFA", "Department of Foreign Affairs", "guidance"),
    "6222": ("PRA", "Philippine Retirement Authority", "guidance"),
    "3553": ("PRA", "Philippine Retirement Authority", "guidance"),
}

ONAR = [
    ("onar/2021-01-28_BI-Rules-implementing-EO-122-Advance-Passenger-Information-System.pdf",
     "BI Rules and Regulations to Implement Executive Order No. 122 Otherwise Known as \"Strengthening "
     "Border Control Through the Adoption and Implementation of the Advance Passenger Information System\"",
     "2021-01-28", "https://law.upd.edu.ph/wp-content/uploads/2021/05/BI-IRR-EO-No-122.pdf",
     "procedural act", BI, "", "filed with ONAR 2021-01-28 (date of the ONAR listing)"),
]

WB = "https://web.archive.org/web/{}id_/{}"
DOJ = "Department of Justice"
ARCHIVE = [
    ("doj-archive/2017-08-15_DOJ-DC-041-s2017_Visa-upon-arrival-PROC-nationals.pdf",
     "Department Circular No. 041, s. 2017 - Granting Visa Upon Arrival to PROC Nationals",
     "2017-08-15", WB.format("20211229122452", "https://doj.gov.ph/files/2017/DCs/DC2017AUG041%20Granting%20Visa%20Upon%20Arrival%20to%20PROC%20Nationals%20dtd%2015%20Aug%202017.pdf"),
     "guidance", DOJ, "DC 041 s.2017", ""),
    ("doj-archive/2018-06-27_DOJ-DC-026-s2018_Guidelines-on-Special-Non-Immigrant-Visas.pdf",
     "Department Circular No. 026, s. 2018 - Guidelines on Special Non-Immigrant Visas",
     "2018-06-27", WB.format("20210919012416", "https://www.doj.gov.ph/files/2018/DC/DC026-2018JUN%20Guidelines%20on%20Special%20Non-Immigrant%20Visas%20dtd%2027%20Jun%202018.pdf"),
     "guidance", DOJ, "DC 026 s.2018", ""),
    ("doj-archive/2019-05-08_DOJ-DC-009-s2019_Granting-visa-to-Chinese-nationals.pdf",
     "Department Circular No. 009, s. 2019 - Granting Visa to Chinese Nationals",
     "2019-05-08", WB.format("20210919025628", "https://www.doj.gov.ph/files/2019/DCs/DC009-2019MAY%20Granting%20Visa%20to%20Chinese%20Nationals%20dtd%2008%20May%202019.pdf"),
     "guidance", DOJ, "DC 009 s.2019", ""),
    ("doj-archive/2019-10-09_DOJ-DC-023-s2019_Omnibus-Rules-on-Appeals-in-Immigration-Matters.pdf",
     "Department Circular No. 023, s. 2019 - Omnibus Rules and Regulations on Appeals to the Department of "
     "Justice on Immigration and Immigration-Related Matters, and for Other Purposes",
     "2019-10-09", WB.format("20211229122428", "https://doj.gov.ph/files/2019/DCs/DC%20023%20-%20Omnibus%20Rules%20and%20Regulations%20on%20Appeals%20to%20the%20Department%20of%20Justice%20on%20Immigration%20and%20Immigration-Related%20Matters%2C%20and%20for%20Other%20Purposes.pdf"),
     "procedural act", DOJ, "DC 023 s.2019", ""),
    ("doj-archive/2020-01-08_DOJ-DC-001-s2020_Amending-DC-041-visa-for-Chinese-nationals.pdf",
     "Department Circular No. 001, s. 2020 - Amending DC No. 041 re Visa Granted to Chinese Nationals",
     "2020-01-08", WB.format("20211229122532", "https://doj.gov.ph/files/2020/DC/DC001-2020JAN%20Amending%20DC%20No%20041%20re%20visa%20Granted%20to%20Chinese%20Nationals%20dtd%2008%20Jan%202020.pdf"),
     "guidance", DOJ, "DC 001 s.2020", ""),
    ("doj-archive/2020-03-13_DOJ-DC-011-s2020_Suspension-of-special-non-immigrant-visa-and-refugee-applications.pdf",
     "Department Circular No. 011, s. 2020 - Suspension of Receipt of Applications for Special Non-Immigrant "
     "Visas under Section 47(a)(2) of the Philippine Immigration Act of 1940, as amended, and Applications for "
     "Recognition of Refugee Status and Statelessness",
     "2020-03-13", WB.format("20200908174208", "https://www.doj.gov.ph/files/2020/DC/DC011-2020MARCH%20Suspension%20of%20receipt%20of%20Application%20for%20Special%20Non-Immigration%20under%20Section%2047(a)(2)%20of%20the%20Philippine%20Immigration%20Act%20of%201940.pdf"),
     "guidance", DOJ, "DC 011 s.2020", ""),
    ("doj-archive/2021_DOJ-Guidelines-processing-special-non-immigrant-visas-IATF-131-A.pdf",
     "Guidelines for the Processing of Applications for the Issuance of Special Non-Immigrant Visas "
     "(Pursuant to IATF Resolution No. 131-A, series of 2021)",
     "2021", WB.format("20210827195355", "https://www.doj.gov.ph/files/2021/Issuances/GUIDELINES%20FOR%20THE%20PROCESSING%20OF%20APPLICATIONS%20FOR%20THE%20ISSUANCE%20OF%20SPECIAL%20NON-IMMIGRANT%20VISAS%20(Pursuant%20to%20IATF%20Resolution%20No.%20131-A%2C%20series%20of%202021).pdf"),
     "guidance", DOJ, "", ""),
    ("doj-archive/2022-06-28_DOJ-DC-024-s2022_Refugee-and-stateless-status-determination-rules.pdf",
     "Department Circular No. 024, s. 2022 - Strengthening the Refugees and Stateless Persons Protection Unit, "
     "Enhancing the Rules for Refugee and Stateless Status Determination, and for Other Purposes",
     "2022-06-28", WB.format("20231025081419", "https://doj.gov.ph/files/2022/DC/DC%20024.pdf"),
     "procedural act", DOJ, "DC 024 s.2022", ""),
]

# English documents: title_en repeats the title.
NOT_OBTAINED = [
    ("DFA Department Order No. 2022-020 - Issuance of 9(e) Foreign Government Official's Visa", "2022-12-27",
     NARO + "/issuances/28",
     "the ONAR record (registration 23-0020) has no electronic copy attached; official copy only on request from ONAR"),
    ("BI 2015 Omnibus Rules of Procedure (as amended before 2024)", "2015",
     "https://immigration.gov.ph/",
     "immigration.gov.ph resets the TLS connection (robots.txt included); its archived robots.txt disallows "
     "GPTBot, CCBot and Google-Extended, taken as applying to this collector, so the Internet Archive copy "
     "was not used either. Only the 2024 amendment (Operations Order 2024-002) is in the folder, from ONAR"),
    ("BI Immigration Memorandum Circulars, Operations Orders and Administrative Circulars of the SBM-2014, "
     "SBM-2015 and later pre-2023 series (e.g. SBM-2015-007 student visas, SBM-2015-010 indigent aliens, "
     "SBM-2014-001 blacklist)", "2014-2022", "https://immigration.gov.ph/",
     "issued before ONAR's online register begins (October 2022); immigration.gov.ph not usable (TLS resets; "
     "robots.txt excludes AI crawlers, archive copy not used)"),
    ("BI Citizen's Charter (staff procedures per service)", "", "https://immigration.gov.ph/",
     "immigration.gov.ph not usable (TLS resets; robots.txt excludes AI crawlers, archive copy not used)"),
    ("BI issuances not filed with ONAR and BI issuances after March 2025", "", NARO + "/agencies/bureau-of-immigration",
     "the register lists nothing later than 2025-04 for BI; the Bureau's own site is not usable"),
    ("DOJ Department Circulars, Orders and legal opinions on immigration other than those in doj-archive/ "
     "(e.g. DC 058 s.2012 on refugee and stateless status determination, superseded)", "",
     "https://www.doj.gov.ph/department-circulars.html",
     "www.doj.gov.ph answers with a Cloudflare JavaScript challenge; only the files listed in the Internet "
     "Archive index were taken"),
    ("IACAT Revised Guidelines on Departure Formalities for International-Bound Philippine Passengers (2023) "
     "and earlier departure guidelines", "2023", "https://iacat.gov.ph/",
     "iacat.gov.ph answers with a Cloudflare challenge / HTTP 403; not in the Internet Archive index of iacat.gov.ph "
     "PDFs; not filed in ONAR's online register"),
    ("DOLE Alien Employment Permit rules before DO 248-25 (DO 186-17 and others)", "2017",
     "https://www.dole.gov.ph/issuances/", "www.dole.gov.ph answers with a Cloudflare challenge"),
    ("Official Gazette copies of BI and DOJ issuances", "", "https://www.officialgazette.gov.ph/",
     "officialgazette.gov.ph answers with a Cloudflare challenge / HTTP 403"),
    ("Supreme Court e-Library copies of administrative issuances", "", "https://elibrary.judiciary.gov.ph/",
     "elibrary.judiciary.gov.ph answers HTTP 403"),
]

GLOSS_FALLBACK = None  # all sources here are in English


class Host:
    def __init__(self, base, delay):
        self.base, self.delay, self.last, self.fails, self.closed = base, delay, 0.0, 0, None
        self.disallow = None

    def robots(self):
        if self.disallow is not None:
            return
        self.disallow = []
        try:
            body = self._get(self.base + "/robots.txt", robots=True).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                self.closed = "robots.txt answered HTTP %d" % e.code
            return
        except Exception as e:  # unreachable robots.txt: treat as closed
            self.closed = "robots.txt unreachable: %s" % e
            return
        groups, agents, rules, in_rules = [], [], [], False
        for line in body.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if in_rules:
                    groups.append((agents, rules))
                    agents, rules, in_rules = [], [], False
                agents.append(v.lower())
            elif k in ("allow", "disallow"):
                in_rules = True
                rules.append((k, v))
        groups.append((agents, rules))
        mine = ("*", "claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot")
        for ag, rl in groups:
            if any(a in mine for a in ag):
                self.disallow += [v for k, v in rl if k == "disallow" and v]

    def allowed(self, url):
        path = urllib.parse.urlsplit(url).path or "/"
        for rule in self.disallow or []:
            pat = re.escape(rule).replace(r"\*", ".*")
            if pat.endswith(r"\$"):
                pat = pat[:-2] + "$"
            if re.match(pat, path):
                return False
        return True

    def _get(self, url, robots=False):
        wait = self.last + self.delay - time.time()
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()

    def get(self, url):
        if self.closed:
            raise RuntimeError("host closed: " + self.closed)
        self.robots()
        if self.closed:
            raise RuntimeError("host closed: " + self.closed)
        if not self.allowed(url):
            raise RuntimeError("disallowed by robots.txt")
        try:
            data = self._get(url)
            self.fails = 0
            return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                self.closed = "HTTP %d on %s" % (e.code, url)
            else:
                self.fails += 1
            raise
        except Exception:
            self.fails += 1
            if self.fails >= 3:
                self.closed = "three failures in a row"
            raise


def is_pdf(path):
    if path.read_bytes()[:5] != b"%PDF-":
        return False
    r = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True)
    return r.returncode == 0 and "Pages:" in r.stdout


def save(host, url, rel, problems):
    dest = OUT / rel
    if dest.exists():
        return True
    try:
        data = host.get(url)
    except Exception as e:
        problems.append((rel, url, str(e)))
        print("  FAIL", rel, e)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    if not is_pdf(tmp) or len(data) == 1048576:
        tmp.unlink()
        problems.append((rel, url, "not a complete PDF (%d bytes)" % len(data)))
        print("  BAD ", rel)
        return False
    tmp.rename(dest)
    print("  got ", rel, len(data))
    return True


def text(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", s))
    return [x.strip() for x in t.splitlines() if x.strip()]


def slug(s, n=90):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s[:n].rstrip("-")


def parse_record(page):
    main = page.split("Related issuances")[0]
    flat = lambda m: re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip() if m else ""
    number = flat(re.search(r'<span[^>]*aria-current="page"[^>]*>(.*?)</span>', main, re.S))
    number = re.sub(r"(\d)- (\d)", r"\1-\2", re.sub(r"(\d) -(\d)", r"\1-\2", number))
    title = flat(re.search(r"<h1[^>]*>(.*?)</h1>", main, re.S))
    dl = {flat(re.match(r"(.*)", k, re.S)): flat(re.match(r"(.*)", v, re.S))
          for k, v in re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", main, re.S)}
    pdf = re.search(r'https://naro\.law\.upd\.edu\.ph/storage/[A-Za-z0-9]+\.pdf', main)
    return dict(title=title, number=number, issued=dl.get("Date issued", ""), filed=dl.get("Date filed", ""),
                reg=dl.get("Registration number", ""), pdf=pdf.group(0) if pdf else "")


def valid(d):
    try:
        return datetime.date.fromisoformat(d)
    except ValueError:
        return None


def pick_date(rid, issued, filed):
    i, f = valid(issued), valid(filed)
    if rid in DATE_FROM_FILED or not i:
        return filed if f else ""
    if f and (i > f or (f - i).days > 400):
        return filed
    return issued


def run_naro(rows, problems):
    host = Host(NARO, 1.5)
    ids = []
    for p in range(1, 15):
        try:
            page = host.get(BI_LIST.format(p)).decode("utf-8", "replace")
        except Exception as e:
            problems.append(("listing page %d" % p, BI_LIST.format(p), str(e)))
            break
        arts = re.findall(r'<article class="group.*?</article>', page, re.S)
        found = [m for a in arts for m in re.findall(r'href="https://naro\.law\.upd\.edu\.ph/issuances/(\d+)"', a)[:1]]
        new = [x for x in dict.fromkeys(found) if x not in ids]
        if not new:
            break
        ids += new
        if "page=%d" % (p + 1) not in page:
            break
    print("naro: %d BI records listed" % len(ids))
    wanted = [(i, "BI", BI, "procedural act" if i in PROCEDURAL else "guidance") for i in ids if i not in EXCLUDE]
    wanted += [(i,) + v for i, v in EXTRA.items()]
    used = set()
    for rid, label, issuer, kind in wanted:
        url = NARO + "/issuances/" + rid
        try:
            rec = parse_record(host.get(url).decode("utf-8", "replace"))
        except Exception as e:
            problems.append(("record " + rid, url, str(e)))
            continue
        if not rec["pdf"]:
            problems.append(("ONAR record %s: %s - %s" % (rid, rec["number"], rec["title"]), url,
                             "no electronic copy attached to the ONAR record (the page says so); official copy only on request from ONAR"))
            continue
        date = pick_date(rid, rec["issued"], rec["filed"])
        num = re.sub(r"\bNo\.?\s*", "", rec["number"], flags=re.I)
        name = "naro/%s_%s_%s" % (date or "nodate", label, slug(num, 60))
        if name in used:
            name += "_onar" + rid
        used.add(name)
        rel = name + ".pdf"
        if save(host, rec["pdf"], rel, problems):
            note = "ONAR %s; issued %s; filed %s" % (rec["reg"], rec["issued"] or "-", rec["filed"] or "-")
            if date and date != rec["issued"]:
                note += "; register's issue date evidently mistyped, filing date used"
            rows.append((rel, "%s - %s" % (rec["number"], rec["title"]), date, rec["pdf"], kind,
                         "%s - %s" % (rec["number"], rec["title"]), issuer, url, note))


def run_static(items, host, rows, problems):
    for rel, title, date, url, kind, issuer, number, note in items:
        if save(host, url, rel, problems):
            rows.append((rel, title, date, url, kind, title, issuer, url, note))


def main():
    want = set(sys.argv[1:]) or {"naro", "onar", "archive"}
    OUT.mkdir(exist_ok=True)
    rows, problems = [], []
    if "naro" in want:
        run_naro(rows, problems)
    if "onar" in want:
        run_static(ONAR, Host("https://law.upd.edu.ph", 1.5), rows, problems)
    if "archive" in want:
        run_static(ARCHIVE, Host("https://web.archive.org", 5.0), rows, problems)

    # keep rows of sources not run this time
    idx = OUT / "index.tsv"
    header = "file\ttitle\tdate\tsource_url\tkind\ttitle_en\tissuer\trecord_page\tnote"
    if idx.exists() and want != {"naro", "onar", "archive"}:
        prefixes = {"naro": "naro/", "onar": "onar/", "archive": "doj-archive/"}
        skip = tuple(prefixes[s] for s in want if s in prefixes)
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if f and not f[0].startswith(skip) and (OUT / f[0]).exists():
                rows.append(tuple(f))
    rows.sort(key=lambda r: r[0])
    clean = lambda v: re.sub(r"[\t\r\n]+", " ", v)
    idx.write_text(header + "\n" + "".join("\t".join(clean(v) for v in r) + "\n" for r in rows), encoding="utf-8")

    no = [(t, d, u, r) for t, d, u, r in NOT_OBTAINED]
    no += [("fetch failed: " + rel, "", url, why) for rel, url, why in problems]
    (OUT / "not-obtained.tsv").write_text(
        "title\tdate\turl\treason\n" + "".join("\t".join(clean(v) for v in r) + "\n" for r in no), encoding="utf-8")
    print("index rows: %d; problems: %d" % (len(rows), len(problems)))


if __name__ == "__main__":
    main()

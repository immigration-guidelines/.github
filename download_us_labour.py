#!/usr/bin/env python3
"""United States, labour authority: Department of Labor, Employment and Training Administration,
Office of Foreign Labor Certification (OFLC) - policy directives and guidance for the officials who
decide labor certifications (National Processing Centers, National Prevailing Wage Center) and for
the State Workforce Agencies (SWAs) that process H-2A/H-2B job orders, housing inspections and
prevailing-wage surveys.

    python3 download_us_labour.py

What is taken: the Training and Employment Guidance Letters (TEGLs) and other directives listed on
OFLC's "Policies and Regulations" page (https://www.dol.gov/agencies/eta/foreign-labor/policy, capture
of 8 August 2026) with their attachments, the annual Foreign Labor Certification grant planning TEGLs
(guidance to SWAs), the prevailing-wage policy guidance, the PERM program guidance bulletins, ET Handbook
385, two 2005 DFLC field directives and the 2021 H-1B secondary-employer bulletin. Not taken: FAQs,
webinars, fact sheets, forms, user guides, Federal Register rules and notices (applicant information or law).

www.dol.gov answers this machine with HTTP 403 (also for robots.txt, 15 November 2026), so nothing is
requested from it; each file is an Internet Archive capture taken unmodified with the "id_" form, at
most one request every 8 s, given up after three refusals in a row. Files already present are skipped;
us/labour/index.tsv is rewritten. NOTES.txt and not-obtained.tsv are written by hand.
"""
import gzip
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.5                      # seconds between requests to one host
HOST_DELAY = {"web.archive.org": 8.0}
AI_AGENTS = ("claudebot", "claude-web", "anthropic-ai", "gptbot", "chatgpt-user", "ccbot", "ai2bot",
             "perplexitybot", "google-extended", "cohere-ai", "bytespider", "amazonbot")

_last = {}        # host -> time of last request
_closed = {}      # host -> reason it may no longer be used
_bad = {}         # host -> consecutive connection failures / refusals
_robots = {}      # host -> list of (allow?, pattern) rules that apply to this script, or None


def _wait(host):
    gap = HOST_DELAY.get(host, DELAY)
    t = _last.get(host)
    if t is not None and time.time() - t < gap:
        time.sleep(gap - (time.time() - t))
    _last[host] = time.time()


def _raw(url, timeout=120):
    """One request. Returns (bytes, final_url, None) or (None, None, reason). No retries."""
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        return None, None, "host closed: " + _closed[host]
    _wait(host)
    quoted = urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")
    try:
        req = urllib.request.Request(quoted, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if body[:2] == b"\x1f\x8b" and not quoted.endswith(".gz"):
                try:                                        # the archive hands back stored gzip transfer encoding
                    body = gzip.decompress(body)
                except OSError:
                    pass
            _bad[host] = 0
            return body, r.geturl(), None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):                       # a refusal closes the host
            if host == "web.archive.org":                   # archive: give up after three in a row
                _bad[host] = _bad.get(host, 0) + 1
                if _bad[host] >= 3:
                    _closed[host] = "three refusals in a row"
            else:
                _closed[host] = f"HTTP {e.code}"
        return None, None, f"HTTP {e.code}"
    except Exception as e:                                  # noqa: BLE001
        _bad[host] = _bad.get(host, 0) + 1
        if _bad[host] >= 3:
            _closed[host] = "three connection failures in a row"
        return None, None, f"{type(e).__name__}: {e}"


def _rule_matches(pattern, path):
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
    return re.match(rx + ("$" if pattern.endswith("$") else ""), path) is not None


def robots_ok(url):
    """Fetch the host's robots.txt before anything else on that host and apply the rules for
    '*' and for any named AI agent (wildcards handled here; urllib.robotparser ignores them)."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host not in _robots:
        body, _, why = _raw(f"{parts.scheme}://{host}/robots.txt", timeout=60)
        rules = []
        if body is None:
            if why == "HTTP 404":
                pass                                        # no robots.txt: nothing is excluded
            else:
                _closed.setdefault(host, "robots.txt not readable (" + str(why) + ")")
        else:
            agents, fresh = [], True
            for line in body.decode("utf-8", "replace").splitlines():
                line = line.split("#", 1)[0].strip()
                if ":" not in line:
                    continue
                key, val = (x.strip() for x in line.split(":", 1))
                key = key.lower()
                if key == "user-agent":
                    if not fresh:
                        agents, fresh = [], True
                    agents.append(val.lower())
                elif key in ("allow", "disallow"):
                    fresh = False
                    if val and any(a == "*" or a in AI_AGENTS for a in agents):
                        rules.append((key == "allow", val))
                elif key == "crawl-delay":
                    fresh = False
                    if any(a == "*" or a in AI_AGENTS for a in agents):
                        try:
                            HOST_DELAY[host] = max(HOST_DELAY.get(host, DELAY), float(val))
                        except ValueError:
                            pass
        _robots[host] = rules
    if host in _closed:
        return False
    path = parts.path + ("?" + parts.query if parts.query else "")
    best, allowed = -1, True
    for allow, pat in _robots[host]:
        if _rule_matches(pat, path) and (len(pat) > best or (len(pat) == best and allow)):
            best, allowed = len(pat), allow
    return allowed


def get(url, timeout=120):
    """Polite GET that respects robots.txt. Returns (bytes, final_url, None) or (None, None, reason)."""
    if not robots_ok(url):
        host = urllib.parse.urlsplit(url).netloc
        return None, None, _closed.get(host, "excluded by robots.txt")
    return _raw(url, timeout)


def looks_ok(body, name):
    """Reject error, login and bot-check pages: the bytes must match the file type."""
    ext = name.rsplit(".", 1)[-1].lower()
    head = body[:2048].lstrip()
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext in ("docx", "xlsx", "zip"):
        return head.startswith(b"PK")
    if ext in ("doc", "xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0")
    if ext == "xml":
        return head.startswith(b"<?xml") or head.startswith(b"<")
    if ext in ("html", "htm"):
        low = body[:200000].lower()
        return b"<html" in low and b"captcha" not in low and b"access denied" not in low
    return True


def save(url, dest):
    """Download url to dest unless dest exists. Returns None on success, else the reason."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    body, _, why = get(url)
    if body is None:
        return why
    if not looks_ok(body, dest.name):
        return "not the expected file type (error or challenge page?)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.rename(dest)
    return None


def clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(clean(x) for x in r) + "\n")


def pdf_ok(path):
    try:
        return subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60).returncode == 0
    except Exception:                                       # noqa: BLE001 - pdfinfo missing: trust the magic bytes
        return True


HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "note"]
NOT_HEADER = ["title", "date", "url", "reason"]

OUT = ROOT / "us" / "labour"
DOL = "https://www.dol.gov/sites/dolgov/files/ETA/"
ARCHIVE = "https://web.archive.org/web/{ts}id_/{url}"
H2A, H2B, GRANT, PW = "H-2A", "H-2B", "SWA grant", "prevailing wage / PERM"

# (file, date, title, path under DOL, archive timestamp, topic)
ITEMS = [
    ("2005-10-13_DFLC-Field-Memorandum_Katrina-deadlines.pdf", "2005-10-13",
     "DFLC Field Memorandum: Response to Hurricane Katrina - Deadlines and Correspondence for the Permanent Labor Certification Program (to National Processing Center and Backlog Elimination Center Directors)",
     "oflc/pdfs/FM_Katrina_Deadline_Guidance.pdf", "20210325191731", PW),
    ("2005-11-16_TEGL_DFLC_hurricanes-Katrina-Rita-Wilma.pdf", "2005-11-16",
     "Training and Employment Guidance Letter (DFLC, unnumbered): Response to Hurricanes Katrina, Rita and Wilma (to FLC National Processing Center and Backlog Elimination Center Directors)",
     "oflc/pdfs/DFLC_Hurricane_guidance_11_15_05.pdf", "20210325191542", PW),
    ("2005-05-09_Prevailing-Wage-Determination-Policy-Guidance_Nonagricultural.pdf", "2005-05-09",
     "Prevailing Wage Determination Policy Guidance, Nonagricultural Immigration Programs, revised May 9, 2005",
     "oflc/pdfs/policy_nonag_progs.pdf", "20200820222401", PW),
    ("2009-11_Prevailing-Wage-Determination-Policy-Guidance_Nonagricultural_rev.pdf", "2009-11",
     "Prevailing Wage Determination Policy Guidance, Nonagricultural Immigration Programs, revised November 2009",
     "oflc/pdfs/NPWHC_Guidance_Revised_11_2009.pdf", "20200819180632", PW),
    ("2008_PERM-Program-Guidance-Bulletin_656-10-b-2.pdf", "2008",
     "PERM Program Guidance Bulletin on the Clarification of Scope of Consideration Rule in 20 CFR 656.10(b)(2)",
     "oflc/pdfs/PERMRule20CFR65610b2.pdf", "20201031102630", PW),
    ("2008-08-29_PERM-Program-Guidance-Bulletin_restatement.pdf", "2008-08-29",
     "Restatement of PERM Program Guidance Bulletin on the Clarification of Scope of Consideration Rule in 20 CFR 656.10(b)(2)",
     "oflc/pdfs/PERM_Guidance_Final_082908.pdf", "20200922055246", PW),
    ("1981-08_ET-Handbook-385_Wage-Finding-Process.pdf", "1981-08",
     "ET Handbook No. 385, Wage Finding Process (domestic agricultural in-season wage surveys by State Workforce Agencies)",
     "oflc/pdfs/et_385_wage_finding_process.pdf", "20200819032835", H2A),
    ("2021-01-15_H-1B-Program-Bulletin_secondary-employers.pdf", "2021-01-15",
     "H-1B Program Bulletin: Clarifying Filing Requirements for Labor Condition Applications (secondary employers)",
     "oflc/pdfs/DOL-ETA_OFLC_Clarifying-Guidance_H-1B-Secondary-Employers_FINAL.pdf", "20210115222913", "H-1B LCA"),
    ("2006-05-31_TEGL-31-05_H-2B-entertainment.pdf", "2006-05-31",
     "TEGL No. 31-05: Procedures for Temporary Labor Certification in the Entertainment Industry under the H-2B Visa Program",
     "advisories/TEGL/2006/TEGL31-05.pdf", "20230926125223", H2B),
    ("2007-02-09_TEGL-15-06_H-2A-open-range-livestock.pdf", "2007-02-09",
     "TEGL No. 15-06: Special Procedures for Processing H-2A Applications for Occupations Involved in the Open Range Production of Livestock",
     "advisories/TEGL/2007/TEGL15-06.pdf", "20250113035701", H2A),
    ("2007-02-09_TEGL-15-06_attachment-1.pdf", "2007-02-09", "TEGL No. 15-06, Attachment 1",
     "advisories/TEGL/2007/TEGL15-06_Att1.pdf", "20250112225737", H2A),
    ("2007-02-12_TEGL-16-06_H-2A-custom-combine.pdf", "2007-02-12",
     "TEGL No. 16-06: Special Procedures for Processing H-2A Applications for Multi-State Custom Combine Owners/Operators",
     "advisories/TEGL/2007/TEGL16-06.pdf", "20250113035505", H2A),
    ("2007-02-12_TEGL-16-06_attachment-1.pdf", "2007-02-12", "TEGL No. 16-06, Attachment 1",
     "advisories/TEGL/2007/TEGL16-06_Att1.pdf", "20250112225931", H2A),
    ("2007-02-12_TEGL-17-06_H-2A-animal-shearing.pdf", "2007-02-12",
     "TEGL No. 17-06: Special Procedures for Employers in the Itinerant Animal Shearing Industry under the H-2A Program",
     "advisories/TEGL/2007/TEGL17-06.pdf", "20250113035551", H2A),
    ("2007-02-12_TEGL-17-06_attachment-1.pdf", "2007-02-12", "TEGL No. 17-06, Attachment 1",
     "advisories/TEGL/2007/TEGL17-06_Att1.pdf", "20250112231328", H2A),
    ("2007-04-04_TEGL-21-06_H-2B-procedures.pdf", "2007-04-04",
     "TEGL No. 21-06: Procedures for H-2B Temporary Labor Certification in Non-Agricultural Occupations",
     "advisories/TEGL/2007/TEGL21-06.pdf", "20250113034545", H2B),
    ("2007-04-04_TEGL-21-06_attachment-1.pdf", "2007-04-04", "TEGL No. 21-06, Attachment 1",
     "advisories/TEGL/2007/TEGL21-06_Att1.pdf", "20250113003121", H2B),
    ("2007-06-25_TEGL-21-06-Change-1_H-2B-procedures.pdf", "2007-06-25",
     "TEGL No. 21-06, Change 1: Procedures for H-2B Temporary Labor Certification in Non-Agricultural Occupations",
     "advisories/TEGL/2007/TEGL21-06c1.pdf", "20250113031927", H2B),
    ("2007-06-25_TEGL-21-06-Change-1_attachment-1.pdf", "2007-06-25", "TEGL No. 21-06, Change 1, Attachment 1",
     "advisories/TEGL/2007/TEGL21-06c1a1.pdf", "20250113031932", H2B),
    ("2007-06-12_TEGL-27-06_H-2B-reforestation.pdf", "2007-06-12",
     "TEGL No. 27-06: Special Guidelines for Processing H-2B Temporary Labor Certification in Tree Planting and Related Reforestation Occupations",
     "advisories/TEGL/2007/TEGL27-06.pdf", "20250113032257", H2B),
    ("2007-06-12_TEGL-27-06_attachment-1.pdf", "2007-06-12", "TEGL No. 27-06, Attachment 1",
     "advisories/TEGL/2007/TEGL27-06a1.pdf", "20250113032307", H2B),
    ("2007-11-06_TEGL-11-07_H-2A-procedures.pdf", "2007-11-06",
     "TEGL No. 11-07: Clarification of Certain Procedures for Processing H-2A Labor Certification Applications",
     "advisories/TEGL/2007/TEGL11-07acc.pdf", "20250113221316", H2A),
    ("2007-11-14_TEGL-11-07-Change-1_H-2A-procedures.pdf", "2007-11-14",
     "TEGL No. 11-07, Change 1: Clarification of Certain Procedures for Processing H-2A Labor Certification Applications",
     "advisories/TEGL/2007/TEGL11-07c1.pdf", "20250113025426", H2A),
    ("2009-08-28_TEGL-11-07-Change-2_rescission.pdf", "2009-08-28",
     "TEGL No. 11-07, Change 2: Rescission of TEGL No. 11-07, Change 1",
     "advisories/TEGL/2009/TEGL11-07c2.pdf", "20240615075743", H2A),
    ("2011-06-14_TEGL-16-06-Change-1_H-2A-custom-combine.pdf", "2011-06-14",
     "TEGL No. 16-06, Change 1: Special Procedures: Labor Certification Process for Multi-State Custom Combine Owners/Operators under the H-2A Program",
     "advisories/TEGL/2011/TEGL16-06-Ch1.pdf", "20250112171328", H2A),
    ("2011-06-14_TEGL-16-06-Change-1_attachment-A.pdf", "2011-06-14", "TEGL No. 16-06, Change 1, Attachment A",
     "advisories/TEGL/2011/TEGL16-06-Ch1-ATT-A.pdf", "20250112171336", H2A),
    ("2011-06-14_TEGL-16-06-Change-1_attachment-B.pdf", "2011-06-14", "TEGL No. 16-06, Change 1, Attachment B",
     "advisories/TEGL/2011/TEGL16-06-Ch1-ATT-B.pdf", "20250112171343", H2A),
    ("2011-06-14_TEGL-17-06-Change-1_H-2A-animal-shearing.pdf", "2011-06-14",
     "TEGL No. 17-06, Change 1: Special Procedures: Labor Certification Process for Employers in the Itinerant Animal Shearing Industry under the H-2A Program",
     "advisories/TEGL/2011/TEGL17-06-Ch1.pdf", "20240318090812", H2A),
    ("2011-06-14_TEGL-17-06-Change-1_attachment-A.pdf", "2011-06-14", "TEGL No. 17-06, Change 1, Attachment A",
     "advisories/TEGL/2011/TEGL17-06-Ch1-ATT-A.pdf", "20240309173825", H2A),
    ("2011-06-14_TEGL-17-06-Change-1_attachment-B.pdf", "2011-06-14", "TEGL No. 17-06, Change 1, Attachment B",
     "advisories/TEGL/2011/TEGL17-06-Ch1-ATT-B.pdf", "20240302072249", H2A),
    ("2011-06-14_TEGL-32-10_H-2A-sheepherding-goatherding.pdf", "2011-06-14",
     "TEGL No. 32-10: Special Procedures: Labor Certification Process for Employers Engaged in Sheepherding and Goatherding Occupations under the H-2A Program",
     "advisories/TEGL/2011/TEGL32-10.pdf", "20220709113853", H2A),
    ("2011-06-14_TEGL-32-10_attachment-A.pdf", "2011-06-14", "TEGL No. 32-10, Attachment A",
     "advisories/TEGL/2011/TEGL32-10ATT-A.pdf", "20220709113811", H2A),
    ("2011-06-14_TEGL-32-10_attachment-B.pdf", "2011-06-14", "TEGL No. 32-10, Attachment B",
     "advisories/TEGL/2011/TEGL32-10ATT-B.pdf", "20220709113824", H2A),
    ("2011-06-14_TEGL-33-10_H-2A-beekeeping.pdf", "2011-06-14",
     "TEGL No. 33-10: Special Procedures: Labor Certification Process for Itinerant Commercial Beekeeping Employers in the H-2A Program",
     "advisories/TEGL/2011/TEGL33-10.pdf", "20250111063325", H2A),
    ("2011-06-14_TEGL-33-10_attachment-A.pdf", "2011-06-14", "TEGL No. 33-10, Attachment A",
     "advisories/TEGL/2011/TEGL33-10ATT-A.pdf", "20250103221034", H2A),
    ("2018-04-25_TEGL-15-17_FY2018-FLC-grant-planning-guidance.pdf", "2018-04-25",
     "TEGL No. 15-17: Fiscal Year (FY) 2018 Foreign Labor Certification (FLC) Grant Planning Guidance",
     "advisories/TEGL/2018/TEGL_15-17.pdf", "20240611231053", GRANT),
    ("2020-04-13_TEGL-14-19_FY2020-FLC-grant-planning-guidance.pdf", "2020-04-13",
     "TEGL No. 14-19: Fiscal Year (FY) 2020 Foreign Labor Certification Grant Planning Guidance",
     "advisories/TEGL/2020/TEGL_14-19.pdf", "20221006040933", GRANT),
    ("2021-05-10_TEGL-21-20_FY2021-FLC-grant-planning-guidance.pdf", "2021-05-10",
     "TEGL No. 21-20: Fiscal Year (FY) 2021 Foreign Labor Certification Grant Planning Guidance",
     "advisories/TEGL/2021/TEGL_21-20.pdf", "20240705084832", GRANT),
    ("2022-06-10_TEGL-12-21_FLC-grant-planning-guidance-FY2022-2024.pdf", "2022-06-10",
     "TEGL No. 12-21: Foreign Labor Certification Grant Planning Guidance for Fiscal Years (FYs) 2022 through FY 2024",
     "advisories/TEGL/2022/TEGL_12-21.pdf", "20220624003935", GRANT),
    ("2023-03-20_TEGL-12-21-Change-1.pdf", "2023-03-20",
     "TEGL No. 12-21, Change 1: Foreign Labor Certification Grant Planning Guidance for FYs 2022 through 2024 (revised)",
     "advisories/TEGL/2021/TEGL%2012-21%20Change%201/TEGL%2012-21%20Change%201%20revised.pdf", "20240620205849", GRANT),
    ("2024-04-26_TEGL-12-21-Change-2.pdf", "2024-04-26",
     "TEGL No. 12-21, Change 2: Foreign Labor Certification Grant Planning Guidance for FYs 2022 through 2024",
     "advisories/TEGL/2021/TEGL%2012-21%20Change%202/TEGL%2012-21%20Change%202A.pdf", "20240706003226", GRANT),
    ("2025-06-11_TEGL-15-24_FLC-grant-planning-guidance-FY2025-2027.pdf", "2025-06-11",
     "TEGL No. 15-24: Foreign Labor Certification Grant Planning Guidance for Fiscal Year (FY) 2025 through FY 2027",
     "advisories/TEGL/2024/TEGL%2015-24/TEGL%2015-24.pdf", "20260113193032", GRANT),
    ("2026-05-12_TEGL-15-24-Change-1_FY2026.pdf", "2026-05-12",
     "Change 1 to TEGL No. 15-24, Foreign Labor Certification Grant Planning Guidance for Fiscal Year 2026",
     "advisories/TEGL/2024/TEGL%2015-24%2C%20Change%201/TEGL%2015-24%2C%20Change%201.pdf", "20260514012438", GRANT),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, failed = [], []
    for name, date, title, path, ts, topic in ITEMS:
        url = DOL + path
        dest = OUT / name
        why = save(ARCHIVE.format(ts=ts, url=url), dest)
        if why is None and not pdf_ok(dest):
            dest.unlink()
            why = "pdfinfo rejects the file"
        if why:
            failed.append((title, date, url, f"www.dol.gov refuses this machine (HTTP 403 on robots.txt); Internet Archive copy {ts} not fetched: {why}"))
            print(f"FAILED\t{name}\t{why}")
            continue
        rows.append([name, title, date, urllib.parse.unquote(url), "guidance", title,
                     f"{topic}; copy from the Internet Archive: " + ARCHIVE.format(ts=ts, url=url)])
    write_tsv(OUT / "index.tsv", HEADER, sorted(rows))
    print(f"index.tsv: {len(rows)} rows; {len(failed)} failed")
    for f in failed:
        print("NOT OBTAINED\t" + "\t".join(f))


if __name__ == "__main__":
    main()

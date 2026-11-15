#!/usr/bin/env python3
"""India: what the Ministry of Home Affairs (Foreigners Division) and the Bureau of Immigration
publish today that officers apply: the rules, orders and notifications under the Immigration and
Foreigners Act 2025 (procedural acts) and the few policy and instruction papers still on line.

    python3 download_in.py              # all sources
    python3 download_in.py mha boi      # only the named sources

Sources (names usable as arguments):
  mha   www.mha.gov.in, "Notifications" filtered to the Foreigners-I division
        (https://www.mha.gov.in/notifications?field_notice_divisions_target_id=285, pages 0-3):
        the Immigration and Foreigners Order 2025, Exemption Order, the notifications appointing
        FRROs and district police as registration officers and civil authorities, delegating powers
        to States/UTs and on compounding; and three instruction papers (permanent residence for
        foreign investors 2017, manual acceptance of citizenship applications of minority migrants
        2014, documents for citizenship under s. 6B 2024).
  boi   boi.mha.gov.in, "Immigration Policies & Process": the Immigration and Foreigners Rules 2025.

The visa policy guidelines (Annexes I-VII of 20.08.2020), the long-term visa SOPs, OCI guidelines and
the orders delegating powers to FRROs were on the old mha.gov.in Foreigners Division pages; the
2025-26 redesign removed them and the old addresses answer 404. They are listed in in/not-obtained.tsv.
The statutes themselves (the 2025 Act, the Citizenship Act) are not collected.

robots.txt of every host is read first and obeyed. HTTP 403/429 or a bot check ends the use of a
host for the run; so do three connection failures in a row. Sequential, 1.6 s between requests.
Existing files are skipped; in/index.tsv and in/not-obtained.tsv are rewritten. Standard library only.
"""
import gzip
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "in"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE, PAUSE_IA = 1.6, 4.0
HEAD = ["file", "title", "date", "source_url", "kind", "title_en", "source", "note"]
CONTEXT = {}

N = "https://www.mha.gov.in/files/notice_document/"
G, P = "guidance", "procedural act"
SOURCES = {"mha": "mha.gov.in Notifications (Foreigners-I Division)",
           "boi": "boi.mha.gov.in Immigration Policies & Process"}
# (source, file, url, title, date, kind, title_en, note)
ITEMS = [
    ("mha", "mha/2025-09-01_Immigration-and-Foreigners-Order-2025.pdf", N + "AnnexureImmigrationFroeignersOrder_2025.pdf",
     "Immigration & Foreigners Order, 2025", "2025-09-01", P, "Immigration and Foreigners Order, 2025",
     "order under the Immigration and Foreigners Act 2025: visas, registration, FRRO powers, protected areas; replaces the Foreigners Order 1948"),
    ("mha", "mha/2025-09-10_Immigration-and-Foreigners-Order-2025_with-corrigendum.pdf",
     N + "CorrigendumImmigrationForeignersOrder2025_0.pdf",
     "The Immigration and Foreigners Order, 2025 along with corrigendum", "2025-09-10", P,
     "Immigration and Foreigners Order, 2025, with corrigendum", ""),
    ("mha", "mha/2025-09-01_Immigration-and-Foreigners-Exemption-Order-2025.pdf",
     N + "ImmigrationForeignersExemptionOrder2025_0.pdf",
     "The Immigration and Foreigners (Exemption) Order, 2025", "2025-09-01", P,
     "Immigration and Foreigners (Exemption) Order, 2025", ""),
    ("mha", "mha/2025-09-01_Notification-compounding-of-offences.pdf", N + "NotificationCompoundingCertainOffences-1.pdf",
     "The notification on compounding of certain offences", "2025-09-01", P,
     "Notification on compounding of certain offences under the 2025 Act", ""),
    ("mha", "mha/2025-09-01_Notification-FRROs-as-Registration-Officers.pdf",
     N + "12NotificationFRROsRegistrationOfficerImmigrationForeignersAct2025.pdf",
     "The notification authorizing Foreigners Regional Registration Officers as Registration Officers", "2025-09-01", P,
     "Notification authorising FRROs as registration officers", ""),
    ("mha", "mha/2025-09-01_Notification-FRROs-as-civil-authorities.pdf",
     N + "11NotificationFRROsCivilAuthorityImmigrationForeignersAct2025-1_1.pdf",
     "The notification appointing Foreigners Regional Registration Officers as civil authorities", "2025-09-01", P,
     "Notification appointing FRROs as civil authorities", ""),
    ("mha", "mha/2025-09_Notification-SP-DCP-as-Registration-Officers.pdf",
     N + "9NotificationSP_DCPRegistrationOfficerImmigrationForeignersAct2025_3.pdf",
     "The notification authorising Superintendent of Police or Deputy Commissioner of Police in each District as Registration Officers",
     "2025-09", P, "Notification authorising district SPs/DCPs as registration officers", "undated in the listing"),
    ("mha", "mha/2025-09_Notification-SP-DCP-as-civil-authorities.pdf",
     N + "10NotificationSP_DCPCivilAuthorityImmigrationForeignersAct2025_0.pdf",
     "The notification appointing the Superintendent of Police or Deputy Commissioner of Police in each District as civil authorities",
     "2025-09", P, "Notification appointing district SPs/DCPs as civil authorities", "undated in the listing"),
    ("mha", "mha/2025-09-01_Notification-delegation-of-powers-to-States-UTs.pdf",
     N + "NotificationregardingpowerDelegation_ImmigrationForeignersAct2025.pdf",
     "The notification delegating certain powers and functions to the State Government, Union Territories etc.",
     "2025-09-01", P, "Notification delegating powers and functions under the 2025 Act to States and UTs", ""),
    ("mha", "mha/2017-04-17_Permanent-Residency-Status-to-Foreign-Investors.pdf", N + "prsforeigninvestors_17042017.pdf",
     "Permanent Residency Status to Foreign Investors", "2017-04-17", G, "Permanent residency status for foreign investors",
     "scheme conditions and procedure"),
    ("mha", "mha/2014-11-17_Manual-acceptance-of-citizenship-applications-minority-migrants.pdf",
     N + "Permission-exemptionmanualacceptanceapplicationgratIndiancitizenship.pdf",
     "Permission/exemption for manual acceptance of application for grant of Indian Citizenship to Minority Community migrated from Pakistan/Afghanistan",
     "2014-11-17", G, "Instruction allowing manual acceptance of citizenship applications by minority migrants from Pakistan/Afghanistan", ""),
    ("mha", "mha/2024-07-08_Clarification-documents-citizenship-s6B.pdf",
     N + "Clarificationdocumentssubmittedapplicantsapplying.pdf",
     "Clarification on documents to be submitted by the applicants for grant of Indian Citizenship under Section 6B and Schedule-1A of the Citizenship Act, 1955",
     "2024-07-08", G, "Clarification on documents for citizenship applications under s. 6B (CAA 2019)", ""),
    ("boi", "boi/2025-09_Immigration-and-Foreigners-Rules-2025.pdf",
     "https://boi.mha.gov.in/boi/pdf/Annexure-Immigration_and_Foreigners_Rules_2025.pdf",
     "Immigration & Foreigners Rules, 2025", "2025-09-01", P, "Immigration and Foreigners Rules, 2025",
     "rules under the 2025 Act (visa, registration, carriers, institutions); the MHA listing gives no file"),
]

A = "removed from mha.gov.in in the 2025-26 redesign (old address answers 404); Internet Archive captures exist but the archive refused this machine (HTTP 403, then repeated connection refusals) during the run of 15 Nov 2026, so it was given up"
O = "https://www.mha.gov.in/sites/default/files/"
NOT_OBTAINED = [
    ("Annex I - General policy guidelines relating to Indian visas", "2020-08-20", O + "2022-08/AnnexIGeneralpolicy20082020%5B1%5D.pdf", A),
    ("Annex II - Regulations (visa)", "2020-08-20", O + "2022-09/AnnexIIRegulations20082020%5B1%5D.pdf", A),
    ("Annex III - Details of visas", "2020-08-20", O + "2022-09/AnnexIIIDetailsofVisas20082020%5B1%5D.pdf", A),
    ("Annex IV - Bangladesh nationals", "2020-08-20", O + "2022-09/AnnexIVBangladeshinationals20082020%5B1%5D.pdf", A),
    ("Annex V - Pakistan nationals", "2020-08-20", O + "2022-09/AnnexVPakistaninationals20082020%5B1%5D.pdf", A),
    ("Annex VI - Long Term Visas", "2020-08-20", O + "2022-09/AnnexVILongTermvisas20082020%5B1%5D.pdf", A),
    ("Annex VII (visa guidelines)", "2020-08-20", O + "2022-09/AnnexVII20082020%5B1%5D.pdf", A),
    ("Powers delegated to FRROs/FROs and State Governments/UTs", "", O + "2022-08/ForeigD-PwrdlgtFRROs%5B1%5D.pdf", A),
    ("Long Term Visa (LTV) guidelines / SOP", "2017-06-09", O + "2022-08/LTV_09062017%5B1%5D.pdf", A),
    ("Facilities to minority-community LTV holders from Afghanistan, Bangladesh and Pakistan", "2016-08-23", O + "2022-09/LTVFacilities_230816_2%5B1%5D.pdf", A),
    ("Long term visa to Pakistan nationals", "2015-04-07", O + "2022-09/LTVisaPak_070415%5B1%5D.pdf", A),
    ("Guidelines OCI", "", O + "2022-08/GuidelinesOCI[1].pdf", A),
    ("Instructions dated 22.07.2016 (OCI)", "2016-07-22", O + "2022-09/InstDated220716OCI_1%5B1%5D.pdf", A),
    ("OCI miscellaneous services: guidelines", "2021-07-16", O + "2022-09/OCIMISCELLANEOUSSERVICES_Guidelines_16072021%5B1%5D.pdf", A),
    ("Supporting documents for services from FRROs", "2014", O + "2022-08/SupportDocServicesFromFRROs2014%5B1%5D.pdf", A),
    ("Visa Manual (MHA internal manual, 2019 and later)", "", "https://www.mha.gov.in/",
     "never published by the Ministry; copies circulating on third-party sites are leaks and are not collected"),
]
class Refused(Exception):
    pass


_last, _fails, _closed, _robots = {}, {}, set(), {}


def _raw(url, timeout=180):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Refused(f"{host}: closed earlier in this run")
    wait = (PAUSE_IA if host.endswith("archive.org") else PAUSE) - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, None, {"User-Agent": UA}), timeout=timeout,
                                    context=CONTEXT.get(host)) as r:
            data = r.read()
        if data[:2] == b"\x1f\x8b":                  # some servers gzip whatever the request says
            data = gzip.decompress(data)
        _fails[host] = 0
        return data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            _closed.add(host)
            raise Refused(f"{host}: HTTP {e.code}") from None
        raise
    except (urllib.error.URLError, OSError) as e:
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] >= 3:
            _closed.add(host)
            raise Refused(f"{host}: three connection failures in a row ({e})") from None
        raise
    finally:
        _last[host] = time.time()


def _rules(host, scheme):
    if host not in _robots:
        try:
            txt = _raw(f"{scheme}://{host}/robots.txt", 60).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                _closed.add(host)
                raise Refused(f"{host}: robots.txt answered HTTP {e.code}") from None
            txt = ""
        if txt.lstrip()[:1] == "<":
            txt = ""
        rules, groups, fresh = [], [], True
        for line in txt.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (s.strip() for s in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if fresh and groups:
                    groups[-1][0].append(v.lower())
                else:
                    groups.append(([v.lower()], []))
                fresh = True
            elif k in ("allow", "disallow"):
                fresh = False
                if groups and v:
                    groups[-1][1].append((k, v))
        for ags, rs in groups:
            if any(a in ("*", "claudebot", "anthropic-ai", "claude-web", "gptbot", "ccbot") for a in ags):
                rules += rs
        _robots[host] = rules
    return _robots[host]


def allowed(url):
    u = urllib.parse.urlsplit(url)
    path = u.path + ("?" + u.query if u.query else "")
    best, verdict = -1, True
    for kind, pat in _rules(u.netloc, u.scheme):
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pat.rstrip("$")) + ("$" if pat.endswith("$") else "")
        if re.match(rx, path) and (len(pat) > best or (len(pat) == best and kind == "allow")):
            best, verdict = len(pat), kind == "allow"
    return verdict


def get(url):
    if not allowed(url):
        raise Refused(f"robots.txt disallows {url}")
    data = _raw(url)
    if re.search(rb"Just a moment|cf-challenge|captcha", data[:4000], re.I) and data[:5] != b"%PDF-":
        _closed.add(urllib.parse.urlsplit(url).netloc)
        raise Refused(f"bot check at {url}")
    return data


def bad(data, name):
    if len(data) < 300:
        return "too small"
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "pdf" and data[:5] != b"%PDF-":
        return "not a PDF"
    if ext == "docx" and data[:2] != b"PK":
        return "not a Word file"
    return None


def fetch(rel, url, missing, title, date):
    dest = OUT / rel
    if dest.exists() and dest.stat().st_size:
        return True
    try:
        data = get(url)
    except Refused:
        raise
    except Exception as e:                                # noqa: BLE001
        missing.append((title, date, url, f"download failed: {e}"))
        print(f"  FAILED {rel}: {e}")
        return False
    why = bad(data, rel)
    if why:
        missing.append((title, date, url, f"server returned {why}"))
        print(f"  REJECTED {rel}: {why}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_name(dest.name + ".part").write_bytes(data)
    dest.with_name(dest.name + ".part").replace(dest)
    print(f"  saved {rel} ({len(data):,} bytes)")
    return True


def tsv(path, head, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(head) + "\n")
        for r in rows:
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in r) + "\n")



def main():
    names = list(SOURCES)
    which = [a for a in sys.argv[1:] if a in names] or names
    OUT.mkdir(exist_ok=True)
    missing, stopped = list(NOT_OBTAINED), set()
    for src, rel, url, title, date, kind, en, note in ITEMS:
        if src in which and src not in stopped:
            try:
                fetch(rel, url, missing, title, date)
            except Refused as e:
                print(f"STOPPED {src}: {e}")
                missing.append((title, date, url, f"{e}; host not used further"))
                stopped.add(src)
        elif src in stopped and not (OUT / rel).exists():
            missing.append((title, date, url, "not attempted: host closed earlier in the run"))
    rows = [[rel, title, date, url, kind, en, SOURCES[src], note]
            for src, rel, url, title, date, kind, en, note in ITEMS if (OUT / rel).exists()]
    tsv(OUT / "index.tsv", HEAD, rows)
    tsv(OUT / "not-obtained.tsv", ["title", "date", "url", "reason"], missing)
    print(f"{len(rows)} rows in index.tsv; {len(missing)} entries in not-obtained.tsv")


if __name__ == "__main__":
    main()

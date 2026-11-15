#!/usr/bin/env python3
"""Hong Kong: the little officer-facing immigration guidance that is public.

    python3 download_hk.py                 # all sources
    python3 download_hk.py sb immd         # only the named sources

Sources (names usable as arguments):

  sb         Security Bureau, Torture Claims Appeal Board / Non-refoulement Claims Petition
             Office pages (www.sb.gov.hk/eng/links/tcab/, /chi/links/tcab/): the Board's
             "Principles, Procedures and the Practice Directions" (PPP) and the "Practice and
             Procedural Guide" of the administrative petition scheme, current (2021) and
             previous (2019) editions, English and Chinese; the Unified Screening Mechanism
             paper; the Board's hearing and work arrangements in bad weather.
  immd       Immigration Department: its published detention policies under ss. 32 and
             37ZK of the Immigration Ordinance (the policies officers apply), English and
             Chinese (www.immd.gov.hk/eng/useful_information/enforcement.html).
  accessinfo Two Immigration Department operational manuals released under the Code on
             Access to Information (request "Detention policy as of August 2021",
             accessinfo.hk, response of the department); plus the Security Bureau's reply
             about guidance to adjudicators on child claimants, kept in foi-replies/.
  wayback    Older editions of the PPP and the petition guide (2013-2016) from the Internet
             Archive's captures of www.sb.gov.hk.

Application forms, FAQs, notices to claimants and the statutes are not collected.
robots.txt of every host is read first and obeyed (generic agent rules, wildcards checked).
HTTP 403/429 or a bot check ends the use of a host for the run; so do three connection
failures in a row. Sequential, 1.6 s between requests (4 s for the Internet Archive).
Existing files are skipped; hk/index.tsv, hk/foi-replies/foi-replies.tsv and
hk/not-obtained.tsv are rewritten. Python standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "hk"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE, PAUSE_IA = 1.6, 4.0
HEAD = ["file", "title", "date", "source_url", "kind", "title_en", "source", "note"]

SB = "https://www.sb.gov.hk"
TCAB_E, TCAB_C = SB + "/eng/links/tcab/", SB + "/chi/links/tcab/"
IMMD = "https://www.immd.gov.hk"
AI = "https://accessinfo.hk/request/detention_policy_as_of_august_20/response/2043/attach/"
WB = "https://web.archive.org/web/{}id_/{}"

G, P = "guidance", "procedural act"
# (source, file, url, title, date, kind, title_en, note)
ITEMS = [
    ("sb", "sb-tcab/2021-08-01_PPP_eng.pdf", TCAB_E + "2021.08.01_PPP_eng.pdf",
     "Principles, Procedures and the Practice Directions of the Torture Claims Appeal Board (seventh edition)",
     "2021-08-01", G, "", "practice directions binding the Board's adjudicators; current edition"),
    ("sb", "sb-tcab/2021-08-01_PPP_chi.pdf", TCAB_C + "2021.08.01_PPP_chi.pdf",
     "酷刑聲請上訴委員會指導原則、執行程序及常規指示（第七版）", "2021-08-01", G,
     "Principles, Procedures and the Practice Directions of the Torture Claims Appeal Board (7th ed., Chinese)", ""),
    ("sb", "sb-tcab/2021-08-01_Petition_Guide_eng.pdf", TCAB_E + "2021.08.01_Petition_Guide_eng.pdf",
     "The Practice and Procedural Guide of the Administrative Non-refoulement Claims Petition Scheme",
     "2021-08-01", G, "", "procedure of the Petition Office for claims outside the statutory scheme (CIDTP, persecution)"),
    ("sb", "sb-tcab/2021-08-01_Petition_Guide_chi.pdf", TCAB_C + "2021.08.01_Petition_Guide_chi.pdf",
     "行政免遣返聲請呈請機制常規和程序指引", "2021-08-01", G,
     "Practice and Procedural Guide of the Administrative Non-refoulement Claims Petition Scheme (Chinese)", ""),
    ("sb", "sb-tcab/2019-08-28_PPP_eng.pdf", TCAB_E + "2019.08.28_PPP_eng.pdf",
     "Principles, Procedures and the Practice Directions of the Torture Claims Appeal Board (previous edition)",
     "2019-08-28", G, "", "superseded edition, kept on the 'previous documents' page"),
    ("sb", "sb-tcab/2019-08-28_PPP_chi.pdf", TCAB_C + "2019.08.28_PPP_chi.pdf",
     "酷刑聲請上訴委員會指導原則、執行程序及常規指示（舊版）", "2019-08-28", G,
     "Principles, Procedures and Practice Directions of the Torture Claims Appeal Board (previous edition, Chinese)", ""),
    ("sb", "sb-tcab/2019-08-28_Petition_Guide_eng.pdf", TCAB_E + "2019.08.28_Petition_Guide_eng.pdf",
     "The Practice and Procedural Guide of the Administrative Non-refoulement Claims Petition Scheme (previous edition)",
     "2019-08-28", G, "", "superseded edition"),
    ("sb", "sb-tcab/2019-08-28_Petition_Guide_chi.pdf", TCAB_C + "2019.08.28_Petition_Guide_chi.pdf",
     "行政免遣返聲請呈請機制常規和程序指引（舊版）", "2019-08-28", G,
     "Practice and Procedural Guide of the Administrative Non-refoulement Claims Petition Scheme (previous edition, Chinese)", ""),
    ("sb", "sb-tcab/2014-02_Item-3A-Unified-Screening-Mechanism_English.pdf",
     TCAB_E + "Item%203A-Unified%20Screening%20Mechanism_English.pdf",
     "Unified Screening Mechanism (\"USM\")", "2014-02", G, "",
     "Security Bureau paper describing how the Immigration Department screens claims and the Board hears appeals; dated by the PDF (Feb 2014): announcement of the mechanism starting 3 March 2014"),
    ("sb", "sb-tcab/2014-02_Item-3A-Unified-Screening-Mechanism_Chinese.pdf",
     TCAB_C + "Item%203A%20-%20Unified%20Screening%20Mechanism_Chinese.pdf",
     "統一審核機制", "2014-02", G, "Unified Screening Mechanism (Chinese)", "date from the PDF"),
    ("sb", "sb-tcab/2019-08-28_hearing_arrangements_inclement_weather_eng.pdf",
     TCAB_E + "2019.08.28_hearing_arrangements_under_inclement_weather_conditions_eng.pdf",
     "Hearing Arrangements under Inclement Weather Conditions", "2019-08-28", G, "", "Board practice notice"),
    ("sb", "sb-tcab/2019-08-28_hearing_arrangements_inclement_weather_chi.pdf",
     TCAB_C + "2019.08.28_hearing_arrangements_under_inclement_weather_conditions_chi.pdf",
     "惡劣天氣情況下的聆訊安排", "2019-08-28", G, "Hearing arrangements under inclement weather conditions (Chinese)", ""),
    ("sb", "sb-tcab/2019-08-28_work_arrangements_inclement_weather_eng.pdf",
     TCAB_E + "2019.08.28_work_arrangements_under_inclement_weather_conditions_eng.pdf",
     "Work Arrangements under Inclement Weather Conditions", "2019-08-28", G, "", "Board / Petition Office practice notice"),
    ("sb", "sb-tcab/2019-08-28_work_arrangements_inclement_weather_chi.pdf",
     TCAB_C + "2019.08.28_work_arrangements_under_inclement_weather_conditions_chi.pdf",
     "惡劣天氣情況下的工作安排", "2019-08-28", G, "Work arrangements under inclement weather conditions (Chinese)", ""),

    ("immd", "immd/2022-04_Detention-Policy_S32_e.pdf", IMMD + "/pdf/Detention%20Policy_S.32_e.pdf",
     "Policy on Exercise of Detention Powers Conferred by Section 32 of the Immigration Ordinance (Cap. 115)",
     "2022-04", G, "", "published statement of the detention policy officers apply; date is the PDF creation date (April 2022)"),
    ("immd", "immd/2022-04_Detention-Policy_S32_tc.pdf", IMMD + "/pdf/Detention%20Policy_S.32_tc.pdf",
     "有關行使根據《入境條例》(第115章)第32條授權作出羈留的政策", "2022-04", G,
     "Policy on exercise of detention powers under s. 32 of the Immigration Ordinance (Chinese)", ""),
    ("immd", "immd/2022-04_Detention_policy_S37ZK_en.pdf", IMMD + "/pdf/Detention_policy_en.pdf",
     "Policy on Exercise of Detention Powers Conferred by Section 37ZK of the Immigration Ordinance (Cap.115)",
     "2022-04", G, "", "detention of non-refoulement claimants; date is the PDF creation date (April 2022)"),
    ("immd", "immd/2022-04_Detention_policy_S37ZK_tc.pdf", IMMD + "/pdf/Detention_policy_tc.pdf",
     "有關行使根據《入境條例》(第115章)第37ZK條授權作出羈留的政策", "2022-04", G,
     "Policy on exercise of detention powers under s. 37ZK of the Immigration Ordinance (Chinese)", ""),

    ("accessinfo", "foi-released/2020-10_CIC-Operational-Manual-Treatment-of-Detainees.pdf",
     AI + "2/CIC%20Operational%20Manual%20Treatment%20of%20Detainees.pdf?cookie_passthrough=1",
     "Castle Peak Bay Immigration Centre (CIC) Operational Manual: Treatment of Detainees", "2020-10", G, "",
     "released by the Immigration Department under the Code on Access to Information in 2021 (request page "
     "https://accessinfo.hk/request/detention_policy_as_of_august_20); date is the PDF creation date"),
    ("accessinfo", "foi-released/2021-09_Ma-Tau-Kok-Detention-Centre-Operational-Manual-Treatment-of-Detained-Persons.pdf",
     AI + "3/Ma%20Tau%20Kok%20Detention%20Centre%20Operational%20Manual%20Treatment%20of%20Detained%20Persons.pdf"
     "?cookie_passthrough=1",
     "Ma Tau Kok Detention Centre Operational Manual: Treatment of Detained Persons", "2021-09", G, "",
     "released by the Immigration Department under the Code on Access to Information in 2021 (same request)"),

    ("wayback", "wayback-sb/2013_PPP_English.pdf",
     WB.format("20130810043910", "http://www.sb.gov.hk:80/eng/links/tcab/PPP_English.pdf"),
     "Principles, Procedures and Practice Directions of the Torture Claims Appeal Board (2013 edition, CAT claims)",
     "2013", G, "", "Internet Archive capture of 10 Aug 2013; edition before the Unified Screening Mechanism"),
    ("wayback", "wayback-sb/2014-02-21_Petition-Guide_first-edition.pdf",
     WB.format("20160418080352", "http://www.sb.gov.hk:80/eng/links/tcab/Frist%20Edition%20of%20the%20PG%20(21%20February%202014)Final.pdf"),
     "Practice and Procedural Guide of the Petition Scheme, first edition (21 February 2014)", "2014-02-21", G, "",
     "Internet Archive capture of 18 Apr 2016"),
    ("wayback", "wayback-sb/2015-03-04_Petition-Guide_second-edition.pdf",
     WB.format("20151230200119", "http://www.sb.gov.hk/eng/links/tcab/20150304%20Second%20Edition%20of%20Petition%20Guide%20(Final)_bookmarks%20added.pdf"),
     "Practice and Procedural Guide of the Petition Scheme, second edition", "2015-03-04", G, "",
     "Internet Archive capture of 30 Dec 2015"),
    ("wayback", "wayback-sb/2015-03-04_PPP_third-edition.pdf",
     WB.format("20151230200114", "http://www.sb.gov.hk/eng/links/tcab/20150304%20Third%20Edition%20of%20PPP%20(Final).pdf"),
     "Principles, Procedures and Practice Directions of the Torture Claims Appeal Board, third edition", "2015-03-04",
     G, "", "Internet Archive capture of 30 Dec 2015"),
    ("wayback", "wayback-sb/2016_PPP.pdf",
     WB.format("20160327074600", "http://www.sb.gov.hk/eng/links/tcab/PPP.pdf"),
     "Principles, Procedures and Practice Directions of the Torture Claims Appeal Board (edition current in March 2016)",
     "2016", G, "", "Internet Archive capture of 27 Mar 2016; date is the capture year"),
    ("wayback", "wayback-sb/2016_Petition-Guide.pdf",
     WB.format("20160327074540", "http://www.sb.gov.hk/eng/links/tcab/Petition%20Guide.pdf"),
     "Practice and Procedural Guide of the Petition Scheme (edition current in March 2016)", "2016", G, "",
     "Internet Archive capture of 27 Mar 2016; date is the capture year"),
    ("wayback", "wayback-sb/2015_Item-3B-Transitional-Arrangement_English.pdf",
     WB.format("20151230200113", "http://www.sb.gov.hk/eng/links/tcab/Item%203B-Transitional%20Arrangement_English.pdf"),
     "Transitional arrangement on the commencement of the Unified Screening Mechanism", "2015", G, "",
     "Internet Archive capture of 30 Dec 2015"),
]

FOI = [  # (source, file, url, title, date, note)
    ("accessinfo", "foi-replies/2022-03_SB-reply_procedural-fairness-child-claimants.docx",
     "https://accessinfo.hk/request/procedural_fairness_consideratio/response/3081/attach/3/reply.docx?cookie_passthrough=1",
     "Security Bureau reply: procedural fairness considerations for child claimants before TCAB/NRCPO", "2022-03",
     "reply to a request for any guidelines or circulars to adjudicators on child claimants; "
     "request page https://accessinfo.hk/request/procedural_fairness_consideratio"),
]

NOT_OBTAINED = [
    ("Immigration Department internal instructions (Departmental General Orders, Immigration Service Standing Orders, "
     "visa and screening manuals)", "", "https://www.immd.gov.hk/eng/useful_information/access_to_information2.html",
     "not published; obtainable only, if at all, by request under the Code on Access to Information"),
    ("Immigration Guidelines for Entry to the HKSAR and scheme guidebooks", "",
     "https://www.immd.gov.hk/eng/services/visas/immigration-entry-guideline.html",
     "not collected: applicant information (category c), not instructions to officers"),
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
        with urllib.request.urlopen(urllib.request.Request(url, None, {"User-Agent": UA}), timeout=timeout) as r:
            data = r.read()
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
    names = ["sb", "immd", "accessinfo", "wayback"]
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
    for src, rel, url, title, date, note in FOI:
        if src in which and src not in stopped:
            try:
                fetch(rel, url, missing, title, date)
            except Refused as e:
                print(f"STOPPED {src}: {e}")
    rows = [[rel, title, date, url, kind, en or title, "sb.gov.hk" if src == "sb" else
             {"immd": "immd.gov.hk", "accessinfo": "accessinfo.hk (release by the Immigration Department)",
              "wayback": "sb.gov.hk via web.archive.org"}[src], note]
            for src, rel, url, title, date, kind, en, note in ITEMS if (OUT / rel).exists()]
    tsv(OUT / "index.tsv", HEAD, rows)
    foi = [[rel[len("foi-replies/"):], title, date, url, note] for src, rel, url, title, date, note in FOI
           if (OUT / rel).exists()]
    tsv(OUT / "foi-replies" / "foi-replies.tsv", ["file", "title", "date", "source_url", "note"], foi)
    tsv(OUT / "not-obtained.tsv", ["title", "date", "url", "reason"], missing)
    print(f"{len(rows)} rows in index.tsv; {len(foi)} FOI replies; {len(missing)} entries in not-obtained.tsv")


if __name__ == "__main__":
    main()

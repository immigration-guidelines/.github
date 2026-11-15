#!/usr/bin/env python3
"""Iceland: guidance for those who decide immigration and asylum cases.

    python3 download_is.py              all sources
    python3 download_is.py knu dmr      only the named source(s): knu dmr utl

Sources (survey of 15 November 2026, details in is/NOTES.txt):
  knu  Kærunefnd útlendingamála (Immigration and Asylum Appeals Board), https://www.knu.is/verklagsreglur/
       and https://www.knu.is/en/code-of-practice/: the board's procedural rules (verklagsreglur) and its
       criteria on suspending the legal effects of decisions, Icelandic and English versions.
  dmr  Dómsmálaráðuneytið (Ministry of Justice): the minister's guidelines to the Directorate of Immigration on
       collective (temporary) protection under art. 44 of the Foreigners Act, as published in the B section of
       the Official Gazette (Stjórnartíðindi), https://adverts.stjornartidindi.is/.
  utl  Útlendingastofnun (Directorate of Immigration), https://island.is/s/utlendingastofnun: its list of safe
       countries of origin and the designation papers with the reasons for each country, which the Directorate
       and the Appeals Board apply in the accelerated procedure.

The Directorate of Labour (Vinnumálastofnun, work permits) publishes no guidance for decision-makers: only
applicant information on island.is and the Act 97/2002 and Regulation 339/2005.

Files go to is/<source>/, unmodified. is/index.tsv and is/not-obtained.tsv are rewritten on every run;
is/NOTES.txt is not touched.

Rules kept: robots.txt of a host is read before anything else is asked of it and obeyed for '*' and for any
group naming an AI agent (wildcards handled here, not by urllib.robotparser); one request at a time, DELAY
seconds apart per host; HTTP 403/429 or three connection errors in a row end the use of that host for the
run; no retries; files already present are skipped. Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

OUT = Path(__file__).resolve().parent / "is"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.6
SLOW = {"web.archive.org": 4.0}
SOURCES = ("knu", "dmr", "utl")
INDEX_HEADER = "file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote"
KNU = "https://www.knu.is/file/"
KNU_EN = "https://www.knu.is/en/wp-content/uploads/"
GAZ = "https://adverts.stjornartidindi.is/"
CTF = "https://assets.ctfassets.net/8k0h54kbe6bj/"
SAFE_NOTE = ("designation by the Directorate of a safe country of origin, with the assessment of the country; "
             "applied by the Directorate and the Appeals Board to decide whether an application is processed in "
             "the accelerated procedure (art. 29 of Act 80/2016); scanned, no text layer; linked from "
             "https://island.is/althjodleg-vernd-rettur-og-ferill-umsokna/listi-yfir-orugg-riki")

# (source, file, title, date, url, kind, title_en, note)
DOCS = [
    # --- Appeals Board -----------------------------------------------------------------------
    ("knu", "knu/2024-12_verklagsreglur-greinargerdarfrestir-althjodleg-vernd.pdf",
     "Verklagsreglur varðandi greinargerðarfresti – alþjóðleg vernd", "2024-12",
     KNU + "2024/12/Verklagsreglur-vardandi-greinargerdarfresti-–-althjodleg-vernd.pdf", "guidance",
     "Procedural rules on deadlines for statements of appeal – international protection",
     "rules the Appeals Board set for its own staff and members"),
    ("knu", "knu/2024-12_verklagsreglur-hagsmunir-barns.pdf",
     "Verklagsreglur vegna mats á hagsmunum barns sem sækir um alþjóðlega vernd", "2024-12",
     KNU + "2024/12/Verklagsreglur-vegna-barna-2024.pdf", "guidance",
     "Procedural rules on assessing the best interests of a child applying for international protection", ""),
    ("knu", "knu/2024-12_verklagsreglur-vidtol.pdf",
     "Verklagsreglur vegna viðtala", "2024-12",
     KNU + "2024/12/Verklagsreglur-vegna-vidtala-2024.pdf", "guidance",
     "Procedural rules for interviews (hearing appellants before the board)", ""),
    ("knu", "knu/2023-04-14_vidmid-frestun-rettarahrifa-althjodleg-vernd.pdf",
     "Viðmið vegna frestunar réttaráhrifa á úrskurðum kærunefndar í málum vegna alþjóðlegrar verndar",
     "2023-04-14", KNU + "2023/06/Vidmid-vegna-FR-AV-14.3.23-060623.pdf", "guidance",
     "Criteria for suspending the legal effects of the board's rulings in international protection cases",
     "criteria with examples from earlier rulings"),
    ("knu", "knu/2025-05-19_akvordun-einn-nefndarmadur-urskurdar.pdf",
     "Ákvörðun kærunefndar útlendingamála um að fela einum nefndarmanni að úrskurða í málum, sbr. 3. mgr. 8. "
     "gr. laga um útlendinga, nr. 80/2016", "2025-05-19",
     KNU + "2025/06/Umbod-3-manna-nefnd-mai-2025-1.pdf", "procedural act",
     "Decision of the Appeals Board delegating to a single member the ruling in specified types of cases "
     "(art. 8(3) Act 80/2016)", "decision of the full board, in force from 19 May 2025; sets which case "
     "types one member decides alone"),
    ("knu", "knu/en/2024-12_rules-of-procedure-deadlines-for-submission-of-reports.pdf",
     "Rules of procedure regarding deadlines for submission of reports", "2024-12",
     KNU_EN + "2024/12/Rules-of-procedure-regarding-deadlines-for-submission-of-reports.pdf", "guidance",
     "Rules of procedure regarding deadlines for submission of reports", "English version published by the board"),
    ("knu", "knu/en/2024-12_rules-of-procedure-interviews.pdf",
     "Rules of procedure regarding interviews", "2024-12",
     KNU_EN + "2024/12/Rules-of-procedure-regarding-interviews.pdf", "guidance",
     "Rules of procedure regarding interviews", "English version published by the board"),
    ("knu", "knu/en/2024-12_rules-of-procedure-interests-of-the-child.pdf",
     "Rules of procedure regarding assessment of the interests of a child who applies for international "
     "protection", "2024-12",
     KNU_EN + "2025/01/Rules-of-procedure-regarding-assessment-of-the-interests-of-a-child-who-applies-for-"
     "international-protection-lagad.pdf", "guidance",
     "Rules of procedure regarding assessment of the interests of a child who applies for international "
     "protection", "English version published by the board"),
    ("knu", "knu/en/2020-07-17_criteria-suspension-of-legal-effects.pdf",
     "Criteria regarding suspension of legal effects of the decisions by the Immigration Appeals Board in cases "
     "of international protection", "2020-07-17",
     KNU_EN + "2020/10/Kaerunefnd-vidmid-vegna-frestunar-rettarakvaeda-enska-HBS.pdf", "guidance",
     "Criteria regarding suspension of legal effects of the decisions by the Immigration Appeals Board in cases "
     "of international protection", "English version of the 2020 criteria (the Icelandic text in force is "
     "dated 14 April 2023)"),
    # --- Ministry of Justice: guidelines on art. 44 -------------------------------------------
    ("dmr", "dmr/2024-02-22_B-220-2024_leidbeiningar-44-gr-sameiginleg-vernd.pdf",
     "Auglýsing um ákvörðun dómsmálaráðherra um að framlengja beitingu 44. gr. laga um útlendinga nr. 80/2016 "
     "(B nr. 220/2024)", "2024-02-22", GAZ + "B_nr_220_2024.pdf", "guidance",
     "Notice of the Minister of Justice extending the application of art. 44 of the Foreigners Act (collective "
     "protection, Ukraine), with the ministry's guidelines of 11 March 2022 and 29 June 2023",
     "the guidelines tell the Directorate whom the collective protection covers and how to treat applications; "
     "published as annexes to the notice in the Official Gazette, B section"),
    ("dmr", "dmr/2025-01-02_B-55-2025_leidbeiningar-44-gr-sameiginleg-vernd.pdf",
     "Auglýsing um ákvörðun dómsmálaráðherra um að framlengja beitingu 44. gr. laga um útlendinga nr. 80/2016 "
     "(B nr. 55/2025)", "2025-01-02", GAZ + "B_nr_55_2025.pdf", "guidance",
     "Notice extending art. 44 to 2 March 2027, with the guidelines of 11 March 2022 and the updated guidelines "
     "of 2 January 2025", "Official Gazette, B section"),
    ("dmr", "dmr/2026-08-20_B-905-2026_leidbeiningar-sameiginleg-vernd.pdf",
     "Auglýsing um leiðbeiningar um meðferð umsókna um sameiginlega vernd vegna fjöldaflótta frá Úkraínu "
     "(B nr. 905/2026)", "2026-08-20", GAZ + "B_nr_905_2026.pdf", "guidance",
     "Notice of new guidelines on handling applications for collective protection following the mass flight "
     "from Ukraine", "applies from 23 August 2026: no collective protection for holders of temporary protection "
     "in another European state, proof of lawful departure from Ukraine; Official Gazette, B section"),
    # --- Directorate of Immigration: safe countries of origin --------------------------------
    ("utl", "utl/listi-yfir-orugg-riki.html", "Listi yfir örugg ríki", "",
     "https://island.is/althjodleg-vernd-rettur-og-ferill-umsokna/listi-yfir-orugg-riki", "guidance",
     "List of safe countries (of origin), with a short statement of reasons for each country",
     "web page of the Directorate on island.is; undated"),
    ("utl", "utl/2015_safe-country_albania.pdf", "Albanía á lista yfir örugg ríki", "2015",
     CTF + "4Z3rr7P2VCZJsvm2Ufyjgd/a370218ec7bcc1530e26d3c0a86f6d6d/Albania-2015.pdf", "guidance",
     "Albania on the list of safe countries", SAFE_NOTE.replace("; scanned, no text layer", "")),
    ("utl", "utl/2016_safe-country_north-macedonia.pdf", "Norður-Makedónía á lista yfir örugg upprunaríki", "2016",
     CTF + "4NJSBeIstfomOYXfFObJek/ab38de55c3936afd6e97766d6910deae/Maked_n_a-2016.pdf", "guidance",
     "North Macedonia on the list of safe countries of origin", SAFE_NOTE),
    ("utl", "utl/2016_safe-country_serbia.pdf", "Serbía á lista yfir örugg upprunaríki", "2016",
     CTF + "j9jclXAZiPzZEmSOFZ94X/20a1b873c3c3ced4d04632965dea07df/Serb_a_2016.pdf", "guidance",
     "Serbia on the list of safe countries of origin", SAFE_NOTE),
    ("utl", "utl/2017_safe-country_georgia.pdf", "Georgía á lista yfir örugg upprunaríki", "2017",
     CTF + "6Mx3h8qxTdWzoC9aWp2Ch/939e44e0176082008880f2b1b92d6f2f/Georgia-2017.pdf", "guidance",
     "Georgia on the list of safe countries of origin", SAFE_NOTE),
    ("utl", "utl/2017_safe-country_kosovo.pdf", "Kósovó á lista yfir örugg upprunaríki", "2017",
     CTF + "4fVsGdvJWOL1z0xTgrsEEO/6f24dca4eff3cd44f1c44a2eede32d84/K_s_v__2017.pdf", "guidance",
     "Kosovo on the list of safe countries of origin", SAFE_NOTE),
    ("utl", "utl/2018_safe-country_bosnia-and-herzegovina.pdf", "Bosnía og Hersegóvína á lista yfir örugg upprunaríki",
     "2018", CTF + "44oEySrBYioDsWtthVlWL1/af98fa6b78e1841278d420f8f344acf6/Bosn_a_og_Herseg_v_na_2018.pdf",
     "guidance", "Bosnia and Herzegovina on the list of safe countries of origin", SAFE_NOTE),
    ("utl", "utl/2018_safe-country_moldova.pdf", "Moldóva á lista yfir örugg upprunaríki", "2018",
     CTF + "JUGpRI8cnINVOk3WxroyT/1f336664694fba203f4ad59300f669b7/Mold_va_2018.pdf", "guidance",
     "Moldova on the list of safe countries of origin", SAFE_NOTE),
    ("utl", "utl/2018_safe-country_montenegro.pdf", "Svartfjallaland á lista yfir örugg upprunaríki", "2018",
     CTF + "1VoEiNXRjzFL7hDXMv0I28/b0426531ebfc7dc4f281919e640e8da4/Svartfjallaland_2018.pdf", "guidance",
     "Montenegro on the list of safe countries of origin", SAFE_NOTE),
]

# Known to exist but not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Útlendingastofnun: internal procedural rules (verklagsreglur) and work instructions for residence-permit, "
     "visa and protection cases", "", "https://island.is/s/utlendingastofnun",
     "not published: the Directorate's pages on island.is hold applicant information, forms, statistics and news "
     "only; the National Audit Office report 'Útlendingastofnun – málsmeðferð og verklagsreglur' (Nov. 2018) "
     "describes internal rules that have never been made public"),
    ("Vinnumálastofnun: internal criteria or instructions for deciding temporary work permits (Act 97/2002, "
     "Regulation 339/2005)", "", "https://island.is/saekja-um-atvinnuleyfi",
     "not published: island.is holds applicant information and links to the Act and the Regulation only"),
    ("Leiðbeiningar dómsmálaráðuneytisins um beitingu 44. gr. laga um útlendinga, 11 March 2022 and 29 June "
     "2023 (as separate documents)", "2022-03-11", "https://adverts.stjornartidindi.is/B_nr_220_2024.pdf",
     "not published separately; their text is in the annexes of notice B 220/2024 (saved)"),
    ("Kærunefnd útlendingamála: earlier versions of the procedural rules (before December 2024)", "",
     "https://web.archive.org/web/2023/https://www.knu.is/verklagsreglur/",
     "no archived copy fetched: the Internet Archive refused three requests in a row (connection refused, "
     "HTTP 503 'temporarily offline') on 15 November 2026 and was given up"),
]


def index_row(d):
    source, name, title, date, url, kind, title_en, note = d
    return [name, title, date, url, kind, title_en, note]


# ----------------------------------------------------------------------------------------------
# Engine (same in download_be_regions.py, download_is.py, download_mt.py, download_cy.py)
# ----------------------------------------------------------------------------------------------
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "perplexitybot", "bytespider", "ai")
MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK", ".doc": b"\xd0\xcf\x11\xe0"}
BAD_HTML = re.compile(rb"captcha|cf-chl|just a moment|access denied|attention required|"
                      rb"enable javascript and cookies|request unsuccessful|incapsula", re.I)

_robots, _last, _closed, _resets, _delay = {}, {}, {}, {}, {}


def _match(pat, path):
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pat)
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.match(rx, path) is not None


def _pause(host):
    d = _delay.get(host, SLOW.get(host, DELAY))
    w = d - (time.time() - _last.get(host, 0))
    if w > 0:
        time.sleep(w)


def _open(url):
    host = urlsplit(url).netloc
    _pause(host)
    try:
        req = urllib.request.Request(quote(url, safe=":/?&=%#+,;@()~!$'*[]"), headers={"User-Agent": UA})
        with OPENER.open(req, timeout=120) as r:
            data = r.read()
        _resets[host] = 0
        return 200, data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            _closed[host] = f"HTTP {e.code}: host not used any further in this run"
        return e.code, b""
    except Exception as e:                                   # noqa: BLE001 - no retry
        _resets[host] = _resets.get(host, 0) + 1
        if _resets[host] >= 3:
            _closed[host] = "three connection errors in a row: host given up"
        return 0, str(e).encode()
    finally:
        _last[host] = time.time()


def robots(host):
    """Read robots.txt of a host once, before anything else is asked of it. Returns the rule
    groups that apply to this script: '*' and every group naming an AI agent."""
    if host in _robots:
        return _robots[host]
    code, data = _open(f"https://{host}/robots.txt")
    groups = {}
    if code == 200 and b"<html" not in data[:600].lower():
        agents, in_agents = [], False
        for line in data.decode("utf-8", "replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if not in_agents:
                    agents = []
                agents.append(v.lower())
                in_agents = True
            elif k in ("allow", "disallow", "crawl-delay"):
                in_agents = False
                for a in agents:
                    if a == "*" or a in AI_AGENTS:
                        groups.setdefault(a, []).append((k, v))
    elif code in (200, 404):
        pass                                                 # no robots.txt: nothing is excluded
    else:
        _closed.setdefault(host, f"robots.txt could not be read (HTTP {code}): host not used")
    _robots[host] = groups
    for rules in groups.values():
        for k, v in rules:
            if k == "crawl-delay":
                try:
                    _delay[host] = max(float(v), SLOW.get(host, DELAY))
                except ValueError:
                    pass
    return groups


def allowed(url):
    u = urlsplit(url)
    groups = robots(u.netloc)
    if u.netloc in _closed:
        return _closed[u.netloc]
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    for name, rules in groups.items():
        best, ok = -1, True
        for k, v in rules:
            if k == "crawl-delay" or not v:
                continue
            if _match(v, path) and (len(v) > best or (len(v) == best and k == "allow")):
                best, ok = len(v), k == "allow"
        if not ok:
            return f"excluded by robots.txt of {u.netloc} (rules for '{name}')"
    return ""


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        why = allowed(newurl)
        if why:
            raise urllib.error.URLError(f"redirect to {newurl}: {why}")
        _pause(urlsplit(newurl).netloc)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_Redirect())


def save(url, dest):
    """Fetch url into dest unless it exists. Returns '' on success, otherwise the reason."""
    if dest.exists() and dest.stat().st_size > 0:
        return ""
    why = allowed(url)
    if why:
        return why
    code, data = _open(url)
    if code != 200:
        return f"HTTP {code}" if code else "download failed: " + data.decode("utf-8", "replace")[:120]
    ext = dest.suffix.lower()
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        return f"server did not return a {ext[1:]} file"
    if ext in (".html", ".htm") and (len(data) < 2000 or BAD_HTML.search(data[:20000])):
        return "server returned an error, login or bot-check page"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  saved {dest.relative_to(OUT)} ({len(data):,} bytes)")
    return ""


def main(argv):
    wanted = set(argv)
    unknown = wanted - set(SOURCES)
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(sorted(unknown))}; known: {', '.join(sorted(SOURCES))}")
    OUT.mkdir(parents=True, exist_ok=True)
    reasons = {}
    for d in DOCS:
        source, name, url = d[0], d[1], d[4]
        if wanted and source not in wanted:
            continue
        why = save(url, OUT / name)
        if why:
            print(f"  NOT SAVED {name}: {why}")
            reasons[name] = why
    present = [d for d in DOCS if (OUT / d[1]).exists()]
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write(INDEX_HEADER + "\n")
        for d in sorted(present, key=lambda d: d[1]):
            f.write("\t".join(index_row(d)) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for d in DOCS:
            if not (OUT / d[1]).exists():
                f.write("\t".join([d[2], d[3], d[4], reasons.get(d[1], "not downloaded yet (source not run)")]) + "\n")
        for row in NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    kinds = {}
    for d in present:
        kinds[d[5]] = kinds.get(d[5], 0) + 1
    print(f"{OUT.name}: {len(present)} of {len(DOCS)} documents present ({kinds}); "
          f"{len(NOT_OBTAINED) + len(DOCS) - len(present)} rows in not-obtained.tsv")


if __name__ == "__main__":
    main(sys.argv[1:])

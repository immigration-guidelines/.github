#!/usr/bin/env python3
"""Latvia: the few immigration instructions ever published for officials, plus the Cabinet
regulations that serve as the working manual today.

    python3 download_lv.py                 # both groups
    python3 download_lv.py instructions    # only the historical agency instructions (guidance)
    python3 download_lv.py regulations     # only the Cabinet regulations (procedural acts)

Latvia publishes no current case-officer guidance. The Office of Citizenship and Migration
Affairs (PMLP) and the State Border Guard (VRS) post only their statutes of organisation
(nolikums / reglaments), ethics codes and service standards. Between 1995 and 2005, however,
the Ministry of the Interior, PMLP and VRS published a series of instructions (instrukcija) to
their officials in the official gazette Latvijas Vestnesis; all were repealed by 2017. Those are
the "guidance" rows here. The "procedural act" rows are a hand-picked set of current Cabinet
regulations that lay down how residence permit, visa, invitation, employment and expulsion
cases are processed.

Source: likumi.lv, the official consolidated-law portal of the publisher Latvijas Vestnesis.
Each act's page https://likumi.lv/ta/id/<id> is saved unmodified (HTML). robots.txt of
likumi.lv is read first and every path is checked against it (search pages and print views are
disallowed and not used). Crawl-delay is 1 s; 2 s is used.

Existing files are skipped, so the script can be re-run. index.tsv and not-obtained.tsv are
rewritten from the list below and the files present. Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "lv"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
HOST = "https://likumi.lv"
DELAY = 2.0
AI_AGENTS = ("claudebot", "claude-web", "anthropic-ai", "gptbot", "chatgpt-user", "ccbot")

G, P = "guidance", "procedural act"

# group, likumi.lv id, date (adoption), file slug, kind, title (original), English gloss, note
DOCS = [
    ("instructions", 211322, "1995-04-17", "IeM-instrukcija_arvalstnieku-piespiedu-izraidisanas-kartiba", G,
     "Instrukcija ar ārvalstnieku un bezvalstnieku piespiedu izraidīšanas kārtību",
     "Instruction on the procedure for the forced expulsion of foreigners and stateless persons",
     "Ministry of the Interior instruction (Latvijas Vēstnesis 63, 25.04.1995); repealed"),
    ("instructions", 28074, "2001-07-27", "IeM-rikojums-510_instrukcija-par-ielugumiem-privatas-vizas-iegusanai", G,
     "Par instrukcijas \"Instrukcija par Ielūgumu Latvijas Republikas privātās vīzas iegūšanai noformēšanas, apstiprināšanas, pārsūtīšanas un anulēšanas kārtību\" apstiprināšanu",
     "Order approving the Instruction on drawing up, approving, forwarding and cancelling invitations for a private visa (PMLP procedure for invitations)",
     "Ministry of the Interior order No 510, instruction annexed; in force 27.07.2001 - 01.02.2003"),
    ("instructions", 70345, "2002-12-28", "IeM-rikojums-957_instrukcija-par-ielugumu-noformesanas-un-apstiprinasanas-kartibu", G,
     "Par instrukcijas \"Instrukcija par ielūgumu noformēšanas un apstiprināšanas kārtību\" apstiprināšanu",
     "Order approving the Instruction on the procedure for drawing up and approving invitations",
     "Ministry of the Interior order No 957, instruction annexed; repealed"),
    ("instructions", 77985, "2003-08-01", "IeM-instrukcija-3_vizu-instrukcija", G,
     "Vīzu instrukcija",
     "Visa Instruction: how PMLP applies the Immigration Law and the Visa Regulations in visa cases",
     "Ministry of the Interior instruction No 3 (in force 14.08.2003); amended 2004 and 2006; repealed. Text as last consolidated on likumi.lv"),
    ("instructions", 87908, "2004-04-27", "VRS-instrukcija-2_personu-un-transportlidzeklu-robezkontroles-organizacija", G,
     "Instrukcija par personu un transportlīdzekļu robežkontroles organizāciju",
     "Instruction on the organisation of border checks on persons and vehicles (including refusal of entry)",
     "State Border Guard instruction No 2; in force 01.05.2004 - 24.02.2017"),
    ("instructions", 91633, "2004-07-23", "VRS-instrukcija-10_atteikums-es-eez-pilsoniem-iecelot", G,
     "Instrukcija par atteikumu Eiropas Savienības, citu Eiropas Ekonomikas zonas valstu un Šveices Konfederācijas pilsoņiem ieceļot Latvijas Republikā",
     "Instruction on refusing entry to nationals of EU, EEA states and Switzerland",
     "State Border Guard instruction No 10; in force 29.07.2004 - 06.04.2005"),
    ("instructions", 92929, "2004-08-24", "VRS-instrukcija-13_vizu-izsniegsana-robezkontroles-punktos", G,
     "Par Latvijas Republikas vīzu izsniegšanu, reģistrēšanu, atcelšanu un anulēšanu robežkontroles punktos",
     "On issuing, registering, cancelling and annulling Latvian visas at border crossing points",
     "State Border Guard instruction No 13; in force 01.09.2004 - 07.06.2011"),
    ("instructions", 94532, "2004-09-29", "PMLP-instrukcija-10_bezvalstnieku-instrukcija", G,
     "Bezvalstnieku instrukcija",
     "Stateless Persons Instruction: PMLP procedure for determining and documenting stateless status",
     "PMLP instruction No 10; in force 06.10.2004 - 23.05.2008"),
    ("instructions", 94902, "2004-10-11", "VRS-instrukcija-18_pirkstu-nospiedumi-patveruma-mekletajiem", G,
     "Par Valsts robežsardzes amatpersonu darbību, noņemot pirkstu nospiedumus patvēruma meklētājiem un nelegālajiem imigrantiem",
     "On the action of Border Guard officers when fingerprinting asylum seekers and illegal immigrants (Eurodac)",
     "State Border Guard instruction No 18; in force 11.10.2004 - 22.01.2008"),
    ("instructions", 97782, "2004-12-10", "VRS-instrukcija-23_ja-arzemnieks-pieprasa-patverumu", G,
     "Par Valsts robežsardzes amatpersonu darbību, ja ārzemnieks pieprasa patvērumu Latvijas Republikā",
     "On the action of Border Guard officers when a foreigner applies for asylum in Latvia (2004 version)",
     "State Border Guard instruction No 23; in force 15.12.2004 - 07.12.2005"),
    ("instructions", 98905, "2005-01-03", "VRS-instrukcija-1_arzemnieka-piespiedu-izraidisana", G,
     "Par ārzemnieka piespiedu izraidīšanu",
     "On the forced expulsion of a foreigner",
     "State Border Guard instruction No 1; in force 03.01.2005 - 13.08.2009"),
    ("instructions", 102037, "2005-02-15", "VRS-instrukcija-3_parsniegts-vizas-vai-uzturesanas-atlaujas-termins", G,
     "Par Valsts robežsardzes amatpersonu rīcību robežkontroles vietā, konstatējot, ka ārzemniekam, kurš vēlas izceļot no Latvijas Republikas, ir pārsniegts vīzas vai uzturēšanās atļaujas derīguma termiņš",
     "On the action of Border Guard officers at a border check on finding that a departing foreigner has overstayed a visa or residence permit",
     "State Border Guard instruction No 3; in force 23.02.2005 - 28.07.2006"),
    ("instructions", 105040, "2005-03-30", "VRS-instrukcija-6_atteikums-es-eez-pilsonim-iecelot", G,
     "Par atteikumu Eiropas Savienības dalībvalsts, citas Eiropas Ekonomikas zonas valsts un Šveices Konfederācijas pilsonim ieceļot Latvijas Republikā",
     "On refusing entry to a national of an EU member state, another EEA state or Switzerland (replaced instruction No 10 of 2004)",
     "State Border Guard instruction No 6; in force 06.04.2005 - 06.06.2007"),
    ("instructions", 122856, "2005-12-01", "VRS-instrukcija-31_ja-arzemnieks-pieprasa-patverumu", G,
     "Par Valsts robežsardzes amatpersonu darbību, ja ārzemnieks pieprasa patvērumu Latvijas Republikā",
     "On the action of Border Guard officers when a foreigner applies for asylum in Latvia (2005 version)",
     "State Border Guard instruction No 31; in force 07.12.2005 - 24.08.2011; amended 2006 and 2008. Text as last consolidated on likumi.lv"),
    # current Cabinet regulations that are the working manual (procedural acts)
    ("regulations", 212441, "2010-06-21", "MK-564_uzturesanas-atlauju-noteikumi", P,
     "Uzturēšanās atļauju noteikumi",
     "Residence Permit Regulations (Cabinet Regulation No 564): documents, examination and issue of residence permits, including the EU Blue Card",
     "Cabinet regulation; consolidated version in force on the download date"),
    ("regulations", 235770, "2011-08-30", "MK-676_vizu-noteikumi", P,
     "Vīzu noteikumi",
     "Visa Regulations (Cabinet Regulation No 676): national (long-stay) visas, procedure and grounds",
     "Cabinet regulation; consolidated version; lapses 02.12.2027 under the new Immigration Law"),
    ("regulations", 264304, "2014-01-28", "MK-55_noteikumi-par-arzemnieku-nodarbinasanu", P,
     "Noteikumi par ārzemnieku nodarbināšanu",
     "Regulations on the employment of foreigners (Cabinet Regulation No 55): employment rights, State Employment Agency opinion on recruiting a foreigner",
     "Cabinet regulation; consolidated version; lapses 02.12.2027"),
    ("regulations", 212362, "2010-06-21", "MK-552_ielugumu-apstiprinasanas-un-uzaicinajumu-noformesanas-kartiba", P,
     "Ielūgumu apstiprināšanas un uzaicinājumu noformēšanas kārtība",
     "Procedure for approving invitations and drawing up invitation letters (Cabinet Regulation No 552)",
     "Cabinet regulation; consolidated version; lapses 02.12.2027"),
    ("regulations", 175980, "2008-05-26", "MK-365_pieejamas-informacijas-parbaude-vizas-vai-uzturesanas-atlaujas-pieprasijuma", P,
     "Kārtība, kādā veic pieejamās informācijas pārbaudi, izskatot ārzemnieka vīzas vai uzturēšanās atļaujas pieprasījuma dokumentus",
     "Procedure for checking available information when examining a foreigner's visa or residence permit application (Cabinet Regulation No 365)",
     "Cabinet regulation; consolidated version; lapses 02.12.2027"),
    ("regulations", 290808, "2017-04-25", "MK-225_arzemniekam-nepieciesamie-finansu-lidzekli", P,
     "Noteikumi par ārzemniekam nepieciešamo finanšu līdzekļu apmēru un finanšu līdzekļu esības konstatēšanu",
     "Regulations on the amount of means of subsistence a foreigner needs and how their existence is established (Cabinet Regulation No 225)",
     "Cabinet regulation; consolidated version; lapses 02.12.2027"),
    ("regulations", 232351, "2011-06-21", "MK-454_arzemnieka-piespiedu-izraidisana-izcelosanas-dokuments", P,
     "Noteikumi par ārzemnieka piespiedu izraidīšanu, izceļošanas dokumentu un tā izsniegšanu",
     "Regulations on the forced expulsion of a foreigner and the exit document (Cabinet Regulation No 454)",
     "Cabinet regulation; consolidated version; lapses 02.12.2027"),
    ("regulations", 82267, "2003-12-16", "MK-707_nepilngadigi-arzemnieki-bez-pavadibas", P,
     "Kārtība, kādā Latvijas Republikā ieceļo un uzturas nepilngadīgi ārzemnieki bez vecāku vai aizbildņu pavadības",
     "Procedure for entry and stay of unaccompanied minor foreigners (Cabinet Regulation No 707)",
     "Cabinet regulation; consolidated version; lapses 02.12.2027"),
]

NOT_OBTAINED = [
    ("Current internal regulations, working procedures and methodological guidance of the Office of Citizenship and Migration Affairs (PMLP) on examining visa, residence permit, EU-citizen, stateless and asylum cases", "",
     "https://www.pmlp.gov.lv/lv/normativie-akti",
     "not published: PMLP posts only its statute (nolikums), organisational rules (reglaments No 8 of 24.08.2020, structure and competences only), ethics code and client-service standard; no instruction of PMLP on case handling appears on likumi.lv after the Stateless Persons Instruction (repealed 2008). Obtainable only by a request under the Freedom of Information Law"),
    ("Current internal instructions of the State Border Guard (VRS) on border checks and refusal of entry, asylum applications at the border, detention, return and forced expulsion", "",
     "https://www.rs.gov.lv/lv/ieksejie-normativie-akti",
     "not published: the VRS page of internal normative acts lists only organisational rules of the service and its regional boards, ethics, whistle-blowing, data-protection and personnel documents (plus a copy of the EU Visa Code); the last published VRS instruction on these matters is No 31 of 2005 (repealed 2011)"),
    ("State Employment Agency (NVA) internal procedure for the opinion on recruiting a foreigner (labour-market test) and vacancy registration", "",
     "https://www.nva.gov.lv/lv/normativie-akti",
     "not published: nva.gov.lv lists statutes, Cabinet regulations, its own statute and organisational rules, and employer information only"),
]


class Blocked(Exception):
    pass


_last = [0.0]


def get(url):
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        _last[0] = time.time()
        if e.code in (401, 403, 429):
            raise Blocked(f"HTTP {e.code} for {url}") from e
        raise
    _last[0] = time.time()
    return data


def robots_rules():
    """Disallow patterns for '*' and for any AI agent named in robots.txt, as regexes (wildcards handled)."""
    rules, active = [], False
    for line in get(HOST + "/robots.txt").decode("utf-8", "replace").splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        if key.lower() == "user-agent":
            active = val == "*" or any(a in val.lower() for a in AI_AGENTS)
        elif key.lower() == "disallow" and active and val:
            rx = "".join(".*" if c == "*" else re.escape(c) for c in val.rstrip("$"))
            rules.append(re.compile("^" + rx + ("$" if val.endswith("$") else "")))
    return rules


def fname(d):
    return f"{d[2]}_{d[3]}.html"


def main():
    groups = set(sys.argv[1:]) or {"instructions", "regulations"}
    bad = groups - {"instructions", "regulations"}
    if bad:
        sys.exit(f"unknown source(s): {', '.join(sorted(bad))}; use instructions and/or regulations")
    OUT.mkdir(exist_ok=True)
    failed = []
    todo = [d for d in DOCS if d[0] in groups and not (OUT / fname(d)).exists()]
    if todo:
        try:
            rules = robots_rules()
        except Exception as e:                                      # noqa: BLE001
            sys.exit(f"could not read {HOST}/robots.txt ({e}); nothing fetched")
        try:
            for d in todo:
                path = f"/ta/id/{d[1]}"
                if any(r.search(path) for r in rules):
                    failed.append((d[5], d[2], HOST + path, "disallowed by robots.txt of likumi.lv"))
                    continue
                try:
                    data = get(HOST + path)
                except Blocked:
                    raise
                except Exception as e:                              # noqa: BLE001 - report, no retry
                    print(f"  FAILED {d[1]}: {e}")
                    failed.append((d[5], d[2], HOST + path, f"download failed: {e}"))
                    continue
                text = data.decode("utf-8", "replace")
                if "Tiesību akta pase" not in text or 'class="doc-body"' not in text:
                    print(f"  NOT AN ACT PAGE, skipped: {d[1]}")
                    failed.append((d[5], d[2], HOST + path, "server did not return the act page"))
                    continue
                (OUT / fname(d)).write_bytes(data)
                print(f"  saved {fname(d)} ({len(data):,} bytes)")
        except Blocked as e:
            print(f"STOPPED: {e}. likumi.lv not used further in this run.")

    present = 0
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        for d in DOCS:
            if not (OUT / fname(d)).exists():
                if not any(r[2].endswith(f"/{d[1]}") for r in failed):
                    failed.append((d[5], d[2], f"{HOST}/ta/id/{d[1]}", "not downloaded in this run"))
                continue
            present += 1
            f.write("\t".join([fname(d), d[5], d[2], f"{HOST}/ta/id/{d[1]}", d[4], d[6],
                               d[7] + "; likumi.lv act page saved as published (HTML); date = adoption date"]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for row in failed + NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    print(f"lv: {present} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

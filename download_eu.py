#!/usr/bin/env python3
"""Download EU-level operational handbooks and guidance on visa, border, return,
residence and asylum case handling into ./eu/.

    ./download_eu.py              everything
    ./download_eu.py commission   European Commission handbooks, notices and guidelines
    ./download_eu.py euaa         EU Agency for Asylum practical guides, tools and guidance
    ./download_eu.py contactgroup Commission "Contact Group Legal Migration" minutes and discussion papers
    ./download_eu.py other        Council Schengen catalogues, Frontex and FRA practitioner handbooks
    ./download_eu.py euaa-list    only show which EUAA publications the title filter keeps or skips

Files already downloaded are skipped, so the script can be re-run. eu/index.tsv
lists what was saved and where it came from. Standard library only; requests are
sequential with a pause between them. A 403/429 answer or a non-PDF reply is
reported and the file is skipped (no retries against a site that refuses).

Commission documents published in the Official Journal are fetched from the
Publications Office repository (publications.europa.eu/resource/celex/...),
which is the machine interface behind EUR-Lex.
"""
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "eu"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 1.0                       # seconds between requests
MAX_FILES = 1000
MAX_BYTES = 1_000_000_000

HA = "https://home-affairs.ec.europa.eu"
CELLAR = "http://publications.europa.eu/resource/celex/"
EURLEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:"
CONS = "https://data.consilium.europa.eu/doc/document/{}/en/pdf"

# (file name, title, date/version, source)
# source is a URL, or "celex:<number>" for Official Journal / COM documents.
COMMISSION = [
    # --- visas
    ("visa-code-handbook-I_C-2024-4319-annex.pdf",
     "Handbook for the processing of visa applications and the modification of issued visas "
     "(Visa Code Handbook I) - annex to Commission Implementing Decision C(2024) 4319",
     "26.6.2024, C(2024) 4319 final (consolidated)",
     HA + "/document/download/1d79f44d-49ba-4847-951e-129f924b1051_en"
          "?filename=Commission%20Implementing%20Decision%20C%282024%29%204319-annex_en.PDF"),
    ("visa-code-handbook-II_C-2020-1764-annex.pdf",
     "Handbook for the administrative management of visa processing and local Schengen cooperation "
     "(Visa Code Handbook II) - annex to Commission Implementing Decision C(2020) 1764",
     "25.3.2020, C(2020) 1764 final",
     HA + "/document/download/da7dfaa7-9a4e-493d-ac40-6c2f412bc94c_en"
          "?filename=c-2020-1764-commission-implementing-decision_en.pdf"),
    ("visa-guidelines-russian-applicants_C-2022-6596.pdf",
     "Communication providing guidelines on general visa issuance in relation to Russian applicants "
     "following Council Decision (EU) 2022/1500 (Council cover note 12351/22)",
     "9.9.2022, C(2022) 6596 final",
     "https://data.consilium.europa.eu/doc/document/ST-12351-2022-INIT/en/pdf"),
    ("visa-and-border-guidelines-russian-citizens_C-2022-7111.pdf",
     "Communication updating guidelines on general visa issuance in relation to Russian applicants and "
     "providing guidelines on controls of Russian citizens at the external borders (Council cover note 13054/22)",
     "30.9.2022, C(2022) 7111 final",
     "https://data.consilium.europa.eu/doc/document/ST-13054-2022-INIT/en/pdf"),
    # --- borders
    ("schengen-handbook-border-guards_C-2022-7591-annex.pdf",
     "Practical Handbook for Border Guards (Schengen Handbook) - annex to Commission Recommendation C(2022) 7591",
     "28.10.2022, C(2022) 7591 final",
     HA + "/document/download/8cea3074-8a87-489c-b9c2-d926101ac621_en"
          "?filename=Practical%20handbook%20for%20border%20guards_en.pdf"),
    ("schengen-handbook-annex-01_national-services.pdf",
     "Schengen Handbook Annex 1: list of national services responsible for border control", "",
     HA + "/document/download/63542847-2d74-4c4b-a8eb-4ed1cee8f721_en?filename=handbook-annex-01_en.pdf"),
    ("schengen-handbook-annex-04_border-crossing-points.pdf",
     "Schengen Handbook Annex 4: list of border crossing points", "",
     HA + "/document/download/43debf3f-adfc-4f7a-908a-49fe29f65aa5_en?filename=handbook-annex-04_en.pdf"),
    ("schengen-handbook-annex-20_part-1.pdf",
     "Schengen Handbook Annex 20: specimens of cards issued by foreign ministries to diplomatic and consular "
     "staff and their families (consolidated version, part 1)", "",
     HA + "/document/download/96b41fa2-1ea6-4090-9b05-73ef4f0d95e1_en?filename=Handbook-annex%2020-part%201_en.pdf"),
    ("schengen-handbook-annex-20_part-2.pdf",
     "Schengen Handbook Annex 20: specimens of cards issued by foreign ministries to diplomatic and consular "
     "staff and their families (consolidated version, part 2)", "",
     HA + "/document/download/7a3324a3-12bc-4e38-add7-7800a80ae64b_en?filename=handbook-annex_20_EN_part%203_0.pdf"),
    ("schengen-handbook-annex-22_residence-permits.pdf",
     "Schengen Handbook Annex 22: list of residence permits issued by Member States", "",
     HA + "/document/download/0c3f53c2-624b-409c-aae8-8fc11031dff3_en?filename=handbook-annex_22_EN.pdf"),
    ("schengen-handbook-annex-23_residence-permit-specimens.pdf",
     "Schengen Handbook Annex 23: list of specimen of residence permits", "",
     HA + "/document/download/d5e78a92-4e8f-4628-8eac-3095d4de89e3_en"
          "?filename=List%20of%20specimen%20of%20residence%20permits%20Handbook%20Annex%2023.pdf"),
    ("schengen-handbook-annex-25_reference-amounts.pdf",
     "Schengen Handbook Annex 25: reference amounts for crossing the external borders (consolidated version)", "",
     HA + "/document/download/97f68496-caf8-47b0-8017-bdd4aad90303_en?filename=handbook-annex-25_en_0.pdf"),
    ("schengen-reference-amounts-overview.pdf",
     "Reference amounts for crossing the external borders - overview table", "",
     HA + "/document/download/9bf9a98f-3bd1-4e14-9b39-c9087a08a32f_en?filename=Reference_amounts_table.pdf"),
    ("border-guidelines-eu-ukraine-borders_2022-C-104-I-01.pdf",
     "Commission Communication providing operational guidelines for external border management to facilitate "
     "border crossings at the EU-Ukraine borders (2022/C 104 I/01)",
     "OJ C 104 I, 4.3.2022", "celex:52022XC0304(10)"),
    # --- return
    ("return-handbook_recommendation-2017-2338.pdf",
     "Commission Recommendation (EU) 2017/2338 establishing a common 'Return Handbook' to be used by Member "
     "States' competent authorities when carrying out return-related tasks",
     "16.11.2017, OJ L 339, 19.12.2017", "celex:32017H2338"),
    # --- legal migration / free movement
    ("family-reunification-guidance_COM-2014-210.pdf",
     "Communication on guidance for application of Directive 2003/86/EC on the right to family reunification",
     "3.4.2014, COM(2014) 210 final", "celex:52014DC0210"),
    ("free-movement-guidance_C-2023-1392.pdf",
     "Commission Notice - Guidance on the right of free movement of EU citizens and their families "
     "(Directive 2004/38/EC)",
     "OJ C, C/2023/1392, 22.12.2023", "celex:52023XC01392"),
    ("withdrawal-agreement-citizens-rights-guidance-note_C-2020-2939.pdf",
     "Commission Notice - Guidance Note relating to the EU-UK Withdrawal Agreement, Part Two - Citizens' rights",
     "OJ C 173, 20.5.2020, C(2020) 2939", "celex:52020XC0520(05)"),
    ("free-movement-guidance-2009_COM-2009-313_SUPERSEDED.pdf",
     "Communication on guidance for better transposition and application of Directive 2004/38/EC "
     "[SUPERSEDED by Commission Notice C/2023/1392]",
     "2.7.2009, COM(2009) 313 final", "celex:52009DC0313"),
    ("marriages-of-convenience-handbook_SWD-2014-284.pdf",
     "Handbook on addressing the issue of alleged marriages of convenience between EU citizens and non-EU "
     "nationals in the context of EU law on free movement of EU citizens (staff working document)",
     "26.9.2014, SWD(2014) 284 final", "celex:52014SC0284"),
    ("blue-card-implementation-report_COM-2014-287_REPORT.pdf",
     "Communication on the implementation of Directive 2009/50/EC (EU Blue Card) [REPORT, not guidance; "
     "concerns the old Directive, repealed by Directive (EU) 2021/1883]",
     "22.5.2014, COM(2014) 287 final", "celex:52014DC0287"),
    ("single-permit-implementation-report_COM-2019-160_REPORT.pdf",
     "Report on Directive 2011/98/EU (Single Permit) [REPORT, not guidance; Directive since recast as (EU) 2024/1233]",
     "29.3.2019, COM(2019) 160 final", "celex:52019DC0160"),
    ("long-term-residents-implementation-report_COM-2019-161_REPORT.pdf",
     "Report on the implementation of Directive 2003/109/EC (long-term residents) [REPORT, not guidance]",
     "29.3.2019, COM(2019) 161 final", "celex:52019DC0161"),
    ("family-reunification-implementation-report_COM-2019-162_REPORT.pdf",
     "Report on the implementation of Directive 2003/86/EC (family reunification) [REPORT, not guidance]",
     "29.3.2019, COM(2019) 162 final", "celex:52019DC0162"),
    # --- Schengen evaluation best practices, SIS
    ("schengen-compendium-of-best-practices-2026_SWD.pdf",
     "Compendium of best practices identified in the framework of the Schengen evaluation - staff working "
     "document accompanying the 2026 State of Schengen Report (Council cover note 9302/26 ADD 1)",
     "2026-05-19", CONS.format("ST-9302-2026-ADD-1")),
    ("sirene-manual_decision-2017-1528_SUPERSEDED.pdf",
     "Commission Implementing Decision (EU) 2017/1528 replacing the Annex to Implementing Decision 2013/115/EU "
     "on the SIRENE Manual [SUPERSEDED: the current SIRENE Manuals, C(2021) 7900/7901 and later replacements, "
     "were not found in a public source]",
     "31.8.2017, OJ L 231, 7.9.2017", "celex:32017D1528"),
    # --- temporary protection (Ukraine)
    ("temporary-protection-operational-guidelines_2022-C-126-I-01.pdf",
     "Commission Communication on operational guidelines for the implementation of Council Implementing "
     "Decision (EU) 2022/382 (temporary protection, Ukraine) (2022/C 126 I/01)",
     "OJ C 126 I, 21.3.2022", "celex:52022XC0321(03)"),
    ("temporary-protection-faq-interpretation.pdf",
     "Frequently asked questions received on the interpretation of the Temporary Protection Directive and "
     "Council Implementing Decision 2022/382",
     "2022-07",
     HA + "/system/files/2022-07/Frequently%20asked%20questions%20received%20on%20the%20interpretation%20of%20"
          "the%20Temporary%20Protection%20Directive%20and%20Council%20Implementing%20Decision%202022-382_en.pdf"),
    ("temporary-protection-faq-unaccompanied-children.pdf",
     "Frequently asked questions on unaccompanied minors and separated children fleeing Ukraine "
     "(Temporary Protection Directive)",
     "2022-07",
     HA + "/system/files/2022-07/FAQs%20UAMs%20and%20separated%20children%20TPD_en_1.pdf"),
    ("temporary-protection-faq-going-home-to-ukraine.pdf",
     "Frequently Asked Questions on going home to Ukraine on a voluntary basis in the context of the "
     "Temporary Protection", "",
     HA + "/document/download/34e1c617-8611-4be0-a9d6-ef34c7a8ad01_en?filename=Frequently%20Asked%20Questions"
          "%20on%20going%20home%20to%20Ukraine%20on%20a%20voluntary%20basis%20in%20the%20context%20of%20the%20"
          "Temporary%20Protection_en.pdf"),
    # --- Pact on Migration and Asylum
    ("pact-common-implementation-plan_COM-2024-251.pdf",
     "Common Implementation Plan for the Pact on Migration and Asylum",
     "12.6.2024, COM(2024) 251 final", "celex:52024DC0251"),
    ("pact-operational-checklist_SWD-2024-251.pdf",
     "Operational checklist and list of Commission implementing and delegated acts to be adopted for the "
     "implementation of the Pact on Migration and Asylum (staff working document)",
     "12.6.2024, SWD(2024) 251 final", "celex:52024SC0251"),
]

CELLAR_PUB = "http://publications.europa.eu/resource/cellar/"
OP_DETAIL = "https://op.europa.eu/en/publication-detail/-/publication/{}/language-en"
EXPERT_API = "https://ec.europa.eu/transparency/expert-groups-register/core/api/front"
FX = "https://www.frontex.europa.eu/assets/Publications/"

COUNCIL = [
    ("schengen-catalogue-external-borders-return-readmission_15250-1-08-REV1.pdf",
     "Updated EU Schengen Catalogue: External borders control, Return and readmission - recommendations and "
     "best practices [old; not formally replaced, supplemented by the Commission compendium of best practices]",
     "2008-12, Council doc 15250/1/08 REV 1", CONS.format("ST-15250-2008-REV-1")),
    ("schengen-catalogue-issuing-of-visa_6183-03.pdf",
     "EU Schengen Catalogue vol. 3: Issuing of visa - recommendations and best practices "
     "[old; predates the Visa Code]",
     "2003-02-07, Council doc 6183/03", CONS.format("ST-6183-2003-INIT")),
]
FRONTEX = [
    ("vega-handbook-children-at-airports.pdf", "VEGA Handbook: Children at airports", "2015",
     FX + "General/VEGA_children/VEGA_Children_Handbook.pdf"),
    ("vega-handbook-children-at-land-borders.pdf", "VEGA Handbook: Children at land borders", "2019 (web page 2021-10-22)",
     FX + "General/VEGA_children/VEGA_Children_at_land_borders.pdf"),
    ("vega-handbook-children-at-sea-borders.pdf", "VEGA Handbook: Children at sea borders", "2019 (web page 2021-10-22)",
     FX + "General/VEGA_children/VEGA_Children_at_sea_borders.pdf"),
    ("guide-return-operations-by-air.pdf", "Guide for return operations by air coordinated or organised by Frontex",
     "2026-08-11", FX + "General/2026/Guide_for_return_operations_by_air_coordinated_or_organised_by_Frontex.pdf"),
    ("fundamental-rights-training-for-border-guards.pdf",
     "Fundamental Rights Training for Border Guards - trainers' manual", "2014-03-17",
     FX + "Training/Fundamental_Rights_Training_for_Border_Guardsl.pdf"),
    ("guidelines-third-country-nationals-automated-border-control.pdf",
     "Guidelines for Processing of Third Country Nationals through Automated Border Control", "2016-03-11",
     FX + "Research/Guidelines_for_Processing_of_Third_Country_Nationals_through_ABC.pdf"),
    ("best-practice-operational-guidelines-abc-systems.pdf",
     "Best Practice Operational Guidelines for Automated Border Control (ABC) Systems", "2016-04-22",
     FX + "Research/Best_Practice_Operational_Guidelines_ABC.pdf"),
]
FRA = [                           # fra.europa.eu shows a bot check; these are the Publications Office copies
    ("handbook-european-law-asylum-borders-immigration-2026.pdf",
     "Handbook on European law relating to asylum, borders and immigration - Edition 2026 (FRA / ECtHR) "
     "[legal handbook for practitioners]", "2026-06, 4th edition", "cellar:2cba8fa6-63aa-11f1-9b18-01aa75ed71a1"),
    ("ees-fundamental-rights-guidance-border-guards.pdf",
     "Entry/Exit System: Fundamental rights guidance for border guards", "2025",
     "cellar:d9e6b64a-da2b-11f0-8da2-01aa75ed71a1"),
    ("ees-fundamental-rights-guidance-managers.pdf",
     "Entry/Exit System: Fundamental rights guidance for managers", "2025",
     "cellar:d9b1c399-da2b-11f0-8da2-01aa75ed71a1"),
    ("border-controls-fundamental-rights-land-borders-practical-guidance.pdf",
     "Border controls and fundamental rights at external land borders - Practical guidance", "2020",
     "cellar:1d94ddfc-cdc8-11ea-adf7-01aa75ed71a1"),
    ("border-controls-fundamental-rights-land-borders-pocket-guide.pdf",
     "Border controls and fundamental rights at external land borders - Practical guidance: pocket guide", "2020",
     "cellar:d0558534-f630-11ea-991b-01aa75ed71a1"),
]
EUAA_PAGES = ["https://www.euaa.europa.eu/practical-tools-first-contact-officials-access-asylum-procedure"]

# EUAA: enumerate the publication listing (English) for these title keywords ...
EUAA_LIST = ("https://euaa.europa.eu/publications?field_category_target_id=All&language=en"
             "&field_geo_coverage_target_id=&field_keywords_target_id=&title={q}&page={p}")
EUAA_QUERIES = ["practical", "guidance", "guide", "guidelines", "tool", "checklist", "standards"]
# ... keep practitioner guidance ...
EUAA_KEEP = re.compile(
    r"practical guide|practical tool|practical recommendation|\bguidance\b|\bguidelines\b|quality (assurance )?tool"
    r"|\btoolkit\b|\btool\b|checklist|pocket|standards and indicators|\bguide\b", re.I)
# ... and drop country reports, case-law / judicial material, catalogues and corporate documents.
EUAA_DROP = re.compile(
    r"country guidance|\bCOI\b|country of origin information report|medcoi|judicial|case law|jurisprudence"
    r"|catalogue|annual|programming|report\b|survey|newsletter|factsheet|fact sheet|training plan"
    r"|operating plan|operational plan|budget|strategy|procurement|recruitment|executive summary"
    r"|writing and referencing|methodology|writing guide|evaluation|brochure|animation|workshops"
    r"|qualifications framework|ESQF|welfare of asylum and reception staff", re.I)

LIST_ONLY = False                 # "euaa-list": show what the EUAA filter keeps, download nothing
problems = []
count = 0
total = 0


def fetch(url, accept=None):
    """Return (status, final_url, body). Never retries a refusal."""
    time.sleep(PAUSE)
    headers = {"User-Agent": UA}
    if accept:
        headers.update({"Accept": accept, "Accept-Language": "eng"})
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status, r.geturl(), r.read()
        except urllib.error.HTTPError as e:
            return e.code, url, e.read()
        except Exception as e:                      # noqa: BLE001 - network hiccup: one retry
            err = e
            time.sleep(10)
    return 0, url, str(err).encode()


def store(dest, body, url):
    global count, total
    if not body.startswith(b"%PDF"):
        problems.append(f"{dest.name}: not a PDF (HTML/challenge page?) from {url}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.rename(dest)
    count += 1
    total += len(body)
    print(f"  saved {dest.relative_to(OUT)} ({len(body) // 1024} kB)")
    return True


def have(dest):
    global count, total
    if dest.exists() and dest.stat().st_size > 0:
        count += 1
        total += dest.stat().st_size
        return True
    return False


def full():
    if count >= MAX_FILES or total >= MAX_BYTES:
        if "limit" not in " ".join(problems):
            problems.append("stopped: file/size limit reached")
        return True
    return False


MAGIC = (b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")   # pdf, docx, doc


def get_direct(dest, url, magic=(b"%PDF",)):
    """Stream url to dest. Large files on a slow server are resumed with Range requests."""
    global count, total
    if have(dest):
        return [dest]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    err = ""
    for attempt in range(3):                        # one start + up to two resumes
        done = tmp.stat().st_size if tmp.exists() else 0
        headers = {"User-Agent": UA}
        if done:
            headers["Range"] = f"bytes={done}-"
        time.sleep(PAUSE if attempt == 0 else 10)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as r:
                if done and r.status != 206:        # server ignored the range: start again
                    done = 0
                with tmp.open("ab" if done else "wb") as f:
                    while chunk := r.read(65536):
                        f.write(chunk)
            break
        except urllib.error.HTTPError as e:
            tmp.unlink(missing_ok=True)
            problems.append(f"{dest.name}: HTTP {e.code} from {url}"
                            + (" (blocked - not retried)" if e.code in (403, 429) else ""))
            return []
        except Exception as e:                      # noqa: BLE001 - dropped connection: resume
            err = repr(e)
    else:
        problems.append(f"{dest.name}: incomplete after resumes ({err}) from {url}")
        return []
    with tmp.open("rb") as f:
        if f.read(4) not in magic:
            tmp.unlink()
            problems.append(f"{dest.name}: not a document (HTML/challenge page?) from {url}")
            return []
    tmp.rename(dest)
    count += 1
    total += dest.stat().st_size
    print(f"  saved {dest.relative_to(OUT)} ({dest.stat().st_size // 1024} kB)", flush=True)
    return [dest]


def get_celex(dest, celex, only_first=False):
    """Fetch the English PDF of a CELEX document; documents in several parts give several files."""
    if have(dest):
        return [dest] + sorted(dest.parent.glob(dest.stem + "_part*.pdf"))
    url = (celex[7:] if celex.startswith("cellar:") else CELLAR + urllib.parse.quote(celex, safe=""))
    for accept in ("application/pdf", "application/pdf;type=pdfa1a"):
        status, _, body = fetch(url, accept)
        if status == 200:
            return [dest] if store(dest, body, url) else []
        if status == 300:                           # main document + annexes
            parts = sorted(set(re.findall(r'href="([^"]+/DOC_\d+)"', body.decode("utf-8", "replace"))),
                           key=lambda u: int(u.rsplit("_", 1)[1]))
            if only_first:
                parts = parts[:1]
            saved = []
            for i, part in enumerate(parts, 1):
                d = dest if i == 1 else dest.with_name(f"{dest.stem}_part{i}.pdf")
                if have(d):
                    saved.append(d)
                    continue
                s, _, b = fetch(part, accept)
                if s == 200 and store(d, b, part):
                    saved.append(d)
                else:
                    problems.append(f"{d.name}: HTTP {s} from {part}")
            return saved
        if status in (403, 429):
            break
    problems.append(f"{dest.name}: HTTP {status} from {url}")
    return []


def run_list(items, folder, body):
    rows = []
    for name, title, version, src in items:
        if full():
            break
        dest = OUT / folder / name
        if src.startswith("celex:"):
            celex = src[6:]
            files, shown = get_celex(dest, celex), EURLEX + celex
        elif src.startswith("cellar:"):             # Publications Office general publication
            files, shown = get_celex(dest, "cellar:" + CELLAR_PUB + src[7:], only_first=True), OP_DETAIL.format(src[7:])
        else:
            files, shown = get_direct(dest, src), src
        for i, f in enumerate(files):
            t = title if i == 0 else f"{title} - part {i + 1} (annex)"
            rows.append((f"{folder}/{f.name}", body, t, version, shown))
    return rows


def commission():
    return run_list(COMMISSION, "commission", "European Commission")


def other():
    return (run_list(COUNCIL, "other/council", "Council of the EU")
            + run_list(FRONTEX, "other/frontex", "Frontex")
            + run_list(FRA, "other/fra", "EU Agency for Fundamental Rights (FRA)"))


def contactgroup():
    """Minutes and discussion papers of the Commission expert group E02904 (agendas are skipped)."""
    status, _, body = fetch(EXPERT_API + "/expertGroups/2904/additionalInformation")
    if status != 200:
        problems.append(f"expert group register: HTTP {status}")
        return []
    import json
    rows = []
    folder = "commission/contact-group-legal-migration"
    for meeting in json.loads(body).get("activityReports", []):
        what = " ".join(meeting.get("description", "").split())
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", what)
        date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""
        for doc in meeting.get("documents", []):
            title = doc["title"].strip()
            if re.search(r"agenda", title, re.I) or full():
                continue
            ext = re.search(r"\.(pdf|docx?|DOCX?|PDF)$", title.replace(".doc.pdf", ".pdf"))
            name = f"{date}_{doc['id']}_" + re.sub(r"[^A-Za-z0-9]+", "-", re.sub(r"\.\w+$", "", title)).strip("-")[:80]
            dest = OUT / folder / (name + "." + (ext.group(1).lower() if ext else "bin"))
            url = "https://ec.europa.eu" + doc["urlDownload"]
            if get_direct(dest, url, MAGIC):
                rows.append((f"{folder}/{dest.name}", "European Commission (Contact Group Legal Migration, E02904)",
                             f"{title} [expert group meeting document, not formal guidance] - {what[:160]}", date, url))
    return rows


def euaa_items(page_html):
    """Yield (date, slug, title, pdf_url) for each publication panel on a listing page."""
    for block in page_html.split("euaa-panel--publication")[1:]:
        date = re.search(r'<time datetime="(\d{4}-\d\d-\d\d)', block)
        head = re.search(r'<h3><a href="/publications/([^"]+)">(.*?)</a></h3>', block, re.S)
        pdf = re.search(r'href="(https?://[^"]+/sites/default/files/[^"]+\.pdf)"[^>]*>\s*Download', block, re.I)
        if head and pdf:
            title = html.unescape(re.sub(r"<[^>]+>", "", head.group(2))).strip()
            yield (date.group(1) if date else "", head.group(1), title, html.unescape(pdf.group(1)))


def euaa():
    found = {}
    for q in EUAA_QUERIES:
        for page in range(0, 40):
            status, _, body = fetch(EUAA_LIST.format(q=q, p=page))
            if status != 200:
                problems.append(f"EUAA listing '{q}' page {page}: HTTP {status}")
                break
            items = list(euaa_items(body.decode("utf-8", "replace")))
            if not items:
                break
            for date, slug, title, pdf in items:
                found.setdefault(slug, (date, title, pdf))
        print(f"  EUAA listing '{q}': {len(found)} publications so far")
    # Where the same title was published more than once, keep only the newest edition.
    newest = {}
    for date, title, _ in found.values():
        key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        newest[key] = max(newest.get(key, ""), date)
    rows = []
    for slug, (date, title, pdf) in sorted(found.items(), key=lambda kv: kv[1][1].lower()):
        if date < newest[re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()]:
            if LIST_ONLY:
                print(f"  old\t{date}\t{title}\t{slug}\t{pdf}")
            continue
        keep = bool(EUAA_KEEP.search(title)) and not EUAA_DROP.search(title)
        if LIST_ONLY:
            print(f"  {'KEEP' if keep else 'skip'}\t{date}\t{title}\t{slug}\t{pdf}")
            continue
        if not keep:
            continue
        if not re.search(r"(^|[_-])EN([_.-]|$)", pdf.rsplit("/", 1)[-1], re.I) and \
                re.search(r"[_-](BG|CS|DA|DE|EL|ES|ET|FI|FR|GA|HR|HU|IT|LT|LV|MT|NL|PL|PT|RO|SK|SL|SV|AR|RU|TR|UK)\.pdf$",
                          pdf):
            continue                                # translation that slipped through the language filter
        if full():
            break
        dest = OUT / "euaa" / (re.sub(r"[^A-Za-z0-9._-]+", "-", slug)[:110] + ".pdf")
        if get_direct(dest, pdf):
            rows.append((f"euaa/{dest.name}", "EU Agency for Asylum (EUAA/EASO)", title, date, pdf))
    # Tools that are only linked from thematic landing pages.
    seen = {r[4].replace("//www.", "//") for r in rows}
    for page in EUAA_PAGES:
        status, _, body = fetch(page)
        if status != 200:
            problems.append(f"EUAA page {page}: HTTP {status}")
            continue
        for pdf in dict.fromkeys(re.findall(r'href="(https?://[^"]+/sites/default/files/publications/[^"]+\.pdf)"',
                                            body.decode("utf-8", "replace"))):
            if pdf.replace("//www.", "//") in seen or full():
                continue
            seen.add(pdf.replace("//www.", "//"))
            stem = urllib.parse.unquote(pdf.rsplit("/", 1)[-1])[:-4]
            month = re.search(r"/publications/(\d{4}-\d\d)/", pdf)
            dest = OUT / "euaa" / ("tools-" + re.sub(r"[^A-Za-z0-9._-]+", "-", stem)[:100] + ".pdf")
            if get_direct(dest, pdf):
                title = re.sub(r"^\d{4} ", "", stem.replace("-", " ").replace("_", " ")).strip().capitalize()
                rows.append((f"euaa/{dest.name}", "EU Agency for Asylum (EUAA/EASO)",
                             title + " (from the first-contact officials tools page)",
                             month.group(1) if month else "", pdf))
    return rows


def section_of(path):
    if path.startswith("commission/contact-group"):
        return "contactgroup"
    return path.split("/")[0]


def write_index(rows, sections):
    """Rewrite index.tsv, keeping rows of sections that were not run this time."""
    index = OUT / "index.tsv"
    kept = []
    if index.exists():
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            cols = line.split("\t")
            if section_of(cols[0]) not in sections and (OUT / cols[0]).exists():
                kept.append(tuple(cols))
    rows = sorted(kept + rows)
    with index.open("w", encoding="utf-8") as f:
        f.write("file\tissuing body\ttitle\tdate/version\tsource URL\n")
        for r in rows:
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in r) + "\n")
    return len(rows)


def main():
    global LIST_ONLY
    todo = sys.argv[1:] or ["commission", "contactgroup", "euaa", "other"]
    if todo == ["euaa-list"]:
        LIST_ONLY = True
        euaa()
        return
    OUT.mkdir(exist_ok=True)
    rows = []
    for section in todo:
        print(f"== {section}")
        rows += {"commission": commission, "contactgroup": contactgroup, "euaa": euaa, "other": other}[section]()
    n = write_index(rows, todo)
    print(f"\n{n} documents in {OUT / 'index.tsv'}; {total / 1e6:.1f} MB in the sections run")
    if problems:
        print("\nProblems:")
        for p in problems:
            print("  " + p)


if __name__ == "__main__":
    main()

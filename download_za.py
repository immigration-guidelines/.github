#!/usr/bin/env python3
"""South Africa: Immigration Directives and related instructions of the Department of
Home Affairs (DHA). See za/NOTES.txt for what was checked and what is missing.

    python3 download_za.py

Immigration Directives are numbered instructions of the Director-General or the Minister
addressed "to all officials" (and to missions and the visa centres). The DHA publishes
only some of them, as loose files behind entries in its "Notices" section; there is no
register, and no handbook or standard operating procedure is published at all.

Where the files come from
  * www.dha.gov.za answers robots.txt with HTTP 403 to scripts. The script reads that
    robots.txt once per run; unless it is readable and permits the path, the live site is
    not touched and the copy held by the Internet Archive (web.archive.org) is used. Those
    are the department's own files, so they are marked official = yes; the capture used
    is in the source_url column.
  * www.gov.za: directives that were printed in the Government Gazette.
  * One directive was found only as a copy published by the Law Society of South Africa;
    it is marked official = mirror.

Rules followed: robots.txt is read for every host before the first request and obeyed;
requests are sequential with a pause (15 s for the Internet Archive, which throttles);
a host that answers 403 or 429, or refuses the connection three times in a row, is
dropped for the rest of the run; nothing else is retried. Files that exist are skipped,
so re-running only fills gaps. za/index.tsv and za/not-obtained.tsv are rewritten on
every run. Standard library only (pdfinfo is used to check PDFs when it is installed).
"""
import gzip
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

OUT = Path(__file__).resolve().parent / "za"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = {"web.archive.org": 15.0}             # seconds between requests; default below
DEFAULT_DELAY = 1.5
REFUSAL_WAIT = 120                           # extra pause before the request after a refused one
WB = "https://web.archive.org/web/"
DHA = "https://www.dha.gov.za/"
GOV = "https://www.gov.za/sites/default/files/gcis_document/"

G, P = "guidance", "procedural act"

# (file, title, date, kind, official, source, text that must be in an HTML page)
# source is a URL, or (Wayback timestamp, path on www.dha.gov.za, "http" or "https" as captured)
DOCS = [
    # DOCS-BEGIN
    ('2021-09_Immigration-Directive-No-07-of-2021_ICT-work-visa-concession.jpg',
     'Immigration Directive No. 07 of 2021: temporary concession for intra-company transfer work visa holders (published as an image)',
     '2021-09', G, 'yes',
     ('20210909195057', 'images/Immigration-Directive07.jpg', 'http'), None),
    ('2021-12_Immigration-Directive-No-12-of-2021_temporary-measures-travel-bans.png',
     'Immigration Directive No. 12 of 2021: temporary measures in respect of foreign nationals in light of the imposition of travel bans (published as an image)',
     '2021-12', G, 'yes',
     ('20220118075857', 'images/graphix/zepdirective-12.png', 'http'), None),
    ('2021-12_Immigration-Directive-No-11-of-2021_ZEP-withdrawal-of-Directive-No-10.png',
     'Immigration Directive No. 11 of 2021: Zimbabwean Exemption Permit holders (ZEP), withdrawal of Immigration Directive No. 10 of 2021 (published as an image, undated)',
     '2021-12', G, 'yes',
     ('20220122130017', 'images/zepwithdrawal.png', 'http'), None),
    ('2022-01_Ministers-Immigration-Directive-No-1-of-2021_ZEP-extension-12-months_image.png',
     "Minister's Immigration Directive No. 1 of 2021: implementation of the decision to extend Zimbabwean nationals' exemptions for 12 months (published as an image under the page title 'No 01 of 2022'; same directive as Gazette No. 45727)",
     '2022-01', G, 'yes',
     ('20220105151200', 'images/IMS_01of22.png', 'http'), None),
    ('2022-01-07_Gazette-45727_Ministers-Immigration-Directive-No-1-of-2021_ZEP-extension.pdf',
     "Minister's Immigration Directive No. 1 of 2021: implementation of the decision to extend Zimbabwean nationals' exemptions under section 31(2)(b) (Government Gazette No. 45727, Government Notice 1666, 7 January 2022)",
     '2022-01-07', G, 'yes',
     ('20220115035721', 'images/ZEP/45727_7-1_HomeAff.pdf', 'http'), None),
    ('2022-01-31_Immigration-Directive-No-2-of-2022_withdrawal-of-blanket-waiver-critical-skills-graduates.pdf',
     'Immigration Directive No. 2 of 2022: withdrawal of blanket waiver dated 21 April 2016 in respect of graduates from South African tertiary institutions in the area of critical skills',
     '2022-01-31', G, 'yes',
     ('20220201195108', 'images/Immigration_Directive_No_2_of_2002.pdf', 'http'), None),
    ('2022-01-31_Minister_withdrawal-of-waivers-section-31-2-c_permanent-residence-critical-skills-graduates.pdf',
     'Withdrawal of waivers granted in terms of section 31(2)(c) of the Immigration Act: permanent residence under section 27(b) for graduates in the area of critical skills (Minister, to head office, immigration services and all offices)',
     '2022-01-31', G, 'yes',
     ('20220203161536', 'images/directive_on_withdrawal_of_blanket_waiver.pdf', 'http'), None),
    ('2022-02_Immigration-Directive-No-1-of-2022_implementation-of-critical-skills-list.pdf',
     'Immigration Directive No. 1 of 2022: implementation of the critical skills list (Minister; handwritten date in February 2022)',
     '2022-02', G, 'yes',
     ('20220207161038', 'images/notices/Immigration_Directive_No._01_of_2022_-_Critical_Skills_Implementation.pdf', 'http'), None),
    ('2022-03-11_DG-Immigration-Directive-No-1-of-2022_implementation-of-critical-skills-list.pdf',
     "Director-General's Immigration Directive No. 1 of 2022: implementation of the critical skills list",
     '2022-03-11', G, 'yes',
     ('20220529120721', 'images/notices/DGs-Directive-No.-1-of-2022_-critical-skills.pdf', 'http'), None),
    ('2022-09-05_Gazette-46865_Ministers-Immigration-Directive-No-2-of-2022_ZEP-extension.pdf',
     "Minister's Immigration Directive No. 2 of 2022: implementation of the decision to extend Zimbabwean nationals' exemptions under section 31(2)(b) for a further six months (Government Gazette No. 46865, Government Notice 2460, 5 September 2022)",
     '2022-09-05', G, 'yes',
     ('20230518024949', 'images/Documents/Gazette-46865_5-9_HomeAffairs.pdf', 'http'), None),
    ('2022-09-01_Circular_temporary-measures-backlog-waiver-and-visa-applications.png',
     'Circular: temporary measures in respect of foreign nationals in light of a backlog experienced in processing outcomes on waiver applications and visa applications (Director-General; handwritten date read as 1 September 2022; published as an image)',
     '2022-09-01', G, 'yes',
     ('20230401000000', 'images/notices/TempMeasures_23.png', 'http'), None),
    ('2023_Notice_temporary-measures-backlog-waiver-and-visa-applications.jpg',
     'Temporary measures in respect of foreign nationals in light of a backlog in processing outcomes on waiver and visa applications (2023 version; published as an image; not examined)',
     '2023', G, 'yes',
     ('20230701000000', 'images/notices/visa_notice2023.jpg', 'http'), None),
    ('2023-12_Ministers-Immigration-Directive-No-3-of-2023_Lesotho-exemption-permits.pdf',
     "Minister's Immigration Directive No. 3 of 2023 on exemptions granted to Lesotho nationals under section 31(2)(b), with press statement (file name of the department: Lesotho-Directive-No3-of-2023)",
     '2023-12', G, 'yes',
     ('20231205202628', 'images/PDFs/LSP/Lesotho-Directive-No3-of-2023.pdf', 'http'), None),
    ('2023-12_Ministers-Immigration-Directive-No-4-of-2023_Zimbabwean-exemption-permits.pdf',
     "Minister's Immigration Directive No. 4 of 2023 on exemptions granted to Zimbabwean nationals under section 31(2)(b), with press statement (file name of the department: Zimbabwe-Directive-No4-of-2023)",
     '2023-12', G, 'yes',
     ('20240521040100', 'images/ZEP/Zimbabwe-Directive-No4-of-2023.pdf', 'https'), None),
    ('2023-12-04_Gazette-49813_Ministers-Immigration-Directive-No-3-of-2023_Lesotho-exemptions.pdf',
     "Minister's Immigration Directive No. 3 of 2023: implementation of the decision in respect of granting exemptions to Lesotho nationals under section 31(2)(b) (Government Gazette No. 49813, Government Notice 4141, 4 December 2023)",
     '2023-12-04', G, 'yes',
     ('20231205204650', 'images/gazettes/Gazette-Lesotho-Special-Dispensation-4-Dec-2023.pdf', 'http'), None),
    ('2023-12-04_Gazette-49814_Ministers-Immigration-Directive-No-4-of-2023_Zimbabwean-exemptions.pdf',
     "Minister's Immigration Directive No. 4 of 2023: exemptions granted to Zimbabwean nationals under section 31(2)(b) (Government Gazette No. 49814, 4 December 2023)",
     '2023-12-04', G, 'yes',
     ('20240521040107', 'images/gazettes/Gazette-Zimbabwean-Special-Dispensation-4-Dec-2023.pdf', 'https'), None),
    ('2023-12-21_Circular_extension-of-temporary-concession_backlog-waiver-visa-appeal-applications.pdf',
     'Circular: extension of temporary concession in respect of foreign nationals in light of a continued backlog in processing outcomes on waiver applications, visa applications and appeal applications (Acting Director-General)',
     '2023-12-21', G, 'yes',
     ('20231222151654', 'images/PDFs/Concession_Document_2023.pdf', 'http'), None),
    ('2024-03-04_Ministers-Immigration-Directive-No-1-of-2024_Constitutional-Court-order-section-34-detention.pdf',
     "Minister's Immigration Directive No. 1 of 2024: implementation of the order of the Constitutional Court in Ex parte Minister of Home Affairs and Others; In re Lawyers for Human Rights v Minister of Home Affairs [2017] ZACC 22 (arrest, detention and release of illegal foreigners under section 34)",
     '2024-03-04', G, 'yes',
     ('20240824212257', 'images/Directive_1_2024.pdf', 'https'), None),
    ('2024-03-04_Ministers-Immigration-Directive-No-1-of-2024_annexures-forms-28-to-32.pdf',
     "Annexures to Minister's Immigration Directive No. 1 of 2024: forms 28 to 32 (warrant of detention and related forms; file name of the department: Sec_341)",
     '2024-03-04', G, 'yes',
     ('20240824212302', 'images/Sec_341.pdf', 'https'), None),
    ('2024-10-08_Immigration-Directive-No-9-of-2024_port-of-entry-visas-adherence-to-requirements.pdf',
     'Immigration Directive No. 9 of 2024 (to missions): port of entry visas, adherence to requirements',
     '2024-10-08', G, 'yes',
     ('20250404214353', 'images/notices/8october24/Immigration_Directive_to_Missions_-_no_9_of_202_-_8_Oct_2024.pdf', 'https'), None),
    ('2024-10-08_Ministerial-waiver_critical-skills-work-visas_points-based-system.pdf',
     'Ministerial waiver for critical skills work visas adjudicated in terms of the points-based system (letter of the Minister to the Director-General, 8 October 2024)',
     '2024-10-08', G, 'yes',
     ('20241112112611', 'images/notices/8october24/Waiver_letter_-_Critical_Skills_work_visa_-_8_Oct_2024.pdf', 'https'), None),
    ('2024-10-08_Ministerial-waiver_general-work-visas_points-based-system.pdf',
     'Ministerial waiver for general work visas adjudicated in terms of the points-based system (letter of the Minister to the Director-General, 8 October 2024)',
     '2024-10-08', G, 'yes',
     ('20241102075831', 'images/notices/8october24/Waiver_letter_-_General_work_visa_-_8_Oct_2024.pdf', 'https'), None),
    ('2024-10-09_Gazette-51365_points-based-system-notice.pdf',
     'Government Gazette No. 51365 of 9 October 2024: points-based system for work visas (notice under section 19 of the Immigration Act)',
     '2024-10-09', P, 'yes',
     ('20241101044342', 'images/notices/8october24/Gazette-Notice-Points-based-system.pdf', 'https'), None),
    ('2024-10_Notice_withdrawal-of-notice-5397_points-based-system.pdf',
     'Government notice: withdrawal of Notice No. 5397 published in Gazette No. 51365, points-based system (text as published by the department, October 2024)',
     '2024-10', P, 'yes',
     ('20250404204848', 'images/notices/october24/Notice_of_Withdrawal-Points-Based_System.pdf', 'https'), None),
    ('2024-10_Notice_points-based-system-criteria.pdf',
     'Government notice: points-based system, criteria under section 19 read with regulation 18(12) and (13) (text as published by the department, October 2024)',
     '2024-10', P, 'yes',
     ('20241108090814', 'images/notices/october24/Notice_Points-Based_Criteria.pdf', 'https'), None),
    ('2024-10-18_Ministerial-Immigration-Directive-No-10-of-2024_implementation-of-points-based-system.pdf',
     'Ministerial Immigration Directive No. 10 of 2024: implementation of the points-based system',
     '2024-10-18', G, 'yes',
     ('20250403173514', 'images/notices/october24/Immigration_Directive_No10of2024-Implementation_of_the_Points-Based_System.pdf', 'https'), None),
    ('2024-10-18_Ministerial-waiver_critical-skills-work-visas_points-based-system.pdf',
     'Ministerial waiver for critical skills work visas adjudicated in terms of the points-based system (letter of the Minister to the Director-General, 18 October 2024)',
     '2024-10-18', G, 'yes',
     ('20250403161956', 'images/notices/october24/Waiver_Letter-Critical_Skills_Work.pdf', 'https'), None),
    ('2024-10-18_Spreadsheet-tool_adjudication-points-based-system.xls',
     'Spreadsheet tool for adjudication under the points-based system (18 October 2024)',
     '2024-10-18', G, 'yes',
     ('20250118183454', 'images/notices/october24/Spreadsheet-Tool-Adjudication-Points-Based_System-18-10-2024.xls', 'https'), None),
    ('2024-11-29_Gazette-51696_Ministers-Immigration-Directive-No-15-of-2024_ZEP-extension.pdf',
     "Minister's Immigration Directive No. 15 of 2024: extension of validity of exemptions granted under section 31(2)(b) (Zimbabwean Exemption Permits; Government Gazette No. 51696, 29 November 2024)",
     '2024-11-29', G, 'yes',
     GOV + '202411/51696gon5603.pdf', None),
    ('2025-03-28_Immigration-Directive-No-4-of-2025_extension-of-temporary-concession.pdf',
     'Immigration Directive No. 4 of 2025: extension of temporary concession for foreign nationals due to processing delays of appeals and certain applications',
     '2025-03-28', G, 'yes',
     ('20250330061219', 'images/notices/Immigration_Directive_No._4_of_2025.pdf', 'https'), None),
    ('2025-09-23_Immigration-Directive-No-22-of-2025_extension-of-temporary-concession_LSSA-copy.pdf',
     'Immigration Directive No. 22 of 2025: extension of temporary concession for foreign nationals due to processing delays of waiver and appeals applications (original version of 23 September 2025; copy circulated by the Law Society of South Africa)',
     '2025-09-23', G, 'mirror',
     'https://www.lssa.org.za/wp-content/uploads/2025/09/EXTENSION-OF-TEMPORARY-CONCESSION-CIRCULAR.pdf', None),
    ('2025-09-30_Amendments-to-Immigration-Directive-No-22-of-2025_extension-of-temporary-concession.pdf',
     'Amendments to Immigration Directive No. 22 of 2025: extension of temporary concession for foreign nationals due to processing delays of waiver and appeals applications (revised directive)',
     '2025-09-30', G, 'yes',
     ('20251002020612', 'images/notices/Revised-Immigration-Directive_22-of-2025.pdf', 'https'), None),
    ('2025-10-07_Gazette-53483_Ministers-Immigration-Directive-No-20-of-2025_Lesotho-exemption-permits.pdf',
     "Minister's Immigration Directive No. 20 of 2025: extension of validity of exemptions granted under section 31(2)(b) (Lesotho Exemption Permits; Government Gazette No. 53483, Notice R. 6715, 7 October 2025)",
     '2025-10-07', G, 'yes',
     GOV + '202510/53483rg11892gon6715.pdf', None),
    ('2025-10-07_Gazette-53484_Ministers-Immigration-Directive-No-21-of-2025_Zimbabwean-exemption-permits.pdf',
     "Minister's Immigration Directive No. 21 of 2025: extension of validity of exemptions granted under section 31(2)(b) (Zimbabwean Exemption Permits; Government Gazette No. 53484, Notice R. 6716, 7 October 2025)",
     '2025-10-07', G, 'yes',
     GOV + '202510/53484rg11893gon6716.pdf', None),
    ('2026-03_Immigration-Directive-No-6-of-2026_airspace-closures-concessions.html',
     'Immigration Directive No. 6 of 2026: temporary concessions for passengers and crew affected by airspace closures in the Middle East and Gulf region (published as a web page, undated)',
     '2026-03', G, 'yes',
     ('20260407213609', 'index.php/immigration-directive-no-6-of-2026', 'https'), b"Immigration Act"),
    ('2026-03-30_Immigration-Directive-No-7-of-2026_extension-of-temporary-concession.pdf',
     'Immigration Directive No. 7 of 2026: extension of temporary concession for foreign nationals related to delayed processing of waiver, visa and appeal applications',
     '2026-03-30', G, 'yes',
     ('20260331152458', 'images/PDFs/Concession_of_30_March_2026.pdf', 'https'), None),
    ('2026-07-08_Gazette-55016_Ministerial-Immigration-Directive-No-10-of-2026_blanket-waiver-medical-report.pdf',
     'Ministerial Immigration Directive No. 10 of 2026: blanket waiver of the requirement to submit a medical report for visa and permanent residence applications (signed 8 July 2026; Government Gazette No. 55016, Notice 7714, 17 July 2026)',
     '2026-07-08', G, 'yes',
     GOV + '202607/55016gon7714.pdf', None),
    ('2019-11-20_Immigration-Directive-No-24-of-2019_Lesotho-exemption-permit-applications.pdf',
     'Immigration Directive No. 24 of 2019: Lesotho Exemption Permit applications (LEP) (Deputy Director-General: Immigration Services)',
     '2019-11-20', G, 'yes',
     ('20210422221240', 'images/LEP_DIRECTIVE.pdf', 'http'), None),
    ('2021-04_Immigration-Directive-No-03-of-2021_temporary-blanket-concession-permanent-residents.png',
     'Immigration Directive No. 03 of 2021: temporary blanket concession to permanent residents who are affected by the Covid-19 pandemic (published as an image about 1 April 2021)',
     '2021-04', G, 'yes',
     ('20210415000000', 'images/graphix/Screenshot-2021-04-01-at-09.13.21.png', 'http'), None),
    # DOCS-END
]

# Items known to exist that this script does not fetch: (item, date, reason, url)
NOT_OBTAINED = [
    # NOT-BEGIN
    ("Standard operating procedures, handbooks or manuals for immigration officers, adjudicators, refugee "
     "reception officers, refugee status determination officers, the Standing Committee for Refugee Affairs or "
     "the Refugee Appeals Authority", "", "not published by the department", "https://www.dha.gov.za/"),
    ("Director-General's directive of 28 September 2026 to all Refugee Reception Offices on the intake of asylum "
     "applications after the Constitutional Court judgment of 7 July 2026 (withdrawn 9 October 2026)", "2026-09-28",
     "not published; only the statement announcing its withdrawal is on the department's site",
     "https://www.dha.gov.za/index.php/statements-speeches/2097-home-affairs-director-general-withdraws-asylum-directive"),
    ("Immigration Directive No. 13 of 2026 (waiver of the 60-day advance filing requirement)", "2026-10-02",
     "reported by advisers; not found on an official site or in the web archive", ""),
    ("Immigration Directive No. 16 of 2024 (temporary concession, backlog)", "2024-12-18",
     "cited in later directives; no copy in the web archive of the department's site", ""),
    ("Minister's Immigration Directive No. 2 of 2023 (extension of Zimbabwean exemption permits, June 2023)", "2023-06",
     "only the department's press statement was found",
     "https://www.dha.gov.za/index.php/statements-speeches/1682-press-statement-on-the-issuing-of-minister-s-immigration-directive-no-2-of-2023-extending-the-validity-of-the-exemption-permits-issued-to-the-zimbabwean-nationals"),
    ("Immigration Directive No. 10 of 2021 (Zimbabwean Exemption Permit holders; withdrawn by No. 11 of 2021)", "2021",
     "not found in the web archive of the department's site", ""),
    ("Immigration Directive No. 23 of 2019 (exemption from port of entry visa requirements, Mali) and the other "
     "directives of 2019 and earlier, e.g. Immigration Directive No. 22 of 2014 (confirmation of skills for a "
     "critical skills visa), Ministerial Waivers of 2005 and of 21 April 2016", "",
     "referred to in saved directives; never published on the department's site as far as the web archive shows", ""),
    ("Notice: temporary visa concession for holders of intra-company transfer visas (2020)", "2020",
     "the Internet Archive refused the connection during the check; page content not examined",
     "https://web.archive.org/web/20201111201202/http://www.dha.gov.za/index.php/notices/1388-temporary-visa-concession-for-holders-of-intra-company-transfer-visas-currently-resident-in-the-republic-of-south-africa"),
    ("Notice: temporary measures in respect of foreign nationals in light of a backlog (2022 notice page)", "2022",
     "the Internet Archive refused the connection during the check; page content not examined",
     "https://web.archive.org/web/20220803143105/http://www.dha.gov.za/index.php/notices/1544-temporary-measures-in-respect-of-foreign-nationals-in-light-of-a-backlog-being-experienced-in-processing-outcomes-on-waiver-applications-and-visa-applications"),
    ("Public notices on the validity of asylum seeker and refugee permits during the Covid-19 lockdown (2020-2021)",
     "2021", "left out on purpose: notices to the public, not instructions to officials",
     "https://web.archive.org/web/20210129112841/http://www.dha.gov.za/index.php/notices/1410-extension-of-validity-of-asylum-seeker-and-refugee-permits-to-31st-of-march-2021"),
    ("Gazette files in the department's /images/gazettes/ and /images/PDFs/ folders that were not opened "
     "(Nos. 43301, 47256, 48764, 48924, 51064, 51437, 55209)", "",
     "not examined, to spare the Internet Archive; may include further gazetted directives",
     "https://web.archive.org/web/2026*/dha.gov.za/images/gazettes/*"),
    ("Passport Control Instruction No. 63 of 1994: procedures for handling asylum-seekers and refugees", "1994",
     "only copy found is in UNHCR's web archive, which answers scripts with HTTP 403",
     "https://webarchive.archive.unhcr.org/20171024203030oe_/http://www.refworld.org/docid/3ae6b5080.html"),
    ("Copies of Directive No. 7 of 2026 and of the amendment to No. 22 of 2025 on Stellenbosch University's file "
     "server", "", "not needed (official copies saved); the host answers robots.txt with HTTP 403",
     "https://files.su.ac.za/public/su-international/documents/2026-03/immigration-directive-7-2026.pdf"),
    # NOT-END
]


class Site:
    """One host: robots.txt read once, sequential paced requests, dropped on refusal."""
    sites = {}

    def __init__(self, host):
        self.host = host
        self.blocked = None
        self.refused = 0
        self.penalty = 0
        self.delay = DELAY.get(host, DEFAULT_DELAY)
        self.rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"https://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                self.rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                self.blocked = f"robots.txt of {host} answered HTTP {e.code}; host not used"
            else:
                self.rp.parse([])                  # no robots.txt: nothing is disallowed
        except Exception as e:                     # noqa: BLE001
            self.blocked = f"robots.txt of {host} not readable ({e}); host not used"
        self.last = time.time()

    @classmethod
    def of(cls, url):
        host = urllib.parse.urlsplit(url).netloc
        if host not in cls.sites:
            cls.sites[host] = cls(host)
        return cls.sites[host]

    def get(self, url):
        """Returns (data, None) or (None, reason)."""
        if self.blocked:
            return None, self.blocked
        if not self.rp.can_fetch("*", url):
            return None, "disallowed by robots.txt"
        time.sleep(max(0.0, self.delay + self.penalty - (time.time() - self.last)))
        self.penalty = 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            self.refused = 0
        except urllib.error.HTTPError as e:
            self.refused = 0
            if e.code in (403, 429):
                self.blocked = f"HTTP {e.code} from {self.host}; host dropped for this run"
            return None, f"HTTP {e.code}"
        except Exception as e:                     # noqa: BLE001 - refused, reset, timeout
            self.refused += 1
            if self.refused >= 3:
                self.blocked = f"{self.host} refused three requests in a row; host dropped for this run"
            else:
                self.penalty = REFUSAL_WAIT          # wait longer before the next request
            return None, str(e)
        finally:
            self.last = time.time()
        if data[:2] == b"\x1f\x8b":                # the archive sometimes replays the stored gzip stream
            data = gzip.decompress(data)
        return data, None


def pdf_ok(path):
    """True if the file is a readable PDF (pdfinfo when available, else the header)."""
    with open(path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            return False
    if shutil.which("pdfinfo"):
        return subprocess.run(["pdfinfo", str(path)], capture_output=True).returncode == 0
    return True


MAGIC = {".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".xls": b"\xd0\xcf\x11\xe0"}


def valid(dest, data, marker):
    """None if data looks like the document it should be, else the reason."""
    ext = dest.suffix.lower()
    if ext == ".pdf":
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        ok = pdf_ok(tmp)
        tmp.unlink()
        return None if ok else "not a valid PDF (error page?)"
    if ext in MAGIC:
        return None if data.startswith(MAGIC[ext]) else f"not a {ext} file (error page?)"
    if marker and marker not in data:
        return "page does not contain the expected text (error or bot-check page?)"
    return None


def sources(src):
    """Addresses to try, in order, and the address to record for each."""
    if isinstance(src, str):
        return [src]
    ts, path, scheme = src
    live = DHA + path
    archived = f"{WB}{ts}id_/{scheme}://www.dha.gov.za/{path}"
    return [live, archived]


def save(src, dest, marker):
    """Download to dest unless present. Returns (address used or None, reason or None)."""
    why = "no source"
    for url in sources(src):
        if dest.exists() and dest.stat().st_size > 0:
            return url, None
        data, why = Site.of(url).get(url)
        if data is None:
            continue
        why = valid(dest, data, marker)
        if why is None:
            dest.write_bytes(data)
            return url, None
    return None, why


def recorded_url(src, dest_was_fetched_from):
    """The address written to index.tsv: the one used now, else the archived copy."""
    if isinstance(src, str):
        return src
    return dest_was_fetched_from if dest_was_fetched_from and dest_was_fetched_from.startswith(WB) \
        else sources(src)[1]


def main():
    OUT.mkdir(exist_ok=True)
    # where each existing file came from, so a re-run keeps the recorded address
    known = {}
    idx = OUT / "index.tsv"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 4:
                known[parts[0]] = parts[3]
    rows, failed = [], []
    for name, title, date, kind, official, src, marker in DOCS:
        dest = OUT / name
        existed = dest.exists() and dest.stat().st_size > 0
        if existed:
            used = known.get(name) or recorded_url(src, None)
            why = None
        else:
            used, why = save(src, dest, marker)
        if why is None:
            rows.append((name, title, date, used, kind, official))
        else:
            print(f"  NOT SAVED {name}: {why}")
            failed.append((title, date, why, sources(src)[-1]))
    rows.sort()
    with open(idx, "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\tofficial\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("item\tdate\treason\turl\n")
        for row in failed + NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    guid = sum(1 for r in rows if r[4] == G)
    mirr = sum(1 for r in rows if r[5] == "mirror")
    print(f"za: {len(rows)} of {len(DOCS)} documents present ({guid} guidance, {len(rows) - guid} "
          f"procedural acts; {mirr} from a mirror); {len(failed) + len(NOT_OBTAINED)} items in not-obtained.tsv")


if __name__ == "__main__":
    main()

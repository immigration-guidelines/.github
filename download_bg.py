#!/usr/bin/env python3
"""Bulgaria: published guidance and working procedural acts for immigration and asylum cases.

    python3 download_bg.py              # all sources
    python3 download_bg.py sar mvr      # only the named sources (mvr, sar, mlsp)

Bulgaria publishes very little. The State Agency for Refugees (SAR / ДАБ при МС), which
decides asylum, posts its internal rules for the international-protection procedure and
the inter-agency instruction on age assessment; those are the only real guidance.
The Ministry of the Interior's Migration Directorate (Дирекция "Миграция") and the
Ministry of Labour post only statutes and the Council of Ministers' / Minister's
implementing regulations, saved here as "procedural act". See bg/NOTES.txt.

Not used: lex.bg (robots.txt "User-agent: * / Disallow: /"), iisda.government.bg
(robots.txt disallows Python-urllib), az.government.bg (TLS handshake fails: the
server's DH key is too small for this machine's OpenSSL; security settings are not
lowered). No request goes to web.archive.org: nothing needed is archive-only.

Standard library only, sequential, one connection per host, 2 s between requests,
robots.txt read first per host (wildcards handled here), skips files that exist,
rewrites bg/index.tsv and bg/not-obtained.tsv.
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "bg"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
AI_AGENTS = ("claudebot", "claude-web", "anthropic-ai", "gptbot", "chatgpt-user", "ccbot", "python-urllib")

MVR = "https://www.mvr.bg"
SAR = "https://aref.government.bg"
MLSP = "https://www.mlsp.government.bg"
MVR_LIST = MVR + "/migration/дирекцията/нормативна-уредба/bgzac"

# source, file, url, title (BG), date, kind, title_en, note
DOCS = [
    ("sar", "2023-07_dab-vatreshni-pravila-za-proizvodstvoto-za-mezhdunarodna-zakrila.pdf",
     SAR + "/sites/default/files/2023-07/В Ъ Т Р Е Ш Н И  П Р А В И Л А.pdf",
     "Вътрешни правила за провеждане на производството за предоставяне на международна закрила в Държавната агенция за бежанците при Министерския съвет",
     "2023-07", "guidance",
     "Internal rules for conducting the international protection procedure in the State Agency for Refugees",
     "59 pages, 197 articles: registration, accommodation, documents, Dublin, accelerated and general procedure, interviews, drafting and signing decisions, subsequent applications, unaccompanied minors, files and registers, staff duties; undated, date = upload/PDF creation (4 Jul 2023); listing page "
     + SAR + "/нормативни-актове/вътрешни-правила-провеждане-производството-предоставяне-международна-закрила"),
    ("sar", "2023-11-30_dab-dazd-instrukciya-za-ocenka-na-vazrast.pdf",
     SAR + "/sites/default/files/2024-01/ИНСТРУКЦИЯ.pdf",
     "Инструкция за реда и условията за оценка на възраст (ДАБ при МС и ДАЗД)",
     "2023-11-30", "guidance",
     "Instruction on the procedure and conditions for age assessment of applicants for international protection (State Agency for Refugees and State Agency for Child Protection)",
     "18 pages; approved by orders of both agencies (Nov/Dec 2023), in force 1 March 2024; criteria and methods, non-invasive assessment, expert assessment; listing page "
     + SAR + "/нормативни-актове/инструкция-реда-и-условията-оценка-възраст"),
    ("sar", "2023-11-30_dab-zapoved-CU-RD05-722-utvarzhdavane-instrukciya-vazrast.pdf",
     SAR + "/sites/default/files/2024-01/Заповед_Инструкция_оценка_възраст_SAR.pdf",
     "Заповед № ЦУ-РД05-722/30.11.2023 на председателя на ДАБ при МС за утвърждаване на Инструкция за реда и условията за оценка на възраст",
     "2023-11-30", "guidance",
     "Order of the SAR Chairperson approving the age-assessment instruction (in force 1 March 2024)",
     "2 pages; approving order belonging to the instruction above"),
    ("sar", "2023-12_dazd-zapoved-RD-02-136-utvarzhdavane-instrukciya-vazrast.pdf",
     SAR + "/sites/default/files/2024-01/Заповед Инструкция възраст дек. 2023 г-clean.pdf",
     "Заповед № РД-02-136 на председателя на ДАЗД за утвърждаване на Инструкция за реда и условията за оценка на възраст",
     "2023-12", "guidance",
     "Order of the Chairperson of the State Agency for Child Protection approving the age-assessment instruction",
     "1 page; approving order belonging to the instruction above; date from SAR's file name (Dec 2023)"),
    ("sar", "2025-11-24_dab-pravilnik-za-nastanyavane-i-vatreshniya-red-v-pomeshteniya-ot-zatvoren-tip.pdf",
     SAR + "/sites/default/files/2026-01/Правилник за условията за настаняване и вътрешния ред в помещения от затворен тип.PDF",
     "Правилник за условията за настаняване и вътрешния ред в помещения от затворен тип към териториалните поделения на ДАБ при МС",
     "2025-11-24", "procedural act",
     "Rules on accommodation conditions and internal order in closed-type premises of the SAR territorial units",
     "8 pages; internal rules approved by order РД-05-786/24.11.2025; marked 'ниво на конфиденциалност: [TLP-AMBER]' although published on the agency's site"),
    ("sar", "2025-11-24_dab-zapoved-RD-05-786-utvarzhdavane-pravilnik-zatvoren-tip.pdf",
     SAR + "/sites/default/files/2026-01/Заповед за утвърждаване на правилник ПЗТ_0.PDF",
     "Заповед № РД-05-786/24.11.2025 относно приемане на Правилник за настаняване и вътрешен ред в помещения от затворен тип",
     "2025-11-24", "procedural act",
     "Order of the SAR Chairperson adopting the rules for closed-type premises",
     "1 page; marked [TLP-AMBER]"),
    ("sar", "2022-06-21_naredba-dablin-evrodak-pms-332-2007.docx",
     SAR + "/sites/default/files/2024-04/Наредба за отговорността и координацията на д-вните органи.docx",
     "Наредба за отговорността и координацията на държавните органи, осъществяващи действия по административно сътрудничество при прилагането на Регламент Дъблин и Регламент Евродак",
     "2022-06-21", "procedural act",
     "Ordinance on the responsibilities and coordination of state authorities in administrative cooperation under the Dublin and Eurodac Regulations (Council of Ministers Decree 332/2007)",
     "consolidated text as hosted by SAR, last amendment DV 46/2022 in force 21.06.2022; date = that amendment; listing page " + SAR + "/нормативни-актове/наредби"),
    ("mvr", "2026-01-20_pravilnik-za-prilagane-na-zakona-za-chuzhdencite.pdf",
     MVR + "/upload/338042/ППЗЧРБ 2026.pdf",
     "Правилник за прилагане на Закона за чужденците в Република България",
     "2026-01-20", "procedural act",
     "Regulation implementing the Foreigners in the Republic of Bulgaria Act (Council of Ministers Decree 179/2011)",
     "consolidated text as hosted by the Migration Directorate, last amendment DV 7/2026 (20 Jan 2026); documents and procedure for every residence category, incl. EU Blue Card, long-term residence, refusals and withdrawals; listing page " + MVR_LIST),
    ("mvr", "2019-04-02_naredba-za-usloviyata-i-reda-za-izdavane-na-vizi.pdf",
     MVR + "/upload/17991/наредба-за-условията-и-реда-за-издаване-на-визи-и-определяне-на-визовия-режим.pdf",
     "Наредба за условията и реда за издаване на визи и определяне на визовия режим",
     "2019-04-02", "procedural act",
     "Ordinance on the conditions and procedure for issuing visas and determining the visa regime (Council of Ministers Decree 198/2011)",
     "consolidated text as hosted by the Migration Directorate, last amendment shown DV 27/2019; later amendments, if any, are not in this copy; listing page " + MVR_LIST),
    ("mvr", "2017-06-30_naredba-Iz-1201-2010-vremenno-nastanyavane-na-chuzhdenci-sdvnch.docx",
     MVR + "/upload/17990/наредба-сдвнч_30062017c2f1d66955d5444dab14e4bc63d8e808.docx",
     "Наредба № Із-1201 от 1 юни 2010 г. за реда за временно настаняване на чужденци в специалните домове за временно настаняване на чужденци и в техните звена и за организацията и дейността им",
     "2017-06-30", "procedural act",
     "Ordinance No Iz-1201 of 1 June 2010 (Minister of the Interior) on the temporary accommodation (detention) of foreigners in the special homes and their organisation",
     "consolidated text, last amendment DV 52/2017 (30 Jun 2017); listing page " + MVR_LIST),
    ("mvr", "2017-07-28_pravilnik-za-vatreshniya-red-v-sdvnch.doc",
     MVR + "/upload/17983/пвр-сдвнч_28072017-цкнч-31-07-174436e7736f1e4afc8b5d2e64abcc511b.doc",
     "Правилник за вътрешния ред в специалните домове за временно настаняване на чужденци при дирекция \"Миграция\" при МВР",
     "2017-07-28", "procedural act",
     "Internal rules of the special homes for the temporary accommodation of foreigners (detention centres) of the Migration Directorate",
     "issued by the Director of the Migration Directorate under art. 8 of Ordinance Iz-1201; replaces the rules of 16.06.2016 (No 5364р-20628); date from the file name; listing page " + MVR_LIST),
    ("mlsp", "2026-07-21_pravilnik-za-prilagane-na-zakona-za-trudovata-migraciya-i-trudovata-mobilnost.pdf",
     MLSP + "/uploads/78/sdrmi/za-prilagane-na-zakona-za-trudovata-migratsiya-i-trudovata-mobilnost.pdf",
     "Правилник за прилагане на Закона за трудовата миграция и трудовата мобилност",
     "2026-07-21", "procedural act",
     "Regulation implementing the Labour Migration and Labour Mobility Act (Council of Ministers Decree 255/2016)",
     "consolidated text as hosted by the Ministry of Labour, last amendment DV 66/2026 (21 Jul 2026); Employment Agency procedure for labour-market access decisions; its Blue Card section (arts 15-17) was repealed in 2021; listing page " + MLSP + "/pravilnitsi"),
]

NOT_OBTAINED = [
    ("Инструкция № 8121з-1276 от 11.10.2018 г. за реда и организацията за издаване на документи и удостоверения по Закона за влизането, пребиваването и напускането на Република България на гражданите на ЕС (Minister of the Interior instruction on issuing documents to EU citizens and family members; amended DV 65/2019) - procedural act",
     "2018-10-11", "https://dv.parliament.bg/",
     "published only in the State Gazette (DV 91/2018); not on mvr.bg; the copies on lex.bg are excluded by its robots.txt (Disallow: / for all but search engines) and iisda.government.bg disallows Python-urllib; the State Gazette's search application was not scripted"),
    ("Internal instructions, orders and methodological guidance of the Director of the Migration Directorate and of the Minister of the Interior to the regional 'Migration' units (residence permits, refusals, withdrawals, return and coercive measures)",
     "", MVR + "/достъп-до-информация/достъп-до-обществена-информация",
     "not published: the Migration Directorate's site carries only statutes and regulations; the Ministry publishes no register of FOI answers; obtainable only by a request under the Access to Public Information Act (ЗДОИ)"),
    ("Employment Agency internal guidance on labour-market access decisions, the single permit and the EU Blue Card",
     "", "https://www.az.government.bg/",
     "az.government.bg could not be reached: TLS handshake fails (server DH key too small for this machine's OpenSSL); security settings were not lowered; a person can open the site in a browser"),
    ("SAR internal guidance on early identification of vulnerable applicants, interview techniques and country-of-origin information use",
     "", SAR + "/достъп-обществена-информация",
     "not published (only the general internal rules and the age-assessment instruction are on aref.government.bg); obtainable only by a ЗДОИ request"),
]


class Blocked(Exception):
    pass


_last = {}
_robots = {}
_closed = {}


def _get(url, timeout=120):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Blocked(_closed[host])
    wait = DELAY - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    q = urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")
    try:
        with urllib.request.urlopen(urllib.request.Request(q, headers={"User-Agent": UA}), timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        _last[host] = time.time()
        if e.code in (401, 403, 429):
            _closed[host] = f"HTTP {e.code}"
            raise Blocked(f"HTTP {e.code} from {host}") from e
        raise
    _last[host] = time.time()
    return data


def _rx(pat):
    return re.compile("^" + "".join(".*" if c == "*" else re.escape(c) for c in pat.rstrip("$"))
                      + ("$" if pat.endswith("$") else ""))


def allowed(url):
    p = urllib.parse.urlsplit(url)
    host = p.netloc
    if host not in _robots:
        rules = []
        try:
            body = _get(f"{p.scheme}://{host}/robots.txt", timeout=60).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = "" if e.code == 404 else None
        except Blocked:
            body = None
        except Exception as e:                                # noqa: BLE001
            print(f"  robots.txt of {host} not readable: {e}")
            body = None
        if body is None:
            _closed.setdefault(host, "robots.txt not readable")
            _robots[host] = None
        else:
            agents, fresh = [], True
            for line in body.splitlines():
                line = line.split("#")[0].strip()
                if ":" not in line:
                    continue
                k, v = (s.strip() for s in line.split(":", 1))
                k = k.lower()
                if k == "user-agent":
                    if not fresh:
                        agents, fresh = [], True
                    agents.append(v.lower())
                    continue
                fresh = False
                if k in ("allow", "disallow") and v and any(a == "*" or a in AI_AGENTS for a in agents):
                    rules.append((k == "allow", len(v), _rx(v)))
            _robots[host] = rules
    rules = _robots[host]
    if rules is None:
        return False
    path = urllib.parse.unquote(p.path) + (("?" + p.query) if p.query else "")
    best = None
    for allow, ln, rx in rules:
        if rx.match(path) or rx.match(urllib.parse.quote(path, safe="/?&=%*$")):
            if best is None or ln > best[1] or (ln == best[1] and allow):
                best = (allow, ln)
    return best is None or best[0]


def valid(data, name):
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return data.startswith(b"%PDF")
    if ext == "docx":
        return data.startswith(b"PK")
    if ext == "doc":
        return data.startswith(b"\xd0\xcf\x11\xe0")
    return b"<html" not in data[:500].lower()


def main():
    wanted = set(sys.argv[1:]) or {"mvr", "sar", "mlsp"}
    unknown = wanted - {"mvr", "sar", "mlsp"}
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(sorted(unknown))}; use mvr, sar, mlsp")
    OUT.mkdir(exist_ok=True)
    failed = []
    for src, name, url, title, date, kind, title_en, note in DOCS:
        if src not in wanted or (OUT / name).exists():
            continue
        try:
            if not allowed(url):
                failed.append((title, date, url, "disallowed by robots.txt or host closed"))
                continue
            data = _get(url)
        except Blocked as e:
            print(f"  REFUSED {name}: {e}; host not used further")
            failed.append((title, date, url, f"refused: {e}"))
            continue
        except Exception as e:                                # noqa: BLE001 - report, no retry
            print(f"  FAILED {name}: {e}")
            failed.append((title, date, url, f"download failed: {e}"))
            continue
        if not valid(data, name):
            print(f"  NOT A DOCUMENT, skipped: {name}")
            failed.append((title, date, url, "server did not return the document"))
            continue
        (OUT / name).write_bytes(data)
        print(f"  saved {name} ({len(data):,} bytes)")

    present = 0
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        for src, name, url, title, date, kind, title_en, note in DOCS:
            if not (OUT / name).exists():
                if not any(r[2] == url for r in failed):
                    failed.append((title, date, url, "not downloaded in this run"))
                continue
            present += 1
            f.write("\t".join([name, title, date, url, kind, title_en, note]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for row in failed + NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    print(f"bg: {present} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

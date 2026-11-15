#!/usr/bin/env python3
"""Panama: what the migration authorities publish for the officials who decide cases.

    python3 download_pa.py            # all sources
    python3 download_pa.py snm        # one source

Sources (see pa/NOTES.txt for what was checked and what is missing):

  snm     www.migracion.gob.pa  "Decretos" pages by year (2019 onwards): the resolutions
          of the Director General of the Servicio Nacional de Migración. These are the
          only working instructions the service publishes (requirements and procedure
          for visas and permits, extensions, fines, registration). Saved as
          "procedural act". The executive decrees listed on the same pages are
          legislation and are not downloaded; they, and the few resolutions left out
          on purpose (organisational acts, a Ministry of Health act, staff discipline;
          see SNM_SKIP), are written to pa/listings/snm-not-downloaded.tsv.
  gaceta  www.gacetaoficial.gob.pa  five Gaceta Oficial issues, fixed list: three
          manuals/protocols (kind "guidance") and SNM resolutions that are not on the
          SNM site. The Gaceta's own pages sit behind an Incapsula JavaScript check;
          only the direct PDF addresses below are requested, and if one of them answers
          with anything but a PDF the host is dropped for the run.

Rules: robots.txt is read for each host before anything else and obeyed (rules for "*"
and rules that name AI agents; wildcards handled here, Crawl-delay honoured); one
request at a time, at least 2 s apart per host; a host that answers 403 or 429, serves a
challenge page, or fails to connect three times in a row is not asked again in that run.
Files that exist are skipped; pa/index.tsv and pa/not-obtained.tsv are rebuilt on every
run. Standard library only.
"""
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
OUT = ROOT / "pa"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
MAX_BYTES = 500_000_000
MAX_FILES = 1500
MAX_ONE = 95_000_000
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "oai-searchbot", "perplexitybot", "bytespider", "ai2bot")

SNM = "https://www.migracion.gob.pa"
SNM_BODY = "Servicio Nacional de Migración (SNM)"
SNM_INDEX = SNM + "/decretos/"

# number -> (subject in Spanish, English gloss), read from the documents themselves (most are scans)
SNM_SUBJECTS = {
    "17405": ("rehabilitación del permiso de residente permanente tras ausencia de más de dos años: requisitos y plazo",
              "rehabilitation of permanent residence after more than two years' absence: requirements and time limit"),
    "5731": ("COVID-19: extiende quince días hábiles la vigencia de permisos de residencia, carnés y visas",
             "COVID-19: 15 working-day extension of residence permits, cards and visas"),
    "7051": ("COVID-19: extiende hasta el 15 de mayo de 2020 permisos y estadías, suspende términos y atención",
             "COVID-19: permits and stays extended to 15 May 2020 without fines; time limits and counters suspended"),
    "7538": ("COVID-19: extiende hasta el 31 de mayo de 2020 permisos y estadías, suspende términos y atención",
             "COVID-19: permits and stays extended to 31 May 2020 without fines; time limits and counters suspended"),
    "8189": ("COVID-19: extiende hasta el 7 de junio de 2020 permisos y estadías y ordena la reapertura gradual de trámites",
             "COVID-19: permits and stays extended to 7 June 2020; phased reopening of migration procedures"),
    "13139": ("pre-registro y requisitos del permiso de residente temporal del personal de Sedes de Empresas Multinacionales "
              "antes de su llegada",
              "pre-registration and documents for temporary residence of staff of multinational headquarters (SEM) before arrival"),
    "15909": ("COVID-19: extiende hasta el 31 de enero de 2021 permisos y estadías y la ausencia de residentes permanentes",
              "COVID-19: permits, stays and permanent residents' absence abroad extended to 31 January 2021"),
    "636": ("COVID-19: extiende hasta el 30 de junio de 2021 permisos, estadías, ausencia de residentes permanentes y "
            "certificados civiles vencidos",
            "COVID-19: permits, stays, permanent residents' absence and expired civil certificates extended to 30 June 2021"),
    "864": ("admisión hasta el 30 de junio de 2021 de certificados de antecedentes penales de la DIJ panameña para "
            "extranjeros con un año de permanencia",
            "Panamanian police (DIJ) criminal-record certificates accepted until 30 June 2021 for foreigners resident a year"),
    "14757": ("procedimiento y requisitos de la solicitud de visa de turista por apoderado legal para nacionalidades que "
              "requieren visa",
              "procedure and requirements for tourist visa applications lodged through a lawyer for visa-required nationals"),
    "14758": ("plazo para solicitar prórrogas de permisos de residencia (tres meses antes del vencimiento) y cierre de "
              "expedientes tardíos",
              "deadline for residence-permit renewals (three months before expiry) and closure of late applications"),
    "18915": ("carnés de trámite por seis meses y supresión del sello de visa múltiple en el pasaporte desde el 15 de agosto "
              "de 2021",
              "six-month 'in process' cards and end of the multiple-entry visa stamp in passports from 15 August 2021"),
    "20133": ("admisión de antecedentes penales extranjeros vencidos durante la pandemia acompañados del certificado de la "
              "DIJ; RUEX en los certificados",
              "foreign criminal records that expired during the pandemic accepted with a Panamanian DIJ certificate"),
    "22068": ("concepto de turista, estancia máxima de tres meses, requisitos de ingreso y carta de invitación",
              "definition of tourist, three-month maximum stay, entry requirements and invitation letters"),
    "24252": ("reglamenta aspectos de procedimiento del Decreto Ejecutivo 235 de 2021 (renovación de permisos provisionales "
              "de regularización y residencia permanente)",
              "procedural rules for Executive Decree 235 of 2021 (renewal of regularisation permits towards permanent residence)"),
    "25316": ("extiende hasta el 31 de diciembre de 2021 las exoneraciones de multas por razones humanitarias y delega su firma",
              "humanitarian waivers of migration fines extended to 31 December 2021; delegation of signature"),
    "26616": ("reglamenta aspectos de procedimiento del Decreto Ejecutivo 226 de 2021 (residencia permanente de nacionales "
              "de países amigos)",
              "procedural rules for Executive Decree 226 of 2021 (permanent residence for nationals of 'friendly nations')"),
    "28291": ("visas de marino, registro de agencias navieras y responsabilidades de las agencias",
              "seafarer visas, registration of shipping agencies and their responsibilities"),
    "1744": ("suspende hasta el 30 de abril de 2022 las solicitudes del Decreto Ejecutivo 235 de 2021 y extiende los permisos "
             "de regularización",
             "applications under Executive Decree 235 of 2021 suspended to 30 April 2022; regularisation permits extended"),
    "2579": ("registro y presentación de solicitudes de visa de trabajadores domésticos antes del ingreso, por apoderado",
             "domestic-worker visa applications lodged by a lawyer before the worker enters Panama"),
    "6994": ("reactiva desde el 18 de abril de 2022 las solicitudes del Decreto Ejecutivo 235, extiende permisos y "
             "exoneraciones de multa",
             "applications under Executive Decree 235 reopened from 18 April 2022; permits and fine waivers extended"),
    "7096": ("reglamentación del Decreto Ejecutivo 235 de 2021: historial policivo, razones de arraigo, razones laborales, "
             "costos y carnés",
             "interpretive rules for Executive Decree 235 of 2021: police record, 'roots' grounds, work grounds, fees, cards"),
    "13680": ("extiende hasta el 31 de diciembre de 2022 la recepción de solicitudes de exoneración de multas",
              "applications for waiver of migration fines accepted until 31 December 2022"),
    "13699": ("implementa el Registro Único de Extranjería (RUEX) y su asignación numérica",
              "introduction of the Single Register of Foreigners (RUEX) number"),
    "12457": ("plazo hasta el 31 de diciembre de 2023 para prórrogas de permisos de residencia vencidos desde el 13 de marzo "
              "de 2020",
              "residence permits expired since 13 March 2020: renewals accepted until 31 December 2023"),
    "32305": ("procedimiento de filiación de extranjeros que solicitan visa de transeúnte o de trabajador eventual",
              "registration (filiación) procedure for applicants for transient or occasional-worker visas"),
    "246": ("plazo hasta el 29 de febrero de 2024 para prórrogas de permisos de residencia vencidos desde el 13 de marzo de 2020",
            "residence permits expired since 13 March 2020: renewals accepted until 29 February 2024"),
    "9049": ("plazo hasta el 30 de junio de 2024 para prórrogas de permisos de residencia vencidos desde el 13 de marzo de 2020",
             "residence permits expired since 13 March 2020: renewals accepted until 30 June 2024"),
    "39760": ("exonera el 50% de las multas por estadía irregular del 1 de agosto de 2024 al 31 de julio de 2025",
              "50% waiver of fines for irregular stay, 1 August 2024 to 31 July 2025"),
    "41029": ("deja sin efecto la Resolución 22068 de 2021 (turistas)",
              "revokes Resolution 22068 of 2021 (tourists)"),
    "46625": ("plazo hasta el 31 de diciembre de 2024 para prórrogas de permisos de residencia vencidos desde el 13 de marzo "
              "de 2020",
              "residence permits expired since 13 March 2020: renewals accepted until 31 December 2024"),
    "1191": ("acepta hasta el 31 de diciembre de 2025 prórrogas de permisos de residencia vencidos",
             "renewals of expired residence permits accepted until 31 December 2025"),
    "4887": ("permiso de estadía de hasta seis meses para personal de Sedes de Empresas Multinacionales y dependientes al "
             "terminar la relación laboral",
             "stay permit of up to six months for multinational-headquarters staff and dependants after employment ends"),
    "6616": ("exoneración total de la multa por estadía vencida a quien solicite por primera vez el Permiso de Protección "
             "de Seguridad Humanitaria",
             "full waiver of overstay fines for first applicants for the Humanitarian Security Protection Permit"),
    "7533": ("acepta pasaportes venezolanos vencidos (desde 2018) como documento de identidad válido para trámites migratorios",
             "expired Venezuelan passports (since 2018) accepted as valid identity documents for migration procedures"),
    "7534": ("acepta certificaciones de estatus y movimiento migratorio solicitadas en línea desde el 10 de febrero de 2025",
             "certificates of migration status and movements requested online accepted from 10 February 2025"),
    "38022": ("exonera el 50% de las multas por estadía irregular del 15 de octubre de 2025 al 15 de abril de 2026",
              "50% waiver of fines for irregular stay, 15 October 2025 to 15 April 2026"),
    "51973": ("adopta el Procedimiento Electrónico de Naturalización y reglas sobre el expediente electrónico de carta de "
              "naturaleza",
              "electronic naturalisation procedure and rules for electronic naturalisation case files"),
}
# number -> date, where the label on the page is wrong or carries no date (read from the document)
SNM_DATES = {"46625": "2024-10-10"}
# resolutions listed on the SNM pages that are deliberately not kept: number -> reason
SNM_SKIP = {
    "300": "Ministry of Health resolution on COVID-19 cleaning and prevention guidelines; not a migration act",
    "12140": "COVID-19 face shields in SNM premises; facility rule, not case handling",
    "24250": "creates the maritime port control unit (UCVMM); organisational",
    "26158": "creates the SNM Judicial Secretariat department; organisational",
    "28219": "structures the unit for migrant-smuggling matters (UATIM); organisational",
    "11138": "creates the field action unit (UMAC); organisational",
    "175": "Ministry of Public Security resolution 175 of 2026 adopting the disciplinary rules for migration career "
           "staff; personnel discipline, not case handling",
}
# links on the SNM pages whose file is not the act named in the label: url ending -> (number, date, note)
SNM_BAD_LINKS = {
    "RESOLUCION_25316-1_rotated.pdf": ("22706", "2021-09-10",
                                       "the link labelled 22706 on the SNM 2021 page serves a copy of Resolution 25316"),
}

GACETA = "https://www.gacetaoficial.gob.pa/storage/gacetas/"
# (file, title, date, url, kind, title_en, issuing body)
GACETA_ITEMS = [
    ("gaceta/2013-05-24_GO-27294-A_MITRADEL-Manual-regularizacion-migratoria-extraordinaria.pdf",
     "Manual de Procedimientos para el Proceso de Regularización Migratoria Extraordinaria (mayo de 2013), aprobado por "
     "Resolución N.° DM 210-2013 del Ministerio de Trabajo y Desarrollo Laboral - Gaceta Oficial 27294-A (número completo)",
     "2013-05-24", "2013/05/27294_A/GacetaNo_27294a_20130524.pdf", "guidance",
     "Procedures manual for work permits in the extraordinary migration regularisation process (May 2013), approved by "
     "Labour Ministry Resolution DM 210-2013 - whole issue 27294-A of the official gazette",
     "Ministerio de Trabajo y Desarrollo Laboral (MITRADEL)"),
    ("gaceta/2016-05-25_GO-28038-B_MITRADEL-Manual-Departamento-Migracion-Laboral.pdf",
     "Manual de Procedimientos y Funciones del Departamento de Migración Laboral (mayo de 2016), aprobado por Resolución "
     "N.° DM-225-16 del Ministerio de Trabajo y Desarrollo Laboral - Gaceta Oficial 28038-B (número completo)",
     "2016-05-25", "2016/05/28038_B/GacetaNo_28038b_20160525.pdf", "guidance",
     "Manual of procedures and functions of the Labour Migration Department (work permits for foreigners; May 2016), "
     "approved by Labour Ministry Resolution DM-225-16 - whole issue 28038-B of the official gazette",
     "Ministerio de Trabajo y Desarrollo Laboral (MITRADEL)"),
    ("gaceta/2019-03-15_GO-28733-A_Manual-gestion-alojamientos-temporales.pdf",
     "Manual de Gestión de Alojamientos Temporales en Panamá (OIM / Ministerio de Seguridad Pública, 2018), aprobado por "
     "Decreto Ejecutivo N.° 121 de 15 de marzo de 2019 - Gaceta Oficial 28733-A",
     "2019-03-15", "2019/03/28733_A/71936.pdf", "guidance",
     "Manual for the management of temporary shelters for migrants in transit in Panama (IOM / Ministry of Public "
     "Security, 2018), approved by Executive Decree 121 of 15 March 2019 - official gazette 28733-A",
     "Ministerio de Seguridad Pública (MINSEG)"),
    ("gaceta/2023-10-23_GO-29895-A_SNM-Resolucion-35517.pdf",
     "Resolución N.° 35517 de 27 de septiembre de 2023 del Servicio Nacional de Migración: formato único de la Visa "
     "Especial de Marino Electrónica y su verificación por las empresas de transporte - Gaceta Oficial 29895-A",
     "2023-09-27", "2023/10/29895_A/101113.pdf", "procedural act",
     "Resolution 35517 of 27 September 2023 of the National Migration Service: single format of the electronic special "
     "seafarer visa and its verification by carriers - official gazette 29895-A", SNM_BODY),
    ("gaceta/2024-06-06_GO-30047-B_Protocolo-NNA-no-acompanados-movilidad-humana.pdf",
     "Protocolo para la identificación y atención a niños, niñas y adolescentes no acompañados y/o separados en contexto "
     "de movilidad humana en Panamá (SENNIAF / UNICEF, 2024), adoptado por Decreto Ejecutivo N.° 16 de 4 de junio de 2024 "
     "- Gaceta Oficial 30047-B",
     "2024-06-06", "2024/06/30047_B/105271.pdf", "guidance",
     "Protocol for identifying and attending to unaccompanied and separated children in the context of human mobility "
     "in Panama (child-protection secretariat SENNIAF / UNICEF, 2024; binds the migration and border services), adopted "
     "by Executive Decree 16 of 4 June 2024 - official gazette 30047-B",
     "Ministerio de Desarrollo Social / Secretaría Nacional de Niñez, Adolescencia y Familia (SENNIAF)"),
]

# Known to exist, not fetched: (title, date, url, reason)
_GO = "not on the SNM site (its resolution pages start in 2019); the Gaceta Oficial (www.gacetaoficial.gob.pa) serves " \
      "an Incapsula JavaScript check on its pages and was not used to search; Internet Archive CDX answered 503"
NOT_OBTAINED = [
    ("Resolución N.° 15703 de 24 de agosto de 2012 del Servicio Nacional de Migración (prórrogas tardías de permisos; "
     "cierre de expedientes) - cited by Resolutions 14758 de 2021, 246 de 2024, 46625 de 2024 and 1191 de 2025",
     "2012-08-24", "https://www.gacetaoficial.gob.pa/", _GO),
    ("Resolución N.° 5893 de 16 de marzo de 2020 del Servicio Nacional de Migración (COVID-19: suspensión de trámites y "
     "términos)", "2020-03-16", "https://www.gacetaoficial.gob.pa/", _GO),
    ("Resolución N.° 6518 de 1 de abril de 2020 del Servicio Nacional de Migración (COVID-19: suspensión de atención y "
     "términos hasta el 30 de abril de 2020)", "2020-04-01", "https://www.gacetaoficial.gob.pa/", _GO),
    ("Resolución N.° 12684 de 21 de agosto de 2020 del Servicio Nacional de Migración (certificados de antecedentes "
     "penales de la DIJ)", "2020-08-21", "https://www.gacetaoficial.gob.pa/", _GO),
    ("Resolución N.° 16977 de 25 de noviembre de 2020 del Servicio Nacional de Migración (certificados de antecedentes "
     "penales de la DIJ hasta el 31 de enero de 2021)", "2020-11-25", "https://www.gacetaoficial.gob.pa/", _GO),
    ("Memorando interno del Servicio Nacional de Migración de 26 de abril de 2010 (estancia de turistas de 180 días), "
     "cited in Resolution 22068 de 2021", "2010-04-26", "",
     "internal memo, never published"),
    ("Reglas de procedimiento de la Oficina Nacional para la Atención de Refugiados (ONPAR)", "",
     "https://www.mingob.gob.pa/reglas-de-procedimientos/",
     "the Ministry of Government page exists but its content is 'Pendiente' (nothing published), checked 2026-11-15"),
    ("Ministerio de Seguridad Pública website (resolutions of the ministry on migration, e.g. disciplinary rules)", "",
     "https://www.minseg.gob.pa/", "robots.txt disallows ClaudeBot from the whole site; not used"),
]

MONTHS = {m: i + 1 for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}
MONTHS.update({"setiembre": 9, "septembre": 9})

blocked = {}       # host -> reason
errors = {}        # host -> consecutive connection errors
last_hit = {}      # host -> time of last request
rules = {}         # host -> (list of (allow?, pattern), crawl delay)
failures = []      # (title, date, url, reason)
rows = []          # index rows
stats = {"new": 0}


def host_of(url):
    return urllib.parse.urlsplit(url).netloc


def quote_url(u):
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(urllib.parse.unquote(p.path), safe="/%")))


def wait(host):
    delay = max(DELAY, rules.get(host, ([], 0))[1])
    gap = time.time() - last_hit.get(host, 0)
    if gap < delay:
        time.sleep(delay - gap)
    last_hit[host] = time.time()


def request(url):
    """One request. Returns (bytes, content type) or None; closes the host on a refusal."""
    host = host_of(url)
    if host in blocked:
        return None
    wait(host)
    try:
        with urllib.request.urlopen(urllib.request.Request(quote_url(url), headers={"User-Agent": UA}),
                                    timeout=180) as r:
            errors[host] = 0
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        errors[host] = 0
        if e.code in (401, 403, 429):
            blocked[host] = f"HTTP {e.code}"
            print(f"  REFUSED by {host} (HTTP {e.code}); host not asked again")
        return ("HTTP %d" % e.code,)
    except Exception as e:                              # noqa: BLE001 - connection trouble
        errors[host] = errors.get(host, 0) + 1
        if errors[host] >= 3:
            blocked[host] = "three connection errors in a row"
            print(f"  giving up on {host}")
        return (f"connection error: {e}",)


def load_robots(host):
    """Fetch and parse robots.txt once per host: groups for '*' and for AI agents both apply."""
    wait(host)
    pats, delay = [], 0.0
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://{host}/robots.txt",
                                                           headers={"User-Agent": UA}), timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            blocked[host] = f"robots.txt answers HTTP {e.code}"
            print(f"  REFUSED: {host} robots.txt answers HTTP {e.code}; host not used")
        text = ""                                       # 404 and the like: no rules
    except Exception as e:                              # noqa: BLE001
        blocked[host] = f"robots.txt unreachable: {e}"
        print(f"  {host}: robots.txt unreachable ({e}); host not used")
        text = ""
    if "<html" in text[:2000].lower() and re.search(r"challenge|captcha|just a moment|incapsula", text, re.I):
        blocked[host] = "robots.txt answers with a bot-check page"
        text = ""
    agents, applies, in_rules = [], False, False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip().lstrip("﻿")
        if ":" not in line:
            continue
        key, val = (x.strip() for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(val.lower())
            applies = any(a == "*" or any(n in a for n in AI_AGENTS) for a in agents)
        elif key in ("allow", "disallow"):
            in_rules = True
            if applies and val:
                pats.append((key == "allow", val))
        elif key == "crawl-delay":
            in_rules = True
            if applies:
                try:
                    delay = max(delay, float(val))
                except ValueError:
                    pass
    rules[host] = (pats, delay)


def allowed(url):
    host = host_of(url)
    if host not in rules:
        load_robots(host)
    if host in blocked:
        return False
    p = urllib.parse.urlsplit(quote_url(url))
    path = p.path + ("?" + p.query if p.query else "")
    best = (-1, True)
    for allow, pat in rules[host][0]:
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pat.rstrip("$")) + ("$" if pat.endswith("$") else "")
        if re.match(rx, path) and (len(pat) > best[0] or (len(pat) == best[0] and allow)):
            best = (len(pat), allow)
    return best[1]


def get_page(url):
    if not allowed(url):
        print(f"  not fetched (robots.txt or closed host): {url}")
        return None
    r = request(url)
    if r is None or len(r) == 1:
        print(f"  page failed: {url} {r[0] if r else blocked.get(host_of(url), '')}")
        return None
    text = r[0].decode("utf-8", "replace")
    if len(text) < 3000 and re.search(r"_Incapsula_Resource|Just a moment|captcha", text, re.I):
        blocked[host_of(url)] = "bot-check page"
        print(f"  BOT CHECK on {host_of(url)}; host not asked again")
        return None
    return text


def is_pdf(path):
    with open(path, "rb") as f:
        if b"%PDF" not in f.read(1024):
            return False
    try:
        return subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=120).returncode == 0
    except FileNotFoundError:
        return True


def used():
    files = [p for p in OUT.rglob("*") if p.is_file() and ".large" not in p.parts]
    return len(files), sum(p.stat().st_size for p in files)


def fetch(rel, title, date, url, kind, title_en, body):
    """Download one PDF to pa/<rel> unless it is there already; add its index row if the file is good."""
    dest = OUT / rel
    large = OUT / ".large" / rel
    if large.exists():
        return
    if not dest.exists():
        n, size = used()
        if n >= MAX_FILES or size >= MAX_BYTES:
            failures.append((title, date, url, "not fetched: size or file limit of the folder reached"))
            return
        if not allowed(url):
            failures.append((title, date, url, "not fetched: " + blocked.get(host_of(url), "excluded by robots.txt")))
            return
        r = request(url)
        if r is None or len(r) == 1:
            failures.append((title, date, url, r[0] if r else "host closed: " + blocked.get(host_of(url), "")))
            print(f"  FAILED {url}: {failures[-1][3]}")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(r[0])
        if not is_pdf(tmp):
            head = r[0][:3000].decode("utf-8", "replace")
            tmp.unlink()
            if re.search(r"_Incapsula_Resource|Just a moment|captcha", head, re.I):
                blocked[host_of(url)] = "bot-check page instead of the file"
            failures.append((title, date, url, "answer was not a PDF (" + (r[1] or "no type") + ")"))
            print(f"  NOT A PDF {url}")
            return
        if len(r[0]) > MAX_ONE:
            large.parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(large)
            print(f"  over 95 MB, kept under .large/: {rel}")
            return
        tmp.rename(dest)
        stats["new"] += 1
        print(f"  saved {rel}")
    rows.append((rel, title, date, url, kind, title_en, body))


def links(page):
    out = []
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        label = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        out.append((html.unescape(m.group(1)), label))
    return out


def label_date(label):
    m = re.search(r"(\d{1,2})\s*[º°o]?\s*(?:de\s+|del\s+)?([a-záé]+)\s+(?:de\s+|del\s+)?(\d{4})", label.lower())
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return ""


def source_snm():
    print("snm: resolutions of the Servicio Nacional de Migración")
    index = get_page(SNM_INDEX)
    if not index:
        return
    years = sorted({m for m in re.findall(r'href="' + re.escape(SNM) + r'/decretos/((?:19|20)\d\d)-2/"', index)})
    skipped, seen, not_kept = [], set(), []
    for year in years:
        page = get_page(f"{SNM}/decretos/{year}-2/")
        if not page:
            continue
        for url, label in links(page):
            if not url.lower().endswith(".pdf") or "/wp-content/uploads/" not in url or url in seen:
                continue
            seen.add(url)
            if re.match(r"decreto", label, re.I):
                skipped.append((label, year, url))
                continue
            m = re.match(r"resoluci[oó]n\s*(?:n[º°o.]*\s*)?(\d+)", label, re.I)
            if not m:
                continue
            num = m.group(1)
            bad = next((v for k, v in SNM_BAD_LINKS.items() if url.endswith(k)), None)
            if bad:
                failures.append((f"Resolución N.° {bad[0]} del Servicio Nacional de Migración", bad[1], url,
                                 "not obtained: " + bad[2] + "; not found elsewhere (Gaceta Oficial host behind a bot "
                                 "check)"))
                continue
            if num in SNM_SKIP:
                not_kept.append((label, year, url, "left out on purpose: " + SNM_SKIP[num]))
                continue
            date = SNM_DATES.get(num) or label_date(label) or year
            subj, gloss = SNM_SUBJECTS.get(num, ("", ""))
            title = f"Resolución N.° {num} de {date[:4]} del Servicio Nacional de Migración" + (f": {subj}" if subj else "")
            title_en = f"Resolution {num} of {date[:4]} of the National Migration Service" + (f": {gloss}" if gloss else "")
            fetch(f"snm/{date}_Resolucion-{num}.pdf", title, date, url, "procedural act", title_en, SNM_BODY)
    listing = OUT / "listings" / "snm-not-downloaded.tsv"
    listing.parent.mkdir(parents=True, exist_ok=True)
    with open(listing, "w", encoding="utf-8") as f:
        f.write("title\tyear\turl\treason\n")
        for label, year, url in skipped:
            f.write(f"{label}\t{year}\t{url}\tskipped on purpose: executive decree (legislation, not guidance)\n")
        for row in not_kept:
            f.write("\t".join(row) + "\n")


def source_gaceta():
    print("gaceta: manuals and resolutions published in the Gaceta Oficial")
    for rel, title, date, path, kind, title_en, body in GACETA_ITEMS:
        fetch(rel, title, date, GACETA + path, kind, title_en, body)


SOURCES = {"snm": source_snm, "gaceta": source_gaceta}


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def main():
    wanted = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    OUT.mkdir(exist_ok=True)
    # keep the rows of sources not run this time
    old = {}
    idx = OUT / "index.tsv"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 7 and (OUT / c[0]).exists() and c[0].split("/")[0] not in wanted:
                old[c[0]] = tuple(c[:7])
    for name in wanted:
        SOURCES[name]()
    final = dict(old)
    for r in rows:
        final[r[0]] = tuple(clean(x) for x in r)
    with open(idx, "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tissuing_body\n")
        for rel in sorted(final):
            f.write("\t".join(final[rel]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for t in NOT_OBTAINED + failures:
            f.write("\t".join(clean(x) for x in t) + "\n")
    on_disk = {str(p.relative_to(OUT)) for p in OUT.rglob("*.pdf") if ".large" not in p.parts}
    stray = sorted(on_disk - set(final))
    n, size = used()
    kinds = {}
    for r in final.values():
        kinds[r[4]] = kinds.get(r[4], 0) + 1
    print(f"done: {len(final)} documents in index ({kinds}), {stats['new']} new, {size / 1e6:.1f} MB in folder, "
          f"{len(failures)} failures, closed hosts: {blocked or 'none'}")
    if stray:
        print("files without an index row:", stray)


if __name__ == "__main__":
    main()

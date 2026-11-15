#!/usr/bin/env python3
"""Colombia: guidance for migration officers published by Migración Colombia, plus the
procedure-setting resolutions officers work from.

    python3 download_co.py

Sources (see co/NOTES.txt for what was checked and what is missing):

  sig     www.migracioncolombia.gov.co  Planeación > Procesos y procedimientos: the
          quality-system packages (ZIP) of the three case-handling processes - Gestión
          Control Migratorio, Gestión Verificación Migratoria, Gestión Extranjería:
          process manual, procedures, guides (guías), instructions (instructivos) and the
          list of applicable norms (normograma). The ZIPs are unpacked; every member is
          saved byte for byte under co/sig/<process>/ and the ZIP itself is not kept.
  actos   www.migracioncolombia.gov.co  Normativa: circulares, directivas, resoluciones
          and conceptos. Only items about migration case handling are kept (KEEP below);
          staffing, contracting, fees and similar are left out.
  nexus   nexusmigracion.cancilleria.gov.co  Marco normativo nacional: the resolutions
          of the Foreign Ministry and Migración Colombia (visas, permits, sanctions).
          Laws, decrees and CONPES papers on that page are not downloaded.

www.cancilleria.gov.co (the ministry's own normograma) answers scripts with a
Cloudflare check (HTTP 403) and is not contacted.

Rules: robots.txt is read for each host and obeyed; one request at a time, at least
1.2 s apart per host; a host that answers 403 or 429, or resets the connection three
times in a row, is not asked again in that run. Files that exist are skipped;
co/index.tsv and co/not-obtained.tsv are rebuilt on every run. Standard library only.
"""
import html
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "co"
TMP = OUT / ".tmp"
MANIFEST = OUT / "listings" / "zip-manifest.tsv"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.2
MAX_BYTES = 500_000_000
MAX_FILES = 1500

MC = "https://www.migracioncolombia.gov.co"
NX = "https://nexusmigracion.cancilleria.gov.co"
MC_BODY = "Unidad Administrativa Especial Migración Colombia (UAEMC)"
MRE_BODY = "Ministerio de Relaciones Exteriores"

SIG_PAGE = MC + "/planeacion-y-estadistica/procesos-y-procedimientos"
# folder name in the ZIP address -> (local folder, process name)
SIG_PROCESSES = [
    (re.compile(r"control_migratorio", re.I), "control-migratorio", "Gestión Control Migratorio"),
    (re.compile(r"VERIFICACI.N_MIGRATORIA", re.I), "verificacion-migratoria", "Gestión Verificación Migratoria"),
    (re.compile(r"EXTRANJER.A", re.I), "extranjeria", "Gestión Extranjería"),
]
# ZIP members that are not case-handling guidance (information security, records management, the decree itself)
SIG_SKIP = [
    (re.compile(r"Thumbs\.db$", re.I), None),
    (re.compile(r"Decreto ", re.I), "skipped on purpose: decree (legislation, not guidance)"),
    (re.compile(r"SGSI|Seguridad y Priva|Datos Personales|Activos de Informaci|Incidentes de Seguridad"
                r"|Informaci.n P.blica|^MEF\.\d|Seguridad en la Informacion", re.I),
     "skipped on purpose: information-security / records-management document, not case guidance"),
]

ACT_PAGES = [
    ("Circular", MC + "/normativa-y-documentacion/normativa/circulares"),
    ("Directiva", MC + "/normativa-y-documentacion/normativa/directivas"),
    ("Resolución", MC + "/normativa-y-documentacion/normativa/resoluciones"),
    ("Concepto", MC + "/normativa-y-documentacion/normativa/conceptos"),
]
KEEP = re.compile(
    r"extranjer|permiso|PEPFF|\bPPT\b|protecci[oó]n temporal|estatuto temporal|venezolan|RUMV|sancionatori"
    r"|obligaciones migratorias|c[eé]dula|contrase[nñ]a|salida del pa[ií]s|movimientos migratorios|control migratorio"
    r"|verificaci[oó]n migratoria|salvoconducto|cuarentena|^Resoluci.n 0?971 de 2021|centro facilitador", re.I)
DROP = re.compile(r"tarifas|jornada|d[ií]a c[ií]vico|grupos internos|contrataci|honorarios|planta|empleos", re.I)

# further documents on the Migración Colombia site that no listing page links any more
EXTRA = [
    ("guias/nodate_MVG.14-v3_Guia-procedimientos-acciones-y-estrategias-en-derechos-humanos.pdf",
     "MVG.14 Guía de procedimientos, acciones y estrategias en derechos humanos (Salas Transitorias de Migración), v3",
     "", MC + "/fileadmin/user_upload/normatividad/guia-procedimientos_acciones_estrategias_en_ddhh.pdf",
     "guidance", MC_BODY),
]

# Copies in the Internet Archive of files from the Foreign Ministry's normograma, whose own host
# (www.cancilleria.gov.co) refuses scripts. Fixed snapshots, fetched raw ("id_"), 3 s apart.
WB = "https://web.archive.org/web/{}id_/https://www.cancilleria.gov.co/sites/default/files/Normograma/docs/pdf/{}"
ARCHIVE = [
    ("archivo-web/2012-01-13_Directiva-001-de-2012.pdf", "Directiva 1 de 2012 - Instrucciones para el reporte de movimientos migratorios diarios",
     "2012-01-13", WB.format("20250525145619", "directiva_uaemc_0001_2012.pdf"), "guidance", MC_BODY,
     "Directive 1 of 2012: instructions to regional directors and border-post heads on reporting daily migration movements"),
    ("archivo-web/2012-02-10_Directiva-002-de-2012.pdf", "Directiva 2 de 2012 - Instrucciones para el control migratorio (derogada por Resolución 1688 de 2013)",
     "2012-02-10", WB.format("20240712020029", "directiva_uaemc_0002_2012.pdf"), "guidance", MC_BODY,
     "Directive 2 of 2012: instructions for border (migration) control; repealed by Resolución 1688 of 2013"),
    ("archivo-web/2017-04-21_Directiva-009-de-2017.pdf", "Directiva 0009 de 2017 - Facilitación del proceso de matrícula de menores de edad extranjeros",
     "2017-04-21", WB.format("20250413082136", "directiva_uaemc_0009_2017.pdf"), "guidance", MC_BODY,
     "Directive 9 of 2017: facilitating school enrolment of foreign minors"),
    ("archivo-web/2020-02-13_Circular-008-de-2020.pdf", "Circular 8 de 2020 - Lineamientos para expedir el Permiso Especial de Permanencia para el Fomento de la Formalización (PEPFF)",
     "2020-02-13", WB.format("20240606180440", "circular_uaemc_0008_2020.pdf"), "guidance", MC_BODY,
     "Circular 8 of 2020: guidelines to extranjería officers for issuing the Special Stay Permit for the Promotion of Formalisation (PEPFF)"),
    ("archivo-web/2017-08-02_Resolucion-6045-de-2017.pdf", "Resolución 6045 de 2017 - Por la cual se dictan disposiciones en materia de visas (derogada por Resolución 5477 de 2022)",
     "2017-08-02", WB.format("20210805000847", "resolucion_minrelaciones_6045_2017.pdf"), "procedural act", MRE_BODY,
     "Resolution 6045 of 2017: visa rules (repealed by Resolución 5477 of 2022)"),
    ("archivo-web/2020-09-29_Resolucion-2357-de-2020.pdf", "Resolución 2357 de 2020 - Criterios para el cumplimiento de obligaciones migratorias y procedimiento sancionatorio",
     "2020-09-29", WB.format("20230426215038", "resolucion_uaemc_2357_2020.pdf"), "procedural act", MC_BODY,
     "Resolution 2357 of 2020: criteria for compliance with migration obligations and the sanctions procedure"),
]

NEXUS_PAGE = NX + "/marcos-normativos/marco-normativo-nacional"
# resolution number -> (date, issuing body); anything else on the page is not downloaded
NEXUS_KEEP = {
    "0360": ("2015", MC_BODY), "1220": ("2016", MC_BODY), "5797": ("2017", MRE_BODY),
    "10064": ("2018", MRE_BODY), "3548": ("2019", MRE_BODY), "0240": ("2020", MRE_BODY),
    "0971": ("2021", MC_BODY), "5477": ("2022", MRE_BODY), "12509": ("2024", MRE_BODY),
}

# exact dates read from the documents themselves (number, year) -> date
DATES = {("971", "2021"): "2021-04-28", ("1284", "2021"): "2021-06-15", ("5477", "2022"): "2022-07-22",
         ("5797", "2017"): "2017-07-25"}

# Items known to exist that this script does not fetch: (item, reason, url)
NOT_OBTAINED = [
    ("Cancillería normograma (Avance Jurídico compilation): Migración Colombia and Foreign Ministry resolutions, "
     "directivas and circulares, 2012 onwards",
     "blocked: www.cancilleria.gov.co answers scripts with a Cloudflare bot check (HTTP 403), also for robots.txt; "
     "needs a browser. The Internet Archive holds part of it: six relevant files were taken from there (co/archivo-web/)",
     "https://www.cancilleria.gov.co/normograma/compilacion/"),
    ("Resolución UAEMC 0760 de 2016 - adopts Manual de Procedimientos de Control Migratorio v4 and Guía de sellos v3",
     "blocked (Cloudflare 403); not in the Internet Archive index either (checked 2026-11-15)",
     "https://www.cancilleria.gov.co/sites/default/files/Normograma/docs/pdf/resolucion_uaemc_0760_2016.pdf"),
    ("Resolución MRE 10434 de 2023 - procedure for recognising stateless persons",
     "blocked (Cloudflare 403); not in the Internet Archive index either (checked 2026-11-15)",
     "https://www.cancilleria.gov.co/sites/default/files/Normograma/docs/pdf/resolucion_minrelaciones_10434_2023.pdf"),
    ("Directiva UAEMC 011 de 2012 - instructions for extranjería procedures",
     "blocked (Cloudflare 403); not in the Internet Archive index either (checked 2026-11-15)",
     "https://www.cancilleria.gov.co/sites/default/files/Normograma/docs/pdf/directiva_uaemc_0011_2012.pdf"),
    ("Resoluciones UAEMC 0112, 0114, 0516, 0801, 1186, 1188 de 2012 - first manuals of verification, control and "
     "extranjería (superseded)",
     "blocked (Cloudflare 403); not in the Internet Archive index either (checked 2026-11-15)",
     "https://www.cancilleria.gov.co/sites/default/files/Normograma/docs/pdf/resolucion_uaemc_0112_2012.pdf"),
    ("Rama Judicial SIDN copies of Resolución 5477 de 2022, 10434 de 2023, UAEMC 3167 de 2019",
     "blocked: sidn.ramajudicial.gov.co answers HTTP 403 (robots.txt included)",
     "https://sidn.ramajudicial.gov.co/SIDN/NORMATIVA/TEXTOS_COMPLETOS/8_RESOLUCIONES/"),
    ("Cancillería quality-system procedures for visa officers (DP-PT-150 authorisation of consulates to issue visas, "
     "DP-PT-168 visa processing in Bogotá, DP-PT-173, visa instructivo) and for refugee status determination (CONARE)",
     "not published: held in the ministry's internal 'Sistema Maestro'; only cited in audit reports",
     "https://www.cancilleria.gov.co/sites/default/files/FOTOS2020/"
     "informe_auditoria_desarrollo_de_la_politica_exterior_-_git_de_visas.pdf"),
    ("Earlier versions of the Migración Colombia guides (e.g. MCG.01 v1-v5) and guides withdrawn from the packages",
     "not on the current site; old portal.migracioncolombia.gov.co addresses now redirect; needs web archive",
     "https://portal.migracioncolombia.gov.co/fileadmin/user_upload/"),
]

# English gloss of titles: first matching pattern wins
GLOSS = [
    (r"MCC ", "Process characterisation: migration (border) control, v8"),
    (r"MCMA\.01", "Manual of the migration (border) control process, v5"),
    (r"MCP\.01", "Procedure: control and authorisation of entry to the country, v5"),
    (r"MCP\.02", "Procedure: control and authorisation of exit from the country, v5"),
    (r"MCP\.04", "Procedure: handling of advance passenger information (APIS) alerts, v1"),
    (r"MCP\.05", "Procedure: requesting and supplying information, v1"),
    (r"MCG\.01", "Guide: general instructions for migration control at border posts, v6"),
    (r"MCG\.02", "Guide: persons with more than one nationality, v6"),
    (r"MCG\.03", "Guide: special treatment of certain migrants (refused entry, deported, expelled, repatriated, "
                  "stowaways, shipwrecked, returning Colombians), v8"),
    (r"MCG\.04", "Guide: migration control of children and adolescents, v9"),
    (r"MCG\.05", "Guide: maritime and river migration control, v6"),
    (r"MCG\.11", "Guide: contingency and operational plans for migration control, v4"),
    (r"MCG\.14 Anexo", "Guide on automated and biometric migration controls: annex 1, fee exemption"),
    (r"MCG\.14", "Guide: automated and biometric migration controls, v5"),
    (r"MCG\.16", "Guide: document examination, v4"),
    (r"MCG\.17", "Guide: fingerprint examination, v4"),
    (r"MCG\.18", "Guide: handwriting examination, v4"),
    (r"MCG\.24", "Guide: data quality in migration control, v4"),
    (r"MCG\.25", "Guide: migration control at land borders, v3"),
    (r"MCG\.26 Anexo", "Guide on migration control at airports: annex 1"),
    (r"MCG\.26", "Guide: migration control at airports, v3"),
    (r"MCG\.27", "Guide: operation of the Joint Migration Analysis Centre (CECAM), v4"),
    (r"MCG\.28", "Guide: generation of operational alerts, v3"),
    (r"MCG\.29", "Guide: stamps used in migration control, foreigners' registration and verification, v2"),
    (r"MCI\.01", "Instruction: migration control of cargo crews, v1"),
    (r"MCI\.02", "Instruction: migration control of passengers posing a risk of contagion, v1"),
    (r"MCI\.03", "Instruction: SIRE reporting system - international maritime and river transport, v1"),
    (r"MCI\.04.Anexo", "Instruction on Colombia-Ecuador road freight crews: annex A"),
    (r"MCI\.04", "Instruction: migration control of international road freight crews, Colombia-Ecuador, v2"),
    (r"Normograma Proceso Gesti.n Control Migratorio \(Excel\)",
     "List of norms applicable to the migration control process (Excel, with the acts embedded)"),
    (r"Normograma Proceso Gesti.n Control", "List of norms applicable to the migration control process"),
    (r"MVC ", "Process characterisation: migration verification (enforcement), v7"),
    (r"MVP\.01", "Procedure: conduct of the administrative sanctions procedure in migration matters, v5"),
    (r"MVP\.02", "Procedure: judicial-police activities of Migración Colombia in the pre-investigation stage, v1"),
    (r"MVG\.12", "Guide: conduct of the administrative sanctions procedure (fines, deportation, expulsion), v9"),
    (r"MVG\.14", "Guide: procedures, actions and strategies on human rights (transitory migration rooms), v3"),
    (r"MVG\.17", "Guide: reporting data on migration verifications, v1"),
    (r"MVG\.18", "Guide: migration verifications (inspections of foreigners, employers, hotels etc.), v2"),
    (r"MVG\.19", "Guide: judicial-police actions, v1"),
    (r"MVI\.49", "Instruction: recording and consulting information in the verification modules of SIRE and "
                  "Platinum, v1"),
    (r"MVI\.50", "Instruction: SIRE external user, v1"),
    (r"Normograma Proceso Gesti.n Verificaci.n Migratoria \(Excel\)",
     "List of norms applicable to the migration verification process (Excel, with the acts embedded)"),
    (r"Normograma Proceso Gesti.n Verificaci", "List of norms applicable to the migration verification process "
                                               "(signed)"),
    (r"MEC ", "Process characterisation: foreigners' registration and documents (extranjería), v10"),
    (r"MEP\.05", "Procedure: issue of foreigner identity cards (cédula de extranjería), v2"),
    (r"MEP\.06", "Procedure: issue of certificates of migratory movements, v2"),
    (r"MEP\.08", "Procedure: issue of the temporary stay permit (PTP), v2"),
    (r"MEP\.10", "Procedure: issue of the safe-conduct (salvoconducto), v2"),
    (r"MEG\.02", "Guide: handling of extranjería applications (registration, identity cards, permits, "
                  "safe-conducts), v7"),
    (r"MEG\.08", "Guide: contingency actions for the extranjería process, v6"),
    (r"MEG\.11", "Guide: consulting, amending and supplying information from the database, v1"),
    (r"MEG\.12", "Guide: handling of applications for the Temporary Protection Permit (PPT) for Venezuelans, v3"),
    (r"MEG\.13", "Guide: administrative register of foreign citizens (CJE), v1"),
    (r"MEI\.03", "Instruction: extranjería user manual for the Platinum system, v2"),
    (r"MEI\.04", "Instruction: producing the ten-fingerprint card, v2"),
    (r"Concepto prueba", "Legal opinion: summary evidence (prueba sumaria)"),
    (r"Otras normas", "Other norms applicable to extranjería, v2"),
    (r"Directiva 003 de 2019", "Directive 003 of 2019: sixth version of the extranjería process characterisation"),
    (r"Directiva 007 de 2017", "Directive 007 of 2017: adopts the guide on data quality in extranjería (MEG.12 v1)"),
    (r"Directiva 016 de 2018", "Directive 016 of 2018: adopts new documents of the extranjería process manual"),
    (r"Directiva 023 de 2016", "Directive 023 of 2016: procedure, guide and form for extranjería applications"),
    (r"Resoluci.n 0?971 +de 2021", "Resolution 0971 of 2021: implements the Temporary Protection Statute for "
                                    "Venezuelan migrants"),
    (r"Resoluci.n 1284 de 2021", "Resolution 1284 of 2021: extends the transition period for certain procedures"),
    (r"Resoluci.n 1499 de 2018", "Resolution 1499 of 2018: adopts the Extranjería Manual, version 4"),
    (r"Resoluci.n 2201 de 2013", "Resolution 2201 of 2013: adopts the Extranjería Manual, version 3"),
    (r"Resoluci.n 2061 de 2020", "Resolution 2061 of 2020: rules on entry, stay and exit, extranjería (replaces "
                                 "Resolution 3167 of 2019)"),
    (r"Resoluci.n 2231 de 2021", "Resolution 2231 of 2021: provisions on entry, transit, stay and exit from the "
                                 "territory"),
    (r"Resoluci.n 2570 de 2019", "Resolution 2570 of 2019: foreigner identity card"),
    (r"Circular 008 de 2020", "Circular 008 of 2020: guidelines for issuing the Special Stay Permit for the "
                              "Promotion of Formalisation (PEPFF)"),
    (r"Circular 017 de 2020", "Circular 017 of 2020: national quarantine (COVID-19) - service arrangements"),
    (r"Resoluci.n 4873", "Resolution 4873 of 2026: closes the Catatumbo migration services centre"),
    (r"Resoluci.n 2451", "Resolution 2451 of 2025: implements the Special Stay Permit for legal representatives "
                         "or custodians of Venezuelan children (Decree 1209 of 2024)"),
    (r"Resoluci.n 4713", "Resolution 4713 of 2024: reopens the Single Register of Venezuelan Migrants (RUMV) and "
                         "defines force majeure for late registration"),
    (r"Resoluci.n 4645", "Resolution 4645 of 2024: amends Resolution 2189 of 2024 on the certificate that a "
                         "Temporary Protection Permit is in process"),
    (r"Resoluci.n 4222", "Resolution 4222 of 2024: 'contraseña' certificate that a foreigner identity card is in "
                         "process"),
    (r"Resoluci.n 2189", "Resolution 2189 of 2024: extends the certificate that a Temporary Protection Permit is "
                         "in process"),
    (r"Resoluci.n 2945", "Resolution 2945 of 2020: amends chapters I and III of Resolution 2357 of 2020 on "
                         "migration obligations and the sanctions procedure"),
    (r"Concepto jur.dico: FAMILIA DE CRIANZA", "Legal opinion: foster ('de crianza') families and authorisation for children to "
                            "leave the country"),
    (r"Concepto jur.dico: RESERVA Y ACCESO", "Legal opinion: confidentiality of and access to the certificate of migratory movements"),
    (r"Resoluci.n 0360", "Resolution 0360 of 2015: compliance with migration obligations and sanctions procedure"),
    (r"Resoluci.n 1220", "Resolution 1220 of 2016: border mobility card (TMF)"),
    (r"Resoluci.n 5797", "Resolution 5797 of 2017: creates the Special Stay Permit (PEP) for Venezuelans"),
    (r"Resoluci.n 10064", "Resolution 10064 of 2018: validity and conditions of the Special Stay Permit (PEP)"),
    (r"Resoluci.n 3548", "Resolution 3548 of 2019: Complementary Special Stay Permit (PEPC) for refused asylum "
                         "seekers"),
    (r"Resoluci.n 0240", "Resolution 0240 of 2020: new term for the Special Stay Permit (PEP)"),
    (r"Resoluci.n 5477", "Resolution 5477 of 2022: visa rules (types, requirements, procedure)"),
    (r"Resoluci.n 12509", "Resolution 12509 of 2024: adds the 'V - special visitor' visa to Resolution 5477"),
]

MONTHS = {m: i + 1 for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}

blocked = {}       # host -> reason
resets = {}        # host -> consecutive connection errors
last_hit = {}      # host -> time of last request
robots = {}        # host -> RobotFileParser or None
failures = []      # (item, reason, url)
stats = {"new": 0}


def host_of(url):
    return urllib.parse.urlsplit(url).netloc


def quote_url(u):
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(urllib.parse.unquote(p.path), safe="/")))


def wait(host):
    gap = time.time() - last_hit.get(host, 0)
    delay = 3.0 if host.endswith("archive.org") else DELAY
    if gap < delay:
        time.sleep(delay - gap)
    last_hit[host] = time.time()


def open_url(url):
    """One request. Returns a response object or None; marks the host blocked on 403/429 or three resets."""
    host = host_of(url)
    if host in blocked:
        return None
    wait(host)
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180)
        resets[host] = 0
        return r
    except urllib.error.HTTPError as e:
        resets[host] = 0
        if e.code in (403, 429):
            blocked[host] = f"HTTP {e.code}"
            print(f"  BLOCKED by {host} (HTTP {e.code}); not asking this host again")
        else:
            print(f"  HTTP {e.code} {url}")
        failures.append((url.rsplit("/", 1)[-1], f"HTTP {e.code}", url))
    except Exception as e:                          # noqa: BLE001 - connection trouble: count it
        resets[host] = resets.get(host, 0) + 1
        print(f"  FAILED {url}: {e}")
        failures.append((url.rsplit("/", 1)[-1], f"connection error: {e}", url))
        if resets[host] >= 3:
            blocked[host] = "three connection errors in a row"
            print(f"  giving up on {host}")
    return None


def allowed(url):
    """robots.txt check; the file is fetched once per host (404 = everything allowed, 403 = nothing)."""
    host = host_of(url)
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser()
        wait(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://{host}/robots.txt", headers={"User-Agent": UA}), timeout=60) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                blocked[host] = f"robots.txt answers HTTP {e.code}"
                print(f"  BLOCKED: {host} robots.txt answers HTTP {e.code}")
            rp.parse([])                            # 404 and the like: no rules
        except Exception as e:                      # noqa: BLE001
            blocked[host] = f"robots.txt unreachable: {e}"
            print(f"  {host}: robots.txt unreachable ({e}); host not used")
        robots[host] = rp
    if host in blocked:
        return False
    ok = robots[host].can_fetch("*", url)
    if not ok:
        failures.append((url.rsplit("/", 1)[-1], "disallowed by robots.txt", url))
    return ok


def page(url):
    if not allowed(url):
        return ""
    r = open_url(url)
    if not r:
        return ""
    with r:
        s = r.read().decode("utf-8", "replace")
    listing = OUT / "listings" / (re.sub(r"[^A-Za-z0-9]+", "-", url.split("//")[1]).strip("-") + ".html")
    listing.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text(s, encoding="utf-8")
    return s


def total_size():
    # repository metadata and the split copies of large files made for publishing do not count
    files = [p for p in OUT.rglob("*") if p.is_file() and ".tmp" not in p.parts and ".git" not in p.parts
             and not re.search(r"\.(part\d+|sha256)$", p.name)]
    return len(files), sum(p.stat().st_size for p in files)


def room():
    n, b = total_size()
    if n >= MAX_FILES or b >= MAX_BYTES:
        print(f"  limit reached ({n} files, {b // 1_000_000} MB); nothing more is downloaded")
        return False
    return True


def fetch_to(url, dest):
    """Stream url into dest (via a temporary file). Returns True if dest exists afterwards."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    if not room() or not allowed(url):
        return False
    r = open_url(url)
    if not r:
        return False
    TMP.mkdir(parents=True, exist_ok=True)
    part = TMP / "download.part"
    try:
        with r, open(part, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except Exception as e:                          # noqa: BLE001
        print(f"  FAILED while reading {url}: {e}")
        failures.append((dest.name, f"transfer failed: {e}", url))
        part.unlink(missing_ok=True)
        return False
    if not good_file(part, dest.suffix.lower()):
        print(f"  not a valid {dest.suffix} file, discarded: {url}")
        failures.append((dest.name, "server did not return a valid file (error or bot-check page?)", url))
        part.unlink(missing_ok=True)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    part.replace(dest)
    stats["new"] += 1
    return True


def good_file(path, suffix):
    with open(path, "rb") as f:
        head = f.read(8)
    if suffix == ".pdf":
        if not head.startswith(b"%PDF"):
            return False
        if shutil.which("pdfinfo"):
            return subprocess.run(["pdfinfo", str(path)], capture_output=True).returncode == 0
        return True
    if suffix in (".zip", ".xlsx", ".docx"):
        return head.startswith(b"PK") and zipfile.is_zipfile(path)
    return not head.lstrip().lower().startswith((b"<!doc", b"<html"))


def text_of(markup):
    t = html.unescape(html.unescape(re.sub(r"<[^>]+>", " ", markup)))
    return re.sub(r"\s+", " ", t).strip()


def slug(s, n=110):
    s = urllib.parse.unquote(s)
    for a, b in zip("áàéèíìóòúùñÁÀÉÈÍÌÓÒÚÙÑ", "aaeeiioouunAAEEIIOOUUN"):
        s = s.replace(a, b)
    return re.sub(r"[^A-Za-z0-9.()-]+", "-", s).strip("-.")[:n].strip("-.") or "x"


def date_in(s):
    m = re.search(r"\b(\d{1,2})\s+de\s+(%s)\s+(?:de|del)\s+(\d{4})" % "|".join(MONTHS), s, re.I)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\bde[l]?\s+((?:19|20)\d\d)\b", s)
    return m.group(1) if m else ""


def act_number(s):
    m = re.search(r"\b(?:No\.?\s*)?(\d{2,5})\s+(?:de|del)\b", s)
    return m.group(1) if m else ""


def exact_date(title, date):
    """Replace a bare year by the exact date where one was read from the document."""
    return DATES.get((act_number(title).lstrip("0"), date[:4]), date)


def own_date(path, ext):
    """Date the file itself carries (PDF CreationDate, Office 'modified'); '' if none. Approximate."""
    try:
        if ext == ".pdf":
            if shutil.which("pdfinfo"):
                out = subprocess.run(["pdfinfo", "-isodates", str(path)], capture_output=True, text=True).stdout
                m = re.search(r"^CreationDate:\s+(\d{4}-\d\d-\d\d)", out, re.M)
                if m:
                    return m.group(1)
            with open(path, "rb") as f:
                data = f.read()
            m = re.search(rb"/CreationDate\s*\(D:(\d{4})(\d\d)(\d\d)", data)
            return "-".join(g.decode() for g in m.groups()) if m else ""
        if ext in (".xlsx", ".docx"):
            with zipfile.ZipFile(path) as z:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
            m = re.search(r"<dcterms:modified[^>]*>(\d{4}-\d\d-\d\d)", core)
            return m.group(1) if m else ""
    except Exception:                               # noqa: BLE001
        pass
    return ""


def gloss(title):
    for pat, en in GLOSS:
        if re.match(pat, title, re.I):
            return en
    return ""


def kind_of(title):
    return "procedural act" if re.match(r"\s*(Resoluci|Decreto)", title, re.I) else "guidance"


# ---------------------------------------------------------------- quality-system packages

def member_name(info):
    name = info.filename
    if not info.flag_bits & 0x800:                  # not flagged UTF-8: undo the cp437 guess where it was wrong
        try:
            name = name.encode("cp437").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name.replace("\\", "/").split("/")[-1]


def load_manifest():
    """zip url -> list of (member, status, local file or reason)."""
    man = {}
    if MANIFEST.exists():
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) == 4:
                man.setdefault(p[0], []).append((p[1], p[2], p[3]))
    return man


def save_manifest(man):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        f.write("zip_url\tmember\tstatus\tfile_or_reason\n")
        for url, members in man.items():
            for m in members:
                f.write("\t".join((url,) + tuple(m)) + "\n")


def do_sig(rows, skipped):
    s = page(SIG_PAGE)
    man = load_manifest()
    links = list(dict.fromkeys(re.findall(r'href="([^"]+\.zip)"', s)))
    if not links:
        print("  sig: no ZIP links found on the listing page (page unreachable or changed)")
    for href in links:
        url = quote_url(urllib.parse.urljoin(SIG_PAGE, html.unescape(href)))
        plain = urllib.parse.unquote(url)
        proc = next(((d, n) for rx, d, n in SIG_PROCESSES if rx.search(plain)), None)
        if not proc:
            continue
        folder, procname = proc
        done = man.get(url)
        if not done or any(st == "saved" and not (OUT / f).exists() for _, st, f in done):
            z = TMP / "package.zip"
            z.unlink(missing_ok=True)
            if not fetch_to(url, z):
                continue
            done = []
            with zipfile.ZipFile(z) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = member_name(info)
                    reason = next((why for rx, why in SIG_SKIP if rx.search(name)), "")
                    if reason is None:              # junk such as Thumbs.db
                        continue
                    if reason:
                        done.append((name, "skipped", reason))
                        continue
                    tmp = TMP / "member"
                    with zf.open(info) as src, open(tmp, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    ext = Path(name).suffix.lower()
                    if not good_file(tmp, ext):
                        done.append((name, "skipped", "member is not a valid " + ext + " file"))
                        tmp.unlink()
                        continue
                    stem = slug(re.sub(r"\s+", " ", Path(name).stem))
                    if re.match(r"(Resoluci|Directiva|Decreto)", name):     # an act: its own year or date
                        date = exact_date(name, date_in(name))
                    else:                           # a quality-system document: the date the file carries
                        date = own_date(tmp, ext)
                    local = f"sig/{folder}/{date or 'nodate'}_{stem}{ext}"
                    (OUT / local).parent.mkdir(parents=True, exist_ok=True)
                    tmp.replace(OUT / local)
                    done.append((name, "saved", local))
            z.unlink(missing_ok=True)
            man[url] = done
            save_manifest(man)
            print(f"  sig: unpacked {plain.rsplit('/', 3)[-3]}/{plain.rsplit('/', 1)[-1]}")
        for name, status, val in done:
            title = re.sub(r"\s+", " ", Path(name).stem).strip()
            if status == "saved":
                if (OUT / val).exists():
                    full = title if re.match(r"(Resoluci|Directiva|Decreto|Concepto)", title) \
                        else f"{title} [{procname}]"
                    date = val.split("/")[-1].split("_")[0]
                    rows[val] = (val, full, "" if date == "nodate" else date, url + "#" + name,
                                 kind_of(title), MC_BODY, gloss(title))
            else:
                skipped.append((f"{title} [{procname}]", val, url + "#" + name))


# ---------------------------------------------------------------- acts listed on the Migración Colombia site

def do_actos(rows):
    for tipo, url in ACT_PAGES:
        s = page(url)
        cards = re.split(r'(?=data-document-id=")', s)[1:]
        if not cards:
            print(f"  actos: no entries found on {url}")
        for c in cards:
            m = re.search(r'data-searchable="([^"]*)"', c)
            href = re.search(r'<a\s+href="([^"]+)"\s+download=', c)
            st = re.search(r'data-share-title="([^"]*)"', c)
            if not (m and href):
                continue
            title = text_of(st.group(1)) if st else ""
            desc = text_of(m.group(1))
            desc = re.sub(r"\s*Norma \d{4}.*$", "", desc).strip()
            if desc and not desc.lower().startswith(title.lower()[:12]):
                desc = f"{title} - {desc}" if title else desc
            full = desc or title
            if tipo != "Concepto" and (not KEEP.search(full) or DROP.search(full)):
                continue
            if tipo == "Concepto" and not full.lower().startswith("concepto"):
                full = "Concepto jurídico: " + full
            src = quote_url(urllib.parse.urljoin(url, html.unescape(href.group(1))))
            date = date_in(full)
            if not date:
                y = re.search(r'data-norma_ano="(\d{4})"', c)
                date = y.group(1) if y else ""
            date = exact_date(full, date)
            num = act_number(title or full)
            ext = Path(urllib.parse.urlsplit(src).path).suffix.lower() or ".pdf"
            label = f"{tipo}-{num}" if num else tipo
            if tipo == "Concepto":
                label = "Concepto_" + slug(full.split(":", 1)[-1].strip().title(), 60)
            local = f"actos/{date or 'nodate'}_{slug(label)}{ext}"
            if fetch_to(src, OUT / local):
                rows[local] = (local, full[:400], date, src,
                               "procedural act" if tipo == "Resolución" else "guidance", MC_BODY, gloss(full))


def do_extra(rows):
    for local, title, date, url, kind, body in EXTRA:
        if fetch_to(url, OUT / local):
            rows[local] = (local, title, date, url, kind, body, gloss(title))


def do_archive(rows):
    for local, title, date, url, kind, body, en in ARCHIVE:
        if fetch_to(url, OUT / local):
            rows[local] = (local, title, date, url, kind, body, en)


# ---------------------------------------------------------------- Cancillería "Nexus Migración" portal

def do_nexus(rows):
    s = page(NEXUS_PAGE)
    seen = set()
    for href, inner in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', s, flags=re.S | re.I):
        label = text_of(inner)
        m = re.match(r"Resoluci[oó]n\s+(\d+)\s+(?:de \w+ )?del?\s+(\d{4})", label)
        if not m or m.group(1) not in NEXUS_KEEP or href in seen:
            continue
        seen.add(href)
        num, year = m.groups()
        date, body = NEXUS_KEEP[num]
        date = DATES.get((num.lstrip("0"), year), date)
        src = quote_url(urllib.parse.urljoin(NEXUS_PAGE, html.unescape(href)))
        fname = urllib.parse.unquote(src.rsplit("/", 1)[-1])
        topic = re.sub(r"Resoluci.n_?\d+_?(de_)?(\w+_)?(de_?)?\s?\d{4}_?", "", Path(fname).stem).replace("_", " ")
        title = f"Resolución {num} de {year}" + (f" - {topic.strip()}" if topic.strip() else "")
        local = f"cancilleria/{date}_Resolucion-{num}-de-{year}.pdf"
        if fetch_to(src, OUT / local):
            rows[local] = (local, title, date, src, "procedural act", body, gloss(title))


def main():
    OUT.mkdir(exist_ok=True)
    rows = {}
    index = OUT / "index.tsv"
    if index.exists():                              # keep rows of files a failed listing could not confirm
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) == 7 and (OUT / p[0]).exists():
                rows[p[0]] = tuple(p)
    skipped = []
    do_sig(rows, skipped)
    do_actos(rows)
    do_extra(rows)
    do_nexus(rows)
    do_archive(rows)
    shutil.rmtree(TMP, ignore_errors=True)

    rows = {k: v for k, v in rows.items() if (OUT / k).exists()}
    with open(index, "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\tissuing_body\ttitle_en\n")
        for k in sorted(rows):
            f.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in rows[k]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("item\treason\turl\n")
        for item in NOT_OBTAINED + sorted(set(skipped)) + failures:
            f.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in item) + "\n")
        for host, why in blocked.items():
            f.write(f"(host) {host}\tnot used further in this run: {why}\thttps://{host}/\n")
    n, b = total_size()
    kinds = {}
    for r in rows.values():
        kinds[r[4]] = kinds.get(r[4], 0) + 1
    print(f"co: {len(rows)} documents indexed ({kinds}), {stats['new']} downloads this run, "
          f"{n} files / {b / 1e6:.0f} MB in {OUT}")
    if failures or blocked:
        print(f"    {len(failures)} failures, blocked hosts: {blocked or 'none'} - see co/not-obtained.tsv")


if __name__ == "__main__":
    main()

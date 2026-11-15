#!/usr/bin/env python3
"""Download Mexico's published guidance for migration, visa and refugee case officers into ./mx/.

    python3 download_mx.py              everything: listing, downloads, mx/index.tsv, mx/not-obtained.tsv
    python3 download_mx.py dof gob      only the named sources (upm, dof, gob, wayback)
    python3 download_mx.py --index      only rebuild the two .tsv files from what is on disk (no network)
    python3 download_mx.py --discover 2026-01-01 2026-12-31
                                        print DOF notes in that period whose title looks migration-related
                                        (to find new instruments to add to EXTRA_DOF below); downloads nothing

What it collects (lineamientos, acuerdos, circulares, protocolos, manuales; not the statutes):
    upm/      consolidated ("texto vigente") PDFs kept by the Unidad de Política Migratoria, Registro e
              Identidad de Personas (SEGOB) in its "Compendio de Normatividad Migratoria", sections 4 and 7
    dof/      the instruments as published in the Diario Oficial de la Federación, one Word file per note,
              from SEGOB's own DOF system (sidof.segob.gob.mx): every DOF note the compendium links to in
              sections 4 and 7, plus the notes listed in EXTRA_DOF (found by scanning the DOF daily indexes)
    inm/      protocols the Instituto Nacional de Migración publishes on gob.mx/inm
    comar/    Comisión Mexicana de Ayuda a Refugiados: procedures manual, operating guide (gob.mx/comar)
    otros/    inter-agency guidance that binds INM/COMAR officers (SIPINNA route for migrant children)
    historico/  pre-2012 texts that survive only in the Wayback Machine copy of the INM's old website

Rules the script follows:
  - robots.txt of every host is read first and obeyed. dof.gob.mx disallows /nota_detalle.php for all
    agents, so DOF notes are never fetched from dof.gob.mx; SEGOB's SIDOF serves the same notes and allows it.
  - one connection, sequential requests, DELAY seconds apart per host (Wayback slower).
  - HTTP 403/429 from a host: that host is left alone for the rest of the run. No retries, no workarounds.
  - sre.gob.mx (bot-manager redirect), www.inm.gob.mx (WAF block page) and acnur.org (403) are never
    contacted; their documents are taken from the Wayback Machine or listed in mx/not-obtained.tsv.
  - files that already exist are skipped; files are saved exactly as served; anything that is not a
    PDF or Word file (error pages, bot-check pages) is discarded.
Standard library only.
"""
import html
import json
import re
import sys
import time
import datetime
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "mx"
CACHE = OUT / "listings"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = {"web.archive.org": 10.0}                    # seconds between requests to one host
DEFAULT_DELAY = 1.5
MAX_FILES, MAX_BYTES = 3000, 1_000_000_000

UPM = "https://portales.segob.gob.mx"
COMPENDIO = UPM + "/es/PoliticaMigratoria/Nnacional"
SIDOF = "https://sidof.segob.gob.mx"
GOB = "https://www.gob.mx/cms/uploads/attachment/file/"
WAYBACK = "https://web.archive.org/web/"
NEVER = {"dof.gob.mx", "www.dof.gob.mx", "sre.gob.mx", "www.sre.gob.mx", "www.inm.gob.mx", "inm.gob.mx",
         "www.acnur.org", "acnur.org"}              # robots / bot checks: see docstring

# Compendium rows that are about Mexican passports, legalisations, household goods or welfare
# programmes rather than about deciding foreigners' cases are left out.
OFF_TOPIC = re.compile(r"pasaportes y del documento de identidad|contenido de los (pasaportes|documentos de identidad)"
                       r"|Legalizaci|menaje|Programa para el Bienestar|Manual de Organizaci.n General de la Secretar"
                       r"|DECRETO por el que se expide la Ley"
                       r"|uniforme|Consejo Ciudadano|Consejo Consultivo|Control de Confianza|cambio de domicilio", re.I)

# --------------------------------------------------------------------------------------------------
# DOF notes that the UPM compendium does not link to. (code, date, issuing body, title)
# Found with --discover over 2010-2026 and checked by hand.  Titles are the DOF index titles.
EXTRA_DOF = [
    # EXTRA_DOF_BEGIN
    ('5129775', '2010-01-29', 'Secretaría de Gobernación', 'Acuerdo por el que se expide el Manual de Criterios y Trámites Migratorios del Instituto Nacional de Migración'),
    ('5131660', '2010-02-12', 'Secretaría de Gobernación', 'Circular No. 001/2010, por la que se instruye el procedimiento para la atención de los niños, niñas y adolescentes migrantes no acompañados'),
    ('5133762', '2010-03-03', 'Secretaría de Gobernación', 'Circular que establece los lineamientos para el diseño, elaboración, distribución, asignación, reposición, registro, control, guarda y uso del sello migratorio de control fronterizo'),
    ('5146481', '2010-06-10', 'Secretaría de Gobernación', 'Acuerdo por el que se dan a conocer las características y especificaciones de las Visas de Lectura Electrónica'),
    ('5180784', '2011-03-07', 'Secretaría de Gobernación', 'Acuerdo por el que se delegan facultades para ejercer las atribuciones en materia de Refugiados y Protección Complementaria previstas en la Ley sobre Refugiados y Protección Complementaria'),
    ('5611673', '2021-02-17', 'Secretaría de Gobernación', 'Acuerdo por el que se autoriza la habilitación de espacios de alojamiento para los cuidados alternativos y/o acogimiento residencial de Niñas, Niños y Adolescentes en contexto de migración'),
    ('5721069', '2024-03-22', 'Secretaría de Gobernación', 'Acuerdo por el cual se dan a conocer los formatos de solicitud de visas mexicanas'),
    ('5757619', '2025-05-20', 'Secretaría de Gobernación', 'Acuerdo por el que se reforma el artículo 7 del diverso por el que se emiten los Lineamientos generales para la transmisión de listas electrónicas de pasajeros, tripulantes y medios de transporte al Instituto Nacional de Migración'),
    ('5782199', '2026-03-13', 'Secretaría de Gobernación', 'Acuerdo por el que se eliminan requisitos y se establecen acciones de simplificación y mejora administrativa de trámites que se realizan ante la Comisión Mexicana de Ayuda a Refugiados'),
    ('5787660', '2026-05-15', 'Secretaría de Gobernación', 'Acuerdo por el que se reforman y adicionan los Lineamientos Generales para la expedición de visas que emiten las secretarías de Gobernación y de Relaciones Exteriores'),
    ('5276966', '2012-11-08', 'Secretaría de Gobernación', 'Lineamientos generales para la expedición de visas que emiten las secretarías de Gobernación y de Relaciones Exteriores'),
    ('5276967', '2012-11-08', 'Secretaría de Gobernación', 'Lineamientos para trámites y procedimientos migratorios'),
    # EXTRA_DOF_END
]

# English glosses, by DOF note code or by file stem.
GLOSS = {
    # GLOSS_BEGIN
    '5179426': 'Agreement creating the INM Vetting and Trust Control Centre',
    '5193668': 'Circular instructing the procedure INM must follow to detect, identify and assist foreign victims of crime',
    '5193935': 'Erratum to the circular on foreign victims of crime',
    '5210006': 'Agreement delegating powers on refugees and complementary protection to INM officials',
    '5275514': "Agreement creating SEGOB's Migration Policy Advisory Council",
    '5275515': "Agreement on the structure and operation of the INM Citizens' Council",
    '5276965': 'Rules for the operation of INM migration stations (detention centres) and provisional holding facilities',
    '5276969': 'General guidelines for transmitting electronic passenger and crew lists (API) to INM',
    '5276970': 'Operating guidelines of the INM Vetting and Trust Control Centre',
    '5277359': 'Agreement delegating powers to INM federal delegations to authorise immigration procedures',
    '5280488': 'Guidelines on protection of migrants (Beta groups, child protection officers, repatriation)',
    '5280487': 'Agreement designating the Chactemal vehicle crossing as an international transit point',
    '5290719': 'Agreement designating the Boquillas del Carmen land crossing as an international transit point',
    '5312385': 'Guidelines for issuing non-ordinary (diplomatic, official, service) visas',
    '5322024': 'Notice to airlines on the electronic mechanism for passenger information (art. 46 Migration Act)',
    '5323243': 'Amendment to the Guidelines for immigration procedures (26 Nov 2013)',
    '5328783': 'Amendment to the circular on migration documents and application forms (3 Jan 2014)',
    '5329084': 'Amendment to the Guidelines for immigration procedures (7 Jan 2014)',
    '5351464': 'Agreement instructing the creation of Comprehensive Border Transit Care Centres (CAITF)',
    '5356563': 'Amendment to the Guidelines for immigration procedures (15 Aug 2014)',
    '5363603': 'General guidelines for visas issued by SEGOB and SRE, 2014 text (replaced 2025)',
    '5402292': 'Amendment to the circular on migration documents and application forms (30 Jul 2015)',
    '5404983': 'Agreement designating the Matamoros-Brownsville railway bridge as an international transit point',
    '5419404': 'Agreement designating the Tijuana-San Diego airport pedestrian link as an international transit point',
    '5422123': 'Amendment to the Guidelines for immigration procedures (5 Jan 2016)',
    '5437383': 'Amendment to the Guidelines for immigration procedures (17 May 2016)',
    '5447404': 'Protocol to ensure respect for the principles and rights of children in administrative immigration proceedings',
    '5455318': 'Amendment to the Guidelines for immigration procedures (30 Sep 2016)',
    '5515621': "Amendment to the agreement attaching SEGOB's deconcentrated bodies (9 Mar 2018)",
    '5533392': 'Amendment to the circular on migration documents and application forms (31 Jul 2018)',
    '5540561': 'Agreement waiving the visa requirement for ordinary-passport holders from the United Arab Emirates',
    '5545102': 'Agreement waiving the visa requirement for ordinary-passport holders from Ecuador',
    '5555320': 'Amendment to the circular on migration documents and application forms (27 Mar 2019)',
    '5558294': 'Amendment to the Guidelines for immigration procedures (23 Apr 2019)',
    '5583060': 'Amendment to the Guidelines for immigration procedures (30 Dec 2019)',
    '5604026': 'General organisation manual of the National Migration Institute (INM)',
    '5610849': 'Amendment to the circular on migration documents and application forms (4 Feb 2021)',
    '5617885': 'Agreement waiving the visa requirement for ordinary-passport holders from Bolivia',
    '5622105': 'Inter-agency strategy for comprehensive care of repatriated and returning Mexican families',
    '5623427': 'Amendment to the agreement creating the Migration Policy Advisory Council (9 Jul 2021)',
    '5636486': 'Agreement temporarily imposing a visitor visa on Brazilian ordinary-passport holders',
    '5640345': 'Agreement imposing a visitor visa on Venezuelan ordinary-passport holders',
    '5643829': 'Agreement indefinitely suspending the visa waiver for Ecuadorian nationals',
    '5645367': 'Agreement designating Felipe Ángeles International Airport as an international transit point',
    '5672525': 'Amendment to the guidelines on border-control entry stamps (28 Nov 2022)',
    '5688669': 'Agreement publishing the passport and visa forms used by Mexican consular offices',
    '5691809': "Internal guidelines of the INM Citizens' Council",
    '5691808': 'Amendment to the operating guidelines of the INM Vetting and Trust Control Centre (12 Jun 2023)',
    '5708067': 'Agreement on personal appearance and uniform of INM staff',
    '5719385': 'Notice of INM offices authorised to process APEC Business Travel Card (ABTC) applications',
    '5720385': 'Agreement publishing the characteristics and specifications of Mexican visas',
    '5722445': 'Agreement temporarily imposing a visitor visa on Peruvian ordinary-passport holders',
    '5723725': 'Amendment to the agreement imposing a visitor visa on Peruvian nationals (18 Apr 2024)',
    '5735225': "Notice of change of address of COMAR's central office in Mexico City",
    '5763838': 'Agreement on simplification and administrative improvement of procedures before INM',
    '5763837': 'General guidelines for visas issued by SEGOB and SRE (2025 text, in force)',
    '5767837': 'Amendment to art. 2 of the agreement imposing a visitor visa on Brazilian nationals',
    '2012-11-08_Lineamientosdetramitesyprocedimientosmigratorios': 'Guidelines for immigration procedures (consolidated text kept by the UPM): the rules INM officers apply to every residence, visitor and regularisation application',
    '2012-11-08_Integracion-Archivo-UPMRIP-Circularformatosysolicitud': 'Circular on migration documents and the application and statistical forms of the INM (consolidated text)',
    '2013-04-04_ACUERDO-ADSCRIBEN-ORGANOS-DESCONCENTRA-DOS-SEGOB': 'Agreement attaching SEGOB deconcentrated bodies (INM, COMAR) to its undersecretariats (consolidated text)',
    '2020-04-23_Lineamientos-Sellos-Migratorios': 'Guidelines on the design, issue, control and use of immigration entry/exit stamps at points of entry (consolidated text)',
    '2021-08-20_ACUERD-2': 'Agreement issued 20 Aug 2021 kept in the UPM compendium (see title)',
    '5129775': 'Agreement issuing the INM Manual of Migration Criteria and Procedures (2010; superseded by the 2012 Lineamientos)',
    '5131660': 'Circular 001/2010 instructing INM staff on the procedure for unaccompanied migrant children',
    '5133762': 'Circular setting the guidelines on immigration border-control stamps (2010)',
    '5146481': 'Agreement on the characteristics and specifications of machine-readable visas (2010)',
    '5180784': 'Agreement delegating powers on refugees and complementary protection (COMAR / Undersecretary, 2011)',
    '5611673': 'Agreement authorising accommodation spaces for alternative care of migrant children (2021)',
    '5721069': 'Agreement publishing the Mexican visa application forms (2024)',
    '5757619': 'Amendment (art. 7) to the guidelines on advance passenger and crew lists (2025)',
    '5782199': 'Agreement removing requirements and simplifying procedures before COMAR (2026)',
    '5787660': 'Amendment to the General Guidelines for issuing visas (SEGOB/SRE), May 2026',
    '5276966': 'General guidelines for issuing visas (SEGOB/SRE), original 2012 text (replaced 2014)',
    '5276967': 'Guidelines for immigration procedures, as first published in the DOF (8 Nov 2012); the consolidated text is in upm/',
    # GLOSS_END
}

# Documents on gob.mx (attachment id/name, folder, date, issuing body, title, English gloss, page)
GOB_DOCS = [
    ("672447/PROTOCOLO_1WEB.pdf", "inm", "2021-10-07", "Instituto Nacional de Migración",
     "Protocolo de Operación de Revisiones Migratorias",
     "Protocol for the conduct of immigration checks (revisiones migratorias)",
     "https://www.gob.mx/inm/documentos/protocolo-de-operacion-de-revisiones-migratorias"),
    ("672448/PROTOCOLO_2020WEB.pdf", "inm", "2021-10-07", "Instituto Nacional de Migración",
     "Protocolo de Atención en México a Personas Migrantes en Flujos Masivos",
     "Protocol for attending to migrants arriving in Mexico in mass flows",
     "https://www.gob.mx/inm/documentos/protocolo-de-atencion-en-mexico-a-personas-migrantes-en-flujos-masivos"),
    ("547982/Protocolo_de_actuaci_n__INM_DGPS.pdf", "inm", "2020-04-20", "Instituto Nacional de Migración",
     "Protocolo de actuación para la prevención y atención de casos sospechosos y confirmados de COVID-19 en las "
     "Estaciones Migratorias y Estancias Provisionales del Instituto Nacional de Migración",
     "Protocol for preventing and handling suspected and confirmed COVID-19 cases in INM detention centres",
     "https://www.gob.mx/inm/documentos/protocolo-de-actuacion-en-las-estaciones-migratorias-y-estancias-provisionales"),
    ("548677/PSO_COVID19.pdf", "inm", "2020-04-28", "Instituto Nacional de Migración",
     "Procedimiento Sistemático de Operación ante el brote del nuevo Coronavirus COVID-19",
     "Standard operating procedure for the COVID-19 outbreak (points of entry)",
     "https://www.gob.mx/inm/documentos/procedimiento-sistematico-de-operacion-ante-el-brote-nuevo-coronavirus-covid-19"),
    ("415838/N00_MP_FINAL2.pdf", "comar", "2018-11-28", "Comisión Mexicana de Ayuda a Refugiados",
     "Manual de Procedimientos de la Coordinación General de la Comisión Mexicana de Ayuda a Refugiados",
     "Procedures manual of the General Coordination of the Mexican Commission for Refugee Assistance (COMAR)",
     "https://www.gob.mx/comar/documentos/manual-de-procedimientos-de-la-coordinacion-general-de-la-comision-mexicana-de-ayuda-a-refugiados"),
    ("194101/MOE_N00_COMAR.pdf", "comar", "2017-02-23", "Comisión Mexicana de Ayuda a Refugiados",
     "Manual de Organización Específico de la Coordinación General de la Comisión Mexicana de Ayuda a Refugiados",
     "Specific organisation manual of COMAR's General Coordination",
     "https://www.gob.mx/comar/documentos/manual-de-organizacion-especifico"),
    ("805229/COMAR_-__GU_A_OPERATIVA_NNA_.pdf", "comar", "2022-03-07", "Comisión Mexicana de Ayuda a Refugiados",
     "Guía operativa para la atención de las solicitudes de reconocimiento de la condición de refugiado de niñas, "
     "niños y adolescentes migrantes acompañados, separados y no acompañados",
     "Operating guide for handling refugee-status applications from accompanied, separated and unaccompanied "
     "migrant children (date is the PDF creation date)",
     "https://www.gob.mx/comar/documentos/marco-juridico-en-materia-de-refugiados"),
    ("775149/Ruta_Protecci_n_Integral_de_Derechos_NNA_situac_n_migraci_n.pdf", "otros", "2022-10-01",
     "SIPINNA (Sistema Nacional de Protección Integral de Niñas, Niños y Adolescentes)",
     "Ruta de Protección Integral de Derechos de Niñas, Niños y Adolescentes en Situación de Migración "
     "(Acuerdo SIPINNA/02/VE/2022)",
     "Comprehensive protection route for the rights of migrant children: inter-agency procedure binding INM, "
     "COMAR, DIF and child-protection offices (approved October 2022; day of month not stated)",
     "https://www.gob.mx/sipinna"),
]

# Documents that survive only in the Wayback Machine (timestamp, original URL, folder, date, body, title, gloss)
WAYBACK_DOCS = [
    ("20070612000901", "http://www.inm.gob.mx/paginas/marcojuridico/acuerdos/CIRCULAR%2021-09-2000_Manual%20Tr%C3%A1mites%20Migratorios.pdf",
     "historico", "2000-09-21", "Instituto Nacional de Migración",
     "Circular 014/2000 por la que se da a conocer el Manual de Trámites Migratorios del Instituto Nacional de Migración (DOF 21-09-2000)",
     "Circular issuing the INM Manual of Immigration Procedures (2000; superseded 2010)"),
    ("20070612000146", "http://www.inm.gob.mx/paginas/marcojuridico/acuerdos/ACUERDO%2026-11-2001_Normas%20Estaciones%20Migratorias.pdf",
     "historico", "2001-11-26", "Secretaría de Gobernación",
     "Acuerdo por el que se emiten las normas para el funcionamiento de las estaciones migratorias del Instituto Nacional de Migración (DOF 26-11-2001)",
     "Rules for the operation of INM detention centres (2001; superseded 2009)"),
    ("20101101010847", "http://inm.gob.mx/static/marco_juridico/pdf/acuerdos/2010/52_ACUERDO_DOF_07-OCT-2009.pdf",
     "historico", "2009-10-07", "Secretaría de Gobernación",
     "Acuerdo por el que se emiten las Normas para el funcionamiento de las Estaciones Migratorias del Instituto Nacional de Migración (DOF 07-10-2009)",
     "Rules for the operation of INM detention centres (2009; superseded 2012)"),
    ("20101124045714", "http://inm.gob.mx/static/marco_juridico/pdf/acuerdos/2010/17_ACUERDO_DE_FACILIDADES_DOF_03-NOV-2008.pdf",
     "historico", "2008-11-03", "Secretaría de Gobernación",
     "Acuerdo que tiene por objeto establecer facilidades para el ingreso al país de extranjeros considerados personas de "
     "negocios titulares de una ABTC y las reglas para aprobar y expedir la ABTC (DOF 03-11-2008)",
     "Agreement on entry facilitation for APEC Business Travel Card holders and rules for approving and issuing the card (2008)"),
    ("20101124045808", "http://inm.gob.mx/static/marco_juridico/pdf/acuerdos/2010/51_ACUERDO_DOF_11-NOV-2008.pdf",
     "historico", "2008-11-11", "Secretaría de Gobernación",
     "Acuerdo que tiene por objeto establecer los criterios conforme a los cuales los extranjeros que se encuentren de manera irregular en territorio nacional podrán promover la obtención de su documentación migratoria (DOF 11-11-2008)",
     "Regularisation criteria for foreigners in an irregular situation (2008)"),
    ("20070612000650", "http://www.inm.gob.mx/paginas/marcojuridico/acuerdos/ACUERDO%2022-12-2006_Regularizaci%C3%B3n%20Migratoria.pdf",
     "historico", "2006-12-22", "Secretaría de Gobernación",
     "Acuerdo que tiene por objeto establecer los criterios conforme a los cuales los extranjeros, de cualquier nacionalidad, "
     "que habiten en el territorio nacional, podrán promover la obtención de su documentación migratoria en la calidad "
     "migratoria de No Inmigrante (DOF 22-12-2006)",
     "Regularisation criteria for foreigners living in Mexico without documents (2006)"),
    ("2", "https://www.acnur.org/fileadmin/Documentos/Publicaciones/2016/10855.pdf",
     "comar", "2016-07-14", "Comisión Mexicana de Ayuda a Refugiados / ACNUR / UNICEF",
     "Protocolo de evaluación inicial para la identificación de indicios de necesidades de protección internacional en niñas, niños y adolescentes no acompañados o separados (2016)",
     "Initial-assessment protocol for identifying international-protection needs of unaccompanied or separated children "
     "(first edition 2016; date is the PDF creation date)"),
]

# Known to exist but not obtainable by script. (title, issuing body, url, reason)
NOT_PUBLISHED = [
    ("Guía Consular / guía de procedimientos de visas para oficinas consulares (vigente)", "Secretaría de Relaciones Exteriores",
     "https://sre.gob.mx/normateca", "sre.gob.mx redirects scripts to a bot-manager check (validate.perfdrive.com); "
     "not worked around. The Wayback Machine lists 1,092 archived files of the SRE Normateca Interna (2011-2023); "
     "none is a visa manual (the 2004 consular-documentation manual covers passports, consular ID and notarial acts only), "
     "so the consular visa guide appears to be internal."),
    ("Normateca Interna de la Secretaría de Relaciones Exteriores (listado actual)", "Secretaría de Relaciones Exteriores",
     "https://sre.gob.mx/normateca-interna", "bot-manager check on sre.gob.mx; open in a browser."),
    ("Marco jurídico / normateca del INM en su sitio propio", "Instituto Nacional de Migración",
     "https://www.inm.gob.mx/gobmx/word/index.php/marco-juridico/", "www.inm.gob.mx answers scripts with a WAF "
     "'URL blocked' page (also for robots.txt); host not used. Pre-2012 texts were taken from the Wayback Machine."),
    ("Manuales de procedimientos internos del INM (control y verificación, estaciones migratorias, regulación migratoria)",
     "Instituto Nacional de Migración", "https://www.gob.mx/inm/archivo/documentos",
     "not published: none appears among the 360 documents on gob.mx/inm, in the UPM compendium or in the DOF; "
     "only the Manual de Organización General (DOF 02-11-2020) is public. Request via the Plataforma Nacional de Transparencia."),
    ("Oficios-instrucción y circulares internas del Comisionado del INM", "Instituto Nacional de Migración",
     "https://www.plataformadetransparencia.org.mx/", "not published; released only case by case through transparency requests."),
    ("Lineamientos/criterios internos de elegibilidad de la COMAR", "Comisión Mexicana de Ayuda a Refugiados",
     "https://www.gob.mx/comar/archivo/documentos", "not published: gob.mx/comar carries only the 2018 procedures manual, "
     "the organisation manual and the children's operating guide."),
]

# --------------------------------------------------------------------------------------------------
blocked = {}        # host -> reason
failures = {}       # host -> consecutive failures
last_hit = {}       # host -> time of last request
robots = {}         # host -> RobotFileParser or None (= no robots.txt: everything allowed)
saved_bytes = 0
OFFLINE = "--index" in sys.argv


def http_get(url):
    """One polite GET, no robots check. Returns (bytes, None) or (None, reason). Never retries."""
    host = urllib.parse.urlsplit(url).netloc
    if host in NEVER:
        return None, f"{host} is not fetched by script (robots.txt or bot check)"
    if host in blocked:
        return None, blocked[host]
    wait = DELAY.get(host, DEFAULT_DELAY) - (time.time() - last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last_hit[host] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            final = urllib.parse.urlsplit(r.geturl()).netloc
            data = r.read()
        if final != host and final not in ("web.archive.org",):
            if "perfdrive" in final or "captcha" in final:
                blocked[host] = f"blocked: {host} redirects to a bot check ({final})"
                return None, blocked[host]
        failures[host] = 0
        return data, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            blocked[host] = f"blocked: HTTP {e.code} from {host}"
            print(f"  {host} answered {e.code}; leaving it alone for the rest of this run")
            return None, blocked[host]
        failures[host] = 0
        return None, f"HTTP {e.code}"
    except Exception as e:                          # noqa: BLE001 - report, do not retry
        failures[host] = failures.get(host, 0) + 1
        if failures[host] >= (2 if host == "web.archive.org" else 3):
            blocked[host] = f"unreachable: {host} refused or failed {failures[host]} times in a row ({type(e).__name__})"
            print(f"  {host} keeps failing; leaving it alone for the rest of this run")
        return None, f"{type(e).__name__}: {e}"


def allowed(url):
    """robots.txt check for the generic user agent. The file is fetched once per host."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host in NEVER:
        return False
    if host == "web.archive.org":                   # has no robots.txt (HTTP 404, checked 2026-11-15)
        return True
    if host not in robots:
        data, why = http_get(f"{parts.scheme}://{host}/robots.txt")
        if data is None:
            if host in blocked:
                return False
            robots[host] = None                     # 404 and the like: no rules
        else:
            text = data.decode("utf-8", "replace")
            if "<html" in text[:2000].lower():      # an HTML page instead of rules: treat as no robots.txt
                robots[host] = None
            else:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(text.splitlines())
                robots[host] = rp
    rp = robots[host]
    return True if rp is None else rp.can_fetch("*", url)


def fetch(url):
    if not allowed(url):
        host = urllib.parse.urlsplit(url).netloc
        return None, blocked.get(host, f"disallowed by robots.txt of {host}")
    return http_get(url)


def clean(markup):
    t = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return re.sub(r"\s+", " ", t).strip()


def slug(s, n=70):
    s = urllib.parse.unquote(s)
    for a, b in zip("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN"):
        s = s.replace(a, b)
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:n].strip("-") or "x"


def kind_of(data):
    if data[:5] == b"%PDF-":
        return ".pdf"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc"
    if data[:4] == b"PK\x03\x04":
        return ".docx"
    return None                                     # HTML error/bot-check page or something unexpected


def category(title):
    """Type of instrument, from the first word of its title."""
    m = re.match(r"\W*([A-Za-zÁÉÍÓÚÑáéíóúñ]+)", title)
    word = m.group(1).lower() if m else ""
    known = {"acuerdo": "acuerdo", "aviso": "aviso", "circular": "circular", "lineamientos": "lineamientos",
             "lineamentos": "lineamientos", "protocolo": "protocolo", "manual": "manual", "programa": "programa",
             "guía": "guía", "ruta": "ruta", "procedimiento": "procedimiento", "normas": "normas",
             "reforma": "reforma", "fe": "fe de erratas", "nota": "nota aclaratoria", "aclaración": "nota aclaratoria",
             "decreto": "decreto", "reglas": "reglas", "criterios": "criterios", "oficio": "oficio"}
    return known.get(word, "otro")


def kind_for(title, cat):
    """guidance (instructions, protocols, manuals addressed to officers) or procedural act."""
    if cat in ("protocolo", "manual", "guía", "ruta", "procedimiento"):
        return "guidance"
    if cat == "circular" and not re.search(r"formatos|sello", title, re.I):
        return "guidance"
    if re.search(r"Manual de (Criterios y )?Tr.mites|Protocolo|Gu.a operativa", title, re.I):
        return "guidance"
    return "procedural act"


def existing(folder, pattern):
    for old in sorted(folder.glob(pattern)):
        if old.is_file() and old.stat().st_size > 0:
            return old
    return None


def save(url, folder, stem, pattern, live=True):
    """Download url to folder/stem.<ext> unless a file matching pattern is there. Returns (relpath, note)."""
    global saved_bytes
    old = existing(folder, pattern)
    if old:
        return str(old.relative_to(OUT)), ""
    if OFFLINE or not live:
        return "", "not downloaded"
    if saved_bytes > MAX_BYTES or sum(1 for p in OUT.rglob("*") if p.is_file()) > MAX_FILES:
        return "", "not downloaded: size/file limit reached"
    data, why = fetch(url)
    if data is None:
        return "", why
    ext = kind_of(data)
    if ext is None:
        return "", "not a document (HTML or unknown content returned)"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (stem + ext)
    dest.write_bytes(data)
    saved_bytes += len(data)
    print(f"  saved {dest.relative_to(OUT)} ({len(data) // 1024} kB)")
    return str(dest.relative_to(OUT)), ""


# ---------------------------------------------------------------------------------- UPM compendium
def compendium():
    """Fetch (or reuse) the compendium page. Returns its HTML or None."""
    cached = CACHE / "upm-compendio-nacional.html"
    if not OFFLINE:
        data, why = fetch(COMPENDIO)
        if data is not None and b"DISPOSICIONES COMPLEMENTARIAS" in data:
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        else:
            print(f"upm: compendium page not retrieved ({why or 'unexpected content'}); using cached copy if any")
    return cached.read_text("latin-1") if cached.exists() else None


def iso(dmy):
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", dmy or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""


def compendium_items(page):
    """Parse sections 4 (disposiciones complementarias) and 7 (documentos históricos).

    Yields dicts: kind 'dof' (cod, date, parent, amends) or 'upm' (url, date, title)."""
    page = re.sub(r"<!--.*?-->", "", page, flags=re.S)
    a = page.find("DISPOSICIONES COMPLEMENTARIAS")
    b = page.find("NORMATIVIDAD VINCULADA", a)
    c = page.find("DOCUMENTOS HIST", b)
    d = page.find("Compendio_Fin", c)
    body = page[a:b] + (page[c:d if d > 0 else None] if c > 0 else "")
    seen = set()
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
        if not cells or "<a " not in cells[0]:
            continue
        cell = cells[0]
        text = clean(cell)
        parent = re.split(r"Reformas?\s*:|Reforma\b|Fe de Erratas", text)[0].strip(" ,.•")
        if OFF_TOPIC.search(parent):
            continue
        pos = 0
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', cell, flags=re.S):
            href, label = html.unescape(m.group(1)).strip(), clean(m.group(2))
            before = clean(cell[pos:m.start()])
            amends = bool(re.search(r"Reforma|Fe de Erratas", before + " " + label)) or \
                bool(re.search(r"Reforma|Fe de Erratas", clean(cell[:m.start()])))
            cod = re.search(r"nota_detalle\.php\?codigo=(\d+)", href)
            if cod:
                key = cod.group(1)
                if key in seen:
                    continue
                seen.add(key)
                fecha = re.search(r"fecha=(\d\d/\d\d/\d{4})", href)
                yield {"kind": "dof", "cod": key, "date": iso(fecha.group(1)) if fecha else iso(label),
                       "parent": parent, "amends": amends}
            elif "/work/models/" in href and re.search(r"\.pdf$", href, re.I):
                path = urllib.parse.urlsplit(href).path if href.startswith("http") else href
                url = UPM + urllib.parse.quote(urllib.parse.unquote(path))
                if url in seen:
                    continue
                seen.add(url)
                yield {"kind": "upm", "url": url, "date": iso(parent[-40:]) or iso(parent), "title": parent}
            pos = m.end()


# ------------------------------------------------------------------------------------- DOF (SIDOF)
def dof_titles():
    """cod -> (date, org, existeDoc, title), from the cache file listings/dof-titles.tsv."""
    out = {}
    f = CACHE / "dof-titles.tsv"
    if f.exists():
        for line in f.read_text("utf-8").splitlines():
            p = line.split("\t")
            if len(p) == 5:
                out[p[0]] = tuple(p[1:])
    return out


def dof_day(date_iso):
    """All notes of one DOF day from SIDOF's open-data web service: list of dicts, or None."""
    d = datetime.date.fromisoformat(date_iso)
    data, why = fetch(f"{SIDOF}/dof/sidof/notas/{d:%d-%m-%Y}")
    if data is None:
        return None
    try:
        j = json.loads(data.decode("utf-8", "replace"))
    except ValueError:
        return None
    notes = []
    for ed in ("NotasMatutinas", "NotasVespertinas", "NotasExtraordinarias"):
        notes += j.get(ed) or []
    return notes


def lookup_titles(items, known):
    """Fill the cache with the DOF index title of every item that has none yet (one request per day)."""
    need = sorted({it["date"] for it in items if it["cod"] not in known and it["date"] and not it.get("title")})
    if not need or OFFLINE:
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / "dof-titles.tsv", "a", encoding="utf-8") as f:
        for day in need:
            notes = dof_day(day)
            if notes is None:
                continue
            wanted = {it["cod"] for it in items if it["date"] == day and it["cod"] not in known}
            for n in notes:
                cod = str(n.get("codNota"))
                if cod in wanted:
                    row = (day, n.get("codOrgaDos") or n.get("nombreCodOrgaUno") or "", n.get("existeDoc") or "",
                           re.sub(r"\s+", " ", n.get("titulo") or "").strip())
                    known[cod] = row
                    f.write("\t".join((cod,) + row) + "\n")
            for cod in wanted - set(known):         # not in that day's index: remember, do not ask again
                known[cod] = (day, "", "", "")
                f.write("\t".join((cod, day, "", "", "")) + "\n")
            f.flush()


BODY = {"SECRETARIA DE GOBERNACION": "Secretaría de Gobernación",
        "SECRETARIA DE RELACIONES EXTERIORES": "Secretaría de Relaciones Exteriores"}


def do_dof(page, rows, live=True):
    items = [it for it in compendium_items(page)] if page else []
    items = [it for it in items if it["kind"] == "dof"]
    have = {it["cod"] for it in items}
    for cod, date, body, title in EXTRA_DOF:
        if str(cod) not in have:
            items.append({"kind": "dof", "cod": str(cod), "date": date, "body": body, "title": title,
                          "parent": "", "amends": False})
    known = dof_titles()
    if live:
        lookup_titles(items, known)
    for it in sorted(items, key=lambda x: (x["date"], x["cod"])):
        cod = it["cod"]
        meta = known.get(cod)
        title = it.get("title") or (meta[3] if meta and meta[3] else "")
        note = ""
        if it["amends"] and it["date"] < (iso(it["parent"][-40:]) or "0"):
            note = "earlier text, listed in the compendium under: " + it["parent"]
            title = title or f"Texto anterior (DOF {it['date']}) de: {it['parent']}"
        elif it["amends"]:
            note = "reforma a: " + it["parent"]
            title = title or f"Reforma (DOF {it['date']}) a: {it['parent']}"
        elif not title:
            title = it["parent"]
        body = it.get("body") or (BODY.get(meta[1], meta[1].title()) if meta and meta[1] else "Secretaría de Gobernación")
        dof_url = "https://www.dof.gob.mx/nota_detalle.php?codigo=%s&fecha=%s" % (
            cod, "/".join(reversed(it["date"].split("-"))))
        url = f"{SIDOF}/notas/getDoc/{cod}"
        old = existing(OUT / "dof", f"*_dof-{cod}_*")
        if old or OFFLINE or not live:
            rel, why = (str(old.relative_to(OUT)), "") if old else ("", "not downloaded")
        elif not allowed(f"{SIDOF}/notas/{cod}"):   # SIDOF's robots.txt withdraws individual notes
            rel, why = "", "note withdrawn from crawling by robots.txt of sidof.segob.gob.mx"
        else:
            rel, why = save(url, OUT / "dof", f"{it['date']}_dof-{cod}_{slug(title)}", f"*_dof-{cod}_*")
        rows.append({"file": rel, "title": title, "date": it["date"], "source_url": url, "body": body,
                     "title_en": GLOSS.get(cod, ""), "category": category(title),
                     "note": "; ".join(x for x in (note, why, "also at " + dof_url) if x)})


def do_upm(page, rows, live=True):
    if not page:
        rows.append({"file": "", "title": "[UPM compendium listing not retrieved]", "date": "", "source_url": COMPENDIO,
                     "body": "Unidad de Política Migratoria, Registro e Identidad de Personas (SEGOB)", "title_en": "",
                     "category": "", "note": blocked.get("portales.segob.gob.mx", "not retrieved")})
        return
    for it in compendium_items(page):
        if it["kind"] != "upm":
            continue
        name = urllib.parse.unquote(it["url"].rsplit("/", 1)[1])
        stem = f"{it['date'] or 'undated'}_{slug(re.sub(r'[.]pdf$', '', name, flags=re.I), 60)}"
        rel, why = save(it["url"], OUT / "upm", stem, stem + ".*", live)
        rows.append({"file": rel, "title": it["title"], "date": it["date"], "source_url": it["url"],
                     "body": "Unidad de Política Migratoria, Registro e Identidad de Personas (SEGOB)",
                     "title_en": GLOSS.get(stem, ""), "category": category(it["title"]),
                     "note": "; ".join(x for x in ("copy kept in the UPM compendium (consolidated text where the title "
                                                    "gives a 'última reforma'); date is the original DOF date", why) if x)})


def do_gob(rows, live=True):
    for path, folder, date, body, title, gloss, page in GOB_DOCS:
        stem = f"{date}_{slug(re.sub(r'[.]pdf$', '', path.split('/', 1)[1]), 50)}_{path.split('/')[0]}"
        rel, why = save(GOB + path, OUT / folder, stem, stem + ".*", live)
        rows.append({"file": rel, "title": title, "date": date, "source_url": GOB + path, "body": body,
                     "title_en": gloss, "category": category(title),
                     "note": "; ".join(x for x in (why, "linked from " + page) if x)})


def do_wayback(rows, live=True):
    for stamp, orig, folder, date, body, title, gloss in WAYBACK_DOCS:
        name = re.sub(r"[.]pdf$", "", urllib.parse.unquote(orig.rsplit("/", 1)[1]), flags=re.I)
        stem = f"{date}_{slug(name, 60)}"
        url = f"{WAYBACK}{stamp}id_/{orig}"
        rel, why = save(url, OUT / folder, stem, stem + ".*", live)
        rows.append({"file": rel, "title": title, "date": date, "source_url": orig, "body": body, "title_en": gloss,
                     "category": category(title),
                     "note": "; ".join(x for x in (why, "via Wayback Machine: " + url) if x)})


# ----------------------------------------------------------------------------------------- discover
KEYWORDS = re.compile(r"migra|visas?\b|refugi|extranjer|asilo|ap[aá]trid|repatria|internaci[oó]n|"
                      r"tr[aá]nsito internacional de personas|condici[oó]n de estancia|visitante", re.I)


def discover(start, end):
    d, stop = datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)
    while d <= stop and "sidof.segob.gob.mx" not in blocked:
        if d.weekday() < 5:
            for n in dof_day(d.isoformat()) or []:
                t = re.sub(r"\s+", " ", n.get("titulo") or "")
                if KEYWORDS.search(t):
                    print("\t".join((d.isoformat(), str(n.get("codNota")), n.get("codOrgaDos") or "", t)), flush=True)
        d += datetime.timedelta(days=1)


# --------------------------------------------------------------------------------------------- main
COLS = ("file", "title", "date", "source_url", "kind", "title_en", "body", "category", "note")
HEAD = ("file", "title", "date", "source_url", "kind", "title_en", "issuing_body", "category", "note")


def tsv(path, header, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for line in lines:
            f.write("\t".join(re.sub(r"[\t\r\n]+", " ", str(c)) for c in line) + "\n")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--discover" in sys.argv:
        discover(args[0], args[1])
        return
    wanted = set(args) or {"upm", "dof", "gob", "wayback"}
    OUT.mkdir(exist_ok=True)
    rows = []
    page = compendium()                             # sources not named are still listed, from disk only
    do_upm(page, rows, "upm" in wanted)
    do_dof(page, rows, "dof" in wanted)
    do_gob(rows, "gob" in wanted)
    do_wayback(rows, "wayback" in wanted)
    for r in rows:
        r["kind"] = kind_for(r["title"], r["category"])
        if not r["title_en"] and r["file"]:
            stem = Path(r["file"]).stem
            cod = re.search(r"_dof-(\d+)_", r["file"])
            r["title_en"] = GLOSS.get(cod.group(1) if cod else stem, "") or GLOSS.get(stem, "")
    rows.sort(key=lambda r: (r["file"].split("/")[0] if r["file"] else "~", r["date"], r["title"]))
    tsv(OUT / "index.tsv", HEAD, [[r[c] for c in COLS] for r in rows if r["file"]])
    missing = [[r["title"], r["date"], r["source_url"], r["note"] or "not downloaded", r["body"]] for r in rows if not r["file"]]
    missing += [[t, "", u, why, b] for t, b, u, why in NOT_PUBLISHED]
    tsv(OUT / "not-obtained.tsv", ("title", "date", "url", "reason", "issuing_body"), missing)
    got = sum(1 for r in rows if r["file"])
    print(f"mx: {got} of {len(rows)} listed documents present; index.tsv and not-obtained.tsv written")
    for host, why in blocked.items():
        print(f"mx: {why}")


if __name__ == "__main__":
    main()

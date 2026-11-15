#!/usr/bin/env python3
"""Peru: guidance for the officials who decide migration cases, published on gob.pe.

    python3 download_pe.py                 # all sources
    python3 download_pe.py migraciones     # one source (migraciones, mapro, rree)

Sources (see pe/NOTES.txt for what was checked, how the list was built and what is missing):

  migraciones  Superintendencia Nacional de Migraciones, www.gob.pe/institucion/migraciones/
               normas-legales: the directivas (lineamientos), protocolos and MAPRO approvals of
               the Superintendencia and its General Management, with the resolutions that
               approve them ("guidance"), and a few resolutions that set the working rule for a
               procedure ("procedural act": PTP requirements, re-entry-ban grading, fine
               exemptions). Fixed list below, built from the site's own keyword filter
               (filter[terms]); the listing's page parameter (?sheet=) is excluded by robots.txt
               and is not used.
  mapro        the procedures-manual page of Migraciones (informes-publicaciones/2766937):
               MAPRO M01 control migratorio, M02 inmigración, S08 verificación y fiscalización,
               and the older DIGEMIN procedures manual with its annexes and flow charts.
               Passport, communications, integrity, user-service and legal-office manuals on the
               same page are left out on purpose.
  rree         Ministerio de Relaciones Exteriores, www.gob.pe/institucion/rree/normas-legales:
               the guidelines on humanitarian migration status, the consular procedures manual
               (MAPRO CONPER) and the 2026 refugee-claim update platform.

Only the PDF files on cdn.www.gob.pe are requested. Rules: robots.txt is read for each host before
anything else and obeyed (rules for "*" and rules that name AI agents; www.gob.pe sets Crawl-delay 5
for GPTBot and that delay is applied; wildcards handled here); one request at a time, at least 2 s
apart per host; a host that answers 401/403/429, serves a challenge page, or fails to connect three
times in a row is not asked again in that run. Files that exist are skipped; pe/index.tsv and
pe/not-obtained.tsv are rebuilt on every run. Standard library only.
"""
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "pe"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
MAX_BYTES = 500_000_000
MAX_FILES = 1500
MAX_ONE = 95_000_000
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "oai-searchbot", "perplexitybot", "bytespider", "ai2bot")

MIG = "Superintendencia Nacional de Migraciones (MIGRACIONES)"
RREE = "Ministerio de Relaciones Exteriores (RREE)"
CDN = "https://cdn.www.gob.pe/uploads/document/file/"
MAPRO_PAGE = "https://www.gob.pe/institucion/migraciones/informes-publicaciones/2766937-manual-de-procedimientos"

# (source, file under pe/<source>/, title, date, page on gob.pe, pdf, kind, title_en)
ITEMS = [
    ('migraciones', '2017-12-28_RS-00000357-2017-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000357-2017-MIGRACIONES: Aprobar la Directiva “Atención a Víctimas de Trata de Personas y Tráfico Ilícito de Migrantes”', '2017-12-28', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440510-00000357-2017-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499078/RS_357_2017_Migraciones.pdf', 'guidance', 'Approves the directive "Assistance to victims of human trafficking and migrant smuggling"'),
    ('migraciones', '2017-12-29_RS-00000361-2017-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000361-2017-MIGRACIONES: Aprobar la Directiva “Lineamientos para el Registro, Actualización y Levantamiento de Alertas Migratorias”', '2017-12-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440509-00000361-2017-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499079/RS_361_2017_Migraciones.pdf', 'guidance', 'Approves the directive "Guidelines for registering, updating and lifting migration alerts"'),
    ('migraciones', '2018-01-30_RS-00000043-2018-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000043-2018-MIGRACIONES: Aprobar la Directiva “Lineamientos para la obtención de la Calidad Migratoria Especial Residente para personas de nacionalidad venezolana con Permiso Temporal de Permanencia”', '2018-01-30', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440942-00000043-2018-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2842674/RS043-2018.pdf.pdf', 'guidance', 'Approves the directive "Guidelines for obtaining the special resident migration status for Venezuelans holding a Temporary Stay Permit (PTP)"'),
    ('migraciones', '2018-03-16_Directiva-M02.SM.DI.003.pdf', 'Directiva M02.SM.DI.003 - Aprobar la Directiva “M02.SM.DI.003-Lineamientos para el Cambio de Calidad Migratoria”', '2018-03-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441864-m02-sm-di-003', 'https://cdn.www.gob.pe/uploads/document/file/1500313/M02.SM.DI.003.pdf', 'guidance', 'Directive M02.SM.DI.003: guidelines for change of migration status'),
    ('migraciones', '2018-03-22_Directiva-M01.SM.DI.003.pdf', 'Directiva M01.SM.DI.003 - Aprobar la Directiva “M01.SM.DI.003-Lineamientos para el Control Migratorio de Personas Nacionales y Extranjeras”', '2018-03-22', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441863-m01-sm-di-003', 'https://cdn.www.gob.pe/uploads/document/file/1500310/M01.SM.DI.003.pdf', 'guidance', 'Directive M01.SM.DI.003: guidelines for migration control of nationals and foreigners'),
    ('migraciones', '2018-03-22_Directiva-M01.SM.DI.004.pdf', 'Directiva M01.SM.DI.004 - Aprobar la Directiva “M01.SM.DI.004-Lineamientos para el Control Migratorio de Personas Nacionales y Extranjeras de Naves Marítimas de Pasajeros y Autorización de Permisos de Tierra para Tripulante', '2018-03-22', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441862-m01-sm-di-004', 'https://cdn.www.gob.pe/uploads/document/file/1500308/M01.SM.DI.004.pdf', 'guidance', 'Directive M01.SM.DI.004: guidelines for migration control of persons on passenger ships and shore-leave permits for crew'),
    ('migraciones', '2018-05-25_Directiva-M02.SM.DI.004.pdf', 'Directiva M02.SM.DI.004 - Aprobar la Directiva “Lineamientos para la expedición del Acta de Permiso de Trabajo Extraordinario – Provisional”', '2018-05-25', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441858-m02-sm-di-004', 'https://cdn.www.gob.pe/uploads/document/file/1500307/M02.SM.DI.004.pdf', 'guidance', 'Directive M02.SM.DI.004: guidelines for issuing the extraordinary provisional work permit record'),
    ('migraciones', '2018-08-16_RS-00000261-2018-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000261-2018-MIGRACIONES: Aprobar el “Protocolo de Verificación y Fiscalización Migratoria en los puestos de Verificación Migratoria” y el “Protocolo de Verificación y Fiscalización Migratoria en los Aeropuertos Internacion', '2018-08-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440728-00000261-2018-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2842593/RS261-2018.pdf.pdf', 'guidance', 'Approves the protocols for migration verification and inspection at verification posts and at international airports'),
    ('migraciones', '2018-11-08_Directiva-M01.SM.DI.001.pdf', 'Directiva M01.SM.DI.001 - Lineamientos para las Alertas Migratorias [Dada de baja]', '2018-11-08', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441855-m01-sm-di-001', 'https://cdn.www.gob.pe/uploads/document/file/1500303/M01.SM.DI.001.pdf', 'guidance', 'Directive M01.SM.DI.001: guidelines on migration alerts (withdrawn)'),
    ('migraciones', '2018-11-08_RS-00000329-2018-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000329-2018-MIGRACIONES: Aprobar la Directiva “M01.SM.DI.001-Lineamientos para las Alertas Migratorias”', '2018-11-08', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440661-00000329-2018-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499197/RS_329_2018_Migraciones.pdf', 'guidance', 'Approves directive M01.SM.DI.001 "Guidelines on migration alerts"'),
    ('migraciones', '2018-11-12_RS-00000333-2018-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000333-2018-MIGRACIONES: Disponer que los ciudadanos venezolanos que solicitaron u obtuvieron el Permiso Temporal de Permanencia – PTP, se encuentran en la obligación de actualizar la información proporcionada a la Superin', '2018-11-12', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440657-00000333-2018-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499199/RS_333_2018_Migraciones.pdf', 'procedural act', 'Orders Venezuelans who applied for or hold the Temporary Stay Permit (PTP) to update the information given to Migraciones'),
    ('migraciones', '2018-11-19_RS-00000344-2018-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000344-2018-MIGRACIONES: Aprobar el “Protocolo de Verificación y Fiscalización Migratoria en los Terminales Terrestres” y el “Protocolo de Verificación y Fiscalización Migratoria en los Establecimientos de Hospedaje”', '2018-11-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440650-00000344-2018-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499188/RS_344_2018_Migraciones.pdf', 'guidance', 'Approves the protocols for migration verification and inspection at bus terminals and at lodging establishments'),
    ('migraciones', '2019-02-14_Directiva-E01.PM.DI.002.2019.pdf', 'Directiva E01.PM.DI.002.2019 - Aprobar la Directiva “E01.PM.DI.002.2019-Acreditación de Personas Extranjeras en Situación de Vulnerabilidad”', '2019-02-14', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441955-e01-pm-di-002-2019', 'https://cdn.www.gob.pe/uploads/document/file/1500401/E01.PM.DI.002.2019.pdf', 'guidance', 'Directive E01.PM.DI.002.2019: accreditation of foreigners in a situation of vulnerability'),
    ('migraciones', '2019-02-14_Directiva-M02.SM.DI.005-2019.pdf', 'Directiva M02.SM.DI.005-2019 - Aprobar la Directiva “M02.SM.DI.005-Lineamientos para la Prórroga de la Calidad Migratoria Especial Residente para personas de nacionalidad venezolana”', '2019-02-14', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441956-m02-sm-di-005-2019', 'https://cdn.www.gob.pe/uploads/document/file/1500403/M02.SM.DI.005-2019.pdf', 'guidance', 'Directive M02.SM.DI.005-2019: guidelines for extending the special resident status of Venezuelans'),
    ('migraciones', '2019-07-26_RS-00000233-2019-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000233-2019-MIGRACIONES: Disponer la exoneración de multa por exceso de permanencia para la población vulnerable constituida por los ciudadanos venezolanos que se encuentran tramitando su Permiso Temporal de P', '2019-07-26', 'https://www.gob.pe/institucion/migraciones/normas-legales/1454758-00000233-2019-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1514453/RS_233_2019_Migraciones.pdf', 'procedural act', 'Exempts vulnerable Venezuelans applying for the PTP from the overstay fine'),
    ('migraciones', '2019-07-26_RS-00000234-2019-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000234-2019-MIGRACIONES: Disponer que todos los ciudadanos extranjeros que se encuentren en territorio nacional y que hayan registrado información ante la Superintendencia Nacional de Migraciones, incluidos l', '2019-07-26', 'https://www.gob.pe/institucion/migraciones/normas-legales/1454757-00000234-2019-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1514459/RS_234_2019_Migraciones.pdf', 'procedural act', 'Orders all foreigners in Peru registered with Migraciones to update their information'),
    ('migraciones', '2019-09-11_RS-00000281-2019-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000281-2019-MIGRACIONES: Otorgar el plazo de sesenta (60) días calendario para que las personas de nacionalidad venezolana que solicitaron el Permiso Temporal de Permanencia – PTP, y que se encuentren pendient', '2019-09-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/1454958-00000281-2019-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1514607/RS_281_2019_Migraciones.pdf', 'procedural act', 'Grants Venezuelans with pending PTP applications 60 days to complete them'),
    ('migraciones', '2019-10-16_RS-00000317-2019-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 00000317-2019-MIGRACIONES: Aprobar el “Protocolo de Verificación y Fiscalización Migratoria en los Aeropuertos Internacionales del Perú” actualizado', '2019-10-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/1454816-00000317-2019-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1514498/RS_317_2019_Migraciones.pdf', 'guidance', "Approves the updated protocol for migration verification and inspection at Peru's international airports"),
    ('migraciones', '2020-06-10_RS-0107-2020-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0107-2020-MIGRACIONES: Prorrogar el plazo de suspensión de inicio del procedimiento administrativo sancionador contra las personas extranjeras que hayan incurrido en infracción migratoria por exceso de perma', '2020-06-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441358-0107-2020-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499728/RS_107_2020_Migraciones.pdf', 'procedural act', 'Extends the suspension of sanction proceedings against foreigners overstaying (COVID-19 emergency)'),
    ('migraciones', '2020-08-10_RS-0169-2020-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0169-2020-MIGRACIONES: Establecer como mecanismo de verificación de la validez de las autorizaciones de viaje de niños, niñas y adolescentes durante el control migratorio de salida del territorio nacional', '2020-08-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441308-0169-2020-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/1499688/RS_169_2020_Migraciones.pdf', 'procedural act', 'Sets the mechanism for verifying the validity of travel authorisations of children at exit control'),
    ('migraciones', '2020-12-29_Directiva-S08.DGTFM.DI.002.pdf', 'Directiva S08.DGTFM.DI.002 - Lineamientos para la Fiscalización Posterior Aleatoria', '2020-12-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/5851045-s08-dgtfm-di-002', 'https://cdn.www.gob.pe/uploads/document/file/6746421/5851045-s08-dgtfm-di-002-lineamientos-para-la-fiscalizacion-posterior-aleatoria_v01.pdf', 'guidance', 'Directive S08.DGTFM.DI.002: guidelines for random ex-post checks of applications'),
    ('migraciones', '2021-02-24_Directiva-M01.DRCM.DI.005.pdf', 'Directiva M01.DRCM.DI.005 - Lineamientos para la aplicación de sanciones a medios de transporte internacional, operadores y establecimientos de hospedaje', '2021-02-24', 'https://www.gob.pe/institucion/migraciones/normas-legales/5603805-m01-drcm-di-005', 'https://cdn.www.gob.pe/uploads/document/file/6393608/5603805-m01-drcm-di-005-lineamientos-para-sanciones-medios-de-transporte-internacional_v01.pdf', 'guidance', 'Directive M01.DRCM.DI.005: guidelines for sanctioning international carriers, operators and lodging establishments'),
    ('migraciones', '2021-02-25_Directiva-M01.DRCM.DI.007.pdf', 'Directiva M01.DRCM.DI.007 - Lineamientos para la aplicación de sanciones a ciudadanos nacionales y extranjeros por infracción a la Norma Migratoria', '2021-02-25', 'https://www.gob.pe/institucion/migraciones/normas-legales/5604371-m01-drcm-di-007', 'https://cdn.www.gob.pe/uploads/document/file/6394428/5604371-m01-drcm-di-007-lineamientos-para-sanciones-a-nacionales-y-extranjeros-por-infraccion-a-la-norma-migratoria_v01.pdf', 'guidance', 'Directive M01.DRCM.DI.007: guidelines for sanctioning nationals and foreigners for breaches of migration rules'),
    ('migraciones', '2021-02-28_Directiva-M01.DRCM.DI.004.pdf', 'Directiva M01.DRCM.DI.004 - Lineamientos para el Control Migratorio de Personas Nacionales y Extranjeras de Medios de Transportes Marítimos [Versión 01] [Dada de baja]', '2021-02-28', 'https://www.gob.pe/institucion/migraciones/normas-legales/2535740-m01-drcm-di-004', 'https://cdn.www.gob.pe/uploads/document/file/2593718/M01.DRCM.DI.004.pdf.pdf', 'guidance', 'Directive M01.DRCM.DI.004 v1: guidelines for migration control of persons on maritime transport (withdrawn)'),
    ('migraciones', '2021-02-28_RS-047-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 047-2021/MIGRACIONES: Aprobar la Directiva: Lineamientos para el Control Migratorio de personas nacionales y extranjeras de medios de transportes marítimos y emisión de Permisos de Tierra para', '2021-02-28', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036821-047-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2037095/Resoluci%C3%B3n%20de%20Superintendencia%20N%C2%B0%2000000047-2021-MIGRACIONES.pdf', 'guidance', 'Approves the directive on migration control of persons on maritime transport and shore-leave permits for crew'),
    ('migraciones', '2021-03-08_RS-039-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 039-2021/MIGRACIONES: Aprobar la Directiva: Lineamientos para el Control Migratorio a nivel nacional\x9d de la Superintendencia Nacional de Migraciones, con código M01.DRCM.DI.003', '2021-03-08', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036828-039-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2037103/Resoluci%C3%B3n%20de%20Superintendencia%20N%C2%B0%2000000039-2021-MIGRACIONES.pdf', 'guidance', 'Approves directive M01.DRCM.DI.003 "Guidelines for migration control nationwide"'),
    ('migraciones', '2021-04-09_RS-080-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 080-2021/MIGRACIONES: Aprobar el Protocolo Atención y Derivación de Personas Migrantes en situación de vulnerabilidad\x9d con Código E01.DPM.PTL.001', '2021-04-09', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036801-080-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2037070/Resoluci%C3%B3n%20de%20Superintendencia%20N%C2%B0%2000000080-2021-MIGRACIONES.pdf', 'guidance', 'Approves protocol E01.DPM.PTL.001 "Attention to and referral of migrants in situations of vulnerability"'),
    ('migraciones', '2021-04-21_Directiva-S08.DGTFM.DI.001.pdf', 'Directiva S08.DGTFM.DI.001 - Lineamientos para la Verificación y Fiscalización de Información y Documentación proporcionada en los Procedimientos y Servicios Migratorios', '2021-04-21', 'https://www.gob.pe/institucion/migraciones/normas-legales/5851013-s08-dgtfm-di-001', 'https://cdn.www.gob.pe/uploads/document/file/6746370/5851013-s08-dgtfm-di-001-lineamientos-verificacion-y-fiscalizacion-de-informacion-y-documentacion_v01.pdf', 'guidance', 'Directive S08.DGTFM.DI.001: guidelines for verifying and checking information and documents submitted in migration procedures and services'),
    ('migraciones', '2021-05-11_Directiva-S05.DIROP.DI.004.pdf', 'Directiva S05.DIROP.DI.004 - Atención a Víctimas de trata de personas y tráfico ilícito de Migrantes', '2021-05-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/5835648-s05-dirop-di-004', 'https://cdn.www.gob.pe/uploads/document/file/6724795/5835648-s05-dirop-di-004-atencion-a-victimas-trata-de-personas-y-trafico-ilicito-de-migrantes.pdf', 'guidance', 'Directive S05.DIROP.DI.004: assistance to victims of human trafficking and migrant smuggling'),
    ('migraciones', '2021-06-10_Directiva-S10.DRCM.DI.002.pdf', 'Directiva S10.DRCM.DI.002 - Lineamientos sobre la Gestión de la Plataforma de Registro de Información Migratoria - RIM', '2021-06-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/5877813-s10-drcm-di-002', 'https://cdn.www.gob.pe/uploads/document/file/6784497/5877813-s10-drcm-di-002-lineamientos-sobre-la-gestion-de-la-plataforma-rim_v01.pdf', 'guidance', 'Directive S10.DRCM.DI.002: guidelines on managing the Migration Information Register (RIM) platform'),
    ('migraciones', '2021-06-11_RS-0131-2021.pdf', 'Resolución de Superintendencia N.° 0131-2021: Aprobar la Directiva Lineamientos para la Depuración de la base de datos del Registro de Información Migratoria RIM\x9d, con Código S10.DRCM.DI.001', '2021-06-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036755-0131-2021', 'https://cdn.www.gob.pe/uploads/document/file/2037022/Resoluci%C3%B3n%20de%20Superintendencia%20N%C2%B0%2000000131-2021-MIGRACIONES.pdf', 'guidance', 'Approves directive S10.DRCM.DI.001 on cleaning the RIM database'),
    ('migraciones', '2021-07-15_Protocolo-de-atenci-n-a-mujeres-migrantes-v-ctimas-de-violen.pdf', 'Protocolo de atención a mujeres migrantes víctimas de violencia', '2021-07-15', 'https://www.gob.pe/institucion/migraciones/informes-publicaciones/2022320-protocolo-de-atencion-a-mujeres-migrantes-victimas-de-violencia', 'https://cdn.www.gob.pe/uploads/document/file/2017132/Protocolo%20de%20atencion%20a%20mujeres%20migrantes%20victimas%20de%20violencia.pdf.pdf', 'guidance', 'Protocol for attending to migrant women who are victims of violence'),
    ('migraciones', '2021-07-15_Protocolo-de-atenci-n-para-personas-extranjeras-v-ctimas-de.pdf', 'Protocolo de atención para personas extranjeras víctimas de trata', '2021-07-15', 'https://www.gob.pe/institucion/migraciones/informes-publicaciones/2022322-protocolo-de-atencion-para-personas-extranjeras-victimas-de-trata', 'https://cdn.www.gob.pe/uploads/document/file/2017134/Protocolo%20de%20atencion%20para%20personas%20extranjeras%20victimas%20de%20trata.pdf.pdf', 'guidance', 'Protocol for attending to foreign victims of human trafficking'),
    ('migraciones', '2021-07-16_RS-0149-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0149-2021-MIGRACIONES: Aprobar la Directiva Disposiciones para la asignación de códigos e iniciales, el uso y resguardo de los sellos de Control Migratorio de la Superintendencia Nacional de M', '2021-07-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323233-0149-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2379245/Resoluci%C3%B3n%20de%20Superintendencia.pdf_', 'guidance', 'Approves the directive on assigning codes and initials and on using and safeguarding migration control stamps'),
    ('migraciones', '2021-07-16_RS-0150-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0150-2021-MIGRACIONES: Aprobar la Directiva “Acreditación de Personas en situación de Vulnerabilidad” con código S05.DIROP-DI.003', '2021-07-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323234-0150-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2379249/Resoluci%C3%B3n%20de%20Superintendencia.pdf_', 'guidance', 'Approves directive S05.DIROP-DI.003 "Accreditation of persons in situations of vulnerability"'),
    ('migraciones', '2021-07-16_RS-0151-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0151-2021-MIGRACIONES: Aprobar el “Protocolo Regularización Migratoria” con código M02.DGTFM.PTL.001', '2021-07-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323235-0151-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2379248/Resoluci%C3%B3n%20de%20Superintendencia.pdf_', 'guidance', 'Approves protocol M02.DGTFM.PTL.001 "Migration regularisation"'),
    ('migraciones', '2021-08-02_Directiva-M03.DGTFM.DI.001.pdf', 'Directiva M03.DGTFM.DI.001 - Gestión de la Nacionalidad Peruana [Dada de baja]', '2021-08-02', 'https://www.gob.pe/institucion/migraciones/normas-legales/5856423-m03-dgtfm-di-001', 'https://cdn.www.gob.pe/uploads/document/file/6754021/5856423-m03-dgtfm-di-001-g-de-la-nacionalidad-peruana_v01.pdf', 'guidance', 'Directive M03.DGTFM.DI.001: management of Peruvian nationality (naturalisation) (withdrawn)'),
    ('migraciones', '2021-08-04_Directiva-M02.DGTFM.DI.003.pdf', 'Directiva M02.DGTFM.DI.003 - Lineamientos para el Cambio de Calidad Migratoria', '2021-08-04', 'https://www.gob.pe/institucion/migraciones/normas-legales/5836119-m02-dgtfm-di-003', 'https://cdn.www.gob.pe/uploads/document/file/6725359/5836119-m02-dgtfm-di-003-lineamientos-para-el-cambio-de-calidad-migratoria_v01.pdf', 'guidance', 'Directive M02.DGTFM.DI.003: guidelines for change of migration status'),
    ('migraciones', '2021-08-04_Directiva-M02.DGTFM.DI.006.pdf', 'Directiva M02.DGTFM.DI.006 - Lineamientos para la Prórroga de la Calidad Migratoria', '2021-08-04', 'https://www.gob.pe/institucion/migraciones/normas-legales/5846358-m02-dgtfm-di-006', 'https://cdn.www.gob.pe/uploads/document/file/6739106/5846358-m02-dgtfm-di-006-lineamientos-para-la-prorroga-de-la-calidad-migratoria_v01.pdf', 'guidance', 'Directive M02.DGTFM.DI.006: guidelines for extension of migration status'),
    ('migraciones', '2021-08-04_Directiva-M02.DGTFM.DI.008.pdf', 'Directiva M02.DGTFM.DI.008 - Lineamientos para la Solicitud de la Calidad Migratoria', '2021-08-04', 'https://www.gob.pe/institucion/migraciones/normas-legales/5846390-m02-dgtfm-di-008', 'https://cdn.www.gob.pe/uploads/document/file/6739146/5846390-m02-dgtfm-di-008-lineamientos-para-la-solicitud-de-la-calidad-migratoria_v01.pdf', 'guidance', 'Directive M02.DGTFM.DI.008: guidelines for applications for a migration status'),
    ('migraciones', '2021-08-06_RS-0166-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0166-2021-MIGRACIONES: Aprobar el “Protocolo Exigencias para el control migratorio de ingreso o salida del país de nacionales y extranjeros”, con código M01.DRCM.PTL.001', '2021-08-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323245-0166-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2379252/Resoluci%C3%B3n%20de%20Superintendencia.pdf_', 'guidance', 'Approves protocol M01.DRCM.PTL.001 "Requirements for migration control on entry to or exit from the country of nationals and foreigners"'),
    ('migraciones', '2021-08-06_RS-0169-2021-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0169-2021-MIGRACIONES: Aprobar las Directivas “Lineamientos para el Cambio de Calidad Migratoria” con código M02.DGTFM.DI.003, “Lineamientos para la Prórroga de la Calidad Migratoria” con Códig', '2021-08-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323248-0169-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2379244/Resoluci%C3%B3n%20de%20Superintendencia.pdf_', 'guidance', 'Approves the directives on change, extension and application of migration status (M02.DGTFM.DI.003, .006, .008)'),
    ('migraciones', '2021-08-11_RGG-0185-2021-GG-MIGRACIONES.pdf', 'Resolución de Gerencia General N.° 0185-2021-GG/MIGRACIONES: Aprobar el Protocolo “Atención de Certificado de Movimiento Migratorio, Certificado de Inscripción en el Registro Central de Extranjería y otros servicios brindados en ex', '2021-08-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/2594791-0185-2021-gg-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2658159/RG00185-2021-GG.pdf_', 'guidance', "Approves the protocol on issuing migration-movement certificates, foreigners' register certificates and other services abroad"),
    ('migraciones', '2021-10-05_Directiva-S06.OAJ.DI.002.pdf', 'Directiva S06.OAJ.DI.002 - Lineamientos para la ejecución de mandatos provenientes de Autoridad Jurisdiccional', '2021-10-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/5891470-s06-oaj-di-002', 'https://cdn.www.gob.pe/uploads/document/file/6805119/5891470-s06-oaj-di-002-lineamientos-para-la-ejecucion-de-mandatos-provenientes-de-a-jurisdiccional_v01.pdf', 'guidance', 'Directive S06.OAJ.DI.002: guidelines for executing orders of judicial authorities'),
    ('migraciones', '2022-04-01_RS-0053-2022-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0053-2022/MIGRACIONES: Disponer la ampliación del plazo de presentación de solicitud de los procedimientos de regularización migratoria previstos en el Decreto Supremo N° 010-2020-IN, por un peri', '2022-04-01', 'https://www.gob.pe/institucion/migraciones/normas-legales/2890241-0053-2022-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2988742/RESOLUCION%20DE%20SUPERINTENDENCIA-000053-2022-MIGRACIONES.pdf.pdf', 'procedural act', 'Extends the deadline for applying under the regularisation procedures of Supreme Decree 010-2020-IN'),
    ('migraciones', '2022-05-06_Directiva-M03.DGTFM.DI.002.pdf', 'Directiva M03.DGTFM.DI.002 - Lineamientos para la atención de Recursos Administrativos interpuestos en los Procedimientos de Nacionalización', '2022-05-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/5856468-m03-dgtfm-di-002', 'https://cdn.www.gob.pe/uploads/document/file/6754080/5856468-m03-dgtfm-di-002-lineamientos-para-recursos-administrativos-en-procedimientos-de-nacionalizacion_v01.pdf', 'guidance', 'Directive M03.DGTFM.DI.002: guidelines for handling administrative appeals in naturalisation procedures'),
    ('migraciones', '2022-05-10_Directiva-M02.DGTFM.DI.001.pdf', 'Directiva M02.DGTFM.DI.001 - Lineamientos para la atención de Recursos Administrativos interpuestos en los Procedimientos de Inmigración', '2022-05-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/5836096-m02-dgtfm-di-001', 'https://cdn.www.gob.pe/uploads/document/file/6725328/5836096-m02-dgtfm-di-001-lineamientos-para-la-atencion-de-recursos-administrativos-interpuestos-en-los-procedimientos-de-inmigracion_v01.pdf', 'guidance', 'Directive M02.DGTFM.DI.001: guidelines for handling administrative appeals in immigration procedures'),
    ('migraciones', '2022-05-10_Directiva-S10.DRCM.DI.001.pdf', 'Directiva S10.DRCM.DI.001 - Lineamientos para la Depuración de la base de datos del RIM', '2022-05-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/5877783-s10-drcm-di-001', 'https://cdn.www.gob.pe/uploads/document/file/6784447/5877783-s10-drcm-di-001-depuracion-de-la-base-de-datos-del-rim_v02.pdf', 'guidance', 'Directive S10.DRCM.DI.001: guidelines for cleaning the RIM database'),
    ('migraciones', '2022-05-11_RS-0113-2022-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0113-2022/MIGRACIONES: Aprobar la Directiva “Lineamientos para el control migratorio a nivel nacional” con código M10.DRCM.DI.003', '2022-05-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/2973576-0113-2022-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/3089950/RESOLUCION%20DE%20SUPERINTENDENCIA-000113-2022-MIGRACIONES.pdf.pdf', 'guidance', 'Approves the directive "Guidelines for migration control nationwide"'),
    ('migraciones', '2023-01-05_Directiva-S05.DIROP.DI.003.pdf', 'Directiva S05.DIROP.DI.003 - Acreditación de personas en situación de vulnerabilidad [Dada de baja]', '2023-01-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/5829533-s05-dirop-di-003', 'https://cdn.www.gob.pe/uploads/document/file/6716398/5829533-s05-dirop-di-003-acreditacion-de-personas-en-situacion-de-vulnerabilidad.pdf', 'guidance', 'Directive S05.DIROP.DI.003: accreditation of persons in situations of vulnerability (withdrawn)'),
    ('migraciones', '2023-02-23_RS-0082-2023-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0082-2023-MIGRACIONES: Aprobar la Directiva “Lineamientos para los Operativos de Verificación y Fiscalización Migratoria_V01” con Código S08.DGTFM.DI.003', '2023-02-23', 'https://www.gob.pe/institucion/migraciones/normas-legales/3939055-0082-2023-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/4179772/RESOLUCION%20DE%20SUPERINTENDENCIA-000082-2023-MIGRACIONES.pdf', 'guidance', 'Approves directive S08.DGTFM.DI.003 v1 "Guidelines for migration verification and inspection operations"'),
    ('migraciones', '2023-05-08_RS-0109-2023-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0109-2023-MIGRACIONES: Indicar los requisitos, tipo de evaluación, así como establecer las condiciones y plazos para el procedimiento del Permiso Temporal de Permanencia a favor de las personas', '2023-05-08', 'https://www.gob.pe/institucion/migraciones/normas-legales/4204818-0109-2023-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/4531026/RESOLUCION%20DE%20SUPERINTENDENCIA-R2080-2023-MIGRACIONES.pdf', 'procedural act', 'Sets the requirements, type of assessment, conditions and time limits of the Temporary Stay Permit procedure (Supreme Decree 003-2023-IN)'),
    ('migraciones', '2023-07-26_RGG-0097-2023-GG-MIGRACIONES.pdf', 'Resolución de Gerencia N.° 0097-2023-GG-MIGRACIONES: Aprobar el Manual de Procedimientos (MAPRO) – S08 Gestión de la Verificación y Fiscalización Migratoria', '2023-07-26', 'https://www.gob.pe/institucion/migraciones/normas-legales/4477434-0097-2023-gg-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/4918989/RESOLUCION%20DE%20GERENCIA-000097-2023-GG-MIGRACIONES.pdf', 'guidance', 'Approves the procedures manual (MAPRO) S08 "Management of migration verification and inspection"'),
    ('migraciones', '2023-09-13_Directiva-M01.DRCM.DI.002.pdf', 'Directiva M01.DRCM.DI.002 - Disposiciones para la asignación de códigos, uso y resguardo de los sellos de Control Migratorio', '2023-09-13', 'https://www.gob.pe/institucion/migraciones/normas-legales/5604567-m01-drcm-di-002', 'https://cdn.www.gob.pe/uploads/document/file/6394727/5604567-m01-drcm-di-002-disposiciones-uso-y-resguardo-de-sellos-de-control-migratorio_v02.pdf', 'guidance', 'Directive M01.DRCM.DI.002: assigning codes, use and safekeeping of migration control stamps'),
    ('migraciones', '2023-09-13_Directiva-M01.DRCM.DI.003.pdf', 'Directiva M01.DRCM.DI.003 - Lineamientos para el Control Migratorio a nivel nacional', '2023-09-13', 'https://www.gob.pe/institucion/migraciones/normas-legales/5604528-m01-drcm-di-003', 'https://cdn.www.gob.pe/uploads/document/file/6394666/5604528-m01-drcm-di-003-lineamientos-para-el-control-migratorio-a-nivel-nacional_v03.pdf', 'guidance', 'Directive M01.DRCM.DI.003: guidelines for migration control nationwide'),
    ('migraciones', '2023-12-17_RS-0204-2023-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0204-2023-MIGRACIONES: Modificar el artículo 15 del “Reglamento que establece el beneficio de fraccionamiento del pago de las multas en materia migratoria impuestas por la Superintendencia Nacio', '2023-12-17', 'https://www.gob.pe/institucion/migraciones/normas-legales/4952932-0204-2023-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/5569241/4952932-resolucion-de-superintendencia-000204-2023-migraciones.pdf', 'procedural act', 'Amends article 15 of the regulation on paying migration fines in instalments'),
    ('migraciones', '2023-12-29_RGG-0204-2023-GG-MIGRACIONES.pdf', 'Resolución de Gerencia N.° 0204-2023-GG-MIGRACIONES: Aprobar el Manual de Procedimientos (MAPRO) – Macroproceso M02 - Gestión de inmigración', '2023-12-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/4991751-0204-2023-gg-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/5635749/4991751-resolucion-de-gerencia-000204-2023-gg-migraciones.pdf', 'guidance', 'Approves the procedures manual (MAPRO) for macroprocess M02 "Immigration management"'),
    ('migraciones', '2024-02-21_RGG-0038-2024-GG-MIGRACIONES.pdf', 'Resolución de Gerencia N.° 0038-2024-GG-MIGRACIONES: Aprobar el Manual de Procedimientos (MAPRO) – Macroproceso M01 - Gestión del Control Migratorio', '2024-02-21', 'https://www.gob.pe/institucion/migraciones/normas-legales/5233889-0038-2024-gg-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/5902493/5233889-resolucion-de-gerencia-000038-2024-gg-migraciones.pdf', 'guidance', 'Approves the procedures manual (MAPRO) for macroprocess M01 "Migration control management"'),
    ('migraciones', '2024-04-19_Directiva-S08.DGTFM.DI.003.pdf', 'Directiva S08.DGTFM.DI.003 - Lineamientos para los Operativos de Verificación y Fiscalización Migratoria [Versión 02] [Dada de baja]', '2024-04-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/5851117-s08-dgtfm-di-003', 'https://cdn.www.gob.pe/uploads/document/file/6746532/5851117-s08-dgtfm-di-003-lineamientos-para-los-operativos-de-verificacion-y-fiscalizacion-migratoria_v02.pdf', 'guidance', 'Directive S08.DGTFM.DI.003 v2: guidelines for migration verification and inspection operations (withdrawn)'),
    ('migraciones', '2024-04-19_RS-000095-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000095-2024-MIGRACIONES: Aprobar la Directiva “Lineamientos para los Operativos de Verificación y Fiscalización Migratoria - Versión 02” con Código S08.DGTFM.DI.003', '2024-04-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/5480038-000095-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6220526/5480038-resolucion-de-superintendencia-000095-2024-migraciones.pdf', 'guidance', 'Approves directive S08.DGTFM.DI.003 v2 on verification and inspection operations'),
    ('migraciones', '2024-05-23_RS-0110-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 0110-2024-MIGRACIONES: Dejar sin efecto, con eficacia anticipada al 1 de enero de 2024, la Directiva “Lineamientos para la fiscalización posterior de las declaraciones, información o documentació', '2024-05-23', 'https://www.gob.pe/institucion/migraciones/normas-legales/5604574-0110-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6394736/5604574-resolucion-de-superintendencia-000110-2024-migraciones.pdf', 'procedural act', 'Repeals, with effect from 1 January 2024, the directive on ex-post checks of declarations, information and documents'),
    ('migraciones', '2024-08-02_Directiva-S10.DRCM.DI.003.pdf', 'Directiva S10.DRCM.DI.003 - Lineamientos para la Gestión de Alertas Migratorias', '2024-08-02', 'https://www.gob.pe/institucion/migraciones/normas-legales/5877852-s10-drcm-di-003', 'https://cdn.www.gob.pe/uploads/document/file/6784555/5877852-s10-drcm-di-003_lineamientos-para-las-alertas-migratorias_v02.pdf', 'guidance', 'Directive S10.DRCM.DI.003: guidelines for managing migration alerts'),
    ('migraciones', '2024-08-02_RS-000142-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000142-2024-MIGRACIONES: Aprobar la Directiva “Lineamientos para la Gestión de las Alertas Migratorias” con Código S10.DRCM.DI.003', '2024-08-02', 'https://www.gob.pe/institucion/migraciones/normas-legales/5845525-000142-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6737937/5845525-resolucion-de-superintendencia-000142-2024-migraciones.pdf', 'guidance', 'Approves directive S10.DRCM.DI.003 "Guidelines for managing migration alerts"'),
    ('migraciones', '2024-08-05_RS-000145-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000145-2024-MIGRACIONES: Aprobar el “Reglamento que establece la graduación del plazo de impedimento de reingreso al país en sanciones no pecuniarias impuestas por la Superintendencia Nacional de', '2024-08-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/5854267-000145-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6750979/5854267-resolucion-de-superintendencia-000145-2024-migraciones.pdf', 'procedural act', 'Approves the regulation grading the length of re-entry bans imposed as non-pecuniary sanctions'),
    ('migraciones', '2024-11-22_Directiva-M03.DGTFM.DI.001_V02.pdf', 'Directiva M03.DGTFM.DI.001_V02 - Gestión de la Nacionalidad Peruana [Versión 02]', '2024-11-22', 'https://www.gob.pe/institucion/migraciones/normas-legales/6559142-m03-dgtfm-di-001_v02', 'https://cdn.www.gob.pe/uploads/document/file/7762751/6559142-m03-dgtfm-di-001-g-de-la-nacionalidad-peruana_v02.pdf', 'guidance', 'Directive M03.DGTFM.DI.001 v2: management of Peruvian nationality'),
    ('migraciones', '2024-11-22_RS-200-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 200-2024-MIGRACIONES: Aprobar la actualización de la Directiva “Gestión de la Nacionalidad Peruana”, con código con código M03.DGTFM.DI.001, versión 02', '2024-11-22', 'https://www.gob.pe/institucion/migraciones/normas-legales/6215998-200-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7269773/6215998-resolucion-de-superintendencia-000200-2024-migraciones.pdf', 'guidance', 'Approves the update of directive M03.DGTFM.DI.001 v2 "Management of Peruvian nationality"'),
    ('migraciones', '2024-12-19_RS-000211-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000211-2024-MIGRACIONES: Aprobar la actualización del Protocolo “Gestión de trámites vinculados al control migratorio”, con código M01.DRCM.PTL.004, versión 02', '2024-12-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/6306356-000211-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7396161/6306356-resolucion-de-superintendencia-000211-2024-migraciones.pdf', 'guidance', 'Approves protocol M01.DRCM.PTL.004 v2 "Handling of requests linked to migration control"'),
    ('migraciones', '2024-12-26_RS-216-2024-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 216-2024-MIGRACIONES: Aprobar el Protocolo de Verificación y Fiscalización Migratoria a Establecimiento de Hospedajes y Arrendamiento de Inmuebles a Extranjeros, con código S08.DGTFM.PTL.001, q', '2024-12-26', 'https://www.gob.pe/institucion/migraciones/normas-legales/6322871-216-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7420125/6322871-resolucion-de-superintendencia-000216-2024-migraciones.pdf', 'guidance', 'Approves protocol S08.DGTFM.PTL.001 on verification and inspection of lodging establishments and of property rented to foreigners'),
    ('migraciones', '2025-01-30_RS-000018-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000018-2025-MIGRACIONES: Aprobar el “Protocolo Exigencias para el control migratorio de ingreso o salida del país de nacionales y extranjeros”, con código: M01.DRCM.PTL.001, versión 02, que en an', '2025-01-30', 'https://www.gob.pe/institucion/migraciones/normas-legales/6423571-000018-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7563353/6423571-resolucion-de-superintendencia-000018-2025-migraciones.pdf', 'guidance', 'Approves protocol M01.DRCM.PTL.001 v2 "Requirements for migration control on entry or exit of nationals and foreigners"'),
    ('migraciones', '2025-03-03_Directiva-E01.DPM.DI.002.pdf', 'Directiva E01.DPM.DI.002 - Acreditación de personas extranjeras en situación de vulnerabilidad y extrema situación de vulnerabilidad', '2025-03-03', 'https://www.gob.pe/institucion/migraciones/normas-legales/6558383-e01-dpm-di-002', 'https://cdn.www.gob.pe/uploads/document/file/7762020/6558383-e01-dpm-di-002-acreditacion-de-personas-extranjeras-en-situacion-de-vulnerabilidad_v01.pdf', 'guidance', 'Directive E01.DPM.DI.002: accreditation of foreigners in situations of vulnerability and extreme vulnerability'),
    ('migraciones', '2025-03-03_RS-000030-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000030-2025-MIGRACIONES: Aprueban Directiva “Acreditación de personas extranjeras en situación de vulnerabilidad y extrema situación de vulnerabilidad” con Código E01.DPM.DI.002', '2025-03-03', 'https://www.gob.pe/institucion/migraciones/normas-legales/6532630-000030-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7722065/6532630-resolucion-de-superintendencia-000030-2025-migraciones.pdf', 'guidance', 'Approves directive E01.DPM.DI.002 on accreditation of foreigners in situations of vulnerability'),
    ('migraciones', '2025-03-13_RS-000034-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000034-2025-MIGRACIONES: Aprueban Directiva - Lineamientos para el Control Migratorio a Nivel Nacional, con Código de Documento M01.DRCM.DI.003, versión 04', '2025-03-13', 'https://www.gob.pe/institucion/migraciones/normas-legales/6563127-000034-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7768437/6563127-resolucion-de-superintendencia-000034-2025-migraciones.pdf', 'guidance', 'Approves directive M01.DRCM.DI.003 v4 "Guidelines for migration control nationwide"'),
    ('migraciones', '2025-05-05_Directiva-M01.DRCM.DI.004_V02.pdf', 'Directiva M01.DRCM.DI.004_V02 - Lineamientos para el control migratorio de personas nacionales y extranjeras en medios de transportes marítimo, fluvial y lacustre [Versión 02]', '2025-05-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/6827560-m01-drcm-di-004_v02', 'https://cdn.www.gob.pe/uploads/document/file/8155138/6827560-m01-drcm-di-004-lineamientos_control-migratorio_maritimo-fluvial-y-lacustre_v02.pdf', 'guidance', 'Directive M01.DRCM.DI.004 v2: migration control of persons on maritime, river and lake transport'),
    ('migraciones', '2025-05-05_RS-000061-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000061-2025-MIGRACIONES: Aprueban la Directiva “Lineamientos para el control migratorio de personas nacionales y extranjeras en medios de transporte marítimo, fluvial y lacustre” versión 2, con código M01.DRCM.DI.004, que', '2025-05-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/6736482-000061-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8020010/6736482-resolucion-de-superintendencia-000061-2025-migraciones.pdf', 'guidance', 'Approves directive M01.DRCM.DI.004 v2 on migration control on maritime, river and lake transport'),
    ('migraciones', '2025-05-29_Directiva-S08.DGTFM.DI.003_V03.pdf', 'Directiva S08.DGTFM.DI.003_V03 - Lineamientos para los Operativos de Verificación y Fiscalización Migratoria [Versión 03]', '2025-05-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/6827008-s08-dgtfm-di-003_v03', 'https://cdn.www.gob.pe/uploads/document/file/8154593/6827008-s08-dgtfm-di-003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoria_v03%282%29.pdf', 'guidance', 'Directive S08.DGTFM.DI.003 v3: guidelines for migration verification and inspection operations'),
    ('migraciones', '2025-05-29_RS-000074-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000074-2025-MIGRACIONES: Aprueban Directiva “Lineamientos para los Operativos de Verificación y Fiscalización Migratoria” - Versión 3, con código S08.DGTFM.DI.003', '2025-05-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/6824918-000074-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8151763/6824918-resolucion-de-superintendencia-000074-2025-migraciones.pdf', 'guidance', 'Approves directive S08.DGTFM.DI.003 v3 on verification and inspection operations'),
    ('migraciones', '2025-08-29_RS-000114-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000114-2025-MIGRACIONES: Aprueban la segunda versión del “Reglamento que establece la graduación del plazo de impedimento de reingreso al país en sanciones no pecuniarias impuestas por la Superintendencia Nacional de Migra', '2025-08-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/7099044-000114-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8576358/7099044-resolucion-de-superintendencia-000114-2025-migraciones.pdf', 'procedural act', 'Approves the second version of the regulation grading the length of re-entry bans imposed as non-pecuniary sanctions'),
    ('migraciones', '2025-09-05_RS-000115-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000115-2025-MIGRACIONES: Aprueban la Directiva “Acreditación de personas extranjeras en situación de vulnerabilidad o extrema vulnerabilidad” versión 2, con código S05.DPM.DI.002', '2025-09-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/7126946-000115-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8609974/7126946-resolucion-de-superintendencia-000115-2025-migraciones.pdf', 'guidance', 'Approves directive S05.DPM.DI.002 v2 "Accreditation of foreigners in situations of vulnerability or extreme vulnerability"'),
    ('migraciones', '2025-09-25_RS-000120-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000120-2025-MIGRACIONES: Aprueban la tercera versión del Protocolo de Verificación y Fiscalización Migratoria a Establecimientos de Hospedaje y Arrendamiento de Inmuebles a Extranjeros, con código S08.DGTFM.PTL.001', '2025-09-25', 'https://www.gob.pe/institucion/migraciones/normas-legales/7210982-000120-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8717046/7210982-resolucion-de-superintendencia-000120-2025-migraciones.pdf', 'guidance', 'Approves the third version of protocol S08.DGTFM.PTL.001 on verification of lodging establishments and property rented to foreigners'),
    ('migraciones', '2025-10-15_RS-000127-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000127-2025-MIGRACIONES: Aprueban la segunda versión del Protocolo “Atención y Referenciación de Personas Extranjeras en situación de Vulnerabilidad o Extrema situación de Vulnerabilidad”, con Código: S05.DPM.PTL.001', '2025-10-15', 'https://www.gob.pe/institucion/migraciones/normas-legales/7291870-000127-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8833565/7291870-resolucion-de-superintendencia-000127-2025-migraciones.pdf', 'guidance', 'Approves the second version of protocol S05.DPM.PTL.001 "Attention to and referral of foreigners in situations of vulnerability or extreme vulnerability"'),
    ('migraciones', '2025-11-03_RS-000136-2025-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000136-2025-MIGRACIONES: Aprueban la segunda versión de la Directiva “Lineamientos para la fiscalización posterior aleatoria”, con Código S08.DGTFM.DI.002', '2025-11-03', 'https://www.gob.pe/institucion/migraciones/normas-legales/7359302-000136-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8936076/7359302-resolucion-de-superintendencia-000136-2025-migraciones.pdf', 'guidance', 'Approves the second version of directive S08.DGTFM.DI.002 "Guidelines for random ex-post checks"'),
    ('migraciones', '2026-03-23_RS-000084-2026-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000084-2026-MIGRACIONES: Aprobación de la tercera versión de la Directiva “Lineamientos para la Fiscalización Posterior Aleatoria”', '2026-03-23', 'https://www.gob.pe/institucion/migraciones/normas-legales/7915957-000084-2026-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/9672673/7915957-resolucion-de-superintendencia-000084-2026-migraciones.pdf', 'guidance', 'Approves the third version of directive "Guidelines for random ex-post checks"'),
    ('migraciones', '2026-09-01_RS-000259-2026-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000259-2026-MIGRACIONES: Aprobación de la segunda versión de la Directiva “Lineamientos para la aplicación de sanciones a personas nacionales y extranjeras por infracción a la norma migratoria”, con código M04.DRCM.DI.001', '2026-09-01', 'https://www.gob.pe/institucion/migraciones/normas-legales/8544228-000259-2026-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/10546955/8544228-resolucion-de-superintendencia-000259-2026-migraciones.pdf', 'guidance', 'Approves the second version of directive M04.DRCM.DI.001 "Guidelines for sanctioning nationals and foreigners for breaches of migration rules"'),
    ('migraciones', '2026-11-06_RS-000314-2026-MIGRACIONES.pdf', 'Resolución de Superintendencia N.° 000314-2026-MIGRACIONES: Aprueban el Protocolo «Evaluación de conocimientos en el procedimiento de obtención de nacionalidad peruana por naturalización», con código M03.DGTFM.PTL.001', '2026-11-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/8801815-000314-2026-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/10927358/8801815-resolucion-de-superintendencia-000314-2026-migraciones.pdf', 'guidance', 'Approves protocol M03.DGTFM.PTL.001 "Knowledge test in the naturalisation procedure"'),

    ('migraciones', '2018-11-08_RS-00000329-2018-MIGRACIONES_anexo-m01-sm-di-001-lineamientos-para-las-alertas-migratorias.pdf', 'Anexo de la Resolución de Superintendencia N.° 00000329-2018-MIGRACIONES: documento aprobado (1440661-m01-sm-di-001-lineamientos-para-las-alertas-migratorias.pdf)', '2018-11-08', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440661-00000329-2018-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6086177/1440661-m01-sm-di-001-lineamientos-para-las-alertas-migratorias.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive M01.SM.DI.001 "Guidelines on migration alerts"'),
    ('migraciones', '2021-06-11_RS-0131-2021_anexo-anexo-ii.pdf', 'Anexo de la Resolución de Superintendencia N.° 0131-2021: documento aprobado (2036755-anexo-ii.pdf)', '2021-06-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036755-0131-2021', 'https://cdn.www.gob.pe/uploads/document/file/2037015/2036755-anexo-ii.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive S10.DRCM.DI.001 on cleaning the RIM database'),
    ('migraciones', '2021-06-11_RS-0131-2021_anexo-ANEXO-I.pdf', 'Anexo de la Resolución de Superintendencia N.° 0131-2021: documento aprobado ( ANEXO I.pdf)', '2021-06-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036755-0131-2021', 'https://cdn.www.gob.pe/uploads/document/file/2037019/%20ANEXO%20I.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive S10.DRCM.DI.001 on cleaning the RIM database'),
    ('migraciones', '2021-04-09_RS-080-2021-MIGRACIONES_anexo-ANEXO-I.pdf', 'Anexo de la Resolución de Superintendencia N.° 080-2021/MIGRACIONES: documento aprobado ( ANEXO I.pdf)', '2021-04-09', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036801-080-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2037073/%20ANEXO%20I.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves protocol E01.DPM.PTL.001 "Attention to and referral of migrants in situations of vulnerability"'),
    ('migraciones', '2021-02-28_RS-047-2021-MIGRACIONES_anexo-ANEXO-I.pdf', 'Anexo de la Resolución de Superintendencia N.° 047-2021/MIGRACIONES: documento aprobado ( ANEXO I.pdf)', '2021-02-28', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036821-047-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/2037097/%20ANEXO%20I.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the directive on migration control of persons on maritime transport and shore-leave permits for crew'),
    ('migraciones', '2021-08-06_RS-0169-2021-MIGRACIONES_anexo-m02-dgtfm-di-003-lineamientos-para-el-cambio-de-calidad-migratoria.pdf', 'Anexo de la Resolución de Superintendencia N.° 0169-2021-MIGRACIONES: documento aprobado (2323248-m02-dgtfm-di-003-lineamientos-para-el-cambio-de-calidad-migratoria.pdf)', '2021-08-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323248-0169-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6085315/2323248-m02-dgtfm-di-003-lineamientos-para-el-cambio-de-calidad-migratoria.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the directives on change, extension and application of migration status (M02.DGTFM.DI.003, .006, .008)'),
    ('migraciones', '2021-08-06_RS-0169-2021-MIGRACIONES_anexo-m02-dgtfm-di-006-lineamientos-para-la-prorroga-de-la-calidad-migratoria.pdf', 'Anexo de la Resolución de Superintendencia N.° 0169-2021-MIGRACIONES: documento aprobado (2323248-m02-dgtfm-di-006-lineamientos-para-la-prorroga-de-la-calidad-migratoria.pdf)', '2021-08-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323248-0169-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6085316/2323248-m02-dgtfm-di-006-lineamientos-para-la-prorroga-de-la-calidad-migratoria.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the directives on change, extension and application of migration status (M02.DGTFM.DI.003, .006, .008)'),
    ('migraciones', '2021-08-06_RS-0169-2021-MIGRACIONES_anexo-m02-dgtfm-di-008-lineamientos-para-la-solicitud-de-la-calidad-migratoria.pdf', 'Anexo de la Resolución de Superintendencia N.° 0169-2021-MIGRACIONES: documento aprobado (2323248-m02-dgtfm-di-008-lineamientos-para-la-solicitud-de-la-calidad-migratoria.pdf)', '2021-08-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323248-0169-2021-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6085318/2323248-m02-dgtfm-di-008-lineamientos-para-la-solicitud-de-la-calidad-migratoria.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the directives on change, extension and application of migration status (M02.DGTFM.DI.003, .006, .008)'),
    ('migraciones', '2023-02-23_RS-0082-2023-MIGRACIONES_anexo-s08-dgtfm-di-003-lineamientos-para-los-operativos-de-verificacion-y-fiscalizacio.pdf', 'Anexo de la Resolución de Superintendencia N.° 0082-2023-MIGRACIONES: documento aprobado (3939055-s08-dgtfm-di-003-lineamientos-para-los-operativos-de-verificacion-y-fiscalizacion-migratoria.pdf)', '2023-02-23', 'https://www.gob.pe/institucion/migraciones/normas-legales/3939055-0082-2023-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6050033/3939055-s08-dgtfm-di-003-lineamientos-para-los-operativos-de-verificacion-y-fiscalizacion-migratoria.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive S08.DGTFM.DI.003 v1 "Guidelines for migration verification and inspection operations"'),
    ('migraciones', '2023-12-29_RGG-0204-2023-GG-MIGRACIONES_anexo-mapro-m02-gestion-de-inmigracion-firmado.pdf', 'Anexo de la Resolución de Gerencia N.° 0204-2023-GG-MIGRACIONES: documento aprobado (4991751-mapro-m02-gestion-de-inmigracion-firmado.pdf)', '2023-12-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/4991751-0204-2023-gg-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/5635750/4991751-mapro-m02-gestion-de-inmigracion-firmado.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the procedures manual (MAPRO) for macroprocess M02 "Immigration management"'),
    ('migraciones', '2024-02-21_RGG-0038-2024-GG-MIGRACIONES_anexo-mapro-m01-gcontrol-migratoriov01fff-002.pdf', 'Anexo de la Resolución de Gerencia N.° 0038-2024-GG-MIGRACIONES: documento aprobado (5233889-mapro-m01-gcontrol-migratoriov01fff-002.pdf)', '2024-02-21', 'https://www.gob.pe/institucion/migraciones/normas-legales/5233889-0038-2024-gg-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/5902539/5233889-mapro-m01-gcontrol-migratoriov01fff-002.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the procedures manual (MAPRO) for macroprocess M01 "Migration control management"'),
    ('migraciones', '2024-04-19_RS-000095-2024-MIGRACIONES_anexo-s08dgtfmdi003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoriav02ff.pdf', 'Anexo de la Resolución de Superintendencia N.° 000095-2024-MIGRACIONES: documento aprobado (5480038-s08dgtfmdi003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoriav02fffff.pdf)', '2024-04-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/5480038-000095-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6220528/5480038-s08dgtfmdi003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoriav02fffff.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive S08.DGTFM.DI.003 v2 on verification and inspection operations'),
    ('migraciones', '2024-08-05_RS-000145-2024-MIGRACIONES_anexo-reglamento-que-establece-la-graduacion-del-plazo-de-impedimento-de-reingreso.pdf', 'Anexo de la Resolución de Superintendencia N.° 000145-2024-MIGRACIONES: documento aprobado (5854267-reglamento-que-establece-la-graduacion-del-plazo-de-impedimento-de-reingreso.pdf)', '2024-08-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/5854267-000145-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/6750980/5854267-reglamento-que-establece-la-graduacion-del-plazo-de-impedimento-de-reingreso.pdf', 'procedural act', 'Annex to the approving resolution - text of the approved document. Approves the regulation grading the length of re-entry bans imposed as non-pecuniary sanctions'),
    ('migraciones', '2024-11-22_RS-200-2024-MIGRACIONES_anexo-directiva-gestion-de-la-nacionalidad-peruana.pdf', 'Anexo de la Resolución de Superintendencia N.° 200-2024-MIGRACIONES: documento aprobado (6215998-directiva-gestion-de-la-nacionalidad-peruana.pdf)', '2024-11-22', 'https://www.gob.pe/institucion/migraciones/normas-legales/6215998-200-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7269774/6215998-directiva-gestion-de-la-nacionalidad-peruana.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the update of directive M03.DGTFM.DI.001 v2 "Management of Peruvian nationality"'),
    ('migraciones', '2024-12-19_RS-000211-2024-MIGRACIONES_anexo-m01drcmptl004-gestin-de-trmites-vinculados-al-cmen-estudio-v02fff.pdf', 'Anexo de la Resolución de Superintendencia N.° 000211-2024-MIGRACIONES: documento aprobado (6306356-m01drcmptl004-gestin-de-trmites-vinculados-al-cmen-estudio-v02fff.pdf)', '2024-12-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/6306356-000211-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7466429/6306356-m01drcmptl004-gestin-de-trmites-vinculados-al-cmen-estudio-v02fff.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves protocol M01.DRCM.PTL.004 v2 "Handling of requests linked to migration control"'),
    ('migraciones', '2024-12-26_RS-216-2024-MIGRACIONES_anexo-s08dgtfmptl001-verificacin-y-fiscalizacin-migratoria.pdf', 'Anexo de la Resolución de Superintendencia N.° 216-2024-MIGRACIONES: documento aprobado (6322871-s08dgtfmptl001-verificacin-y-fiscalizacin-migratoria.pdf)', '2024-12-26', 'https://www.gob.pe/institucion/migraciones/normas-legales/6322871-216-2024-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7446970/6322871-s08dgtfmptl001-verificacin-y-fiscalizacin-migratoria.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves protocol S08.DGTFM.PTL.001 on verification and inspection of lodging establishments and of property rented to foreigners'),
    ('migraciones', '2025-01-30_RS-000018-2025-MIGRACIONES_anexo-m01drcmptl001-exigencias-para-el-control-migratorio-de-ingreso-o-salida-nacional.pdf', 'Anexo de la Resolución de Superintendencia N.° 000018-2025-MIGRACIONES: documento aprobado (6423571-m01drcmptl001-exigencias-para-el-control-migratorio-de-ingreso-o-salida-nacionales-y-extranjeros.pdf)', '2025-01-30', 'https://www.gob.pe/institucion/migraciones/normas-legales/6423571-000018-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7563355/6423571-m01drcmptl001-exigencias-para-el-control-migratorio-de-ingreso-o-salida-nacionales-y-extranjeros.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves protocol M01.DRCM.PTL.001 v2 "Requirements for migration control on entry or exit of nationals and foreigners"'),
    ('migraciones', '2025-03-03_RS-000030-2025-MIGRACIONES_anexo-acreditacion-de-personas-en-situacion-de-vulnerabilidad-o-extrema-situacion-de-v.pdf', 'Anexo de la Resolución de Superintendencia N.° 000030-2025-MIGRACIONES: documento aprobado (6532630-acreditacion-de-personas-en-situacion-de-vulnerabilidad-o-extrema-situacion-de-vulnerabilidad.pdf)', '2025-03-03', 'https://www.gob.pe/institucion/migraciones/normas-legales/6532630-000030-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7722066/6532630-acreditacion-de-personas-en-situacion-de-vulnerabilidad-o-extrema-situacion-de-vulnerabilidad.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive E01.DPM.DI.002 on accreditation of foreigners in situations of vulnerability'),
    ('migraciones', '2025-03-13_RS-000034-2025-MIGRACIONES_anexo-m01drcmdi003-lineamientos-para-el-control-migratorio-a-nivel-nacional.pdf', 'Anexo de la Resolución de Superintendencia N.° 000034-2025-MIGRACIONES: documento aprobado (6563127-m01drcmdi003-lineamientos-para-el-control-migratorio-a-nivel-nacional.pdf)', '2025-03-13', 'https://www.gob.pe/institucion/migraciones/normas-legales/6563127-000034-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/7768438/6563127-m01drcmdi003-lineamientos-para-el-control-migratorio-a-nivel-nacional.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive M01.DRCM.DI.003 v4 "Guidelines for migration control nationwide"'),
    ('migraciones', '2025-05-05_RS-000061-2025-MIGRACIONES_anexo-m01drcmdi004-control-migratorio-de-personas-nac-y-extranj-en-medios-de-transpv02.pdf', 'Anexo de la Resolución de Superintendencia N.° 000061-2025-MIGRACIONES: documento aprobado (6736482-m01drcmdi004-control-migratorio-de-personas-nac-y-extranj-en-medios-de-transpv02f.pdf)', '2025-05-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/6736482-000061-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8020011/6736482-m01drcmdi004-control-migratorio-de-personas-nac-y-extranj-en-medios-de-transpv02f.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive M01.DRCM.DI.004 v2 on migration control on maritime, river and lake transport'),
    ('migraciones', '2025-05-29_RS-000074-2025-MIGRACIONES_anexo-s08dgtfmdi003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoriav03f..pdf', 'Anexo de la Resolución de Superintendencia N.° 000074-2025-MIGRACIONES: documento aprobado (6824918-s08dgtfmdi003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoriav03f.pdf)', '2025-05-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/6824918-000074-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8151764/6824918-s08dgtfmdi003-lineamientos-para-los-operativos-de-verif-y-fiscal-migratoriav03f.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive S08.DGTFM.DI.003 v3 on verification and inspection operations'),
    ('migraciones', '2025-08-29_RS-000114-2025-MIGRACIONES_anexo-reglamento-de-graduacin-de-impedimento-de-reingreso-al-pas-18jun2025f.pdf', 'Anexo de la Resolución de Superintendencia N.° 000114-2025-MIGRACIONES: documento aprobado (7099044-reglamento-de-graduacin-de-impedimento-de-reingreso-al-pas-18jun2025f.pdf)', '2025-08-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/7099044-000114-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8576359/7099044-reglamento-de-graduacin-de-impedimento-de-reingreso-al-pas-18jun2025f.pdf', 'procedural act', 'Annex to the approving resolution - text of the approved document. Approves the second version of the regulation grading the length of re-entry bans imposed as non-pecuniary sanctions'),
    ('migraciones', '2025-09-05_RS-000115-2025-MIGRACIONES_anexo-s05dpmdi002-acreditacion-de-personas-en-situacion-de-vulnerabilidad-o-extrema-si.pdf', 'Anexo de la Resolución de Superintendencia N.° 000115-2025-MIGRACIONES: documento aprobado (7126946-s05dpmdi002-acreditacion-de-personas-en-situacion-de-vulnerabilidad-o-extrema-situacin-de.pdf)', '2025-09-05', 'https://www.gob.pe/institucion/migraciones/normas-legales/7126946-000115-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8609975/7126946-s05dpmdi002-acreditacion-de-personas-en-situacion-de-vulnerabilidad-o-extrema-situacin-de.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves directive S05.DPM.DI.002 v2 "Accreditation of foreigners in situations of vulnerability or extreme vulnerability"'),
    ('migraciones', '2025-09-25_RS-000120-2025-MIGRACIONES_anexo-protocolo-de-verificacion-y-fiscalizacion-migratoria-a-establecimientos-de-hospe.pdf', 'Anexo de la Resolución de Superintendencia N.° 000120-2025-MIGRACIONES: documento aprobado (7210982-protocolo-de-verificacion-y-fiscalizacion-migratoria-a-establecimientos-de-hospedaje-y-arrendamiento-de-inmuebles-a-extranjeros.pdf)', '2025-09-25', 'https://www.gob.pe/institucion/migraciones/normas-legales/7210982-000120-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8717047/7210982-protocolo-de-verificacion-y-fiscalizacion-migratoria-a-establecimientos-de-hospedaje-y-arrendamiento-de-inmuebles-a-extranjeros.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the third version of protocol S08.DGTFM.PTL.001 on verification of lodging establishments and property rented to foreigners'),
    ('migraciones', '2025-10-15_RS-000127-2025-MIGRACIONES_anexo-s05dpmptl001atencion-y-referenciacion-de-personas-vulnerabv02f.pdf', 'Anexo de la Resolución de Superintendencia N.° 000127-2025-MIGRACIONES: documento aprobado (7291870-s05dpmptl001atencion-y-referenciacion-de-personas-vulnerabv02f.pdf)', '2025-10-15', 'https://www.gob.pe/institucion/migraciones/normas-legales/7291870-000127-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8833566/7291870-s05dpmptl001atencion-y-referenciacion-de-personas-vulnerabv02f.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the second version of protocol S05.DPM.PTL.001 "Attention to and referral of foreigners in situations of vulnerability or extreme vulnerability"'),
    ('migraciones', '2025-11-03_RS-000136-2025-MIGRACIONES_anexo-s08dgtfmdi002-lineamientos-para-la-fiscalizacin-posterior-aleatoriav02f.pdf', 'Anexo de la Resolución de Superintendencia N.° 000136-2025-MIGRACIONES: documento aprobado (7359302-s08dgtfmdi002-lineamientos-para-la-fiscalizacin-posterior-aleatoriav02f.pdf)', '2025-11-03', 'https://www.gob.pe/institucion/migraciones/normas-legales/7359302-000136-2025-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/8936077/7359302-s08dgtfmdi002-lineamientos-para-la-fiscalizacin-posterior-aleatoriav02f.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the second version of directive S08.DGTFM.DI.002 "Guidelines for random ex-post checks"'),
    ('migraciones', '2026-03-23_RS-000084-2026-MIGRACIONES_anexo-dgtfmdi001-lineamientos-para-la-fiscalizacin-posterior-aleatoriav03ff.pdf', 'Anexo de la Resolución de Superintendencia N.° 000084-2026-MIGRACIONES: documento aprobado (7915957-dgtfmdi001-lineamientos-para-la-fiscalizacin-posterior-aleatoriav03ff.pdf)', '2026-03-23', 'https://www.gob.pe/institucion/migraciones/normas-legales/7915957-000084-2026-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/9672674/7915957-dgtfmdi001-lineamientos-para-la-fiscalizacin-posterior-aleatoriav03ff.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the third version of directive "Guidelines for random ex-post checks"'),
    ('migraciones', '2026-09-01_RS-000259-2026-MIGRACIONES_anexo-directiva-sobre-lineamientos-para-sanciones.pdf', 'Anexo de la Resolución de Superintendencia N.° 000259-2026-MIGRACIONES: documento aprobado (8544228-directiva-sobre-lineamientos-para-sanciones.pdf)', '2026-09-01', 'https://www.gob.pe/institucion/migraciones/normas-legales/8544228-000259-2026-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/10546956/8544228-directiva-sobre-lineamientos-para-sanciones.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves the second version of directive M04.DRCM.DI.001 "Guidelines for sanctioning nationals and foreigners for breaches of migration rules"'),
    ('migraciones', '2026-11-06_RS-000314-2026-MIGRACIONES_anexo-protocolo-evaluacion-de-conocimiento.pdf', 'Anexo de la Resolución de Superintendencia N.° 000314-2026-MIGRACIONES: documento aprobado (8801815-protocolo-evaluacion-de-conocimiento.pdf)', '2026-11-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/8801815-000314-2026-migraciones', 'https://cdn.www.gob.pe/uploads/document/file/10927359/8801815-protocolo-evaluacion-de-conocimiento.pdf', 'guidance', 'Annex to the approving resolution - text of the approved document. Approves protocol M03.DGTFM.PTL.001 "Knowledge test in the naturalisation procedure"'),
    ('mapro', '2024-02-21_MAPRO-M01-Gestion-del-Control-Migratorio-v01.pdf',
     'Manual de Procedimientos (MAPRO) - Macroproceso M01 Gestión del Control Migratorio, versión 01 (aprobado por '
     'Resolución de Gerencia N.° 0038-2024-GG-MIGRACIONES; dejado sin efecto por RGG N.° 000193-2025-GG-MIGRACIONES)',
     '2024-02-21', MAPRO_PAGE, CDN + '6011939/2766937-mapro-m01-g-control-migratorio_v01yres.pdf', 'guidance',
     'Procedures manual (MAPRO) for macroprocess M01, migration control management, version 1 (approved Feb 2024, '
     'revoked Dec 2025)'),
    ('mapro', '2023-12-29_MAPRO-M02-Gestion-de-Inmigracion.pdf',
     'Manual de Procedimientos (MAPRO) - Macroproceso M02 Gestión de Inmigración (aprobado por Resolución de Gerencia '
     'N.° 0204-2023-GG-MIGRACIONES)',
     '2023-12-29', MAPRO_PAGE, CDN + '5699334/2766937-mapro-m02-gestion-de-inmigracion.pdf', 'guidance',
     'Procedures manual (MAPRO) for macroprocess M02, immigration management (residence and status procedures)'),
    ('mapro', '2023-07-26_MAPRO-S08-Gestion-de-la-Verificacion-y-Fiscalizacion-Migratoria.pdf',
     'Manual de Procedimientos (MAPRO) - S08 Gestión de la Verificación y Fiscalización Migratoria (aprobado por '
     'Resolución de Gerencia N.° 0097-2023-GG-MIGRACIONES; dejado sin efecto por RGG N.° 000056-2025-GG-MIGRACIONES)',
     '2023-07-26', MAPRO_PAGE,
     CDN + '4953078/MAPRO%20S08%20-%20Gesti%C3%B3n%20de%20la%20Verificaci%C3%B3n%20y%20Fiscalizaci%C3%B3n%20Migratoria.pdf',
     'guidance', 'Procedures manual (MAPRO) S08, migration verification and inspection (approved July 2023, revoked '
     'March 2025)'),
    ('mapro', '2010_DIGEMIN_MAPRO-DIGEMIN.pdf', 'Manual de Procedimientos (MAPRO) de la Dirección General de Migraciones y Naturalización (DIGEMIN)', '2010', MAPRO_PAGE, CDN + '2851067/MAPRO%20-%20%20DIGEMIN.pdf', 'guidance', 'Procedures manual (MAPRO) of the former General Directorate of Migration and Naturalisation (DIGEMIN)'),
    ('mapro', '2010_DIGEMIN_MAPRO-Anexo-III-DINM.pdf', 'MAPRO DIGEMIN - Anexo III: procedimientos de la Dirección de Inmigración (DINM)', '2010', MAPRO_PAGE, CDN + '2851060/MAPRO%20-%20Anexo%20III-DINM%20%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual, annex III: procedures of the Immigration Directorate'),
    ('mapro', '2010_DIGEMIN_MAPRO-Anexo-III-DCM.pdf', 'MAPRO DIGEMIN - Anexo III: procedimientos de la Dirección de Control Migratorio (DCM)', '2010', MAPRO_PAGE, CDN + '2851068/MAPRO%20-%20ANEXO%20III-DCM%20%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual, annex III: procedures of the Migration Control Directorate'),
    ('mapro', '2010_DIGEMIN_MAPRO-Anexo-III-Naturalizacion.pdf', 'MAPRO DIGEMIN - Anexo III: procedimientos de naturalización', '2010', MAPRO_PAGE, CDN + '2851059/MAPRO%20-%20Anexo%20III-NATURALIZACI%C3%93N%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual, annex III: naturalisation procedures'),
    ('mapro', '2010_DIGEMIN_MAPRO-Anexo-III-Servicios.pdf', 'MAPRO DIGEMIN - Anexo III: servicios', '2010', MAPRO_PAGE, CDN + '2851057/MAPRO%20-%20Anexo%20III-SERVICIOS%20%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual, annex III: services'),
    ('mapro', '2010_DIGEMIN_MAPRO-Flujograma-Inmigracion.pdf', 'MAPRO DIGEMIN - flujogramas de inmigración', '2010', MAPRO_PAGE, CDN + '2851065/MAPRO%20-%20FLUJOGRAMA-INMIGRACI%C3%93N%20%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual: immigration flow charts'),
    ('mapro', '2010_DIGEMIN_MAPRO-Flujograma-DCM.pdf', 'MAPRO DIGEMIN - flujogramas de control migratorio (DCM)', '2010', MAPRO_PAGE, CDN + '2851061/MAPRO%20-%20FLUJOGRAMA-DCM%20%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual: migration control flow charts'),
    ('mapro', '2010_DIGEMIN_MAPRO-Flujograma-Naturalizacion.pdf', 'MAPRO DIGEMIN - flujogramas de naturalización', '2010', MAPRO_PAGE, CDN + '2851066/MAPRO%20-%20FLUJOGRAMA-NATURALIZACI%C3%93N%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual: naturalisation flow charts'),
    ('mapro', '2010_DIGEMIN_MAPRO-Flujograma-Naturalizacion-Parent.pdf', 'MAPRO DIGEMIN - flujogramas de naturalización (parentesco)', '2010', MAPRO_PAGE, CDN + '2851064/MAPRO%20-%20FLUJOGRAMA-NATURALIZACI%C3%93N-PARENT%20%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual: flow charts for nationality by family relationship'),
    ('mapro', '2010_DIGEMIN_MAPRO-Flujograma-Servicios.pdf', 'MAPRO DIGEMIN - flujogramas de servicios', '2010', MAPRO_PAGE, CDN + '2851063/MAPRO%20-%20FLUJOGRAMA-SERVICIOS%28OGP%29.pdf', 'guidance', 'DIGEMIN procedures manual: services flow charts'),
    ('rree', '2021-07-06_RM-0207-2021-RE_Lineamientos-Calidad-Migratoria-Humanitaria.pdf',
     'Resolución Ministerial N.° 0207-2021/RE: Lineamientos para el otorgamiento y prórroga de la Calidad Migratoria '
     'Humanitaria', '2021-07-06', 'https://www.gob.pe/institucion/rree/normas-legales/2007440-0207-2021-re',
     CDN + '1997186/RM%20N%C2%B0%200207-2021-RE%20%20Lineamientos%20para%20el%20otorgamiento%20y%20pr%C3%B3rroga%20de%20'
     'Calidad%20Migratoria%20Humanitaria.pdf', 'guidance',
     'Ministerial Resolution 0207-2021/RE: guidelines for granting and extending the humanitarian migration status'),
    ('rree', '2024-12-27_RSG-1663-2024-RE_MAPRO-Oficinas-Consulares.pdf',
     'Resolución de Secretaría General N.° 1663-2024-RE: aprueba el Manual de Procedimientos de las Oficinas '
     'Consulares - MAPRO CONPER', '2024-12-27', 'https://www.gob.pe/institucion/rree/normas-legales/6331283-1663-2024-re',
     CDN + '7431023/6331283-resolucion-de-secretaria-general-n-1663-2024-re.PDF', 'guidance',
     'Secretary-General Resolution 1663-2024-RE approving the procedures manual of consular offices (MAPRO CONPER, '
     'includes visa processing abroad)'),
    ('rree', '2026-07-14_RM-424-2026-RE_Actualizacion-Solicitudes-de-Refugio-2026.pdf',
     'Resolución Ministerial N.° 424-2026-RE: habilita la plataforma web "Actualización de Solicitudes de Refugio 2026"',
     '2026-07-14', 'https://www.gob.pe/institucion/rree/normas-legales/8381751-424-2026-re',
     CDN + '10316959/8381751-resolucion-ministerial-n-424-2026-re.pdf', 'procedural act',
     'Ministerial Resolution 424-2026-RE enabling the web platform for updating pending refugee claims (2026)'),
]

# Known to exist, not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ('Documento aprobado por la Resolución de Superintendencia N.° 00000357-2017-MIGRACIONES (Aprobar la Directiva “Atención a Víctimas de Trata de Personas y Tráfico Ilícito de Migrantes”)', '2017-12-28', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440510-00000357-2017-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 00000361-2017-MIGRACIONES (Aprobar la Directiva “Lineamientos para el Registro, Actualización y Levantamiento de Alertas Migratorias”)', '2017-12-29', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440509-00000361-2017-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 00000043-2018-MIGRACIONES (Aprobar la Directiva “Lineamientos para la obtención de la Calidad Migratoria Especial Residente para personas de nacionalidad venezolana con Permiso )', '2018-01-30', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440942-00000043-2018-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 00000261-2018-MIGRACIONES (Aprobar el “Protocolo de Verificación y Fiscalización Migratoria en los puestos de Verificación Migratoria” y el “Protocolo de Verificación y Fiscaliz)', '2018-08-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440728-00000261-2018-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 00000344-2018-MIGRACIONES (Aprobar el “Protocolo de Verificación y Fiscalización Migratoria en los Terminales Terrestres” y el “Protocolo de Verificación y Fiscalización Migrato)', '2018-11-19', 'https://www.gob.pe/institucion/migraciones/normas-legales/1440650-00000344-2018-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 00000317-2019-MIGRACIONES (Aprobar el “Protocolo de Verificación y Fiscalización Migratoria en los Aeropuertos Internacionales del Perú” actualizado)', '2019-10-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/1454816-00000317-2019-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 039-2021/MIGRACIONES (Aprobar la Directiva: Lineamientos para el Control Migratorio a nivel nacional de la Superintendencia Nacional de Migraciones, con código M01.DRCM.DI)', '2021-03-08', 'https://www.gob.pe/institucion/migraciones/normas-legales/2036828-039-2021-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 0149-2021-MIGRACIONES (Aprobar la Directiva Disposiciones para la asignación de códigos e iniciales, el uso y resguardo de los sellos de Control Migratorio de la Superintend)', '2021-07-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323233-0149-2021-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 0150-2021-MIGRACIONES (Aprobar la Directiva “Acreditación de Personas en situación de Vulnerabilidad” con código S05.DIROP-DI.003)', '2021-07-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323234-0150-2021-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 0151-2021-MIGRACIONES (Aprobar el “Protocolo Regularización Migratoria” con código M02.DGTFM.PTL.001)', '2021-07-16', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323235-0151-2021-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Superintendencia N.° 0166-2021-MIGRACIONES (Aprobar el “Protocolo Exigencias para el control migratorio de ingreso o salida del país de nacionales y extranjeros”, con código M01.DRCM.PTL.001)', '2021-08-06', 'https://www.gob.pe/institucion/migraciones/normas-legales/2323245-0166-2021-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Documento aprobado por la Resolución de Gerencia General N.° 0185-2021-GG/MIGRACIONES (Aprobar el Protocolo “Atención de Certificado de Movimiento Migratorio, Certificado de Inscripción en el Registro Central de Extranjería y otros servi)', '2021-08-11', 'https://www.gob.pe/institucion/migraciones/normas-legales/2594791-0185-2021-gg-migraciones', 'only the approving resolution is published (2-3 pages, saved); the approved directive/protocol is not attached on gob.pe and was not found as a separate entry'),
    ('Resolución de Superintendencia N.° 0100-2020-MIGRACIONES: Suspender las sanciones administrativas por el plazo de quince (15) días calendario, para aquellas personas extranjeras con infracción migratoria por exceso de permanencia al momento', '2020-05-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441365-0100-2020-migraciones', 'the page on gob.pe carries no file (checked 2026-11-15)'),
    ('Resolución de Superintendencia N.° 0139-2020-MIGRACIONES: Aprobar la Directiva M02.SM.DI.001 – “Lineamientos para la Verificación y Fiscalización de Información y Documentación proporcionada en los Procedimientos y Servicios Migratorios” – S', '2020-07-10', 'https://www.gob.pe/institucion/migraciones/normas-legales/1441328-0139-2020-migraciones', 'the page on gob.pe carries no file (checked 2026-11-15)'),
]

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


def fetch(rel, title, date, url, kind, title_en, body, page=""):
    """Download one PDF to pe/<rel> unless it is there already; add its index row if the file is good."""
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
    rows.append((rel, title, date, url, kind, title_en, body, page))



def run_source(name):
    print(f"{name}:")
    for src, rel, title, date, page, url, kind, title_en in ITEMS:
        if src == name:
            body = RREE if src == "rree" else MIG
            fetch(f"{src}/{rel}", title, date, url, kind, title_en, body, page)


SOURCES = ("migraciones", "mapro", "rree")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


HEADER = "file\ttitle\tdate\tsource_url\tkind\ttitle_en\tissuing_body\tpage_url"


def main():
    wanted = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    OUT.mkdir(exist_ok=True)
    old = {}
    idx = OUT / "index.tsv"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 8 and (OUT / c[0]).exists() and c[0].split("/")[0] not in wanted:
                old[c[0]] = tuple(c[:8])
    for name in wanted:
        run_source(name)
    final = dict(old)
    for r in rows:
        final[r[0]] = tuple(clean(x) for x in r)
    with open(idx, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n")
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

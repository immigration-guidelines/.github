#!/usr/bin/env python3
"""Costa Rica: what the migration authority publishes for the officials who decide cases.

    python3 download_cr.py              # all sources
    python3 download_cr.py scij         # one source (scij, dgme)
    python3 download_cr.py --give-up=web.archive.org   # rebuild without asking a host that refused

Sources (see cr/NOTES.txt for what was checked and what is missing):

  scij   sinalevi.go.cr (Sistema Costarricense de Información Jurídica of the Procuraduría
         General de la República; www.pgrweb.go.cr/scij redirects there). All norms whose
         issuing body is the Dirección General de Migración y Extranjería (ente emisor 72) are
         listed with one search; a fixed selection is downloaded as the full-text HTML
         fragment the site serves (POST /ResultadosNormativa/_CargarTextoCompleto, the
         same call its "Texto completo" button makes; the "html" member of the JSON answer
         is saved byte for byte, UTF-8, no page wrapper). Circulars and directrices to
         officials are "guidance"; resolutions and DGME regulations "procedural act".
         Left out: fees, uniforms, budget/trust-fund rules, delegations of signature,
         national passports, office opening hours (see SKIP_SCIJ).
  dgme   www.migracion.go.cr (DGME) - the site answers every request, robots.txt included,
         with a Cloudflare JavaScript challenge, so it is not contacted. Its PDFs (circulars
         and protocols for the Policía Profesional de Migración, children's protocols, visa
         directrices before 2010, labour-ministry occupation recommendations) are taken from
         the Internet Archive (web.archive.org/web/<timestamp>id_/<url>, the unmodified
         archived bytes), fixed list in WAYBACK.

Rules: robots.txt is read for each host before anything else and obeyed (rules for "*"
and rules that name AI agents; wildcards handled here, Crawl-delay honoured); one
request at a time, at least 2 s apart (4 s and a shared lock file for web.archive.org);
a host that answers 403 or 429, serves a challenge page, or fails three times in a row is
not asked again in that run. Files that exist are skipped; cr/index.tsv and
cr/not-obtained.tsv are rebuilt on every run. Standard library only.
"""
import fcntl
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cr"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
IA_DELAY = 4.0
LOCKDIR = Path("/tmp/claude-1000/-home-brinly-vab/90332c16-33fe-47cb-91e5-cd2687d17632/scratchpad/locks")
MAX_BYTES = 500_000_000
MAX_FILES = 1500
MAX_ONE = 95_000_000
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "oai-searchbot", "perplexitybot", "bytespider", "ai2bot")
DGME_BODY = "Dirección General de Migración y Extranjería (DGME)"

SCIJ = "https://sinalevi.go.cr"
SCIJ_LIST = (SCIJ + "/ResultadosNormativa/Resultados?TipoBusqueda=2&Pagina=1&EnteEmisor=72&VetoOSello=0"
             "&NormasHistoricas=false&CantidadResultados=-1&radioFechas=1&radioFechasGaceta=1&radioFechasBoletin=1")
SCIJ_TEXT = SCIJ + "/ResultadosNormativa/_CargarTextoCompleto"
SCIJ_PAGE = SCIJ + "/ResultadosNormativa/Informacion?param1={ficha}&param2={version}&param3=1"
# IdFichaNorma left out on purpose -> reason
SKIP_SCIJ = {
    103567: "fee", 96456: "fee", 60349: "fee", 58887: "fee", 56471: "fee",
    97162: "uniforms", 94001: "office closure",
    96027: "subsidy rules", 95226: "trust fund", 95227: "trust fund", 95228: "trust fund", 95229: "trust fund",
    95230: "trust fund", 89177: "budget", 85380: "confidential expenses", 85662: "petty cash",
    88178: "board rules", 92719: "office visitor rules", 91292: "office visitor rules",
    98462: "organisation of a department", 91371: "delegation of signature", 87181: "delegation of signature",
    58542: "delegation of signature", 90730: "delegation of signature", 89999: "delegation of signature",
    74457: "national passports", 71740: "office hours", 100835: "national passports", 99604: "national passports",
    96013: "national passports", 47312: "exit permits for (national) minors",
}
TYPE_EN = {"Resolución": "Resolution", "Circular": "Circular", "Directriz": "Directive", "Reglamento": "Regulation",
           "Acuerdo": "Agreement"}

WAYBACK = [
    # (timestamp, archived URL, date, kind, title, title_en, file name stem)
    ("20081203055946", "http://www.migracion.go.cr:80/visas/Directrices_ingreso/Directrices%20visas%20Feb%202008.pdf",
     "2007-12-21", "guidance", 'Circular DG-2949-2007: Directrices Generales sobre Visas de Ingreso para no Residentes (rige 15 de enero de 2008)',
     'Circular DG-2949-2007: general guidelines on entry visas for non-residents, addressed to migration agents abroad and all DGME units (in force 15 January 2008)',
     "Circular-DG-2949-2007-Directrices-visas"),
    ("20090730142046", "http://migracion.go.cr:80/visas/Directrices_ingreso/DirectricesvisasFeb2009.pdf",
     "2009-01-30", "guidance", 'Circular DG-0339-2009: Directrices Generales sobre Visas de Ingreso para no Residentes (rige 16 de febrero de 2009)',
     'Circular DG-0339-2009: general guidelines on entry visas for non-residents (in force 16 February 2009)',
     "Circular-DG-0339-2009-Directrices-visas"),
    ("20090521041322", "http://www.migracion.go.cr:80/visas/Directrices_ingreso/Directrices%20visas%20Mayo%202009.pdf",
     "2009-04-15", "guidance", 'Circular DG-1198-2009: Directrices Generales sobre Visas de Ingreso para no Residentes (rige 4 de mayo de 2009)',
     'Circular DG-1198-2009: general guidelines on entry visas for non-residents (in force 4 May 2009)',
     "Circular-DG-1198-2009-Directrices-visas"),
    ("20100215202753", "http://www.migracion.go.cr:80/visas/Directrices_ingreso/Directrices%20visas-Noviembre2009.pdf",
     "2009-11-05", "guidance", 'Circular DG-3309-2009: Directrices Generales sobre Visas de Ingreso para no Residentes (rige 1 de diciembre de 2009)',
     'Circular DG-3309-2009: general guidelines on entry visas for non-residents (in force 1 December 2009)',
     "Circular-DG-3309-2009-Directrices-visas"),
    ("20090824134818", "http://migracion.go.cr:80/Leyes%20Migratorias/Leyes%20Migratorio/Circular%20procedimientos%20visas.pdf",
     "2008-08-28", "guidance", 'Circular DGSV-675-2008: Requisitos y procedimientos en el otorgamiento de visas realizadas dentro del Subproceso de Visas',
     'Circular DGSV-675-2008: requirements and procedure for granting visas in the DGME visa unit',
     "Circular-DGSV-675-2008-procedimientos-visas"),
    ("20200927221050", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/-4.%20PROTOCOLO%20DE%20ATENCI%C3%93N%20%20EN%20PUESTOS%20FRONTERIZOS%20MIGRATORIOS%20AEREOS%2C%20MARITIMOS%20Y%20TERRESTRES.pdf",
     "2020-03", "guidance", 'Protocolo de atención de la emergencia nacional por COVID-19 en puestos fronterizos migratorios aéreos, marítimos y terrestres (Ministerio de Salud / DGME)',
     'Protocol for handling the COVID-19 national emergency at air, sea and land border posts (Ministry of Health / DGME)',
     "Protocolo-COVID-19-puestos-fronterizos-migratorios"),
    ("20200922102706", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/1.%20PROTOCOLO%20PPME-COVID%2019.pdf.pdf",
     "2020-03-16", "guidance", 'Protocolo operativo de funcionamiento de las oficinas de la Policía Profesional de Migración y Extranjería ante la emergencia sanitaria por COVID-19',
     'Operating protocol for the offices of the Professional Migration Police during the COVID-19 health emergency',
     "Protocolo-operativo-PPME-COVID-19"),
    ("20200922115358", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/2.%20DPPME-004-03-2020-AJ.pdf",
     "2020-03", "guidance", 'Circular DPPME-004-03-2020-AJ (Dirección de la Policía Profesional de Migración)',
     'Circular DPPME-004-03-2020-AJ of the Professional Migration Police directorate (COVID-19 measures)',
     "Circular-DPPME-004-03-2020-AJ"),
    ("20200927220650", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/5.%20DPPME-005-03-2020-AJ.pdf",
     "2020-03-18", "guidance", 'Circular DPPME-005-03-2020-AJ: Medidas de contingencia por la emergencia nacional del COVID-19 (a oficiales de la PPME)',
     'Circular DPPME-005-03-2020-AJ to Professional Migration Police officers: contingency measures for the COVID-19 emergency',
     "Circular-DPPME-005-03-2020-AJ-medidas-contingencia"),
    ("20200927234406", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/6.DGME-0005-03-2020-AJ.pdf",
     "2020-03-17", "guidance", 'Circular DG-0005-03-2020-AJ: Directriz de ingreso de personas extranjeras por la emergencia de COVID-19 (a oficiales de la PPME)',
     'Circular DG-0005-03-2020-AJ to Professional Migration Police officers: directive on admitting foreign nationals during the COVID-19 emergency',
     "Circular-DG-0005-03-2020-AJ-directriz-ingreso"),
    ("20200927222303", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/9.%20Directriz%20de%20suspensi%C3%B3n%20de%20visitas%20en%20el%20CARC_DPPME-006-03-2020-AJ.pdf",
     "2020-03-20", "guidance", 'Circular DPPME-006-03-2020-AJ: Suspensión de visitas en el CARC (Centro de Aprehensión Temporal para Extranjeros en Condición Irregular)',
     'Circular DPPME-006-03-2020-AJ: suspension of visits at the CARC immigration detention centre',
     "Circular-DPPME-006-03-2020-AJ-visitas-CARC"),
    ("20200927223806", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/AJ-0706-04-2020%2C%20Protocolo%20procesos%20Migratorios%20Decretos%20COVID-19%20FINAAJL.pdf",
     "2020-04-14", "guidance", 'Circular AJ-0706-04-2020-ABM-JM: Procesos migratorios aplicables ante la pandemia COVID-19, con fundamento en los decretos 42238-MGP-S y 42256-MGP-S',
     'Circular AJ-0706-04-2020-ABM-JM to migration police, operations, refuge and legal units: migration procedures applicable during COVID-19 under decrees 42238-MGP-S and 42256-MGP-S',
     "Circular-AJ-0706-04-2020-procesos-migratorios-COVID-19"),
    ("20201026071820", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Circular%20AJ-1671-09-2020-ABM.pdf",
     "2020-09-22", "guidance", 'Circular AJ-1671-09-2020-ABM: Medidas administrativas temporales de atención al usuario externo',
     'Circular AJ-1671-09-2020-ABM: temporary administrative measures for service to the public (validity of documents extended)',
     "Circular-AJ-1671-09-2020-ABM-medidas-administrativas"),
    ("20200927234817", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Circular%20Prorroga%20DIMEX%20y%20Permisos%20Solicitantes%20Refugio.pdf",
     "2020-07-14", "guidance", 'Circular AJ-1331-07-2020-JM: Prórroga de Documento de Identidad Migratorio para Extranjeros (DIMEX) y permisos de solicitantes de refugio',
     "Circular AJ-1331-07-2020-JM: extension of foreigners' identity documents (DIMEX) and asylum-seeker permits",
     "Circular-AJ-1331-07-2020-JM-prorroga-DIMEX"),
    ("20200927234146", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Circular%20Transportistas%20que%20Ingresen%20a%20Panam%C3%A1%20con%20Permiso%20de%20Ingreso%20M%C3%BAltiple.pdf",
     "2020-04-15", "guidance", 'Circular AJ-0725-04-2020-JM: transportistas que ingresen a Panamá con permiso de ingreso múltiple (a funcionarios de control migratorio en Paso Canoas y Las Tablillas)',
     'Circular AJ-0725-04-2020-JM to border-control officers at Paso Canoas and Las Tablillas: truck drivers travelling to Panama with a multiple-entry permit',
     "Circular-AJ-0725-04-2020-JM-transportistas-Panama"),
    ("20200928000204", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/CIRCULAR%20TRANSPORTISTAS%20TERRESTRE%2027%20ABRIL%202020%20FINAL.pdf",
     "2020-04-27", "guidance", 'Circular AJ-0755-04-2020-JM: Ingreso, permanencia y egreso de personas que conduzcan medios de transporte de carga o mercancías',
     'Circular AJ-0755-04-2020-JM to migration police at land borders: entry, stay and exit of drivers of goods vehicles',
     "Circular-AJ-0755-04-2020-JM-transportistas-terrestres"),
    ("20200922095602", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Control%20Migratorio%20en%20Puestos%20Mar%C3%ADtimos%20durante%20la%20emergencia%20nacional%20del%20COVID19.pdf",
     "2020-04-21", "guidance", 'Circular DPPME-0010-04-2020-AJ: Control migratorio en puestos marítimos durante la emergencia nacional del COVID-19',
     'Circular DPPME-0010-04-2020-AJ to migration police officers: border control at sea ports during the COVID-19 emergency',
     "Circular-DPPME-0010-04-2020-AJ-puestos-maritimos"),
    ("20200927191636", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/D.JUR.%200069-04-2020-JM.pdf",
     "2020", "guidance", 'D.JUR. 0069-04-2020-JM',
     'resolution D.JUR-0069-04-2020-JM (COVID-19 measures)',
     "D-JUR-0069-04-2020-JM"),
    ("20201026065823", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DG-040-07-2020%20-AJ%20Nuevas%20Medidas%20de%20Ingreso%20para%20Transportistas.pdf",
     "2020", "guidance", 'DG-040-07-2020 -AJ Nuevas Medidas de Ingreso para Transportistas',
     'circular DG-040-07-2020-AJ: new entry measures for truck drivers',
     "DG-040-07-2020-AJ-Nuevas-Medidas-de-Ingreso-para-Transportistas"),
    ("20201026071004", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DG-42-09-2020-AJ%20Actualizaci%C3%B3n%20de%20Medidas%20relacionadas%20con%20el%20COVID19%20para%20la%20PPM.pdf",
     "2020", "guidance", 'DG-42-09-2020-AJ Actualización de Medidas relacionadas con el COVID19 para la PPM',
     'circular DG-42-09-2020-AJ: updated COVID-19 measures for the migration police',
     "DG-42-09-2020-AJ-Actualizacion-de-Medidas-relacionadas-con-el-COVID19-para-la-PP"),
    ("20200922111837", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DGME-0014-04-2020%20prorroga%20de%20medidas%20de%20cierre%20de%20fronteras.pdf",
     "2020", "guidance", 'DGME-0014-04-2020 prorroga de medidas de cierre de fronteras',
     'circular DGME-0014-04-2020: extension of border-closure measures',
     "DGME-0014-04-2020-prorroga-de-medidas-de-cierre-de-fronteras"),
    ("20200927222529", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DGME-0015-04-2020%2C%20aclaraci%C3%B3n%20sobre%20prorroga%20de%20medidas%20de%20cierre%20de%20fronteras.pdf",
     "2020", "guidance", 'DGME-0015-04-2020, aclaración sobre prorroga de medidas de cierre de fronteras',
     'circular DGME-0015-04-2020: clarification on the extension of border closure',
     "DGME-0015-04-2020-aclaracion-sobre-prorroga-de-medidas-de-cierre-de-fronteras"),
    ("20200922095046", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DGME-0017-04-2020%20emisi%C3%B3n%20de%20orden%20sanitaria%20por%20parte%20de%20toda%20la%20PPME.pdf",
     "2020", "guidance", 'DGME-0017-04-2020 emisión de orden sanitaria por parte de toda la PPME',
     'circular DGME-0017-04-2020: issuing of health orders by all migration police officers',
     "DGME-0017-04-2020-emision-de-orden-sanitaria-por-parte-de-toda-la-PPME"),
    ("20200922112643", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DGME-009-03-2020%20procedimiento%20para%20aplicar%20impedimentos.pdf",
     "2020", "guidance", 'DGME-009-03-2020 procedimiento para aplicar impedimentos',
     'circular DGME-009-03-2020: procedure for applying entry bans',
     "DGME-009-03-2020-procedimiento-para-aplicar-impedimentos"),
    ("20200922114754", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DGME-018-03-2020%20aclaraci%C3%B3n%20circular%20DG-005-04-2020-AJ.pdf",
     "2020", "guidance", 'DGME-018-03-2020 aclaración circular DG-005-04-2020-AJ',
     'circular DGME-018-03-2020: clarification of circular DG-005',
     "DGME-018-03-2020-aclaracion-circular-DG-005-04-2020-AJ"),
    ("20200927230759", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DPPME-007-03-2020-AJ%20directriz%20de%20aplicaci%C3%B3n%20de%20acta%20colectiva%20por%20COVID19.pdf",
     "2020", "guidance", 'DPPME-007-03-2020-AJ directriz de aplicación de acta colectiva por COVID19',
     'circular DPPME-007-03-2020-AJ: use of a collective record (acta colectiva) during COVID-19',
     "DPPME-007-03-2020-AJ-directriz-de-aplicacion-de-acta-colectiva-por-COVID19"),
    ("20200927224215", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/DPPME-009-04-2020-AJ%2C%20implementaci%C3%B3n%20de%20modulo%20de%20impedimentos%20de%20ingreso%20en%20SIMMEL.pdf",
     "2020", "guidance", 'DPPME-009-04-2020-AJ, implementación de modulo de impedimentos de ingreso en SIMMEL',
     'circular DPPME-009-04-2020-AJ: entry-ban module in the SIMMEL border system',
     "DPPME-009-04-2020-AJ-implementacion-de-modulo-de-impedimentos-de-ingreso-en-SIMM"),
    ("20200914214108", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Lineamientos%20para%20Atenci%c3%b3n%20de%20Transportistas.pdf",
     "2020", "guidance", 'Lineamientos para Atención de Transportistas',
     'guidelines for handling truck drivers at the border',
     "Lineamientos-para-Atencion-de-Transportistas"),
    ("20201124175939", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Nuevas%20disposiciones%20migratorias.pdf",
     "2020", "guidance", 'Nuevas disposiciones migratorias',
     'new migration provisions (COVID-19 period)',
     "Nuevas-disposiciones-migratorias"),
    ("20200927235357", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/COVID-19/Versi%C3%B3n%202%20Protocolo%20Operativo%20PPM%20Oficinas%20COVID-19.pdf",
     "2020", "guidance", 'Versión 2 Protocolo Operativo PPM Oficinas COVID-19',
     'operating protocol for migration police offices, COVID-19, version 2',
     "Version-2-Protocolo-Operativo-PPM-Oficinas-COVID-19"),
    ("20230606154700", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2020/Circular%20DG-026-06-2020%20EEUU.pdf",
     "2020", "guidance", 'Circular DG-026-06-2020 EEUU',
     'circular DG-026-06-2020 (United States)',
     "Circular-DG-026-06-2020-EEUU"),
    ("20240917221512", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2020/DGME%202020%20RECOMENDACI%c3%93N%20COLECTIVA%20PARA%20EMPLEADA%20DOM%c3%89STICA%20%28DENEGATORIA%29%20%28TOE%29.pdf",
     "2020", "guidance", 'DGME 2020 RECOMENDACIÓN COLECTIVA PARA EMPLEADA DOMÉSTICA (DENEGATORIA) (TOE)',
     'labour ministry collective recommendation (refusal) on domestic workers, applied to work permits',
     "DGME-2020-RECOMENDACION-COLECTIVA-PARA-EMPLEADA-DOMESTICA-DENEGATORIA-TOE"),
    ("20230606154508", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2021/Circular%20DG-003-02-2021%20Sobre%20documentos%20emitidos%20por%20Unidad%20de%20Refugio%2003%20Marzo%202021.pdf",
     "2021", "guidance", 'Circular DG-003-02-2021 Sobre documentos emitidos por Unidad de Refugio 03 Marzo 2021',
     'circular DG-003-02-2021: documents issued by the Refuge Unit',
     "Circular-DG-003-02-2021-Sobre-documentos-emitidos-por-Unidad-de-Refugio-03-Marzo"),
    ("20230606154822", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2021/Circular%20DG-14-07-2021%20Documentos%20de%20Identificaci%C3%B3n%20de%20Personas%20Extranjeras%20Julio%202021.pdf",
     "2021", "guidance", 'Circular DG-14-07-2021 Documentos de Identificación de Personas Extranjeras Julio 2021',
     'circular DG-14-07-2021: identity documents of foreign nationals',
     "Circular-DG-14-07-2021-Documentos-de-Identificacion-de-Personas-Extranjeras-Juli"),
    ("20210512150719", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2021/COVID%2019%20-%202021/Circular%20AJ-0292-03-2021-ABM%20Actualizaci%C3%B3n%20de%20procesos%20COVID%20PPME.pdf",
     "2021", "guidance", 'Circular AJ-0292-03-2021-ABM Actualización de procesos COVID PPME',
     'circular AJ-0292-03-2021-ABM: updated COVID-19 procedures for the migration police',
     "Circular-AJ-0292-03-2021-ABM-Actualizacion-de-procesos-COVID-PPME"),
    ("20240917221314", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2021/DGME%202020%20187%20%20RECOMENDACI%C3%93N%20COLECTIVA%20PARA%20OCUPACIONES%20NO%20RECOMENDADAS.pdf",
     "2021", "guidance", 'DGME 2020 187  RECOMENDACIÓN COLECTIVA PARA OCUPACIONES NO RECOMENDADAS',
     'labour ministry collective recommendation of occupations not recommended for work permits (2020)',
     "DGME-2020-187-RECOMENDACION-COLECTIVA-PARA-OCUPACIONES-NO-RECOMENDADAS"),
    ("20240917221512", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2021/DGME%2c%202021%20501%20RECOMENDACI%c3%93N%20COLECTIVA%20DE%20OCUPACIONES%20NO%20RECOMENDADAS%20%282021%20-%202022%29.pdf",
     "2021", "guidance", 'DGME, 2021 501 RECOMENDACIÓN COLECTIVA DE OCUPACIONES NO RECOMENDADAS (2021 - 2022)',
     'labour ministry collective recommendation of occupations not recommended for work permits (2021-2022)',
     "DGME-2021-501-RECOMENDACION-COLECTIVA-DE-OCUPACIONES-NO-RECOMENDADAS-2021-2022"),
    ("20241005031405", "https://migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2021/Protocolo-2021-2022%20Trabajadores-Temporales-Agricolas.%2017092021.pdf",
     "2021", "guidance", 'Protocolo-2021-2022 Trabajadores-Temporales-Agricolas. 17092021',
     'protocol for temporary agricultural workers 2021-2022',
     "Protocolo-2021-2022-Trabajadores-Temporales-Agricolas-17092021"),
    ("20220121163239", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2021/Resoluci%C3%B3n%20Lineamientos%20%20Gestion%20de%20Extranjeria%20PUBLICADA%20GAC%20227%2024%20NOV%202021.pdf",
     "2021", "guidance", 'Resolución Lineamientos  Gestion de Extranjeria PUBLICADA GAC 227 24 NOV 2021',
     "resolution with guidelines for the Foreigners' Department (Gazette 227, 24 Nov 2021)",
     "Resolucion-Lineamientos-Gestion-de-Extranjeria-PUBLICADA-GAC-227-24-NOV-2021"),
    ("20211204125142", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2021/D.JUR.%20179-10-2021-ABM%20Regularizaci%C3%B3n%20Poblaci%C3%B3n%20Ind%C3%ADgena%20Transfronteriza.pdf",
     "2021", "guidance", 'D.JUR. 179-10-2021-ABM Regularización Población Indígena Transfronteriza',
     'resolution D.JUR-179-10-2021-ABM: regularisation of cross-border indigenous population',
     "D-JUR-179-10-2021-ABM-Regularizacion-Poblacion-Indigena-Transfronteriza"),
    ("20230606154358", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2022/CIRCULAR%20DG-0029-10-2022-DG-GE%20COMUNICADO%20INSTITUCIONES%20PUBLICAS%20Y%20PRIVADAS%20DJUR%200144-09-2022.pdf",
     "2022", "guidance", 'CIRCULAR DG-0029-10-2022-DG-GE COMUNICADO INSTITUCIONES PUBLICAS Y PRIVADAS DJUR 0144-09-2022',
     'circular DG-0029-10-2022-DG-GE to public and private institutions on resolution DJUR-0144-09-2022',
     "CIRCULAR-DG-0029-10-2022-DG-GE-COMUNICADO-INSTITUCIONES-PUBLICAS-Y-PRIVADAS-DJUR"),
    ("20220809165850", "https://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2022/DG-05-03-2022%20Circular%20pro%cc%81rroga%20de%20DIMEX.pdf",
     "2022", "guidance", 'DG-05-03-2022 Circular prórroga de DIMEX',
     'circular DG-05-03-2022: extension of DIMEX documents',
     "DG-05-03-2022-Circular-prorroga-de-DIMEX"),
    ("20230606154638", "https://www.migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/2023/Circular%2012-02-2023%20Documentos%20emitidos%20por%20la%20DGME.pdf",
     "2023", "guidance", 'Circular 12-02-2023 Documentos emitidos por la DGME',
     'circular 12-02-2023: documents issued by the DGME',
     "Circular-12-02-2023-Documentos-emitidos-por-la-DGME"),
    ("20240704182137", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2023/DNE-DML-OF-340-2023%20RECOMENDACI%C3%93N%20DE%20OCUPACIONES%20NO%20RECOMENDADAS.pdf",
     "2023", "guidance", 'DNE-DML-OF-340-2023 RECOMENDACIÓN DE OCUPACIONES NO RECOMENDADAS',
     'labour ministry recommendation DNE-DML-OF-340-2023 of occupations not recommended',
     "DNE-DML-OF-340-2023-RECOMENDACION-DE-OCUPACIONES-NO-RECOMENDADAS"),
    ("20240917221512", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2023/DNE-DML-OF-535-2022%20RECOMENDACI%c3%93N%20DE%20OCUPACIONES%20NO%20RECOMENDADAS%20FIRMADO%2010122022%20014514.pdf",
     "2023", "guidance", 'DNE-DML-OF-535-2022 RECOMENDACIÓN DE OCUPACIONES NO RECOMENDADAS FIRMADO 10122022 014514',
     'labour ministry recommendation DNE-DML-OF-535-2022 of occupations not recommended',
     "DNE-DML-OF-535-2022-RECOMENDACION-DE-OCUPACIONES-NO-RECOMENDADAS-FIRMADO-1012202"),
    ("20240705175739", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2023/Resoluci%C3%B3n%20N%C2%BA%20D.%20JUR-552-07-2023-ABM%20Solicitud%20de%20Inscripci%C3%B3n%20Consular.pdf",
     "2023", "guidance", 'Resolución Nº D. JUR-552-07-2023-ABM Solicitud de Inscripción Consular',
     'resolution D.JUR-552-07-2023-ABM: applications through consular registration',
     "Resolucion-No-D-JUR-552-07-2023-ABM-Solicitud-de-Inscripcion-Consular"),
    ("20241109151447", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2024/Protocolo-General-Atencion-Migrantes-Epoca-Cosechas.pdf",
     "2024", "guidance", 'Protocolo-General-Atencion-Migrantes-Epoca-Cosechas',
     'general protocol for attending migrants in the harvest season',
     "Protocolo-General-Atencion-Migrantes-Epoca-Cosechas"),
    ("20240705173623", "https://www.migracion.go.cr/Documentos%20compartidos/Normativa%20Legal%20Migratoria/2024/Recomendaci%C3%B3n%20MTSS%20Trabajo%20Domestico%20MTSS-DMT-DVAS-DNE-DML-OF-108-2024.pdf",
     "2024", "guidance", 'Recomendación MTSS Trabajo Domestico MTSS-DMT-DVAS-DNE-DML-OF-108-2024',
     'labour ministry recommendation on domestic work (2024)',
     "Recomendacion-MTSS-Trabajo-Domestico-MTSS-DMT-DVAS-DNE-DML-OF-108-2024"),
    ("20191017090943", "http://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/Circular%20Categor%C3%ADas%20Especiapes%20por%20Razones%20de%20Humanidad.pdf",
     "2019", "guidance", 'Circular Categorías Especiapes por Razones de Humanidad',
     'circular on special categories on humanitarian grounds',
     "Circular-Categorias-Especiapes-por-Razones-de-Humanidad"),
    ("20191017090803", "http://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/Circular%20DIMEX%20que%20se%20encuentran%20actualmente%20vigentes.pdf",
     "2019", "guidance", 'Circular DIMEX que se encuentran actualmente vigentes',
     'circular on DIMEX documents currently valid',
     "Circular-DIMEX-que-se-encuentran-actualmente-vigentes"),
    ("20191017085733", "http://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/Documento%20explicativo%20sobre%20los%20Cambios%20de%20la%20Directriz%20de%20Visas.pdf",
     "2019", "guidance", 'Documento explicativo sobre los Cambios de la Directriz de Visas',
     'explanatory note on the changes to the visa directive',
     "Documento-explicativo-sobre-los-Cambios-de-la-Directriz-de-Visas"),
    ("20191017092226", "http://migracion.go.cr/Documentos%20compartidos/Circulares%20y%20Directrices/Recomendaci%C3%B3n%20de%20Ocupaciones%20No%20Recomendadas%20de%20Trabajo%20DGME%202018.pdf",
     "2019", "guidance", 'Recomendación de Ocupaciones No Recomendadas de Trabajo DGME 2018',
     'labour ministry recommendation of occupations not recommended (2018)',
     "Recomendacion-de-Ocupaciones-No-Recomendadas-de-Trabajo-DGME-2018"),
    ("20220809165327", "https://migracion.go.cr/Documentos%20compartidos/GTT/Protocolo_Atencion_Situaciones_Migratorias_Especiales_27Nov.pdf",
     "2022", "guidance", 'Protocolo_Atencion_Situaciones_Migratorias_Especiales_27Nov',
     'protocol for special migration situations (trafficking task force)',
     "Protocolo-Atencion-Situaciones-Migratorias-Especiales-27Nov"),
    ("20220516205523", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Manual%20Atenci%C3%B3n%20Interinstitucional%20PME%20en%20Explotaci%C3%B3n.pdf",
     "2022", "guidance", 'Manual Atención Interinstitucional PME en Explotación',
     'inter-agency manual for minors in exploitation',
     "Manual-Atencion-Interinstitucional-PME-en-Explotacion"),
    ("20220516205452", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/OIM%20PROTOCOLO%20COSTA%20RICA.pdf",
     "2022", "guidance", 'OIM PROTOCOLO COSTA RICA',
     'IOM protocol for Costa Rica (unaccompanied and separated children)',
     "OIM-PROTOCOLO-COSTA-RICA"),
    ("20220516205408", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20Atenci%C3%B3n%20PME%20No%20Acompa%C3%B1ada%20o%20Separada.pdf",
     "2022", "guidance", 'Protocolo Atención PME No Acompañada o Separada',
     'protocol for unaccompanied or separated minors',
     "Protocolo-Atencion-PME-No-Acompanada-o-Separada"),
    ("20220516205403", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20de%20Actuacion%20para%20atender%20a%20las%20Personas%20Menoresd%20de%20Edad%20Estudiantes%20Extranjeros.pdf",
     "2022", "guidance", 'Protocolo de Actuacion para atender a las Personas Menoresd de Edad Estudiantes Extranjeros',
     'protocol for foreign minor students',
     "Protocolo-de-Actuacion-para-atender-a-las-Personas-Menoresd-de-Edad-Estudiantes-"),
    ("20220516205433", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20de%20Actuacion%20para%20Situaciones%20Migratoris%20Especiales.pdf",
     "2022", "guidance", 'Protocolo de Actuacion para Situaciones Migratoris Especiales',
     'protocol for special migration situations of minors',
     "Protocolo-de-Actuacion-para-Situaciones-Migratoris-Especiales"),
    ("20220516205436", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20de%20Regularizacion%20de%20Permanencia%20de%20las%20Personas%20Menores%20de%20Edad%20Extranjeras%20PANI.pdf",
     "2022", "guidance", 'Protocolo de Regularizacion de Permanencia de las Personas Menores de Edad Extranjeras PANI',
     'protocol (with PANI) for regularising foreign minors',
     "Protocolo-de-Regularizacion-de-Permanencia-de-las-Personas-Menores-de-Edad-Extra"),
    ("20220516205442", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20Interno%20Para%20Repatriaci%C3%B3n%20V%C3%ADctimas%20de%20Trata%20Menores%20de%20Edad%20DGME.pdf",
     "2022", "guidance", 'Protocolo Interno Para Repatriación Víctimas de Trata Menores de Edad DGME',
     'DGME internal protocol for repatriating child victims of trafficking',
     "Protocolo-Interno-Para-Repatriacion-Victimas-de-Trata-Menores-de-Edad-DGME"),
    ("20220516205405", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20Nacional%20del%20Sistema%20de%20Alerta.pdf",
     "2022", "guidance", 'Protocolo Nacional del Sistema de Alerta',
     'national protocol of the alert system (missing minors)',
     "Protocolo-Nacional-del-Sistema-de-Alerta"),
    ("20220516205513", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20para%20la%20atenci%C3%B3n%20de%20personas%20menores%20de%20edad%20extranjeras%20padres%20sometidos%20a%20deportacion.pdf",
     "2022", "guidance", 'Protocolo para la atención de personas menores de edad extranjeras padres sometidos a deportacion',
     'protocol for foreign minors whose parents face deportation',
     "Protocolo-para-la-atencion-de-personas-menores-de-edad-extranjeras-padres-someti"),
    ("20220516205442", "https://www.migracion.go.cr/Documentos%20compartidos/Ni%C3%B1ez/Protocolo%20para%20la%20Detecci%C3%B3n,%20Atenci%C3%B3n%20y%20Protecci%C3%B3n%20Integral.pdf",
     "2022", "guidance", 'Protocolo para la Detección, Atención y Protección Integral',
     'protocol for detection, care and protection (minors)',
     "Protocolo-para-la-Deteccion-Atencion-y-Proteccion-Integral"),
    ("20231216123616", "https://www.migracion.go.cr/Documentos%20compartidos/Refugio/Procedimiento%20para%20el%20Otorgamiento%20de%20Permisos%20Laborales%20a%20las%20Personas%20Solicitantes%20de%20Refugio.pdf",
     "2023", "guidance", 'Procedimiento para el Otorgamiento de Permisos Laborales a las Personas Solicitantes de Refugio',
     'procedure for granting work permits to asylum seekers',
     "Procedimiento-para-el-Otorgamiento-de-Permisos-Laborales-a-las-Personas-Solicita"),
    ("20220826195554", "https://www.migracion.go.cr/Documentos%20compartidos/Visas/Cambios%20principales%20de%20la%20Circular%20DG-0018-07-2022-DG-UV.pdf",
     "2022", "guidance", 'Cambios principales de la Circular DG-0018-07-2022-DG-UV',
     'main changes made by circular DG-0018-07-2022 (visa guidelines)',
     "Cambios-principales-de-la-Circular-DG-0018-07-2022-DG-UV"),
    ("20160804074736", "http://migracion.go.cr:80/institucion/leyes%20migratorias/circulares/circular%20DG0029-2013.pdf",
     "2016", "guidance", 'circular DG0029-2013',
     'circular DG-0029-2013',
     "circular-DG0029-2013"),
    ("20180517001912", "http://www.migracion.go.cr:80/institucion/leyes%20migratorias/circulares%20y%20directrices/CAMBIOS%20EN%20LA%20DIRECTRIZ%20DE%20INGRESO%20NO%20RESIDENTES%20DG-0042-11-2016.pdf",
     "2018", "guidance", 'CAMBIOS EN LA DIRECTRIZ DE INGRESO NO RESIDENTES DG-0042-11-2016',
     'changes in the entry directive for non-residents DG-0042-11-2016',
     "CAMBIOS-EN-LA-DIRECTRIZ-DE-INGRESO-NO-RESIDENTES-DG-0042-11-2016"),
    ("20151123185648", "http://www.migracion.go.cr:80/institucion/leyes%20migratorias/otros/Actividades%20Laborales%20SI%20recomendadas%20por%20el%20Ministerio%20de%20Trabajo.pdf",
     "2015", "guidance", 'Actividades Laborales SI recomendadas por el Ministerio de Trabajo',
     'work activities recommended by the labour ministry',
     "Actividades-Laborales-SI-recomendadas-por-el-Ministerio-de-Trabajo"),
    ("20161020142207", "http://migracion.go.cr:80/institucion/ninez_adolescencia/protocolos/3-ProtocoloPME-Nofamilyfinal.pdf",
     "2016", "guidance", '3-ProtocoloPME-Nofamilyfinal',
     'protocol for minors without family (2016)',
     "3-ProtocoloPME-Nofamilyfinal"),
    ("20140813171318", "http://migracion.go.cr/institucion/Trata/MODELO%20ATENCION%20INTEGRAL.pdf",
     "2014", "guidance", 'MODELO ATENCION INTEGRAL',
     'integral care model for victims of trafficking',
     "MODELO-ATENCION-INTEGRAL"),
    ("20130426083958", "http://migracion.go.cr/extranjeros/CASOS%20ESPECIALES.pdf",
     "2013", "guidance", 'CASOS ESPECIALES',
     'special cases (2013)',
     "CASOS-ESPECIALES"),
]

# subject glosses for SCIJ titles: first matching pattern wins
SCIJ_GLOSS = [
    (r"^Reforma Directrices Generales de Visas", "amendment of the general guidelines on entry and stay visas for non-residents"),
    (r"^Addenda|^Adenda", "addendum to the general guidelines on entry and stay visas for non-residents"),
    (r"Directrices? [Gg]enerales (de|sobre) [Vv]isas", "general guidelines on entry (and stay) visas for non-residents"),
    (r"^Lineamientos de las visas de ingreso a Costa Rica para nacionales de Venezuela", "guidelines on entry visas for Venezuelan nationals and transit visas for Cuban, Nicaraguan and Venezuelan nationals"),
    (r"(?i)exoneración temporal de visa .*cruceros|Exonera de visa consular durante la temporada de cruceros", "temporary visa exemption for Colombian, Ecuadorian and Dominican nationals arriving in transit on cruise ships"),
    (r"^Revoca la exoneración temporal de visa", "revokes the temporary visa exemption for international transport crews (resolution D.JUR 426-08-2023-JM)"),
    (r"^Exoneración temporal de visa para las personas extranjeras que ingresan .*Transporte Internacional|^Dispone una exoneración temporal de visa para las personas extranjeras que ingresan", "temporary visa exemption for non-residents in the subcategory crews of international passenger and goods transport"),
    (r"pase corto a la costa|ampliación del área geográfica de movilización", "temporary extension of the area cruise-ship crew (shore-excursion staff) may move in on shore leave"),
    (r"^Establece disposiciones sobre el ingreso de tripulantes marítimos", "rules on entry of ship crews on shore leave"),
    (r"Categoría especial temporal complementaria", "special temporary complementary category for Nicaraguan, Venezuelan, Cuban and Colombian nationals whose refugee claims are pending or refused"),
    (r"^Reforma Crea categoría especial temporal de protección complementaria", "amendment of the special temporary category of complementary protection for Venezuelans, Nicaraguans and Cubans refused refugee status"),
    (r"^Crea categoría especial temporal de protección complementaria", "creates a special temporary category of complementary protection for Venezuelans, Nicaraguans and Cubans refused refugee status"),
    (r"deportadas de(sde)? los Estados Unidos", "entry, temporary stay, documentation and regularisation of foreign nationals deported from the United States to Costa Rica"),
    (r"^Actualización de los Documentos de Identificación|^Documentos de identificación de personas extranjeras emitidos|^Nuevo formato de documento", "identity documents for foreign nationals issued by the DGME (which remain valid, new format)"),
    (r"^Crea los mecanismos para agilizar", "mechanisms to speed up the processing of regularisation applications by persons who have claimed refugee status"),
    (r"^Medidas administrativas temporales para la emisión, renovación y duplicados", "temporary administrative measures for issuing, renewing and duplicating migration identity documents (DIMEX)"),
    (r"^Continuidad para la emisión de documentos DIMEX", "continued issue of DIMEX identity documents in physical form"),
    (r"flujos migratorios mixtos", "exceptional entry and transitory stay permits for persons travelling in mixed migration flows in vulnerable conditions"),
    (r"pasaportes venezolanos", "acceptance of expired Venezuelan passports for entry, stay and exit"),
    (r"^Nuevas medidas administrativas aplicables a los trámites", "new administrative measures for procedures handled by the Visa and Refuge units, the Foreigners' Department and the regional offices"),
    (r"^Establece modificaciones a requisitos y procedimientos", "changes to requirements and procedures for processing and deciding applications for legal residence"),
    (r"^Exonerar de manera excepcional de la presentación del pasaporte", "exceptional passport exemption for Panamanian crews of international passenger transport"),
    (r"^Procedimiento para el otorgamiento de permisos laborales", "procedure for granting work permits to asylum seekers"),
    (r"^Procedimiento temporal para la tramitación y resolución|^Lineamientos de procedimientos modificaciones temporales", "temporary procedure and requirements for processing and deciding applications for legal residence"),
    (r"^Se modifican punto Quinto|^Se modifican las medidas administrativas relativas a la documentación", "amendment of the administrative measures on documentation (DIMEX) of foreign nationals"),
    (r"^Adenda a la Circular DG-0018", "addendum to circular DG-0018-07-2022 (general visa guidelines)"),
    (r"[Mm]edidas administrativas temporales|Medidas Administrativas", "temporary administrative measures for DGME services to the public (COVID-19 period: deadlines, appointments, extensions)"),
    (r"^Prorrogar por el período|^Establece (medidas y )?(los )?plazos de permanencia|^Autorización (de )?ingreso de personas extranjeras al país bajo|^Reforma Autorización ingreso|^Regulaciones para autorizar el ingreso|^Prorroga plazo de permanencia legal", "entry and permitted stay of international transport crews (COVID-19 period)"),
    (r"^Deroga actos administrativos", "repeals the administrative acts issued because of the COVID-19 emergency"),
    (r"Decreto Ejecutivo (número |N° )?42690|42513", "migration provisions for applying the COVID-19 entry decrees (42513-MGP-S, 42690-MGP-S)"),
    (r"^Medidas administrativas sobre la relación y autorización de ingreso", "administrative measures on authorising entry of foreign nationals under decree 42690-MGP-S"),
    (r"^Actualización de las disposiciones migratorias para ingreso y egreso", "updated migration provisions for entry and exit during the COVID-19 emergency"),
    (r"menores de edad migrantes insertas en el sistema educativo", "temporary requirements for regularising and documenting migrant children enrolled in public schools"),
    (r"indígenas transfronterizas", "special procedure to regularise cross-border indigenous persons"),
    (r"^Proceso de personas que conduzcan|^Ingreso, permanencia y egreso personas que conduzcan|Sixaola", "entry, stay and exit of drivers of goods vehicles"),
    (r"puesto no habilitado", "how officers proceed on detecting entry or exit of foreign nationals with regular status through an unauthorised crossing"),
    (r"turismo de China", "temporary protocol for promoting tourism from China (visa handling)"),
    (r"^Establece como requisito de egreso", "PCR test requirement for leaving Costa Rica for Nicaragua"),
    (r"cordón fronterizo", "declares the entire land border a migration control post"),
    (r"^Proceso de excepción para la resolución de solicitudes", "exceptional process for deciding pending residence applications"),
    (r"antecedentes penales", "criminal-record certificates from countries with local and federal criminal jurisdictions"),
    (r"depósito de garantía", "guarantee deposits for temporary and permanent residence"),
    (r"^Procedimiento especial para la obtención de permanencia legal en el país de las personas de nacionalidad venezolana", "special procedure for Venezuelan nationals to obtain legal residence"),
    (r"solicitantes de refugio y la condición de apátridas", "identity documents for asylum seekers and stateless persons"),
    (r"atención de humanitaria", "entry and transitory stay permits on humanitarian grounds for migrants from Africa, South Asia and the Caribbean"),
    (r"Entrada en vigencia de la Ley", "entry into force of Migration Law 8764"),
    (r"^Reforma Reglamento del Regimen de Excepción", "amendment of the 1999 regulation on the exceptional regularisation regime"),
    (r"Régimen de Excepción 1999", "regulation on the 1999 exceptional regularisation regime"),
]
SCIJ_GUIDANCE = {99521, 100591, 100907, 105721}


# Known to exist, not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Sitio de la DGME: circulares, protocolos y normativa publicados en www.migracion.go.cr (versión actual)", "",
     "https://www.migracion.go.cr/", "not fetched: the site answers robots.txt and every page with a Cloudflare "
     "JavaScript challenge ('Just a moment...'); host closed; older copies taken from the Internet Archive instead"),
    ("Textos publicados en La Gaceta / Boletín Judicial (Imprenta Nacional)", "", "https://www.imprentanacional.go.cr/",
     "not fetched: robots.txt of www.imprentanacional.go.cr disallows ClaudeBot, anthropic-ai and Claude-Web"),
]

blocked = {}
errors = {}
last_hit = {}
rules = {}
failures = []
rows = []
stats = {"new": 0}


def host_of(url):
    return urllib.parse.urlsplit(url).netloc


def quote_url(u):
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(urllib.parse.unquote(p.path), safe="/%:")))


class HostLock:
    """Exclusive lock per shared host (web.archive.org), held through the pause after the request."""
    def __init__(self, host):
        self.f = None
        if host == "web.archive.org":
            LOCKDIR.mkdir(parents=True, exist_ok=True)
            self.f = open(LOCKDIR / (host + ".lock"), "w")

    def __enter__(self):
        if self.f:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        if self.f:
            time.sleep(IA_DELAY)
            fcntl.flock(self.f, fcntl.LOCK_UN)
            self.f.close()


def wait(host):
    delay = max(IA_DELAY if host == "web.archive.org" else DELAY, rules.get(host, ([], 0))[1])
    gap = time.time() - last_hit.get(host, 0)
    if gap < delay:
        time.sleep(delay - gap)
    last_hit[host] = time.time()


def request(url, data=None):
    """One request. Returns (bytes, content type) or a 1-tuple with the error; closes the host on a refusal."""
    host = host_of(url)
    if host in blocked:
        return None
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["X-Requested-With"] = "XMLHttpRequest"
        data = urllib.parse.urlencode(data).encode()
    with HostLock(host):
        wait(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(quote_url(url), data=data, headers=headers),
                                        timeout=180) as r:
                errors[host] = 0
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                blocked[host] = f"HTTP {e.code}"
                print(f"  REFUSED by {host} (HTTP {e.code}); host not asked again")
            else:
                errors[host] = errors.get(host, 0) + (1 if e.code >= 500 else 0)
            return ("HTTP %d" % e.code,)
        except Exception as e:                              # noqa: BLE001 - connection trouble
            errors[host] = errors.get(host, 0) + 1
            if errors[host] >= 3:
                blocked[host] = "three failures in a row"
                print(f"  giving up on {host}")
            return (f"connection error: {e}",)


def load_robots(host):
    pats, delay, text = [], 0.0, ""
    with HostLock(host):
        wait(host)
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://{host}/robots.txt",
                                                               headers={"User-Agent": UA}), timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                blocked[host] = f"robots.txt answers HTTP {e.code}"
                print(f"  REFUSED: {host} robots.txt answers HTTP {e.code}; host not used")
        except Exception as e:                              # noqa: BLE001
            blocked[host] = f"robots.txt unreachable: {e}"
            print(f"  {host}: robots.txt unreachable ({e}); host not used")
    if re.search(r"<html", text[:2000], re.I):
        if re.search(r"challenge|captcha|just a moment|incapsula", text, re.I):
            blocked[host] = "robots.txt answers with a bot-check page"
        text = ""                                           # an HTML error page: no rules
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
    if host in blocked:
        return False
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


def room(title, date, url):
    n, size = used()
    if n >= MAX_FILES or size >= MAX_BYTES:
        failures.append((title, date, url, "not fetched: size or file limit of the folder reached"))
        return False
    return True


def save(dest, content):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(content)
    tmp.rename(dest)
    stats["new"] += 1
    print(f"  saved {dest.relative_to(OUT)}")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def slug(s, n=70):
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:n].rstrip("-")


def gloss(name):
    for pat, en in SCIJ_GLOSS:
        if re.search(pat, name):
            return en
    return ""


def source_scij():
    print("scij: DGME norms in the Sistema Costarricense de Información Jurídica")
    if not allowed(SCIJ_LIST):
        failures.append(("Listado SCIJ de normas de la DGME", "", SCIJ_LIST, "excluded by robots.txt or host closed"))
        return
    r = request(SCIJ_LIST)
    if r is None or len(r) == 1:
        failures.append(("Listado SCIJ de normas de la DGME", "", SCIJ_LIST, r[0] if r else "host closed"))
        return
    page = r[0].decode("utf-8", "replace")
    i = page.find('"data":{"Data":[')
    j = page.find('],"Total":', i)
    if i < 0 or j < 0:
        failures.append(("Listado SCIJ de normas de la DGME", "", SCIJ_LIST, "result list not found in the page"))
        return
    data = json.loads(page[i + len('"data":{"Data":'):j + 1])
    print(f"  {len(data)} DGME norms listed")
    for d in data:
        ficha, version = d["IdFichaNorma"], d["IdVersionNorma"]
        if ficha in SKIP_SCIJ:
            continue
        tipo, num, date = d["NombreTipoNorma"].strip(), d["NumeroNormativa"], d["FechaNormativa"][:10]
        name, state = clean(d["NombreNormativa"]), d["EstadoNorma"].strip()
        kind = "guidance" if tipo in ("Circular", "Directriz") or ficha in SCIJ_GUIDANCE else "procedural act"
        title = f"{tipo} N.° {num} de la DGME, {date}: {name} [{state} según SCIJ]"
        title_en = (f"DGME {TYPE_EN.get(tipo, tipo)} {num} of {date}: " + gloss(name)
                    + f" [{ {'Vigente': 'in force', 'Derogado': 'repealed', 'Revocada': 'revoked'}.get(state, state)} per SCIJ]")
        rel = f"scij/{date}_{slug(tipo)}-{num}_ficha-{ficha}.html"
        dest = OUT / rel
        url = SCIJ_PAGE.format(ficha=ficha, version=version)
        if not dest.exists():
            if not room(title, date, url):
                continue
            r = request(SCIJ_TEXT, {"idFichaNorma": ficha, "version": version, "busqueda": ""})
            if r is None or len(r) == 1:
                failures.append((title, date, url, r[0] if r else "host closed: " + blocked.get(host_of(SCIJ), "")))
                continue
            try:
                frag = json.loads(r[0].decode("utf-8"))["html"]
            except Exception:                               # noqa: BLE001
                failures.append((title, date, url, "answer was not the expected JSON with the text"))
                continue
            if "contenedorTexto" not in frag or len(frag) < 1500:
                failures.append((title, date, url, "SCIJ returned no text for this norm"))
                continue
            save(dest, frag.encode("utf-8"))
        rows.append((rel, title, date, url, kind, title_en, DGME_BODY))


def source_dgme():
    print("dgme: DGME PDFs from the Internet Archive (the DGME site itself is behind a bot check)")
    for ts, orig, date, kind, title, title_en, name in WAYBACK:
        rel = f"dgme/{date}_{name}.pdf"
        dest = OUT / rel
        url = f"https://web.archive.org/web/{ts}id_/{orig}"
        if (OUT / ".large" / rel).exists():
            continue
        if not dest.exists():
            if not room(title, date, url):
                continue
            if not allowed(url):
                failures.append((title, date, url, "not fetched: web.archive.org " + blocked.get("web.archive.org", "robots.txt")
                                 + " - the Internet Archive throttles this machine (connection refused); try again later"))
                continue
            r = request(url)
            if r is None or len(r) == 1:
                failures.append((title, date, url, r[0] if r else "host closed: " + blocked.get("web.archive.org", "")))
                print(f"  FAILED {url}: {failures[-1][3]}")
                continue
            tmp = dest.with_name(dest.name + ".part")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(r[0])
            if not is_pdf(tmp):
                tmp.unlink()
                failures.append((title, date, url, "archived copy is not a PDF (" + (r[1] or "no type") + ")"))
                continue
            if len(r[0]) > MAX_ONE:
                (OUT / ".large" / rel).parent.mkdir(parents=True, exist_ok=True)
                tmp.rename(OUT / ".large" / rel)
                continue
            tmp.rename(dest)
            stats["new"] += 1
            print(f"  saved {rel}")
        rows.append((rel, title, date, url, kind, title_en or "", DGME_BODY))


SOURCES = {"scij": source_scij, "dgme": source_dgme}


def main():
    wanted = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    for a in sys.argv[1:]:                  # --give-up=HOST: treat HOST as closed (e.g. after it refused us)
        if a.startswith("--give-up="):
            blocked[a.split("=", 1)[1]] = "given up before this run (it had refused connections)"
    OUT.mkdir(exist_ok=True)
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
    on_disk = {str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file() and p.suffix in (".pdf", ".html")
               and ".large" not in p.parts}
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

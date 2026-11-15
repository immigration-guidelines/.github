#!/usr/bin/env python3
"""Download Chile's published migration circulars, instructions and general resolutions into ./cl/.

    python3 download_cl.py            all three sources, then rewrite cl/index.tsv and cl/not-obtained.tsv
    python3 download_cl.py leychile   one source only: leychile | dem | sermig | transparencia
    python3 download_cl.py --index    no network: rebuild the index from the cached listings and the files on disk

What it collects:
    leychile/   Resolutions, exempt decrees and decrees of general application on migration published in
                the Diario Oficial, as held by the Biblioteca del Congreso Nacional (LeyChile). Found with
                LeyChile's search service, filtered by issuing body (Interior, Servicio Nacional de
                Migraciones, Relaciones Exteriores) and title, and saved as LeyChile's official XML
                (https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=N). The law (21.325), the
                refugee law and their regulations are left out on purpose.
    dem/        Circulars, oficios and instructivos of the former Departamento de Extranjería y Migración
                (extranjeria.gob.cl, closed), 2008-2021, from the Wayback Machine: the documents linked
                from the "Legislación Migratoria" / "Leyes Migratorias" pages, plus archived PDFs whose
                name says circular / oficio / instructivo / protocolo.
    sermig/     Oficios, resolutions and manuals that the Servicio Nacional de Migraciones publishes on
                serviciomigraciones.cl (the site is scanned through its sitemaps; a page is fetched again
                only when its sitemap date changes).

    transparencia/  The Servicio's own circulars ("circulares de uso interno") and protocol resolutions, as
                listed in its Transparencia Activa pages on portaltransparencia.cl (sections "Marco
                Normativo" and "Actos y resoluciones con efectos sobre terceros > Circulares"). The portal
                asks for 60 s between requests, so this part takes about six minutes. The files themselves
                sit on Google Drive, whose robots.txt forbids the download address, so the script only
                lists them in cl/not-obtained.tsv with the name to save each one under; a file saved by
                hand under that name is indexed with its full title on the next run.

Rules: robots.txt is read for every host and obeyed; one request at a time; 1.5 s between requests
(8 s for the Wayback Machine); a host that answers 403 or 429, or fails three times in a row, is left
alone for the rest of the run. Files already present are skipped. Whatever is listed but could not be
fetched goes to cl/not-obtained.tsv, and a later run picks it up.
"""
import hashlib
import html
import http.cookiejar
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cl"
CACHE = OUT / "listings"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = {"web.archive.org": 8.0}                    # seconds between requests; default 1.5
MAX_FILES, MAX_BYTES = 3000, 1_000_000_000
OFFLINE = "--index" in sys.argv

blocked = {}        # host -> reason
failures = {}       # host -> consecutive failures
last_hit = {}       # host -> time of last request
robots = {}         # host -> RobotFileParser or None
rows = {}           # file or source_url -> index row (dict)
missing = []        # (source_url, title, date, why, source)
current = [""]      # name of the source being processed
INDEX_COLS = ["file", "title", "date", "source_url", "issuing_body", "act_number", "title_en", "note"]


# ---------------------------------------------------------------------------------------------- network

def _get(url, host, data=None, headers=None, opener=None):
    wait = max(DELAY.get(host, 1.5), _crawl_delay(host)) - (time.time() - last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last_hit[host] = time.time()
    req = urllib.request.Request(_ascii(url), data=data, headers=dict({"User-Agent": UA}, **(headers or {})))
    with (opener.open if opener else urllib.request.urlopen)(req, timeout=120) as r:
        return r.read(), r.headers.get("Content-Type", "")


def _ascii(url):
    """Percent-encode non-ASCII characters (N°, accents) without touching existing escapes."""
    return urllib.parse.quote(url, safe=":/?&=%#+,;@!$'()*~[]")


def _crawl_delay(host):
    rp = robots.get(host)
    try:
        return float(rp.crawl_delay("*") or 0) if rp else 0.0
    except Exception:                               # noqa: BLE001
        return 0.0


def allowed(url):
    """Read the host's robots.txt once; True if a generic user agent may fetch url."""
    host = urllib.parse.urlsplit(url).netloc
    if host not in robots:
        robots[host] = None
        try:
            data, ctype = _get(f"https://{host}/robots.txt", host)
            if "text/plain" in ctype and b"<html" not in data[:500].lower():
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(data.decode("utf-8", "replace").splitlines())
                robots[host] = rp
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                blocked[host] = f"blocked: HTTP {e.code} from {host} (robots.txt)"
        except Exception:                           # noqa: BLE001 - no robots.txt: nothing is disallowed
            pass
    rp = robots[host]
    return rp is None or rp.can_fetch("*", url)


def fetch(url, data=None, headers=None, opener=None):
    """One polite request (GET, or POST when data is given). Returns (bytes, None) or (None, reason)."""
    host = urllib.parse.urlsplit(url).netloc
    if OFFLINE:
        return None, "offline run"
    if host in blocked:
        return None, blocked[host]
    if not allowed(url):
        return None, f"disallowed by robots.txt of {host}"
    if host in blocked:
        return None, blocked[host]
    try:
        body, _ = _get(url, host, data, headers, opener)
        failures[host] = 0
        return body, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            blocked[host] = f"blocked: HTTP {e.code} from {host}"
            print(f"  {host} answered {e.code}; leaving it alone for the rest of this run")
            return None, blocked[host]
        if e.code < 500:                            # 404 and the like: the host is fine, the item is not there
            failures[host] = 0
            return None, f"HTTP {e.code}"
        why = f"HTTP {e.code}"
    except Exception as e:                          # noqa: BLE001 - report, do not retry
        why = f"{type(e).__name__}: {e}"
    failures[host] = failures.get(host, 0) + 1
    if failures[host] >= 3:
        blocked[host] = f"unreachable: {host} failed 3 times in a row (last: {why})"
        print(f"  {host} keeps failing; leaving it alone for the rest of this run")
    return None, why


# ---------------------------------------------------------------------------------------------- helpers

def plain(s):
    """Upper case without accents, for matching."""
    s = unicodedata.normalize("NFD", s.upper())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def clean(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def slug(s, n=70):
    s = unicodedata.normalize("NFD", urllib.parse.unquote(s))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("°", "").replace("º", "")
    return re.sub(r"[^A-Za-z0-9.-]+", "-", s).strip("-.")[:n].strip("-.") or "x"


def basename(url):
    return unicodedata.normalize("NFC", urllib.parse.unquote(url.split("?")[0].rstrip("/").split("/")[-1]))


def meta_for(url):
    """Hand-checked metadata for a published file: by upload folder + name first, then by name alone."""
    parts = urllib.parse.unquote(url.split("?")[0]).split("/")
    key = slug(re.sub(r"\.(pdf|docx?|odt)$", "", unicodedata.normalize("NFC", parts[-1]), flags=re.I), 90).lower()
    if len(parts) > 3 and re.fullmatch(r"\d{4}", parts[-3]):
        full = f"{parts[-3]}/{parts[-2]}/{key}"
        if full in META:
            return META[full]
    return META.get(key, {})          # (a "YYYY/MM/name" entry never matches by name alone)


def number_in(title):
    m = re.match(r"\W*((?:Oficio )?Circular|Of(?:icio|\.) Ord(?:inario|\.)?|Resoluci[oó]n Exenta|Instructivo Presidencial)"
                 r"\s*N[°º.]?\s*([\d.]+(?:\s?Bis|-A)?)", title, re.I)
    return f"{m.group(1)} {m.group(2)}" if m else ""


def cache_json(name, value=None):
    path = CACHE / name
    if value is not None:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=0), "utf-8")
        return value
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def over_limit():
    files = [p for p in OUT.rglob("*") if p.is_file()]
    return len(files) >= MAX_FILES or sum(p.stat().st_size for p in files) >= MAX_BYTES


def save(url, dest, check, meta, via=""):
    """Download url to dest unless it is there already; record an index row or a not-obtained row."""
    rel = str(dest.relative_to(OUT))
    row = dict(meta, file=rel, source_url=url)
    if not (dest.exists() and dest.stat().st_size > 0):
        if over_limit():
            data, why = None, "size/file limit reached"
        else:
            data, why = fetch(url)
        if data is not None and not check(data):
            why = "not the document (error page or unexpected content returned)"
            if data[:5] == b"%PDF-":
                why = f"the only copy is cut off after {len(data)} bytes (incomplete PDF), not kept"
            data = None
        if data is None:
            missing.append((meta.get("listed_url", url), meta.get("title", ""), meta.get("date", ""), why, current[0]))
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"  saved {rel} ({len(data) // 1024} kB)")
    if via and not row.get("note"):
        row["note"] = via
    rows[rel] = row
    return True


def is_pdf(data):
    return data[:5] == b"%PDF-" and b"%%EOF" in data[-2048:]


# ---------------------------------------------------------------------------------------------- LeyChile

LEY_SEARCH = ("https://nuevo.leychile.cl/servicios/Consulta/listaresultadosimple?cadena={q}&npagina={p}"
              "&itemsporpagina=100&exacta=1&orden=2&tipoviene=1&seleccionado=0&taxonomia=&valor_taxonomia="
              "&o=externa&r=")
LEY_XML = "https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma={id}"
LEY_WEB = "https://www.bcn.cl/leychile/navegar?idNorma={id}"
LEY_QUERIES = ["extranjería", "servicio nacional de migraciones", "departamento de extranjería y migración",
               "migraciones", "migratoria", "refugiados", "reconducción", "subcategorías migratorias",
               "visto consular", "tarjeta de turismo", "regularización migratoria", "permanencia transitoria",
               "residencia temporal", "residencia definitiva", "permanencia definitiva", "inmigrantes"]
LEY_ORG = re.compile(r"^MINISTERIO DEL INTERIOR|^MINISTERIO DE RELACIONES EXTERIORES|^MINISTERIO DE SEGURIDAD"
                     r"|SERVICIO NACIONAL DE MIGRACIONES|EXTRANJERIA Y MIGRACION")
LEY_KW = re.compile(r"EXTRANJER[OA]S?\b|EXTRANJERIA|MIGRA|REFUGI|VISACION|\bVISAS?\b|VISTO|PERMANENCIA (DEFINITIVA|"
                    r"TRANSITORIA|EN EL PAIS)|RESIDENCIA (TEMPORAL|DEFINITIVA|TEMPORARIA)|TURISTA|TARJETA DE TURISMO"
                    r"|EXPULSI|APATRID|ASILO|RECONDUC|DOCUMENTOS? DE VIAJE|EMPADRONAMIENTO|INGRESO AL PAIS")
LEY_TYPES = ("Resoluc", "Circular", "Decreto", "Oficio", "Instruc", "Ordinario", "Carta Circular", "Dictamen",
             "Orden", "OTRO", "Otro")
# staffing, procurement, budget, councils, treaties, individual acts, the regulations themselves,
# and the 2020-21 weekly border-closure decrees
LEY_DROP = re.compile(
    r"COLECTA|SUBROGA|CONVENIO|COMITE|DELEGA|NOMBRA|DESIGNA|LICITACION|CONCURSO|FONDO|PRESUPUEST|PLANTA|DOTACION"
    r"|ESTRUCTURA|ORGANIZACION INTERNA|ASIGNACION|TELETRABAJO|MEJORAMIENTO|HONORARIOS|PROMULGA|RATIFICA|INVERSION"
    r"|CAPITALES|SOCIEDAD CIVIL|REGISTRO DE ORGANIZACIONES|FIRMAR|HORARIO|JORNADA|PRELACION|COMISION|CONSEJO"
    r"|PARTICIPACION CIUDADANA|METAS|SELLO|PROGRAMA|CUENTA PUBLICA|REFUGIO DE CRISTO|FERIADO|TRASPAS|ENCASILLA"
    r"|RENUNCIA|CONVOCATORIA|CUMPLIMIENTO GLOBAL|CODIGO DE ETICA|ACOSO|CIERRE TEMPORAL|DECRETO SUPREMO N. ?102"
    r"|AERONAVES|CIRCOS|EXPULSA |APRUEBA (EL |NUEVO )?REGLAMENTO|PARA CHILENOS|CHILENOS RESIDENTES|EMPRESTITOS"
    r"|ELECCION|VEHICULOS|ACUERDO|PROTOCOLO SOBRE EL ESTATUTO|CONVENCION|TRATADO|EVALUACION|AUTORIZA A "
    r"|HOGAR|ALBERGUE|DECLARA|EMERGENCIA|CATASTROFE|ZONA|SUBSIDIO|VIVIENDA|BONO|VIATICO|COMETIDO|GRADO|DEUDAS"
    r"|TEXTO REFUNDIDO|INMIGRACION LIBRE|MODIFICA DECRETO SUPREMO N. ?837")
LEY_EXTRA = {
    1150575: "Registro Civil resolution on the visa-renewal procedure agreed with the DEM",
    1201131: "travel documents during the 2024 state of catastrophe",
}
LEY_EN = {
    212275: "Authorises the Foreign Ministry to grant multiple-entry visas",
    16310: "Conditions and procedure for setting and paying the fees for immigration acts",
    154517: "Border transit areas for foreign residents, Aysén region",
    142603: "Tourist visa or consular registration of passports for listed nationalities",
    226681: "Consular registration or tourist visa requirement for Norwegian citizens",
    38822: "Entry facilities for foreigners attending the Teatro de las Naciones festival",
    12066: "Fees payable by foreigners for immigration acts",
    231053: "Tourist-card charge for nationals of listed countries",
    1059694: "Amends Decree 605/2004 on the tourist-card charge",
    1073346: "Amends Decree 605/2004 on the tourist-card charge",
    1103864: "Amends Decree 605/2004 on the tourist-card charge",
    1117475: "Consular tourist visa requirement for nationals of Haiti",
    1124596: "Humanitarian plan for orderly return of foreign citizens to their country of origin",
    1130740: "Expired Venezuelan travel documents accepted as travel documents",
    1133025: "Consular tourist visa requirement for nationals of Venezuela",
    1137760: "Consular tourist visa requirement for nationals of Australia",
    1141641: "Fee table for visas and tourist visas granted abroad",
    1145182: "Fee table for visas and tourist visas granted abroad",
    1150575: "Formalises the procedure for renewing visas and permanent residence notified by the DEM (ID cards)",
    1158563: "Approves the regularisation process of transitory article 8 of Law 21.325",
    1173324: "Establishes the migratory subcategories of transitory stay (permanencia transitoria)",
    1176043: "Establishes the migratory subcategories of temporary residence",
    1187023: "Sets the validity periods of the temporary-residence subcategories",
    1188503: "Minimum funds required of holders of transitory stay",
    1189397: "Establishes accepted travel documents under article 24 of Law 21.325",
    1193381: "Orders biometric registration (empadronamiento) of foreigners who entered irregularly",
    1193939: "Amends the biometric registration resolution",
    1199553: "Establishes the National Policy on Migration and Foreigners",
    1196405: "Amends the biometric registration resolution",
    1196406: "Reduces the temporary-residence fee for listed foreigners",
    1196686: "Establishes accepted travel documents under article 24 of Law 21.325",
    1201131: "Qualifies travel documents under article 24 of Law 21.325 during the state of catastrophe",
    1206019: "Approves the protocol of instructions for the reconducción (immediate return) of foreigners",
    1203443: "Establishes accepted travel documents under article 24 of Law 21.325",
    1204103: "Establishes accepted travel documents under article 24 of Law 21.325",
    1207664: "Evidence of stable employment for applicants for definitive residence",
    1206585: "Establishes accepted travel documents under article 24 of Law 21.325",
    1216772: "Prior authorisation or visa for entry and stay of transitory-stay holders of listed nationalities",
    1211388: "Establishes accepted travel documents under article 24 of Law 21.325",
    1220597: "Establishes accepted travel documents under article 24 of Law 21.325",
    1227338: "Approves a new protocol of instructions for the reconducción of foreigners",
    1228260: "Qualifies a Venezuelan-issued instrument as a travel document under article 24",
}


def ley_candidates():
    """Run the searches; return {idNorma: record}. Falls back to the cached result of the last run."""
    found, complete = {}, True
    for q in LEY_QUERIES:
        page = 1
        while page <= 30:
            data, why = fetch(LEY_SEARCH.format(q=urllib.parse.quote(q), p=page))
            if data is None:
                print(f"leychile: search '{q}' page {page} not retrieved ({why})")
                complete = False
                break
            try:
                res = json.loads(data)
                items, total = res[0], int(res[1]["totalitems"])
            except Exception:                       # noqa: BLE001
                print(f"leychile: search '{q}' returned something unexpected")
                complete = False
                break
            for r in items:
                found[str(r["IDNORMA"])] = {k: r.get(k, "") for k in (
                    "IDNORMA", "NORMA", "DESCRIPCION", "NUMERO", "ORGANISMO", "TITULO_NORMA",
                    "FECHA_PROMULGACION", "FECHA_PUBLICACION", "FECHA_DEROGACION")}
            if page * 100 >= total or not items:
                break
            page += 1
        if urllib.parse.urlsplit(LEY_SEARCH).netloc in blocked:
            break
    old = cache_json("leychile-candidates.json") or {}
    if not complete:
        found = dict(old, **found)                  # keep what an earlier run found
    if found:
        cache_json("leychile-candidates.json", found)
    return found or old


def ley_selected(r):
    kind = r["DESCRIPCION"].split(";")[0]
    if int(r["IDNORMA"]) in LEY_EXTRA:
        return True
    if not kind.startswith(LEY_TYPES) or "Decreto Ley" in kind or "Fuerza" in kind:
        return False
    org, title = plain(r["ORGANISMO"]), plain(re.sub(r"\s+", " ", r["TITULO_NORMA"]))
    if not LEY_ORG.search(org) or LEY_DROP.search(title):
        return False
    return bool(LEY_KW.search(title)) or "MIGRACIONES" in org or "EXTRANJERIA" in org


def leychile():
    cands = cache_json("leychile-candidates.json") if OFFLINE else ley_candidates()
    chosen = sorted((r for r in (cands or {}).values() if ley_selected(r)),
                    key=lambda r: (r["FECHA_PROMULGACION"], int(r["IDNORMA"])))
    print(f"leychile: {len(cands or {})} search results, {len(chosen)} selected")
    for r in chosen:
        nid = int(r["IDNORMA"])
        norma = r["NORMA"].split(";")[0].strip()
        date = r["FECHA_PROMULGACION"] or ""
        title = re.sub(r"\s+", " ", r["TITULO_NORMA"]).strip()
        body = "; ".join(dict.fromkeys(x.strip().title() for x in r["ORGANISMO"].split(";")))
        body = re.sub(r"\b(Del|De|Y|E|La)\b", lambda m: m.group(1).lower(), body)
        note = f"LeyChile XML, consolidated text; web view {LEY_WEB.format(id=nid)}"
        if r.get("FECHA_DEROGACION"):
            note += f"; repealed {r['FECHA_DEROGACION']}"
        meta = {"title": title, "date": date, "issuing_body": body, "act_number": norma,
                "title_en": LEY_EN.get(nid, ""), "note": note}
        dest = OUT / "leychile" / f"{date or '0000-00-00'}_{slug(norma.lower(), 40)}_{nid}.xml"
        save(LEY_XML.format(id=nid), dest,
             lambda d, n=nid: d[:5] == b"<?xml" and f'normaId="{n}"'.encode() in d[:1000] and b"</Norma>" in d[-200:],
             meta)


# ---------------------------------------------------------------------------------------------- DEM (Wayback)

CDX = "https://web.archive.org/cdx/search/cdx?"
WB = "https://web.archive.org/web/{ts}id_/{url}"
DEM_PAGES = ["extranjeria.gob.cl/legislacion-migratoria/", "extranjeria.gob.cl/leyes-migratorias/"]
DEM_NAME = re.compile(r"circ|oficio|of\.?[-_ ]?ord|instructivo|inst[-._ ]*pres|protocolo|resoluci|resol\.", re.I)
DEM_TITLE = re.compile(r"^\W*(circular|oficio|of\.|instructivo|protocolo|resoluci)", re.I)
# laws, decrees, the competitive fund, the "Sello Migrante" municipal label, press and forms
DEM_SKIP = re.compile(r"sello|^(pd|te?|rt|v)\d|fondo|bases|convocatoria|concurso|rex(declara|rectifica)|ley[-_]|reglamento|dto-|decreto"
                      r"|trafico|rectifica-res|formulario|solicitud|requisitos|estad|anuario|memoria|glosario|gu[ií]a"
                      r"|diario-oficial-14|siregad|antofagasta|instrucciones-", re.I)
DEM_BODY = "Ministerio del Interior y Seguridad Pública; Subsecretaría del Interior; Departamento de Extranjería y Migración"


def cdx(query, cache_name):
    """A CDX query as a list of rows; the last good answer is cached and reused when the archive refuses."""
    data, why = fetch(CDX + query)
    if data is not None and not data.lstrip().startswith(b"<"):
        rows_ = [line.split(" ") for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
        return cache_json(cache_name, rows_)
    if not OFFLINE:
        print(f"dem: archive index query not answered ({why or 'error page'}); using cached copy if any")
    return cache_json(cache_name) or []


def dem_listing_snapshots():
    """(timestamp, original url) of the listing pages: the last distinct capture of each quarter."""
    picks = {}
    for page in DEM_PAGES:
        q = f"url={page}&filter=statuscode:200&fl=timestamp,original,digest&collapse=digest"
        for ts, orig, _ in cdx(q, "dem-" + slug(page) + ".cdx.json"):
            quarter = (page, ts[:4], (int(ts[4:6]) - 1) // 3)
            picks[quarter] = (ts, orig)
    return sorted(picks.values())


def dem_links(markup, base):
    """(absolute url, title) for document links in a listing page; the title is the line above 'Ver'."""
    out = []
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", markup, flags=re.S)
    parts = re.split(r'(<a\b[^>]*href="[^"]*"[^>]*>.*?</a>)', text, flags=re.S)
    for i in range(1, len(parts), 2):
        m = re.match(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>', parts[i], flags=re.S)
        href = re.sub(r"^(https?:)?//web\.archive\.org/web/\d+[a-z_]*/", "", html.unescape(m.group(1)))
        if not re.search(r"\.pdf($|\?)", href, re.I):
            continue
        before = [clean(x) for x in re.split(r"<(?:br|/p|/div|/li|/h\d|/tr|/td)[^>]*>", parts[i - 1])]
        before = [x for x in before if len(x) > 8 and not re.fullmatch(r"[>\s]*Ver\s*", x)]
        title = re.sub(r"[>\s]*Ver\s*$", "", before[-1]).strip(' "') if before else ""
        if len(title) < 12 or len(title) > 400:
            title = clean(m.group(2))
        out.append((urllib.parse.urljoin(base, href), title))
    return out


def dem():
    docs = {}                                       # basename -> {url, ts, title}
    for ts, orig in dem_listing_snapshots():
        cached = CACHE / f"dem-{slug(orig.split('//', 1)[1].replace(':80', ''))}-{ts}.html"
        if not cached.exists():
            data, why = fetch(WB.format(ts=ts, url=orig))
            if data is None or b"<html" not in data[:3000].lower():
                print(f"dem: listing capture {ts} not retrieved ({why})")
                continue
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        base = "https://www.extranjeria.gob.cl/" + orig.split("/", 3)[3]
        for url, title in dem_links(cached.read_text("utf-8", "replace"), base):
            name = basename(url)
            if "extranjeria.gob.cl" not in url or DEM_SKIP.search(name) or name in SKIP_FILES:
                continue
            if not (DEM_NAME.search(name) or DEM_TITLE.search(title)):
                continue
            d = docs.setdefault(dem_key(url), {"url": url, "ts": "2", "title": title, "listed": ts})
            if ts >= d["listed"]:                   # the newest listing has the best wording
                d.update(url=url, title=title or d["title"], listed=ts)
    q = ("url=extranjeria.gob.cl&matchType=domain&filter=mimetype:application/pdf&filter=statuscode:200"
         "&collapse=urlkey&fl=timestamp,original&limit=20000")
    for ts, orig in cdx(q, "dem-pdfs.cdx.json"):
        name, key = basename(orig), dem_key(orig)
        if key in docs:
            docs[key]["ts"], docs[key]["url"] = ts, orig       # an exact capture exists: use it
        elif DEM_NAME.search(name) and not DEM_SKIP.search(name) and "?" not in orig and name not in SKIP_FILES:
            docs[key] = {"url": orig, "ts": ts, "title": ""}
    print(f"dem: {len(docs)} documents listed")
    same = cache_json("dem-duplicates.json") or {}  # listed url -> file it duplicates
    gone = cache_json("dem-unavailable.json") or {}  # listed url -> why the archive cannot supply it
    # (delete cl/listings/dem-unavailable.json to make the script ask the archive for those again)
    digests = {hashlib.sha256(p.read_bytes()).hexdigest(): p.name for p in (OUT / "dem").glob("*.pdf")}
    for key, d in sorted(docs.items()):
        name = basename(d["url"])
        if d["url"] in same and (OUT / "dem" / same[d["url"]]).exists():
            continue
        m = meta_for(d["url"])
        up = re.search(r"/media/(\d{4})/(\d\d)/", d["url"])
        date = m.get("date") or (f"{up.group(1)}-{up.group(2)}" if up else "")
        title = m.get("title") or d["title"] or re.sub(r"[-_]+", " ", re.sub(r"\.pdf$", "", name, flags=re.I))
        note = "via Wayback Machine (extranjeria.gob.cl is closed)"
        if not m.get("date") and up:
            note += "; date is the month the file was uploaded, not the date of the act"
        num = m.get("num") or number_in(title)
        meta = {"title": title, "date": date, "issuing_body": m.get("body", DEM_BODY),
                "act_number": num, "title_en": m.get("en", ""), "note": note, "listed_url": d["url"]}
        stem = "_".join(x for x in (date, slug(num, 40).lower() if num else "",
                                    slug(re.sub(r"\.pdf$", "", name, flags=re.I), 60)) if x)
        dest = OUT / "dem" / (stem + ".pdf")
        fresh = not dest.exists()
        if fresh and d["url"] in gone:
            missing.append((d["url"], title, date, gone[d["url"]], "dem"))
            continue
        ok = save(WB.format(ts=d["ts"], url=d["url"]), dest, is_pdf, meta)
        if not ok and missing[-1][3].startswith(("the only copy", "HTTP 404", "not the document")):
            why = missing[-1][3].replace("HTTP 404", "no copy in the Wayback Machine (HTTP 404)").replace(
                "not the document (error page or unexpected content returned)",
                "no PDF copy in the Wayback Machine (the address was archived only as an error or redirect page)")
            gone[d["url"]] = why
            missing[-1] = missing[-1][:3] + (why, "dem")
        if ok and fresh:
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            if digest in digests:                   # the same file published twice under two addresses
                same[d["url"]] = digests[digest]
                dest.unlink()
                del rows[str(dest.relative_to(OUT))]
                print(f"  ... identical to {digests[digest]}; second copy not kept")
            else:
                digests[digest] = dest.name
    cache_json("dem-duplicates.json", same)
    cache_json("dem-unavailable.json", gone)


def dem_key(url):
    """Upload folder + file name, so that 2019/10/Circular-N°29.pdf and 2020/12/Circular-N°29.pdf stay apart."""
    path = unicodedata.normalize("NFC", urllib.parse.unquote(url.split("?")[0]))
    return "/".join(path.split("/")[-3:]).replace(":80", "")


# ---------------------------------------------------------------------------------------------- SERMIG site

SM = "https://serviciomigraciones.cl"
SM_SITEMAPS = ["page", "guia", "post"]
SM_NAME = re.compile(r"ofic|of[-_. ]?ord|circular|instruc|instructivo|res[-._ ]?ex|resoluci|protocolo|manual"
                     r"|criterio|lineamiento|^\d{4,6}\.pdf$", re.I)
SM_SKIP = re.compile(r"cosoc|ross|org[-_]|organiz|nomina|candidat|inscrip|presupuesto|ppto|acta|programa|sesion"
                     r"|particip|bases|consejo|electoral|mesa|comite|cuenta|guia|formulario|encuesta|resumen"
                     r"|resultado|presentacion|fallo|-dt-|tlc|mexico|canada", re.I)
SM_SKIP_PAGE = re.compile(r"/(participacion-ciudadana|quienes-somos|estudios-migratorios|sello-migrante"
                          r"|compromiso-migrante|en)/")
SM_BODY = "Ministerio del Interior y Seguridad Pública; Servicio Nacional de Migraciones"


def sm_doc_links(markup):
    a = markup.find('data-elementor-type="wp-p')
    b = markup.find('data-elementor-type="footer"')
    body = markup[a if a > 0 else 0: b if b > 0 else None]
    out = []
    for href, text in re.findall(r'<a\b[^>]*href="([^"]+\.(?:pdf|docx?|odt))"[^>]*>(.*?)</a>', body, flags=re.S | re.I):
        out.append([urllib.parse.urljoin(SM + "/", html.unescape(href)), clean(text)])
    return out


def sm_scan():
    """{page url: {"lastmod":..., "docs":[[url, link text], ...]}}, refreshed where the sitemap date changed."""
    pages = cache_json("sermig-pages.json") or {}
    if OFFLINE:
        return pages
    for name in SM_SITEMAPS:
        data, why = fetch(f"{SM}/{name}-sitemap.xml")
        if data is None:
            print(f"sermig: {name} sitemap not retrieved ({why}); using cached page list")
            continue
        for loc, lastmod in re.findall(r"<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?",
                                       data.decode("utf-8", "replace")):
            if "/wp-content/" in loc or "/en/" in loc:
                continue
            if loc in pages and pages[loc].get("lastmod") == lastmod:
                continue
            page, why = fetch(loc)
            if page is None:
                print(f"sermig: page not retrieved ({why}): {loc}")
                if urllib.parse.urlsplit(SM).netloc in blocked:
                    cache_json("sermig-pages.json", pages)
                    return pages
                continue
            pages[loc] = {"lastmod": lastmod, "docs": sm_doc_links(page.decode("utf-8", "replace"))}
        cache_json("sermig-pages.json", pages)
    return pages


def sermig():
    pages = sm_scan()
    docs = {}
    for page, info in sorted(pages.items()):
        if SM_SKIP_PAGE.search(page):
            continue
        for url, text in info["docs"]:
            name = basename(url)
            if "serviciomigraciones.cl" not in url or name in docs or name in SKIP_FILES:
                continue
            if meta_for(url) or (SM_NAME.search(name) and not SM_SKIP.search(name)):
                docs[name] = (url.replace("http://", "https://").replace(".cl//", ".cl/"), text, page)
    print(f"sermig: {len(pages)} pages scanned, {len(docs)} documents listed")
    for name, (url, text, page) in sorted(docs.items()):
        m = meta_for(url)
        up = re.search(r"/uploads/(\d{4})/(\d\d)/", url)
        date = m.get("date") or (f"{up.group(1)}-{up.group(2)}" if up else "")
        note = f"linked from {page}"
        if not m.get("date") and up:
            note += "; date is the month the file was uploaded, not the date of the act"
        title = m.get("title") or re.sub(r"^Abrir\s+", "", text) or name
        num = m.get("num") or number_in(title)
        meta = {"title": title, "date": date, "issuing_body": m.get("body", SM_BODY),
                "act_number": num, "title_en": m.get("en", ""), "note": note}
        stem = "_".join(x for x in (date, slug(num, 40).lower() if num else "",
                                    slug(re.sub(r"\.(pdf|docx?|odt)$", "", name, flags=re.I), 60)) if x)
        ext = "." + name.rsplit(".", 1)[-1].lower()
        ok = is_pdf if ext == ".pdf" else (lambda d: d[:4] in (b"PK\x03\x04", b"\xd0\xcf\x11\xe0"))
        save(url, OUT / "sermig" / (stem + ext), ok, meta)


# ---------------------------------------------------------------------------------------------- Transparencia Activa

PT = "https://www.portaltransparencia.cl/PortalPdT/directorio-de-organismos-regulados/?org=AB099"
PT_PATHS = {"marco-normativo": ["Marco Normativo"],
            "circulares": ["Actos y resoluciones con efectos sobre terceros", "Circulares"]}
PT_KEEP = re.compile(r"circular|resoluci|oficio|protocolo", re.I)   # laws, decrees, instructivos: other sources
PT_DROP = re.compile(r"LOBBY|COBRANZA|DELEGA FACULTAD|FACULTAD DE FIRMAR|REPRESENTACION JUDICIAL|CONFIDENCIALIDAD")
NO_SCRIPT = {   # hosts this script must not fetch documents from, and why
    "drive.google.com": "robots.txt of drive.google.com allows the viewer page but not the download address",
    "www.interior.gob.cl": "www.interior.gob.cl/transparencia answers scripts with a JavaScript bot check",
}


def pt_table(path):
    """Open the Service's page on the portal and click through path; return the table as a list of dicts."""
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    data, why = fetch(PT, opener=opener)
    if data is None:
        return None, why
    page = data.decode("utf-8", "replace")
    enc = re.search(r'name="javax.faces.encodedURL" value="([^"]+)"', page)
    state = re.search(r'name="javax.faces.ViewState"[^>]*value="([^"]+)"', page)
    if not enc or not state:
        return None, "portal page has changed (no form found)"
    enc, state = html.unescape(enc.group(1)), html.unescape(state.group(1))
    ajax = {"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    for label in path:
        link = re.search(r'<a id="([^"]+)"[^>]*onclick="[^"]*PrimeFaces\.ab[^"]*"[^>]*>\s*' + re.escape(label) + r"\s*</a>", page)
        if not link:
            return None, f"portal page has changed (no link '{label}')"
        src = link.group(1)
        form = src.split(":")[0] + ":formInfo"
        fields = [(form, form), ("javax.faces.encodedURL", enc)]
        fields += re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]*_scrollState)"[^>]*value="([^"]*)"', page)
        fields += [("javax.faces.ViewState", state), ("javax.faces.partial.ajax", "true"),
                   ("javax.faces.source", src), ("javax.faces.partial.execute", "@all"),
                   ("javax.faces.partial.render", form), (src, src)]
        data, why = fetch(enc, urllib.parse.urlencode(fields).encode(), ajax, opener)
        if data is None:
            return None, why
        page = data.decode("utf-8", "replace")
        new = re.search(r'<update id="[^"]*javax.faces.ViewState[^"]*"><!\[CDATA\[(.*?)\]\]>', page)
        state = new.group(1) if new else state
    heads = [clean(h) for h in re.findall(r"<th\b[^>]*>(.*?)</th>", page, flags=re.S)]
    table = []
    for tr in re.findall(r'<tr data-ri="\d+"[^>]*>(.*?)</tr>', page, flags=re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr, flags=re.S)
        row = {h: clean(c) for h, c in zip(heads, cells)}
        href = re.search(r'href="([^"]+)"', tr)
        row["link"] = html.unescape(href.group(1)) if href else ""
        table.append(row)
    return (table, None) if table else (None, "portal answered without a table")


def pt_field(row, *starts):
    for k, v in row.items():
        if plain(k).startswith(tuple(plain(s) for s in starts)):
            return v
    return ""


def held_in_leychile():
    """(number, date) of the acts already saved from LeyChile, read from this run and from index.tsv."""
    held = {(re.sub(r"\D", "", r.get("act_number", "")), r.get("date", "")) for r in rows.values()
            if r.get("file", "").startswith("leychile/")}
    index = OUT / "index.tsv"
    if index.exists():
        for line in index.read_text("utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) > 5 and c[0].startswith("leychile/"):
                held.add((re.sub(r"\D", "", c[5]), c[2]))
    return held


def transparencia():
    seen, held = set(), held_in_leychile()
    for name, path in PT_PATHS.items():
        cache = f"transparencia-{name}.json"
        table, why = (None, "offline run") if OFFLINE else pt_table(path)
        if table is None:
            if not OFFLINE:
                print(f"transparencia: list '{' > '.join(path)}' not retrieved ({why}); using cached copy if any")
            table = cache_json(cache) or []
        else:
            cache_json(cache, table)
        print(f"transparencia: {len(table)} entries under {' > '.join(path)}")
        for row in table:
            kind = pt_field(row, "Tipo de norma", "Tipo de acto")
            num = pt_field(row, "Número norma", "Número del acto", "Numero")
            title = pt_field(row, "Breve descripción", "Denominación norma")
            when = pt_field(row, "Fecha promulgación") or pt_field(row, "Fecha")
            m = re.fullmatch(r"(\d\d)/(\d\d)/(\d{4})", when)
            date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""
            link = row.get("link", "")
            host = urllib.parse.urlsplit(link).netloc
            ident = (plain(kind), num.lstrip("0"), date)
            if not PT_KEEP.search(kind) or PT_DROP.search(plain(title)) or not link or ident in seen:
                continue
            if "bcn.cl" in host or "leychile" in host or (re.sub(r"\D", "", num), date) in held:
                continue                                    # the leychile source has these
            seen.add(ident)
            act = f"{kind} {num}".strip()
            dest = OUT / "transparencia" / f"{date}_{slug(act, 40).lower()}.pdf"
            meta = {"title": title, "date": date, "issuing_body": SM_BODY, "act_number": act, "title_en": "",
                    "note": f"listed on portaltransparencia.cl ({' > '.join(path)}); saved by hand from {link}"}
            if host in NO_SCRIPT and not dest.exists():
                missing.append((link, f"{act}: {title}", date,
                                f"{NO_SCRIPT[host]}; open the link in a browser and save the PDF as cl/{dest.relative_to(OUT)}",
                                "transparencia"))
            else:
                save(link, dest, is_pdf, meta)


# ---------------------------------------------------------------------------------------------- metadata
# Date, number and title read from the documents themselves (most are scans). Keys are the published
# file name without extension, lower case, without accents or the degree sign; "YYYY/MM/name" where two
# different documents were published under the same name.
PRES = "Presidencia de la República"
SUBINT = "Ministerio del Interior y Seguridad Pública; Subsecretaría del Interior"
META = {
    # --- Departamento de Extranjería y Migración (Wayback copies)
    "oficio-circular-26465-acuerdo-mercosur-diciembre-2009": dict(
        date="2009-12-04", num="Oficio Circular 26465", body=SUBINT,
        title="Instruye sobre aplicación del Acuerdo sobre Residencia de los Estados Partes del MERCOSUR, Bolivia y Chile",
        en="Instructs on applying the MERCOSUR, Bolivia and Chile residence agreement"),
    "inst-presidencial-n-9": dict(
        date="2008-09-02", num="Instructivo Presidencial 9", body=PRES,
        title="Imparte instrucciones sobre la Política Nacional Migratoria",
        en="Presidential instruction on the national migration policy"),
    "inst.-pres-n5": dict(
        date="2015-11-06", num="Instructivo Presidencial 5", body=PRES,
        title="Lineamientos e instrucciones para la Política Nacional Migratoria",
        en="Presidential guidelines and instructions for the national migration policy"),
    "circular-n13": dict(
        date="2017-06-19", num="Oficio Circular 13",
        title="Valores actualizados de sanciones pecuniarias y pago de derechos para el segundo semestre de 2017",
        en="Updated fines and fees for the second half of 2017"),
    "circular-16-de-2017-visacion-temporaria-nna": dict(
        date="2017-07-26", num="Circular 16",
        title="Instruye sobre visación temporaria para niños, niñas y adolescentes",
        en="Instructs on temporary visas for children and adolescents"),
    "circular-n30": dict(
        date="2017-12-27", num="Oficio Circular 30",
        title="Valores actualizados de sanciones pecuniarias y pago de derechos para el año 2018",
        en="Updated fines and fees for 2018"),
    "2018/08/circular-n14": dict(
        date="2018-08-01", num="Circular 14",
        title="Instruye sobre otorgamiento de Visado de Orientación Nacional",
        en="Instructs on granting the 'national orientation' visa"),
    "circular-n15": dict(
        date="2018-08-03", num="Circular 15",
        title="Establece normas de atención de público en las sucursales del Departamento de Extranjería y Migración",
        en="Rules for attending the public at the Department's offices"),
    "circular-n15-a": dict(
        date="2018-11-19", num="Circular 15-A",
        title="Complementa Circular N° 15, de 3 de agosto de 2018, que establece normas de atención de público",
        en="Supplements Circular 15 on attending the public"),
    "circular-n11": dict(
        date="2019-04-09", num="Circular 11",
        title="Ingreso digital de solicitudes de Permisos de Permanencia Definitiva",
        en="Online filing of permanent-residence applications"),
    "2019/05/circular-n14": dict(
        date="2019-04-29", num="Circular 14",
        title="Ingreso digital de solicitudes de Duplicado del Certificado de Permanencia Definitiva",
        en="Online filing of requests for a duplicate permanent-residence certificate"),
    "circular-n18": dict(
        date="2019-05-30", num="Circular 18",
        title="Solicitud de permiso de trabajo, en calidad de turista, para extranjeros artistas y deportistas profesionales",
        en="Work permits as tourists for foreign artists and professional athletes"),
    "circular-n29-bis": dict(
        date="2019-10-28", num="Circular 29 Bis",
        title="Modifica y complementa Circular N° 29, de 1 de octubre de 2019, y dispone nuevo procedimiento que establece medida para facilitar la salida del país de extranjeros que se encuentren tramitando permisos de residencia",
        en="Amends and supplements Circular 29 on departure of foreigners with pending residence applications"),
    "circular-n4": dict(
        date="2020-02-04", num="Circular 4",
        title="Establece procedimiento aplicable a extranjeros que tengan o soliciten permisos de residencia durante estado de latencia vigente en el territorio especial de Rapa Nui",
        en="Procedure for foreigners holding or seeking residence permits during the 'latency' state in Rapa Nui"),
    "circular-n23": dict(
        date="2019-08-02", num="Circular 23",
        title="Ingreso digital de solicitudes de modificación y/o rectificación de datos contenidos en el Certificado de Permanencia Definitiva",
        en="Online filing of requests to amend or correct the permanent-residence certificate"),
    "circular-n24": dict(
        date="2019-08-02", num="Circular 24",
        title="Ingreso digital de solicitudes de prórroga de Visa Temporaria Mercosur y Responsabilidad Democrática",
        en="Online filing of extensions of Mercosur and 'democratic responsibility' temporary visas"),
    "circular-n25": dict(
        date="2019-08-05", num="Circular 25", title="Certificado digital de Permanencia Definitiva",
        en="Digital permanent-residence certificate"),
    "2019/10/circular-n29": dict(
        date="2019-10-01", num="Circular 29",
        title="Deja sin efecto Circular N° 9, de 3 de abril de 2019, y dispone medida para facilitar la salida del país de extranjeros que se encuentren tramitando permisos de residencia",
        en="Revokes Circular 9 and eases departure of foreigners with pending residence applications"),
    "circular-n23bis": dict(
        date="2019-10-11", num="Circular 23 Bis", title="Modifica Circular N° 23, de 2 de agosto de 2019, en la parte que indica",
        en="Amends Circular 23"),
    "circular-n27": dict(
        date="2020-03-20", num="Circular 27", body=SUBINT,
        title="Establece certificado electrónico provisorio de otorgamiento de visaciones de residencia",
        en="Creates the provisional electronic certificate of grant of a residence visa"),
    "circular-8": dict(
        date="2020-03-25", num="Circular 8",
        title="Precisa sentido y alcance de Circular N° 27, de 20 de marzo de 2020, de la Subsecretaría del Interior",
        en="Clarifies the meaning and scope of Circular 27"),
    "protocolo-casos-sociales": dict(
        date="2020-06-03", num="Oficio Ordinario 13525", title="Actualización Protocolo de Casos Sociales",
        en="Updated protocol for social (hardship) cases"),
    "resolucion-exenta-n-2933": dict(
        date="2020-06-12", num="Resolución Exenta 2933", body=SUBINT,
        title="Dispone medida provisional de extensión del plazo contemplado en el artículo 31 de la Ley N° 19.880, en los casos que indica, producto de la emergencia sanitaria por brote de COVID-19",
        en="Provisional extension of the time limit of article 31 of Law 19.880 during the COVID-19 emergency"),
    "circular-n-14": dict(
        date="2020-06-18", num="Circular 14",
        title="Imparte instrucciones para el trámite de solicitud de permanencia definitiva, en particular para los certificados de antecedentes penales del país de origen, en virtud de la crisis sanitaria",
        en="Instructions on permanent-residence applications: home-country criminal record certificates during the pandemic"),
    "circular-28": dict(
        date="2020-11-27", num="Circular 28", title="Actualiza procedimiento para otorgamiento del Título de Residencia",
        en="Updates the procedure for issuing the residence title"),
    "interior-resol.-1769": dict(
        date="2021-04-20", num="Resolución Exenta 1769", body=SUBINT,
        title="Aprueba proceso de regularización contemplado en el artículo octavo transitorio de la Ley N° 21.325 (copia del Diario Oficial)",
        en="Approves the regularisation process of transitory article 8 of Law 21.325 (Official Gazette copy)"),
    # --- Servicio Nacional de Migraciones website
    "129194": dict(
        date="2020-07-03", num="Resolución Exenta 129194", body=SUBINT,
        title="Fija tabla de valores de derechos por visaciones de residencia otorgadas en Chile, por nacionalidad",
        en="Fee table for residence visas granted in Chile, by nationality"),
    "oficio-17379-20-04-2022-entrada-en-vigencia-de-pr": dict(
        date="2022-04-20", num="Oficio 17379",
        title="Comunica al Servicio de Registro Civil la fecha de entrada en vigencia de los permisos de Residencia Temporal y Residencia Definitiva",
        en="Tells the Civil Registry when temporary and definitive residence permits take effect"),
    "oficio-19220-documentos-para-solicitar-cedula": dict(
        date="2022-04-28", num="Oficio 19220", title="Comunica los documentos para solicitar Cédula de Identidad",
        en="Documents needed to apply for an identity card"),
    "oficio-23268-de-fecha-10-05-2022": dict(
        date="2022-05-10", num="Oficio 23268",
        title="Comunica nuevo formato de notificación del otorgamiento de la Residencia Definitiva, mediante correo electrónico",
        en="New e-mail notification format for grants of definitive residence"),
    "oficio-n31133-2022-a-srcei": dict(
        date="2022-06-08", num="Oficio 31133", title="Complementa los Oficios N° 17.379 y N° 19.220",
        en="Supplements Oficios 17379 and 19220"),
    "40626": dict(
        date="2022-07-15", num="Oficio 40626",
        title="Informa cómputo del plazo dispuesto en el artículo 43 de la Ley N° 21.325, para solicitud de cédula de identidad de residentes temporales y definitivos",
        en="How the article 43 time limit for residents' identity-card applications is counted"),
    "48351": dict(
        date="2022-08-19", num="Oficio 48351",
        title="Adjunta muestras de Resoluciones Exentas mencionadas en Oficio N° 17.379 y en Oficio N° 23.268",
        en="Sample exempt resolutions referred to in Oficios 17379 and 23268"),
    "of-ord-67130-comision-para-el-mercado-financiero": dict(
        date="2022-11-07", num="Oficio Ordinario 67130",
        title="Solicita a la Comisión para el Mercado Financiero impartir instrucción para el cumplimiento del artículo 43, inciso final, de la Ley N° 21.325 (vigencia de la cédula de identidad) respecto de bancos, instituciones financieras y compañías de seguro",
        en="Asks the financial regulator to instruct banks and insurers on article 43 (validity of identity cards)"),
    "of-ord-80585-corte-suprema-vigencia-cedula-identidad": dict(
        date="2022-12-29", num="Oficio Ordinario 80585",
        title="Sobre vigencia de la Cédula de Identidad: solicita a la Corte Suprema impartir instrucción respecto de notarios, conservadores y archiveros (artículo 43, inciso final, Ley N° 21.325)",
        en="Asks the Supreme Court to instruct notaries and registrars on the validity of identity cards"),
    "of-ord-80586-sup-de-salud-vigencia-cedula-identidad": dict(
        date="2022-12-29", num="Oficio Ordinario 80586",
        title="Sobre vigencia de la Cédula de Identidad: solicita a la Superintendencia de Salud impartir instrucción respecto de prestadores, seguros y fondos de salud (artículo 43, inciso final, Ley N° 21.325)",
        en="Asks the health regulator to instruct providers and insurers on the validity of identity cards"),
    "resexenta-25425-proceso-empadronamiento-biometrico": dict(
        date="2023-05-31", num="Resolución Exenta 25425",
        title="Dispone proceso de empadronamiento biométrico de personas extranjeras que hayan ingresado al país por paso no habilitado o eludiendo el control migratorio",
        en="Orders biometric registration of foreigners who entered irregularly"),
    "resexenta-27896-proceso-empadronamiento-biometrico": dict(
        date="2023-06-13", num="Resolución Exenta 27896",
        title="Modifica resolución exenta que dispone proceso de empadronamiento biométrico de personas extranjeras en la parte que indica",
        en="Amends the biometric registration resolution"),
}

# Published file names that are out of scope although their name matches (applicant leaflets, forms).
SKIP_FILES = {"INSTRUCTIVO-antofagasta-3-22.pdf", "INSTRUCCIONES-PRAS-2018-2019.pdf"}

# Known to exist but not published anywhere this script may fetch (kept in not-obtained.tsv).
KNOWN_GAPS = [
    ("", "DEM Circular N° 18.757 (visa processing rules cited as background by DEM Circular 8 of 2020)", "2008-09-26",
     "cited in a saved circular; never found published", "cited"),
    ("", "DEM Circular N° 10.218 (cited as background by DEM Circular 8 of 2020)", "2012-05-10",
     "cited in a saved circular; never found published", "cited"),
    ("", "DEM Oficio Circular N° 20.842 (fines and fees; cited by Oficio Circular 30 of 2017)", "2012",
     "cited in a saved circular; never found published", "cited"),
    ("", "DEM Oficio Circular N° 07277 (residence title; cited by Circular 28 of 2020)", "2000-06-06",
     "cited in a saved circular; never found published", "cited"),
    ("https://www.revistasur.cl/revistasur.cl/wp-content/uploads/2020/06/Oficio-de-Extranjería-Nro-12292-del-20-5-2020.pdf",
     "DEM Oficio N° 12292: directrices para vuelos humanitarios", "2020-05-20",
     "only a copy on a third-party (press) site was found, not an official source; not fetched", "cited"),
]


# ---------------------------------------------------------------------------------------------- output

def write_outputs(ran):
    index = OUT / "index.tsv"
    old = {}
    if index.exists():
        lines = index.read_text("utf-8").splitlines()
        cols = lines[0].split("\t") if lines else []
        for line in lines[1:]:
            r = dict(zip(cols, line.split("\t")))
            if r.get("file"):
                old[r["file"]] = r
    for rel, r in old.items():                      # keep rows of sources not refreshed in this run
        if rel not in rows and (OUT / rel).exists() and rel.split("/")[0] not in ran:
            rows[rel] = r
    for p in sorted(OUT.rglob("*")):                # a file added by hand gets a row too
        rel = str(p.relative_to(OUT))
        if p.is_file() and rel.split("/")[0] in ("leychile", "dem", "sermig", "transparencia") and rel not in rows:
            rows[rel] = old.get(rel) or {"file": rel, "title": p.stem, "note": "on disk; not listed in this run"}

    def tsv(c):
        return re.sub(r"[\t\r\n]+", " ", str(c or "")).strip()
    ordered = sorted(rows.values(), key=lambda r: (r["file"].split("/")[0], r.get("date", ""), r["file"]))
    with open(index, "w", encoding="utf-8") as f:
        f.write("\t".join(INDEX_COLS) + "\n")
        for r in ordered:
            f.write("\t".join(tsv(r.get(c)) for c in INDEX_COLS) + "\n")
    gaps = OUT / "not-obtained.tsv"
    kept, before = [], {}                           # rows of sources not run this time stay as they were
    if gaps.exists():
        for line in gaps.read_text("utf-8").splitlines()[1:]:
            c = line.split("\t")
            before[c[0]] = c[3] if len(c) > 3 else ""
            if len(c) == 5 and c[4] in ("leychile", "dem", "sermig", "transparencia") and c[4] not in ran:
                kept.append(c)
    with open(gaps, "w", encoding="utf-8") as f:
        f.write("source_url\ttitle\tdate\treason\tsource\n")
        for i, row in enumerate(missing):           # an offline run cannot know better than the last real one
            if row[3] == "offline run" and before.get(row[0]):
                missing[i] = row[:3] + (before[row[0]],) + row[4:]
        for row in missing + kept + KNOWN_GAPS:
            f.write("\t".join(tsv(c) for c in row) + "\n")
    print(f"cl: {len(ordered)} files indexed; {len(missing)} listed but not fetched in this run; "
          f"{len(KNOWN_GAPS)} known gaps")
    for host, why in blocked.items():
        print(f"cl: {why}")


def main():
    OUT.mkdir(exist_ok=True)
    sources = {"leychile": leychile, "dem": dem, "sermig": sermig, "transparencia": transparencia}
    ran = [a for a in sys.argv[1:] if a in sources] or list(sources)
    for name in ran:
        current[0] = name
        sources[name]()
    write_outputs(ran)


if __name__ == "__main__":
    main()

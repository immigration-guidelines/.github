#!/usr/bin/env python3
"""Argentina: what the Dirección Nacional de Migraciones (DNM) and the refugee
commission (CONARE) publish for the officials who decide cases.

    python3 download_ar.py                      # fetch what is missing, rebuild ar/index.tsv
    python3 download_ar.py --refresh-catalogue  # also rebuild ar/catalogue.tsv from the open dataset
    python3 download_ar.py --no-fallback        # gazette only (skip argentina.gob.ar / InfoLEG)
    python3 download_ar.py --no-gazette         # skip the gazette (it rate-limits: HTTP 429 after ~60 requests at 1.5 s)
    python3 download_ar.py --no-gazette --wayback-only   # texts only from the Internet Archive's copies of InfoLEG
    python3 download_ar.py --no-wayback         # never ask the Internet Archive
    python3 download_ar.py --refresh-catalogue --dataset-zip=FILE   # use a copy of the dataset already on disk

Argentina has no published procedures manual. Everything an officer works from is
issued as a numbered act (disposición of the DNM, resolución of CONARE) in the
Boletín Oficial; the real guidance (instructivos, protocolos, procedimientos,
pautas) exists only as annexes to such acts. See ar/NOTES.txt.

How it works
  1. ar/catalogue.tsv lists the acts wanted. It is built from the Justice
     Ministry's open dataset "Base InfoLEG de normativa nacional"
     (datos.jus.gob.ar): acts of the DNM / CONARE for which InfoLEG holds a text,
     minus staffing, procurement, fees, office openings, notifications and the
     like. Rows are marked "guidance" when the act approves an instructivo,
     protocolo, procedimiento, pautas or instrucciones, otherwise "procedural act".
  2. For each act the official gazette is asked first (www.boletinoficial.gob.ar,
     first section): the notice as PDF plus every annex as PDF.
  3. If the gazette does not have it, the consolidated-law site is tried
     (www.argentina.gob.ar/normativa, HTML, 10 s between requests as its
     robots.txt asks), then InfoLEG itself (servicios.infoleg.gob.ar, HTML).
  4. If neither delivers, the Internet Archive's copy of the InfoLEG page (web.archive.org, 4 s apart).
  5. Where InfoLEG keeps an updated (consolidated) text, that HTML is saved too.

Rules: robots.txt of each host was read (see NOTES.txt); one request at a time;
4 s between requests on the gazette, 10 s on argentina.gob.ar, 1.5 s on InfoLEG; a host that answers
403/429 is not asked again in the run; three connection failures in a row, or
six server errors in a row, also end the use of that host. Files that exist are
skipped. Standard library only; `pdfinfo` is used to verify PDFs when installed.
"""
import base64
import csv
import http.cookiejar
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ar"
ACTS = OUT / "actos"
CATALOGUE = OUT / "listings" / "catalogue.tsv"
MANIFEST = OUT / "listings" / "manifest.tsv"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
MAX_BYTES = 500_000_000
MAX_FILES = 1500

BO = "https://www.boletinoficial.gob.ar"
ARG = "https://www.argentina.gob.ar"
INFOLEG = "https://servicios.infoleg.gob.ar"
DATASET = ("https://datos.jus.gob.ar/dataset/d9a963ea-8b1d-4ca3-9dd9-07a4773e8c23/resource/"
           "bf0ec116-ad4e-4572-a476-e57167a84403/download/base-infoleg-normativa-nacional.zip")
DELAY = {"www.boletinoficial.gob.ar": 4.0, "www.argentina.gob.ar": 10.0,
         "servicios.infoleg.gob.ar": 1.5, "datos.jus.gob.ar": 10.0, "web.archive.org": 4.0}
CDX = "https://web.archive.org/cdx/search/cdx"

# ---- selection of acts from the dataset -------------------------------------
OWN = re.compile(r"MIGRA|REFUG")
EXTRA_IDS = {"155937",   # Ministerio del Interior, Resolución 800/2009: CONARE rules of procedure
             "350507"}   # Ministerio del Interior, Resolución 72/2021: prior intervention on residences
DROP_IDS = {"56656", "56730", "132243", "160814"}
DROP = re.compile(
    r"CONTRATACI|LICITACI|DESIGNA|ASIGNA(SE|CION) (TRANSITORIA|DE FUNCIONES)|NOTIFI[CQ]"
    r"|CADUCIDAD DE LOS PROCEDIMIENTOS|IDENTIDAD INSTITUCIONAL|BONIFICACION|PLANTA|AGENTE|ADSCRIP|RENUNCIA"
    r"|CONCURSO|ESTRUCTURA ORGANIZATIVA|ASUETO|EDICTO|ADJUDIC|PLIEGO|PAGO DE HABILITACIONES|DEUDORES|LICENCIA"
    r"|CAJA CHICA|PRESUPUESTO|AUSPICI|DE INTERES"
    r"|\bTASAS?\b|ARANCEL|OFICINAS? MIGRATORIA|DELEGACION [A-Z ]+ - (HABILIT|FIN)|HABILITA(N)?SE|- HABILITACION"
    r"|\bAREA\b|FUNCION(ES)? (DE|-)|^FUNCION|CONVOCATORIA|DONACION|PROHIBICION DE FUMAR|ATENCION AL PUBLICO"
    r"|CARTEL|CONVENIO MARCO|HONORARIOS|PAGO VOLUNTARIO|FACILIDADES DE PAGO|BOLETA ELECTRONICA|MESA DE DIALOGO"
    r"|ESCUELA INFANTIL|EJECUCIONES|REGISTRO DE (EMPRESAS|COMPAÑIAS|RESPONSABLES|APODERADOS DE AGENCIAS|FIRMANTES)"
    r"|OPERADOR(ES|AS) DE TRANSPORTE|TRANSPORTE FLUVIAL|PASOS? (FRONTERIZOS?|INTERNACIONALES)"
    r"|PUENTE INTERNACIONAL|AEROPUERTO|COVID|CORONAVIRUS|1714/20|3911/20|1711/2020|3763/20|1798/2021"
    r"|JURISDICCION|DISTRIBUCION DE LAS JURISDICCIONES|INTERVENCION|COMPROMISO DE CONFIDENCIALIDAD|SELLOS"
    r"|COORDINACION GENERAL|DIRECTOR DE|FIRMA DESPACHO|COMISION CATOLICA|INTERCAMBIO ELECTRONICO"
    r"|UNICA BASE DE DATOS|CLAVE UNICA|TERMINALES DE AUTENTICACION|CONGRESO|CUMBRE|REUNION|RALLY|JUEGOS"
    r"|CONFERENCIA MINISTERIAL|EVENTO", re.I)
EVENT = re.compile(r"AUTORI[ZC][AE]SE (EL )?INGRESO|INGRESO - AUTORI|^AUTORIZACION$", re.I)
GUIDE = re.compile(
    r"INSTRUCTIVO|INSTRUCCIONES|MANUAL DE PROCEDIMIENTO|PROTOCOLO (DE|PARA)|PAUTAS A SEGUIR"
    r"|APRUEB[AE]SE (COMO ANEXO .{0,40})?(EL |UN )?'?\"?(REGLAMENTO DE )?PROCEDIMIENTO"
    r"|ESTABLE[CZ][EC]A?SE (COMO |UN |EL )?PROCEDIMIENTO|IMPLEMENTASE UN PROCEDIMIENTO|CRITERIOS QUE REGIRAN"
    r"|DIRECTIVA PARA", re.I)
# hand corrections of the automatic guidance / procedural-act split
FORCE_KIND = {"99299": "procedural act",    # only orders a manual to be drafted
              "387464": "procedural act"}   # paid priority-service surcharge

CAT_COLS = ["id", "type", "number", "date", "bo_date", "body", "title", "summary", "kind", "has_updated",
            "title_en"]

# ---- polite HTTP ----------------------------------------------------------------
last_hit = {}
blocked = {}                 # host -> reason
net_errors = {}              # host -> consecutive connection failures
srv_errors = {}              # host -> consecutive 5xx
stats = {"new": 0, "bytes": 0, "files": 0}
cookies = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def fetch(url, data=None, headers=None, timeout=90):
    """Return (status, bytes, content_type). status 0 = network error, -1 = host not in use."""
    host = urllib.parse.urlsplit(url).netloc
    if host in blocked:
        return -1, b"", ""
    wait = DELAY.get(host, 2.0) - (time.time() - last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    h = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.8,en;q=0.5"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read()
            last_hit[host] = time.time()
            net_errors[host] = srv_errors[host] = 0
            return r.status, body, r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        last_hit[host] = time.time()
        net_errors[host] = 0
        if e.code in (403, 429):
            blocked[host] = f"HTTP {e.code} on {url}"
            print(f"  BLOCKED by {host} (HTTP {e.code}); not asking this host again", flush=True)
        elif e.code >= 500:
            srv_errors[host] = srv_errors.get(host, 0) + 1
            if srv_errors[host] >= (3 if host == "web.archive.org" else 6):
                blocked[host] = f"six server errors in a row (last HTTP {e.code})"
                print(f"  GIVING UP on {host}: {blocked[host]}", flush=True)
        else:
            srv_errors[host] = 0
        return e.code, b"", ""
    except Exception as e:                           # noqa: BLE001 - timeouts, resets, TLS
        last_hit[host] = time.time()
        net_errors[host] = net_errors.get(host, 0) + 1
        print(f"  network error on {url}: {e}", flush=True)
        if net_errors[host] >= 3:
            blocked[host] = f"three connection failures in a row ({e})"
            print(f"  GIVING UP on {host}: {blocked[host]}", flush=True)
        return 0, b"", ""


def pdf_ok(data):
    if not data.startswith(b"%PDF"):
        return False
    exe = shutil.which("pdfinfo")
    if not exe:
        return True
    with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
        t.write(data)
        t.flush()
        return subprocess.run([exe, t.name], capture_output=True).returncode == 0


def store(dest, data, act, url, part):
    if stats["bytes"] + len(data) > MAX_BYTES or stats["files"] >= MAX_FILES:
        print("  size/file cap reached; not saving more", flush=True)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    stats["new"] += 1
    stats["bytes"] += len(data)
    stats["files"] += 1
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    new = not MANIFEST.exists()
    with open(MANIFEST, "a", encoding="utf-8") as f:
        if new:
            f.write("file\tid\tpart\tsource_url\n")
        f.write(f"{dest.relative_to(OUT)}\t{act['id']}\t{part}\t{url}\n")
    print(f"  saved {dest.name} ({len(data) // 1024} kB)", flush=True)
    return True


# ---- catalogue --------------------------------------------------------------------
def refresh_catalogue():
    old = {r["id"]: r for r in read_catalogue()} if CATALOGUE.exists() else {}
    local = [a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--dataset-zip=")]
    if local:
        status, data = 200, Path(local[0]).read_bytes()
    else:
        print("downloading the InfoLEG open dataset (about 50 MB) ...", flush=True)
        status, data, _ = fetch(DATASET, timeout=900)
    if status != 200 or not data.startswith(b"PK"):
        print(f"  dataset not obtained (status {status}); catalogue left as it is")
        return
    csv.field_size_limit(10 ** 9)
    rows = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        with z.open(name) as fh:
            for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
                i = r["id_norma"]
                if not (OWN.search(r["organismo_origen"]) or i in EXTRA_IDS):
                    continue
                if not r["texto_original"] or i in DROP_IDS:
                    continue
                s = r["titulo_resumido"] + " " + r["texto_resumido"][:300]
                if i not in EXTRA_IDS and (DROP.search(s) or EVENT.search(r["titulo_resumido"])):
                    continue
                kind = "guidance" if GUIDE.search(s) and "PROTOCOLO ADICIONAL" not in s else "procedural act"
                kind = FORCE_KIND.get(i, kind)
                clean = lambda x: re.sub(r"\s+", " ", x).strip()        # noqa: E731
                rows.append({"id": i, "type": r["tipo_norma"] + (" Conjunta" if r["clase_norma"] == "Conjunta" else ""),
                             "number": r["numero_norma"], "date": r["fecha_sancion"], "bo_date": r["fecha_boletin"],
                             "body": clean(r["organismo_origen"]), "title": clean(r["titulo_resumido"]),
                             "summary": clean(r["texto_resumido"]), "kind": kind,
                             "has_updated": "1" if r["texto_actualizado"] else "",
                             "title_en": old.get(i, {}).get("title_en", "")})
    rows.sort(key=lambda r: (r["date"], int(r["id"])))
    OUT.mkdir(exist_ok=True)
    with open(CATALOGUE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, CAT_COLS, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE, escapechar="\\")
        w.writeheader()
        w.writerows(rows)
    print(f"catalogue: {len(rows)} acts ({sum(r['kind'] == 'guidance' for r in rows)} guidance)")


def read_catalogue():
    with open(CATALOGUE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE, escapechar="\\"))


def body_names(act):
    b = act["body"]
    if "REFUGIADOS" in b:
        return "CONARE", "Comisión Nacional para los Refugiados (CONARE)"
    if "MIGRACI" in b:
        return "DNM", "Dirección Nacional de Migraciones (DNM)"
    if "INTERIOR" in b:
        return "MI", "Ministerio del Interior"
    return "X", b.title()


def stem(act):
    t = act["type"].replace("ó", "o").replace(" ", "-")
    num = re.sub(r"[^0-9A-Za-z]+", "-", act["number"]).strip("-") or "sn"
    return f"{act['date']}_{t}-{body_names(act)[0]}-{num}-{act['date'][:4]}"


# ---- source 1: Boletín Oficial ------------------------------------------------------
day_cache = {}


def anchors(markup):
    out = []
    for m in re.finditer(r'<a href="(/detalleAviso/primera/(\d+)/(\d+))[^"]*"(.*?)</a>', markup, re.S):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(4)))
        out.append((m.group(2), m.group(3), text))
    return out


def gazette_day(ymd):
    """All first-section notices of one gazette date: list of (aviso id, date, text)."""
    if ymd in day_cache:
        return day_cache[ymd]
    found = []
    status, data, _ = fetch(f"{BO}/seccion/primera/{ymd}")
    if status == 200:
        page = data.decode("utf-8", "replace")
        found = anchors(page)
        m = re.search(r"var ultimoRubro = '([^']*)'", page)
        rubro, pag, more = (m.group(1) if m else ""), 2, len(found) >= 100
        guard = 0
        while more and guard < 25:
            guard += 1
            url = f"{BO}/seccion/actualizar/primera?pag={pag}&ult_rubro={urllib.parse.quote(rubro)}"
            status, data, _ = fetch(url, headers={"X-Requested-With": "XMLHttpRequest",
                                                  "Referer": f"{BO}/seccion/primera/{ymd}"})
            if status != 200:
                break
            try:
                j = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                break
            got = anchors(j.get("html") or "")
            found += got
            more, pag, rubro = bool(j.get("hay_mas_datos")) and bool(got), j.get("sig_pag") or pag + 1, j.get("ult_rubro") or ""
    day_cache[ymd] = found
    return found


def gazette_find(act):
    if not act["bo_date"]:
        return None
    ymd = act["bo_date"].replace("-", "")
    num = act["number"].lstrip("0")
    year = act["date"][:4]
    word = "Disposici" if act["type"].startswith("Disp") else "Resoluci" if act["type"].startswith("Res") else act["type"][:5]
    pat = re.compile(rf"{word}[oó]n\s+(?:Conjunta\s+)?(?:N[°ºo.]*\s*)?(?:E\s+)?0*{re.escape(num)}(?:-E)?/(?:{year}|{year[2:]})\b", re.I)
    code = body_names(act)[0]
    want = {"DNM": "MIGRACI", "CONARE": "REFUGIAD", "MI": "INTERIOR"}.get(code, "")
    loose = re.compile(rf"(?<![\d/])0*{re.escape(num)}(?:-E)?/(?:{year}|{year[2:]})\b")
    day = list(dict.fromkeys(gazette_day(ymd)))
    typed = [a for a in day if pat.search(a[2].replace(".", ""))]
    best = [a for a in typed if want and want in a[2].upper()]
    if best:
        return best[0]
    # older notices are listed as "DIRECCION NACIONAL DE MIGRACIONES 32441/2004 ..." without the type word
    untyped = [a for a in day if want and want in a[2].upper() and loose.search(a[2].replace(".", ""))]
    if untyped:
        return untyped[0]
    return typed[0] if len(typed) == 1 else None


def from_gazette(act, base):
    hit = gazette_find(act)
    if not hit:
        return False
    aviso, ymd, _ = hit
    page_url = f"{BO}/detalleAviso/primera/{aviso}/{ymd}"
    status, data, _ = fetch(page_url)
    annexes = []
    if status == 200:
        annexes = re.findall(r'descargarPDFAnexo\("primera",\s*"(\d+)",\s*"(\d+)",\s*"(\d+)"', data.decode("utf-8", "replace"))
    pdf_url = f"{BO}/pdf/aviso/primera/{aviso}/{ymd}"
    # notices older than the electronic gazette are scans embedded in the page itself
    m = re.search(r'convertBase64InUrlBlob\("([A-Za-z0-9+/=]{2000,})"', data.decode("ascii", "ignore")) if status == 200 else None
    if m:
        try:
            data, pdf_url = base64.b64decode(m.group(1)), page_url
        except ValueError:
            return False
    else:
        status, data, _ = fetch(pdf_url)
    if status != 200 or not pdf_ok(data):
        return False
    if not store(ACTS / f"{base}.pdf", data, act, pdf_url, "act"):
        return False
    for n, anexo_id, fecha in dict.fromkeys(annexes):
        dest = ACTS / f"{base}_anexo-{n}.pdf"
        if dest.exists():
            continue
        body = urllib.parse.urlencode({"seccion": "primera", "nroAnexo": n, "idAnexo": anexo_id,
                                       "fechaPublicacion": fecha}).encode()
        status, data, _ = fetch(f"{BO}/pdf/download_anexo", data=body,
                                headers={"X-Requested-With": "XMLHttpRequest", "Referer": page_url}, timeout=180)
        pdf = b""
        if status == 200:
            try:
                pdf = base64.b64decode(json.loads(data.decode("utf-8", "replace")).get("pdfBase64") or "")
            except ValueError:
                pdf = b""
        if pdf and pdf_ok(pdf):
            store(dest, pdf, act, f"{page_url}?anexos=1#anexo-{n}-{anexo_id}", f"annex {n}")
        else:
            failures.append((act, f"annex {n} (id {anexo_id}) not delivered by the gazette", f"{page_url}?anexos=1"))
    return True


# ---- sources 2 and 3: argentina.gob.ar/normativa and InfoLEG (HTML) ---------------------
def html_ok(data, act):
    t = data.decode("utf-8", "replace") if b"charset=utf-8" in data[:3000].lower() else data.decode("latin-1", "replace")
    if len(t) < 1500 or re.search(r"500 - Error|404 Not Found|Error report|Proxy Error|no está disponible", t[:60000]) and "VISTO" not in t.upper():
        return False
    return bool(re.search(r"VISTO|CONSIDERANDO|ART[IÍ]CULO|Art\.", t))


def from_html(act, base, which="texto"):
    suffix = "" if which == "texto" else "_texto-actualizado"
    part = "act (HTML text)" if which == "texto" else "updated text"
    direct = "--wayback-only" not in sys.argv
    url = f"{ARG}/normativa/nacional/norma-{act['id']}/{which}"
    status, data, _ = fetch(url) if direct else (0, b"", "")
    if status == 200 and html_ok(data, act):
        return store(ACTS / f"{base}{suffix}.html", data, act, url, part)
    lo = int(act["id"]) // 5000 * 5000
    name = "norma.htm" if which == "texto" else "texact.htm"
    url = f"{INFOLEG}/infolegInternet/anexos/{lo}-{lo + 4999}/{act['id']}/{name}"
    status, data, _ = fetch(url) if direct else (0, b"", "")
    if status == 200 and html_ok(data, act):
        return store(ACTS / f"{base}{suffix}_infoleg.html", data, act, url, part)
    return False


def from_wayback(act, base):
    """The Internet Archive's copies of the act's InfoLEG folder: norma.htm (text), texact.htm (updated text)
    and the annexes (PDF or images). Returns True if the text was obtained."""
    lo = int(act["id"]) // 5000 * 5000
    folder = f"servicios.infoleg.gob.ar/infolegInternet/anexos/{lo}-{lo + 4999}/{act['id']}/"
    status, data, _ = fetch(f"{CDX}?url={folder}*&output=json&fl=original,timestamp&filter=statuscode:200"
                            f"&collapse=urlkey&limit=200")
    if status != 200:
        return False
    try:
        caps = json.loads(data.decode("utf-8", "replace") or "[]")[1:]
    except ValueError:
        return False
    got_text = have(base)
    seen = set()
    for original, ts in caps:
        name = urllib.parse.unquote(original.rsplit("/", 1)[-1]).split("?")[0]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        url = f"https://web.archive.org/web/{ts}id_/{original}"
        low = name.lower()
        if low in ("norma.htm", "texact.htm"):
            dest = ACTS / (f"{base}_infoleg.html" if low == "norma.htm" else f"{base}_texto-actualizado_infoleg.html")
            if dest.exists() or (low == "norma.htm" and got_text):
                continue
            status, body, _ = fetch(url)
            if status == 200 and html_ok(body, act):
                part = "act (HTML text, Wayback Machine copy of InfoLEG)" if low == "norma.htm" else \
                    "updated text (Wayback Machine copy of InfoLEG)"
                if store(dest, body, act, url, part) and low == "norma.htm":
                    got_text = True
        elif re.search(r"\.(pdf|jpe?g|png|gif|tiff?)$", low):
            dest = ACTS / f"{base}_anexo-{re.sub(r'[^A-Za-z0-9.-]+', '-', name)}"
            if dest.exists():
                continue
            status, body, _ = fetch(url)
            ok = status == 200 and (pdf_ok(body) if low.endswith(".pdf") else
                                    body[:3] in (b"\xff\xd8\xff", b"GIF") or body[:4] in (b"\x89PNG", b"II*\x00", b"MM\x00*"))
            if ok:
                store(dest, body, act, url, f"annex {name} (Wayback Machine copy of InfoLEG)")
            else:
                failures.append((act, f"annex {name}: archived copy not a valid file", url))
    return got_text


# ---- main -------------------------------------------------------------------------------
failures = []


def have(base, updated=False):
    pat = f"{base}_texto-actualizado*" if updated else f"{base}.*"
    hits = list(ACTS.glob(pat)) if updated else [p for p in ACTS.glob(f"{base}*") if "_texto-actualizado" not in p.name
                                                 and "_anexo-" not in p.name]
    return bool(hits)


def write_outputs(cat):
    by_id = {a["id"]: a for a in cat}
    rows, seen = [], set()
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8") as f:
            for line in list(f)[1:]:
                file, i, part, url = line.rstrip("\n").split("\t")
                if file in seen or i not in by_id or not (OUT / file).exists():
                    continue
                seen.add(file)
                a = by_id[i]
                label = f"{a['type']} {body_names(a)[0]} {a['number']}/{a['date'][:4]} - {a['title']}"
                note = "" if part == "act" else f" [{part}]"
                rows.append((file, label + note, a["date"], url, a["kind"], body_names(a)[1], a["title_en"] + note))
    rows.sort(key=lambda r: (r[2], r[0]))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tissuing_body\n")
        for r in rows:
            r = r[:5] + (r[6], r[5])
            f.write("\t".join(x.replace("\t", " ") for x in r) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\tkind\n")
        for a in cat:
            base = stem(a)
            label = f"{a['type']} {body_names(a)[0]} {a['number']}/{a['date'][:4]} - {a['title']}"
            if not have(base):
                f.write(f"{label}\t{a['date']}\t{ARG}/normativa/nacional/norma-{a['id']}/texto\t{MISSING_WHY}\t{a['kind']}\n")
            elif a["has_updated"] and not have(base, True):
                f.write(f"{label} [updated text]\t{a['date']}\t{ARG}/normativa/nacional/norma-{a['id']}/actualizacion\t"
                        f"updated (consolidated) text not delivered; the original act was saved\t{a['kind']}\n")
        for a, why, url in failures:
            label = f"{a['type']} {body_names(a)[0]} {a['number']}/{a['date'][:4]} - {a['title']}"
            f.write(f"{label}\t{a['date']}\t{url}\t{why}\t{a['kind']}\n")
        for item, date, kind, why, url in STATIC_NOT_OBTAINED:
            f.write(f"{item}\t{date}\t{url}\t{why}\t{kind}\n")
    return rows


# Why an act is missing, as established on 2026-11-15 (see NOTES.txt).
MISSING_WHY = ("gazette (www.boletinoficial.gob.ar) answered HTTP 429 and was not used again; "
               "argentina.gob.ar/normativa answered HTTP 500 and InfoLEG (servicios.infoleg.gob.ar) HTTP 502 "
               "or timed out to every request; the Internet Archive was offline or had no copy")

STATIC_NOT_OBTAINED = [
    ("Políticas de calidad del servicio de control migratorio (DNM quality policy, ISO 9001 system)", "2026", "guidance",
     "robots.txt of www.argentina.gob.ar disallows /*.pdf$ ; a one-page policy statement, not a procedure",
     "https://www.argentina.gob.ar/sites/default/files/politicas-calidad_dnmcdr202610.pdf"),
    ("Procedures and work instructions of the DNM quality-management system (Dirección General de Movimiento Migratorio)",
     "", "guidance", "not published: the site shows only the policy statement and the ISO certificate",
     "https://www.argentina.gob.ar/migraciones/gestion-de-calidad"),
    ("CONARE eligibility guidelines / internal instructions of its Executive Secretariat", "", "guidance",
     "not published: the CONARE pages carry only treaties, Ley 26.165 and three resolutions",
     "https://www.argentina.gob.ar/migraciones/comision-nacional-para-los-refugiados/normativa-conare"),
    ("DNM acts for which InfoLEG holds no text (about 1,640 of 2,260, almost all staffing and procurement)", "", "procedural act",
     "outside the selection; listed in the open dataset only by title", "https://datos.jus.gob.ar/dataset/base-de-datos-legislativos-infoleg"),
]


def main():
    args = sys.argv[1:]
    OUT.mkdir(exist_ok=True)
    if "--refresh-catalogue" in args or not CATALOGUE.exists():
        refresh_catalogue()
    if not CATALOGUE.exists():
        sys.exit("no catalogue; run with --refresh-catalogue")
    cat = read_catalogue()
    existing = [p for p in ACTS.glob("*") if p.is_file()] if ACTS.exists() else []
    stats["files"], stats["bytes"] = len(existing), sum(p.stat().st_size for p in existing)
    fallback = "--no-fallback" not in args
    for n, act in enumerate(cat, 1):
        base = stem(act)
        if not have(base):
            print(f"[{n}/{len(cat)}] {act['type']} {act['number']}/{act['date'][:4]} {act['title'][:60]}", flush=True)
            ok = "--no-gazette" not in args and from_gazette(act, base)
            if not ok and fallback:
                ok = from_html(act, base)
            if not ok and "--no-wayback" not in args and "web.archive.org" not in blocked:
                ok = from_wayback(act, base)
            if not ok:
                print("  not obtained", flush=True)
        if act["has_updated"] and fallback and have(base) and not have(base, True):
            from_html(act, base, "actualizacion")
        if all(h in blocked for h in DELAY if h != "datos.jus.gob.ar") or \
                ("--wayback-only" in args and "web.archive.org" in blocked):
            print("all hosts given up; stopping")
            break
    rows = write_outputs(cat)
    print(f"ar: {len(rows)} files indexed, {stats['new']} new this run, {stats['bytes'] / 1e6:.0f} MB in ar/actos")
    for h, why in blocked.items():
        print(f"  host not used further: {h}: {why}")


if __name__ == "__main__":
    main()

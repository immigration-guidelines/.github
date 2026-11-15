#!/usr/bin/env python3
"""Ecuador: what the migration authorities publish for the officials who decide cases.

    python3 download_ec.py                              # all sources
    python3 download_ec.py --give-up=web.archive.org    # do not ask a host that refused

Sources (see ec/NOTES.txt for what was checked; in the run of 2026-11-15 nothing could be
fetched, so ec/ holds only the listings):

  mremh  Ministerio de Relaciones Exteriores y Movilidad Humana (www.cancilleria.gob.ec):
         a fixed list of process documents, instructivos, protocols and ministerial
         agreements on visas, residence, refuge and statelessness found in the Internet
         Archive's index of the ministry's uploads. Each is asked first from the ministry
         (only with a verifiable TLS certificate - in 2026-11 the server does not send
         its intermediate certificate, so this fails and the host is dropped), then from
         the Internet Archive (web.archive.org/web/<timestamp>id_/<url>, archived bytes).

Rules: robots.txt is read for each host before anything else and obeyed (rules for "*"
and rules that name AI agents; wildcards handled here, Crawl-delay honoured); one
request at a time, at least 2 s apart (4 s and a shared lock file for web.archive.org);
a host that answers 401, 403 or 429, serves a challenge page, or fails three times in a
row is not asked again in that run. TLS verification is never disabled. Files that exist
are skipped; ec/index.tsv and ec/not-obtained.tsv are rebuilt on every run. Standard
library only.
"""
import fcntl
import html
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ec"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
IA_DELAY = 4.0
LOCKDIR = Path("/tmp/claude-1000/-home-brinly-vab/90332c16-33fe-47cb-91e5-cd2687d17632/scratchpad/locks")
MAX_BYTES = 500_000_000
MAX_FILES = 1500
MAX_ONE = 95_000_000
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "oai-searchbot", "perplexitybot", "bytespider", "ai2bot")
MREMH_BODY = "Ministerio de Relaciones Exteriores y Movilidad Humana (MREMH)"
U = "https://www.cancilleria.gob.ec/wp-content/uploads/"

# (archive timestamp, path under wp-content/uploads/, date, kind, title, title_en, file name stem)
# Titles are taken from the file names (the documents could not be read); dates are the
# upload month unless the name gives a date.
MREMH = [
    ("20141005051600", "2013/03/acuerdo_337_derecho_estudio_refugiados_01.pdf",
     "2013-03", "procedural act", 'Acuerdo 337: derecho a la educación de personas refugiadas',
     'Agreement 337: right to education of refugees', "Acuerdo-337-derecho-estudio-refugiados"),
    ("20161009231031", "2013/11/proceso-naturalizaciones.pdf",
     "2013-11", "guidance", 'Proceso de naturalizaciones',
     'Naturalisation process (process description)', "Proceso-naturalizaciones"),
    ("20161009231212", "2013/11/proceso-transferencia-visa.pdf",
     "2013-11", "guidance", 'Proceso de transferencia de visa',
     'Visa transfer process (process description)', "Proceso-transferencia-visa"),
    ("20140714074047", "2014/04/Acuerdo_ministerial_no._000031_que_norma_la_aplicaci%C3%93n_del_acuerdo_sobre_residencia_del_mercosur.pdf",
     "2014-04", "procedural act", 'Acuerdo Ministerial N.° 000031 que norma la aplicación del Acuerdo sobre Residencia del MERCOSUR',
     'Ministerial Agreement 000031 regulating the application of the MERCOSUR Residence Agreement', "AM-000031-aplicacion-residencia-MERCOSUR"),
    ("20220303214548", "2015/04/INSTRUCTIVOS-DE-PROCESOS-DE-LA-SUBSECRETARIA-DE-ASUNTOS-MIGRATORIOS.pdf",
     "2015-04", "guidance", 'Instructivos de procesos de la Subsecretaría de Asuntos Migratorios',
     'Process instructions of the Under-Secretariat for Migration Affairs', "Instructivos-procesos-Subsecretaria-Asuntos-Migratorios"),
    ("20220120040352", "2018/09/acuerdo_ministerial_242_pasaportes_venezolanos.pdf",
     "2018-09", "procedural act", 'Acuerdo Ministerial 242: pasaportes venezolanos',
     'Ministerial Agreement 242: Venezuelan passports', "AM-242-pasaportes-venezolanos"),
    ("20220223135705", "2018/09/acuerdo_ministerial_243_excepcion_pasaporte_ninios_venezolanos.pdf",
     "2018-09", "procedural act", 'Acuerdo Ministerial 243: excepción de pasaporte para niños venezolanos',
     'Ministerial Agreement 243: passport exemption for Venezuelan children', "AM-243-excepcion-pasaporte-ninos-venezolanos"),
    ("20210511043807", "2018/09/acuerdo_ministerial_244_de_documento_de_identidad_venezolanos.pdf",
     "2018-09", "procedural act", 'Acuerdo Ministerial 244: documento de identidad de ciudadanos venezolanos',
     'Ministerial Agreement 244: identity documents of Venezuelan nationals', "AM-244-documento-identidad-venezolanos"),
    ("20220119014033", "2018/11/procedimiento.pdf",
     "2018-11", "guidance", 'Procedimiento (documento sin título en el nombre del archivo)',
     'Procedure (document whose subject the file name does not give)', "Procedimiento-2018-11"),
    ("20240617015133", "2019/02/ACUERDO-ANTECEDENTES-VENEZUELA.pdf",
     "2019-02", "procedural act", 'Acuerdo: antecedentes penales de ciudadanos venezolanos',
     'Agreement: criminal-record certificates of Venezuelan nationals', "Acuerdo-antecedentes-Venezuela"),
    ("20211204075137", "2019/07/Instructivo-Visas-Vacaciones-y-Trabajo-Ecuador-Australia-final.pdf",
     "2019-07", "guidance", 'Instructivo de visas de vacaciones y trabajo Ecuador-Australia',
     'Instructions on Ecuador-Australia working-holiday visas', "Instructivo-visas-vacaciones-trabajo-Australia"),
    ("20210511030425", "2019/07/Protocolo-para-acreditar-medios-de-vida-li%CC%81citos.pdf",
     "2019-07", "guidance", 'Protocolo para acreditar medios de vida lícitos',
     'Protocol for proving lawful means of subsistence (visa applications)', "Protocolo-medios-de-vida-licitos"),
    ("20210803235819", "2019/08/acuaerdo_interministerial_000003_visas_a_nacionales_de_11_pai%CC%81ses_de_africa_y_asia.pdf",
     "2019-08", "procedural act", 'Acuerdo Interministerial 000003: visas para nacionales de 11 países de África y Asia',
     'Inter-ministerial Agreement 000003: visa requirement for nationals of 11 African and Asian countries', "AI-000003-visas-11-paises-Africa-Asia"),
    ("20200715042321", "2019/09/acuerdo_ministerial_103_medidas_migratorias_a_favor_de_ciudadanos_venezolanos0169571001567716139.pdf",
     "2019-09", "procedural act", 'Acuerdo Ministerial 103: medidas migratorias a favor de ciudadanos venezolanos',
     'Ministerial Agreement 103: migration measures for Venezuelan nationals (amnesty, humanitarian visa)', "AM-103-medidas-migratorias-venezolanos"),
    ("20200321222105", "2020/03/ACUERDO-INTERMINISTERIAL-0000001.pdf.pdf.pdf",
     "2020-03", "procedural act", 'Acuerdo Interministerial 0000001 (2020)',
     'Inter-ministerial Agreement 0000001 of 2020 (COVID-19 period)', "AI-0000001-2020"),
    ("20220119155411", "2020/06/protocolo-para-acreditar-medios-de-vida-li%CC%81citos0045269001593444369.pdf",
     "2020-06", "guidance", 'Protocolo para acreditar medios de vida lícitos (versión 2020)',
     'Protocol for proving lawful means of subsistence (2020 version)', "Protocolo-medios-de-vida-licitos-2020"),
    ("20210720135314", "2021/07/lineamiento_ingreso_al_pais_-_12-07-2021-signed-2-signed-signed0254473001626112749_210718_205712-1.pdf",
     "2021-07-12", "guidance", 'Lineamiento de ingreso al país (12-07-2021)',
     'Guideline on entry into the country (12 July 2021, COVID-19)', "Lineamiento-ingreso-al-pais"),
    ("20210917124836", "2021/09/INSTRUCTIVO-PARA-EL-ACCESO-DE-INTERPRETACIO%CC%81N-EN-EL-PROCESO-PARA-LA-DETERMINACIO%CC%81N-DE-LA-CONDICIO%CC%81N-DE-REFUGIO-Y-APATRIDIA-signed.pdf",
     "2021-09", "guidance", 'Instructivo para el acceso de interpretación en el proceso para la determinación de la condición de refugio y apatridia',
     'Instructions on access to interpretation in refugee and statelessness determination', "Instructivo-interpretacion-determinacion-refugio-apatridia"),
    ("20261018040120", "2023/09/230131_AM-0006_instructivo-determinacion-condicion-refugiado-y-apatrida.pdf",
     "2023-01-31", "procedural act", 'Acuerdo Ministerial 0006: Instructivo para el procedimiento de determinación de la condición de personas refugiadas y apátridas en el Ecuador',
     'Ministerial Agreement 0006: instructions on the procedure for determining refugee and stateless status (binding on the officials who decide)', "AM-0006-instructivo-determinacion-refugiado-apatrida"),
    ("20170215030449", "downloads/2012/06/7-Manual-Proceso-Especiales.pdf",
     "2012-06", "guidance", 'Manual de procesos especiales',
     'Manual of special processes', "Manual-procesos-especiales"),
    ("20161009231158", "downloads/2013/08/DME-SP02-gestion-visa-no-inmigrante.pdf",
     "2013-08", "guidance", 'DME-SP02: Gestión de visa de no inmigrante (subproceso)',
     'DME-SP02: handling of non-immigrant visas (sub-process document)', "DME-SP02-gestion-visa-no-inmigrante"),
    ("20161009231205", "downloads/2013/08/DME-SP04-gestion-visa-inmigrante.pdf",
     "2013-08", "guidance", 'DME-SP04: Gestión de visa de inmigrante (subproceso)',
     'DME-SP04: handling of immigrant visas (sub-process document)', "DME-SP04-gestion-visa-inmigrante"),
    ("20161009231241", "downloads/2013/08/DME-SP07-cancelacion-visa.pdf",
     "2013-08", "guidance", 'DME-SP07: Cancelación de visa (subproceso)',
     'DME-SP07: visa cancellation (sub-process document)', "DME-SP07-cancelacion-visa"),
    ("20250605104513", "downloads/2021/07/mremh-dvn-2021-0313-m._acuerdo_6__procedimiento_para_la_regularizaci%C3%B3n.pdf",
     "2021-07", "procedural act", 'MREMH-DVN-2021-0313-M: Acuerdo 6, procedimiento para la regularización',
     'MREMH-DVN-2021-0313-M: Agreement 6, procedure for regularisation', "Acuerdo-6-procedimiento-regularizacion"),
    ("20240225140550", "downloads/2021/07/mremh-dvn-2021-0313-m._acuerdo_85_medios_l%C3%ADcitos.pdf",
     "2021-07", "procedural act", 'MREMH-DVN-2021-0313-M: Acuerdo 85, medios lícitos de vida',
     'MREMH-DVN-2021-0313-M: Agreement 85, lawful means of subsistence', "Acuerdo-85-medios-licitos"),
]

# Known to exist, not fetched (besides the list above): (title, date, url, reason)
NOT_OBTAINED = [
    ("Instructivo para el procedimiento de determinación de la condición de personas refugiadas y apátridas en el "
     "Ecuador (Acuerdo Ministerial MREMH, suscrito 2023-01-31, Registro Oficial 259 de 2023-03-01) - copia de gob.ec",
     "2023-01-31", "https://www.gob.ec/sites/default/files/regulations/2025-02/INSTRUCTIVO_PARA_EL_PROCEDIMIENTO_DE_"
     "DETERMINACI%C3%93N_CONDICI%C3%93N_REFUGIADO.pdf",
     "not fetched: www.gob.ec answered HTTP 403 ('Acceso denegado') to an earlier request in this task; host closed"),
    ("Normas publicadas en el Registro Oficial (acuerdos ministeriales del MREMH y del Ministerio del Interior)", "",
     "https://www.registroficial.gob.ec/", "not fetched: the site's search interface (/wp-json/) answers HTTP 401; "
     "host closed after that; the gazette editions cannot be searched otherwise"),
    ("Documentos de UNHCR/ACNUR Refworld sobre Ecuador (copias de instructivos)", "", "https://www.refworld.org/",
     "not fetched: robots.txt answers with a Cloudflare JavaScript challenge (seen by an earlier agent); host closed"),
]

blocked = {}
errors = {}
last_hit = {}
rules = {}
contexts = {}           # host -> SSL context with the intermediate the server fails to send
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
                                        timeout=180, context=contexts.get(host)) as r:
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


def completed_context(host):
    """The server does not send its intermediate certificate (www.cancilleria.gob.ec, 2026-11). Do what a
    browser does: read the "CA Issuers" (AIA) address in the server's own certificate, fetch that
    intermediate (robots.txt of the CA's host read first) and add it to the system trust store. The chain
    is still verified up to a root this machine trusts, and the host name is still checked; verification
    is never switched off. Returns None if this is not possible."""
    try:
        leaf = ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate((host, 443), timeout=60))
    except Exception as e:                                  # noqa: BLE001
        print(f"  {host}: could not read the server certificate ({e})")
        return None
    m = re.search(rb"http://[\x21-\x7e]+?\.(?:crt|cer)", leaf)
    if not m:
        print(f"  {host}: certificate chain incomplete and no CA Issuers address in the certificate")
        return None
    aia = m.group().decode()
    if not allowed(aia):
        print(f"  {aia}: excluded or refused ({blocked.get(host_of(aia), 'robots.txt')})")
        return None
    r = request(aia)
    if r is None or len(r) == 1:
        return None
    der = r[0]
    pem = der.decode("ascii") if der.startswith(b"-----BEGIN") else ssl.DER_cert_to_PEM_cert(der)
    ctx = ssl.create_default_context()                      # system roots, CERT_REQUIRED, check_hostname
    ctx.load_verify_locations(cadata=pem)
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    print(f"  {host}: chain completed with the intermediate from {aia}")
    return ctx


def load_robots(host, scheme="https"):
    pats, delay, text = [], 0.0, ""
    for attempt in (1, 2):
        try:
            with HostLock(host):
                wait(host)
                with urllib.request.urlopen(urllib.request.Request(f"{scheme}://{host}/robots.txt",
                                                                   headers={"User-Agent": UA}), timeout=60,
                                            context=contexts.get(host) if scheme == "https" else None) as r:
                    text = r.read().decode("utf-8", "replace")
            break
        except urllib.error.URLError as e:
            if (attempt == 1 and scheme == "https" and isinstance(getattr(e, "reason", None),
                                                                  ssl.SSLCertVerificationError)):
                ctx = completed_context(host)
                if ctx:
                    contexts[host] = ctx
                    continue
            if isinstance(e, urllib.error.HTTPError):
                if e.code in (401, 403, 429):
                    blocked[host] = f"robots.txt answers HTTP {e.code}"
                    print(f"  REFUSED: {host} robots.txt answers HTTP {e.code}; host not used")
            else:
                blocked[host] = f"robots.txt unreachable: {e}"
                print(f"  {host}: robots.txt unreachable ({e}); host not used")
            break
        except Exception as e:                              # noqa: BLE001
            blocked[host] = f"robots.txt unreachable: {e}"
            print(f"  {host}: robots.txt unreachable ({e}); host not used")
            break
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
        load_robots(host, urllib.parse.urlsplit(url).scheme)
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


def source_mremh():
    print("mremh: Foreign Ministry process documents, instructivos and agreements")
    for ts, path, date, kind, title, title_en, name in MREMH:
        rel = f"mremh/{date}_{name}.pdf"
        dest = OUT / rel
        direct = U + path
        archived = f"https://web.archive.org/web/{ts}id_/{direct}"
        if (OUT / ".large" / rel).exists():
            continue
        url = direct
        if not dest.exists():
            if not room(title, date, direct):
                continue
            got, why = None, []
            for url in (direct, archived):
                if not allowed(url):
                    why.append(f"{host_of(url)}: " + blocked.get(host_of(url), "excluded by robots.txt"))
                    continue
                r = request(url)
                if r is None or len(r) == 1:
                    why.append(f"{host_of(url)}: " + (r[0] if r else blocked.get(host_of(url), "closed")))
                    continue
                tmp = dest.with_name(dest.name + ".part")
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_bytes(r[0])
                if not is_pdf(tmp):
                    tmp.unlink()
                    why.append(f"{host_of(url)}: answer was not a PDF")
                    continue
                got = tmp
                break
            if not got:
                failures.append((title, date, archived, "not fetched - " + "; ".join(why)))
                continue
            if got.stat().st_size > MAX_ONE:
                (OUT / ".large" / rel).parent.mkdir(parents=True, exist_ok=True)
                got.rename(OUT / ".large" / rel)
                continue
            got.rename(dest)
            stats["new"] += 1
            print(f"  saved {rel}")
        rows.append((rel, title, date, url, kind, title_en, MREMH_BODY))


SOURCES = {"mremh": source_mremh}


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

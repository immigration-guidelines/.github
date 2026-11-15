#!/usr/bin/env python3
"""Uruguay: what the migration authorities publish for the officials who decide cases.

    python3 download_uy.py            # all sources
    python3 download_uy.py sinae      # one source (sinae, mrree)

Uruguay publishes almost nothing of this kind (see uy/NOTES.txt). The script fetches a
fixed list of the few documents found, all on www.gub.uy:

  sinae   Sistema Nacional de Emergencias (Presidencia): two inter-agency protocols for
          migration control at the points of entry during the 2020-2021 health emergency,
          written with the Dirección Nacional de Migración, the Foreign Ministry and UNHCR /
          IOM, addressed to the officials at the border (kind "guidance").
  mrree   Ministerio de Relaciones Exteriores: protocol for embassies and consular offices on
          trafficking in women and children (2011, with Inmujeres/MIDES) (kind "guidance").

www.gub.uy answered HTTP 403 during the first run (2026-11-15) after these files had been
obtained; the script only asks for a file that is not on disk yet, and closes a host
that answers 401/403/429 or a bot check.

Rules: robots.txt is read for each host before anything else and obeyed (rules for "*"
and rules that name AI agents; wildcards handled here, Crawl-delay honoured); one
request at a time, at least 2 s apart per host. Files that exist are skipped;
uy/index.tsv and uy/not-obtained.tsv are rebuilt on every run. Standard library only.
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
OUT = ROOT / "uy"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
MAX_ONE = 95_000_000
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "oai-searchbot", "perplexitybot", "bytespider", "ai2bot")

G = "https://www.gub.uy"
# source -> list of (file, title, date, url, kind, title_en, issuing body)
ITEMS = {
    "sinae": [
        ("sinae/2021-01_Protocolo-ingreso-solicitantes-refugio-emergencia-sanitaria.pdf",
         "Protocolo de actuación específico para personas solicitantes de refugio (literal g, Decreto 104/2020) para el "
         "ingreso de personas a través de los puntos habilitados de control migratorio en el marco del Estado de "
         "Emergencia Nacional Sanitaria por el Coronavirus SARS-CoV-2",
         "2021-01",
         G + "/sistema-nacional-emergencias/sites/sistema-nacional-emergencias/files/documentos/publicaciones/"
             "Protocolo%20para%20ingreso%20de%20personas%20solicitantes%20de%20refugio%20durante%20la%20emergencia"
             "%20nacional%20sanitaria.pdf",
         "guidance",
         "Specific operating protocol for asylum seekers entering through the authorised migration control points "
         "during the national health emergency (COVID-19): steps for migration, health and refugee-commission staff",
         "Sinae / MSP / MRREE / Ministerio del Interior (DNM) / MDN, with OIM and ACNUR"),
        ("sinae/2020-04_Protocolo-integrado-puntos-de-entrada.pdf",
         "Protocolo integrado para el ingreso de personas por los Puntos de Entrada al país, en el marco del Estado de "
         "Emergencia Nacional Sanitaria por el Coronavirus Covid-19 en Uruguay",
         "2020-04",
         G + "/sistema-nacional-emergencias/sites/sistema-nacional-emergencias/files/documentos/publicaciones/"
             "Protocolo%20integrado_Puntos%20de%20Entrada_Sinae.pdf",
         "guidance",
         "Integrated protocol for the entry of persons at the country's points of entry during the COVID-19 national "
         "health emergency (migration, health and customs officials at ports, airports and land crossings)",
         "Sistema Nacional de Emergencias (Presidencia) with MSP, Ministerio del Interior (DNM) and others"),
    ],
    "mrree": [
        ("mrree/2011_Protocolo-trata-embajadas-oficinas-consulares.pdf",
         "Trata de mujeres, niñas, niños y adolescentes con fines de explotación sexual comercial: Protocolo de actuación "
         "para el abordaje de la temática en las embajadas y oficinas consulares",
         "2011",
         G + "/ministerio-relaciones-exteriores/sites/ministerio-relaciones-exteriores/files/documentos/publicaciones/"
             "Protocolo%2Bpara%2BEmbajadas%2By%2BOficinas%2BConsulares.pdf",
         "guidance",
         "Trafficking in women and children for commercial sexual exploitation: operating protocol for embassies and "
         "consular offices (identification, interview and assistance of victims)",
         "Ministerio de Relaciones Exteriores / Ministerio de Desarrollo Social (Inmujeres)"),
    ],
}

# Known to exist, not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Guía de actuación para funcionarios de la Dirección Nacional de Migración sobre detección de posibles situaciones "
     "de trata de personas (controles migratorios, gestión de residencias)", "2026-07",
     G + "/ministerio-interior/comunicacion/noticias/ministerio-del-interior-presento-dos-nuevos-protocolos-para-migracion",
     "announced by the Ministerio del Interior on 30/07/2026; not published online (no file on the announcement page)"),
    ("Guía de actuación para funcionarios de la Dirección Nacional de Identificación Civil sobre trata de personas",
     "2026-07",
     G + "/ministerio-interior/comunicacion/noticias/ministerio-del-interior-presento-dos-nuevos-protocolos-para-migracion",
     "announced on 30/07/2026; not published online. Strictly an identity-document guide, listed for completeness"),
    ("Protocolos de intervención del Ministerio del Interior en materia de trata de personas (en revisión)", "",
     G + "/ministerio-interior/comunicacion/noticias/ministerio-del-interior-presento-dos-nuevos-protocolos-para-migracion",
     "mentioned as under revision; not published"),
    ("Resolución de la Comisión de Refugiados (CORE): plan piloto de reconocimiento prima facie para solicitantes "
     "venezolanos sin entrevista", "2024-05",
     G + "/ministerio-relaciones-exteriores/comunicacion/noticias/gobierno-establece-procedimiento-abreviado-para-solicitantes-refugio",
     "only press releases found; the CORE resolution itself is not published on gub.uy or IMPO"),
    ("Guía de orientación del Programa de Residencias por Arraigo", "",
     G + "/ministerio-interior/comunicacion/publicaciones/guia-orientacion-del-programa-residencias-arraigo",
     "www.gub.uy answered HTTP 403 on 2026-11-15; host closed for the run (probably applicant information anyway)"),
]

blocked, errors, last_hit, rules = {}, {}, {}, {}
failures, rows = [], []
stats = {"new": 0}


def host_of(url):
    return urllib.parse.urlsplit(url).netloc


def wait(host):
    delay = max(DELAY, rules.get(host, ([], 0))[1])
    gap = time.time() - last_hit.get(host, 0)
    if gap < delay:
        time.sleep(delay - gap)
    last_hit[host] = time.time()


def request(url):
    host = host_of(url)
    if host in blocked:
        return None
    wait(host)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180) as r:
            errors[host] = 0
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        errors[host] = 0
        if e.code in (401, 403, 429):
            blocked[host] = f"HTTP {e.code}"
            print(f"  REFUSED by {host} (HTTP {e.code}); host not asked again")
        return ("HTTP %d" % e.code,)
    except Exception as e:                              # noqa: BLE001
        errors[host] = errors.get(host, 0) + 1
        if errors[host] >= 3:
            blocked[host] = "three connection errors in a row"
        return (f"connection error: {e}",)


def load_robots(host):
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
        text = ""
    except Exception as e:                              # noqa: BLE001
        blocked[host] = f"robots.txt unreachable: {e}"
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
    p = urllib.parse.urlsplit(url)
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


def fetch(rel, title, date, url, kind, title_en, body):
    dest = OUT / rel
    if (OUT / ".large" / rel).exists():
        return
    if not dest.exists():
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
            tmp.unlink()
            failures.append((title, date, url, "answer was not a PDF (" + (r[1] or "no type") + ")"))
            return
        if len(r[0]) > MAX_ONE:
            (OUT / ".large" / rel).parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(OUT / ".large" / rel)
            return
        tmp.rename(dest)
        stats["new"] += 1
        print(f"  saved {rel}")
    rows.append((rel, title, date, url, kind, title_en, body))


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def main():
    wanted = [a for a in sys.argv[1:] if a in ITEMS] or list(ITEMS)
    OUT.mkdir(exist_ok=True)
    idx = OUT / "index.tsv"
    old = {}
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            c = line.split("\t")
            if len(c) >= 7 and (OUT / c[0]).exists() and c[0].split("/")[0] not in wanted:
                old[c[0]] = tuple(c[:7])
    for name in wanted:
        print(name)
        for item in ITEMS[name]:
            fetch(*item)
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
    print(f"done: {len(final)} documents in index, {stats['new']} new, {len(failures)} failures, "
          f"closed hosts: {blocked or 'none'}")
    if on_disk - set(final):
        print("files without an index row:", sorted(on_disk - set(final)))


if __name__ == "__main__":
    main()

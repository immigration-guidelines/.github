#!/usr/bin/env python3
"""Paraguay: what the migration authorities publish for the officials who decide cases.

    python3 download_py.py              # all sources
    python3 download_py.py manuales     # one source (manuales, resoluciones)

Sources (see py/NOTES.txt for what was checked and what is missing), all on
migraciones.gov.py, the site of the Dirección Nacional de Migraciones (DNM; until 2022
Dirección General de Migraciones, DGM):

  manuales      the "Procedimientos" items of the MECIP page (https://migraciones.gov.py/mecip/):
                the Manual para Servidores Públicos de Frontera (EUROFRONT, 2023) and its
                annexes (kind "guidance").
  resoluciones  https://migraciones.gov.py/resoluciones/ : the resolutions of the Director
                that set working procedure or decision criteria for migration cases
                (residence criteria and evidence, cancellation, border-control procedures,
                the 2016 manual for foreign victims of trafficking). Chosen by number in
                RES_KEEP; the many resolutions on internal control (MECIP), ethics
                committees, HR, structure, fees and opening hours are left out on purpose.

Rules: robots.txt is read for each host before anything else and obeyed (rules for "*"
and rules that name AI agents; wildcards handled here, Crawl-delay honoured); one
request at a time, at least 2 s apart per host; a host that answers 401/403/429, a bot
check, or three connection errors in a row is not asked again in that run. Files that
exist are skipped; py/index.tsv and py/not-obtained.tsv are rebuilt on every run.
Standard library only. The server is slow (often 100-200 kB/s): a full first run takes
a while.
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
OUT = ROOT / "py"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
MAX_ONE = 95_000_000
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "oai-searchbot", "perplexitybot", "bytespider", "ai2bot")

B = "https://migraciones.gov.py"
DNM = "Dirección Nacional de Migraciones (DNM; until 2022 Dirección General de Migraciones, DGM)"

MANUALES = [
    ("manuales/2023_Manual-Servidores-Publicos-de-Frontera-EUROFRONT.pdf",
     "Manual para Servidores Públicos de Frontera de la Dirección Nacional de Migraciones (portada: Manual para los "
     "Guardias de Fronteras Terrestres de Paraguay; Programa EUROFRONT, financiado por la Unión Europea, 2023)",
     "2023", B + "/wp-content/uploads/2024/10/23_Manual_eurofront_Conv_2023_DEF_compressed.pdf", "guidance",
     "Manual for border officials of the National Migration Directorate (border checks, entry/refusal, documents, "
     "vulnerable persons; produced with the EU EUROFRONT programme, 2023)"),
    ("manuales/2023_Anexos-Manual-Servidores-Publicos-de-Frontera.pdf",
     "Anexos del Manual para los Servidores Públicos de Frontera de la DNM",
     "2023", B + "/wp-content/uploads/2024/10/24_Anexos_del_Manual_REV_final_compressed.pdf", "guidance",
     "Annexes to the manual for border officials of the DNM"),
]

# number/year -> (kind, English gloss, exact date if known)
RES_KEEP = {
    "496/2026": ("procedural act", "procedure for issuing the Neighbourhood Border Transit Document (DTVF) for "
                 "the linked border towns of Brazil", ""),
    "407/2026": ("procedural act", "unified criteria of economic solvency for permanent residence", "2026-05-28"),
    "376/2026": ("procedural act", "procedure for cancelling temporary or permanent residence for unjustified "
                 "absence from the country, and for requests to authorise absences", ""),
    "081/2026": ("procedural act", "amends art. 5 of the annex to Resolution 710/2024 (criteria for granting "
                 "residence under the special regime and permanent residence under Law 6984/2022)", "2026-01-26"),
    "754/2024": ("procedural act", "acceptance of documents in the particular situations met in residence "
                 "applications", ""),
    "749/2024": ("procedural act", "procedure for the offices that hand over residence cards and certificates", ""),
    "1096/2012": ("procedural act", "exemption from the fine for Paraguayan citizens who hold another "
                  "nationality", ""),
    "859/2012": ("procedural act", "collection of documents issued by the migration directorate (by third "
                 "parties under notarial power)", ""),
    "563/2016": ("procedural act", "procedure for the entry of foreigners who are public figures", ""),
    "543/2016": ("procedural act", "visa requirement for entry into the country", ""),
    "296/2016": ("guidance", "approves the manual of procedures for foreign victims of trafficking in "
                 "persons", ""),
    "062/2019": ("procedural act", "procedure and requirements for temporary residence under Law 978/96 for "
                 "Venezuelan citizens", ""),
    "295/2016": ("procedural act", "procedure for receiving documents at the registry of the general secretariat "
                 "and requirements for applications", ""),
    "701/2021": ("procedural act", "requirements and procedure for presenting criminal-record certificates of the "
                 "country of origin in residence applications", ""),
    "128/2020": ("procedural act", "temporary suspension of the fingerprint step of Resolution 621/2016 (COVID-19)",
                 ""),
    "151/2020": ("procedural act", "procedure at the migration control posts for nationals resident abroad and "
                 "vice versa during the COVID-19 emergency", ""),
    "152/2020": ("procedural act", "extends art. 1 of Resolution 151/2020 (control-post procedure, COVID-19)", ""),
    "230/2020": ("procedural act", "amends Resolution 3484/2013 on the evidence of economic solvency for temporary "
                 "and permanent admission", ""),
    "311/2020": ("procedural act", "receipt of documents from foreigners outside the country through third "
                 "parties (art. 41 of Law 978/96)", ""),
    "476/2020": ("procedural act", "sanitary procedure for entry and exit at the land border crossings (gradual "
                 "reopening, COVID-19)", ""),
    "477/2020": ("procedural act", "amends art. 5 of Resolution 476/2020", ""),
    "502/2020": ("procedural act", "amends art. 1 of Resolution 477/2020", ""),
}

# Known to exist, not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Protocolo de Actuación para la Detección Temprana de Situaciones de Trata de Personas en Puestos de Control "
     "Migratorio (actualización aprobada por la DNM)", "2026-07-30",
     "https://www.hoy.com.py/nacionales/2026/07/30/aprueban-protocolo-para-detectar-casos-de-trata-en-puestos-de-control-fronterizo",
     "reported in the press as approved; not published on migraciones.gov.py (not in /resoluciones/ or /mecip/)"),
    ("Resolución DNM N.° 710/2024 (criterios para el otorgamiento de la residencia del régimen especial y de la "
     "residencia permanente, Ley 6984/2022) y su modificatoria N.° 124/2025", "2024",
     B + "/resoluciones/", "cited by Resolution 081/2026; not on the resolutions page"),
    ("Resolución DGM N.° 3484/2013 (requisitos de solvencia económica para la admisión temporal y permanente)", "2013",
     B + "/resoluciones/", "cited by Resolution 230/2020; not on the resolutions page"),
    ("Resolución DNM N.° 577/2024 (Protocolo de Facilitación Migratoria para Eventos)", "2024",
     B + "/protocolo-de-facilitacion-migratoria-para-eventos/",
     "only an applicant-facing summary page; the resolution is not published"),
    ("Protocolo consular de respuesta a víctimas de trata de personas (Ministerio de Relaciones Exteriores)", "2024-12",
     "https://www.mre.gov.py/",
     "www.mre.gov.py robots.txt disallows ClaudeBot and anthropic-ai (Disallow: /); not requested"),
    ("Procedimientos de la Comisión Nacional de Refugiados (CONARE) para la determinación de la condición de refugiado",
     "", "https://www.mre.gov.py/",
     "CONARE sits in the Foreign Ministry; its site is excluded by robots.txt for AI agents; no manual found elsewhere"),
]

blocked, errors, last_hit, rules = {}, {}, {}, {}
failures, rows = [], []
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
    host = host_of(url)
    if host in blocked:
        return None
    wait(host)
    try:
        with urllib.request.urlopen(urllib.request.Request(quote_url(url), headers={"User-Agent": UA}),
                                    timeout=900) as r:
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
            print(f"  giving up on {host}")
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
        print(f"  page failed: {url}")
        return None
    text = r[0].decode("utf-8", "replace")
    if len(text) < 3000 and re.search(r"_Incapsula_Resource|Just a moment|captcha", text, re.I):
        blocked[host_of(url)] = "bot-check page"
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


def fetch(rel, title, date, url, kind, title_en, body=DNM):
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
            print(f"  NOT A PDF {url}")
            return
        if len(r[0]) > MAX_ONE:
            (OUT / ".large" / rel).parent.mkdir(parents=True, exist_ok=True)
            tmp.rename(OUT / ".large" / rel)
            return
        tmp.rename(dest)
        stats["new"] += 1
        print(f"  saved {rel}")
    rows.append((rel, title, date, url, kind, title_en, body))


def text_of(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def source_manuales():
    print("manuales: border manual (MECIP page, 'Procedimientos')")
    for item in MANUALES:
        fetch(*item)


def source_resoluciones():
    print("resoluciones: resolutions of the Director that set procedure or criteria")
    page = get_page(B + "/resoluciones/")
    if not page:
        return
    seen = set()
    for tr in re.findall(r"(?s)<tr\b.*?</tr>", page):
        cells = [text_of(c) for c in re.findall(r"(?s)<td\b.*?</td>", tr)]
        h = re.search(r'href="([^"]+\.pdf)"', tr, re.I)
        if len(cells) < 2 or not h:
            continue
        m = re.match(r"(\d{4})\s+Resoluci[oó]n\s+(DNM|DGM)\s+(\d+)", cells[0])
        if not m:
            continue
        year, body, num = m.group(1), m.group(2), m.group(3)
        key = f"{int(num):03d}/{year}"
        if key not in RES_KEEP or key in seen:
            continue
        seen.add(key)
        kind, gloss, exact = RES_KEEP[key]
        url = urllib.parse.urljoin(B + "/", html.unescape(h.group(1)))
        date = exact or year
        desc = cells[1]
        fetch(f"resoluciones/{date}_Resolucion-{body}-{int(num):03d}-{year}.pdf",
              f"Resolución {body} N.° {int(num):03d}/{year}: {desc}", date, url, kind,
              f"Resolution {body} {int(num):03d}/{year} of the migration directorate: {gloss}")
    for key in sorted(set(RES_KEEP) - seen):
        failures.append((f"Resolución {key}", key.split("/")[1], B + "/resoluciones/",
                         "no longer listed on the resolutions page"))


SOURCES = {"manuales": source_manuales, "resoluciones": source_resoluciones}


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def main():
    wanted = [a for a in sys.argv[1:] if a in SOURCES] or list(SOURCES)
    OUT.mkdir(exist_ok=True)
    idx = OUT / "index.tsv"
    old = {}
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
    kinds = {}
    for r in final.values():
        kinds[r[4]] = kinds.get(r[4], 0) + 1
    print(f"done: {len(final)} documents in index ({kinds}), {stats['new']} new, {len(failures)} failures, "
          f"closed hosts: {blocked or 'none'}")
    if on_disk - set(final):
        print("files without an index row:", sorted(on_disk - set(final)))


if __name__ == "__main__":
    main()

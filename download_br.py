#!/usr/bin/env python3
"""Brazil: published guidance and procedure-setting acts for immigration, residence,
naturalisation and refugee decisions.

    python3 download_br.py            # everything
    python3 download_br.py library    # one source: library | refugio | pf | mre | archive

Brazil has no single case-officer manual. What is published falls into two groups:

  guidance         CONARE technical notes (country-of-origin studies that tell the
                   refugee committee how to decide a nationality's claims), the
                   SISCONARE manuals for Federal Police staff who register asylum
                   claims, the 2010 consular manual (Manual do Servico Consular e
                   Juridico) and a few handbooks for front-line staff.
  procedural act   the numbered acts officers actually work from: CONARE and CNIg
                   resolucoes normativas, portarias (ministerial, interministerial,
                   Federal Police), despachos.

Sources (see br/NOTES.txt for what was checked and what is missing):

  library  bibliotecadigital.mj.gov.br  Justice Ministry digital library (DSpace); items are
           found by walking its subject index (the site search is closed to robots)
  refugio  www.gov.br/mj  CONARE pages: technical notes, SISCONARE manuals, resolutions,
           portarias, despachos
  pf       www.gov.br/pf  Federal Police immigration co-ordination (CGPI) portarias
  archive  web.archive.org  copies of the CNIg / Portal de Imigração files (CNIg normative
           resolutions, joint resolutions, service orders and technical notes of the labour-
           immigration unit, DEMIG and other portarias) and of three gazette pages; both
           portaldeimigracao.mj.gov.br and www.in.gov.br refuse this machine
  mre      conhecimento.fgv.br  the 2010 consular manual as handed to candidates of the
           foreign-service entrance exam (the ministry itself does not publish it)

Rules followed: robots.txt of every host is read first and obeyed; one request at a
time, at least 1.2 s apart per host; a host that answers 403 or 429, or resets the
connection three times in a row, is not asked again in that run. Files already
present are skipped; br/index.tsv and br/not-obtained.tsv are rebuilt on every run.
Standard library only.
"""
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "br"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.2
HOST_DELAY = {"bibliotecadigital.mj.gov.br": 3.0, "web.archive.org": 4.0}   # this server starts dropping connections when asked faster
MAX_BYTES = 500_000_000
MAX_FILES = 1500
MAX_ONE = 80_000_000

LIB = "https://bibliotecadigital.mj.gov.br"
MJ = "https://www.gov.br/mj/pt-br/assuntos/seus-direitos/refugio"
PF = "https://www.gov.br/pf/pt-br/assuntos/imigracao"

# ------------------------------------------------------------------ fetching

last = {}        # host -> time of last request
blocked = {}     # host -> reason
resets = {}      # host -> consecutive connection failures
robots = {}      # host -> list of (allow?, regex)
problems = []    # (url, reason) collected for not-obtained.tsv


def host_of(url):
    return urllib.parse.urlsplit(url).netloc


def quote_url(u):
    p = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(p._replace(path=urllib.parse.quote(p.path, safe="/%@+,;=()")))


def raw_get(url, limit=MAX_ONE):
    """One polite request. Returns (bytes, final_url) or raises."""
    host = host_of(url)
    wait = HOST_DELAY.get(host, DELAY) - (time.time() - last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last[host] = time.time()
    req = urllib.request.Request(quote_url(url), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(limit + 1)
        final = r.geturl()
    last[host] = time.time()
    if len(data) > limit:
        raise ValueError("larger than %d MB" % (limit // 1_000_000))
    return data, final


def load_robots(host):
    """Read robots.txt once per host; keep the rules of the '*' group."""
    if host in robots or host in blocked:
        return
    rules = []
    try:
        data, _ = raw_get("https://%s/robots.txt" % host, 2_000_000)
        resets[host] = 0
        group, mine = [], False
        seen_rule = False
        for line in data.decode("utf-8", "replace").splitlines():
            line = line.split("#")[0].strip()
            if ":" not in line:
                continue
            key, val = [x.strip() for x in line.split(":", 1)]
            key = key.lower()
            if key == "user-agent":
                if seen_rule:
                    mine, seen_rule = False, False
                if val == "*":
                    mine = True
            elif key in ("disallow", "allow"):
                seen_rule = True
                if mine and val:
                    pat = re.escape(val).replace(r"\*", ".*")
                    if pat.endswith(r"\$"):
                        pat = pat[:-2] + "$"
                    rules.append((key == "allow", len(val), re.compile(pat)))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            blocked[host] = "HTTP %d on robots.txt" % e.code
            print("  BLOCKED by %s (HTTP %d on robots.txt); host not used" % (host, e.code))
            return
        # 404 and the like: no robots.txt, nothing is disallowed
    except Exception as e:                           # noqa: BLE001
        blocked[host] = "robots.txt unreadable (%s)" % e
        print("  %s: robots.txt unreadable (%s); host not used" % (host, e))
        return
    robots[host] = rules


def allowed(url):
    host = host_of(url)
    load_robots(host)
    if host in blocked:
        return False
    p = urllib.parse.urlsplit(quote_url(url))
    path = p.path + ("?" + p.query if p.query else "")
    best = (True, -1)
    for allow, n, rx in robots.get(host, []):
        if rx.match(path) and (n > best[1] or (n == best[1] and allow)):
            best = (allow, n)
    return best[0]


def get(url):
    """Return bytes or None. Records why a request was not made or failed."""
    host = host_of(url)
    if not allowed(url):
        problems.append((url, blocked.get(host) or "disallowed by robots.txt"))
        return None
    try:
        data, _ = raw_get(url)
        resets[host] = 0
        return data
    except urllib.error.HTTPError as e:
        resets[host] = 0
        if e.code in (403, 429):
            blocked[host] = "HTTP %d" % e.code
            print("  BLOCKED by %s (HTTP %d); not asking this host again" % (host, e.code))
        problems.append((url, "HTTP %d" % e.code))
    except Exception as e:                           # noqa: BLE001 - no retry, report
        resets[host] = resets.get(host, 0) + 1
        if resets[host] >= 3:
            blocked[host] = "three connection failures in a row"
            print("  GIVING UP on %s after three failures in a row" % host)
        problems.append((url, str(e)[:120]))
    return None


def page(url):
    data = get(url)
    return data.decode("utf-8", "replace") if data else ""


# ------------------------------------------------------------------ helpers

MONTHS = {m: i + 1 for i, m in enumerate(
    "janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro".split())}
MONTHS["marco"] = 3
EN_MONTHS = ("January February March April May June July August September October "
             "November December").split()


def clean(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def pt_date(s):
    m = re.search(r"(\d{1,2})[ºo°]?\s+de\s+([a-zç]+)\s+de\s+(\d{4})", s, re.I)
    if m and m.group(2).lower() in MONTHS:
        return "%s-%02d-%02d" % (m.group(3), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"de\s+([a-zç]+)\s+de\s+(\d{4})", s, re.I)
    if m and m.group(1).lower() in MONTHS:
        return "%s-%02d" % (m.group(2), MONTHS[m.group(1).lower()])
    return ""


ACT_EN = [
    ("Portaria Interministerial", "Interministerial Ordinance"),
    ("Portaria Conjunta", "Joint Ordinance"),
    ("Portaria Normativa", "Normative Ordinance"),
    ("Portaria", "Ordinance"),
    ("Resolução Normativa", "Normative Resolution"),
    ("Resolução Conjunta", "Joint Resolution"),
    ("Resolução Administrativa", "Administrative Resolution"),
    ("Resolução Recomendada", "Recommendatory Resolution"),
    ("Resolução", "Resolution"),
    ("Instrução Normativa", "Normative Instruction"),
    ("Despacho", "Order"),
    ("Regimento Interno", "Internal Rules"),
]


def gloss(title):
    """Mechanical English rendering of an act's formal title."""
    t = title
    for pt, en in ACT_EN:
        if t.lower().startswith(pt.lower()):
            t = en + t[len(pt):]
            break
    t = re.sub(r"\bn(?:\.?[º°]|o\.?(?=\s*\d))\s*", "No. ", t, flags=re.I)

    def d(m):
        mon = MONTHS.get(m.group(2).lower())
        return " of %d %s %s" % (int(m.group(1)), EN_MONTHS[mon - 1], m.group(3)) if mon else m.group(0)
    t = re.sub(r",?\s+de\s+(\d{1,2})[ºo°]?\s+(?:de\s+)?([a-zçA-ZÇ]+)\s+(?:de\s+)?(\d{4})", d, t)
    return t


def slug(s, n=90):
    s = urllib.parse.unquote(s)
    for a, b in zip("áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇºª", "aaaaeeiooouc" + "AAAAEEIOOOUC" + "oa"):
        s = s.replace(a, b)
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")
    m = re.search(r"\.[A-Za-z0-9]{2,5}$", s)
    ext = m.group(0) if m else ""
    stem = s[:len(s) - len(ext)]
    if len(stem) > n and len(stem) % 2 == 0 and stem[:len(stem) // 2] == stem[len(stem) // 2:]:
        stem = stem[:len(stem) // 2]                 # gov.br sometimes doubles a file name
    return (stem[:n].strip("-.") or "x") + ext


rows = []        # index rows: (file, title, date, source_url, kind, body, title_en)
stats = {"new": 0, "bytes": 0}


def total_size():
    return sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())


def pdf_ok(path):
    """True if pdfinfo (when installed) can read the file."""
    exe = shutil.which("pdfinfo")
    if not exe:
        return True
    try:
        return subprocess.run([exe, str(path)], capture_output=True, timeout=60).returncode == 0
    except Exception:                                # noqa: BLE001
        return False


def save(url, rel, title, date, kind, body, title_en):
    """Fetch url into br/<rel> unless it is there already; add an index row if present."""
    dest = OUT / rel
    if not (dest.exists() and dest.stat().st_size > 0):
        if stats["bytes_total"] > MAX_BYTES or stats["files_total"] >= MAX_FILES:
            problems.append((url, "size or file cap reached"))
            return False
        data = get(url)
        if data is None:
            return False
        ext = dest.suffix.lower()
        if ext == ".pdf" and not data.lstrip()[:5].startswith(b"%PDF"):
            problems.append((url, "not a PDF (error or bot-check page?)"))
            return False
        if ext in (".docx", ".odt") and not data.startswith(b"PK"):
            problems.append((url, "not a document file"))
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if ext == ".pdf" and not pdf_ok(dest):
            dest.unlink()
            problems.append((url, "pdfinfo cannot read the file"))
            return False
        stats["new"] += 1
        stats["bytes_total"] += len(data)
        stats["files_total"] += 1
        print("  saved %s (%d kB)" % (rel, len(data) // 1024))
    rows.append((rel, title, date, url, kind, body, title_en))
    return True


def links_in(markup):
    """(absolute href, link text) pairs of the content area of a gov.br page."""
    m = re.search(r"<main.*?</main>", markup, re.S)
    part = m.group(0) if m else markup
    out, seen = [], set()
    for h, x in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', part, re.S):
        h = html.unescape(h).strip().split("#")[0]
        if h.endswith("/view"):
            h = h[:-5]
        if re.search(r"facebook\.com|linkedin\.com|twitter\.com|whatsapp|/@@search", h):
            continue
        if h.startswith("http") and h not in seen:
            seen.add(h)
            out.append((h, clean(x)))
    return out


# ------------------------------------------------------------------ source: MJ digital library

SUBJECTS = """Refugiado|Refugiados|Refugiados, Brasil|Migração|Migrações|Migrante|Imigração|Imigração Ilegal
|Imigração Laboral|Imigração laboral|Imigração, Brasil|Imigrante|Imigrantes|Emigrante|Estrangeiro
|Estrangeiro tripulante|Estrangeiro, solicitação|Estrangeiros|Naturalização|Naturalização especial
|Naturalização especial laboral|Naturalização especial por casamento|Naturalização extraordinária
|Naturalização ordinária|Naturalização provisória|Visto|Visto de Residência CPLP|Visto de trabalho
|Visto de visita|Visto permanente|Visto temporário|Visto temporário de estudante
|Visto temporário sem vinculo empregatício|Vistos|Apatridia|Expulsão|Expulsão de estrangeiro|Deportação
|Nacionalidade|Asilo político|Retirada compulsória|Repatriação|Repatriação e deportação|Venezuela|Haitianos
|Acolhida humanitária|Autorização de entrada no Brasil|Autorização de permanência|Autorização de residência
|Autorização de residência no Brasil|Autorização de trabalho|Residente fronteiriço|Residência|Residência CPLP
|Residência no Brasil|Residência para Nacionais dos Estados Partes do MERCOSUL|Residência permanente
|Residência provisória|Residência provisória, regulamento|Residência temporária|Permanência
|Permanência definitiva|Permanência do estrangeiro no País|Permanência no país
|Permanência no território nacional|Permanência provisória|Regularização migratória|Registro de estrangeiro
|Registro de estrangeiros|Registro Nacional Migratório|Carteira de identidade do estrangeiro
|Carteira de identidade para estrangeiro|Carteira de Registro Nacional Migratório|Reunião familiar
|Trabalhador estrangeiro|Trabalhador migrante|Entrada e saída do território nacional|Entrada no país
|Impedimento de ingresso|Impedimento de ingresso no País|Afeganistão|Crise humanitária|Crise migratória"""
SUBJECTS = [s.strip() for s in SUBJECTS.replace("\n", "").split("|")]

LIB_ACT = re.compile(r"^(Portaria|Resolução|Instrução Normativa|Despacho|Orientação|Nota Técnica|Parecer|Circular)", re.I)
LIB_KEEP = re.compile(
    r"estrangeir|imigra|migrat|migrant|refugi|ref[úu]gio|naturaliz|\bvisto|ap[áa]trid|expuls|deporta|repatria"
    r"|asilad|resid[êe]ncia|perman[êe]ncia definitiva|perman[êe]ncia no|acolhida|nacionalidade"
    r"|entrada no pa[ií]s|impedimento de ingresso|registro nacional migrat|fronteiri[çc]o", re.I)
LIB_DROP = re.compile(
    r"for[çc]a nacional|terra ind[íi]gena|penitenci|di[áa]rias|nomea[çc][ãa]o de candidatos|arma de fogo"
    r"|resid[êe]ncia m[ée]dica|resid[êe]ncia jur[íi]dica|identidade funcional|migra[çc][ãa]o de (dados|sistema)", re.I)
# Handbooks in the library that are written for the staff who deal with migrants, kept as guidance.
LIB_GUIDANCE = {
    "9718": "Guide to assisting migrants, refugees, trafficking victims and returned Brazilians in "
            "vulnerable situations in border areas (MT Brasil project handbook for federal front-line staff)",
    "9719": "Practical guide to assisting migrants, refugees, trafficking victims and returned Brazilians "
            "in vulnerable situations in border areas (short field version)",
    "10375": "Recognition of refugees by Brazil: annotated decisions of CONARE (casebook of the refugee "
             "committee's reasoning)",
    "10376": "Humanised reception post for migrants (deported and non-admitted persons, Guarulhos airport): "
             "write-up of the practice and working method",
}
# Library records left out: one person's expulsion order, fee tables, committees and other acts that
# set no procedure for immigration decisions.
LIB_SKIP = {"348", "4860", "6644", "6646", "6647", "6648", "6652", "3162", "11708", "14724"}
BODY_EN = [
    ("CONARE", "CONARE (Comitê Nacional para os Refugiados)"),
    ("CNIG", "CNIg (Conselho Nacional de Imigração)"),
    ("CNI_", "CNIg (Conselho Nacional de Imigração)"),
    ("DPF", "Polícia Federal"),
    ("DG_PF", "Polícia Federal"),
    ("DIREX", "Polícia Federal"),
    ("SENAJUS", "Secretaria Nacional de Justiça (MJSP)"),
    ("SNJ", "Secretaria Nacional de Justiça (MJ)"),
    ("PRI_", "Ministérios (portaria interministerial)"),
    ("GM", "Ministério da Justiça (Gabinete do Ministro)"),
]


def lib_items():
    """Walk the subject index; return {handle: listing title}."""
    items = {}
    for s in SUBJECTS:
        t = page(LIB + "/browse?type=subject&rpp=100&value=" + urllib.parse.quote(s))
        for h, ti in re.findall(r'<td headers="t2" ><a href="/handle/1/(\d+)">(.*?)</a>', t, re.S):
            items.setdefault(h, clean(ti))
        if host_of(LIB) in blocked:
            break
    return items


def lib_meta(handle, cache):
    if handle in cache:
        return cache[handle]
    t = page("%s/handle/1/%s" % (LIB, handle))
    if not t:
        return None
    meta = {}
    for k, v in re.findall(r'<meta name="(DC[^"]+|citation_pdf_url)" content="([^"]*)"', t):
        meta.setdefault(k, []).append(html.unescape(v).strip())
    meta["bitstreams"] = sorted(set(re.findall(r'href="(/bitstream/1/%s/[^"]+)"' % handle, t)))
    cache[handle] = meta
    return meta


def do_library():
    print("library: bibliotecadigital.mj.gov.br")
    cache_file = OUT / "listings" / "library-items.json"
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    items = lib_items()
    if not items:                                    # site unreachable: fall back on what we know
        items = {h: (m.get("DC.title") or [""])[0] for h, m in cache.items()}
    print("  %d items under %d subject headings" % (len(items), len(SUBJECTS)))
    used_rels = set()
    for h, listing_title in sorted(items.items(), key=lambda kv: int(kv[0])):
        if h in LIB_SKIP or not (LIB_ACT.match(listing_title) or h in LIB_GUIDANCE):
            continue
        meta = lib_meta(h, cache)
        if not meta:
            continue
        title = (meta.get("DC.title") or [listing_title])[0]
        abstract = " ".join(meta.get("DCTERMS.abstract", []))
        text = " ".join([title, abstract] + meta.get("DC.subject", []))
        if h not in LIB_GUIDANCE and (not LIB_KEEP.search(text) or LIB_DROP.search(text)):
            continue
        pdfs = [b for b in meta["bitstreams"] if b.lower().endswith(".pdf")]
        if not pdfs:
            problems.append(("%s/handle/1/%s" % (LIB, h), "no PDF attached to the library record: " + title))
            continue
        date = (meta.get("DCTERMS.created") or meta.get("DCTERMS.issued") or [""])[0][:10]
        if not re.match(r"\d{4}", date):
            date = pt_date(title)
        name = pdfs[0].rsplit("/", 1)[-1]
        body = "Ministério da Justiça"
        for key, val in BODY_EN:
            if key in name.upper():
                body = val
                break
        for c in meta.get("DC.contributor", []):
            if re.search(r"Conselho Nacional de Imigra", c):
                body = "CNIg (Conselho Nacional de Imigração)"
            elif re.search(r"Comit[êe] Nacional para os Refugiados", c):
                body = "CONARE (Comitê Nacional para os Refugiados)"
        if h in LIB_GUIDANCE:
            kind, sub, en = "guidance", "biblioteca-mj/guias", LIB_GUIDANCE[h]
            body = "Ministério da Justiça / Secretaria Nacional de Justiça"
        else:
            kind, sub = "procedural act", "biblioteca-mj/atos"
            en = gloss(title) + (" - " + LIB_EN[h] if h in LIB_EN else "")
        rel = "%s/%s_%s" % (sub, date or "nodate", slug(name))
        if rel in used_rels:                         # two records can carry the same file name
            stem, dot, ext = rel.rpartition(".")
            rel = "%s_h%s.%s" % (stem, h, ext)
        used_rels.add(rel)
        full = title + (": " + abstract if abstract else "")
        save(LIB + pdfs[0], rel, full, date, kind, body, en)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


# English summaries of the library acts (what the act does), keyed by library handle.
LIB_EN = dict(line.split("|", 1) for line in """
8838|extends to 30 June 1987 the deadline for re-registration of foreigners holding identity cards
8839|extends to 30 September 1987 the deadline for re-registration of holders of foreigner identity cards
8841|extends to 20 March 1988 the validity of certified copies of the foreigner identity card with the re-registration receipt as identification
8842|extends by four years the validity of identity cards of foreigners with permanent visas
1574|applications for permanent visas for foreign investors in companies in export-processing zones
1630|authorises the Justice Ministry to grant permanent stay to foreigners with refugee or asylee status
884|approves the naturalisation application forms
905|procedure for applying for naturalisation
898|procedure for applying for naturalisation, provisional naturalisation certificates and confirmation of provisionally granted nationality
1536|visa or permanent stay on family-reunion grounds
1629|permanent stay for asylees or refugees and their families
1631|permanent visa or permanent stay for foreigners who lost permanent status through absence from the country
2004|work authorisation for foreign artists and athletes without an employment relationship
1607|departure from the country of foreigners holding temporary visas
2019|repeals item VI of art. 22 of Normative Resolution 15/1998 on permanent visas for retirees
2018|permanent visas for foreign retirees (as amended by Normative Resolution 20/1998)
1575|permanent visas for foreign investors, administrators or directors of companies in export-processing zones
1980|work authorisation for the purpose of a permanent visa for individual foreign investors
2005|engagement of crew of foreign vessels under charter, service and risk contracts
2003|work authorisation for foreign artists and athletes without an employment relationship
1524|temporary or permanent visas on family-reunion grounds
2017|permanent visas for foreign retirees
1596|visas for foreigners coming to study in Brazil under educational exchange programmes
1939|visas for foreign seafarers employed on foreign cruise ships operating in Brazilian waters
5787|situation of refugees who hold permanent stay
1956|engagement of crew of foreign vessels and of technicians under service and risk contracts
1670|procedure for work authorisation for foreigners
748|sub-delegates to the Department of Foreigners the power to authorise, in exceptional reasoned cases, a change of name after naturalisation
755|amends art. 1 of Ordinance 218/2004
1669|procedure for work authorisation for foreigners
1977|work authorisation for the purpose of a permanent visa for individual foreign investors
1644|authorisation for refugees to travel abroad, issue of Brazilian passports to refugees, and loss of refugee status as a result of unauthorised travel
870|new models of naturalisation certificate
881|refused applications for extension of temporary visas and for permanent stay
1936|visas for foreign seafarers employed on foreign cruise ships operating in Brazilian waters
2002|work authorisation for foreign artists and athletes without an employment relationship
1929|visas for foreign seafarers employed on foreign cruise ships operating in Brazilian waters
1951|engagement of foreign professionals to work aboard foreign vessels or platforms
891|documents required in naturalisation proceedings
1668|procedure for work authorisation for foreigners
8844|amends the sole paragraph of art. 1 of Ordinance 526/1955
1639|referral by CONARE to the National Immigration Council of cases that may be considered special or humanitarian situations
1533|criteria for temporary or permanent visas, or authorisation to stay, for partners in a stable union, regardless of sex
1593|visas for foreign professionals employed on foreign cruise ships on long-haul voyages to Brazil
882|time limits for requests for reconsideration and appeals within the Department of Foreigners
1975|authorisation for the purpose of a permanent visa for individual foreign investors
868|electronic issue of negative and positive naturalisation certificates on the ministry website
953|respective duties of the National Justice Secretariat and the Federal Police in granting provisional residence to irregular foreigners (2009 regularisation, Law 11.961)
921|procedure for examining omitted or special cases for residence under the 2009 regularisation (Law 11.961)
952|extends the effects of the Mercosur, Bolivia and Chile Residence Agreement to Bolivians covered by the Brazil-Bolivia regularisation agreement
1586|visas for foreigners coming to Brazil for internships
1455|permanent visa or stay for foreigners who are victims of human trafficking
460|sub-delegates to the head of the Nationality and Naturalisation Division the power to authorise changes to foreigners' registration records and name changes
897|procedure for converting provisional residence granted under SNJ Ordinance 22/2009 into permanent residence
915|procedure for converting provisional residence under Law 11.961/2009 into permanent residence
892|procedure for granting definitive residence under the agreement with Argentina on permanent stay for holders of temporary visas and tourists
1541|permanent visa on humanitarian grounds for nationals of Haiti (art. 16 of Law 6.815/1980)
762|sub-delegates to the National Secretary of Justice the power to grant nationality and decide on equality of rights, civil obligations and political rights
914|permanent registration of Angolan and Liberian nationals who had refugee status
1480|work authorisation and temporary visas for foreigners working exclusively on the 2014 World Cup and 2016 Olympic and Paralympic Games
1667|procedure for work authorisation for foreigners
1662|procedure and request form for family-reunion applications of refugees
5788|appropriate (humanitarian) visas for persons forcibly displaced by the armed conflict in Syria
1487|temporary or permanent visas and permanent stay on family-reunion grounds
1476|temporary visas for foreigners coming to carry out studies and surveys needed to prepare project proposals
732|sub-delegates to the Department of Foreigners the power to authorise, in exceptional reasoned cases, a change of name after naturalisation
922|simplification of the procedure for permanent stay and registration of foreigners on grounds of family reunion, offspring, marriage and stable union, and related applications
951|amends Ordinance 1.351/2014 on the simplified permanent-stay and registration procedure
955|amends the annex to Ordinance 1.351/2014 on the simplified permanent-stay and registration procedure
957|amends Ordinance 1.351/2014
948|procedures for permanent stay and registration of foreigners on grounds of family reunion, offspring, marriage and stable union, extension of stay and change of visa
928|implements CNIg Normative Resolution 110/2014 on provisional stay, on a special basis, for foreigners in criminal proceedings or serving sentences
863|documents required for changes to registration records and annotation of nationality in the foreigners' register
864|documents required in naturalisation proceedings
5784|extends the validity of the refugee identity card from two to five years
5786|extends the validity of Normative Resolution 17/2013 (visas for persons displaced by the Syrian conflict)
1569|adopts the asylum application form and the appeal form and amends CONARE Normative Resolution 18
916|procedures for naturalisation, changes to foreigners' registration records, annotation of nationality and equality of rights between Portuguese and Brazilians
913|exempts refugees and asylees from fees for foreigner registration and the foreigner identity card
1974|authorisation for the purpose of a permanent visa for individual foreign investors
1454|stay in Brazil for foreigners who are victims of human trafficking and/or slave-like labour
886|time limit for registration with the Federal Police after a regularisation application is granted, and related requests
1687|procedure for passport applications and travel abroad by refugees and asylum seekers
1453|change from temporary student status to temporary work status
1415|temporary residence for nationals of bordering countries
310|stay in Brazil for foreigners who are victims of human trafficking
1570|adopts the refugee-status application form, the family-extension form and the appeal form, and amends Normative Resolution 18
1663|procedures for residence authorisations within the competence of the Labour Ministry (work-based residence)
2056|residence authorisation for work without an employment relationship for seafarers aboard foreign cruise ships
2020|residence authorisation for work without an employment relationship for seafarers aboard foreign vessels or platforms
1674|special cases for granting residence authorisation linked to labour matters
8029|residence authorisation for work with an employment relationship as a professional athlete
2987|time limits for copying and authenticating documents from foreigners' files
936|procedures for processing applications for residence authorisation, registration and issue of the National Migration Registry Card (CRNM)
298|procedure for residence authorisation in cases not expressly provided for in the Migration Law and its regulation
1434|procedure for recognising statelessness and the facilitated naturalisation that follows
890|procedure for assessing economic hardship for exemption from fees for regularisation documents
2369|procedure for loss and cancellation of residence authorisation
1967|residence authorisation for nationals of bordering countries where the Mercosur Residence Agreement is not in force
924|procedures for temporary visas and residence authorisation for study
927|procedures for temporary visas and residence authorisation for health treatment
875|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons resident in Haiti
880|procedures for naturalisation, equality of rights, loss and reacquisition of Brazilian nationality
888|temporary visa and residence authorisation for family reunion
1969|amends Interministerial Ordinance 9/2018 (residence for nationals of bordering countries)
1440|amends Interministerial Ordinances 5/2018 (statelessness) and 11/2018 (naturalisation)
1682|regulates art. 2 of Law 9.474/1997: extension of refugee status to family members
2608|amends Interministerial Ordinance 10/2018 (humanitarian visas for Haitians)
3276|residence authorisation linked to labour for applicants for refugee status before CONARE
2496|procedures for residence authorisation for persons who formerly held Brazilian nationality
2245|procedures for residence authorisation, registration and CRNM issue for unaccompanied or separated migrant children and adolescents
1421|instructions on refusing entry to persons recorded in migration-control systems as members of violent football supporter groups
1970|amends Interministerial Ordinance 9/2018 (residence for nationals of bordering countries)
883|sub-delegates powers to the General Co-ordinator of Labour Immigration and the Co-ordinator of Migration Cases in the Department of Migration and regulates administrative appeals
1773|procedure for converting diplomatic or official visas into residence authorisation
280|refusal of entry, repatriation and summary deportation of dangerous persons or persons who have acted against constitutional principles
887|residence authorisation for Cuban nationals who took part in the Mais Médicos programme
885|residence authorisation for nationals of the Dominican Republic with pending asylum claims in Brazil
1653|rules for refusing entry to senior officials of the Venezuelan regime
1677|amends CNIg Normative Resolution 23/2017 (special labour-related cases)
1664|amends CNIg Normative Resolution 1/2017 (work-based residence procedure)
874|temporary visa and residence authorisation on humanitarian-reception grounds for persons affected by the armed conflict in Syria
1419|procedures for applications for special naturalisation
281|refusal of entry, repatriation and deportation of dangerous persons or persons who have acted against constitutional principles (replaces Ordinance 666/2019)
1391|instructions on refusing entry to persons recorded as members of violent football supporter groups
1226|how to fill in the federal payment form (GRU) for work- and investment-based residence applications
2049|temporary visa and residence authorisation on the basis of retirement or survivor's pension
876|residence authorisation for nationals of Senegal with pending asylum claims in Brazil
866|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons resident in Haiti
2503|COVID-19: exceptional temporary restriction on entry of foreigners coming from Venezuela
1046|COVID-19: exceptional temporary restriction on entry of foreigners coming from listed countries
749|COVID-19: exceptional temporary restriction on entry of foreigners coming from listed countries
776|COVID-19: exceptional temporary restriction on entry by land of foreigners coming from Uruguay
750|COVID-19: exceptional temporary restriction on entry of foreigners coming from listed countries
323|residence authorisation for victims of human trafficking, slave labour or rights violations aggravated by migration status
752|COVID-19: exceptional temporary restriction on entry of foreigners by water transport
751|COVID-19: exceptional temporary restriction on entry of foreigners
781|COVID-19: exceptional temporary restriction on entry of foreigners coming from Venezuela
573|COVID-19: exceptional temporary restriction on entry of foreigners coming from listed countries
333|COVID-19: extends the restriction on entry by land of foreigners coming from Uruguay
758|COVID-19: exceptional temporary restriction on entry of foreigners by water transport
757|COVID-19: exceptional temporary restriction on entry of foreigners by air
878|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality by land
858|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
859|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
877|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
1193|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
1473|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
1613|amends CONARE Normative Resolution 18/2014 (asylum procedure) and repeals Normative Resolutions 22/2015 and 24/2017
2011|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2012|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2013|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2022|amends CNIg Normative Resolution 6/2017 (seafarers aboard foreign vessels or platforms)
2043|amends CNIg Normative Resolution 5/2017 (seafarers aboard foreign cruise ships)
2476|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2247|procedures for naturalisation, equality of rights, loss and reacquisition of nationality and revocation of loss decisions
2380|amends CONARE Normative Resolution 18/2014 (asylum procedure) and repeals Normative Resolutions 22, 24 and 32
2482|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2483|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2474|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons resident in Haiti
2490|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2723|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2722|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
2969|amends MJSP Ordinance 62/2021
3328|changes the residence period under art. 142 para. 3 of Decree 9.199/2017
3538|residence authorisation for nationals of bordering countries where the Mercosur Residence Agreement is not in force
4523|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
4524|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
4543|COVID-19: exceptional temporary restriction on entry of foreigners of any nationality
5336|temporary visa and residence authorisation on humanitarian-reception grounds for Afghans, stateless persons and persons affected by the situation in Afghanistan
5561|COVID-19: exceptional temporary measures for entry into the country
5586|COVID-19: exceptional temporary measures for entry into the country
6732|COVID-19: exceptional temporary measures for entry into the country
6733|COVID-19: exceptional temporary measures for entry into the country
6735|COVID-19: exceptional temporary measures for entry into the country
6007|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons affected by major calamity in Haiti
6736|COVID-19: exceptional temporary measures for entry into the country
6057|temporary visa and residence authorisation for immigrants without a Brazilian employer whose work can be done remotely (digital nomads)
6220|temporary visa and residence authorisation on humanitarian-reception grounds for Ukrainians and stateless persons displaced by the conflict in Ukraine
6737|COVID-19: exceptional temporary measures for entry into the country
6422|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons affected by major calamity in Haiti
8092|residence authorisation for work with an employment relationship in sporting activities
7463|temporary visa and residence authorisation on humanitarian-reception grounds for Ukrainians and stateless persons displaced by the conflict in Ukraine
7506|COVID-19: exceptional temporary measures for entry into the country
8585|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons affected by major calamity in Haiti
9312|temporary visa and residence authorisation on humanitarian-reception grounds for Ukrainians and stateless persons displaced by the conflict in Ukraine
9525|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians and stateless persons affected by major calamity in Haiti
9591|prior residence authorisation and temporary visa for family reunion for Haitians and stateless persons with family ties in Brazil
11033|temporary visa and residence authorisation for nationals of the Community of Portuguese-Language Countries under the CPLP Mobility Agreement
11325|temporary visa and residence authorisation on humanitarian-reception grounds for Afghans, stateless persons and persons affected by the situation in Afghanistan
12767|residence authorisation for victims of human trafficking, slave labour or rights violations aggravated by migration status
13504|residence authorisation for work for immigrants who completed undergraduate or postgraduate studies in Brazil
14132|temporary visa and residence authorisation on humanitarian-reception grounds
14131|temporary visa and residence authorisation on humanitarian-reception grounds for Haitians affected by major calamity
14133|residence authorisation on humanitarian-reception grounds for Ukrainians and stateless persons displaced by the conflict in Ukraine
16477|temporary visa and residence authorisation on humanitarian-reception grounds
17422|temporary visa and residence authorisation on humanitarian-reception grounds for Afghans and stateless persons, and processing of the applications
""".strip().splitlines())


# ------------------------------------------------------------------ source: gov.br/mj (CONARE)

# Technical notes and manuals: file name on gov.br -> (date, Portuguese title, English gloss).
# Filled from the documents themselves; files that turn up later are saved with "nodate".
_VEN = "Estudo de país de origem - Venezuela"
NOTES_META = {
    "sei_mj8757617estudodepaisdeorigemvenezuela.pdf": (
        "2019-06-13", "Nota Técnica nº 3/2019/CONARE_Administrativo/CONARE/DEMIG/SENAJUS/MJ - " + _VEN,
        "CONARE Technical Note 3/2019: country-of-origin study on Venezuela, proposing that the committee recognise "
        "'serious and generalised violation of human rights' (Cartagena definition, art. 1 III of Law 9.474) and "
        "decide Venezuelan claims on that basis"),
    "SEI_MJ10407688NotaTcnicaVenezuela_aditamento1.pdf": (
        "2019-12-03", "Nota Técnica nº 12/2019/CONARE_Administrativo/CONARE/DEMIG/SENAJUS/MJ - " + _VEN + " - Aditamento",
        "CONARE Technical Note 12/2019: addendum to the Venezuela study - simplified, group-based (prima facie) "
        "procedure and its criteria and exclusions"),
    "sei_08018-001832_2018_012-ago21.pdf": (
        "2020-08-25", "Nota Técnica nº 17/2020/CONARE_Administrativo/CONARE/DEMIG/SENAJUS/MJ - Venezuela: prorrogação "
        "do reconhecimento de grave e generalizada violação de direitos humanos",
        "CONARE Technical Note 17/2020: extension of the finding of serious and generalised human-rights violation "
        "in Venezuela"),
    "sei_08018-001832_2018_01notatecnicavenezuela-dez22.pdf": (
        "2021-07-01", "Nota Técnica nº 15/2021/CONARE_Nare/CONARE/DEMIG/SENAJUS/MJ - Venezuela: prorrogação do "
        "reconhecimento de grave e generalizada violação de direitos humanos",
        "CONARE Technical Note 15/2021: further extension of the Venezuela finding (to December 2022)"),
    "sei_08018-001832_2018_01-ntsiria.pdf": (
        "2020-10-28", "Nota Técnica nº 19/2020/CONARE_Administrativo/CONARE/DEMIG/SENAJUS/MJ - Estudo de país de origem - Síria",
        "CONARE Technical Note 19/2020: country-of-origin study on Syria and applicability of the 'serious and "
        "generalised violation of human rights' ground"),
    "NT_Iraque.pdf": (
        "2020-11-25", "Nota Técnica nº 26/2020/CONARE_Administrativo/CONARE/DEMIG/SENAJUS/MJ - Iraque",
        "CONARE Technical Note 26/2020: country analysis of Iraq and applicability of the 'serious and generalised "
        "violation of human rights' ground"),
    "SEI_08018.001832_2018_01Afeganistao.pdf": (
        "2020-11-25", "Nota Técnica nº 3/2020/CONARE_em_prod/CONARE/DEMIG/SENAJUS/MJ - Afeganistão",
        "CONARE Technical Note 3/2020: country analysis of Afghanistan and applicability of the 'serious and "
        "generalised violation of human rights' ground"),
    "sei_08018-001832_2018_01-nt_mali.pdf": (
        "2021-09-16", "Nota Técnica nº 1/2021/CONARE_em_prod/CONARE/DEMIG/SENAJUS/MJ - República do Mali",
        "CONARE Technical Note 1/2021: country analysis of Mali and applicability of the 'serious and generalised "
        "violation of human rights' ground"),
    "sei_08018-001832_2018_01-nt_burkinafaso.pdf": (
        "2021-09-16", "Nota Técnica nº 2/2021/CONARE_em_prod/CONARE/DEMIG/SENAJUS/MJ - Burkina Faso",
        "CONARE Technical Note 2/2021: country analysis of Burkina Faso and applicability of the 'serious and "
        "generalised violation of human rights' ground"),
    "copy2_of_manualsisconareparaapolciafederal_versao8.pdf": (
        "2021-02", "Manual Sisconare - Polícia Federal (versão 8, fevereiro de 2021)",
        "SISCONARE manual for the Federal Police, version 8 (February 2021): how police immigration staff receive, "
        "check and register asylum claims and issue the provisional protocol and document in the CONARE case system"),
}


# What each act on the CONARE pages does, keyed by a fragment of its file name (read from the documents).
GOV_EN = [
    ("n-01-do-conare", "model declaration form filled in by the Federal Police at the initial asylum request (repealed by NR 18)"),
    ("n-02-do-conare", "model questionnaire for the asylum application (repealed by NR 18)"),
    ("n-03-do-conare", "model undertaking signed before registration as a refugee with the Federal Police (repealed by NR 18)"),
    ("n-04-do-conare", "extension of refugee status to family members (repealed by NR 16)"),
    ("n-05-do-conare", "authorisation for refugees to travel abroad (repealed by NR 12)"),
    ("n-06-do-conare", "issue of the provisional protocol to asylum seekers (repealed by NR 18)"),
    ("n-07-do-conare", "time limits for procedural steps and for answering summonses (repealed by NR 11)"),
    ("n-08-do-conare", "notification of refusal of refugee status"),
    ("n-09-do-conare", "where the asylum questionnaire is filled in where there is no Caritas office (repealed by NR 18)"),
    ("n-10-do-conare", "situation of refugees who hold permanent stay"),
    ("n-11-do-conare", "publication of the notification under art. 29 of Law 9.474/1997 (repealed by NR 18)"),
    ("n-12-do-conare", "travel abroad by refugees, Brazilian passports for refugees, and loss of status for unauthorised departure (repealed by NR 18)"),
    ("n-13-do-conare", "referral by CONARE to the National Immigration Council of cases that may be treated as special situations (repealed by NR 18)"),
    ("n-14-do-conare", "the Brazilian resettlement programme"),
    ("n-15-do-conare", "issue of the provisional protocol to asylum seekers (repealed by NR 18)"),
    ("n-16-do-conare", "procedure and request form for family-reunion applications"),
    ("ResolucaoNormativan16e17", "Normative Resolutions 16 and 17 of 20 September 2013 as printed in the official gazette (family reunion; visas for persons displaced by the Syrian conflict)"),
    ("n-17-do-conare", "appropriate (humanitarian) visas for persons forcibly displaced by the armed conflict in Syria"),
    ("ResolucaoCONAREn18", "the asylum procedure: rules for lodging and processing applications for refugee status (original text)"),
    ("RN18ajustada", "the asylum procedure: rules for lodging and processing applications for refugee status, consolidated with amendments up to NR 33 - the committee's main working text"),
    ("n-19-do-conare", "regional migration and socio-economic integration project for refugees"),
    ("n-20-do-conare", "extends the validity of NR 17/2013 (visas for persons displaced by the Syrian conflict)"),
    ("n-21-do-conare", "extends the validity of the refugee identity card from two to five years"),
    ("rn22-ajustada", "adopts the asylum application form and the appeal form and amends NR 18 (as adjusted by NR 24)"),
    ("rn-no-23", "passport applications and travel abroad by refugees and asylum seekers (as amended by NR 28)"),
    ("n-24-do-conare", "adopts the refugee-status application form, the family-extension form and the appeal form, and amends NR 22"),
    ("resolucao-conjunta-n-1", "joint resolution with CONANDA, CNIg and the Public Defender: preliminary identification, care and protection of unaccompanied or separated children and adolescents"),
    ("n-25-do-conare", "extends the validity of NR 17/2013 (visas for persons displaced by the Syrian conflict)"),
    ("n-26-do-conare", "amends NR 18 to regulate when a case is closed without a decision on the merits"),
    ("n_27_conare", "regulates art. 2 of Law 9.474/1997: extension of refugee status to family members"),
    ("RESOLUONORMATIVAN31", "amends NR 18/2014 on the asylum procedure"),
    ("RegimentoConare", "internal rules of CONARE as published in the official gazette of 6 November 1998"),
    ("PRT_GM_2012_2650", "permanent registration of Angolan and Liberian nationals who had refugee status"),
    ("INTERMINISTERIALN5DE27", "procedure for recognising statelessness and the facilitated naturalisation that follows (as amended by Interministerial Ordinance 16/2018)"),
    ("INTERMINISTERIALN8DE13", "temporary visa and residence authorisation for health treatment"),
    ("despachodeconcessaocoletiva", "collective grant of residence authorisation to Haitians and stateless persons"),
    ("PORTARIADG_PFN16.362", "issue of the National Migration Registry Card and Document in electronic form"),
    ("no-40-de-1o-de-setembro", "temporary visa and residence authorisation for nationals of the Community of Portuguese-Language Countries under the CPLP Mobility Agreement"),
    ("no-42-de-22-de-setembro", "temporary visa and residence authorisation on humanitarian-reception grounds for Afghans, stateless persons and persons affected by the situation in Afghanistan"),
    ("no_49__de_24", "temporary visa and residence authorisation on humanitarian-reception grounds"),
    ("no_50__de_26", "residence authorisation on humanitarian-reception grounds for Ukrainians and stateless persons displaced by the conflict in Ukraine"),
    ("no_51__de_27", "temporary visa and residence authorisation on humanitarian-reception grounds for Haitians affected by major calamity"),
]


def gov_en(name, title):
    en = gloss(title)
    for key, what in GOV_EN:
        if key in name:
            return en + " - " + what
    return en


def do_refugio():
    print("refugio: www.gov.br/mj (CONARE)")
    body = "CONARE (Comitê Nacional para os Refugiados), CG-CONARE/MJSP"
    seen = set()

    # 1. technical notes (guidance)
    cand = []
    for u in (MJ + "/o-que-e-refugio/anexos", MJ + "/o-que-e-refugio/etapas-do-processo-de-refugio",
              MJ + "/perguntas-frequentes/faq-perguntas-frequentes"):
        cand += links_in(page(u))
    for h, text in cand:
        h = urllib.parse.urljoin(MJ + "/o-que-e-refugio/", h.replace("https://www.gov.br/../../", MJ + "/"))
        name = h.rsplit("/", 1)[-1]
        if not re.search(r"\.pdf$", name, re.I) or name in seen:
            continue
        if not re.search(r"nt[_-]|_nt|nota|estudo|08018|afeganist|iraque|siria|venezuela", name, re.I):
            continue
        seen.add(name)
        date, title, en = NOTES_META.get(name, ("", "Nota técnica do CONARE (%s)" % (text or name), "CONARE technical note"))
        save(h, "conare-notas-tecnicas/%s_%s" % (date or "nodate", slug(name)), title, date, "guidance", body, en)

    # 2. SISCONARE manuals (guidance for Federal Police staff; the applicants' manual is left out)
    for h, text in links_in(page(MJ + "/sisconare/anexos")):
        name = h.rsplit("/", 1)[-1]
        if re.search(r"manualsisconare.*pol", name, re.I) and name not in seen:
            seen.add(name)
            date, title, en = NOTES_META.get(name, ("", "Manual do Sisconare (%s)" % name, "SISCONARE manual"))
            save(h, "sisconare/%s_%s" % (date or "nodate", slug(name)), title, date, "guidance", body, en)

    # 3. CONARE normative resolutions as listed on the legislation page (procedural acts)
    gazette = []
    last_title = ""
    for h, text in links_in(page(MJ + "/legislacao/resolucoes")) + [
            x for x in cand if re.search(r"(?i)resolucao[-_]normativa|/rn-?no?-?\d", x[0])]:
        if re.search(r"in\.gov\.br|imprensanacional", h):
            gazette.append((h, text if len(text) > 8 else last_title))
            continue
        if re.match(r"RESOLU", text, re.I):
            last_title = text
        name = h.rsplit("/", 1)[-1]
        if "/refugio/" not in h or not re.search(r"\.(pdf|docx)$", name, re.I) or name in seen:
            continue
        if re.search(r"formul", name, re.I):
            continue
        seen.add(name)
        title = text if len(text) > 8 else "%s (texto publicado; %s)" % (last_title, name)
        date = pt_date(title)
        save(h, "conare-resolucoes/%s_%s" % (date or "nodate", slug(name)), title, date,
             "procedural act", "CONARE (Comitê Nacional para os Refugiados)",
             gov_en(name, title.title().replace(" De ", " de ").replace("Nº", "nº").replace("Conare", "CONARE")))

    # 4. portarias and despachos kept as files on the CONARE legislation pages (procedural acts)
    for u in (MJ + "/legislacao/portarias", MJ + "/legislacao/outros-normativos-de-interesse-de-refugiados-e-imigrantes",
              MJ + "/legislacao/despachos"):
        for h, text in links_in(page(u)):
            if re.search(r"in\.gov\.br|imprensanacional", h):
                gazette.append((h, text))
                continue
            name = h.rsplit("/", 1)[-1]
            if "/refugio/" not in h or name in seen or name in ("portarias", "despachos") \
                    or not re.search(r"(?i)portaria|PRT_|despacho|regimento", name):
                continue
            seen.add(name)
            if not name.lower().endswith(".pdf"):
                name += ".pdf"
            title = text if len(text) > 8 else urllib.parse.unquote(name)
            if re.search(r"regimento", name, re.I):
                title = "Regimento Interno do Comitê Nacional para os Refugiados (Portaria MJ nº 756, de 5 de novembro de 1998)"
            if re.search(r"despachodeconcessaocoletiva", name):
                title = ("Despachos do Departamento de Migrações (DOU de 15 de outubro de 2018): concessão coletiva "
                         "de autorização de residência para haitianos e apátridas")
            date = pt_date(title)
            who = "Polícia Federal" if re.search(r"DG_PF|DIREX", name) else \
                "MJSP / MRE (interministerial)" if re.search(r"(?i)interministerial", name) else "Ministério da Justiça"
            save(h, "mj-portarias/%s_%s" % (date or "nodate", slug(name)), title, date, "procedural act", who, gov_en(name, title))
    return gazette


# ------------------------------------------------------------------ source: gov.br/pf

def do_pf():
    print("pf: www.gov.br/pf (CGPI)")
    for h, text in links_in(page(PF + "/lei-de-migracao/publicacoes/cgpi")):
        name = h.rsplit("/", 1)[-1]
        if not name.lower().endswith(".pdf"):
            continue
        title = re.sub(r"\.pdf$", "", text).replace("DIREX_PF", "DIREX/PF")
        date = pt_date(title)
        save(h, "pf/%s_%s" % (date or "nodate", slug(name)), title, date, "procedural act",
             "Polícia Federal (Diretoria-Executiva / CGPI)", gloss(title) + PF_EN.get(date, ""))


PF_EN = {
    "2020-10-19": " - resumption of migration time limits at the Federal Police after the COVID-19 suspension",
    "2021-02-02": " - extension of the time limit for migration regularisation at the Federal Police",
}


# ------------------------------------------------------------------ source: consular manual

def do_mre():
    print("mre: consular manual (copy on conhecimento.fgv.br)")
    save("https://conhecimento.fgv.br/sites/default/files/concursos/mre/MSCJ_completo-1.pdf",
         "mre/2010_Manual-do-Servico-Consular-e-Juridico_MSCJ_completo.pdf",
         "Manual do Serviço Consular e Jurídico (MSCJ), edição 2010 - Regulamento Consular Brasileiro, 12 capítulos "
         "(inclui o capítulo sobre vistos)",
         "2010", "guidance", "Ministério das Relações Exteriores (cópia hospedada pela FGV, banca do concurso do MRE)",
         "Consular and Legal Service Manual, 2010 edition: the Foreign Ministry's binding instructions to consular "
         "posts, 12 chapters including visas. Superseded in part; the ministry does not publish the current text. "
         "Copy hosted by FGV, which ran the ministry's entrance exam.")


# ------------------------------------------------------------------ source: web.archive.org

PORTAL = "portaldeimigracao.mj.gov.br"
CDX = ("https://web.archive.org/cdx/search/cdx?url=%s/images/*&output=json&fl=original,timestamp"
       "&filter=statuscode:200&filter=mimetype:application/pdf&collapse=urlkey&limit=10000" % PORTAL)

# Folders of the Portal de Imigração that hold acts or staff instructions, with the kind to give them.
PORTAL_DIRS = {
    "resolucoes_normativas": "procedural act",       # CNIg normative resolutions since the 2017 Migration Law
    "resolucoes_conjuntas": "procedural act",        # joint CNIg/CONARE resolutions
    "portarias": "procedural act",                   # ministerial, interministerial, DEMIG, PF portarias
    "resoluções_CONARE": "procedural act",
    "ordens_de_servico": "guidance",                 # service orders of the labour-immigration unit (CGIg)
    "notas_informativas": "guidance",                # technical and information notes of CGIg / DEMIG
}
PORTAL_SKIP = re.compile(r"(?i)formul|perguntas|_DOU_|ANEXO|DISSEMINA|827_DE_19_DE_NOVEMBRO|Migrante_Digital|"
                         r"08018\.030354|^165_|^171_|^PORTARIA_INTERMINISTERIAL_[89]\.pdf")

# Gazette pages (www.in.gov.br answers 403 to this machine) kept from the Internet Archive.
GAZETTE_IA = [
    ("20250413012830", "https://www.in.gov.br/web/dou/-/resolucao-normativa-n-30-de-12-de-setembro-de-2019-216798568",
     "RESOLUÇÃO NORMATIVA Nº 30, DE 12 DE SETEMBRO DE 2019 (CONARE): prorroga a vigência da Resolução Normativa nº 17",
     "2019-09-12", "CONARE (Comitê Nacional para os Refugiados)",
     "CONARE Normative Resolution No. 30 of 12 September 2019 - extends Resolution 17/2013 (humanitarian visas for "
     "people affected by the Syrian conflict)"),
    ("20240629194001", "https://www.in.gov.br/materia/-/asset_publisher/Kujrw0TZC2Mb/content/id/39937908/"
     "do1-2018-09-06-portaria-n-8-728-de-21-de-agosto-de-2018-39937733",
     "PORTARIA Nº 8.728, DE 21 DE AGOSTO DE 2018 (DG/PF): institui os modelos das Carteiras de Registro Nacional "
     "Migratório e do Documento Provisório de Registro Nacional Migratório", "2018-08-21", "Polícia Federal",
     "Federal Police Ordinance No. 8,728 of 21 August 2018 - models of the National Migration Registration card and "
     "provisional document"),
    ("20250618153931", "https://www.in.gov.br/web/dou/-/portaria-n-28/2022-direx/pf-de-11-de-marco-de-2022-386096092",
     "PORTARIA Nº 28/2022-DIREX/PF, DE 11 DE MARÇO DE 2022: dispõe sobre prorrogação de prazo para regularização "
     "migratória no âmbito da Polícia Federal", "2022-03-11", "Polícia Federal (Diretoria-Executiva)",
     "Federal Police Ordinance No. 28/2022-DIREX of 11 March 2022 - extension of time limits for migration "
     "regularisation at the Federal Police"),
]

# Better reasons for gazette links that stay unfetched on purpose.
GAZETTE_WHY = [
    ("despacho-n-3-", "not fetched on purpose: notice to named refugee applicants in individual cases (an archived "
                      "copy exists at web.archive.org)"),
    ("/content/id/53242907", "not fetched on purpose: notice to named refugee applicants in individual cases"),
    ("/content/id/53242913", "not fetched on purpose: notice to named refugee applicants in individual cases"),
    ("/content/id/58366994", "not fetched on purpose: notice to named refugee applicants in individual cases"),
    ("/content/id/47987227", "not fetched on purpose: notice to named refugee applicants in individual cases"),
    ("resolucao-n-1-de-13-de-novembro-de-2020", "outside scope: Education Council resolution (school enrolment)"),
    ("resolucao-n-1-de-25-de-julho-de-2022", "outside scope: Education Council resolution (recognition of foreign "
                                             "diplomas)"),
    ("resolucao-n-2-de-26-de-marco-de-2018", "outside scope: emergency-assistance committee (Operação Acolhida "
                                             "logistics), not a decision rule"),
]


def act_key(text, cnig=False):
    """(family, number, year) of an act named in a title or file name, or None.
    CNIg resolutions since the 2017 Migration Law are keyed by number alone (file names often lack the year)."""
    t = urllib.parse.unquote(text).replace("_", " ").replace("-", " ")
    fam = "conj" if re.search(r"(?i)conjunta", t) else "res" if re.search(r"(?i)resolu|\bRN\b|\bREN\b|\bRES\b", t) else \
        "prt" if re.search(r"(?i)portaria|\bPR[IT]\b|\bPI\b", t) else ""
    m = re.search(r"(?i)n[º°o]\.?\s*([\d.]+)", t) or re.search(r"(?i)\b(?:RN|portaria|RES|REN|PR[IT])\s+([\d.]+)", t)
    if not (fam and m) or not m.group(1).strip("."):
        return None
    num = str(int(m.group(1).split(".")[0] if re.match(r"\d+\.(19|20)\d\d", m.group(1)) else m.group(1).replace(".", "")))
    y = re.findall(r"\b((?:19|20)\d\d)\b", t[m.end():]) or re.findall(r"\b((?:19|20)\d\d)\b", t)
    if fam == "res" and cnig and (not y or y[0] >= "2017"):
        return "cnig", num
    if not y:
        return None
    return fam, num, y[0]


def portal_title(name):
    t = urllib.parse.unquote(name).rsplit(".", 1)[0]
    t = re.sub(r"_\d$|_\d{3}$", "", t).replace("_", " ").strip()
    m = re.match(r"(?i)RN\s*(\d+)\s*-?\s*(?:-\s*)?((?:19|20)\d\d)?(.*)", t)
    if m:
        t = "Resolução Normativa CNIg nº %s%s %s" % (m.group(1), "/" + m.group(2) if m.group(2) else "", m.group(3))
    return re.sub(r"\s+", " ", t).strip(" -")


def first_page_date(path):
    """Date of the act from the first page of a PDF (pdftotext), for files whose names carry none."""
    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    try:
        txt = subprocess.run([exe, "-l", "1", str(path), "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    except Exception:                                # noqa: BLE001
        return ""
    return pt_date(re.sub(r"\s+", " ", txt)[:1500])


def do_archive():
    print("archive: web.archive.org (Portal de Imigração / CNIg, gazette pages)")
    have = set()
    old_rows = []
    if (OUT / "index.tsv").exists():                 # a partial run still knows what the library gave
        for line in (OUT / "index.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            if "cnig-portal/" not in line:
                old_rows.append(tuple(line.split("\t")))
    for r in rows + old_rows:
        cn = "CNIG" in " ".join(r).upper()
        k = act_key(r[1], cn) or act_key(r[0], cn)
        if k:
            have.add(k)
    data = get(CDX)
    listing = json.loads(data.decode("utf-8"))[1:] if data else []
    if listing:
        (OUT / "listings").mkdir(exist_ok=True)
        (OUT / "listings" / "portal-imigracao-cdx.json").write_text(json.dumps(listing, ensure_ascii=False, indent=0),
                                                                    encoding="utf-8")
    known = {}                                       # archived URL -> saved file, from earlier runs
    kf = OUT / "listings" / "portal-imigracao-files.json"
    if kf.exists():
        known = json.loads(kf.read_text(encoding="utf-8"))
    hashes = {}
    for rel in known.values():
        if rel and (OUT / rel).exists():
            hashes[hashlib.sha1((OUT / rel).read_bytes()).hexdigest()] = rel
    for original, ts in sorted(listing, key=lambda x: x[0]):
        parts = urllib.parse.unquote(original).split("/")
        folder = parts[4] if len(parts) > 5 else ""
        name = parts[-1]
        if folder not in PORTAL_DIRS or PORTAL_SKIP.search(name) or not name.lower().endswith(".pdf"):
            continue
        if folder == "resoluções_CONARE" and not re.search(r"N.? ?(28|29)_", name):
            continue                                 # the other CONARE resolutions came from gov.br/mj
        kind = PORTAL_DIRS[folder]
        title = portal_title(name)
        if kind == "procedural act" and act_key(title, "normativas" in folder) in have:
            continue
        url = "https://web.archive.org/web/%sid_/%s" % (ts, original)
        sub = "cnig-portal/" + {"resolucoes_normativas": "resolucoes-normativas", "resolucoes_conjuntas":
                                "resolucoes-conjuntas", "resoluções_CONARE": "resolucoes-conare"}.get(
                                    folder, folder.replace("_", "-"))
        if original in known:
            rel = known[original]
            if rel is None:                          # identical to another archived file
                continue
        else:
            b = get(url)
            if b is None:
                continue
            if not b.lstrip()[:5].startswith(b"%PDF"):
                problems.append((original, "archived copy is not a PDF"))
                continue
            hsh = hashlib.sha1(b).hexdigest()
            if hsh in hashes:
                print("  same file as %s, skipped: %s" % (hashes[hsh], name))
                known[original] = None
                continue
            tmp = OUT / sub / ("_tmp_" + slug(name))
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(b)
            if not pdf_ok(tmp):
                tmp.unlink()
                problems.append((original, "pdfinfo cannot read the archived copy"))
                continue
            date = pt_date(title) or first_page_date(tmp)
            if not date:
                y = re.findall(r"((?:19|20)\d\d)", name)
                date = y[-1] if y else ""
            rel = "%s/%s_%s" % (sub, date or "nodate", slug(name))
            tmp.rename(OUT / rel)
            known[original] = rel
            hashes[hsh] = rel
            stats["new"] += 1
            print("  saved %s (%d kB)" % (rel, len(b) // 1024))
        date = rel.split("/")[-1].split("_")[0]
        date = "" if date == "nodate" else date
        body = ("Polícia Federal" if re.search(r"(?i)DIREX|DG.PF", name) else
                "Departamento de Migrações (DEMIG/MJSP)" if "DEMIG" in name else
                "CONARE" if "CONARE" in folder else
                "Ministério das Relações Exteriores" if "MRE_N" in name and "INTERMIN" not in name else
                "CNIg / Coordenação-Geral de Imigração Laboral" if kind == "guidance" or "normativas" in folder
                else "Ministério da Justiça e Segurança Pública")
        if kind == "guidance":
            en = PORTAL_EN.get(name, "Labour-immigration unit (CGIg) " + gloss(title))
        else:
            en = gloss(title.replace("Resolução Normativa CNIg", "Resolução Normativa"))
            if "normativas" in folder:
                en = en.replace("Normative Resolution", "CNIg Normative Resolution", 1)
        rows.append((rel, "%s [arquivo do Portal de Imigração: %s]" % (title, urllib.parse.unquote(original)),
                     date, url, kind, body, en))
    if known:
        kf.write_text(json.dumps(known, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    for ts, original, title, date, body, en in GAZETTE_IA:
        rel = "dou-arquivo/%s_%s.html" % (date, slug(original.rsplit("/", 1)[-1], 70))
        dest = OUT / rel
        url = "https://web.archive.org/web/%sid_/%s" % (ts, original)
        if not dest.exists():
            b = get(url)
            if b is None:
                continue
            if b"texto-dou" not in b:
                problems.append((original, "archived gazette page has no act text"))
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b)
            stats["new"] += 1
            print("  saved %s (%d kB)" % (rel, len(b) // 1024))
        rows.append((rel, title, date, url, "procedural act", body, en))


PORTAL_EN = {}


# ------------------------------------------------------------------ not obtained

# Known items that this script does not fetch, with the reason. (title, url, reason)
STATIC_MISSING = [
    ("Polícia Federal: Instruções Normativas DG/PF on migration (e.g. IN 142/2018-DG/PF on migration registration, "
     "IN 198/2021-DG/PF on infraction and fine proceedings) - the working instructions of police immigration units",
     "https://www.gov.br/pf/pt-br/assuntos/imigracao",
     "not published: issued in the Federal Police internal service bulletin; cited in decisions on gov.br/pf but the "
     "texts are not on the site"),
    ("Polícia Federal, CGPI: Mensagem Oficial-Circular nº 54/2020 (migration control of seafarers, English version)",
     "https://www.steamshipmutual.com/sites/default/files/medialibrary/files/Guidance-on-migratory-control-of-crew-seafarers-CGPI-DIREX-PF-20I-12-2020.pdf",
     "not officially published; a copy circulates on a shipping insurer's site - not fetched (not an official source)"),
    ("Polícia Federal, CGPI: Mensagem Oficial-Circular nº 09/2021 (migration control of seafarers)",
     "https://www.steamshipmutual.com/sites/default/files/medialibrary/files/MOC_09-2021_CGPI.pdf",
     "not officially published; third-party copy only - not fetched"),
    ("Polícia Federal, CGPI: Mensagem Oficial-Circular nº 02/2022 (seafarers' identity documents)",
     "https://www.steamshipmutual.com/sites/default/files/medialibrary/files/MOC_2_2022%20seafarers%20identity%20documents.pdf",
     "not officially published; third-party copy only - not fetched"),
    ("Itamaraty: current consular regulations (revisions of the Manual do Serviço Consular e Jurídico after 2010) "
     "and circular telegrams on visas",
     "https://www.gov.br/mre/pt-br/assuntos/portal-consular",
     "not published by the ministry; only the 2010 edition was found, on the exam organiser's site"),
    ("Itamaraty: Quadro Geral de Regime de Vistos (visa-regime table used by consulates and border police) and "
     "other PDFs under www.gov.br/mre",
     "https://www.gov.br/mre/pt-br/assuntos/portal-consular/vistos",
     "robots.txt of www.gov.br disallows /mre/*.pdf for all robots; open in a browser"),
    ("Portal de Imigração (CNIg): listing of CNIg resoluções normativas, resoluções conjuntas and portarias, "
     "e.g. Resolução Conjunta CNIg/CONARE nº 2 of 2 December 2020",
     "https://portaldeimigracao.mj.gov.br/images/resolucoes_conjuntas/RESOLU%C3%87%C3%83O_CONJUNTA_CNIG_CONARE_MJSP_N%C2%BA_2_DE_2_DE_DEZEMBRO_DE_2020.pdf",
     "host reset the connection three times in a row (robots.txt could not even be read); host not used. "
     "Most CNIg resolutions were obtained from the ministry's digital library instead"),
    ("Portaria MJ nº 218, de 27 de fevereiro de 2018 (copy on the Portal de Imigração)",
     "https://portaldeimigracao.mj.gov.br/images/portarias/PORTARIA_N%C2%BA_218_DE_27_DE_FEVEREIRO_DE_2018_1.pdf",
     "host reset the connection three times in a row; the same act was obtained from the digital library"),
    ("CONARE: minutes of plenary meetings (atas), 2004 onwards, about 150 PDFs",
     "https://www.gov.br/mj/pt-br/assuntos/seus-direitos/refugio/institucional/atas-do-conare",
     "skipped on purpose: minutes record decisions and votes, they are not instructions"),
    ("CONARE: SISCONARE manual for applicants and information leaflets",
     "https://www.gov.br/mj/pt-br/assuntos/seus-direitos/refugio/sisconare/anexos",
     "skipped on purpose: applicant information"),
]


def write_outputs(gazette):
    have = " ".join(r[1] for r in rows).lower()
    missing = list(STATIC_MISSING)
    seen = set()
    for url, text in gazette:
        text = clean(text)
        m = re.search(r"n[ºo°]\s*([\d.]+)[^\d]+de\s+\d{1,2}[ºo°]?\s+de\s+[a-zç]+\s+de\s+(\d{4})", text, re.I)
        if url in seen:
            continue
        seen.add(url)
        if m:                                        # the same act may have come from the library
            num, year = m.group(1), m.group(2)
            kind = re.match(r"\s*(portaria interministerial|portaria|resolu[çc][ãa]o normativa|resolu[çc][ãa]o|despacho)", text, re.I)
            if kind and re.search(r"%s[^:]{0,25}n[ºo°] ?%s, de [^:]{0,25}%s" % (
                    re.escape(kind.group(1).lower()), re.escape(num), year), have):
                continue
        missing.append((text or "(untitled link)", url,
                        "linked only to the official gazette (in.gov.br), which answered HTTP 403 to this machine; "
                        "needs a browser or a web archive"))
    for url, why in problems:
        missing.append(("", url, why))
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for title, url, why in missing:
            for key, better in GAZETTE_WHY:
                if key in url:
                    why = better
            row = (title, pt_date(title), url, why)
            f.write("\t".join(re.sub(r"\s+", " ", x) for x in row) + "\n")

    rows.sort(key=lambda r: (r[4] != "guidance", r[0].split("/")[0], r[2], r[0]))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tissuing_body\n")
        for row in rows:
            row = row[:5] + (row[6], row[5])
            f.write("\t".join(re.sub(r"\s+", " ", x) for x in row) + "\n")
    g = sum(1 for r in rows if r[4] == "guidance")
    print("br: %d files indexed (%d guidance, %d procedural acts), %d new this run, %d not obtained" % (
        len(rows), g, len(rows) - g, stats["new"], len(missing)))
    for host, why in blocked.items():
        print("  host given up this run: %s (%s)" % (host, why))


def main():
    which = sys.argv[1:] or ["refugio", "pf", "mre", "library", "archive"]
    OUT.mkdir(exist_ok=True)
    stats["bytes_total"] = total_size()
    stats["files_total"] = sum(1 for f in OUT.rglob("*") if f.is_file())
    gazette = []
    if "refugio" in which:
        gazette = do_refugio()
    if "pf" in which:
        do_pf()
    if "mre" in which:
        do_mre()
    if "library" in which:
        do_library()
    if "archive" in which:
        do_archive()
    if set(which) >= {"refugio", "pf", "mre", "library", "archive"}:
        write_outputs(gazette)
    else:
        print("partial run: index.tsv and not-obtained.tsv are only rebuilt by a full run")


if __name__ == "__main__":
    main()

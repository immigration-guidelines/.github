#!/usr/bin/env python3
"""Slovakia: what is published of the material immigration officials work from.

    ./download_sk.py            # default sources (minv)
    ./download_sk.py minv       # Migration Office internal staff material on minv.sk
    ./download_sk.py ia         # OPTIONAL, not run by default: one item only obtainable
                                # from the Internet Archive (4 s spacing, gives up after
                                # three refusals in a row)

Slovakia publishes almost no guidance for decision-makers. The Bureau of Border and
Foreign Police (UHCP P PZ) and its foreign-police departments decide residence, visas,
return and detention; the Migration Office of the Ministry of the Interior decides
asylum. Both work from internal regulations of the Ministry (nariadenia ministra vnutra,
published only in the internal Vestnik MV SR, e.g. N MV 34/2014 on the procedure of the
Migration Office and police units under the Asylum Act) and from methodological
instructions of UHCP; none of them is on minv.sk. The Ministry publishes only the list of
its valid internal regulations. The labour offices (UPSVaR) publish employer information
only; the labour ministry's site employment.gov.sk forbids AI crawlers in robots.txt and
is not touched.

Sources
  minv  two staff manuals of the Migration Office's Department of Migration and
        Integration for social workers in asylum facilities (2019, 2020), from minv.sk.
        Real internal guidance, but for reception staff, not for decision-makers.
  ia    (optional) Refworld's copy of the 2003 Interior Minister regulation on the
        procedure of the Migration Office and police units under the Asylum Act, the
        predecessor of N MV 34/2014. refworld.org shows a Cloudflare challenge, so only
        an archived copy could be used; whether one exists was not checked.

robots.txt of every host is read before anything else is requested from it; a 403/429
or a bot check closes the host for the rest of the run. Existing files are skipped.
index.tsv and not-obtained.tsv are rewritten on every run. Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CODE = "sk"
OUT = Path(__file__).resolve().parent / CODE
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
HOST_DELAY = {"web.archive.org": 4.0}
AI_AGENTS = ("claude", "anthropic", "gptbot", "chatgpt", "ccbot", "ai-", "perplexity", "cohere",
             "google-extended", "bytespider", "amazonbot")
MU = "Internal material of the Department of Migration and Integration of the Migration Office (MU MV SR) "

# source -> [(url, file, title, date, kind, title_en, note, must-contain)]
SOURCES = {
    "minv": [
        ("https://www.minv.sk/?kompetencie-sp-pri-predchadzani-a-rieseni-krizovych-situacii-v-azylovych-zariadeniach&subor=426435",
         "2019-06-13_migracny-urad_kompetencie-socialnych-pracovnikov-pri-krizovych-situaciach.pdf",
         "Kompetencie sociálnych pracovníkov pri predchádzaní a riešení krízových situácií (Interný materiál odboru migrácie a integrácie MÚ MV SR)",
         "2019-06-13", "guidance",
         "Competences of social workers in preventing and handling crisis situations (in asylum facilities)",
         MU + "('pomocna interna metodika'), 30 pages: duties and methods of social workers in asylum facilities, ten typical "
         "crisis situations (violence, protests, domestic violence, child care, addiction, trauma, special needs, trafficking "
         "victims) and a record form. States that it does not cover the asylum procedure. Reception staff, not decision-makers. "
         "Date = PDF creation date. Page: https://www.minv.sk/?kompetencie-sp-pri-predchadzani-a-rieseni-krizovych-situacii-v-azylovych-zariadeniach",
         ""),
        ("https://www.minv.sk/?skusenosti-v-oblasti-socialnej-prace-v-azylovych-zariadeniach&subor=426434",
         "2020-12-17_migracny-urad_skusenosti-v-oblasti-socialnej-prace-v-azylovych-zariadeniach.pdf",
         "Skúsenosti v oblasti sociálnej práce v azylových zariadeniach", "2020-12-17", "guidance",
         "Experience in social work in asylum facilities",
         "Migration Office of the Ministry of the Interior, 2020, 93 pages, written by its staff (with the Slovak Humanitarian "
         "Council): handbook on social work in the reception, accommodation and integration centres - role of the social "
         "worker, work with vulnerable applicants, unaccompanied minors, crisis situations. Reception staff, not decision-makers. "
         "Date = PDF creation date. Page: https://www.minv.sk/?skusenosti-v-oblasti-socialnej-prace-v-azylovych-zariadeniach",
         ""),
    ],
    "ia": [
        ("https://web.archive.org/web/2019id_/https://www.refworld.org/pdfid/42b6e45d4.pdf",
         "2003_nariadenie-ministra-vnutra-postup-migracneho-uradu-a-policie-pri-vykonavani-zakona-o-azyle_refworld.pdf",
         "Nariadenie ministra vnútra Slovenskej republiky o postupe migračného úradu Ministerstva vnútra Slovenskej republiky "
         "a útvarov Policajného zboru pri vykonávaní zákona o azyle (2003; Refworld copy)",
         "2003", "guidance",
         "Regulation of the Minister of the Interior on the procedure of the Migration Office and Police units in applying the Asylum Act (2003)",
         "internal regulation of the Minister (published only in the internal Vestnik MV SR); predecessor of N MV 34/2014; "
         "copy hosted by UNHCR Refworld (https://www.refworld.org/pdfid/42b6e45d4.pdf, Cloudflare challenge), fetched from "
         "the Internet Archive. Title and year from a search-engine description; check against the file.",
         ""),
    ],
}
DEFAULT = ["minv"]

# (title, date, url, reason) - known to exist, not fetched
NOT_FETCHED = [
    ("Nariadenie ministra vnútra SR č. 34/2014 o postupe migračného úradu MV SR, útvarov Policajného zboru a centier podpory "
     "pri vykonávaní zákona č. 480/2002 Z. z. o azyle (amended by N MV 80/2015, 131/2015, 84/2016, 127/2022 and later) - "
     "the Minister's working rules for the asylum procedure", "2014",
     "https://www.minv.sk/swift_data/source/images/interne-predpisy-prehlad2025.pdf",
     "not published: internal regulation printed only in the internal Vestnik MV SR; listed (title only) in the Ministry's "
     "published overview of valid internal regulations as at 18 June 2025 (URL given). Obtainable only by a request under "
     "Act 211/2000 (211@minv.sk)"),
    ("Nariadenie ministra vnútra SR č. 26/2007 o postupe pri umiestňovaní cudzincov do útvaru policajného zaistenia pre "
     "cudzincov (as amended) - placement of foreigners in the police detention facility", "2007",
     "https://www.minv.sk/swift_data/source/images/interne-predpisy-prehlad2025.pdf",
     "not published: internal regulation (Vestnik MV SR); title only in the overview of internal regulations"),
    ("Nariadenie ministra vnútra SR č. 61/2011 o činnosti centrálneho vízového orgánu - work of the central visa authority",
     "2011", "https://www.minv.sk/swift_data/source/images/interne-predpisy-prehlad2025.pdf",
     "not published: internal regulation (Vestnik MV SR); title only in the overview of internal regulations"),
    ("Rozkaz ministra vnútra SR č. 65/2012 o zriadení multidisciplinárnej pracovnej skupiny na koordináciu činností "
     "súvisiacich s určovaním oprávnenosti pobytu cudzincov", "2012",
     "https://www.minv.sk/swift_data/source/images/interne-predpisy-prehlad2025.pdf",
     "not published: internal order (Vestnik MV SR); title only in the overview of internal regulations"),
    ("Metodické pokyny / usmernenia Úradu hraničnej a cudzineckej polície P PZ pre oddelenia cudzineckej polície (methodological "
     "instructions of the Bureau of Border and Foreign Police to the foreign-police departments on residence, visas, return)", "",
     "https://www.minv.sk/?uhcp",
     "not published: their existence is confirmed by the Ministry's own analysis of foreign-police processes (2021, "
     "https://www.minv.sk/swift_data/source/verejna_sprava/analyticke_kapacity/Analyza%20OCP%20cudzina.pdf: 'different "
     "interpretation of methodological instructions' between departments); not on minv.sk and not in the overview of internal "
     "regulations, which lists only ministerial acts. Obtainable only by a request under Act 211/2000"),
    ("Internal instructions of the Migration Office for decision-makers (referred to as 'Guidelines for Decision-makers' and "
     "'internal instructions' alongside EUAA tools)", "", "https://dip.euaa.europa.eu/print/pdf/node/5926",
     "not published: mentioned in an EUAA-hosted document; nothing on minv.sk"),
    ("Methodological guidance of the Ministry of Labour, Social Affairs and Family on employing foreigners (if any)", "",
     "https://www.employment.gov.sk/sk/informacie-cudzincov/",
     "robots: employment.gov.sk disallows GPTBot, ChatGPT-User and PerplexityBot from the whole site; treated as applying to "
     "this collection, so the site was not read at all and whether such guidance exists there is unknown"),
    ("Internal rules of UPSVaR / labour offices for issuing the confirmation on filling a vacancy (potvrdenie o moznosti "
     "obsadenia VPM) and the employment permit", "", "https://www.upsvr.gov.sk/sluzby-zamestnanosti/zamestnavanie-cudzincov.html?page_id=272197",
     "not published: upsvr.gov.sk carries employer information, forms and the shortage-occupation list only (not collected)"),
]


class Closed(Exception):
    pass


_last, _closed, _robots, _delay, _errs = {}, {}, {}, {}, {}


def _raw(url):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Closed(_closed[host])
    wait = max(DELAY, HOST_DELAY.get(host, 0), _delay.get(host, 0)) - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        _errs[host] = 0
        return data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            if host == "web.archive.org":                  # the archive: give up after three refusals in a row
                _errs[host] = _errs.get(host, 0) + 1
                if _errs[host] >= 3:
                    _closed[host] = "three refusals in a row from web.archive.org"
                raise
            _closed[host] = f"HTTP {e.code} from {host}"
            raise Closed(_closed[host]) from e
        raise
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        _errs[host] = _errs.get(host, 0) + 1
        if _errs[host] >= 3:
            _closed[host] = f"three connection failures in a row from {host}"
        raise
    finally:
        _last[host] = time.time()


def _rules(host, scheme):
    """Allow/Disallow rules that apply to us: group '*' plus any group naming an AI crawler."""
    if host in _robots:
        return _robots[host]
    try:
        txt = _raw(f"{scheme}://{host}/robots.txt").decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        txt = "" if e.code in (404, 410) else None
    if txt is None or "<html" in txt[:500].lower():
        if txt is None:
            _closed[host] = f"robots.txt of {host} could not be read"
            raise Closed(_closed[host])
        txt = ""
    groups, agents, rules, in_agents = [], [], [], False
    for line in txt.splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if not in_agents and agents:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(val.lower())
            in_agents = True
        elif key in ("allow", "disallow", "crawl-delay"):
            rules.append((key, val))
            in_agents = False
    if agents:
        groups.append((agents, rules))
    mine = []
    for ags, rs in groups:
        if any(a == "*" or any(x in a for x in AI_AGENTS) for a in ags):
            mine += rs
    for k, v in mine:
        if k == "crawl-delay":
            try:
                _delay[host] = max(_delay.get(host, 0), float(v))
            except ValueError:
                pass
    _robots[host] = mine
    return mine


def allowed(url):
    u = urllib.parse.urlsplit(url)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    best = (-1, True)
    for k, v in _rules(u.netloc, u.scheme):
        if k == "crawl-delay" or not v:
            continue
        rx = "^" + re.escape(v).replace(r"\*", ".*").replace(r"\$", "$")
        if re.search(rx, path) or re.search(rx, urllib.parse.unquote(path)):
            if len(v) > best[0] or (len(v) == best[0] and k == "allow"):
                best = (len(v), k == "allow")
    return best[1]


def good(name, data, must):
    """Reject error pages, login pages and bot checks."""
    low = data[:4000].lower()
    if b"just a moment" in low or b"captcha" in low or b"cf-chl" in low:
        return "bot check page"
    if name.endswith(".pdf"):
        return None if data.startswith(b"%PDF") else "server did not return a PDF"
    if name.endswith((".docx", ".xlsx", ".zip")):
        return None if data.startswith(b"PK") else "server did not return an Office file"
    if name.endswith((".doc", ".xls")):
        return None if data.startswith(b"\xd0\xcf\x11\xe0") else "server did not return an Office file"
    if must and must.encode("utf-8") not in data:
        return f"page does not contain the expected text ({must})"
    return None if len(data) > 2000 else "page too short"


def main():
    names = sys.argv[1:] or DEFAULT
    bad = [n for n in names if n not in SOURCES]
    if bad:
        sys.exit(f"unknown source(s) {bad}; choose from {list(SOURCES)}")
    OUT.mkdir(exist_ok=True)
    failed = {}
    for name in names:
        for url, fn, title, date, kind, gloss, note, must in SOURCES[name]:
            dest = OUT / fn
            if dest.exists() and dest.stat().st_size > 0:
                continue
            try:
                if not allowed(url):
                    failed[fn] = "disallowed by robots.txt"
                    continue
                data = _raw(url)
            except Closed as e:
                failed[fn] = f"host closed: {e}"
                continue
            except Exception as e:                                # noqa: BLE001 - report, never retry
                failed[fn] = f"download failed: {e}"
                continue
            why = good(fn, data, must)
            if why:
                failed[fn] = why
                continue
            dest.write_bytes(data)
            print(f"  saved {fn} ({len(data):,} bytes)")

    rows, missing = [], []
    for name in SOURCES:
        for url, fn, title, date, kind, gloss, note, must in SOURCES[name]:
            if (OUT / fn).exists():
                rows.append("\t".join([fn, title, date, url, kind, gloss, note]))
            else:
                missing.append((title, date, url, failed.get(fn, "only reachable through the Internet Archive; optional source 'ia' was not run" if name == "ia" else "not downloaded (source not selected in the last run)")))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        f.write("".join(r + "\n" for r in rows))
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for row in missing + NOT_FETCHED:
            f.write("\t".join(row) + "\n")
    print(f"{CODE}: {len(rows)} files indexed, {len(missing)} failed/missing, {len(NOT_FETCHED)} known but unpublished")
    for fn, why in failed.items():
        print(f"  FAILED {fn}: {why}")


if __name__ == "__main__":
    main()

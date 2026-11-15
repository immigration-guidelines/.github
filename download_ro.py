#!/usr/bin/env python3
"""Romania: what is published of the material immigration officials work from.

    ./download_ro.py          # source igi
    ./download_ro.py ia       # also/only the three legal acts from web.archive.org (4 s spacing)

Romania publishes no guidance for decision-makers. The General Inspectorate for
Immigration (Inspectoratul General pentru Imigrări, IGI) decides residence, work
authorisation (aviz de angajare), return and asylum cases. Its website carries the
statutes, applicant information, press releases and Ombudsman visit reports; its
internal procedures and the Inspector General's dispositions are not published (its own
list of public-interest documents does not even name them), and AIDA records that the
asylum directorate's internal guidelines are "only for internal use".

What an official can be seen to work from are legal acts: the two ordinances, the Asylum
Act, the Government's methodological norms for the Asylum Act and a few orders of the
Minister of Internal Affairs. The official source for those, legislatie.just.ro, closed
the connection on robots.txt three times in a row on 2026-11-15 and is therefore not
used directly by this script; source "ia" takes three of those acts (asylum methodological
norms HG 1251/2006, Eurodac/Dublin order 441/2008, asylum-centre rules order 130/2016) from
the Internet Archive's copies, and runs only when named. The one procedural act that IGI hosts itself is downloaded:

  igi   Regulation of the accommodation centres for foreigners taken into public custody
        (Order 121/2014 of the Minister of Internal Affairs), kind = procedural act.

robots.txt of the host is read before anything else is requested from it; a 403/429 or a
bot check closes the host for the rest of the run. Existing files are skipped. index.tsv
and not-obtained.tsv are rewritten on every run. Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CODE = "ro"
OUT = Path(__file__).resolve().parent / CODE
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0

# source -> [(url, file, title, date, kind, title_en, note, must_contain)]
SOURCES = {
    "igi": [
        ("https://igi.mai.gov.ro/wp-content/uploads/2021/10/regulament_din_30_iulie_2014-4.pdf",
         "2014-07-30_OMAI-121-2014_regulamentul-centrelor-de-cazare-a-strainilor-luati-in-custodie-publica.pdf",
         "Regulamentul centrelor de cazare a străinilor luați în custodie publică, aprobat prin Ordinul viceprim-ministrului, "
         "ministrul afacerilor interne, nr. 121/2014", "2014-07-30", "procedural act",
         "Regulation of the accommodation centres for foreigners taken into public custody, approved by Order No 121/2014 "
         "of the Deputy Prime Minister, Minister of Internal Affairs",
         "ministerial order published in Monitorul Oficial; copy hosted by IGI on its Legislație page "
         "(https://igi.mai.gov.ro/legislatie/), a printout of the legislation portal's text; date = date of the regulation", None),
    ],
}

LJ = ("legislatie.just.ro closed the connection without a response on robots.txt three times in a row (2026-11-15), "
      "so the host was given up; ")
IA_WHY = (LJ + "an archived copy exists; source 'ia' of this script fetches it from web.archive.org but has not been run "
          "(on 2026-11-15 the agent's step that checks archived pages was refused by the local permission system, and later "
          "agents did not work around that). Run: python3 download_ro.py ia")
WB = "https://web.archive.org/web/"
LJN = "procedural act: Government decision / ministerial order, page of the official legislation portal as archived by the Internet Archive; date = date of the act"
SOURCES["ia"] = [
    (WB + "2026id_/https://legislatie.just.ro/Public/DetaliiDocument/75383",
     "2006-09-13_HG-1251-2006_normele-metodologice-de-aplicare-a-legii-122-2006-privind-azilul.html",
     "Hotărârea Guvernului nr. 1251/2006 pentru aprobarea Normelor metodologice de aplicare a Legii nr. 122/2006 privind azilul în România",
     "2006-09-13", "procedural act",
     "Government Decision 1251/2006 approving the methodological norms for applying the Asylum Act (Law 122/2006)",
     LJN + "; original https://legislatie.just.ro/Public/DetaliiDocument/75383", "1251"),
    (WB + "2024id_/https://legislatie.just.ro/Public/DetaliiDocument/91271",
     "2008-04-04_OMIRA-441-2008_eurodac-si-metodologia-practica-de-cooperare-dublin.html",
     "Ordinul ministrului internelor și reformei administrative nr. 441/2008 pentru stabilirea atribuțiilor autorităților responsabile "
     "cu implementarea datelor în sistemul Eurodac și pentru stabilirea metodologiei practice de cooperare",
     "2008-04-04", "procedural act",
     "Order 441/2008 of the Minister of the Interior and Administrative Reform on the authorities responsible for Eurodac data and the practical cooperation methodology (Dublin)",
     LJN + "; original https://legislatie.just.ro/Public/DetaliiDocument/91271", "441"),
    (WB + "2024id_/https://legislatie.just.ro/Public/DetaliiDocumentAfis/181397",
     "2016-08-25_OMAI-130-2016_regulamentul-de-ordine-interioara-al-centrelor-regionale-pentru-solicitanti-de-azil.html",
     "Regulamentul de ordine interioară al centrelor regionale de proceduri și cazare a solicitanților de azil, aprobat prin "
     "Ordinul ministrului afacerilor interne nr. 130/2016",
     "2016-08-25", "procedural act",
     "Internal rules of the regional procedure and accommodation centres for asylum seekers, approved by Order 130/2016 of the Minister of Internal Affairs",
     LJN + "; original https://legislatie.just.ro/Public/DetaliiDocumentAfis/181397", "130"),
]
DEFAULT_WHY = {e[1]: IA_WHY for e in SOURCES["ia"]}
_delay_init = {"web.archive.org": 4.0}
# (title, date, url, reason) - known to exist, not fetched
NOT_FETCHED = [
    ("Proceduri interne și dispoziții ale inspectorului general al IGI (internal working procedures and dispositions of the "
     "Inspector General on residence permits, work authorisations, return, asylum interviews and decisions, early "
     "identification of vulnerable applicants, Dublin)", "",
     "https://igi.mai.gov.ro/solicitare-informatii-legislatie/",
     "not published: internal documents; AIDA reports that the asylum directorate's guidelines are for internal use only. "
     "Obtainable only by a request under Law 544/2001 (page given)"),
]


class Closed(Exception):
    pass


_last, _closed, _robots, _delay, _errs = {}, {}, {}, dict(_delay_init), {}


def _raw(url):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Closed(_closed[host])
    wait = max(DELAY, _delay.get(host, 0)) - (time.time() - _last.get(host, 0))
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
        if any(a == "*" or any(x in a for x in ("claude", "anthropic", "gptbot", "ccbot", "ai-")) for a in ags):
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
    names = sys.argv[1:] or [n for n in SOURCES if n != "ia"]   # "ia" only when asked for
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
                missing.append((title, date, url, failed.get(fn, DEFAULT_WHY.get(fn, "not downloaded (source not selected in the last run)"))))
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

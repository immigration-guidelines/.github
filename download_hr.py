#!/usr/bin/env python3
"""Croatia: what is published of the material immigration officials work from.

    ./download_hr.py            # everything
    ./download_hr.py nn         # only the Narodne novine rulebooks
    ./download_hr.py protocol   # only the inter-agency protocol

Croatia publishes almost no guidance for decision-makers. The Ministry of the Interior
(MUP) decides residence, work-permit, return and asylum cases through its police
administrations and its Directorate for Immigration, Citizenship and Administrative
Affairs; its instructions to them ("naputak", "uputa", "standardni operativni
postupak") are internal and are not on mup.gov.hr, policija.gov.hr or in Narodne novine.
The Croatian Employment Service (hzz.hr) publishes only information for employers.

Sources
  protocol  the Government's inter-agency Protocol on the treatment of unaccompanied
            children (2018), from the social policy ministry's site: the one real
            guidance document (kind = guidance).
  nn        the minister's rulebooks (pravilnici) in the official gazette Narodne novine
            that lay down how cases are handled - in practice the working manual
            (kind = procedural act). Base text and each amending rulebook as published;
            the gazette publishes no consolidated versions.

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

CODE = "hr"
OUT = Path(__file__).resolve().parent / CODE
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
NN = "https://narodne-novine.nn.hr/clanci/sluzbeni/"
MUP_LIST = "https://mup.gov.hr/pristup-informacijama-16/zakoni-i-ostali-propisi/kretanje-i-boravak-stranaca/175297"

RB = "Minister of the Interior rulebook (pravilnik), as published in Narodne novine; date = publication date"

# source -> [(url, file, title, date, kind, title_en, note, must_contain)]
SOURCES = {
    "protocol": [
        ("https://mrosp.gov.hr/UserDocsImages/dokumenti/Socijalna%20politika/Obitelj%20i%20djeca/Protokol%20o%20postupanju%20prema%20djeci%20bez%20pratnje.pdf",
         "2018-08-30_protokol-o-postupanju-prema-djeci-bez-pratnje.pdf",
         "Protokol o postupanju prema djeci bez pratnje", "2018-08-30", "guidance",
         "Protocol on the treatment of unaccompanied children",
         "Government of Croatia inter-agency protocol (adopted 30 Aug 2018): steps for police administrations/stations, "
         "health institutions, social welfare centres and the Ministry of the Interior - identification, age assessment, "
         "guardianship, accommodation, international protection procedure, Dublin, return", None),
    ],
    "nn": [
        (NN + "2022_02_20_215.html", "2022-02-16_NN-20-2022_pravilnik-o-boravku-drzavljana-trecih-zemalja.html",
         "Pravilnik o boravku državljana trećih zemalja u Republici Hrvatskoj", "2022-02-16", "procedural act",
         "Rulebook on the stay of third-country nationals in the Republic of Croatia",
         RB + "; how the conditions for temporary/long-term residence, stay-and-work permits and the EU Blue Card are established, "
         "documents required, forms; NN 20/2022; amended by NN 155/2022 and 43/2026 (separate files)", "PRAVILNIK"),
        (NN + "2022_12_155_2458.html", "2022-12-29_NN-155-2022_pravilnik-o-izmjenama-pravilnika-o-boravku-drzavljana-trecih-zemalja.html",
         "Pravilnik o izmjenama i dopuni Pravilnika o boravku državljana trećih zemalja u Republici Hrvatskoj", "2022-12-29", "procedural act",
         "Rulebook amending the Rulebook on the stay of third-country nationals", RB + "; NN 155/2022", "PRAVILNIK"),
        (NN + "2026_04_43_511.html", "2026-04-22_NN-43-2026_pravilnik-o-izmjenama-i-dopunama-pravilnika-o-boravku-drzavljana-trecih-zemalja.html",
         "Pravilnik o izmjenama i dopunama Pravilnika o boravku državljana trećih zemalja u Republici Hrvatskoj", "2026-04-22", "procedural act",
         "Rulebook amending and supplementing the Rulebook on the stay of third-country nationals", RB + "; NN 43/2026", "PRAVILNIK"),
        (NN + "2021_12_136_2244.html", "2021-12-10_NN-136-2021_pravilnik-o-postupanju-prema-drzavljanima-trecih-zemalja.html",
         "Pravilnik o postupanju prema državljanima trećih zemalja", "2021-12-10", "procedural act",
         "Rulebook on the treatment of third-country nationals",
         RB + "; police procedure for refusal of entry, return decisions, removal, entry bans, alternatives to detention, vulnerable persons; "
         "NN 136/2021; amended by NN 145/2023 and 102/2025 (separate files)", "PRAVILNIK"),
        (NN + "2023_12_145_2004.html", "2023-12-06_NN-145-2023_pravilnik-o-izmjenama-pravilnika-o-postupanju-prema-drzavljanima-trecih-zemalja.html",
         "Pravilnik o izmjenama i dopunama Pravilnika o postupanju prema državljanima trećih zemalja", "2023-12-06", "procedural act",
         "Rulebook amending the Rulebook on the treatment of third-country nationals", RB + "; NN 145/2023", "PRAVILNIK"),
        (NN + "2025_07_102_1414.html", "2025-07-16_NN-102-2025_pravilnik-o-izmjenama-pravilnika-o-postupanju-prema-drzavljanima-trecih-zemalja.html",
         "Pravilnik o izmjenama i dopunama Pravilnika o postupanju prema državljanima trećih zemalja", "2025-07-16", "procedural act",
         "Rulebook amending the Rulebook on the treatment of third-country nationals", RB + "; NN 102/2025", "PRAVILNIK"),
        (NN + "2020_10_107_2009.html", "2020-10-02_NN-107-2020_pravilnik-o-ulasku-i-boravku-drzavljana-egp-i-clanova-obitelji.html",
         "Pravilnik o ulasku i boravku u Republici Hrvatskoj državljana država članica Europskog gospodarskog prostora i članova njihovih obitelji",
         "2020-10-02", "procedural act",
         "Rulebook on the entry and stay in Croatia of nationals of EEA member states and their family members",
         RB + "; NN 107/2020; amended by NN 148/2020, 86/2021 and 155/2022 (separate files)", "PRAVILNIK"),
        (NN + "2020_12_148_2905.html", "2020-12-31_NN-148-2020_pravilnik-o-izmjenama-pravilnika-o-ulasku-i-boravku-drzavljana-egp.html",
         "Pravilnik o izmjenama i dopunama Pravilnika o ulasku i boravku u Republici Hrvatskoj državljana država članica Europskog gospodarskog prostora i članova njihovih obitelji",
         "2020-12-31", "procedural act", "Rulebook amending the Rulebook on the entry and stay of EEA nationals and their family members",
         RB + "; NN 148/2020", "PRAVILNIK"),
        (NN + "2021_07_86_1596.html", "2021-07-30_NN-86-2021_pravilnik-o-izmjenama-pravilnika-o-ulasku-i-boravku-drzavljana-egp.html",
         "Pravilnik o izmjenama i dopunama Pravilnika o ulasku i boravku u Republici Hrvatskoj državljana država članica Europskog gospodarskog prostora i članova njihovih obitelji",
         "2021-07-30", "procedural act", "Rulebook amending the Rulebook on the entry and stay of EEA nationals and their family members",
         RB + "; NN 86/2021", "PRAVILNIK"),
        (NN + "2022_12_155_2448.html", "2022-12-29_NN-155-2022_pravilnik-o-izmjenama-pravilnika-o-ulasku-i-boravku-drzavljana-egp.html",
         "Pravilnik o izmjeni Pravilnika o ulasku i boravku u Republici Hrvatskoj državljana država članica Europskog gospodarskog prostora i članova njihovih obitelji",
         "2022-12-29", "procedural act", "Rulebook amending the Rulebook on the entry and stay of EEA nationals and their family members",
         RB + "; NN 155/2022", "PRAVILNIK"),
        (NN + "2021_12_145_2502.html", "2021-12-29_NN-145-2021_pravilnik-o-boravku-u-prihvatnom-centru-za-strance.html",
         "Pravilnik o boravku u prihvatnom centru za strance i načinu izračuna troškova prisilnog udaljenja", "2021-12-29", "procedural act",
         "Rulebook on stay in the reception (detention) centre for foreigners and the calculation of the costs of forced removal",
         RB + "; NN 145/2021; amended by NN 155/2022 and 137/2023 (separate files)", "PRAVILNIK"),
        (NN + "2022_12_155_2455.html", "2022-12-29_NN-155-2022_pravilnik-o-izmjenama-pravilnika-o-boravku-u-prihvatnom-centru-za-strance.html",
         "Pravilnik o izmjenama Pravilnika o boravku u prihvatnom centru za strance i načinu izračuna troškova prisilnog udaljenja",
         "2022-12-29", "procedural act", "Rulebook amending the Rulebook on stay in the reception (detention) centre for foreigners",
         RB + "; NN 155/2022", "PRAVILNIK"),
        (NN + "2023_11_137_1863.html", "2023-11-15_NN-137-2023_pravilnik-o-dopunama-pravilnika-o-boravku-u-prihvatnom-centru-za-strance.html",
         "Pravilnik o dopunama Pravilnika o boravku u prihvatnom centru za strance i načinu izračuna troškova prisilnog udaljenja",
         "2023-11-15", "procedural act", "Rulebook supplementing the Rulebook on stay in the reception (detention) centre for foreigners",
         RB + "; NN 137/2023", "PRAVILNIK"),
        (NN + "2021_10_109_1919.html", "2021-10-08_NN-109-2021_pravilnik-o-vizama.html",
         "Pravilnik o vizama", "2021-10-08", "procedural act", "Rulebook on visas",
         "Minister of Foreign and European Affairs rulebook, as published in Narodne novine; date = publication date; "
         "visa procedure at consulates and at the border; NN 109/2021", "PRAVILNIK"),
    ],
}

# (title, date, url, reason) - known to exist, not fetched
NOT_FETCHED = [
    ("Naputci / upute Ravnateljstva policije i Uprave za imigraciju policijskim upravama o primjeni Zakona o strancima "
     "(internal instructions of the Police Directorate and the Immigration Directorate to police administrations on residence, "
     "work permits, return and the treatment of irregular migrants)", "",
     "https://mup.gov.hr/pristup-informacijama-16/sluzbenik-za-informiranje/pravo-na-pristup-informacijama/147920",
     "not published: internal documents of the Ministry of the Interior; referred to in Ombudsman reports, the Independent "
     "Monitoring Mechanism reports and the press, never posted. Obtainable only by a request under the Right of Access to "
     "Information Act (page given)"),
    ("Standard operating procedures and internal guidance of the International Protection Service (interview, decision "
     "drafting, Dublin, vulnerability)", "", "https://mup.gov.hr/",
     "not published: no such document on mup.gov.hr; the ministry points only to the Act, the rulebooks and EUAA guides"),
    ("Croatian Employment Service internal rules for issuing the opinion on a stay-and-work permit and for the labour-market test",
     "", "https://www.hzz.hr/usluge/radne-dozvole-za-zaposljavanje-stranaca-i-test-trzista-rada/",
     "not published: hzz.hr carries employer information, FAQ and the Governing Council's list of shortage occupations only "
     "(applicant information, not collected)"),
]


class Closed(Exception):
    pass


_last, _closed, _robots, _delay, _errs = {}, {}, {}, {}, {}


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
    names = sys.argv[1:] or list(SOURCES)
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
                missing.append((title, date, url, failed.get(fn, "not downloaded (source not selected in the last run)")))
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

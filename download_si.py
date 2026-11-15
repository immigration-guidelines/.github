#!/usr/bin/env python3
"""Slovenia: what is published of the material immigration officials work from.

    ./download_si.py            # default source: ul (Uradni list, the official gazette)
    ./download_si.py ul         # the same
    ./download_si.py ia         # Internet Archive copies of the same gazette pages (NOT run by default)

Slovenia publishes no case-officer guidance. Residence permits and single permits are
decided by the 58 administrative units (upravne enote); the Ministry of the Interior and
Public Administration (MNZJU; until 2025 the Ministry of the Interior, MNZ) decides
international protection at first instance and appeals; the police decide refusal of
entry and return; the Employment Service (ZRSZ, ess.gov.si) gives the consent to a
single permit or EU Blue Card. The ministry's instructions and interpretations to the
administrative units are sent to them directly and are not published on gov.si; police
instructions are not public either (policija.si forbids all robots).

What exists in public are a few instructions (navodila) of the Minister of the Interior
published in the official gazette. Two of them are the instructions under which the
border control body decides refusal of entry (Art. 9 and 10 of the Aliens Act ZTuj-2:
"the border control body decides on refusal of entry in accordance with the
instruction issued by the minister"). They are the only items this script tries to fetch.

Sources
  ul   www.uradni-list.si, the gazette's own pages for the instructions. On 2026-11-15 the
       host's TLS certificate had expired (notAfter 10 Nov 2026), so nothing could be
       fetched; TLS verification is never disabled. Re-run when the certificate is renewed.
  ia   web.archive.org copies of the same pages (4 s spacing, gives up after three
       refusals in a row). Only run when named explicitly; it was NOT run on 2026-11-15.

The gazette's successor database PISRS (pisrs.si) serves only a JavaScript shell whose
data calls are gated by a proof-of-work bot challenge; it is not used.

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

CODE = "si"
OUT = Path(__file__).resolve().parent / CODE
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
HOST_DELAY = {"web.archive.org": 4.0}
UL = "https://www.uradni-list.si/glasilo-uradni-list-rs/vsebina/"
IA = "https://web.archive.org/web/2024id_/"

# (gazette item, file, title, date, kind, title_en, note, must_contain)
DOCS = [
    ("2012-01-2491", "2012-08-03_UL-59-2012_navodilo-o-razlogih-za-zavrnitev-vstopa-drzavljanu-tretje-drzave.html",
     "Navodilo o razlogih za zavrnitev vstopa v Republiko Slovenijo državljanu tretje države", "2012-08-03", "guidance",
     "Instruction on the grounds for refusing entry into Slovenia to a third-country national",
     "Minister of the Interior instruction (navodilo) published in Uradni list RS 59/2012, in force 18 Aug 2012; the border "
     "control body decides refusal of entry in accordance with it (ZTuj-2); sets out the public-order, security and "
     "public-health grounds and the evidence for them. Formally a published regulation-type act addressed to the police",
     "Navodilo"),
    ("2006-01-8189", "2006-07-14_UL-74-2006_navodilo-o-zavrnitvi-vstopa-drzavljanu-eu.html",
     "Navodilo o zavrnitvi vstopa v Republiko Slovenijo državljanu Evropske unije in družinskemu članu državljana Evropske unije",
     "2006-07-14", "guidance",
     "Instruction on refusing entry into Slovenia to EU citizens and their family members",
     "Minister of the Interior instruction (navodilo) published in Uradni list RS 74/2006 (corr. 75/2006); amended 2012 "
     "(Uradni list RS 59/2012); grounds for the border police to refuse entry to EU citizens and family members",
     "Navodilo"),
    ("2012-01-2490", "2012-08-03_UL-59-2012_navodilo-o-spremembah-navodila-o-zavrnitvi-vstopa-drzavljanu-eu.html",
     "Navodilo o spremembah in dopolnitvah Navodila o zavrnitvi vstopa v Republiko Slovenijo državljanu Evropske unije",
     "2012-08-03", "guidance",
     "Instruction amending the instruction on refusing entry to EU citizens",
     "Minister of the Interior instruction published in Uradni list RS 59/2012 (item 2490), in force 18 Aug 2012; "
     "title as given by secondary sources, to be checked against the page", "Navodilo"),
]
SOURCES = {"ul": UL, "ia": IA + UL}
DEFAULT = ["ul"]

NOT_FETCHED = [
    ("Navodilo o izvajanju pomoči v primeru tranzita tujca, ki se prisilno odstranjuje po zračni poti (Minister of the "
     "Interior instruction on assistance in the transit of foreigners removed by air; Uradni list RS 25/2006) - guidance "
     "addressed to the police", "2006",
     "https://www.uradni-list.si/",
     "official sources unusable on 2026-11-15: uradni-list.si TLS certificate expired, PISRS behind a proof-of-work bot "
     "check; gazette item number not identified, so not in the script"),
    ("Instructions, interpretations and circulars of the Ministry of the Interior (Direktorat za migracije) to the "
     "administrative units on applying the Aliens Act (ZTuj-2) and the single permit - e.g. the 2019 instruction on "
     "filing extension applications 90 days before expiry", "",
     "https://www.gov.si/zbirke/katalogi-informacij-javnega-znacaja/?org=4447",
     "not published: the ministry's own reports and its answers on stopbirokraciji.gov.si say such instructions are sent "
     "to the administrative units; the Administrative Inspectorate (2018) recommended that interpretations be sent to all "
     "units, not only to those that ask. None is on gov.si. Obtainable by a request under the Access to Public Information "
     "Act (ZDIJZ)"),
    ("Internal instructions of the Migration Office for the international protection procedure (interview, decision "
     "drafting, Dublin, vulnerable applicants)", "",
     "https://www.gov.si/drzavni-organi/ministrstva/ministrstvo-za-notranje-zadeve-in-javno-upravo/o-ministrstvu/direktorat-za-migracije-in-upravne-notranje-zadeve/urad-za-migracije/",
     "not published: the Migration Office page and the international-protection topic page carry only applicant "
     "information and annual reports"),
    ("Police instructions and guidelines on treating foreigners at the border and in the interior in conditions of "
     "increased migration (released in part to Amnesty International Slovenia after Information Commissioner decision "
     "090-54/2019 of 14 June 2019)", "2019",
     "https://www.ip-rs.si/informacije-javnega-zna%C4%8Daja/iskalnik-po-odlo%C4%8Dbah/605093ff216cb",
     "not published by the police; policija.si robots.txt is 'Disallow: /' for all agents, so the police site was not "
     "searched at all"),
    ("Employment Service (ZRSZ) internal rules for giving consent to a single permit or EU Blue Card and for the "
     "labour-market test", "",
     "https://www.ess.gov.si/delodajalci/zaposlovanje-tujcev-iz-tretjih-drzav/enotno-dovoljenje/",
     "not published: ess.gov.si carries employer information only; its public-information catalogue lists statutes, no "
     "internal acts"),
]


class Closed(Exception):
    pass


_last, _closed, _robots, _delay, _errs = {}, {}, {}, {}, {}


def _raw(url):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Closed(_closed[host])
    gap = max(DELAY, HOST_DELAY.get(host, 0), _delay.get(host, 0))
    wait = gap - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        _errs[host] = 0
        return data
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            if host == "web.archive.org":
                _errs[host] = _errs.get(host, 0) + 1
                if _errs[host] >= 3:
                    _closed[host] = "three refusals in a row from web.archive.org"
            else:
                _closed[host] = f"HTTP {e.code} from {host}"
                raise Closed(_closed[host]) from e
        raise
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e):
            _closed[host] = f"TLS certificate of {host} not valid ({e})"
            raise Closed(_closed[host]) from e
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
    except Closed:
        raise
    except urllib.error.HTTPError as e:
        txt = "" if e.code in (404, 410) else None
    except Exception as e:                                      # noqa: BLE001
        _closed[host] = f"robots.txt of {host} could not be read ({e})"
        raise Closed(_closed[host]) from e
    if txt is None:
        _closed[host] = f"robots.txt of {host} could not be read"
        raise Closed(_closed[host])
    if "<html" in txt[:500].lower():
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


def good(data, must):
    """Reject error pages, login pages and bot checks."""
    low = data[:6000].lower()
    if b"just a moment" in low or b"captcha" in low or b"cf-chl" in low:
        return "bot check page"
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
        for item, fn, title, date, kind, gloss, note, must in DOCS:
            dest = OUT / fn
            if dest.exists() and dest.stat().st_size > 0:
                continue
            url = SOURCES[name] + item
            try:
                if not allowed(url):
                    failed[fn] = f"{name}: disallowed by robots.txt"
                    continue
                data = _raw(url)
            except Closed as e:
                failed[fn] = f"{name}: host closed: {e}"
                continue
            except Exception as e:                                # noqa: BLE001 - report, never retry
                failed[fn] = f"{name}: download failed: {e}"
                continue
            why = good(data, must)
            if why:
                failed[fn] = f"{name}: {why}"
                continue
            dest.write_bytes(data)
            print(f"  saved {fn} ({len(data):,} bytes) from {url}")

    rows, missing = [], []
    for item, fn, title, date, kind, gloss, note, must in DOCS:
        if (OUT / fn).exists():
            rows.append("\t".join([fn, title, date, UL + item, kind, gloss, note]))
        else:
            missing.append((f"{title} ({gloss}) - {kind}", date, UL + item,
                            failed.get(fn, "not downloaded (source not selected in the last run)")
                            + "; an Internet Archive copy may exist: ./download_si.py ia"))
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

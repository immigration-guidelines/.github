#!/usr/bin/env python3
"""Hungary: what is published of the material immigration officials work from.

    ./download_hu.py            # default sources (njt)
    ./download_hu.py njt        # only the internal normative instructions from the Nemzeti Jogszabálytár
    ./download_hu.py ia         # optional, NOT run by default: archived copies from web.archive.org

Hungary publishes almost no guidance for decision-makers. The National Directorate-General
for Aliens Policing (Országos Idegenrendészeti Főigazgatóság, OIF) decides residence,
work-related residence (single permit, EU Blue Card, guest-worker permit), return and
asylum matters. Its Director-General's instructions published in the Hivatalos Értesítő
("OIF utasítás", 2019-2026) are all organisational (rules of organisation, rule-making,
fitness tests); its working instruments ("intézkedés", "módszertani útmutató",
"ügyrend") are not published, apart from data-protection and copying rules on oif.gov.hu.

What IS published, in the Hivatalos Értesítő and therefore in the Nemzeti Jogszabálytár
(njt.jog.gov.hu), are a handful of instructions of the National Police Chief (ORFK
utasítás) that tell police officers how to handle aliens-policing cases: border checks,
irregular migrants, SIS hits, removal by air and immigration detention. They are
downloaded here as the consolidated page that njt.jog.gov.hu serves (current version).

Sources
  njt   ORFK instructions on njt.jog.gov.hu (kind = guidance where they instruct officers on
        handling a case, procedural act where they are service rules of a detention facility)
  ia    nothing at present; reserved for archived copies (web.archive.org, 4 s spacing,
        stops after three refusals). Not part of the default run.

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

CODE = "hu"
OUT = Path(__file__).resolve().parent / CODE
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
HOST_DELAY = {"web.archive.org": 4.0}
NJT = "https://njt.jog.gov.hu/jogszabaly/"

ORFK = ("instruction of the National Police Chief (ORFK utasítás), published in the Hivatalos Értesítő; "
        "file = consolidated text served by njt.jog.gov.hu at download time; date = date of the instruction")

# source -> [(url, file, title, date, kind, title_en, note, must_contain)]
SOURCES = {
    "njt": [
        # filled below
    ],
    "ia": [],
}

# (njt id, date, slug, Hungarian title, kind, English title, extra note)
NJT_DOCS = [
    ("2015-24-B0-8E", "2015-10-15", "ORFK-24-2015_hatarforgalom-ellenorzesi-szabalyzat",
     "24/2015. (X. 15.) ORFK utasítás a Határforgalom-ellenőrzési Szabályzatról", "guidance",
     "ORFK instruction 24/2015 on the Border Traffic Control Rules",
     "how border police check persons at crossing points: thorough checks of third-country nationals, checks of "
     "persons with EU free-movement rights and their family members, refusal of entry, visas issued at the border, "
     "entry/exit stamps, database checks"),
    ("2018-36-B0-8E", "2018-06-27", "ORFK-36-2018_illegalis-migracioval-osszefuggo-jogsertesek-kezelese",
     "36/2018. (VI. 27.) ORFK utasítás az illegális migrációval összefüggő jogsértések kezelésével kapcsolatos rendőri feladatok végrehajtására",
     "guidance",
     "ORFK instruction 36/2018 on carrying out police tasks in handling offences connected with illegal migration",
     "which offences count (smuggling, facilitating illegal stay, document fraud, sham family ties, illegal employment of "
     "third-country nationals, unlawful border crossing) and what border and other police units do: detection, "
     "turning back at crossing points, the inland 'illegal migration filter net', reporting and cooperation"),
    ("2023-4-B0-8E", "2023-02-24", "ORFK-4-2023_schengeni-informacios-rendszer-talalat-eljaras",
     "4/2023. (II. 24.) ORFK utasítás a Schengeni Információs Rendszerben elért találat esetén követendő eljárásról",
     "guidance",
     "ORFK instruction 4/2023 on the procedure to follow on a hit in the Schengen Information System",
     "steps for officers on a SIS hit, including entry-ban and return alerts on third-country nationals; replaced 22/2018"),
    ("2016-29-B0-8E", "2016-11-10", "ORFK-29-2016_kulfoldiek-legi-uton-torteno-kitoloncolasa",
     "29/2016. (XI. 10.) ORFK utasítás a külföldiek légi úton történő kitoloncolásának végrehajtásáról", "guidance",
     "ORFK instruction 29/2016 on carrying out the removal of foreigners by air",
     "duties of the Airport Police Directorate escort unit and of the aliens-policing authority (travel documents, "
     "booking, escorts, Frontex joint operations)"),
    ("2014-21-B0-8E", "2014-07-04", "ORFK-21-2014_orzott-szallasok-szolgalati-szabalyzata",
     "21/2014. (VII. 4.) ORFK utasítás a Rendőrség őrzött szállásainak szolgálati szabályzatáról és a menekültügyi őrzött "
     "befogadó központokban végrehajtandó rendőrségi feladatokról", "procedural act",
     "ORFK instruction 21/2014 on the service rules of the police's guarded accommodation (immigration detention) and on "
     "police tasks in guarded asylum reception centres",
     "service rules of immigration detention facilities (admission, guarding, rights of detainees, release); amended "
     "inter alia by 23/2023 and 12/2026 (included in the consolidated text)"),
]

for _id, _date, _slug, _title, _kind, _en, _note in NJT_DOCS:
    SOURCES["njt"].append((NJT + _id, f"{_date}_{_slug}.html", _title, _date, _kind, _en,
                           f"{ORFK}; {_note}; njt id {_id}", "utasítás"))

# (title, date, url, reason) - known to exist, not fetched
NOT_FETCHED = [
    ("Az Országos Idegenrendészeti Főigazgatóság főigazgatói intézkedései, ügyrendjei és módszertani útmutatói "
     "(Director-General's measures, rules of procedure and methodological guides of the OIF on residence, single permit, "
     "EU Blue Card, guest-worker permit, return and asylum cases)", "",
     "https://oif.gov.hu/tajekoztatok/tevekenysegre-mukodesre-vonatkozo-adatok",
     "not published: the OIF publishes as 'OIF utasítás' only organisational rules (SZMSZ, rule-making, fitness tests) and "
     "on oif.gov.hu only its data-protection and copying rules (intézkedés 20/2025 and 7/2025); the case-handling "
     "instruments named in its rules of organisation are internal. Obtainable only by a request under Act CXII of 2011 "
     "(page given)"),
    ("Konzuli/vízumügyi belső utasítások a külképviseletek részére (visa-handling instructions of the Ministry of "
     "Foreign Affairs and Trade to consulates)", "", "https://njt.jog.gov.hu/",
     "not found: the KKM instructions in the Hivatalos Értesítő that surfaced (issuer code B0-6Q on njt) concern "
     "organisation, seals and courier service; the series was not walked number by number, so a published visa "
     "instruction cannot be ruled out. Consular visa instructions are normally internal"),
    ("Kormányhivatalok / foglalkoztatás-felügyeleti hatóság belső eljárásrendje a harmadik országbeli munkavállalók "
     "munkaerőpiaci vizsgálatáról (government offices' internal rules on the labour-market check in single-permit and "
     "guest-worker cases)", "", "https://kormanyhivatalok.hu/",
     "not published: kormanyhivatalok.hu carries employer information leaflets only (applicant information, not collected)"),
]


class Closed(Exception):
    pass


_last, _closed, _robots, _delay, _errs = {}, {}, {}, {}, {}


def _raw(url):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Closed(_closed[host])
    gap = max(HOST_DELAY.get(host, DELAY), _delay.get(host, 0))
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
    except Closed:
        raise
    except Exception:                                             # noqa: BLE001
        txt = None
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


def good(name, data, must):
    """Reject error pages, login pages and bot checks."""
    low = data[:4000].lower()
    if b"just a moment" in low or b"captcha" in low or b"cf-chl" in low:
        return "bot check page"
    if name.endswith(".pdf"):
        return None if data.startswith(b"%PDF") else "server did not return a PDF"
    if must and must.encode("utf-8") not in data:
        return f"page does not contain the expected text ({must})"
    return None if len(data) > 5000 else "page too short"


def main():
    names = sys.argv[1:] or ["njt"]
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

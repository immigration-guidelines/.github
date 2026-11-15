#!/usr/bin/env python3
"""Belgium, regional layer: what the three regions and the German-speaking Community publish for
deciding work authorisations (single permit, work permit B, professional cards), a competence
they hold since the sixth state reform (2014).

    python3 download_be_regions.py            all sources
    python3 download_be_regions.py wal        only the named source(s): vl wal bru dg

Result of the survey (15 November 2026, details in be/regions/NOTES.txt): none of the four
authorities publishes circulars, instructions or a manual for its case officers. Their sites
hold information for employers and applicants, forms and the legal texts. The only texts
addressed to those who handle applications are two pages of the Walloon public service telling
the accredited business counters and the Belgian diplomatic posts how to receive, check and
forward professional-card applications and how to deliver the card; they are saved here.

Files go to be/regions/<vl|wal|bru|dg>/, unmodified. be/regions/index.tsv and
be/regions/not-obtained.tsv are rewritten on every run; NOTES.txt is not touched. Nothing else
in be/ is read or written.

Rules kept: robots.txt of a host is read before anything else is asked of it and obeyed for
'*' and for any group naming an AI agent (wildcards handled here, not by urllib.robotparser);
one request at a time, DELAY seconds apart per host; HTTP 403/429 or three connection errors
in a row end the use of that host for the run; no retries; files already present are skipped.
Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

OUT = Path(__file__).resolve().parent / "be" / "regions"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.6
SLOW = {"web.archive.org": 4.0}
REGION = {"vl": "Flanders", "wal": "Wallonia", "bru": "Brussels-Capital", "dg": "German-speaking Community"}
SOURCES = tuple(REGION)
INDEX_HEADER = "file\tregion\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote"
WAL = "https://emploi.wallonie.be/home/travailleurs-etrangers/carte-professionnelle-independant/"

# (source, file, title, date, url, kind, title_en, note)
DOCS = [
    ("wal", "wal/2026-07-03_carte-professionnelle_guichet-d-entreprises.html",
     "Guichet d'entreprises – Guichet pour les demandes de cartes professionnelles (Wallonie)", "2026-07-03",
     WAL + "guichet-d-entreprises.html", "guidance",
     "Business counters: handling professional-card applications filed in Wallonia (who needs a card, which residence "
     "documents make an application admissible, checks to make, forwarding within 5 days, delivering the card)",
     "web page of SPW Emploi-Formation addressed to the accredited business counters (guichets d'entreprises), which "
     "receive and check applications for the Region; date is the page's last-update stamp; states SPW practice, e.g. "
     "platform work is no longer treated as self-employment and such applications are refused"),
    ("wal", "wal/2026-07-03_carte-professionnelle_poste-diplomatique.html",
     "Poste diplomatique – Guichet pour les demandes de cartes professionnelles (étranger)", "2026-07-03",
     WAL + "poste-diplomatique.html", "guidance",
     "Diplomatic posts: handling professional-card applications filed abroad for an activity in Wallonia",
     "web page of SPW Emploi-Formation addressed to Belgian diplomatic and consular posts; date is the page's "
     "last-update stamp"),
]

# Known to exist but not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Flanders: internal work instructions of the Dienst Economische Migratie (Departement Werk, Economie, Wetenschap, "
     "Innovatie en Sociale Economie) for assessing single-permit and professional-card applications", "",
     "https://www.vlaanderen.be/werken/een-buitenlander-in-vlaanderen-tewerkstellen",
     "not published: the site holds only information for employers, forms, model contracts and the legal texts; no "
     "omzendbrief or richtlijn on the decree of 7 December 2018 or its later amendments was found on vlaanderen.be, in "
     "web search or among the 47 pages read"),
    ("Flanders: 'Wijzigingen in Vlaamse regelgeving rond tewerkstelling van buitenlandse werknemers' (slides on the "
     "amending decree of 1 December 2025) and the 'Economische analyse hernieuwing recht op verblijf' checklists "
     "(1 November 2019)", "2025-12",
     "https://www.vlaanderen.be/werken/een-buitenlander-in-vlaanderen-tewerkstellen",
     "information for employers and applicants, not guidance; in any case hosted on assets.vlaanderen.be, whose "
     "robots.txt reads 'User-agent: * / Disallow: /'"),
    ("Brussels-Capital: any instructions of Brussels Economy and Employment (Direction de la migration économique) on "
     "the ordinance of 1 February 2024 and the decree of 16 May 2024", "",
     "https://economie-emploi.brussels/permis-travail",
     "site not read: its robots.txt shuts out AI agents by name (anthropic-ai, ClaudeBot, Claude-Web, GPTBot: "
     "Disallow: /). Web search and the Wayback Machine index of the site's PDF files show only forms, GDPR notices "
     "and applicant pages; no circular or instruction is known to be published"),
    ("Wallonia: internal instructions of the Direction de l'Emploi et des Permis de travail (SPW Emploi-Formation) on "
     "the decrees of 16 May 2019 and 6 June 2024", "",
     "https://emploi.wallonie.be/home/travailleurs-etrangers/permis-de-travail.html",
     "not published: the 61 pages of the 'Travailleurs étrangers' section hold applicant information, forms and "
     "links to the legal texts only"),
    ("German-speaking Community: instructions of the Ministry (Fachbereich Beschäftigung) on work permits and "
     "professional cards", "",
     "https://ostbelgienlive.be/desktopdefault.aspx/tabid-269",
     "not published: the two sections (Arbeitserlaubnis, Berufskarte) hold applicant information and two application "
     "forms only"),
]


def index_row(d):
    source, name, title, date, url, kind, title_en, note = d
    return [name, REGION[source], title, date, url, kind, title_en, note]


# ----------------------------------------------------------------------------------------------
# Engine (same in download_be_regions.py, download_is.py, download_mt.py, download_cy.py)
# ----------------------------------------------------------------------------------------------
AI_AGENTS = ("claudebot", "anthropic-ai", "claude-web", "claude-user", "claude-searchbot", "gptbot", "ccbot",
             "google-extended", "chatgpt-user", "perplexitybot", "bytespider", "ai")
MAGIC = {".pdf": b"%PDF", ".docx": b"PK", ".xlsx": b"PK", ".doc": b"\xd0\xcf\x11\xe0"}
BAD_HTML = re.compile(rb"captcha|cf-chl|just a moment|access denied|attention required|"
                      rb"enable javascript and cookies|request unsuccessful|incapsula", re.I)

_robots, _last, _closed, _resets, _delay = {}, {}, {}, {}, {}


def _match(pat, path):
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pat)
    if rx.endswith(r"\$"):
        rx = rx[:-2] + "$"
    return re.match(rx, path) is not None


def _pause(host):
    d = _delay.get(host, SLOW.get(host, DELAY))
    w = d - (time.time() - _last.get(host, 0))
    if w > 0:
        time.sleep(w)


def _open(url):
    host = urlsplit(url).netloc
    _pause(host)
    try:
        req = urllib.request.Request(quote(url, safe=":/?&=%#+,;@()~!$'*[]"), headers={"User-Agent": UA})
        with OPENER.open(req, timeout=120) as r:
            data = r.read()
        _resets[host] = 0
        return 200, data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            _closed[host] = f"HTTP {e.code}: host not used any further in this run"
        return e.code, b""
    except Exception as e:                                   # noqa: BLE001 - no retry
        _resets[host] = _resets.get(host, 0) + 1
        if _resets[host] >= 3:
            _closed[host] = "three connection errors in a row: host given up"
        return 0, str(e).encode()
    finally:
        _last[host] = time.time()


def robots(host):
    """Read robots.txt of a host once, before anything else is asked of it. Returns the rule
    groups that apply to this script: '*' and every group naming an AI agent."""
    if host in _robots:
        return _robots[host]
    code, data = _open(f"https://{host}/robots.txt")
    groups = {}
    if code == 200 and b"<html" not in data[:600].lower():
        agents, in_agents = [], False
        for line in data.decode("utf-8", "replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if not in_agents:
                    agents = []
                agents.append(v.lower())
                in_agents = True
            elif k in ("allow", "disallow", "crawl-delay"):
                in_agents = False
                for a in agents:
                    if a == "*" or a in AI_AGENTS:
                        groups.setdefault(a, []).append((k, v))
    elif code in (200, 404):
        pass                                                 # no robots.txt: nothing is excluded
    else:
        _closed.setdefault(host, f"robots.txt could not be read (HTTP {code}): host not used")
    _robots[host] = groups
    for rules in groups.values():
        for k, v in rules:
            if k == "crawl-delay":
                try:
                    _delay[host] = max(float(v), SLOW.get(host, DELAY))
                except ValueError:
                    pass
    return groups


def allowed(url):
    u = urlsplit(url)
    groups = robots(u.netloc)
    if u.netloc in _closed:
        return _closed[u.netloc]
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    for name, rules in groups.items():
        best, ok = -1, True
        for k, v in rules:
            if k == "crawl-delay" or not v:
                continue
            if _match(v, path) and (len(v) > best or (len(v) == best and k == "allow")):
                best, ok = len(v), k == "allow"
        if not ok:
            return f"excluded by robots.txt of {u.netloc} (rules for '{name}')"
    return ""


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        why = allowed(newurl)
        if why:
            raise urllib.error.URLError(f"redirect to {newurl}: {why}")
        _pause(urlsplit(newurl).netloc)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_Redirect())


def save(url, dest):
    """Fetch url into dest unless it exists. Returns '' on success, otherwise the reason."""
    if dest.exists() and dest.stat().st_size > 0:
        return ""
    why = allowed(url)
    if why:
        return why
    code, data = _open(url)
    if code != 200:
        return f"HTTP {code}" if code else "download failed: " + data.decode("utf-8", "replace")[:120]
    ext = dest.suffix.lower()
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        return f"server did not return a {ext[1:]} file"
    if ext in (".html", ".htm") and (len(data) < 2000 or BAD_HTML.search(data[:20000])):
        return "server returned an error, login or bot-check page"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  saved {dest.relative_to(OUT)} ({len(data):,} bytes)")
    return ""


def main(argv):
    wanted = set(argv)
    unknown = wanted - set(SOURCES)
    if unknown:
        sys.exit(f"unknown source(s): {', '.join(sorted(unknown))}; known: {', '.join(sorted(SOURCES))}")
    OUT.mkdir(parents=True, exist_ok=True)
    reasons = {}
    for d in DOCS:
        source, name, url = d[0], d[1], d[4]
        if wanted and source not in wanted:
            continue
        why = save(url, OUT / name)
        if why:
            print(f"  NOT SAVED {name}: {why}")
            reasons[name] = why
    present = [d for d in DOCS if (OUT / d[1]).exists()]
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write(INDEX_HEADER + "\n")
        for d in sorted(present, key=lambda d: d[1]):
            f.write("\t".join(index_row(d)) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for d in DOCS:
            if not (OUT / d[1]).exists():
                f.write("\t".join([d[2], d[3], d[4], reasons.get(d[1], "not downloaded yet (source not run)")]) + "\n")
        for row in NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    kinds = {}
    for d in present:
        kinds[d[5]] = kinds.get(d[5], 0) + 1
    print(f"{OUT.name}: {len(present)} of {len(DOCS)} documents present ({kinds}); "
          f"{len(NOT_OBTAINED) + len(DOCS) - len(present)} rows in not-obtained.tsv")


if __name__ == "__main__":
    main(sys.argv[1:])

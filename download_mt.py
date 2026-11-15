#!/usr/bin/env python3
"""Malta: guidance for those who decide immigration, employment-licence and asylum cases.

    python3 download_mt.py              (no source is downloadable at present; the script rewrites
                                         mt/index.tsv and mt/not-obtained.tsv)

Survey of 15 November 2026 (details in mt/NOTES.txt): nothing could be fetched.
  identita.gov.mt   robots.txt names ClaudeBot, anthropic-ai and Claude-Web with 'Disallow: /'.
  jobsplus.gov.mt   robots.txt itself answers HTTP 403 with a Cloudflare JavaScript challenge.
  ipa.gov.mt        robots.txt answers HTTP 403 with a Cloudflare JavaScript challenge.
  homeaffairs.gov.mt robots.txt answers HTTP 403 with a Cloudflare JavaScript challenge.
  web.archive.org   refused three requests in a row (connection refused, HTTP 503 'temporarily offline').
  index.commoncrawl.org robots.txt excludes the index API ('User-agent: *' / 'Disallow: /').
The documents known to exist are listed in mt/not-obtained.tsv. If the situation changes, add rows to DOCS
(same layout as download_is.py) and re-run: the engine below reads robots.txt first and obeys it.

Files go to mt/<source>/, unmodified. mt/index.tsv and mt/not-obtained.tsv are rewritten on every run;
mt/NOTES.txt is not touched. Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

OUT = Path(__file__).resolve().parent / "mt"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.6
SLOW = {"web.archive.org": 4.0}
SOURCES = ("identita", "jobsplus", "ipa", "homeaffairs")
INDEX_HEADER = "file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote"

# (source, file, title, date, url, kind, title_en, note)
DOCS = []

ID_WHY = ("not fetched: robots.txt of identita.gov.mt excludes ClaudeBot, anthropic-ai and Claude-Web by name "
          "('Disallow: /'); archived copies were not used for a host that excludes AI agents")
CF_WHY = ("not fetched: {h} answers every request, robots.txt included, with HTTP 403 and a Cloudflare "
          "JavaScript challenge; the Internet Archive was unavailable (three refusals in a row) and the Common "
          "Crawl index API is excluded by its robots.txt")

# Known to exist but not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Identità, Expatriates Unit: Family Members Policy (non-employment permits, family members outside the "
     "Family Reunification Regulations, S.L. 217.06), version 5.3", "2025-04-04",
     "https://identita.gov.mt/policies/family-members-policy/", ID_WHY),
    ("Identità, Expatriates Unit: Key Employee Initiative (KEI) policy and conditions", "",
     "https://identita.gov.mt/expatriates-unit-main-page", ID_WHY),
    ("Identità, Expatriates Unit: Specialist Employee Initiative (SEI) policy and conditions", "",
     "https://identita.gov.mt/expatriates-unit-main-page", ID_WHY),
    ("Identità, Expatriates Unit: EU Blue Card conditions (S.L. 217.25) and other employment-related permit "
     "conditions (single permit, intra-corporate transferees)", "",
     "https://identita.gov.mt/expatriates-unit-main-page/noneu-nationals/employment-related-permits/"
     "information-for-non-eu-nationals-and-prospective-employers/", ID_WHY),
    ("Identità: checklists for single-permit applications, including 'Recruiting and Temping Agency' checklists "
     "(new application, still abroad, change of employer) and the KEI checklist", "2024-2026",
     "https://identita.gov.mt/wp-content/uploads/2026/01/Checklist-New-Application-for-Recruiting-and-Temping-"
     "Agency.pdf", "applicant checklists (not guidance); in any case " + ID_WHY[len("not fetched: "):]),
    ("Jobsplus, Employment Licences Unit: guidelines on employment licences for third-country nationals "
     "(elu_guidelines_08_2025_r01)", "2025-08",
     "https://jobsplus.gov.mt/media/haodjchc/elu_guidelines_08_2025_r01.pdf", CF_WHY.format(h="jobsplus.gov.mt")),
    ("International Protection Agency: internal guidelines on the accelerated procedure, on special procedural "
     "guarantees and on lawyers' conduct in interviews (reported by AIDA as existing but unpublished)", "",
     "https://ipa.gov.mt/", "not published (AIDA country report Malta); and ipa.gov.mt cannot be read: "
     + CF_WHY.format(h="ipa.gov.mt")[len("not fetched: "):]),
    ("Ministry for Home Affairs: Malta Labour Migration Policy (2025) and policies on residence (e.g. specific "
     "residence authorisation)", "2025",
     "https://homeaffairs.gov.mt/", "government policy statements rather than guidance to decision-makers; "
     "in any case " + CF_WHY.format(h="homeaffairs.gov.mt")[len("not fetched: "):]),
]


def index_row(d):
    source, name, title, date, url, kind, title_en, note = d
    return [name, title, date, url, kind, title_en, note]


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

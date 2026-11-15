#!/usr/bin/env python3
"""Cyprus: guidance for those who decide immigration, employment and asylum cases.

    python3 download_cy.py              (no source is downloadable at present; the script rewrites
                                         cy/index.tsv and cy/not-obtained.tsv)

Survey of 15 November 2026 (details in cy/NOTES.txt): nothing could be fetched.
  moi.gov.cy / www.moi.gov.cy   (Civil Registry and Migration Department, Asylum Service, Migration Department)
  www.mlsi.gov.cy               (Department of Labour)
      robots.txt: 'User-agent: *' / 'Disallow: /' (only Googlebot is let in).
  www.gov.cy (new portal, Deputy Ministry of Migration and International Protection): allowed by robots.txt,
      but no circular, policy note or instruction for decision-makers was found on it; the old Ministry of
      Finance file of the Business Attraction Strategy (mof.gov.cy/...updated_strategyfebr_2024.pdf) now
      redirects to the gov.cy home page of the ministry.
  web.archive.org refused three requests in a row (connection refused, HTTP 503); the Common Crawl index
      API is excluded by its robots.txt.
The documents known to exist are listed in cy/not-obtained.tsv. If the situation changes, add rows to DOCS
(same layout as download_is.py) and re-run: the engine below reads robots.txt first and obeys it.

Files go to cy/<source>/, unmodified. cy/index.tsv and cy/not-obtained.tsv are rewritten on every run;
cy/NOTES.txt is not touched. Standard library only.
"""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlsplit

OUT = Path(__file__).resolve().parent / "cy"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.6
SLOW = {"web.archive.org": 4.0}
SOURCES = ("crmd", "labour", "asylum", "govcy")
INDEX_HEADER = "file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote"

# (source, file, title, date, url, kind, title_en, note)
DOCS = []

MOI_WHY = ("not fetched: robots.txt of moi.gov.cy and www.moi.gov.cy reads 'User-agent: *' / 'Disallow: /' "
           "(only Googlebot allowed); archived copies were not used for a host that excludes all crawlers")
MLSI_WHY = MOI_WHY.replace("moi.gov.cy and www.moi.gov.cy", "www.mlsi.gov.cy")

# Known to exist but not fetched: (title, date, url, reason)
NOT_OBTAINED = [
    ("Civil Registry and Migration Department: policy for the employment of third-country nationals (pages and "
     "PDFs linked under 'Employment', incl. the policy for companies of foreign interest, Council of Ministers "
     "decisions of 29.11.2006, 2013, 7.10.2020, Nov. 2022 and the 2024 renewal)", "",
     "https://moi.gov.cy/moi/crmd/crmd.nsf/all/2B35F48FA68ADC94C22587AE002F25AA", MOI_WHY),
    ("Civil Registry and Migration Department / Migration Department: EU Blue Card conditions (sectors ICT, "
     "pharmaceutical research, shipping; salary threshold), operational from July 2025", "2025-07",
     "https://moi.gov.cy/moi/CRMD/crmd.nsf/immigrationpfi_en/immigrationpfi_en",
     MOI_WHY + "; what is known of it (from news and law-firm notes) is applicant information"),
    ("Civil Registry and Migration Department: document checklists for entry and work permits (e.g. 'Entry "
     "permit and work permit up to 3 months', 'Work permit from 3 to 6 months', EEZ permits)", "2023",
     "https://moi.gov.cy/MOI/CRMD/crmd.nsf/All/357BCBE3150A0CECC2258939002D3350/$file/WORK%20PERMIT%20FROM%203%20TO%206%20MONTHS.pdf",
     "applicant checklists (not guidance); in any case " + MOI_WHY[len("not fetched: "):]),
    ("Department of Labour: criteria and procedure for approving the employment of third-country nationals "
     "(revised 'Πλαίσιο Εργοδότησης Αλλοδαπών Εργαζομένων' approved by the Council of Ministers, February 2025)",
     "2025-02", "https://www.mlsi.gov.cy/mlsi/dl/dl.nsf/page5a_en/page5a_en",
     MLSI_WHY + ". A copy circulated by the employers' federation OEB is linked from web search "
     "(https://www.oeb.org.cy/wp-content/uploads/2025/02/...FINAL-ΥΣ.pdf) but returned HTTP 404 and is not "
     "an official source"),
    ("Asylum Service: announcement on the implementation of a new policy on the management of Syrian asylum "
     "seekers, and any instructions on the examination of applications", "",
     "https://moi.gov.cy/moi/asylum/asylumservice.nsf/index_en/index_en", MOI_WHY),
    ("Council of Ministers / Ministry of Finance: Business Attraction Strategy (updated February 2024), which "
     "sets the employment criteria for companies of foreign interest", "2024-02",
     "https://mof.gov.cy/assets/modules/wnp/articles/202111/1012/docs/updated_strategyfebr_2024.pdf",
     "the file is gone: the URL now redirects to https://www.gov.cy/mof/ (checked 15 November 2026); it is a "
     "policy statement rather than guidance to decision-makers"),
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

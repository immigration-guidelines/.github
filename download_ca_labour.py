#!/usr/bin/env python3
"""Canada, labour authority: Employment and Social Development Canada (ESDC) / Service Canada,
Temporary Foreign Worker Program - the published criteria for Labour Market Impact Assessments.

    python3 download_ca_labour.py             # everything
    python3 download_ca_labour.py esdc        # the only source; accepted for symmetry

ESDC officers assess LMIA applications; IRCC then decides the work permit. ESDC does not
publish its internal directives or an officer manual (they are known only through
access-to-information releases). What it does publish, and what officers apply, are the
"program requirements" pages of each TFWP stream and a few cross-cutting policy pages
(business legitimacy, refusal to process, wage variations, employer compliance). Those pages
are saved here; purely procedural "how to apply / after you apply" pages, forms, worker
leaflets and reports are left out.

www.canada.ca does not answer scripted requests from this machine (read timeout on robots.txt),
so nothing is requested from it. Each page is the most recent Internet Archive capture, taken
unmodified with the "id_" form: https://web.archive.org/web/<timestamp>id_/<url>.
web.archive.org is asked at most once every 15 s (it refused connections at 4 s spacing on
15 November 2026) and is given up after three refusals in a row; re-run later to fill gaps.

Files already present (any date prefix) are skipped; ca/labour/index.tsv is rewritten from the
files on disk. NOTES.txt and not-obtained.tsv in ca/labour/ are written by hand and left alone.
"""
import gzip
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.5                      # seconds between requests to one host
HOST_DELAY = {"web.archive.org": 15.0}     # 4 s proved too fast: the archive refused connections
AI_AGENTS = ("claudebot", "claude-web", "anthropic-ai", "gptbot", "chatgpt-user", "ccbot", "ai2bot",
             "perplexitybot", "google-extended", "cohere-ai", "bytespider", "amazonbot")

_last = {}        # host -> time of last request
_closed = {}      # host -> reason it may no longer be used
_bad = {}         # host -> consecutive connection failures / refusals
_robots = {}      # host -> list of (allow?, pattern) rules that apply to this script, or None


def _wait(host):
    gap = HOST_DELAY.get(host, DELAY)
    t = _last.get(host)
    if t is not None and time.time() - t < gap:
        time.sleep(gap - (time.time() - t))
    _last[host] = time.time()


def _raw(url, timeout=120):
    """One request. Returns (bytes, final_url, None) or (None, None, reason). No retries."""
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        return None, None, "host closed: " + _closed[host]
    _wait(host)
    quoted = urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")
    try:
        req = urllib.request.Request(quoted, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            if body[:2] == b"\x1f\x8b" and not quoted.endswith(".gz"):
                try:                                        # the archive hands back stored gzip transfer encoding
                    body = gzip.decompress(body)
                except OSError:
                    pass
            _bad[host] = 0
            return body, r.geturl(), None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):                       # a refusal closes the host
            if host == "web.archive.org":                   # archive: give up after three in a row
                _bad[host] = _bad.get(host, 0) + 1
                if _bad[host] >= 3:
                    _closed[host] = "three refusals in a row"
            else:
                _closed[host] = f"HTTP {e.code}"
        return None, None, f"HTTP {e.code}"
    except Exception as e:                                  # noqa: BLE001
        _bad[host] = _bad.get(host, 0) + 1
        if _bad[host] >= 3:
            _closed[host] = "three connection failures in a row"
        return None, None, f"{type(e).__name__}: {e}"


def _rule_matches(pattern, path):
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
    return re.match(rx + ("$" if pattern.endswith("$") else ""), path) is not None


def robots_ok(url):
    """Fetch the host's robots.txt before anything else on that host and apply the rules for
    '*' and for any named AI agent (wildcards handled here; urllib.robotparser ignores them)."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host not in _robots:
        body, _, why = _raw(f"{parts.scheme}://{host}/robots.txt", timeout=60)
        rules = []
        if body is None:
            if why == "HTTP 404":
                pass                                        # no robots.txt: nothing is excluded
            else:
                _closed.setdefault(host, "robots.txt not readable (" + str(why) + ")")
        else:
            agents, fresh = [], True
            for line in body.decode("utf-8", "replace").splitlines():
                line = line.split("#", 1)[0].strip()
                if ":" not in line:
                    continue
                key, val = (x.strip() for x in line.split(":", 1))
                key = key.lower()
                if key == "user-agent":
                    if not fresh:
                        agents, fresh = [], True
                    agents.append(val.lower())
                elif key in ("allow", "disallow"):
                    fresh = False
                    if val and any(a == "*" or a in AI_AGENTS for a in agents):
                        rules.append((key == "allow", val))
                elif key == "crawl-delay":
                    fresh = False
                    if any(a == "*" or a in AI_AGENTS for a in agents):
                        try:
                            HOST_DELAY[host] = max(HOST_DELAY.get(host, DELAY), float(val))
                        except ValueError:
                            pass
        _robots[host] = rules
    if host in _closed:
        return False
    path = parts.path + ("?" + parts.query if parts.query else "")
    best, allowed = -1, True
    for allow, pat in _robots[host]:
        if _rule_matches(pat, path) and (len(pat) > best or (len(pat) == best and allow)):
            best, allowed = len(pat), allow
    return allowed


def get(url, timeout=120):
    """Polite GET that respects robots.txt. Returns (bytes, final_url, None) or (None, None, reason)."""
    if not robots_ok(url):
        host = urllib.parse.urlsplit(url).netloc
        return None, None, _closed.get(host, "excluded by robots.txt")
    return _raw(url, timeout)


def looks_ok(body, name):
    """Reject error, login and bot-check pages: the bytes must match the file type."""
    ext = name.rsplit(".", 1)[-1].lower()
    head = body[:2048].lstrip()
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext in ("docx", "xlsx", "zip"):
        return head.startswith(b"PK")
    if ext in ("doc", "xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0")
    if ext == "xml":
        return head.startswith(b"<?xml") or head.startswith(b"<")
    if ext in ("html", "htm"):
        low = body[:200000].lower()
        return b"<html" in low and b"captcha" not in low and b"access denied" not in low
    return True


def save(url, dest):
    """Download url to dest unless dest exists. Returns None on success, else the reason."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    body, _, why = get(url)
    if body is None:
        return why
    if not looks_ok(body, dest.name):
        return "not the expected file type (error or challenge page?)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(body)
    tmp.rename(dest)
    return None


def clean(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join(clean(x) for x in r) + "\n")


def pdf_ok(path):
    try:
        return subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60).returncode == 0
    except Exception:                                       # noqa: BLE001 - pdfinfo missing: trust the magic bytes
        return True


HEADER = ["file", "title", "date", "source_url", "kind", "title_en", "note"]
NOT_HEADER = ["title", "date", "url", "reason"]
import html as htmlmod

OUT = ROOT / "ca" / "labour"
BASE = "https://www.canada.ca/en/employment-social-development/services/foreign-workers/"
WAYBACK = "https://web.archive.org/web/20261231id_/"       # the archive redirects to the capture nearest this date

# path under BASE (without .html): what the page is
PAGES = {
    "median-wage/high/requirements": "High-wage stream: program requirements (who counts as the employer, wages, recruitment, transition plan)",
    "median-wage/low/requirements": "Low-wage stream: program requirements (cap, refusal to process, wages, recruitment, housing, transport)",
    "median-wage/wage-variations": "Wages below or above the prevailing wage: when a variation is accepted",
    "variations": "Variations to minimum advertising requirements",
    "business-legitimacy": "Business legitimacy: how ESDC verifies that the employer is a genuine, active business able to fulfil the offer",
    "refusal": "Refusal to process an LMIA application (ministerial instructions and policy grounds)",
    "employer-compliance": "Employer compliance: conditions, inspections, penalties and bans",
    "modification-positive-lmia": "Modifying a positive LMIA",
    "lmia-expiry": "Validity and expiry of LMIAs",
    "unamed": "Unnamed LMIAs and adding worker names",
    "temporary-measures": "Temporary policy measures in force",
    "quebec": "LMIA applications for positions in Quebec (joint assessment with the province)",
    "quebec/simplified-process": "Quebec facilitated (simplified) LMIA process",
    "quebec/regular-process": "Quebec regular LMIA process",
    "global-talent/requirements": "Global Talent Stream: program requirements",
    "permanent/requirements": "LMIA in support of permanent residence: program requirements",
    "permanent/recruitment": "LMIA in support of permanent residence: recruitment and advertising",
    "permanent/working-conditions": "LMIA in support of permanent residence: wages and working conditions",
    "caregiver/requirements": "In-home caregivers: program requirements",
    "caregiver/recruitment": "In-home caregivers: recruitment and advertising",
    "caregiver/working-conditions": "In-home caregivers: wages, working conditions and occupations",
    "caregiver/financial-ability": "In-home caregivers: assessing the employer's financial ability",
    "agricultural/agricultural/requirements": "Agricultural stream: program requirements",
    "agricultural/agricultural/recruitment": "Agricultural stream: recruitment and advertising",
    "agricultural/agricultural/working-conditions": "Agricultural stream: wages and working conditions",
    "agricultural/agricultural-wages": "Agricultural wage tables by commodity and province",
    "agricultural/seasonal-agricultural/requirements": "Seasonal Agricultural Worker Program: program requirements",
    "agricultural/seasonal-agricultural/recruitment": "Seasonal Agricultural Worker Program: recruitment and advertising",
    "agricultural/seasonal-agricultural/working-conditions": "Seasonal Agricultural Worker Program: wages and working conditions",
    "academic": "Academics: overview of LMIA requirements and exemptions",
    "academic/exemption": "Academics: LMIA exemptions",
    "academic/recruitment": "Academics: recruitment and advertising",
    "academic/working-conditions": "Academics: wages and working conditions",
    "recognized-employer/requirements": "Recognized Employer Pilot: program requirements",
    "recognized-employer/working-conditions": "Recognized Employer Pilot: wages and working conditions",
}


def slug(path):
    return path.replace("/", "_")


def meta(text):
    t = re.search(r"<title>([^<]*)", text)
    d = re.search(r'name="dcterms\.modified"[^>]*content="([0-9-]{10})', text)
    title = htmlmod.unescape(t.group(1)).replace(" - Canada.ca", "").strip() if t else ""
    return title, d.group(1) if d else ""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    caps = {}                                           # slug -> archive capture the file came from
    idx = OUT / "index.tsv"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            m = re.search(r"https://web\.archive\.org/\S+", f[-1])
            if m:
                caps[f[0].split("_", 1)[1][:-5]] = m.group(0)
    for path in PAGES:
        url = BASE + path + ".html"
        if list(OUT.glob(f"*_{slug(path)}.html")):
            continue
        body, final, why = get(WAYBACK + url)
        if body is None:
            failed.append((path, url, why))
            print(f"FAILED\t{url}\t{why}")
            continue
        text = body.decode("utf-8", "replace")
        title, date = meta(text)
        if not date or "employment-social-development" not in text or not looks_ok(body, "x.html"):
            failed.append((path, url, "capture is not the page (no dcterms.modified)"))
            print(f"FAILED\t{url}\tnot the expected page")
            continue
        (OUT / f"{date}_{slug(path)}.html").write_bytes(body)
        caps[slug(path)] = final
        print(f"saved {date}_{slug(path)}.html")
    rows = []
    for path, what in PAGES.items():
        for f in sorted(OUT.glob(f"*_{slug(path)}.html")):
            title, date = meta(f.read_text(encoding="utf-8", errors="replace"))
            rows.append([f.name, title, date, BASE + path + ".html", "guidance", what,
                         "employer-facing statement of the criteria ESDC officers apply; date = 'date modified' on the page; "
                         "copy from the Internet Archive: " + caps.get(slug(path), "capture not recorded")])
    rows.sort()
    write_tsv(OUT / "index.tsv", HEADER, rows)
    print(f"index.tsv: {len(rows)} rows; {len(failed)} failed")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Austria, labour authority: Arbeitsmarktservice (AMS) federal guidelines that touch the
employment of third-country nationals.

    python3 download_at_labour.py

The AMS decides employment permits and gives the labour-market opinion for the Red-White-Red
Card and EU Blue Card under the Ausländerbeschäftigungsgesetz (AuslBG). It publishes its
federal guidelines (Bundesrichtlinien) at
    https://www.ams.at/organisation/ueber-ams/ams-richtlinien
    https://www.ams.at/organisation/kontaktmoeglichkeiten/informationsfreiheit-ams
but none of them is about the AuslBG, the Red-White-Red Card or the EU Blue Card. The only
published instructions that reach the subject are the two "core process" guidelines saved
here: the one for the employer service contains the replacement-worker procedure
(Ersatzkraftverfahren, the labour-market test of §§ 4(1) and 4b AuslBG), the one for the
jobseeker service the rules on registering and placing third-country nationals.

www.ams.at robots.txt (read first) excludes only its search pages. Files already present are
skipped; at/labour/index.tsv is rewritten. NOTES.txt is written by hand and left alone.
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
HOST_DELAY = {"web.archive.org": 4.0}
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

OUT = ROOT / "at" / "labour"
BASE = "https://www.ams.at/content/dam/ifg-ver%C3%B6ffentlichungen/001_bgs/"
LISTING = "https://www.ams.at/organisation/kontaktmoeglichkeiten/informationsfreiheit-ams"

# (file, date, title, English gloss, url, note)
ITEMS = [
    ("2026-09-01_BRL_Kernprozess-Unternehmen-unterstuetzen_SFU-2-2026.pdf", "2026-09-01",
     "Bundesrichtlinie Kernprozess „Unternehmen unterstützen“ (SFU/2-2026, GZ BGS/SFU/0602/6264/2026), gültig ab 01.09.2026",
     "Federal guideline, core process 'Supporting enterprises' (employer service): 103 pages; section 6.1.4.2 "
     "employment of third-country nationals, section 9.2.1 replacement-worker procedure (labour-market test, "
     "§§ 4(1) and 4b AuslBG), handling of AuslBG violations and of temporary-work agencies as customers",
     BASE + "001_brl_kernprozess-unternehmen-unterstuetzen_ab_01092026.pdf",
     "signed 1 July 2026; replaces SFU/1-2026 (in force from 2 March 2026, no longer on the site); listed at " + LISTING),
    ("2025-07-01_BRL_Kernprozess-Arbeitskraefte-unterstuetzen.pdf", "2025-07-01",
     "Bundesrichtlinie Kernprozess Arbeitskräfte unterstützen, gültig ab 01.07.2025",
     "Federal guideline, core process 'Supporting workers' (jobseeker service): 146 pages; registration of "
     "third-country nationals as jobseekers, placement rules for foreigners without free labour-market access "
     "(no placement with temporary-work agencies, § 4(1) no. 7 AuslBG)",
     BASE + "001_brl_kernprozess-arbeitskraefte-unterstuetzen_ab_01072025.pdf",
     "listed at " + LISTING),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, date, title, title_en, url, note in ITEMS:
        why = save(url, OUT / name)
        if why is None and not pdf_ok(OUT / name):
            (OUT / name).unlink()
            why = "pdfinfo rejects the file"
        if why:
            print(f"FAILED\t{name}\t{url}\t{why}")
            continue
        rows.append([name, title, date, url, "guidance", title_en, note])
    write_tsv(OUT / "index.tsv", HEADER, rows)
    print(f"index.tsv: {len(rows)} rows")


if __name__ == "__main__":
    main()

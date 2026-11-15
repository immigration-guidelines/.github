#!/usr/bin/env python3
"""Ghana: published guidance for officials deciding immigration cases. See gh/NOTES.txt.

    python3 download_gh.py [source ...]      sources: gis

The Ghana Immigration Service publishes one item written for its officers, the Legal Handbook
of August 2016 (produced with IOM and EU funding "to enhance the capacity of law enforcement
officers to interpret and apply relevant laws"; mostly a compilation of the laws), and the two
legislative instruments that set the application procedures: the Immigration Regulations 2001
(L.I. 1691) and the Citizenship Regulations 2001 (L.I. 1690). The Ghana Refugee Board publishes
no procedure.

Rules followed: robots.txt is read for every host before the first request and obeyed
(wildcards, groups naming AI agents and 'ai-input=no' content signals included); one request at
a time, 1.5 s apart (4 s for web.archive.org); a host answering 401/403/429 or failing three
times in a row is dropped for the run; no retries; no redirects to other hosts. Existing files
are skipped. gh/index.tsv and gh/not-obtained.tsv are rewritten on every run. Standard library
only (pdfinfo, when installed, checks every PDF).
"""

import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = {"web.archive.org": 4.0}             # seconds between requests to one host
DEFAULT_DELAY = 1.5
G, P = "guidance", "procedural act"
# robots.txt groups naming these agents are treated as applying to this script
AI_AGENTS = ("claudebot", "claude-web", "claude-user", "claude-searchbot", "anthropic-ai", "gptbot",
             "chatgpt-user", "oai-searchbot", "ccbot", "google-extended", "perplexitybot", "bytespider",
             "applebot-extended", "meta-externalagent", "cohere-ai")


def _rule_regex(path):
    """robots.txt path pattern (with * and $) as a regular expression."""
    end = path.endswith("$")
    if end:
        path = path[:-1]
    rx = "".join(".*" if c == "*" else re.escape(c) for c in path)
    return re.compile(rx + ("$" if end else ""))


class Robots:
    """Minimal robots.txt reader that honours * and $ wildcards (urllib.robotparser does not),
    applies the '*' group together with any group naming an AI agent, and treats
    'Content-Signal: ... ai-input=no' as a refusal."""

    def __init__(self, text):
        self.rules = []                       # (allow?, pattern text, regex)
        self.refuse = None
        groups, agents, in_rules = [], [], False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (s.strip() for s in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if in_rules or not groups:          # a new group starts
                    agents, in_rules = [val.lower()], False
                    groups.append((agents, []))
                else:                               # another agent line of the same group
                    agents.append(val.lower())
            elif key in ("allow", "disallow") and agents:
                in_rules = True
                groups[-1][1].append((key == "allow", val))
            elif key == "content-signal" and re.search(r"ai-input\s*=\s*no", val, re.I):
                self.refuse = "robots.txt content signal ai-input=no"
        for names, rules in groups:
            if any(n == "*" or any(a in n for a in AI_AGENTS) for n in names):
                ai = any(any(a in n for a in AI_AGENTS) for n in names)
                for allow, pat in rules:
                    if pat == "" and not allow:
                        continue              # "Disallow:" with no path allows everything
                    if ai and not allow and pat == "/":
                        self.refuse = f"robots.txt disallows {', '.join(names)}"
                    self.rules.append((allow, pat, _rule_regex(pat)))

    def allowed(self, url):
        parts = urllib.parse.urlsplit(url)
        path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
        best = None
        for allow, pat, rx in self.rules:
            if rx.match(path) and (best is None or len(pat) > len(best[1]) or
                                   (len(pat) == len(best[1]) and allow)):
                best = (allow, pat)
        return best is None or best[0]


class NoCrossHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            raise urllib.error.HTTPError(req.full_url, code, "redirect to another host: " + newurl,
                                         headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(NoCrossHost)


class Site:
    """One host: robots.txt read once, sequential paced requests, dropped on refusal."""
    sites = {}

    def __init__(self, host, scheme):
        self.host, self.blocked, self.resets = host, None, 0
        self.delay = DELAY.get(host, DEFAULT_DELAY)
        self.robots = Robots("")
        try:
            req = urllib.request.Request(f"{scheme}://{host}/robots.txt", headers={"User-Agent": UA})
            with OPENER.open(req, timeout=60) as r:
                self.robots = Robots(r.read().decode("utf-8", "replace"))
            self.blocked = self.robots.refuse and f"{self.robots.refuse}; host not used"
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429) or e.code >= 500:
                self.blocked = f"robots.txt of {host} answered HTTP {e.code}; host not used"
        except Exception as e:                     # noqa: BLE001
            self.blocked = f"robots.txt of {host} not readable ({e}); host not used"
        self.last = time.time()

    @classmethod
    def of(cls, url):
        parts = urllib.parse.urlsplit(url)
        if parts.netloc not in cls.sites:
            cls.sites[parts.netloc] = cls(parts.netloc, parts.scheme)
        return cls.sites[parts.netloc]

    def get(self, url):
        """Returns (data, None) or (None, reason)."""
        if self.blocked:
            return None, self.blocked
        if not self.robots.allowed(url):
            return None, "disallowed by robots.txt"
        time.sleep(max(0.0, self.delay - (time.time() - self.last)))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with OPENER.open(req, timeout=300) as r:
                data = r.read()
                expected = r.headers.get("Content-Length")
            self.resets = 0
            if expected and expected.isdigit() and int(expected) != len(data):
                return None, f"incomplete download ({len(data)} of {expected} bytes)"
            return data, None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                self.blocked = f"HTTP {e.code} from {self.host}; host dropped for this run"
            return None, f"HTTP {e.code}"
        except Exception as e:                     # noqa: BLE001 - refused, reset, timeout
            self.resets += 1
            if self.resets >= 3:
                self.blocked = f"{self.host} failed three requests in a row; host dropped for this run"
            return None, str(e)
        finally:
            self.last = time.time()


MAGIC = {".png": b"\x89PNG", ".jpg": b"\xff\xd8\xff", ".docx": b"PK\x03\x04"}


def valid(dest, data):
    """None if data looks like the document it should be, else the reason."""
    ext = dest.suffix.lower()
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            return "not a PDF (error or bot-check page?)"
        if shutil.which("pdfinfo"):
            tmp = dest.with_name(dest.name + ".part")
            tmp.write_bytes(data)
            ok = subprocess.run(["pdfinfo", str(tmp)], capture_output=True).returncode == 0
            tmp.unlink()
            if not ok:
                return "pdfinfo cannot read the file (truncated or damaged)"
        return None
    if ext in MAGIC and not data.startswith(MAGIC[ext]):
        return f"not a {ext} file (error page?)"
    return None


def run(out, docs, not_obtained):
    """docs: (file, title, date, kind, title_en, official, source name, [urls])."""
    out.mkdir(exist_ok=True)
    wanted = set(sys.argv[1:])
    known = {}
    idx = out / "index.tsv"
    if idx.exists():
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 4:
                known[parts[0]] = parts[3]
    rows, failed = [], []
    for name, title, date, kind, title_en, official, source, urls in docs:
        dest = out / name
        used, why = None, "not attempted (source not selected)"
        if dest.exists() and dest.stat().st_size > 0:
            used, why = known.get(name, urls[0]), None
        elif not wanted or source in wanted:
            for url in urls:
                data, why = Site.of(url).get(url)
                if data is not None:
                    why = valid(dest, data)
                if why is None:
                    dest.write_bytes(data)
                    used = url
                    print(f"  saved {name}")
                    break
        if why is None:
            rows.append((name, title, date, used, kind, title_en, official))
        else:
            print(f"  NOT SAVED {name}: {why}")
            failed.append((title, date, urls[0], why))
    rows.sort()
    with open(idx, "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tofficial\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    with open(out / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for row in failed + not_obtained:
            f.write("\t".join(row) + "\n")
    guid = sum(1 for r in rows if r[4] == G)
    print(f"{out.name}: {len(rows)} of {len(docs)} documents present ({guid} guidance, "
          f"{len(rows) - guid} procedural acts); {len(failed) + len(not_obtained)} items in not-obtained.tsv")

OUT = Path(__file__).resolve().parent / "gh"

# (file, title, date, kind, title_en, official, source name, [addresses to try in order])
DOCS = [
    ("2016-08_GIS-Legal-Handbook.pdf",
     "Ghana Immigration Service Legal Handbook, August 2016 (for immigration officers; GIS with IOM, "
     "EU-funded GIMMA project; mainly a compilation of immigration, security and investment laws)",
     "2016-08", G, "", "yes", "gis",
     ["https://gis.gov.gh/wp-content/uploads/2024/02/Legal-Handbook-2016.pdf"]),
    ("2001_LI-1691_Immigration-Regulations-2001.pdf",
     "Immigration Regulations, 2001 (L.I. 1691): entry, visas and permits, residence, indefinite residence, "
     "employment of foreign nationals",
     "2001", P, "", "yes", "gis",
     ["https://gis.gov.gh/wp-content/uploads/2024/02/LI-1691.pdf"]),
    ("2001_LI-1690_Citizenship-Regulations-2001.pdf",
     "Citizenship Regulations, 2001 (L.I. 1690): applications for citizenship by registration and "
     "naturalisation, investigation of applications, dual citizenship, renunciation and deprivation",
     "2001", P, "", "yes", "gis",
     ["https://gis.gov.gh/wp-content/uploads/2024/02/LI-1690.pdf"]),
]

# Items known to exist that are not in the folder: (title, date, url, reason)
NOT_OBTAINED = [
    ("Standard operating procedures or permit guidelines of the Ghana Immigration Service for officers", "",
     "https://gis.gov.gh/", "not published (the site's media library, about 47 PDFs, and the web archive of "
     "gis.gov.gh, www.gis.gov.gh and home.gis.gov.gh back to 2019 hold laws, forms, fees, reports and policies only)"),
    ("Immigration Service Regulations, 2016 (L.I. 2245)", "2016",
     "https://web.archive.org/web/20250405105704/https://gis.gov.gh/gis_library/IMMIGRATION-SERVICE-REGULATIONS-2016-L.I.-2245.pdf",
     "left out on purpose after reading it: conditions of service of immigration staff (recruitment, ranks, "
     "allowances, leave), not case procedure; no longer on the live site (HTTP 404)"),
    ("Refugee status determination procedure or manual of the Ghana Refugee Board", "", "https://grb.gov.gh/",
     "not published; the Board's site has descriptive pages and Right to Information manuals only"),
    ("Ghana Refugee Board Right to Information manuals 2024 and 2025", "2025",
     "https://www.grb.gov.gh/file/GRB%20MANUAL%202025.pdf",
     "left out on purpose: manual on access to the Board's information under the RTI Act, not refugee decisions"),
    ("Ghana Immigration Service Client Service Charter (September 2022)", "2022-09",
     "https://gis.gov.gh/wp-content/uploads/2024/02/THE-NEW-GIS-SERVICE-CHARTER.pdf",
     "left out on purpose: service charter for the public"),
    ("Ghana Immigration Service code of conduct, HR policy, gender policy, strategic plans", "",
     "https://gis.gov.gh/wp-content/uploads/2024/02/new-code-of-conduct-April-25th-Justified-File-1-With-Cover-1_compressed-1.pdf",
     "left out on purpose: staff conduct and corporate documents, not case-handling guidance"),
    ("Ghana gazettes on gazettes.africa", "", "https://gazettes.africa/",
     "robots.txt names AI agents and sets the content signal ai-input=no; not used"),
]


if __name__ == "__main__":
    run(OUT, DOCS, NOT_OBTAINED)

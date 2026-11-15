#!/usr/bin/env python3
"""Rwanda: published guidance for officials deciding immigration cases. See rw/NOTES.txt.

    python3 download_rw.py [source ...]      sources: dgie

The Directorate General of Immigration and Emigration (DGIE) publishes no officer guidance.
Saved are three procedural acts from its "Laws" and "ODL" pages that set out visa and permit
classes, nationality procedure and the occupations-in-demand list used for work permits. The
Official Gazette texts are trilingual (Kinyarwanda, English, French); titles are given in English.
The Ministry in charge of Emergency Management (MINEMA, refugees) could not be used: its
robots.txt excludes CCBot (see not-obtained.tsv).

Rules followed: robots.txt is read for every host before the first request and obeyed
(wildcards, groups naming AI agents and 'ai-input=no' content signals included); one request at
a time, 1.5 s apart (4 s for web.archive.org); a host answering 401/403/429 or failing three
times in a row is dropped for the run; no retries; no redirects to other hosts. Existing files
are skipped. rw/index.tsv and rw/not-obtained.tsv are rewritten on every run. Standard library
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

OUT = Path(__file__).resolve().parent / "rw"
DGIE = "https://www.migration.gov.rw/fileadmin/user_upload/pdf_files/"

# (file, title, date, kind, title_en, official, source name, [addresses to try in order])
DOCS = [
    ("2019-05-29_Ministerial-Order-No-06-01-relating-to-immigration-and-emigration.pdf",
     "Ministerial Order N°06/01 of 29/05/2019 relating to Immigration and Emigration (Official Gazette "
     "no. Special of 30/05/2019; visa and residence permit classes, requirements and procedure)",
     "2019-05-29", P, "", "yes", "dgie", [DGIE + "ministerial_order_relating_to_immigration.pdf"]),
    ("2022-03-23_Ministerial-Order-No-007-01-relating-to-Rwandan-nationality.pdf",
     "Ministerial Order Nº 007/01 of 23/03/2022 relating to Rwandan nationality (Official Gazette n° Special "
     "of 25/03/2022; applications for acquisition and reacquisition of nationality)",
     "2022-03-23", P, "", "yes", "dgie", [DGIE + "ministerial_order_relating_to_rwandan_nationality1.pdf"]),
    ("2022-08-30_Occupations-in-demand-list_Annex-III-Ministerial-Order-No-02-MIFOTRA-22.pdf",
     "Annex III to Ministerial Order Nº 02/MIFOTRA/22 of 30/08/2022: occupations in demand list (employment "
     "of foreigners; Official Gazette n° Special of 02/09/2022)",
     "2022-08-30", P, "", "yes", "dgie", [DGIE + "ministerial_order_11_11_2022_2.pdf"]),
]

# Items known to exist that are not in the folder: (title, date, url, reason)
NOT_OBTAINED = [
    ("Prime Minister's Order No 112/03 of 19/06/2015 determining the organisation and functioning of the National "
     "Refugee Status Determination Committee, and any later order under Law No 042/2024 on refugees", "2015-06-19",
     "https://www.refworld.org/legal/decreees/natlegbod/2015/en/115880",
     "the Ministry in charge of Emergency Management (www.minema.gov.rw) robots.txt disallows CCBot, treated as "
     "excluding AI agents; www.refworld.org answers robots.txt with HTTP 403; policyvault.africa refuses "
     "connections; no other official copy found"),
    ("Ministerial Instructions N°003/19.18 of 04/04/2013 determining the occupations in demand list", "2013-04-04",
     "https://www.migration.gov.rw/laws",
     "the link on the DGIE 'Laws' page points to the 2019 immigration order instead; superseded by the 2022 list"),
    ("Standard operating procedures, permit guidelines or service standards of the DGIE for officers", "",
     "https://www.migration.gov.rw/1-1/sops",
     "not published; the 'SOPs' page holds only a personal-data notice for persons relocated under the "
     "UK-Rwanda partnership"),
    ("MEDP 'Standard operation procedure on how we handle your personal data' (2024)", "2024-05",
     DGIE + "sop_data_protection_medp_factsheet.pdf",
     "left out on purpose: privacy notice addressed to relocated persons, not guidance on decisions"),
    ("DGIE clients charter and permit/visa service pages", "", "https://www.migration.gov.rw/client-charter",
     "left out on purpose: information for applicants"),
    ("Law N°57/2018 on immigration and emigration, Organic Law N°002/2021.OL on nationality, Law N°042/2024 on "
     "refugees, border-post and API/PNR instruments", "", "https://www.migration.gov.rw/laws",
     "left out on purpose: statutes, or instruments not about case decisions"),
]


if __name__ == "__main__":
    run(OUT, DOCS, NOT_OBTAINED)

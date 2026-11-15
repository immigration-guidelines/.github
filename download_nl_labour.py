#!/usr/bin/env python3
"""Netherlands, labour authority: the rules UWV applies when it decides or advises on work permits.

    python3 download_nl_labour.py            # everything
    python3 download_nl_labour.py ruwav2022  # only the named source(s)

UWV (Uitvoeringsinstituut Werknemersverzekeringen) decides applications for a work permit
(tewerkstellingsvergunning) and advises the IND on combined permits (GVVA) under the Foreign
Nationals Employment Act (Wet arbeid vreemdelingen, Wav). Its working rules are published as
legal texts in the Basiswettenbestand:

  ruwav2022   Regeling uitvoering Wet arbeid vreemdelingen 2022 (ministerial regulation; its
              annex I is the detailed "uitvoeringsregels" UWV applies)           BWBR0046054
  ruwav2014   Regeling uitvoering Wet arbeid vreemdelingen 2014                  BWBR0034945
  delegatie   Delegatie- en uitvoeringsbesluit Wet arbeid vreemdelingen (1995 - 2013; annex:
              Uitvoeringsregels Wav)                                             BWBR0007514
  uwv2018     UWV Beleidsregels uitvoering Wav 2018 (policy rules of UWV itself) BWBR0041410
  uwv2009     UWV Beleidsregels uitvoering Wav (2009 - 2013)                     BWBR0024885

  uwvwoo      UWV internal guidance released under the Open Government Act (Woo): Woo decision
              2025016 of 26 June 2025 ("Woo-besluit kennismigrantenregeling"), annexes 2-11 -
              the work instruction on market-rate salary advice for knowledge migrants and EU Blue
              Card holders, two pages of the internal handbook "Wetsuitleg Werkvergunningen", and
              internal e-mails settling how the salary test is applied. Taken from www.uwv.nl
              (robots.txt read first: only /nl/webpublicaties is excluded). Annex 12 (a list of
              case numbers) and the decision letter itself are not kept.

Every consolidated version of each BWB text is taken, as XML, from the government's bulk repository
https://repository.officiele-overheidspublicaties.nl/bwb/<id>/ (no robots.txt; bulk download
is the purpose of that host). wetten.overheid.nl itself is NOT used: its robots.txt excludes
AI agents by name. Files already present are skipped; nl/labour/index.tsv is rewritten.
NOTES.txt and not-obtained.tsv in nl/labour/ are written by hand and left alone.
"""
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

OUT = ROOT / "nl" / "labour"
REPO = "https://repository.officiele-overheidspublicaties.nl/bwb"

# name: (BWB id, kind, Dutch title, English gloss)
WORKS = {
    "ruwav2022": ("BWBR0046054", "procedural act", "Regeling uitvoering Wet arbeid vreemdelingen 2022",
                  "Regulation implementing the Foreign Nationals Employment Act 2022 (with annex I, the implementation rules UWV applies to work-permit and combined-permit cases)"),
    "ruwav2014": ("BWBR0034945", "procedural act", "Regeling uitvoering Wet arbeid vreemdelingen 2014",
                  "Regulation implementing the Foreign Nationals Employment Act 2014 (with annex I, implementation rules)"),
    "delegatie": ("BWBR0007514", "procedural act", "Delegatie- en uitvoeringsbesluit Wet arbeid vreemdelingen",
                  "Delegation and Implementation Order, Foreign Nationals Employment Act (with annex: Implementation Rules Wav)"),
    "uwv2018": ("BWBR0041410", "guidance", "UWV Beleidsregels uitvoering Wav 2018",
                "UWV policy rules on implementing the Foreign Nationals Employment Act 2018"),
    "uwv2009": ("BWBR0024885", "guidance", "UWV Beleidsregels uitvoering Wav",
                "UWV policy rules on implementing the Foreign Nationals Employment Act (2009)"),
}


WOO_PAGE = "https://www.uwv.nl/nl/wet-open-overheid/woo-publicaties/2025/woo-besluit-kennismigrantenregeling"
# file-name stem on uwv.nl -> (saved name, date, Dutch title, English gloss)
WOO_FILES = {
    "bijlage-11-werkinstructie-adviesverzoeken-mc-loon-def-geanonimiseerd":
        ("2024_werkinstructie-adviesverzoeken-marktconform-loon-km-ebk.pdf", "2024",
         "Werkinstructie adviesverzoeken marktconform loon (kennismigranten/Europese blauwe kaart), bestemd voor Bureau TWV (Woo-besluit 2025016, bijlage 11, geanonimiseerd)",
         "Work instruction for the work-permit bureau: advising the IND on whether the salary offered to a knowledge migrant or EU Blue Card applicant is at market rate (amounts for 2024); includes assessment at the actual employer where the worker is hired out"),
    "bijlage-2-handboek-uwv-marktconforme-beloning-kennismigranten-geanonimiseerd":
        ("2025_handboek-wetsuitleg-werkvergunningen_marktconforme-beloning-kennismigranten.pdf", "2025",
         "Handboek Wetsuitleg Werkvergunningen - Adviesverzoeken IND - Marktconforme beloning kennismigranten (Woo-besluit 2025016, bijlage 2, geanonimiseerd)",
         "Internal handbook 'Legal interpretation: work permits', page on IND advice requests - market-rate pay of knowledge migrants and EU Blue Card holders"),
    "bijlage-10-handboek-uwv-toetsmoment-loon-geanonimiseerd":
        ("2025_handboek-wetsuitleg-werkvergunningen_toetsmoment-loon.pdf", "2025",
         "Handboek Wetsuitleg Werkvergunningen - Duur en inhoud werkvergunning - Toetsmoment loon (Woo-besluit 2025016, bijlage 10, geanonimiseerd)",
         "Internal handbook 'Legal interpretation: work permits', page on the reference date for testing the salary (and age) of knowledge migrants"),
    "bijlage-6-re-vraag-toets-moment-leeftijd-kennismigrant -deel-1-geanonimiseerd":
        ("2024-03-15_email_toetsmoment-leeftijd-kennismigrant_deel-1.pdf", "2024-03-15",
         "E-mailwisseling UWV/IND 'Vraag toetsmoment leeftijd kennismigrant', deel 1 (Woo-besluit 2025016, bijlage 6, geanonimiseerd)",
         "Internal UWV-IND e-mails settling the reference date for the age-dependent salary threshold, part 1"),
    "bijlage-7-re-vraag-toets-moment-leeftijd-kennismigrant-deel-2-geanonimiseerd":
        ("2024-11-21_email_toetsmoment-leeftijd-kennismigrant_deel-2.pdf", "2024-11-21",
         "E-mailwisseling UWV/IND 'Vraag toetsmoment leeftijd kennismigrant', deel 2 (Woo-besluit 2025016, bijlage 7, geanonimiseerd)",
         "Internal UWV-IND e-mails settling the reference date for the age-dependent salary threshold, part 2 (November 2024 - January 2025)"),
    "bijlage-8-re-werkinstructie-toetsmoment-loon-deel-1-geanonimiseerd":
        ("2024-09-09_email_werkinstructie-toetsmoment-loon_deel-1.pdf", "2024-09-09",
         "Interne e-mail 'Werkinstructie toetsmoment loon', deel 1 (Woo-besluit 2025016, bijlage 8, geanonimiseerd)",
         "Internal e-mail instructing staff on the reference date for the salary test, part 1"),
    "bijlage-9-re- werkinstructie-toetsmoment-loon-deel-2-geanonimiseerd":
        ("2025-01-08_email_werkinstructie-toetsmoment-loon_deel-2.pdf", "2025-01-08",
         "Interne e-mail 'Werkinstructie toetsmoment loon', deel 2 (Woo-besluit 2025016, bijlage 9, geanonimiseerd)",
         "Internal e-mail instructing staff on the reference date for the salary test, part 2"),
    "bijlage-3-re-adv-toeslag-mc-geanonimiseerd":
        ("2025-01-23_email_adv-toeslag-marktconform.pdf", "2025-01-23",
         "Interne e-mail 'ADV-toeslag MC' (Woo-besluit 2025016, bijlage 3, geanonimiseerd)",
         "Internal e-mail on whether paid-out reduced-working-hours (ADV) allowances count towards the market-rate salary"),
    "bijlage-4-re-kennismigranten-geanonimiseerd":
        ("2025-01-23_email_kennismigranten.pdf", "2025-01-23",
         "Interne e-mail 'Kennismigranten' (Woo-besluit 2025016, bijlage 4, geanonimiseerd)",
         "Internal e-mail on the reference date (ex tunc / ex nunc) when re-examining knowledge-migrant advice on objection"),
    "bijlage-5-re-onkostenvergoeding-bij-km-regeling-geanonimiseerd-":
        ("2025-01-23_email_onkostenvergoeding-km-regeling.pdf", "2025-01-23",
         "Interne e-mail 'Onkostenvergoeding bij KM regeling' (Woo-besluit 2025016, bijlage 5, geanonimiseerd)",
         "Internal e-mail on expense allowances and monthly ADV pay-outs in knowledge-migrant salary assessments"),
}


def woo(rows, failed):
    """UWV Woo decision 2025016: read the publication page, save the listed annexes."""
    body, _, why = get(WOO_PAGE)
    if body is None:
        print(f"uwvwoo: page not fetched: {why}")
        return False
    links = {}
    for href in re.findall(r'(?:href|link-url)="(/assets-kai/files/[^"]+\.pdf)"', body.decode("utf-8", "replace")):
        stem = urllib.parse.unquote(href.rsplit("/", 1)[1])[:-4]
        links[stem] = "https://www.uwv.nl" + href
    got = 0
    for stem, (name, date, title, title_en) in WOO_FILES.items():
        url = links.get(stem)
        if not url:
            failed.append((title, date, WOO_PAGE, "no longer linked from the publication page"))
            continue
        rel = "uwvwoo/" + name
        why = save(url, OUT / rel)
        if why is None and not pdf_ok(OUT / rel):
            (OUT / rel).unlink()
            why = "pdfinfo rejects the file"
        if why:
            failed.append((title, date, url, why))
            continue
        got += 1
        rows[rel] = [rel, title, date, url, "guidance", title_en,
                     "released in anonymised form with UWV Woo decision 2025016 of 26 June 2025; listed at " + WOO_PAGE]
    print(f"uwvwoo: {got} of {len(WOO_FILES)} files present")
    return True


def versions(manifest):
    """(label, valid_from, valid_to, item file name) for every non-deleted XML version."""
    out = []
    for m in re.finditer(r'<expression label="([^"]+)">(.*?)</expression>', manifest, re.S):
        label, body = m.group(1), m.group(2)
        start = re.search(r"<datum_inwerkingtreding>([^<]+)", body)
        end = re.search(r"<einddatum>([^<]+)", body)
        xml = re.search(r'<manifestation label="xml">(.*?)</manifestation>', body, re.S)
        item = re.search(r'<item label="([^"]+\.xml)"(?: _deleted="(\w+)")?', xml.group(1)) if xml else None
        if not item or item.group(2) == "true":
            continue
        out.append((label, start.group(1) if start else label[:10], end.group(1) if end else "", item.group(1)))
    return out


def main():
    names = list(WORKS) + ["uwvwoo"]
    wanted = [a for a in sys.argv[1:] if a in names] or names
    OUT.mkdir(parents=True, exist_ok=True)
    old = {}
    idx = OUT / "index.tsv"
    if idx.exists():                                    # keep rows of sources not run this time
        for line in idx.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            old[f[0]] = f
    rows, failed = {}, []
    for name in WORKS:
        bwb, kind, title, title_en = WORKS[name]
        if name not in wanted:
            rows.update({k: v for k, v in old.items() if k.startswith(name + "/")})
            continue
        body, _, why = get(f"{REPO}/{bwb}/manifest.xml")
        if body is None:
            print(f"{name}: manifest not fetched: {why}")
            rows.update({k: v for k, v in old.items() if k.startswith(name + "/")})
            continue
        vs = versions(body.decode("utf-8", "replace"))
        got = 0
        for label, start, end, item in vs:
            rel = f"{name}/{label}_{bwb}.xml"
            url = f"{REPO}/{bwb}/{label}/xml/{item}"
            why = save(url, OUT / rel)
            if why:
                failed.append((f"{title} ({label})", start, url, why))
                continue
            got += 1
            until = "in force" if end.startswith("9999") else f"until {end}"
            rows[rel] = [rel, f"{title} (geldend van {start}, {'heden' if end.startswith('9999') else 'tot en met ' + end})",
                         start, url, kind, f"{title_en}; consolidated version in force from {start}, {until}",
                         f"BWB id {bwb}, version {label}; XML as published in the Basiswettenbestand"]
        print(f"{name}: {got} of {len(vs)} versions present")
    if "uwvwoo" not in wanted or not woo(rows, failed):
        rows.update({k: v for k, v in old.items() if k.startswith("uwvwoo/")})
    for rel in list(rows):
        if not (OUT / rel).exists():
            del rows[rel]
    write_tsv(idx, HEADER, [rows[k] for k in sorted(rows)])
    print(f"index.tsv: {len(rows)} rows")
    for f in failed:
        print("FAILED\t" + "\t".join(f))


if __name__ == "__main__":
    main()

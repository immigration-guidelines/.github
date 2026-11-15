#!/usr/bin/env python3
"""Estonia: the ministerial regulations that serve as the procedure manual for immigration cases.

    ./download_ee.py

Estonia publishes no case-officer guidance. The internal guidelines and the
Director General's directives of the Police and Border Guard Board (PPA) sit in the
PPA document register https://adr.politsei.ee/ppa/ , which forbids robots
(robots.txt "Disallow: /") and shows a bot check, so it is not touched; the same goes
for the Ministry of the Interior's register https://adr.siseministeerium.ee/ .
politsei.ee itself carries only applicant information.

What an official actually works from in public are the Minister of the Interior's
procedure regulations ("... kord") in Riigi Teataja. Only that small hand-picked set is
downloaded here, every row flagged "procedural act" in index.tsv - they are legal acts,
not guidance. Statutes and form/register regulations are left out on purpose.

Source: https://www.riigiteataja.ee/public-api/api/v1/akt/<id> (metadata) and
.../akt/<id>/pdf (the PDF rendering Riigi Teataja offers under "Laadi alla"). The PDF is
generated on request, so its bytes differ between downloads. robots.txt of
riigiteataja.ee is read first and every path is checked against it.

Existing files are skipped, so the script can be re-run. Standard library only.
"""
import datetime
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "ee"
UA = "immigration-guidelines-collector/1.0 (research archive)"
HOST = "https://www.riigiteataja.ee"
API = "/public-api/api/v1/akt/"
DELAY = 2.0

# (Riigi Teataja id, file slug, English gloss, note)
DOCS = [
    (104062026001, "international-and-temporary-protection-application-and-residence-permit-procedure",
     "Procedure for applying for international protection and temporary protection and for granting a residence permit under the Act on Granting International Protection to Aliens",
     "in force from 2026-06-12 (EU Pact); replaced the separate interview, refugee and temporary-protection regulations"),
    (110052016009, "international-protection-applicant-interview-procedure",
     "Procedure for conducting the interview with an applicant for international protection",
     "HISTORICAL: in force 2016-05-13 to 2026-06-11, repealed 2026-06-12"),
    (119052026006, "temporary-and-long-term-residence-permit-application-procedure-and-income-rates",
     "Procedure for applying for a temporary residence permit and its extension and for a long-term resident's permit and its restoration, and the rates of legal income",
     "version in force 2026-05-22 to 2026-12-31"),
    (125042025013, "eu-citizen-and-family-member-right-of-residence-procedure",
     "Procedure for applying for, granting, extending and terminating the right of residence of an EU citizen and family members", ""),
    (119052026005, "long-stay-visa-and-extension-of-stay-procedure",
     "Procedure and time limits for issuing a long-stay visa, formalising and extending the period of stay, and the rate of sufficient funds", ""),
    (109062026006, "visa-consultation-procedure-and-competent-authorities",
     "Procedure and time limits for giving consent in visa decisions, and the authorities competent for visa consultation and for processing VIS data", ""),
    (131072026008, "visa-and-period-of-stay-decision-appeal-procedure",
     "Procedure for contesting a visa decision or a period-of-stay decision", ""),
    (119052026008, "short-term-employment-registration-procedure",
     "Procedure for registering an alien's short-term employment in Estonia", ""),
    (107062022023, "enforcement-of-obligation-to-leave-procedure",
     "Procedure for organising the compulsory enforcement of the obligation to leave", ""),
    (118122015009, "ensuring-participation-in-proceedings-and-recoverable-costs",
     "Procedure for ensuring an alien's obligation to take part in proceedings, and the list and rates of costs recoverable from the person", ""),
    (109062026005, "detention-centre-internal-rules",
     "Internal rules of the detention centre", ""),
]

NOT_FETCHED = [
    ("PPA public document register: Director General's directives (peadirektori käskkirjad) and internal guidelines (juhendid, juhised) on residence permit, visa, return and international protection procedures",
     "robots.txt of adr.politsei.ee is 'Disallow: /' and the site shows a Cloudflare Turnstile robot check; not fetched. Titles can be browsed by a person; many documents are marked for internal use (AK).",
     "https://adr.politsei.ee/ppa/"),
    ("Ministry of the Interior document register (ministerial directives, correspondence with PPA)",
     "robots.txt of adr.siseministeerium.ee is 'Disallow: /'; not fetched",
     "https://adr.siseministeerium.ee/"),
    ("PPA Director General's directive 1.1-1/280 (2014) on the advisory expert committee for temporary residence permit applications, and similar directives",
     "only reachable through the PPA document register (robots: disallowed) or an unofficial third-party mirror (adr-docs.karlerss.com); not fetched",
     "https://adr.politsei.ee/ppa/"),
]


class Blocked(Exception):
    pass


_last = [0.0]


def get(url, binary=False):
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        _last[0] = time.time()
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} from {HOST}") from e
        raise
    _last[0] = time.time()
    return data if binary else data.decode("utf-8", "replace")


def robots_rules():
    """Disallow patterns for 'User-agent: *' as compiled regexes (the file uses * wildcards)."""
    rules, active = [], False
    for line in get(HOST + "/robots.txt").splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        key, val = (s.strip() for s in line.split(":", 1))
        if key.lower() == "user-agent":
            active = val == "*"
        elif key.lower() == "disallow" and active and val:
            rules.append(re.compile("^" + re.escape(val).replace(r"\*", ".*").replace(r"\$", "$")))
    return rules


def allowed(rules, path):
    return not any(r.search(path) for r in rules)


def main():
    OUT.mkdir(exist_ok=True)
    try:
        rules = robots_rules()
    except Exception as e:                                   # noqa: BLE001
        sys.exit(f"could not read robots.txt of riigiteataja.ee ({e}); nothing fetched")

    meta_path = OUT / ".meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    failed = []
    try:
        for rid, slug, gloss, note in DOCS:
            key = str(rid)
            m = meta.get(key)
            if m and (OUT / m["file"]).exists() and (OUT / m["file"]).stat().st_size > 0:
                continue
            page = f"{HOST}/akt/{rid}"
            mpath, ppath = f"{API}{rid}", f"{API}{rid}/pdf"
            if not (allowed(rules, mpath) and allowed(rules, ppath) and allowed(rules, f"/akt/{rid}/")):
                failed.append((gloss, "disallowed by robots.txt", page))
                continue
            try:
                info = json.loads(get(HOST + mpath))
                p = info["aktiParameetrid"]
                data = get(HOST + ppath, binary=True)
            except Blocked:
                raise
            except Exception as e:                           # noqa: BLE001 - report, no retry
                print(f"  FAILED {rid}: {e}")
                failed.append((gloss, f"download failed: {e}", page))
                continue
            if not data.startswith(b"%PDF"):
                print(f"  NOT A PDF, skipped: {rid}")
                failed.append((gloss, "server did not return a PDF", page))
                continue
            # the API gives validity start as the UTC instant of Estonian midnight (21:00Z or 22:00Z
            # the day before); adding 3 hours lands on the Estonian calendar day in both cases
            start = (datetime.datetime.strptime(p["kehtivuseAlgus"][:19], "%Y-%m-%dT%H:%M:%S")
                     + datetime.timedelta(hours=3)).strftime("%Y-%m-%d")
            name = f"{start}_{slug}.pdf"
            (OUT / name).write_bytes(data)
            meta[key] = {"file": name, "title": p["pealkiri"], "date": start, "status": info.get("aktiStaatus", ""),
                         "issuer_type": info.get("dokumentliik", "")}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  saved {name} ({len(data):,} bytes)")
    except Blocked as e:
        print(f"STOPPED: {e}. Host not used further in this run.")

    present = 0
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        for rid, slug, gloss, note in DOCS:
            m = meta.get(str(rid))
            if not m or not (OUT / m["file"]).exists():
                if not any(g == gloss for g, _, _ in failed):
                    failed.append((gloss, "not downloaded in this run", f"{HOST}/akt/{rid}"))
                continue
            present += 1
            full = "; ".join(x for x in (
                "Minister of the Interior regulation (siseministri määrus); date = start of validity of this consolidated version",
                note, f"PDF from {HOST}{API}{rid}/pdf") if x)
            f.write("\t".join([m["file"], m["title"], m["date"], f"{HOST}/akt/{rid}", "procedural act", gloss, full]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\treason\turl\n")
        for row in failed + NOT_FETCHED:
            f.write("\t".join(row) + "\n")
    print(f"ee: {present} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

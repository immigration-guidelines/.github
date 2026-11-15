#!/usr/bin/env python3
"""Poland: published instructions for officials handling foreigners' cases.

    ./download_pl.py            # default source: kgsg
    ./download_pl.py kgsg ia    # 'ia' is optional and not run by default

Poland publishes almost no case-officer guidance. The deciding bodies are the
voivodes (first instance: residence, work permits), the Head of the Office for
Foreigners (UdSC: appeals, international protection), the Border Guard (border
refusals, return, detention) and the labour ministry (work permits policy).

Sources
- kgsg: Official Journal of the Commander-in-Chief of the Border Guard,
  https://e-dziennik.strazgraniczna.pl (robots.txt: only /login disallowed).
  The whole journal 2012-2026 was listed (1,279 acts) and the few orders that
  instruct officers on how foreigners are handled were picked by hand. They are
  internal normative orders (zarzadzenia), so every row is kind "procedural act".
  The server sends an incomplete certificate chain (the Sectigo DV R36
  intermediate is missing); the intermediate is added below to the default trust
  store. Verification stays on.
- ia: optional, NOT run by default. One CDX query per host to the Internet
  Archive for PDFs on udsc.gov.pl and www.gov.pl/attachment whose original URL
  contains a guidance keyword; prints the candidates only (nothing is saved),
  4 s spacing, stops after three refusals. udsc.gov.pl and www.gov.pl did not
  answer (connection timeouts) on 2026-11-15, which is why this exists.

Not used: psz.praca.gov.pl (robots.txt: "User-agent: ClaudeBot / Disallow: /*"),
udsc.bip.gov.pl (Incapsula bot check, HTTP 403).

Existing files are skipped; index.tsv and not-obtained.tsv are rewritten.
Standard library only, sequential.
"""
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "pl"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 2.0
HOST_DELAY = {"web.archive.org": 4.0}
AI_AGENTS = ("claudebot", "claude-web", "anthropic-ai", "gptbot", "ccbot")

SECTIGO_DV_R36 = """-----BEGIN CERTIFICATE-----
MIIGTDCCBDSgAwIBAgIQOXpmzCdWNi4NqofKbqvjsTANBgkqhkiG9w0BAQwFADBf
MQswCQYDVQQGEwJHQjEYMBYGA1UEChMPU2VjdGlnbyBMaW1pdGVkMTYwNAYDVQQD
Ey1TZWN0aWdvIFB1YmxpYyBTZXJ2ZXIgQXV0aGVudGljYXRpb24gUm9vdCBSNDYw
HhcNMjEwMzIyMDAwMDAwWhcNMzYwMzIxMjM1OTU5WjBgMQswCQYDVQQGEwJHQjEY
MBYGA1UEChMPU2VjdGlnbyBMaW1pdGVkMTcwNQYDVQQDEy5TZWN0aWdvIFB1Ymxp
YyBTZXJ2ZXIgQXV0aGVudGljYXRpb24gQ0EgRFYgUjM2MIIBojANBgkqhkiG9w0B
AQEFAAOCAY8AMIIBigKCAYEAljZf2HIz7+SPUPQCQObZYcrxLTHYdf1ZtMRe7Yeq
RPSwygz16qJ9cAWtWNTcuICc++p8Dct7zNGxCpqmEtqifO7NvuB5dEVexXn9RFFH
12Hm+NtPRQgXIFjx6MSJcNWuVO3XGE57L1mHlcQYj+g4hny90aFh2SCZCDEVkAja
EMMfYPKuCjHuuF+bzHFb/9gV8P9+ekcHENF2nR1efGWSKwnfG5RawlkaQDpRtZTm
M64TIsv/r7cyFO4nSjs1jLdXYdz5q3a4L0NoabZfbdxVb+CUEHfB0bpulZQtH1Rv
38e/lIdP7OTTIlZh6OYL6NhxP8So0/sht/4J9mqIGxRFc0/pC8suja+wcIUna0HB
pXKfXTKpzgis+zmXDL06ASJf5E4A2/m+Hp6b84sfPAwQ766rI65mh50S0Di9E3Pn
2WcaJc+PILsBmYpgtmgWTR9eV9otfKRUBfzHUHcVgarub/XluEpRlTtZudU5xbFN
xx/DgMrXLUAPaI60fZ6wA+PTAgMBAAGjggGBMIIBfTAfBgNVHSMEGDAWgBRWc1hk
lfmSGrASKgRieaFAFYghSTAdBgNVHQ4EFgQUaMASFhgOr872h6YyV6NGUV3LBycw
DgYDVR0PAQH/BAQDAgGGMBIGA1UdEwEB/wQIMAYBAf8CAQAwHQYDVR0lBBYwFAYI
KwYBBQUHAwEGCCsGAQUFBwMCMBsGA1UdIAQUMBIwBgYEVR0gADAIBgZngQwBAgEw
VAYDVR0fBE0wSzBJoEegRYZDaHR0cDovL2NybC5zZWN0aWdvLmNvbS9TZWN0aWdv
UHVibGljU2VydmVyQXV0aGVudGljYXRpb25Sb290UjQ2LmNybDCBhAYIKwYBBQUH
AQEEeDB2ME8GCCsGAQUFBzAChkNodHRwOi8vY3J0LnNlY3RpZ28uY29tL1NlY3Rp
Z29QdWJsaWNTZXJ2ZXJBdXRoZW50aWNhdGlvblJvb3RSNDYucDdjMCMGCCsGAQUF
BzABhhdodHRwOi8vb2NzcC5zZWN0aWdvLmNvbTANBgkqhkiG9w0BAQwFAAOCAgEA
YtOC9Fy+TqECFw40IospI92kLGgoSZGPOSQXMBqmsGWZUQ7rux7cj1du6d9rD6C8
ze1B2eQjkrGkIL/OF1s7vSmgYVafsRoZd/IHUrkoQvX8FZwUsmPu7amgBfaY3g+d
q1x0jNGKb6I6Bzdl6LgMD9qxp+3i7GQOnd9J8LFSietY6Z4jUBzVoOoz8iAU84OF
h2HhAuiPw1ai0VnY38RTI+8kepGWVfGxfBWzwH9uIjeooIeaosVFvE8cmYUB4TSH
5dUyD0jHct2+8ceKEtIoFU/FfHq/mDaVnvcDCZXtIgitdMFQdMZaVehmObyhRdDD
4NQCs0gaI9AAgFj4L9QtkARzhQLNyRf87Kln+YU0lgCGr9HLg3rGO8q+Y4ppLsOd
unQZ6ZxPNGIfOApbPVf5hCe58EZwiWdHIMn9lPP6+F404y8NNugbQixBber+x536
WrZhFZLjEkhp7fFXf9r32rNPfb74X/U90Bdy4lzp3+X1ukh1BuMxA/EEhDoTOS3l
7ABvc7BYSQubQ2490OcdkIzUh3ZwDrakMVrbaTxUM2p24N6dB+ns2zptWCva6jzW
r8IWKIMxzxLPv5Kt3ePKcUdvkBU/smqujSczTzzSjIoR5QqQA6lN1ZRSnuHIWCvh
JEltkYnTAH41QJ6SAWO66GrrUESwN/cgZzL4JLEqz1Y=
-----END CERTIFICATE-----"""

KGSG = "https://e-dziennik.strazgraniczna.pl"
PUB = "KOMENDA_GLOWNA_STRAZY_GRANICZNEJ"

# (year, position, file slug, English gloss, note)
DOCS = [
    (2016, 81, "zarzadzenie-84-KGSG_doprowadzenia-cudzoziemcow",
     "Order No 84 of the Commander-in-Chief of the Border Guard of 29 July 2016 on how Border Guard officers perform service when escorting foreigners (doprowadzenia: removal escorts, escorts to guarded centres, courts, consulates)",
     "amended by Order No 4 of 22 Feb 2023 (Dz. Urz. KGSG 2023.2, separate file)"),
    (2023, 2, "zarzadzenie-4-KGSG_zmiana-doprowadzenia-cudzoziemcow",
     "Order No 4 of the Commander-in-Chief of the Border Guard of 22 February 2023 amending the order on escorting foreigners",
     "amends Dz. Urz. KGSG 2016.81"),
    (2024, 15, "zarzadzenie-16-KGSG_sluzba-w-strzezonym-osrodku-i-areszcie-dla-cudzoziemcow",
     "Order No 16 of the Commander-in-Chief of the Border Guard of 21 March 2024 on service of Border Guard officers in guarded centres and detention facilities for foreigners (admission, deposit, supervision, coercive measures, release)",
     "replaced the 2012 rules (regulamin) for service in guarded centres, repealed by Dz. Urz. KGSG 2024.16"),
    (2023, 28, "zarzadzenie-35-KGSG_wpisy-do-SIS",
     "Order No 35 of the Commander-in-Chief of the Border Guard of 28 June 2023 on making entries in the Schengen Information System (including refusal-of-entry and return alerts on third-country nationals)",
     ""),
]

NOT_OBTAINED = [
    ("Pisma i wytyczne Szefa Urzędu do Spraw Cudzoziemców do wojewodów / dyrektorów wydziałów spraw cudzoziemców (letters and guidelines of the Head of the Office for Foreigners to the voivodes' foreigners departments on residence and work-permit cases)", "",
     "https://www.gov.pl/web/udsc",
     "not published: the Ministry of the Interior told the Ombudsman (14 Nov 2024, https://bip.brpo.gov.pl/sites/default/files/2024-11/Odpowiedz_MSWiA_cudzoziemcy_legalizacja_pobytu_przewleklosc_mswia_14_11_2024.pdf) that the Head of UdSC repeatedly writes to the directors of the voivodes' foreigners departments; no such letter or guideline is posted. Obtainable only by a request under the Act on access to public information (2001)"),
    ("Wewnętrzne procedury i instrukcje Departamentu Postępowań Uchodźczych UdSC (internal procedures for international protection interviews and decisions)", "",
     "https://www.gov.pl/web/udsc",
     "not published; in addition www.gov.pl and udsc.gov.pl did not answer from this machine on 2026-11-15 (three connection timeouts each on robots.txt), so the UdSC pages could not be checked directly"),
    ("UdSC Biuletyn Informacji Publicznej (internal acts, answers to information requests)", "",
     "https://udsc.bip.gov.pl/",
     "refused: robots.txt request answered with an Incapsula bot check (HTTP 403); host not used further"),
    ("Wyjaśnienia Ministerstwa Rodziny, Pracy i Polityki Społecznej do ustawy z 20 marca 2025 r. o warunkach dopuszczalności powierzania pracy cudzoziemcom (ministry explanations of the 2025 act for voivodes and district labour offices)", "2025",
     "https://psz.praca.gov.pl/",
     "robots: psz.praca.gov.pl disallows ClaudeBot entirely (treated as applying to this collector); the ministry's own pages are on www.gov.pl/web/rodzina, which did not answer (connection timeouts). Not fetched"),
    ("Wewnętrzne zarządzenia i decyzje Komendanta Głównego Straży Granicznej o metodach i formach wykonywania zadań wobec cudzoziemców (return, Dublin transfers, border procedure, identification of vulnerable persons)", "",
     "https://e-dziennik.strazgraniczna.pl/",
     "not published: the Border Guard's official journal (all 1,279 acts of 2012-2026 listed) carries only organisational orders and the four orders saved here; operational instructions are not in it"),
]


class Blocked(Exception):
    pass


_last, _closed, _bad, _robots = {}, {}, {}, {}
_ctx = ssl.create_default_context()
_ctx.load_verify_locations(cadata=SECTIGO_DV_R36)


def _raw(url, timeout=120):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Blocked(f"{host}: {_closed[host]}")
    gap = HOST_DELAY.get(host, DELAY)
    t = _last.get(host)
    if t is not None and time.time() - t < gap:
        time.sleep(gap - (time.time() - t))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
            body = r.read()
        _bad[host] = 0
        return body
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            if host == "web.archive.org":
                _bad[host] = _bad.get(host, 0) + 1
                if _bad[host] >= 3:
                    _closed[host] = "three refusals in a row"
            else:
                _closed[host] = f"HTTP {e.code}"
        raise
    except Exception:
        _bad[host] = _bad.get(host, 0) + 1
        if _bad[host] >= 3:
            _closed[host] = "three connection failures in a row"
        raise
    finally:
        _last[host] = time.time()


def _match(pattern, path):
    rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
    return re.match(rx + ("$" if pattern.endswith("$") else ""), path) is not None


def robots_ok(url):
    """robots.txt first; rules for '*' and for named AI agents both apply; wildcards handled."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc
    if host not in _robots:
        try:
            text = _raw(f"{p.scheme}://{host}/robots.txt", timeout=60).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                text = ""
            else:
                _closed.setdefault(host, f"robots.txt HTTP {e.code}")
                raise Blocked(f"{host}: robots.txt HTTP {e.code}")
        rules, agents, in_rules = [], [], False
        for line in text.splitlines():
            line = line.split("#")[0].strip()
            if ":" not in line:
                continue
            k, v = (s.strip() for s in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if in_rules:
                    agents, in_rules = [], False
                agents.append(v.lower())
            elif k in ("allow", "disallow"):
                in_rules = True
                if any(a == "*" or a in AI_AGENTS for a in agents) and v:
                    rules.append((k == "allow", v))
            elif k == "crawl-delay" and any(a == "*" or a in AI_AGENTS for a in agents):
                try:
                    HOST_DELAY[host] = max(HOST_DELAY.get(host, DELAY), float(v))
                except ValueError:
                    pass
        _robots[host] = rules
    path = p.path + ("?" + p.query if p.query else "")
    best = None
    for allow, pat in _robots[host]:
        if _match(pat, path) and (best is None or len(pat) > len(best[1]) or (len(pat) == len(best[1]) and allow)):
            best = (allow, pat)
    return best is None or best[0]


def get(url, timeout=120):
    if not robots_ok(url):
        raise Blocked(f"disallowed by robots.txt: {url}")
    return _raw(url, timeout)


def run_kgsg(meta, failed):
    for year, pos, slug, gloss, note in DOCS:
        key = f"{year}/{pos}"
        m = meta.get(key)
        if m and (OUT / m["file"]).exists() and (OUT / m["file"]).stat().st_size > 0:
            continue
        api = f"{KGSG}/api/eli/acts/{PUB}/{year}/{pos}"
        try:
            info = json.loads(get(api))
            data = get(api + "/text.pdf")
        except Blocked as e:
            print(f"STOPPED: {e}")
            failed.append((gloss, "", f"{KGSG}/DUKGSG/{year}/{pos}", f"not fetched: {e}"))
            return
        except Exception as e:                                  # noqa: BLE001 - no retry
            print(f"  FAILED {key}: {e}")
            failed.append((gloss, "", f"{KGSG}/", f"download failed: {e}"))
            continue
        if not data.startswith(b"%PDF"):
            failed.append((gloss, "", api + "/text.pdf", "server did not return a PDF"))
            continue
        m_date = re.search(r"z dnia (\d{1,2}) (\w+) (\d{4})", info["title"])
        months = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia",
                  "września", "października", "listopada", "grudnia"]
        date = f"{m_date.group(3)}-{months.index(m_date.group(2)) + 1:02d}-{int(m_date.group(1)):02d}"
        name = f"{date}_DzUrzKGSG-{year}-{pos}_{slug}.pdf"
        (OUT / name).write_bytes(data)
        meta[key] = {"file": name, "title": re.sub(r"\s+", " ", info["title"]).strip(), "date": date,
                     "status": info.get("status", ""), "display": info.get("displayAddress", "")}
        (OUT / ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  saved {name} ({len(data):,} bytes)")


def run_ia():
    """Print archived candidates only; nothing is saved."""
    pat = re.compile(r"wytyczn|instrukcj|metodyk|wyjasnien|wyja%C5%9Bnien|podrecznik|procedur", re.I)
    for prefix in ("udsc.gov.pl/", "www.gov.pl/attachment/"):
        q = ("https://web.archive.org/cdx/search/cdx?url=" + urllib.parse.quote(prefix) +
             "&matchType=prefix&filter=mimetype:application/pdf&collapse=urlkey&fl=timestamp,original&limit=5000")
        try:
            rows = get(q, timeout=180).decode("utf-8", "replace").splitlines()
        except Exception as e:                                  # noqa: BLE001
            print(f"ia: {prefix}: {e}")
            continue
        for r in rows:
            if pat.search(r):
                print("ia candidate:", r)


def main():
    OUT.mkdir(exist_ok=True)
    sources = sys.argv[1:] or ["kgsg"]
    meta_path = OUT / ".meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    failed = []
    if "kgsg" in sources:
        run_kgsg(meta, failed)
    if "ia" in sources:
        run_ia()
    present = 0
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        for year, pos, slug, gloss, note in DOCS:
            m = meta.get(f"{year}/{pos}")
            if not m or not (OUT / m["file"]).exists():
                if not any(r[0] == gloss for r in failed):
                    failed.append((gloss, "", f"{KGSG}/", "not downloaded in this run"))
                continue
            present += 1
            full = "; ".join(x for x in (
                f"internal order of the Commander-in-Chief of the Border Guard published in its official journal ({m['display']}, status: {m['status']}); date = date of the order",
                note, f"PDF from {KGSG}/api/eli/acts/{PUB}/{year}/{pos}/text.pdf") if x)
            f.write("\t".join([m["file"], m["title"], m["date"], f"{KGSG}/api/eli/acts/{PUB}/{year}/{pos}/text.pdf",
                               "procedural act", gloss, full]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for row in failed + NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    print(f"pl: {present} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

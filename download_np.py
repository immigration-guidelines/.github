#!/usr/bin/env python3
"""Nepal: the Department of Immigration's published procedures (कार्यविधि) and directives (निर्देशिका),
and the Immigration Rules that are in practice the working rules for visas.

    python3 download_np.py

Source:
  doi  Department of Immigration, immigration.gov.np: the "निर्देशिका" (/directive), "कार्यविधी"
       (/procedures) and "नियमावली" (/rule) lists. Kept: the Immigration Procedure 2065, the Foreign
       Nationals Monitoring Directive 2075, the staff Code of Conduct, the China border-pass procedure
       2081 (guidance) and the Immigration Rules 2051 (procedural act). Left out: the Acts, the
       Non-Resident Nepali Rules and the visa-fee gazette notice.

The site does not send its intermediate certificate. As a browser does, the script reads the
"CA Issuers" address in the server certificate, fetches that intermediate and adds it to the default
trust store; the chain is still verified to a root this machine trusts, verification is never off.
robots.txt is read first ("Disallow:" empty). Sequential, 1.6 s between requests; existing files are
skipped; np/index.tsv and np/not-obtained.tsv are rewritten. Python standard library only.
"""
import gzip
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "np"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE, PAUSE_IA = 1.6, 4.0
HEAD = ["file", "title", "date", "source_url", "kind", "title_en", "source", "note"]
HOST = "immigration.gov.np"


def _context():
    ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://{HOST}/robots.txt", headers={"User-Agent": UA}),
                               timeout=60, context=ctx).close()
        return ctx
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
    time.sleep(1.6)
    leaf = ssl.PEM_cert_to_DER_cert(ssl.get_server_certificate((HOST, 443)))
    m = re.search(rb"http://[\x21-\x7e]+?\.(?:crt|cer)", leaf)
    if not m:
        sys.exit(f"{HOST}: certificate chain incomplete and no CA Issuers address found")
    issuer = urllib.request.urlopen(m.group().decode(), timeout=60).read()
    if not issuer.startswith(b"-----BEGIN"):
        issuer = ssl.DER_cert_to_PEM_cert(issuer).encode()
    ctx.load_verify_locations(cadata=issuer.decode())
    return ctx


CONTEXT = {HOST: _context()}
F = f"https://{HOST}/doi-notice-file/"
SOURCES = {"doi": "immigration.gov.np ऐन, नियम, कानून"}
G, P = "guidance", "procedural act"
ITEMS = [
    ("doi", "doi/2008_अध्यागमन-कार्यविधि-२०६५.pdf", F + "Notices-202605082117037656.pdf",
     "अध्यागमन कार्यविधि - २०६५", "2008", G, "Immigration Procedure 2065 (2008)",
     "the Department's working procedure for visas, entry and exit; BS 2065 = 2008/09; listing page https://immigration.gov.np/detail/148"),
    ("doi", "doi/2018_विदेशी-नागरिक-अनुगमन-निर्देशिका-२०७५.pdf", F + "Notices-202605082113547741.pdf",
     "विदेशी नागरिक अनुगमन निर्देशिका, २०७५", "2018", G, "Foreign Nationals Monitoring Directive 2075 (2018)",
     "BS 2075 = 2018/19; listing page https://immigration.gov.np/detail/142"),
    ("doi", "doi/2023_अध्यागमनका-कर्मचारीहरुको-आचारसंहिता.pdf", F + "Notices-202605082115423970.pdf",
     "अध्यागमनका कर्मचारीहरुको आचारसंहिता", "2023", G, "Code of conduct for immigration staff",
     "undated; year from the PDF (created Aug 2023); listing page https://immigration.gov.np/detail/145"),
    ("doi", "doi/2024_चीन-आवागमन-अनुमतिपत्र-प्रवेश-पास-कार्यविधि-२०८१.pdf", F + "Notices-202605082040299909.pdf",
     "चीनसँग सीमा जोडिएका जिल्लाका नेपाली नागरिकहरुलाई चीन आवागमन (Entry/Exit) अनुमतिपत्र (प्रवेश पास) उपलब्ध गराउने सम्बन्धी कार्यविधि, २०८१",
     "2024", G, "Procedure 2081 (2024) for issuing China entry/exit passes to Nepali citizens of districts bordering China",
     "BS 2081 = 2024/25; listing page https://immigration.gov.np/detail/76"),
    ("doi", "doi/1994_अध्यागमन-नियमावली-२०५१.pdf", F + "Notices-202605082109391297.pdf",
     "अध्यागमन नियमावली-२०५१", "1994", P, "Immigration Rules 2051 (1994), as amended",
     "regulation under the Immigration Act 2049: visa categories, conditions and fees in detail; listing page https://immigration.gov.np/detail/136"),
]
NOT_OBTAINED = []
class Refused(Exception):
    pass


_last, _fails, _closed, _robots = {}, {}, set(), {}


def _raw(url, timeout=180):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Refused(f"{host}: closed earlier in this run")
    wait = (PAUSE_IA if host.endswith("archive.org") else PAUSE) - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, None, {"User-Agent": UA}), timeout=timeout,
                                    context=CONTEXT.get(host)) as r:
            data = r.read()
        if data[:2] == b"\x1f\x8b":                  # some servers gzip whatever the request says
            data = gzip.decompress(data)
        _fails[host] = 0
        return data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            _closed.add(host)
            raise Refused(f"{host}: HTTP {e.code}") from None
        raise
    except (urllib.error.URLError, OSError) as e:
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] >= 3:
            _closed.add(host)
            raise Refused(f"{host}: three connection failures in a row ({e})") from None
        raise
    finally:
        _last[host] = time.time()


def _rules(host, scheme):
    if host not in _robots:
        try:
            txt = _raw(f"{scheme}://{host}/robots.txt", 60).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                _closed.add(host)
                raise Refused(f"{host}: robots.txt answered HTTP {e.code}") from None
            txt = ""
        if txt.lstrip()[:1] == "<":
            txt = ""
        rules, groups, fresh = [], [], True
        for line in txt.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (s.strip() for s in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if fresh and groups:
                    groups[-1][0].append(v.lower())
                else:
                    groups.append(([v.lower()], []))
                fresh = True
            elif k in ("allow", "disallow"):
                fresh = False
                if groups and v:
                    groups[-1][1].append((k, v))
        for ags, rs in groups:
            if any(a in ("*", "claudebot", "anthropic-ai", "claude-web", "gptbot", "ccbot") for a in ags):
                rules += rs
        _robots[host] = rules
    return _robots[host]


def allowed(url):
    u = urllib.parse.urlsplit(url)
    path = u.path + ("?" + u.query if u.query else "")
    best, verdict = -1, True
    for kind, pat in _rules(u.netloc, u.scheme):
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pat.rstrip("$")) + ("$" if pat.endswith("$") else "")
        if re.match(rx, path) and (len(pat) > best or (len(pat) == best and kind == "allow")):
            best, verdict = len(pat), kind == "allow"
    return verdict


def get(url):
    if not allowed(url):
        raise Refused(f"robots.txt disallows {url}")
    data = _raw(url)
    if re.search(rb"Just a moment|cf-challenge|captcha", data[:4000], re.I) and data[:5] != b"%PDF-":
        _closed.add(urllib.parse.urlsplit(url).netloc)
        raise Refused(f"bot check at {url}")
    return data


def bad(data, name):
    if len(data) < 300:
        return "too small"
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "pdf" and data[:5] != b"%PDF-":
        return "not a PDF"
    if ext == "docx" and data[:2] != b"PK":
        return "not a Word file"
    return None


def fetch(rel, url, missing, title, date):
    dest = OUT / rel
    if dest.exists() and dest.stat().st_size:
        return True
    try:
        data = get(url)
    except Refused:
        raise
    except Exception as e:                                # noqa: BLE001
        missing.append((title, date, url, f"download failed: {e}"))
        print(f"  FAILED {rel}: {e}")
        return False
    why = bad(data, rel)
    if why:
        missing.append((title, date, url, f"server returned {why}"))
        print(f"  REJECTED {rel}: {why}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_name(dest.name + ".part").write_bytes(data)
    dest.with_name(dest.name + ".part").replace(dest)
    print(f"  saved {rel} ({len(data):,} bytes)")
    return True


def tsv(path, head, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(head) + "\n")
        for r in rows:
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in r) + "\n")



def main():
    names = list(SOURCES)
    which = [a for a in sys.argv[1:] if a in names] or names
    OUT.mkdir(exist_ok=True)
    missing, stopped = list(NOT_OBTAINED), set()
    for src, rel, url, title, date, kind, en, note in ITEMS:
        if src in which and src not in stopped:
            try:
                fetch(rel, url, missing, title, date)
            except Refused as e:
                print(f"STOPPED {src}: {e}")
                missing.append((title, date, url, f"{e}; host not used further"))
                stopped.add(src)
        elif src in stopped and not (OUT / rel).exists():
            missing.append((title, date, url, "not attempted: host closed earlier in the run"))
    rows = [[rel, title, date, url, kind, en, SOURCES[src], note]
            for src, rel, url, title, date, kind, en, note in ITEMS if (OUT / rel).exists()]
    tsv(OUT / "index.tsv", HEAD, rows)
    tsv(OUT / "not-obtained.tsv", ["title", "date", "url", "reason"], missing)
    print(f"{len(rows)} rows in index.tsv; {len(missing)} entries in not-obtained.tsv")


if __name__ == "__main__":
    main()

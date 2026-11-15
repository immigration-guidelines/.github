#!/usr/bin/env python3
"""Download German FEDERAL guidance to immigration decision-makers that download_de.py does not cover.

    python3 download_de_federal.py              everything
    python3 download_de_federal.py ba bamf      only the named sources (ba, bamf, bmi, aa, bva)
    python3 download_de_federal.py --skip=web.archive.org,fragdenstaat.de   leave these hosts alone in this run

Sources (one subfolder of de/ each):
    ba    Bundesagentur fuer Arbeit: "Fachliche Weisungen zum Aufenthaltsgesetz und zur
          Beschaeftigungsverordnung" (current file from arbeitsagentur.de, earlier versions from the
          Internet Archive and asyl.net), "Fachliche Weisungen Werkvertragsverfahren", and the numbered
          "Weisungen" on labour-market admission of foreigners, read from the yearly lists on
          arbeitsagentur.de/ueber-uns/veroeffentlichungen/weisungen... on every run.
    bamf  BAMF service instructions (DA-Asyl, DA-Dublin, DA-AVS). BAMF does not publish them; the copies
          are the ones it released under the freedom-of-information act, as hosted by Pro Asyl and asyl.net.
    bmi   BMI Anwendungshinweise, Laenderschreiben and Aufnahmeanordnungen that are not in de/bund/,
          including earlier dated versions (Internet Archive copies of bmi.bund.de, and asyl.net).
    aa    Auswaertiges Amt: instructions to missions other than the Visumhandbuch.
    bva   Bundesverwaltungsamt (Internet Archive copies of bva.bund.de).

Rules the script keeps:
  * robots.txt of every host is read first and obeyed; a host whose robots.txt cannot be read is not used.
  * one request at a time, a pause between requests per host (see PAUSE / SLOW);
  * a 403 or 429 answer stops that host for the rest of the run; so do three dropped connections in a row;
  * files that already exist are skipped, so the script can be re-run; nothing is overwritten;
  * an archive capture whose bytes equal a file already in the folder or in de/bund/ is not kept; its name is
    remembered in <folder>/.duplicates.tsv so that it is not fetched again.
The script does not notice a document replaced under the same file name: delete the file and re-run.
The one exception is the current Fachliche Weisungen AufenthG/BeschV, whose size is compared (see ba()).

Output: de/<source>/..., de/federal-index.tsv (file, body, title, date, source_url) and
de/federal-not-obtained.tsv (body, title, url, reason). Rows of sources not named on the command line
are kept as they are. Standard library only.
"""
import gzip
import hashlib
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "de"
INDEX = ROOT / "federal-index.tsv"
MISSING = ROOT / "federal-not-obtained.tsv"
UA = "immigration-guidelines-collector/1.0 (public guidance archive; python-urllib)"
PAUSE = 1.5                                   # seconds between requests to one host
SLOW = {"web.archive.org": 5.0, "www.proasyl.de": 3.0, "www.bmi.bund.de": 4.0}
MAX_FILES, MAX_BYTES = 2000, 1_000_000_000
WB = "https://web.archive.org/web/"           # + <timestamp>id_/<original url> = the capture's original bytes

OPENER = urllib.request.build_opener()
OPENER.addheaders = [("User-Agent", UA), ("Accept-Encoding", "identity")]
BLOCKED = {}                                  # host -> reason
RESETS = {}                                   # host -> consecutive connection failures
ROBOTS = {}                                   # host -> RobotFileParser
LAST = {}                                     # host -> time of last request
STATS = {"new": 0, "bytes": 0}


def log(*a):
    print(*a, flush=True)


def quote(url):
    return urllib.parse.quote(url, safe="/:?&=%#;,+@~!$'()*[]")


def _open(url, host):
    wait = SLOW.get(host, PAUSE) - (time.time() - LAST.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    LAST[host] = time.time()
    try:
        with OPENER.open(urllib.request.Request(quote(url)), timeout=180) as r:
            data = r.read()
            total = r.headers.get("Content-Length")
            if total and total.isdigit() and len(data) < int(total):
                raise ConnectionError("short read")
        RESETS[host] = 0
        return data, None
    except urllib.error.HTTPError as e:
        RESETS[host] = 0
        if e.code in (403, 429):
            BLOCKED[host] = f"HTTP {e.code}"
            log(f"  !! {host} answered {e.code}: not used again in this run")
        return None, f"HTTP {e.code}"
    except Exception as e:                    # connection refused / reset / timeout
        RESETS[host] = RESETS.get(host, 0) + 1
        if RESETS[host] >= 3:
            BLOCKED[host] = "three connection failures in a row"
            log(f"  !! {host}: three connection failures in a row, not used again in this run")
        return None, f"connection: {e}"


def allowed(url):
    """robots.txt check; reads the host's robots.txt on first use."""
    host = urllib.parse.urlsplit(url).netloc
    if host in BLOCKED:
        return False
    if host not in ROBOTS:
        rp = urllib.robotparser.RobotFileParser()
        data, err = _open(f"https://{host}/robots.txt", host)
        if data is None and err and RESETS.get(host):          # one more try after a dropped connection
            time.sleep(20)
            data, err = _open(f"https://{host}/robots.txt", host)
        if data is not None:
            rp.parse(data.decode("utf-8", "replace").splitlines())
        elif err == "HTTP 404":
            rp.parse([])                                       # no robots.txt: nothing is disallowed
        else:
            BLOCKED.setdefault(host, f"robots.txt unreadable ({err})")
            log(f"  !! {host}: robots.txt unreadable ({err}), host not used")
            return False
        ROBOTS[host] = rp
    return ROBOTS[host].can_fetch(UA, url)


def get(url):
    """Return (bytes, None) or (None, reason). Never retries a 403/429."""
    host = urllib.parse.urlsplit(url).netloc
    if not allowed(url):
        return None, BLOCKED.get(host, "disallowed by robots.txt")
    data, err = _open(url, host)
    if data is None and err.startswith("connection") and host not in BLOCKED:
        time.sleep(20)
        data, err = _open(url, host)
    return data, err


def page(url):
    data, err = get(url)
    return (data.decode("utf-8", "replace") if data else ""), err


def links(markup):
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', markup, re.S):
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        yield html.unescape(m.group(1)), text


def slug(text, n=90):
    for a, b in (("§", "Par"), ("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return re.sub(r"[^A-Za-z0-9.]+", "-", text).strip("-.")[:n].rstrip("-.")


def good(data, ext):
    """Reject error pages, bot-check pages and truncated transfers."""
    if ext == ".pdf":
        return data[:5] == b"%PDF-" and b"%%EOF" in data[-2048:]
    if ext == ".html":
        return b"<html" in data[:2000].lower() and len(data) > 2000
    return len(data) > 500


class Source:
    def __init__(self, code, body):
        self.code, self.body = code, body
        self.dir = ROOT / code
        self.rows, self.missing = [], []
        old = {}
        if INDEX.exists():
            for line in INDEX.read_text(encoding="utf-8").splitlines()[1:]:
                f = line.split("\t")
                if len(f) == 5:
                    old[f[0]] = f
        self.old = old
        # captures that turned out byte-identical to a file already held: remembered so they are not fetched again
        self.dupfile = self.dir / ".duplicates.tsv"
        self.dups = dict(l.split("\t", 1) for l in self.dupfile.read_text(encoding="utf-8").splitlines() if "\t" in l) \
            if self.dupfile.exists() else {}
        self.hashes = None

    def known(self, data):
        """Name of an already held file (this folder or de/bund/) with the same content, or None."""
        if self.hashes is None:
            self.hashes = {}
            for d in (ROOT / "bund", self.dir):
                for f in (sorted(d.iterdir()) if d.exists() else []):
                    if f.is_file() and not f.name.startswith("."):
                        self.hashes.setdefault(hashlib.sha1(f.read_bytes()).hexdigest(), f"{d.name}/{f.name}")
        return self.hashes.get(hashlib.sha1(data).hexdigest())

    def save(self, name, title, date, urls, body=None):
        """Fetch the first of `urls` that yields a valid file; skip if the file exists."""
        rel = f"{self.code}/{name}"
        path = self.dir / name
        ext = path.suffix.lower()
        if path.exists() and path.stat().st_size:
            src = self.old.get(rel, [0, 0, 0, 0, urls[0]])[4]
            self.rows.append((rel, body or self.body, title, date, src))
            return True
        if name in self.dups:
            return True
        reason = "no source"
        for url in urls:
            if STATS["new"] >= MAX_FILES or STATS["bytes"] >= MAX_BYTES:
                reason = "size/file cap of the run reached"
                break
            data, err = get(url)
            if data is None:
                reason = err
                continue
            if data[:2] == b"\x1f\x8b":       # archive capture stored with gzip transfer encoding
                try:
                    data = gzip.decompress(data)
                except Exception:
                    reason = "truncated gzip capture"
                    continue
            if not good(data, ext):
                reason = "not a complete %s (error page or truncated capture)" % ext.lstrip(".")
                continue
            self.dir.mkdir(parents=True, exist_ok=True)
            same = self.known(data)
            if same:
                log(f"  = {rel} is identical to {same}: not kept")
                self.dups[name] = same
                self.dupfile.write_text("".join(f"{k}\t{v}\n" for k, v in sorted(self.dups.items())), encoding="utf-8")
                return True
            self.hashes[hashlib.sha1(data).hexdigest()] = rel
            tmp = path.with_suffix(path.suffix + ".part")
            tmp.write_bytes(data)
            tmp.rename(path)
            STATS["new"] += 1
            STATS["bytes"] += len(data)
            log(f"  + {rel}  ({len(data) / 1e6:.2f} MB)")
            self.rows.append((rel, body or self.body, title, date, url))
            return True
        log(f"  - not obtained: {title}  [{reason}]")
        self.missing.append((body or self.body, title, urls[0], reason))
        return False

    def note(self, title, url, reason, body=None):
        self.missing.append((body or self.body, title, url, reason))

    def finish(self):
        files = [f for f in self.dir.iterdir() if f.is_file() and not f.name.startswith(".")] if self.dir.exists() else []
        log(f"{self.code}: {len(self.rows)} documents indexed, folder holds {len(files)} files, "
            f"{sum(f.stat().st_size for f in files) / 1e6:.1f} MB; {len(self.missing)} not obtained")


def write_tables(done):
    """Rewrite both tables, replacing only the rows of the sources that were run."""
    codes = {s.code for s in done}
    bodies = {b for s in done for b in ([s.body] + [m[0] for m in s.missing] + [r[1] for r in s.rows])}
    rows = []
    if INDEX.exists():
        for line in INDEX.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if len(f) == 5 and f[0].split("/")[0] not in codes:
                rows.append(tuple(f))
    for s in done:
        rows += s.rows
    rows = sorted(set(rows))
    INDEX.write_text("file\tbody\ttitle\tdate\tsource_url\n" +
                     "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    miss = []
    if MISSING.exists():
        for line in MISSING.read_text(encoding="utf-8").splitlines()[1:]:
            f = line.split("\t")
            if len(f) == 4 and f[0] not in bodies:
                miss.append(tuple(f))
    for s in done:
        miss += s.missing
    MISSING.write_text("body\ttitle\turl\treason\n" +
                       "".join("\t".join(r) + "\n" for r in sorted(set(miss))), encoding="utf-8")
    log(f"{INDEX.name}: {len(rows)} rows; {MISSING.name}: {len(set(miss))} rows")


# --- Bundesagentur fuer Arbeit ------------------------------------------------------------------------

BA = "https://www.arbeitsagentur.de/"
BA_PUB = BA + "ueber-uns/veroeffentlichungen/"
BA_LISTS = ["weisungen"] + [f"weisungen-{y}" for y in range(2025, 2015, -1)] + ["weisungen-ab-2015"]
# Titles of numbered Weisungen that concern residence status / labour-market admission of foreigners.
BA_KEEP = re.compile(
    r"Aufenthaltsgesetz|AufenthG|Beschäftigungsverordnung|BeschV\b|Arbeitsmark[t]?zulassung|Arbeitserlaubnis|"
    r"Werkvertragsverfahren|Aufenthaltsstatus|Aufenthaltsrechtlich|Aufenthaltstitel|Zuwanderungsgesetz|\bAMZ\b|"
    r"Asylbewerber|Vorrangprüfung|Saisonhilfskräfte|Austritts? des Vereinigten Königreichs|Fachkräfteeinwanderung")
BA_FW = "Fachliche-Weisungen-AufenthG-BeschV"
BA_FW_URL = BA + "datei/dok_ba033210.pdf"
BA_FW_KNOWN = {1728783: "2024-12-01"}         # size of the live file -> Stand (version date in its change history)
# Earlier versions of the Fachliche Weisungen: (Stand, [sources])
BA_FW_OLD = [
    ("2020-03-01", ["https://www.asyl.net/fileadmin/user_upload/dokumente/28702w.pdf"]),
    ("2020-08-01", [WB + "20201001020402id_/https://www.arbeitsagentur.de/datei/dok_ba146473.pdf",
                    WB + "20210126190827id_/https://www.arbeitsagentur.de/datei/dok_ba146473.pdf"]),
    ("2021-06-01", [WB + "20231025073152id_/https://www.arbeitsagentur.de/datei/dok_ba033210.pdf"]),
    ("2023-11-01", [WB + "20240225204112id_/https://www.arbeitsagentur.de/datei/dok_ba146473.pdf",
                    WB + "20231129095020id_/https://www.arbeitsagentur.de/datei/dok_ba033210.pdf"]),
    ("2024-06-01", [WB + "20240609180801id_/https://www.arbeitsagentur.de/datei/dok_ba033210.pdf"]),
]


def de_date(text):
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def ba_clean(text):
    text = re.sub(r"^Öffnet in neuem Tab\s*", "", text)
    return re.sub(r"\s*pdf \| [\d.,]+ [KM]B \|.*$", "", text).strip()


def ba():
    s = Source("ba", "Bundesagentur für Arbeit")
    title = "Fachliche Weisungen zum Aufenthaltsgesetz und zur Beschäftigungsverordnung"
    # current version: named by its Stand if the live file is the one this script knows, otherwise by today's date
    have = {f.stat().st_size for f in s.dir.glob(f"*_{BA_FW}*.pdf")} if s.dir.exists() else set()
    size = None
    if allowed(BA_FW_URL):
        host = urllib.parse.urlsplit(BA_FW_URL).netloc
        wait = PAUSE - (time.time() - LAST.get(host, 0))
        time.sleep(max(wait, 0))
        LAST[host] = time.time()
        try:
            with OPENER.open(urllib.request.Request(BA_FW_URL, method="HEAD"), timeout=60) as r:
                size = int(r.headers.get("Content-Length") or 0) or None
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                BLOCKED[host] = f"HTTP {e.code}"
        except Exception:
            pass
    if size in BA_FW_KNOWN or size is None:
        stand = BA_FW_KNOWN.get(size, max(BA_FW_KNOWN.values()))
        s.save(f"{stand}_{BA_FW}_Stand-{stand[5:7]}-{stand[:4]}.pdf", f"{title} (Stand {stand[5:7]}/{stand[:4]})",
               stand, [BA_FW_URL])
    elif size in have:
        log("  current Fachliche Weisungen: a file of the same size is already present")
        for f in s.dir.glob(f"*_{BA_FW}*.pdf"):
            if f.stat().st_size == size:
                s.save(f.name, f"{title} (retrieved {f.name[:10]}, Stand not determined)", f.name[:10], [BA_FW_URL])
    else:
        today = time.strftime("%Y-%m-%d")
        log("  the live Fachliche Weisungen differ from the known version: saved under today's date; "
            "read the Stand from its footer and rename it")
        s.save(f"{today}_{BA_FW}_abgerufen.pdf", f"{title} (retrieved {today}, Stand not determined)", today,
               [BA_FW_URL])
    for stand, urls in BA_FW_OLD:
        s.save(f"{stand}_{BA_FW}_Stand-{stand[5:7]}-{stand[:4]}.pdf", f"{title} (Stand {stand[5:7]}/{stand[:4]})",
               stand, urls)
    s.note(title + " (Stand 04/2020 and 03/2024)", BA_FW_URL,
           "versions named in the change history; no copy found on arbeitsagentur.de, asyl.net or in the Internet Archive")

    # Fachliche Weisungen Werkvertragsverfahren, from the list "Sonstige Rechtsnormen"
    markup, err = page(BA_PUB + "gesetze-und-weisungen/sonstige-rechtsnormen")
    hit = [(h, ba_clean(t)) for h, t in links(markup) if "Werkvertragsverfahren" in t and h.endswith(".pdf")]
    for href, text in hit[:1]:
        d = de_date(text)
        s.save(f"{d}_Fachliche-Weisungen-Werkvertragsverfahren.pdf", "Fachliche Weisungen Werkvertragsverfahren (FW WVV)",
               d, [urllib.parse.urljoin(BA, href)])
    if not hit:
        s.note("Fachliche Weisungen Werkvertragsverfahren (FW WVV)",
               BA_PUB + "gesetze-und-weisungen/sonstige-rechtsnormen", err or "not found in the list")

    # numbered Weisungen (and their Anlagen) from the yearly lists
    items, numbers = [], set()
    for name in BA_LISTS:
        markup, err = page(BA_PUB + name)
        if not markup:
            s.note(f"list {name}", BA_PUB + name, err or "empty")
            continue
        for href, text in links(markup):
            if "/datei/" in href and href.lower().endswith(".pdf"):
                items.append((urllib.parse.urljoin(BA, href).replace("https://arbeitsagentur.de", "https://www.arbeitsagentur.de"),
                              ba_clean(text)))
    for href, text in items:
        m = re.match(r"(?:Weisung|HEGA) ([\d/ -]+?) vom", text)
        if m and BA_KEEP.search(text):
            numbers.add(m.group(1))
    seen = set()
    for href, text in items:
        m = re.match(r"(?:Weisung|HEGA) ([\d/ -]+?) vom", text)
        a = re.search(r"zur Weisung (\d{9})", text)
        if href in seen or not ((m and m.group(1) in numbers and BA_KEEP.search(text)) or (a and a.group(1) in numbers)):
            continue
        seen.add(href)
        d = de_date(text)
        s.save(f"{d}_{slug(text, 100)}.pdf", text, d, [href])
    s.finish()
    return s


# --- static lists (filled in below) -------------------------------------------------------------------

PROASYL = "https://www.proasyl.de/wp-content/uploads/"
ASYLNET = "https://www.asyl.net/fileadmin/user_upload/"
FDS = "https://fragdenstaat.de/anfrage/"

# (file name, title, Stand, [sources in order of preference])
def _fds(path):                               # FragDenStaat attachment, then its newest Internet Archive capture
    return [FDS + path, WB + "2id_/" + FDS + path]


_DA = "BAMF Dienstanweisung Asyl (DA-Asyl), Stand "
_DU = "BAMF Dienstanweisung Dublin (DA-Dublin), Stand "
_AV = "BAMF Dienstanweisung Asylverfahrenssekretariat (DA-AVS), Stand "
BAMF_DOCS = [
    ("2017-04-25_DA-Asyl.pdf", _DA + "25.04.2017", "2017-04-25", [PROASYL + "2015/12/DA-Asyl-April-2017.pdf"]),
    ("2019-02-21_DA-Asyl.pdf", _DA + "21.02.2019", "2019-02-21", [PROASYL + "DA-Asyl_21_02_2019.pdf"]),
    ("2021-08-03_DA-Asyl.pdf", _DA + "03.08.2021", "2021-08-03", [PROASYL + "2021-08-03-BAMF-Dienstanweisung-Asyl.pdf"]),
    ("2022-02-04_DA-Asyl.pdf", _DA + "04.02.2022", "2022-02-04", [PROASYL + "DA-Asyl.pdf", ASYLNET + "DA-Asyl_02_2022.pdf"]),
    ("2023-01-01_DA-Asyl.pdf", _DA + "01.01.2023", "2023-01-01", [ASYLNET + "2023-01-01_BAMF_Dienstanweisung_Asyl.pdf"]),
    ("2024-02-26_DA-Asyl.pdf", _DA + "26.02.2024", "2024-02-26", [PROASYL + "DA-Asyl2024.pdf"]),
    ("2024-06-12_DA-Asyl.pdf", _DA + "12.06.2024", "2024-06-12", [PROASYL + "DA-Asyl_Stand_12.06.2024.pdf"]),
    ("2025-07-10_DA-Asyl.pdf", _DA + "10.07.2025 (listed by Pro Asyl as 15.07.2025)", "2025-07-10", [PROASYL + "DA-Asyl-1.pdf"]),
    ("2025-11-05_DA-Asyl.pdf", _DA + "05.11.2025", "2025-11-05", [PROASYL + "2025-11-05-BAMF-Dienstanweisung-Asyl.pdf"]),
    ("2026-06-12_DA-Asyl_GEAS-ohne-Kapitel-Grenzverfahren.pdf", _DA + "12.06.2026 (GEAS, ohne Kapitel Grenzverfahren)",
     "2026-06-12", [PROASYL + "da-asyl-geas-ohne-kapitel-grenzverfahren_konvertiert.pdf"] +
     _fds("dienstanweisung-asyl-2026/1128667/anhang/da-asyl-geas-ohne-kapitel-grenzverfahren_konvertiert.pdf")),
    ("2021-03_DA-Dublin.pdf", _DU + "03/2021 (scan without text layer; Stand as stated by Pro Asyl)", "2021-03", [PROASYL + "DA-Dublin-Stand-03-2021.pdf",
                                                            ASYLNET + "DA-Dublin-Stand-03-2021-.pdf"]),
    ("2022-12_DA-Dublin.pdf", _DU + "12/2022", "2022-12", [ASYLNET + "2022-12_BAMF_Dienstanweisung_Dublin.pdf"]),
    ("2023-02_DA-Dublin.pdf", _DU + "02/2023", "2023-02", [PROASYL + "2023-06-12-BAMF-Dienstanweisung-Dublin.pdf"]),
    ("2024-02_DA-Dublin.pdf", _DU + "02/2024", "2024-02", [PROASYL + "DA-Dublin.pdf"]),
    ("2024-10_DA-Dublin.pdf", _DU + "10/2024", "2024-10", [PROASYL + "2024-10-BAMF-Dienstanweisung-Dublin.pdf"]),
    ("2025-10_DA-Dublin.pdf", _DU + "10/2025", "2025-10", [PROASYL + "2025-10-BAMF-Dienstanweisung-Dublin.pdf"]),
    ("2023-03_DA-AVS.pdf", _AV + "03/2023 (chapters dated up to 04/23)", "2023-03", [PROASYL + "2023-06-12-BAMF-Dienstanweisung-AVS.pdf"]),
    ("2024-02_DA-AVS.pdf", _AV + "02/2024 (listed by Pro Asyl as 08/2023; chapters dated up to 02/24, PDF created 05.03.2024)",
     "2024-02", [PROASYL + "DA-AVS-0823.pdf"]),
    ("2024-12-12_DA-AVS.pdf", _AV + "12.12.2024", "2024-12-12", [PROASYL + "2024-12-12-BAMF-Dienstanweisung-AVS.pdf"]),
    ("2025-09-18_DA-AVS.pdf", _AV + "18.09.2025", "2025-09-18", [PROASYL + "2025-09-18-BAMF-Dienstanweisung-AVS.pdf"]),
    ("2026-06_DA-AVS_GEAS-ohne-Kapitel-Grenzverfahren.pdf", _AV + "06/2026 (GEAS, ohne Kapitel Grenzverfahren)", "2026-06",
     _fds("dienstanweisung-asyl-2026/1128667/anhang/da-avs-geas-ohne-kapitel-grenzverfahren_konvertiert.pdf")),
    ("2026-06-03_Leitfaden-Zustaendigkeitsbestimmungsverfahren.pdf",
     "BAMF Leitfaden zum Zuständigkeitsbestimmungsverfahren (ZBV) für Ausländerbehörden, Stand 03.06.2026", "2026-06-03",
     _fds("leitfaden-zustaendigkeitsbestimmungsverfahren-zbv/1128097/anhang/abh-leitfaden2026stand03-06-2026.pdf")),
]
BAMF_NOTES = [
    ("BAMF Qualitätshandbuch / further internal instructions",
     "https://www.bamf.de/DE/Themen/AsylFluechtlingsschutz/VerfahresteuerungQualitaetssicherung/verfahresteuerungqualitaetssicherung-node.html",
     "not published by BAMF; www.bamf.de answered 403 to this script, so its site was not searched"),
]
_BMI_AN = "https://www.asyl.net/fileadmin/user_upload/"
BMI_DOCS = [
    ("BMI-Allgemeine-Anwendungshinweise-zu-Par-25b-AufenthG.pdf",
     "Allgemeine Anwendungshinweise des BMI zur Einfügung des § 25b AufenthG durch das Gesetz zur Neubestimmung des "
     "Bleiberechts und der Aufenthaltsbeendigung vom 27. Juli 2015", "", [_BMI_AN + "dokumente/26754w.pdf"]),
    ("2019-01-08_BMI-Rundschreiben_Neuregelung-Familiennachzug-zu-subsidiaer-Schutzberechtigten.pdf",
     "BMI, Rundschreiben an die Länder (M 3 - 20010/18#3): Neuregelung des Familiennachzugs zu subsidiär Schutzberechtigten "
     "(§ 36a AufenthG), Klarstellungen; im Dokument auf den 8. Januar 2018 datiert, dem Inhalt nach 8. Januar 2019",
     "2019-01-08", [_BMI_AN + "dokumente/26913w.pdf"]),
    ("2022-11-07_BMI-Laenderschreiben_Familiennachzug-zum-anerkannten-Fluechtling_EuGH-Rechtsprechung.pdf",
     "BMI, Länderschreiben vom 07.11.2022 (M3-21002/1#73): Familiennachzug zum anerkannten Flüchtling – Auswirkungen der "
     "EuGH-Rechtsprechung vom 01.08.2022", "2022-11-07", [_BMI_AN + "31185w.pdf"]),
    ("2023-02-14_BMI-Laenderschreiben_Chancen-Aufenthaltsrecht_Ergaenzung-der-Anwendungshinweise.pdf",
     "BMI, Länderschreiben vom 14.02.2023 (M3-20010/28#11): Gesetz zur Einführung eines Chancen-Aufenthaltsrechts – "
     "Ergänzung der Anwendungshinweise vom 23.12.2022", "2023-02-14", [_BMI_AN + "31332.pdf"]),
    ("2023-04-28_BMI-Laenderrundschreiben_Einbindung-der-Auslaenderbehoerden-in-Visumverfahren-beim-Familiennachzug.pdf",
     "BMI, Länderrundschreiben vom 28.04.2023 (MI3.21002/1#95): Hinweise zur Einbindung der Ausländerbehörden in "
     "Visumverfahren beim Familiennachzug (mit IFG-Begleitschreiben vom 22.06.2023)", "2023-04-28", [_BMI_AN + "31692w.pdf"]),
]
# Internet Archive captures of bmi.bund.de downloads whose content differs from every file in de/bund/ (compared by
# SHA-1 on 2026-11-15): earlier versions of the Anwendungshinweise and their annexes, citizenship guidance, and the
# Aufnahmeanordnungen (section 23 AufenthG) with their Begleitschreiben. One line: <capture timestamp> <original URL>.
# These were not inspected, so they carry the capture date in the file name and no Stand.
BMI_WB = """
20220120123038 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage1.pdf;jsessionid=5515BB0E5B023C48E13C9F9407ECB12B.2_cid295?__blob=publicationFile&v=15
20240429182807 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage1_neu.pdf?__blob=publicationFile&v=2
20210727184719 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage2.pdf?__blob=publicationFile&v=5
20210811101356 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage2.pdf;jsessionid=1BF8F7FF9C82B956E37790EB866D44B0.1_cid287?__blob=publicationFile&v=5
20210918203226 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage2.pdf?__blob=publicationFile&v=8
20230208113831 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage2.pdf?__blob=publicationFile&v=5
20211008112416 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage4.pdf;jsessionid=B42C53690D7DC8575F7C072D5D8DBE87.1_cid295?__blob=publicationFile&v=8
20220621173326 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage4.pdf?__blob=publicationFile&v=5
20240225152749 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage4.pdf;jsessionid=B42C53690D7DC8575F7C072D5D8DBE87.1_cid295?__blob=publicationFile&v=8
20211008112415 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage5.pdf;jsessionid=1BDEBA612A4AE7BEF1B4969D646B5CC0.1_cid373?__blob=publicationFile&v=9
20221124112548 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage5.pdf?__blob=publicationFile&v=10
20211008112503 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage6.pdf;jsessionid=1BDEBA612A4AE7BEF1B4969D646B5CC0.1_cid373?__blob=publicationFile&v=7
20230206212210 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage6.pdf?__blob=publicationFile&v=3
20230417012324 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage6.pdf?__blob=publicationFile&v=3
20230419034700 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage6.pdf;jsessionid=1BDEBA612A4AE7BEF1B4969D646B5CC0.1_cid373?__blob=publicationFile&v=7
20220120083540 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage7.pdf;jsessionid=5515BB0E5B023C48E13C9F9407ECB12B.2_cid295?__blob=publicationFile&v=8
20240429182808 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage7_neu.pdf?__blob=publicationFile&v=3
20240528172727 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage7_neu.pdf?__blob=publicationFile&v=3
20220120092010 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage8.pdf;jsessionid=5515BB0E5B023C48E13C9F9407ECB12B.2_cid295?__blob=publicationFile&v=8
20240429182817 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage8_neu.pdf?__blob=publicationFile&v=2
20240528172545 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage8_neu.pdf?__blob=publicationFile&v=2
20220120090616 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/feg-anwendungshinweise-anlagen/anlage9.pdf;jsessionid=5515BB0E5B023C48E13C9F9407ECB12B.2_cid295?__blob=publicationFile&v=5
20190905110956 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-assoziationsrecht-ewg-tuerkei.pdf?__blob=publicationFile&v=2
20210816095017 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-duldungsregelung.pdf;jsessionid=3D94459B4EF6F412DA0DFE9DBA5BE7E9.1_cid287?__blob=publicationFile&v=2
20230225211125 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-duldungsregelung.pdf?__blob=publicationFile&v=3
20200422065340 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf;jsessionid=043D0B7685EB6C90C9EFCFF9F1118914.1_cid373?__blob=publicationFile&v=2
20210117174319 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf?__blob=publicationFile&v=3
20220120051817 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf;jsessionid=21E509016959F74942665C19A629F531.2_cid373?__blob=publicationFile&v=5
20220612075646 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf?__blob=publicationFile&v=5
20231128063305 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf;jsessionid=E89AE961145F049479A1FAEB80ABD349.live882?__blob=publicationFile&v=7
20240404152509 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf;jsessionid=37C15F084D07E9DBB1FEE5FAAC4EAA7F.live891?__blob=publicationFile&v=12
20240528172303 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-fachkraefteeinwanderungsgesetz.pdf;jsessionid=1AC4064D6C95D5AB3E36B50CA13E59A2.live862?__blob=publicationFile&v=15
20200603115036 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-zum-gesetz-ueber-duldung-bei-ausbildung.pdf?__blob=publicationFile&v=2
20230214114352 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/anwendungshinweise-zum-gesetz-ueber-duldung-bei-ausbildung.pdf?__blob=publicationFile&v=2
20240429230840 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/arbeitshinweise-umsetzung-aufenhaltsrechtliche-richtlinien-zur-arbeitsmigration.pdf?__blob=publicationFile&amp;v=4
20190412060015 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/brexit-rundschreiben.pdf;jsessionid=2950F4189DCD110D96852579837A960E.2_cid295?__blob=publicationFile&v=3
20220719150417 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/AnordnungNesT-Resettlement2022-20220701.pdf;jsessionid=ECF6C101940F53E478056ECE0F742631.2_cid295?__blob=publicationFile&v=2
20240429201824 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/AnordnungNesT-Resettlement2022-20220701.pdf?__blob=publicationFile&v=2
20220119143525 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/ao-nest-2021-begleitschreiben.pdf;jsessionid=394F6C3A82859E16BB39EFB24E49AE3D.1_cid295?__blob=publicationFile&v=2
20220119035426 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/ao-nest-2021.pdf;jsessionid=D1CE98A5A7B18A064CAFA36311528080.2_cid295?__blob=publicationFile&v=2
20200530221914 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-1-begleitregelung.pdf?__blob=publicationFile&v=3
20200530220721 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-1.pdf?__blob=publicationFile&v=5
20200531011533 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-2-begleitregelung.pdf?__blob=publicationFile&v=3
20200531011116 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-2.pdf?__blob=publicationFile&v=4
20250118235207 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-2.pdf?__blob=publicationFile&v=7
20220119152847 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-20210115-begleitschreiben.pdf;jsessionid=394F6C3A82859E16BB39EFB24E49AE3D.1_cid295?__blob=publicationFile&v=3
20220119141438 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-20210115.pdf?__blob=publicationFile&v=2
20200530235700 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-3-begleitregelung.pdf?__blob=publicationFile&v=3
20200530225834 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-3.pdf?__blob=publicationFile&v=4
20200530235450 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-4-begleitregelung.pdf?__blob=publicationFile&v=1
20200531000000 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-4.pdf?__blob=publicationFile&v=4
20200530235948 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-5-begleitregelung.pdf?__blob=publicationFile&v=3
20200530215741 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-5.pdf?__blob=publicationFile&v=4
20200531011451 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-6-begleitregelung.pdf?__blob=publicationFile&v=5
20200531011439 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-6.pdf?__blob=publicationFile&v=5
20200530223655 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-7-begleitregelung.pdf?__blob=publicationFile&v=1
20250119000547 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-7-begleitregelung.pdf?__blob=publicationFile&v=4
20190517012302 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-7.pdf;jsessionid=6C9A5A69950F5445F9462EF72F0F540E.2_cid373?__blob=publicationFile&v=1
20250119003359 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-7.pdf?__blob=publicationFile&v=4
20200530232201 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-8-begleitregelung.pdf?__blob=publicationFile&v=5
20200531002131 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-8.pdf?__blob=publicationFile&v=2
20200530222757 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-9-begleitregelung.pdf?__blob=publicationFile&v=2
20250119005651 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-9-begleitregelung.pdf?__blob=publicationFile&v=5
20200531005133 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-9.pdf?__blob=publicationFile&v=3
20230601134213 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-bap-afghanistan.pdf?__blob=publicationFile&v=2
20240429232141 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-lby-2018-begleitregelung.pdf?__blob=publicationFile&amp;v=5
20240429231858 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-lby-2018.pdf?__blob=publicationFile&amp;v=3
20200531004102 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-nest-2020-begleitschreiben.pdf?__blob=publicationFile&v=2
20200530223529 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-nest-2020.pdf?__blob=publicationFile&v=2
20200530215430 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2020-begleitschreiben.pdf?__blob=publicationFile&v=2
20200530231330 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2020.pdf?__blob=publicationFile&v=2
20250113094428 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2020.pdf?__blob=publicationFile&v=5
20220119185245 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2021-begleitschreiben.pdf;jsessionid=394F6C3A82859E16BB39EFB24E49AE3D.1_cid295?__blob=publicationFile&v=3
20210901094759 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2021.pdf?__blob=publicationFile&v=4
20220408153225 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2022-begleitschreiben.pdf?__blob=publicationFile&v=2
20231024050008 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2022-begleitschreiben.pdf?__blob=publicationFile&v=5
20220408153216 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2022.pdf?__blob=publicationFile&v=2
20230407163648 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-rst-2022.pdf?__blob=publicationFile&v=4
20240227011511 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-tur-220117--.pdf;jsessionid=F20E2C16B7CA00B7B469341C50AC8267.live891?__blob=publicationFile&v=2
20220301223800 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-tur-220117-begleitschreiben.pdf;jsessionid=8969369E3353E2E4C22423DFBE56F26A.1_cid373?__blob=publicationFile&v=6
20240226220256 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-tur-220117-begleitschreiben.pdf;jsessionid=F20E2C16B7CA00B7B469341C50AC8267.live891?__blob=publicationFile&v=16
20220302152558 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-tur-220117.pdf;jsessionid=81B1E437A625390F9F153F3D6F5352C6.1_cid287?__blob=publicationFile&v=7
20230421180143 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-tur-220117.pdf?__blob=publicationFile&v=9
20231113053657 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/aufnahmeanordnung-tur-220117.pdf?__blob=publicationFile&v=9
20220719150425 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/begleitschreibenNesT-Resettlement2022-20220701.pdf;jsessionid=ECF6C101940F53E478056ECE0F742631.2_cid295?__blob=publicationFile&v=2
20240429201815 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/begleitschreibenNesT-Resettlement2022-20220701.pdf?__blob=publicationFile&v=2
20240429231205 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/mai2015-aufnahm-ao.pdf?__blob=publicationFile&v=4
20240429231645 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/mai2015-begleitschr-aufnahm-ao.pdf?__blob=publicationFile&v=4
20220408153445 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/ao-nest-2021-begleitschreiben.pdf?__blob=publicationFile&v=2
20220408153226 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/ao-nest-2021.pdf?__blob=publicationFile&v=2
20240429230842 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/ao-nest-neustart-im-team-begleitschreiben.pdf?__blob=publicationFile&v=3
20240429231508 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/ao-nest-neustart-im-team.pdf?__blob=publicationFile&v=2
20220408153232 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/aufnahmeanordnung-nest-2020-begleitschreiben.pdf?__blob=publicationFile&v=2
20250119005846 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/aufnahmeanordnung-nest-2020-begleitschreiben.pdf?__blob=publicationFile&v=5
20220408153238 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/aufnahmeanordnung-nest-2020.pdf?__blob=publicationFile&v=2
20250119005809 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/nest-neustart-im-team/aufnahmeanordnung-nest-2020.pdf?__blob=publicationFile&v=5
20220408153230 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-4-begleitregelung.pdf?__blob=publicationFile&v=1
20220408153648 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-4.pdf?__blob=publicationFile&v=4
20250119010142 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-4.pdf?__blob=publicationFile&v=7
20230627060437 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-bes-2023-02-15-begleitschreiben.pdf;jsessionid=09D3FF3D105AF0769EE48B7B93F8DC02.2_cid373?__blob=publicationFile&v=3
20230627060347 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-bes-2023-02-15.pdf;jsessionid=09D3FF3D105AF0769EE48B7B93F8DC02.2_cid373?__blob=publicationFile&v=2
20240426053638 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-bes-2024-04-10-begleitschreiben.pdf;jsessionid=342F402576088C4F4E1B1B87ADC9B417.live891?__blob=publicationFile&v=2
20240429181927 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-bes-2024-04-10.pdf?__blob=publicationFile&v=2
20240225033755 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-nest-2023-begleitschreiben.pdf;jsessionid=31EF60CF3BA6CB4F9B2F0C9DBA8AD19C.live862?__blob=publicationFile&v=4
20240224001814 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/resettlement/aufnahmeanordnung-nest-2023.pdf;jsessionid=31EF60CF3BA6CB4F9B2F0C9DBA8AD19C.live862?__blob=publicationFile&v=2
20240429231954 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/sept2015-aufnahm-ao.pdf?__blob=publicationFile&v=4
20240429230809 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/humanitaere-aufnahmeprogramme/sept2015-begleitschr-aufnahm-ao.pdf?__blob=publicationFile&v=5
20191230132113 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/migration/resettlement-20190806.pdf?__blob=publicationFile&v=2
20200524153657 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/aenderung-vah-stag.pdf?__blob=publicationFile&v=1
20201113173436 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/anwendungshinweise-brexit.pdf?__blob=publicationFile&v=4
20210701112034 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/anwendungshinweise-brexit.pdf;jsessionid=0FE5FEC16590AA4D621649230F828B88.2_cid295?__blob=publicationFile&v=7
20220303230827 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/anwendungshinweise-staatsangehoerigkeit.pdf;jsessionid=57E6C75CD51FD6ADBB4925288FBFE469.2_cid295?__blob=publicationFile&v=3
20210914103007 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/anwendungshinweise-umsetzung-freizuegigkeitsgesetz.pdf;jsessionid=81FA98F92F3BF0BC11CAC12832AB0E06.2_cid295?__blob=publicationFile&v=4
20220719095908 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/anwendungshinweise-umsetzung-freizuegigkeitsgesetz.pdf?__blob=publicationFile&v=4
20230107234019 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/laenderschreiben-ukr-mehrstaatigkeit.pdf?__blob=publicationFile&v=5
20210909171926 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/optionsverfahren.pdf?__blob=publicationFile&v=1
20250803192115 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/staatsangehoerigkeit/2505_anwendungshinweise-staatsangehoerigkeit.pdf?__blob=publicationFile&v=6
20190126032744 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/stag-anwendungshinweise-06-15.pdf?__blob=publicationFile&v=3
20220409013117 https://www.bmi.bund.de/SharedDocs/downloads/DE/veroeffentlichungen/themen/verfassung/stag-anwendungshinweise-06-15.pdf?__blob=publicationFile&v=3
"""
BMI_TITLES = [                                # file stem prefix -> title
    ("anwendungshinweise-fachkraefteeinwanderungsgesetz", "Anwendungshinweise des BMI zum Fachkräfteeinwanderungsgesetz"),
    ("feg-anlage", "Anlage zu den Anwendungshinweisen des BMI zum Fachkräfteeinwanderungsgesetz"),
    ("anwendungshinweise-duldungsregelung", "Anwendungshinweise zur Duldungsregelung des § 60a AufenthG"),
    ("anwendungshinweise-zum-gesetz-ueber-duldung", "Anwendungshinweise des BMI zum Gesetz über Duldung bei Ausbildung und Beschäftigung"),
    ("anwendungshinweise-assoziationsrecht", "Anwendungshinweise zum Assoziationsrecht EWG/Türkei"),
    ("arbeitshinweise-umsetzung", "Anwendungshinweise zur Umsetzung aufenthaltsrechtlicher Richtlinien der EU zur Arbeitsmigration"),
    ("brexit-rundschreiben", "Rundschreiben zum Umgang mit britischen Staatsangehörigen im Falle eines ungeregelten Brexit"),
    ("anwendungshinweise-brexit", "Anwendungshinweise des BMI zum Brexit"),
    ("anwendungshinweise-umsetzung-freizuegigkeitsgesetz", "Anwendungshinweise zur Umsetzung des Gesetzes zur aktuellen Anpassung des FreizügG/EU"),
    ("anwendungshinweise-staatsangehoerigkeit", "Anwendungshinweise des BMI zum Staatsangehörigkeitsgesetz (frühere Fassung)"),
    ("staatsangehoerigkeit_2505", "Anwendungshinweise des BMI zum StAG (Stand 1. Mai 2025), andere Dateifassung"),
    ("stag-anwendungshinweise-06-15", "Vorläufige Anwendungshinweise des BMI zum Staatsangehörigkeitsgesetz (Datei stag-anwendungshinweise-06-15)"),
    ("aenderung-vah-stag", "Änderung der Vorläufigen Anwendungshinweise des BMI zum Staatsangehörigkeitsgesetz"),
    ("laenderschreiben-ukr-mehrstaatigkeit", "BMI-Länderschreiben: Mehrstaatigkeit bei ukrainischen Staatsangehörigen"),
    ("optionsverfahren", "BMI: Optionsverfahren (Staatsangehörigkeitsrecht)"),
    ("hap_", "BMI Aufnahmeanordnung / Begleitschreiben (humanitäre Aufnahmeprogramme, Resettlement)"),
]
BMI_NOTES = [
    ("Current Anwendungshinweise and Länderschreiben listed on bmi.bund.de",
     "https://www.bmi.bund.de/DE/themen/migration/migration-node.html",
     "www.bmi.bund.de answered 403 to this script's robots.txt request on 2026-11-15, so the site was not read; "
     "its Anwendungshinweise known to download_de.py are in de/bund/"),
    ("Bundespolizei: instructions on border control and return", "https://www.bundespolizei.de/",
     "none found published; bundespolizei.de answered 406 to the robots.txt request, so the site was not read"),
    ("Allgemeine Verwaltungsvorschrift zum Staatsangehörigkeitsrecht (StAR-VwV) and BVFG-VwV",
     "https://www.verwaltungsvorschriften-im-internet.de/erlassstellen.html",
     "not in the federal database of administrative regulations (checked the lists of BMI, BMAS and AA)"),
]


def bmi_wb_items():
    names = set()
    for line in BMI_WB.strip().splitlines():
        ts, orig = line.split(" ", 1)
        path = re.sub(r"[;?].*|%3B.*", "", orig).split("/themen/", 1)[1].replace("%20", "")
        stem = (path[:-4].split("/", 1)[1].replace("humanitaere-aufnahmeprogramme/", "hap/")
                .replace("feg-anwendungshinweise-anlagen/", "feg-").replace("/", "_"))
        name = f"{stem}_archiviert-{ts[:4]}-{ts[4:6]}-{ts[6:8]}.pdf"
        if name in names:
            name = name[:-4] + f"-{ts[8:]}.pdf"
        names.add(name)
        title = next((t for k, t in BMI_TITLES if stem.startswith(k)), stem)
        yield (name, f"{title} [{path.rsplit('/', 1)[-1]}; bmi.bund.de, Internet Archive capture of "
                     f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}]", "", [WB + ts + "id_/" + orig])
AA_DOCS = [
    ("2017-03-20_AA-Weisung_Familiennachzug-zum-unbegleiteten-minderjaehrigen-Fluechtling.pdf",
     "Auswärtiges Amt, Weisung an alle Auslandsvertretungen vom 20.03.2017 (Gz. 508-3-543.53/2): Familiennachzug zum "
     "unbegleiteten minderjährigen Flüchtling – Eltern- und Geschwisternachzug, humanitäre Aufnahme nach § 22 AufenthG",
     "2017-03-20", [ASYLNET + "dokumente/24862w.pdf"]),
    ("2023-07-17_AA-Weisung_Gueltigkeitsdauer-nationaler-Visa.pdf",
     "Auswärtiges Amt, Weisung an alle Auslandsvertretungen mit Visastelle vom 17.07.2023 (Gz. 508-540.30/allg.): "
     "Gültigkeitsdauer nationaler Visa", "2023-07-17",
     ["https://www.frsh.de/fileadmin/user_upload/AA_Rundschreiben_Gueltigeitsdauer-nationaler-Visa-Weisung_20230717.pdf"]),
]
AA_NOTES = [
    ("Runderlasse / Weisungen to missions other than the Visumhandbuch", "https://www.auswaertiges-amt.de/de/service/visa-und-aufenthalt",
     "not published by the Auswärtiges Amt itself (only the Visumhandbuch and the Handreichung Studierendenvisa, both in de/bund/); "
     "the two files saved are copies of single Weisungen republished by asyl.net and Flüchtlingsrat Schleswig-Holstein; "
     "further ones exist only as freedom-of-information releases on fragdenstaat.de, which dropped this script's connections"),
]
BVA_DOCS = []
BVA_NOTES = [
    ("Instructions for decision practice on Spätaussiedler admission (BVFG) and citizenship cases abroad",
     "https://www.bva.bund.de/DE/Services/Buerger/Migration-Integration/Spaetaussiedler/spaetaussiedler_node.html",
     "www.bva.bund.de answered 403 to this script's robots.txt request on 2026-11-15, so the site was not read; a web search "
     "found only applicant leaflets (Merkblätter) and forms, no published instructions to case officers"),
]


def static(code, body, docs, notes):
    s = Source(code, body)
    for name, title, date, urls in docs:
        s.save(name, title, date, urls)
    for title, url, reason in notes:
        s.note(title, url, reason)
    s.finish()
    return s


SOURCES = {
    "ba": ba,
    "bamf": lambda: static("bamf", "Bundesamt für Migration und Flüchtlinge", BAMF_DOCS, BAMF_NOTES),
    "bmi": lambda: static("bmi", "Bundesministerium des Innern", BMI_DOCS + list(bmi_wb_items()), BMI_NOTES),
    "aa": lambda: static("aa", "Auswärtiges Amt", AA_DOCS, AA_NOTES),
    "bva": lambda: static("bva", "Bundesverwaltungsamt", BVA_DOCS, BVA_NOTES),
}


def main():
    args = sys.argv[1:]
    for a in [a for a in args if a.startswith("--skip=")]:    # hosts to leave alone in this run, e.g. one that throttles
        args.remove(a)
        for host in a[7:].split(","):
            BLOCKED[host] = "host not contacted in this run (--skip); re-run without --skip to fetch"
    names = args or list(SOURCES)
    bad = [n for n in names if n not in SOURCES]
    if bad:
        sys.exit(f"unknown source(s): {', '.join(bad)}; known: {', '.join(SOURCES)}")
    done = []
    try:
        for n in names:
            log(f"== {n}")
            done.append(SOURCES[n]())
    finally:
        if done:
            write_tables(done)
        for host, why in BLOCKED.items():
            log(f"host given up in this run: {host} ({why})")
        log(f"new files: {STATS['new']}, {STATS['bytes'] / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

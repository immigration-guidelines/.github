#!/usr/bin/env python3
"""Download the Israeli Population and Immigration Authority's published procedures.

    python3 download_il.py                 # everything
    python3 download_il.py --rebuild-list  # also re-parse the master list (needs pdftohtml)

Israel: Population and Immigration Authority (rashut ha-ukhlusin ve-ha-hagira, PIBA),
"nehalim" - the numbered working procedures for its registry, visa, border and
enforcement officials. The authority publishes a master table of all of them
("procedures_list.pdf", https://www.gov.il/he/pages/list_of_piba_procedures); each
procedure has a page https://www.gov.il/he/departments/policies/<slug> and its files
are at https://www.gov.il/BlobFolder/policy/<slug>/<lang>/<file>.

www.gov.il answers scripted requests - robots.txt included - with a Cloudflare
challenge (HTTP 403). This script does not try to get around that and never contacts
gov.il. Everything is taken from the Internet Archive's Wayback Machine:

  1. the Wayback index (CDX) of www.gov.il/BlobFolder/policy/ is listed once;
  2. the master table is downloaded and (if pdftohtml is installed, or with
     --rebuild-list) parsed into il/procedures-list.tsv: number, title, date, page link;
  3. for every folder the table links to, and every other folder holding a file named
     after a procedure number, the latest good capture of each file is saved;
  4. the authority's previous website (piba.gov.il/Regulations/, 2012-2016, also only
     from the Wayback Machine) is saved into il/old-piba.gov.il/ - older versions.

Procedures with no archived copy, or only one older than the date in the table, are
written to il/not-obtained.tsv with their gov.il addresses for saving in a browser.
A file saved by hand into a series folder with a name starting with the procedure
number (e.g. il/5-visas-and-foreigners/5.2.0008.pdf) is picked up in il/index.tsv
on the next run.

Files that already exist are skipped. Standard library only. One request at a time,
PAUSE seconds apart; the run stops after three refusals in a row.
"""
import gzip
import html
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "il"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 2.5
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000
CDX = "https://web.archive.org/cdx/search/cdx"
WB = "https://web.archive.org/web/"
LIST_PAGE = "https://www.gov.il/he/pages/list_of_piba_procedures"
LIST_TSV = OUT / "procedures-list.tsv"

SERIES = {
    "1": "1-general", "2": "2-registry", "3": "3-passports", "4": "4-citizenship",
    "5": "5-visas-and-foreigners", "6": "6-border-control", "8": "8-registration-stations",
    "9": "9-foreign-workers", "10": "10-enforcement",
}
OLD = "old-piba.gov.il"
LISTS = "lists"
NUM = r"\d{1,2}\.\d{1,2}\.\d{4,5}"
MAGIC = {
    ".pdf": (b"%PDF",), ".docx": (b"PK",), ".xlsx": (b"PK",), ".pptx": (b"PK",),
    ".doc": (b"\xd0\xcf\x11\xe0",), ".xls": (b"\xd0\xcf\x11\xe0",),
    ".jpg": (b"\xff\xd8",), ".jpeg": (b"\xff\xd8",), ".png": (b"\x89PNG",), ".rtf": (b"{\\rtf",),
}
refusals = 0


class Stop(Exception):
    pass


def fetch(url, dest=None, timeout=300, retry=True):
    """One paced request. Returns (bytes or None, error or None). With dest, streams to
    dest.part and renames. Refusals are never retried; three in a row end the run."""
    global refusals
    time.sleep(PAUSE)
    url = urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout) as r:
            if dest is None:
                data = r.read()
            else:
                part = dest.with_name(dest.name + ".part")
                n = 0
                with open(part, "wb") as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        n += len(chunk)
                length = r.headers.get("Content-Length")
                if length is not None and int(length) != n:
                    part.unlink()
                    return None, "transfer cut short"
                with open(part, "rb") as f:
                    head = f.read(8)
                if head[:2] == b"\x1f\x8b" and dest.suffix.lower() != ".gz":
                    # captured with "Content-Encoding: gzip": undo the transfer compression
                    with gzip.open(part, "rb") as f:
                        raw = f.read()
                    part.write_bytes(raw)
                    head = raw[:8]
                want = MAGIC.get(dest.suffix.lower())
                if (want and not head.startswith(want)) or head.lstrip()[:1] == b"<":
                    part.unlink()
                    return None, "not the expected file type (error or challenge page?)"
                if dest.suffix.lower() == ".pdf":
                    with open(part, "rb") as f:
                        f.seek(max(0, part.stat().st_size - 4096))
                        if b"%%EOF" not in f.read():
                            part.unlink()
                            return None, "PDF is cut short (no end-of-file marker)"
                part.replace(dest)
                data = b""
        refusals = 0
        return data, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            refusals += 1
            if refusals >= 3:
                raise Stop(f"three refusals in a row (last: HTTP {e.code} for {url}); stopping. Re-run later.")
            time.sleep(60)
        return None, f"HTTP {e.code}"
    except Exception as e:                              # noqa: BLE001 - network trouble: one more go
        if "refused" in str(e).lower():
            refusals += 1
            if refusals >= 3:
                raise Stop(f"three refused connections in a row (last: {url}); stopping. Re-run later.")
            time.sleep(60)
        if retry:
            time.sleep(20)
            return fetch(url, dest, timeout, retry=False)
        return None, f"{type(e).__name__}: {e}"


def cdx(prefix):
    """All HTTP-200 captures under a URL prefix: {urlkey: [(timestamp, original, mime, digest), ...]}."""
    q = (f"{CDX}?url={urllib.parse.quote(prefix, safe='/:')}&matchType=prefix&filter=statuscode:200"
         "&fl=urlkey,timestamp,original,mimetype,digest&limit=300000")
    for attempt in range(3):
        data, why = fetch(q, timeout=600)
        if data is not None and not data.lstrip().startswith(b"<"):
            break
        print(f"  index query failed ({why or 'archive offline page'}); waiting")
        time.sleep(60)
    else:
        raise Stop(f"Wayback index not available for {prefix}")
    caps = defaultdict(list)
    for line in data.decode("utf-8", "replace").splitlines():
        p = line.split(" ")
        if len(p) == 5:
            caps[p[0]].append(tuple(p[1:]))
    for v in caps.values():
        v.sort()
    return caps


def candidates(captures, n=3):
    """Captures that are not HTML pages, newest first, one per distinct content, at most n."""
    out, seen = [], set()
    for c in reversed(captures):
        if "html" not in c[2] and c[3] not in seen:
            seen.add(c[3])
            out.append(c)
    return out[:n]


def clean(name, n=120):
    name = urllib.parse.unquote(name)
    name = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 5:
        return name[:n]
    return stem[:n].rstrip("._") + "." + ext.lower()


def iso(raw):
    """Last d.m.y date in a table cell -> YYYY-MM-DD ('' if none)."""
    found = re.findall(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4}|\d{2})(?!\d)", raw)
    if not found:
        return ""
    d, m, y = found[-1]
    y = int(y) + 2000 if len(y) == 2 else int(y)
    if not (1 <= int(m) <= 12 and 1 <= int(d) <= 31 and 1990 <= y <= 2100):
        return ""
    return f"{y:04d}-{int(m):02d}-{int(d):02d}"


# ---------------------------------------------------------------- master table

def unvisual(s):
    """pdftohtml gives right-to-left lines in visual order; turn one into reading order."""
    s = s[::-1]
    return re.sub(r"[0-9A-Za-z][0-9A-Za-z.,/\-:' ]*[0-9A-Za-z]|[0-9A-Za-z]", lambda m: m.group(0)[::-1], s)


def join_line(frags):
    out, end = "", None
    for left, width, txt in sorted(frags):
        if end is not None and left - end > 2:
            out += " "
        out += txt
        end = left + width
    return out


def parse_list(pdf):
    """Master table PDF -> rows (number, title, date_raw, links). Needs poppler's pdftohtml."""
    xml = subprocess.run(["pdftohtml", "-xml", "-i", "-q", "-stdout", str(pdf)],
                         capture_output=True, check=True).stdout.decode("utf-8", "replace")
    rows = []
    for page in re.findall(r"<page .*?</page>", xml, re.S):
        items = []
        for top, left, width, body in re.findall(
                r'<text top="(\d+)" left="(\d+)" width="(\d+)" height="\d+" font="\d+">(.*?)</text>', page, re.S):
            href = re.search(r'href="([^"]+)"', body)
            txt = html.unescape(re.sub(r"<[^>]+>", "", body))
            if txt.strip() and txt.strip() != "~":
                items.append((int(top), int(left), int(width), txt, html.unescape(href.group(1)) if href else None))

        def is_num(it):
            return it[1] >= 640 and it[0] < 1100 and not it[4] and re.fullmatch(r"[\d.]+", it[3].strip())
        cells = defaultdict(list)
        for it in items:
            if is_num(it):
                cells[it[0]].append((it[1], it[3].strip()))
        nums = [(top, n) for top, n in ((t, "".join(x for _, x in sorted(c))) for t, c in sorted(cells.items()))
                if re.fullmatch(NUM, n)]
        if not nums:
            continue
        recs = [{"num": n, "title": defaultdict(list), "date": defaultdict(list), "links": []} for _, n in nums]
        lo, hi = nums[0][0] - 32, nums[-1][0] + 45       # above: the column headings
        for it in items:
            top, left, width, txt, href = it
            if not lo <= top <= hi or left < 75 or is_num(it):
                continue
            rec = recs[min(range(len(nums)), key=lambda i: abs(nums[i][0] - top))]
            if left < 205 and not href:
                rec["date"][top].append((left, width, txt))
            else:
                rec["title"][top].append((left, width, txt))
                if href and href not in rec["links"]:
                    rec["links"].append(href)
        for rec in recs:
            title = " ".join(unvisual(join_line(rec["title"][t])) for t in sorted(rec["title"]))
            date = " ".join("".join(x.strip() for _, _, x in sorted(rec["date"][t])) for t in sorted(rec["date"]))
            if not re.search(r"\d", date):
                date = unvisual(date)
            rows.append((rec["num"], re.sub(r"\s+", " ", title).strip(), date.strip(), rec["links"]))
    return rows


def load_list():
    rows = []
    if LIST_TSV.exists():
        for line in LIST_TSV.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) >= 5:
                rows.append({"num": p[0], "title": p[1], "date_raw": p[2], "date": p[3],
                             "links": [x for x in p[4].split(" ") if x]})
    return rows


def slug_of(link):
    path = urllib.parse.unquote(urllib.parse.urlsplit(link).path).lower()
    m = re.search(r"/(?:policies|pages)/([^/]+)/?$", path) or re.search(r"/blobfolder/policy/([^/]+)/", path)
    return m.group(1) if m else None


# ---------------------------------------------------------------- main

def piba_number(num):
    """True for a number shaped like the authority's (series 1-10, serial not a year): other
    ministries' files under the same address prefix are often named after dates."""
    a, _, c = num.split(".")
    return a in SERIES and not re.match(r"(19|20)\d\d$", c)


def series_dir(num):
    return SERIES.get(num.split(".")[0], "other")


def main():
    rebuild = "--rebuild-list" in sys.argv
    for sub in list(SERIES.values()) + [OLD, LISTS]:
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    rows, failed, total = [], [], 0
    prev = {}                               # last run's index: which capture each existing file came from
    if (OUT / "index.tsv").exists():
        for line in (OUT / "index.tsv").read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) >= 10:
                prev[p[0]] = p

    def save(namer, cands):
        """Make sure one of the captures (newest first) is on disk; namer(timestamp) gives the
        destination. Returns (dest, timestamp, original address, Wayback address) or None."""
        nonlocal total
        for ts, original, *_ in cands:
            dest = namer(ts)
            if dest.exists() and dest.stat().st_size > 0:
                p = prev.get(str(dest.relative_to(OUT)))
                total += dest.stat().st_size
                if p and p[7]:
                    return dest, p[7], p[8], p[3]
                return dest, ts, original, f"{WB}{ts}id_/{original}"
        if len(rows) >= MAX_FILES or total >= MAX_BYTES:
            failed.append((namer(cands[0][0]).name, cands[0][1], "not attempted: file/size limit reached"))
            return None
        whys = []
        for ts, original, *_ in cands:
            dest, src = namer(ts), f"{WB}{ts}id_/{original}"
            _, why = fetch(src, dest)
            if not why:
                print(f"  saved {dest.relative_to(OUT)} ({dest.stat().st_size:,} bytes)", flush=True)
                total += dest.stat().st_size
                return dest, ts, original, src
            print(f"  FAILED {dest.name} (capture {ts}): {why}", flush=True)
            whys.append(f"Wayback capture {ts}: {why}")
        failed.append((namer(cands[0][0]).name, cands[0][1], "; ".join(whys)))
        return None

    print("listing Wayback captures of www.gov.il/BlobFolder/policy/ ...", flush=True)
    caps = cdx("www.gov.il/BlobFolder/policy/")
    folders = defaultdict(list)
    for key in caps:
        m = re.match(r"il,gov\)/blobfolder/policy/([^/]+)/(.+)", key)
        if m:
            folders[urllib.parse.unquote(m.group(1))].append(key)
    print(f"  {len(caps)} archived addresses in {len(folders)} folders")

    # 1. the master table(s)
    newest_list = None
    for key in sorted(folders.get("list_of_piba_procedures", [])):
        cands = candidates(caps[key], 1)
        if not cands or not cands[0][1].lower().endswith(".pdf"):
            continue
        c = cands[0]
        first = min(x[0] for x in caps[key] if x[3] == c[3])     # first capture of this exact file
        date = f"{first[:4]}-{first[4:6]}-{first[6:8]}"
        dest = OUT / LISTS / f"{date}_{clean(c[1].rsplit('/', 1)[-1])}"
        done = save(lambda ts, dest=dest: dest, cands)
        if done:
            rows.append((f"{LISTS}/{dest.name}", "טבלה מרכזת של הנהלים המקצועיים ברשות האוכלוסין וההגירה", "",
                         done[3], "", LISTS, "he", done[1], done[2], f"master table; first archived {date}"))
            if c[1].endswith("procedures_list.pdf"):
                newest_list = dest
    if newest_list and (rebuild or not LIST_TSV.exists()):
        if shutil.which("pdftohtml"):
            parsed = parse_list(newest_list)
            with open(LIST_TSV, "w", encoding="utf-8") as f:
                f.write("procedure_number\ttitle\tdate_as_printed\tdate\tlinks\n")
                for num, title, raw, links in parsed:
                    f.write("\t".join([num, title, raw, iso(raw), " ".join(links)]) + "\n")
            print(f"  parsed {len(parsed)} procedures from {newest_list.name} into {LIST_TSV.name}")
        else:
            print("  pdftohtml not installed: cannot parse the master table")
    table = load_list()
    if not table:
        sys.exit(f"{LIST_TSV} is missing and could not be built; install poppler-utils (pdftohtml) and re-run")
    by_num = {}
    for r in table:
        by_num.setdefault(r["num"], r)
    slug_nums = defaultdict(list)
    for r in table:
        for link in r["links"]:
            s = slug_of(link)
            if s and r["num"] not in slug_nums[s]:
                slug_nums[s].append(r["num"])

    # 2. current site: every file in a folder the table links to, or named after a procedure number
    got = defaultdict(list)                 # number -> [(capture timestamp, is_current)]
    seen_names = set()
    for folder in sorted(folders):
        if folder == "list_of_piba_procedures":
            continue
        for key in sorted(folders[folder]):
            cands = candidates(caps[key])
            if not cands:
                continue
            original = cands[0][1]
            rest = urllib.parse.unquote(original.split("/policy/", 1)[-1] if "/policy/" in original
                                        else original.split("/Policy/", 1)[-1])
            parts = rest.split("/")
            base = parts[-1]
            lang = parts[1].lower() if len(parts) >= 3 and len(parts[1]) == 2 else ""
            ext = "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""
            if ext not in MAGIC:
                continue                                    # truncated addresses, web pages
            m = re.match(rf"({NUM})(?!\d)", base)
            if m and (m.group(1) in by_num or folder in slug_nums or piba_number(m.group(1))):
                num = m.group(1)
            elif folder in slug_nums:
                num = slug_nums[folder][0]
            else:
                continue
            info = by_num.get(num)
            listed = info["date"] if info else ""
            name = clean(base)
            if not name.startswith(num):
                name = f"{num}_{name}"
            if lang and lang != "he":
                name = name.replace(num, f"{num}_{lang}", 1)
            sub = series_dir(num)
            if (sub, name) in seen_names:
                name = name.rsplit(".", 1)[0] + "_" + clean(folder, 40) + ext
            seen_names.add((sub, name))

            def namer(ts, sub=sub, name=name, listed=listed):
                # the date in the master table is only this file's date if it was archived on or after it
                if listed and f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" >= listed:
                    return OUT / sub / f"{listed}_{name}"
                return OUT / sub / name
            done = save(namer, cands)
            if not done:
                continue
            dest, ts, original, src = done
            name = dest.name
            cap_date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
            current = bool(listed) and name.startswith(listed + "_")
            got[num].append((ts, current))
            if not info:
                note = "number not in the 2026 master table (withdrawn or renumbered?)"
            elif current:
                note = ""
            elif listed:
                note = f"archived {cap_date}, before the version dated {listed} in the master table: may be superseded"
            else:
                note = f"archived {cap_date}; master table gives no date ({info['date_raw'] or 'blank'})"
            rows.append((f"{sub}/{name}", info["title"] if info else "", listed if current else "", src, num,
                         sub, lang or "he", ts, original, note))

    # 3. the authority's previous website, 2012-2016 (older versions)
    print("listing Wayback captures of piba.gov.il/Regulations/ ...", flush=True)
    try:
        old = cdx("piba.gov.il/Regulations/")
    except Stop as e:
        print(f"  {e}\n  keeping the old-site files already listed in index.tsv; re-run later for the rest")
        old = {}
        rows.extend(tuple(p[:10]) for f, p in prev.items() if p[5] == OLD and (OUT / f).exists())
        total += sum((OUT / r[0]).stat().st_size for r in rows if r[5] == OLD)
    for key in sorted(old):
        cands = candidates(old[key])
        if not cands:
            continue
        original = cands[0][1]
        base = urllib.parse.unquote(original.rsplit("/", 1)[-1])
        ext = "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""
        if ext not in MAGIC:
            continue
        m = re.search(rf"(?<![\d.])({NUM})(?!\d)", base)
        num = m.group(1) if m else ""
        name = clean(base)
        if (OLD, name) in seen_names:
            continue
        seen_names.add((OLD, name))
        done = save(lambda ts, name=name: OUT / OLD / name, cands)
        if not done:
            continue
        _, ts, original, src = done
        info = by_num.get(num)
        rows.append((f"{OLD}/{name}", info["title"] if info else "", "", src, num, OLD, "he", ts, original,
                     f"previous website piba.gov.il, archived {ts[:4]}-{ts[4:6]}-{ts[6:8]}: older version"
                     + ("" if info or not num else "; number not in the 2026 master table")))

    # 4. files saved by hand into a series folder
    known = {r[0] for r in rows}
    for sub in SERIES.values():
        for p in sorted((OUT / sub).iterdir()):
            rel = f"{sub}/{p.name}"
            if rel in known or p.name.endswith(".part") or not p.is_file():
                continue
            m = re.search(rf"(?<![\d.])({NUM})(?!\d)", p.name)
            num = m.group(1) if m else ""
            info = by_num.get(num)
            d = re.match(r"(\d{4}-\d{2}-\d{2})_", p.name)
            link = info["links"][0] if info and info["links"] else ""
            rows.append((rel, info["title"] if info else "", d.group(1) if d else "", link, num, sub, "", "", link,
                         "not downloaded by the script (saved by hand)"))
            got[num].append(("", True))
            total += p.stat().st_size

    rows.sort(key=lambda r: (r[5] == OLD, r[5] == LISTS, [int(x) for x in re.findall(r"\d+", r[4])[:3]], r[0]))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tprocedure_number\tseries\tlanguage_folder\twayback_timestamp"
                "\toriginal_url\tnote\n")
        for r in rows:
            f.write("\t".join(r) + "\n")

    # 5. what the master table lists but the archive does not hold (or holds only in an older version)
    old_nums = {r[4] for r in rows if r[5] == OLD}
    missing = []
    for r in table:
        have = got.get(r["num"], [])
        page = r["links"][0] if r["links"] else LIST_PAGE
        extra = "; an older version from piba.gov.il is in old-piba.gov.il/" if r["num"] in old_nums else ""
        removed = "הוסר" in r["date_raw"]
        if any(cur for _, cur in have):
            continue
        if have:
            latest = max(ts for ts, _ in have)
            if r["date"]:
                why = (f"only an older copy archived ({latest[:4]}-{latest[4:6]}-{latest[6:8]}); "
                       f"master table dates the current version {r['date']}")
            else:
                continue                                    # no date to compare against: kept as is
        elif removed:
            why = "master table: taken down for updating; no archived copy on gov.il" + extra
        elif not r["links"]:
            why = "master table gives no link; no archived copy found" + extra
        else:
            why = "no copy in the Wayback Machine; gov.il refuses scripted requests (Cloudflare challenge)" + extra
        missing.append((r["num"], r["title"], r["date"] or r["date_raw"], page, why))
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("procedure_number\ttitle\tdate\turl\treason\n")
        for m in missing:
            f.write("\t".join(m) + "\n")
        for name, url, why in failed:
            f.write("\t".join(["", name, "", url, why]) + "\n")

    print(f"{len(rows)} files, {total:,} bytes in {OUT}; {len(failed)} downloads failed; "
          f"{len(missing)} of {len(table)} listed procedures not obtained in their current version")


if __name__ == "__main__":
    try:
        main()
    except Stop as e:
        sys.exit(str(e))

#!/usr/bin/env python3
"""Download published immigration-office guidance from other countries.

    ./download.py nl    Netherlands: Vreemdelingencirculaire 2000, parts A, B and C (current version)
    ./download.py wi    Netherlands: IND work instructions (werkinstructies), 2000 onwards,
                        from Radboud University's archive (the IND's own portal blocks scripts)
    ./download.py dk    Denmark: practice notes (praksisnotater) listed on nyidanmark.dk
    ./download.py uk    United Kingdom: Home Office "Visas and immigration operational guidance"
    ./download.py ukcoi United Kingdom: Home Office country policy and information notes (into uk/coi/)
    ./download.py       all of them

Files already downloaded are skipped, so the script can be re-run. Each country
folder gets an index.tsv listing what was saved and where it came from.
"""
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


def get(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:                      # noqa: BLE001 - report and retry
            err = e
            time.sleep(3 * (attempt + 1))
    print(f"  FAILED {url}: {err}")
    return None


def save(url, dest):
    """Download url to dest unless it is already there. Returns True if the file exists afterwards."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    data = get(url)
    if data is None:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def quiet_save(url, dest):
    """Like save(), but a single attempt and no error message; used when trying alternative addresses."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception:                               # noqa: BLE001
        return False
    if not data.startswith(b"%PDF"):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def slug(s, n=90):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:n] or "x"


def text_of(markup):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    t = re.sub(r"<(br|/p|/div|/li|/h\d|/tr|/al|/lid|/titel|/kop)[^>]*>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip() + "\n"


# --- Netherlands -----------------------------------------------------------

NL_PARTS = {"A": "BWBR0012287", "B": "BWBR0012289", "C": "BWBR0012288"}
NL_REPO = "https://repository.officiele-overheidspublicaties.nl/bwb"


def nl():
    out = ROOT / "nl"
    out.mkdir(exist_ok=True)
    rows = []
    for part, bwb in NL_PARTS.items():
        manifest = get(f"{NL_REPO}/{bwb}/manifest.xml")
        if manifest is None:
            continue
        (out / f"manifest-{part}.xml").write_bytes(manifest)
        m = manifest.decode("utf-8", "replace")
        latest = re.search(r'_latestItem="([^"]+)"', m).group(1)
        versions = re.findall(r'<expression[^>]*label="([^"]+)"', m)
        date = latest.split("_")[0]
        xml = out / f"vreemdelingencirculaire-{part}-{date}.xml"
        url = f"{NL_REPO}/{bwb}/{latest}"
        if save(url, xml):
            (xml.with_suffix(".txt")).write_text(text_of(xml.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
            rows.append(f"{part}\t{date}\t{len(versions)} versions since {versions[0][:10]}\t{xml.name}\t{url}")
            print(f"nl: part {part} version {date} ({len(versions)} versions listed in manifest-{part}.xml)")
    (out / "index.tsv").write_text("part\tversion\thistory\tfile\tsource\n" + "\n".join(rows) + "\n", encoding="utf-8")


CMR = "https://cmr.jur.ru.nl/cmr/tbv"


def wi():
    """IND work instructions, one folder per year, from the Radboud migration law archive."""
    out = ROOT / "nl" / "werkinstructies"
    out.mkdir(parents=True, exist_ok=True)
    rows, seen = [], set()
    for year in range(2000, int(time.strftime("%Y")) + 1):
        yy = f"{year % 100:02d}"
        base = f"{CMR}/{'tbv00' if year <= 2012 else 'tbv13'}/"
        page = get(base + yy + "/")
        time.sleep(0.5)
        if page is None:
            continue
        p = page.decode("latin-1", "replace")
        for m in re.finditer(r'href="([^"]*wi[._-]?(\d{4})[^"]*\.pdf)"[^>]*>(.*?)</a>', p, flags=re.S | re.I):
            url = urllib.parse.urljoin(base, m.group(1))
            if url.lower() in seen:
                continue
            seen.add(url.lower())
            name = url.split("/")[-1].lower()
            title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(3)))).strip()
            dest = out / m.group(2) / name
            ok = dest.exists() and dest.stat().st_size > 0
            if not ok:
                # the archive is inconsistent about upper/lower case and about the year folder
                head, base_name = url.rsplit("/", 1)
                swapped = base_name.replace("wi.", "WI.", 1) if base_name.startswith("wi.") else base_name.replace("WI.", "wi.", 1)
                year_dir = f"{base}{m.group(2)[2:]}"
                candidates = [url, f"{head}/{swapped}", f"{year_dir}/{base_name}", f"{year_dir}/{swapped}",
                              f"{head}/{base_name.lower()}", f"{head}/{base_name.upper().replace('.PDF', '.pdf')}"]
                for cand in dict.fromkeys(candidates):
                    if quiet_save(cand, dest):
                        ok, url = True, cand
                        break
                    time.sleep(0.3)
            rows.append(f"{m.group(2) + '/' + name if ok else 'FAILED'}\t{title}\t{url}")
            time.sleep(0.4)
    rows.sort()
    (out / "index.tsv").write_text("file\ttitle\tsource\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"wi: {sum(not r.startswith('FAILED') for r in rows)} of {len(rows)} work instructions saved")


# --- Denmark ---------------------------------------------------------------

DK_PAGE = "https://nyidanmark.dk/da/Lovstof/Praksisnotater"


def dk():
    out = ROOT / "dk"
    out.mkdir(exist_ok=True)
    page = get(DK_PAGE)
    if page is None:
        return
    (out / "praksisnotater.html").write_bytes(page)
    p = page.decode("utf-8", "replace")
    rows, seen = [], set()
    for m in re.finditer(r'<a[^>]*href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', p, flags=re.S | re.I):
        href = html.unescape(m.group(1))
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))).strip()
        url = urllib.parse.urljoin(DK_PAGE, href)
        if url in seen:
            continue
        seen.add(url)
        name = slug(urllib.parse.unquote(url.split("/")[-1].split("?")[0]), 120)
        ok = save(urllib.parse.quote(url, safe=":/?=&%"), out / name)
        rows.append(f"{name if ok else 'FAILED'}\t{title}\t{url}")
        time.sleep(0.5)
    (out / "index.tsv").write_text("file\ttitle\tsource\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"dk: {sum(not r.startswith('FAILED') for r in rows)} of {len(rows)} practice notes saved")


# --- United Kingdom --------------------------------------------------------

UK_API = "https://www.gov.uk/api/content"
UK_START = "/government/collections/visas-and-immigration-operational-guidance"


UK_COI = "/government/collections/country-policy-and-information-notes"


def uk(start_path=UK_START, out=None, label="uk"):
    out = out or ROOT / "uk"
    out.mkdir(parents=True, exist_ok=True)
    rows, done = [], set()

    def content(path):
        data = get(UK_API + path)
        time.sleep(0.25)
        return json.loads(data) if data else None

    def document(path, folder):
        if path in done:
            return
        done.add(path)
        d = content(path)
        if not d:
            rows.append(f"FAILED\t\t\t{path}")
            return
        kind, title = d.get("document_type", ""), d.get("title", "")
        if kind == "document_collection":
            if "archive-immigration-rules" in path and "--with-rules-archive" not in sys.argv:
                # hundreds of superseded versions of the rules themselves (law, not guidance); very slow
                rows.append(f"SKIPPED\t{title}\t\thttps://www.gov.uk{path}")
                print(f"{label}: skipped {title} (pass --with-rules-archive to include)", flush=True)
                return
            sub = folder / slug(title, 70)
            for x in d.get("links", {}).get("documents", []):
                document(x["base_path"], sub)
            return
        dest = folder / slug(path.rstrip("/").split("/")[-1], 80)
        details = d.get("details", {})
        n = 0
        for a in details.get("attachments", []):
            url = a.get("url") or ""
            if not url or a.get("attachment_type") == "html":
                continue
            url = urllib.parse.urljoin("https://www.gov.uk", url)
            name = slug(urllib.parse.unquote(url.split("/")[-1]), 120)
            if save(url, dest / name):
                n += 1
                rows.append(f"{(dest / name).relative_to(out)}\t{title}\t{d.get('public_updated_at', '')[:10]}\thttps://www.gov.uk{path}")
            time.sleep(0.25)
        body = details.get("body")
        if isinstance(body, list):                      # some formats give several renderings
            body = next((b.get("content") for b in body if b.get("content_type") == "text/html"), "")
        if body and (n == 0 or kind in ("detailed_guide", "manual", "manual_section")):
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "page.html").write_text(body, encoding="utf-8")
            rows.append(f"{(dest / 'page.html').relative_to(out)}\t{title}\t{d.get('public_updated_at', '')[:10]}\thttps://www.gov.uk{path}")
        for group in details.get("child_section_groups", []):   # manuals: fetch each section
            for sec in group.get("child_sections", []):
                document(sec["base_path"], dest)
        print(f"uk: {title[:70]} ({n} files)", flush=True)

    start = content(start_path)
    if not start:
        return
    by_id = {x["content_id"]: x for x in start.get("links", {}).get("documents", [])}
    for group in start.get("details", {}).get("collection_groups", []):
        folder = out / slug(group.get("title", "other"), 60)
        for cid in group.get("documents", []):
            if cid in by_id:
                document(by_id[cid]["base_path"], folder)
        (out / "index.tsv").write_text("file\ttitle\tupdated\tsource\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"{label}: {sum(not r.startswith('FAILED') for r in rows)} files saved, {sum(r.startswith('FAILED') for r in rows)} failed")


def ukcoi():
    """UK Home Office country policy and information notes (country-of-origin information)."""
    uk(UK_COI, ROOT / "uk" / "coi", "ukcoi")


if __name__ == "__main__":
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or ["nl", "wi", "dk", "uk"]
    for name in wanted:
        {"nl": nl, "wi": wi, "dk": dk, "uk": uk, "ukcoi": ukcoi}[name]()

#!/usr/bin/env python3
"""Portugal: the little officially published guidance on immigration case handling.

    ./download_pt.py

AIMA (aima.gov.pt) publishes no circulars, service instructions or procedures
manual; neither did the SEF, with two exceptions that this script collects:

  legispedia/   "Legispédia de estrangeiros e fronteiras" (formerly "Legispédia SEF"),
                the annotated Aliens Act (Lei 23/2007) kept by the SEF legal office at
                https://sites.google.com/site/leximigratoria/ : one page per article
                with commentary, "Nota SEF" remarks, regulations and case law, plus
                annotated versions of the implementing decree and related statutes.
                Still maintained after the SEF was abolished. Saved as HTML.
  ari/          SEF "Manual de Procedimentos" for the investment residence permit
                (ARI), two editions and the summary, from the archived sef.pt
                (Arquivo.pt, the Portuguese web archive).

Files already downloaded are skipped, so the script can be re-run (pages already
on disk are re-read for their links, not fetched again).
"""
import gzip
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "pt"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
SITE = "https://sites.google.com"
PREFIX = "/site/leximigratoria"
MAX_PAGES = 1000

ARCHIVE = "https://arquivo.pt/noFrame/replay/{ts}id_/{url}"
ARI = [
    ("ari/Manual-de-Procedimentos-ARI_2015.pdf",
     "Manual de Procedimentos relativo à Autorização de Residência para Investimento (ARI)", "2015",
     "20160211062156", "http://www.sef.pt/documentos/56/Manual%20de%20Procedimentos%20ARI.pdf"),
    ("ari/Sintese-Manual-de-Procedimentos-ARI_2015.pdf",
     "Síntese do Manual de Procedimentos relativo à Autorização de Residência para Investimento (ARI)", "2015",
     "20150914141221", "http://www.sef.pt/documentos/56/Sintese_MANUAL_ARI.pdf"),
    ("ari/Manual-de-Procedimentos-ARI_2017.pdf",
     "Manual de Procedimentos relativo à Autorização de Residência para Investimento (ARI), edição de 2017", "2017",
     "20180413195025", "http://www.sef.pt/documentos/56/Manual_ARI_2017.pdf"),
]


class Blocked(Exception):
    pass


def get(url):
    """One polite request. 403/429 raise Blocked (we stop instead of retrying); other errors return None."""
    time.sleep(0.5)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return gzip.decompress(data) if r.headers.get("Content-Encoding") == "gzip" else data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"{e.code} for {url}") from e
        print(f"  FAILED {url}: {e}")
    except Exception as e:                          # noqa: BLE001 - report and carry on
        print(f"  FAILED {url}: {e}")
    return None


def norm(path):
    """Canonical form of a site path: percent-decoded, no trailing slash, query or fragment."""
    path = urllib.parse.unquote(html.unescape(path)).split("#")[0].split("?")[0].rstrip("/")
    return path if path == PREFIX or path.startswith(PREFIX + "/") else None


def file_for(path):
    rest = path[len(PREFIX):].strip("/") or "index"
    name = re.sub(r"[^\w.-]+", "-", rest.replace("/", "__")).strip("-")[:150]
    return f"legispedia/{name}.html"


def title_of(markup):
    m = re.search(r'<meta property="og:title" content="([^"]*)"', markup) or re.search(r"<title>(.*?)</title>", markup, re.S)
    t = html.unescape(m.group(1)) if m else ""
    return re.sub(r"\s+", " ", t.replace("LEGISPÉDIA de estrangeiros e fronteiras - ", "")).strip()


def legispedia(rows):
    (OUT / "legispedia").mkdir(parents=True, exist_ok=True)
    queue, seen = [PREFIX], {PREFIX}
    while queue and len(seen) <= MAX_PAGES:
        path = queue.pop(0)
        rel = file_for(path)
        dest = OUT / rel
        url = SITE + urllib.parse.quote(path)
        if dest.exists() and dest.stat().st_size > 0:
            data = dest.read_bytes()
        else:
            data = get(url)
            if data is None:
                continue
            if b"leximigratoria" not in data:
                print(f"  unexpected content, skipped: {url}")
                continue
            dest.write_bytes(data)
        markup = data.decode("utf-8", "replace")
        rows.append((rel, title_of(markup), "", url))
        for href in re.findall(r'href="(?:https://sites\.google\.com)?(/site/leximigratoria[^"]*)"', markup):
            p = norm(href)
            if p and p not in seen:
                seen.add(p)
                queue.append(p)
    if queue:
        print(f"  stopped at the {MAX_PAGES}-page limit with {len(queue)} pages left")


def ari(rows):
    (OUT / "ari").mkdir(parents=True, exist_ok=True)
    for rel, title, date, ts, url in ARI:
        dest = OUT / rel
        src = ARCHIVE.format(ts=ts, url=url)
        if not (dest.exists() and dest.stat().st_size > 0):
            data = get(src)
            if data is None or not data.startswith(b"%PDF"):
                print(f"  not saved: {src}")
                continue
            dest.write_bytes(data)
        rows.append((rel, title, date, src))


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    try:
        ari(rows)
        legispedia(rows)
    except Blocked as e:
        print(f"  BLOCKED, stopping: {e}")
    rows.sort()
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    print(f"pt: {len(rows)} files in index.tsv")


if __name__ == "__main__":
    main()

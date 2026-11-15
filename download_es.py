#!/usr/bin/env python3
"""Download Spain's published immigration-office guidance into ./es/.

    ./download_es.py            fetch listings, download what is missing, rewrite es/index.tsv
    ./download_es.py --index    only rebuild es/index.tsv from what is on disk (no network)

What it collects (Ministerio de Inclusión, Seguridad Social y Migraciones, inclusion.gob.es):
    instrucciones/          Instrucciones SEM / DGM / DGGM / DGI, 2006 onwards
    criterios-de-gestion/   "Criterios de Gestión" page next to the Instrucciones
    uge/                    Unidad de Grandes Empresas y Colectivos Estratégicos (Ley 14/2013)
    hojas-informativas/     procedure sheets for residence and work permits

Sources, in order: the live site, then the Wayback Machine copy of the same URL.
A host that answers 403 or 429 is left alone for the rest of the run: no retries,
no workarounds. Whatever could not be fetched is listed in index.tsv with an empty
"file" column, so a later run picks it up. Files already present are skipped.
Listing pages are cached in es/listings/ and reused when the network copy is unavailable.
Hojas informativas and the UGE section are web pages, so they are saved as .html.
"""
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "es"
CACHE = OUT / "listings"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
SITE = "https://www.inclusion.gob.es"
WAYBACK = "https://web.archive.org/web/2id_/"       # "2" = most recent snapshot, id_ = raw bytes
DELAY = {"web.archive.org": 6.0}                    # seconds between requests; default 0.5
MAX_FILES, MAX_BYTES = 3000, 1_000_000_000

SKIP = re.compile(r"nota[-_ ]de[-_ ]prensa|estadistic|modelos?[-_ ]de[-_ ]solicitud|formulario|/EX[-_]?\d\d|"
                  r"mi[-_]?[a-z]\b.*\.pdf$", re.I)       # press, statistics, application forms

blocked = {}        # host -> reason
failures = {}       # host -> consecutive connection failures
last_hit = {}       # host -> time of last request
saved_bytes = 0


def fetch(url):
    """One polite GET. Returns (bytes, None) or (None, reason). Never retries."""
    host = urllib.parse.urlsplit(url).netloc
    if host in blocked:
        return None, blocked[host]
    wait = DELAY.get(host, 0.5) - (time.time() - last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last_hit[host] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        failures[host] = 0
        return data, None
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            blocked[host] = f"blocked: HTTP {e.code} from {host}"
            print(f"  {host} answered {e.code}; leaving it alone for the rest of this run")
            return None, blocked[host]
        failures[host] = 0
        return None, f"HTTP {e.code}"
    except Exception as e:                          # noqa: BLE001 - report, do not retry
        failures[host] = failures.get(host, 0) + 1
        if failures[host] >= 3:                     # refusing connections: stop asking
            blocked[host] = f"unreachable: {host} failed 3 times in a row ({type(e).__name__})"
            print(f"  {host} keeps failing; leaving it alone for the rest of this run")
        return None, f"{type(e).__name__}: {e}"


def fetch_any(url):
    """Live URL first, Wayback copy second. boe.es and other hosts are fetched directly only."""
    data, why = fetch(url)
    if data is not None or "inclusion.gob.es" not in url:
        return data, why, url
    wb = WAYBACK + url
    data, why2 = fetch(wb)
    return data, (None if data is not None else f"{why}; wayback: {why2}"), wb


def clean(markup):
    t = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return re.sub(r"\s+", " ", t).strip()


def slug(s, n=80):
    s = urllib.parse.unquote(s)
    for a, b in zip("áéíóúüñÁÉÍÓÚÜÑºª", "aeiouunAEIOUUNoa"):
        s = s.replace(a, b)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n] or "x"


def content_of(page):
    """The main column of a Liferay page (leaves out the site menu and the footer)."""
    a = page.find('id="main-content"')
    b = page.find("<footer", a)
    return page[a if a > 0 else 0: b if b > 0 else None]


def absolute(href, base):
    href = html.unescape(href)
    href = re.sub(r"^https?://web\.archive\.org/web/\d+[a-z_]*/", "", href)
    return urllib.parse.urljoin(base, href)


def is_document(url):
    return "/documents/" in url or re.search(r"\.(pdf|docx?|odt)(\?|$)", url, re.I)


def items_of(page, base):
    """Yield (year, link text, full item title, absolute URL) for every link in the content."""
    body = content_of(page)
    year = ""
    for part in re.split(r"(<h[2-4][^>]*>.*?</h[2-4]>)", body, flags=re.S):
        if part.startswith("<h"):
            m = re.search(r"\b(19|20)\d\d\b", clean(part))
            year = m.group(0) if m else ""
            continue
        blocks = re.findall(r"<li[^>]*>(.*?)</li>", part, flags=re.S) or [part]
        for block in blocks:
            links = re.findall(r'<a[^>]+href="([^"#][^"]*)"[^>]*>(.*?)</a>', block, flags=re.S)
            for href, text in links:
                title = clean(block) if len(links) == 1 and len(clean(block)) < 900 else clean(text)
                yield year, clean(text), title, absolute(href, base)


def page_at(name, url, dest=None):
    """Return a page's HTML: from dest/the cache if already there, else from the network."""
    cached = dest or CACHE / f"{slug(url.split('//', 1)[1], 120)}.html"
    if not cached.exists() and "--index" not in sys.argv:
        data, why, src = fetch_any(url)
        if data is not None and b'id="main-content"' in data:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
            print(f"{name}: page from {src}")
        else:
            print(f"{name}: page NOT available ({why or 'unexpected content'})")
    if cached.exists():
        return cached.read_text("utf-8", "replace")
    return None


def canonical(url):
    url = url.split("#")[0].rstrip("/")
    return re.sub(r"^https?://(www\.)?inclusion\.gob\.es", SITE, url)


def extension(data, url):
    if data[:5] == b"%PDF-":
        return ".pdf"
    if data[:4] == b"PK\x03\x04":
        return ".docx" if "doc" in url.lower() else ".zip"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc"
    return None                                     # HTML error page or something unexpected


def download(url, folder, stem):
    """Save url as folder/stem.<ext>. Returns (relative path or '', note)."""
    global saved_bytes
    for old in folder.glob(stem + ".*"):
        if old.stat().st_size > 0:
            return str(old.relative_to(OUT)), ""
    if "--index" in sys.argv:
        return "", "not downloaded"
    if saved_bytes > MAX_BYTES or sum(1 for _ in OUT.rglob("*.*")) > MAX_FILES:
        return "", "not downloaded: size/file limit reached"
    data, why, src = fetch_any(url)
    if data is None:
        return "", why
    ext = extension(data, url)
    if ext is None:
        return "", "not a document (HTML or unknown content returned)"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / (stem + ext)
    dest.write_bytes(data)
    saved_bytes += len(data)
    print(f"  saved {dest.relative_to(OUT)} ({len(data) // 1024} kB)")
    return str(dest.relative_to(OUT)), ("" if src == url else "via Wayback Machine")


def documents(name, pages, rows, seen):
    """Download every document linked from the main column of the given (url, html) pages."""
    for base, markup in pages:
        for year, text, title, link in items_of(markup, base):
            link = canonical(link)
            if not is_document(link) or link in seen or SKIP.search(link):
                continue
            seen.add(link)
            base_name = link.split("?")[0].rstrip("/").split("/")
            base_name = base_name[-2] if re.fullmatch(r"[0-9a-f-]{36}", base_name[-1]) else base_name[-1]
            base_name = re.sub(r"\.(pdf|docx?|odt)$", "", base_name, flags=re.I)
            stem = "_".join(x for x in (year, slug(text, 45), slug(base_name, 60)) if x)
            rel, note = download(link, OUT / name, stem)
            rows.append((rel, title, year, link, note))


def flat(name, url, rows):
    """Instrucciones, Criterios de Gestion: one page that links straight to the documents."""
    page = refresh(name, url)
    if page is None:
        rows.append(("", f"[{name} listing not retrieved]", "", url, blocked_note(url)))
        return
    documents(name, [(url, page)], rows, set())


def refresh(name, url):
    """Listings change, so re-fetch them each run; fall back to the cached copy."""
    cached = CACHE / f"{slug(url.split('//', 1)[1], 120)}.html"
    if "--index" in sys.argv:
        return cached.read_text("utf-8", "replace") if cached.exists() else None
    data, why, src = fetch_any(url)
    if data is not None and b'id="main-content"' in data:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
        print(f"{name}: listing from {src}")
    elif cached.exists():
        print(f"{name}: using cached listing ({why})")
    return cached.read_text("utf-8", "replace") if cached.exists() else None


def uge(name, url, rows):
    """UGE-CE: the guidance is the web pages themselves plus linked PDFs. Crawl the section."""
    prefix = SITE + "/web/unidadgrandesempresas"
    queue, seen, pages = [(url, "Unidad de Grandes Empresas y Colectivos Estrategicos", 0)], {url}, []
    while queue:
        link, title, depth = queue.pop(0)
        tail = link[len(prefix):].strip("/") or "index"
        dest = OUT / name / f"{slug(tail, 110)}.html"
        markup = page_at(f"{name}: {title[:50]}", link, dest)
        rows.append((str(dest.relative_to(OUT)) if markup else "", title, "", link,
                     "" if markup else "page not retrieved"))
        if markup is None:
            continue
        pages.append((link, markup))
        for _, text, _, nxt in items_of(markup, link):
            nxt = canonical(nxt)
            if nxt.startswith(prefix + "/") and nxt not in seen and depth < 3 and not SKIP.search(nxt):
                seen.add(nxt)
                queue.append((nxt, text, depth + 1))
    documents(name, pages, rows, set())


def hojas(name, url, rows):
    """Hojas informativas: index -> category pages -> one web page per hoja (saved as .html)."""
    prefix = SITE + "/web/migraciones/"
    index = refresh(name, url)
    if index is None:
        rows.append(("", f"[{name} listing not retrieved]", "", url, blocked_note(url)))
        return
    categories, seen = [(url, index)], {url}
    for _, text, _, link in items_of(index, url):
        link = canonical(link)
        if link.startswith(prefix) and "/w/" not in link and link not in seen:
            seen.add(link)
            markup = page_at(f"{name}: {text[:50]}", link)
            if markup is None:
                rows.append(("", f"[category page: {text}]", "", link, "category page not retrieved"))
            else:
                categories.append((link, markup))
    for base, markup in categories:
        for _, text, _, link in items_of(markup, base):
            link = canonical(link)
            if not link.startswith(prefix + "w/") or link in seen:
                continue
            seen.add(link)
            dest = OUT / name / f"{slug(link[len(prefix) + 2:], 110)}.html"
            got = page_at(f"{name}: {text[:50]}", link, dest)
            rows.append((str(dest.relative_to(OUT)) if got else "", text, "", link,
                         "" if got else "page not retrieved"))


def blocked_note(url):
    host = urllib.parse.urlsplit(url).netloc
    return blocked.get(host, "not retrieved")


SECTIONS = {
    "instrucciones": (SITE + "/web/migraciones/instrucciones", flat),
    "criterios-de-gestion": (SITE + "/web/migraciones/criterios-de-gestion", flat),
    "uge": (SITE + "/web/unidadgrandesempresas", uge),
    "hojas-informativas": (SITE + "/web/migraciones/hojas-informativas", hojas),
}


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, (url, how) in SECTIONS.items():
        how(name, url, rows)
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tnote\n")
        for row in rows:
            f.write("\t".join(re.sub(r"[\t\r\n]+", " ", c) for c in row) + "\n")
    got = sum(1 for r in rows if r[0])
    print(f"es: {got} of {len(rows)} listed documents present; index.tsv written")
    for host, why in blocked.items():
        print(f"es: {why}")


if __name__ == "__main__":
    main()

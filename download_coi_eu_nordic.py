#!/usr/bin/env python3
"""Download country-of-origin information (COI) reports published by the EU asylum
agency and the Nordic asylum authorities - each agency's OWN reports only.

    ./download_coi_eu_nordic.py euaa   EUAA: COI reports, COI query responses, MedCOI reports and
                                       Country Guidance (euaa.europa.eu/publications, English)
    ./download_coi_eu_nordic.py no     Norway: Landinfo temanotater, responser and rapporter
    ./download_coi_eu_nordic.py se     Sweden: Migrationsverket's own country reports in Lifos
    ./download_coi_eu_nordic.py dk     Denmark: Udlaendingestyrelsen "Landerapport" publications (us.dk)
    ./download_coi_eu_nordic.py fi     Finland: Maahanmuuttovirasto country information service
                                       reports, fact-finding reports and query responses (Tellus)
    ./download_coi_eu_nordic.py        all of them, one after the other

Files go to <source>/coi/ (the EU asylum agency: eu/coi/), newest first, until that source holds 1,500 files or 500 MB
(change with --max-files / --max-mb). Files already present are skipped, so the script
can be stopped and re-run. Each folder gets an index.tsv:
file, country covered, title, date, source URL.

Requests are sequential with a pause between them. On HTTP 403 or 429 the source is
abandoned at once (nothing is retried or worked around).

Sweden: Lifos' robots.txt disallows its search pages (/sokning*), so documents are found by
looking at document numbers one by one (/dokument?documentSummaryId=N, about 2 s each);
--se-low sets how far back to look (default 44000, roughly 2020). Numbers already looked at
are remembered in se/coi/.cache/scan.jsonl; the scan log of download_se.py (se/.cache/scan.jsonl),
if present, is read too so that no page is requested twice.
"""
import argparse
import gzip
import hashlib
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def coi_dir(name):
    """Reports go to <country>/coi/; the EU asylum agency's go to eu/coi/."""
    return ROOT / ("eu" if name == "euaa" else name) / "coi"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 0.5
MAX_FILES = 1500
MAX_BYTES = 500 * 1000 * 1000


class Blocked(Exception):
    pass


class Incomplete(Exception):
    """A listing page could not be loaded: stop rather than work from half a list."""


_last = {}


def fetch(url, post=None, delay=DELAY, timeout=120, ctx=None, tries=3):
    """Return the body, or None (404 / repeated failure). Raises Blocked on 403/429."""
    host = urllib.parse.urlsplit(url).netloc
    err = None
    for attempt in range(tries):
        wait = delay - (time.time() - _last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            headers = {"User-Agent": UA, "Accept-Encoding": "gzip"}
            data = None
            if post is not None:
                data = json.dumps(post).encode()
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                body = r.read()
                return gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} for {url}")
            if e.code in (404, 410):
                return None
            err = e
        except Exception as e:                      # noqa: BLE001 - report and retry
            err = e
        finally:
            _last[host] = time.time()
        time.sleep(5 * (attempt + 1))
    print(f"  FAILED {url}: {err}", flush=True)
    return None


def geturl(url):
    """Percent-encode non-ASCII characters and spaces in a URL."""
    return urllib.parse.quote(url, safe="/:?&=%#+,;@()!$'*~[]")


def short(s):
    """A short stable key for a URL (used at the end of file names)."""
    return hashlib.md5(s.encode()).hexdigest()[:10]


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def slug(s, n=80):
    s = s.translate(str.maketrans("åäöÅÄÖéøæØÆü", "aaoAAOeoaOAu"))
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:n].rstrip("-") or "x"


def ext_of(data, name=""):
    if data[:5] == b"%PDF-" or b"%PDF-" in data[:1024]:
        return ".pdf"
    if data[:2] == b"PK":
        m = re.search(r"\.(docx|xlsx|pptx|zip)\b", name, re.I)
        return "." + m.group(1).lower() if m else ".zip"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return ".doc"
    if data[:5] == b"{\\rtf":
        return ".rtf"
    return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def run_source(name, items, total=None, ctx=None, delay=DELAY):
    """Download items (an iterable, newest first) into <name>/coi/ and write index.tsv.

    An item is a dict: key (unique, stable), date, title, country, and either urls (list of
    file URLs) or resolve (function returning that list; the answer is remembered).
    """
    out = coi_dir(name)
    cache = out / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    resolved = {k: v for k, v in load_json(cache / "resolved.json", {}).items() if v}
    have = {}
    for p in out.iterdir():
        m = re.search(r"_([A-Za-z0-9]+(?:-\d+)?)\.[a-z]+$", p.name)
        if p.is_file() and m and p.stat().st_size > 0:
            have[m.group(1)] = p
    rows, nfiles, nbytes, new, seen, done = [], 0, 0, 0, 0, 0
    oldest, stopped, first_left = "", False, ""
    try:
        for it in items:
            seen += 1
            urls = it.get("urls") or resolved.get(it["key"])
            missing = urls is None or any((f"{it['key']}-{n}" if n else it["key"]) not in have
                                          for n in range(len(urls)))
            if missing and (stopped or nfiles >= MAX_FILES or nbytes >= MAX_BYTES):
                if not stopped:
                    stopped, first_left = True, it["date"]
                if total is not None:
                    break                           # the listing knows its own size: no need to read on
                continue                            # past the cap: only count what is left
            done += 1
            if urls is None:
                urls = it["resolve"]()
                if urls:
                    resolved[it["key"]] = urls
                    save_json(cache / "resolved.json", resolved)
                else:
                    print(f"  no file found for {it['date']} {it['title'][:70]}", flush=True)
            for n, url in enumerate(urls):
                k = f"{it['key']}-{n}" if n else it["key"]
                dest = have.get(k)
                if dest is None:
                    data = fetch(geturl(url), ctx=ctx, delay=delay)
                    ext = ext_of(data, url) if data else None
                    if not ext:
                        print(f"  SKIPPED (not a document) {url}", flush=True)
                        continue
                    dest = out / f"{it['date'] or 'undated'}_{slug(it['title'])}_{k}{ext}"
                    dest.write_bytes(data)
                    have[k] = dest
                    new += 1
                    print(f"  {dest.name} ({len(data) // 1024} kB)", flush=True)
                nfiles += 1
                nbytes += dest.stat().st_size
                oldest = min(oldest or it["date"], it["date"] or oldest)
                rows.append((dest.name, it["country"], it["title"], it["date"], url))
    except Blocked as e:
        print(f"{name}: BLOCKED ({e}) - stopping this source, not retrying", flush=True)
    except Incomplete as e:
        print(f"{name}: listing incomplete ({e}) - run again later", flush=True)
    except KeyboardInterrupt:
        print(f"{name}: interrupted", flush=True)
    rows.sort(key=lambda r: r[3], reverse=True)
    with open(out / "index.tsv", "w", encoding="utf-8") as fh:
        fh.write("file\tcountry covered\ttitle\tdate\tsource URL\n")
        for row in rows:
            fh.write("\t".join(re.sub(r"\s+", " ", c) for c in row) + "\n")
    total = total() if callable(total) else total
    left = (total if total else seen) - done
    newest = rows[0][3] if rows else "-"
    msg = (f"{name}: {nfiles} files ({new} new), {nbytes / 1e6:.0f} MB, dated {oldest or '-'} to {newest}")
    if stopped:
        msg += f"; cap reached - about {max(left, 0)} older reports not fetched (from {first_left} back)"
    print(msg, flush=True)


# --- country names -----------------------------------------------------------

COUNTRIES = """Afghanistan Albania Algeria Angola Armenia Azerbaijan Bangladesh Belarus Burundi Cameroon
Chad China Colombia Cuba Djibouti Egypt Eritrea Ethiopia Gambia Georgia Ghana Guinea Haiti India Iran Iraq
Israel Jordan Kazakhstan Kenya Kosovo Kuwait Kyrgyzstan Lebanon Libya Mali Mauritania Moldova Mongolia
Morocco Myanmar Nepal Nicaragua Niger Nigeria Pakistan Palestine Peru Russia Rwanda Senegal Serbia Somalia
Sudan Syria Tajikistan Tanzania Togo Tunisia Turkey Turkmenistan Uganda Ukraine Uzbekistan Venezuela
Vietnam Yemen Zimbabwe""".split() + [
    "Democratic Republic of the Congo", "Democratic Republic of Congo", "DRC", "DR Congo", "Sri Lanka",
    "Congo (Brazzaville)", "Republic of the Congo", "Congo",
    "Saudi Arabia", "South Sudan", "Sierra Leone", "Ivory Coast", "Côte d'Ivoire", "El Salvador", "Burkina Faso",
    "Russian Federation", "Türkiye", "West Bank", "Gaza", "North Caucasus", "Chechnya", "Kurdistan Region of Iraq",
    "Irak", "Syrien", "Rusland", "Ryssland", "Tyrkiet", "Turkiet", "Libanon", "Etiopien", "Marokko", "Marocko",
    "Algeriet", "Tunesien", "Tunisien", "Egypten", "Jemen", "Usbekistan", "Georgien", "Armenien", "Indien",
    "Kina", "Libyen", "Ukraina", "Hviderusland", "Belarus", "Västbanken", "Vestbredden", "Palæstina",
    "Demokratiska republiken Kongo", "Demokratiske Republik Congo", "Kamerun", "Kenia", "Colombia", "Cuba",
    "Kuba", "Kirgizistan", "Kazakstan", "Tadzjikistan", "Azerbajdzjan", "Aserbajdsjan", "Mongoliet", "Serbien",
    "Albanien", "Nordkaukasus", "Tjetjenien", "Sydsudan", "Burma", "Stateless", "Bidoon", "Kuwait"]
_COUNTRY_RE = re.compile(r"(?<![A-Za-zÀ-ÿ])(" + "|".join(sorted(map(re.escape, COUNTRIES), key=len, reverse=True))
                         + r")(?:s|ns|'s)?(?![A-Za-zÀ-ÿ])")
_PREFIX_RE = re.compile(r"^\s*(COI Query Response|COI Query|COI Report|EASO COI Report|EUAA COI Report|MedCOI[^:–-]*"
                        r"|Interim Country Guidance|Country Guidance|Country Focus|Landinformation|Lifosrapport"
                        r"|Temarapport|Rapport|Report|Brief report|Lägesanalys|Landrapport)\s*[:.–-]+\s*", re.I)


def country_of(title):
    """Best-effort country (or countries) named in a report title; '' if none is recognised."""
    t = _PREFIX_RE.sub("", title)
    found = []
    for m in _COUNTRY_RE.finditer(t):
        if m.group(1) not in found:
            found.append(m.group(1))
    if found:
        return ", ".join(found[:4])
    m = re.match(r"\s*([A-ZÀ-Þ][\w'’.-]+(?: (?:and |of |the |[A-ZÀ-Þ])[\w'’.-]+){0,3})\s*(?::| [–-] |, |\. )", t)
    return m.group(1) if m else ""


# --- EUAA --------------------------------------------------------------------

EUAA = "https://www.euaa.europa.eu/publications"
EUAA_CATS = {"15181": "Country of Origin Information", "15105": "Country Guidance", "15383": "MedCOI"}


def euaa_items():
    cache = coi_dir("euaa") / ".cache" / "listing.json"       # the listing is slow (about 45 pages): keep it a day
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        return load_json(cache, [])
    items, seen = [], set()
    for cat, label in EUAA_CATS.items():
        page = 0
        while True:
            body = fetch(f"{EUAA}?field_category_target_id={cat}&language=en&field_geo_coverage_target_id="
                         f"&field_keywords_target_id=&title=&page={page}")
            if body is None:
                raise Incomplete(f"{label} page {page + 1}")
            panels = body.decode("utf-8", "replace").split("euaa-panel--publication")[1:]
            for b in panels:
                d = re.search(r'datetime="(\d{4}-\d\d-\d\d)', b)
                t = re.search(r'<h3><a href="([^"]+)">(.*?)</a>', b, re.S)
                f = re.search(r'href="([^"]+)"[^>]*>\s*Download', b)
                if not (t and f) or f.group(1) in seen:
                    continue
                seen.add(f.group(1))
                title = clean(t.group(2))
                items.append({"key": short(f.group(1)),
                              "date": d.group(1) if d else "", "title": title, "country": country_of(title),
                              "urls": [html.unescape(f.group(1))]})
            print(f"euaa: {label} page {page + 1}: {len(panels)} publications", flush=True)
            if not panels:
                break
            page += 1
    items.sort(key=lambda i: i["date"], reverse=True)
    save_json(cache, items)
    return items


def euaa():
    run_source("euaa", euaa_items())


# --- Norway: Landinfo --------------------------------------------------------

NO_API = "https://landinfo.no/wp-json/o7/v1/articles"       # the list the site's own publication page loads


def no_items():
    cache = coi_dir("no") / ".cache" / "articles.json"
    if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
        body = fetch(NO_API, timeout=900)          # one large (about 5 MB) and slow response
        if body is None:
            sys.exit("no: could not load the Landinfo publication list")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(body)
    arts = json.loads(cache.read_text(encoding="utf-8"))
    lang = lambda a: {x["name"] for x in (a.get("languages") or [])}                 # noqa: E731
    is_en = lambda a: bool(lang(a) & {"Engelsk", "English"})                        # noqa: E731
    summ = lambda a: re.sub(r"\W+", "", (a.get("summary_no") or "").lower())[:60]    # noqa: E731
    cset = lambda a: {c["slug"].rstrip("-0123456789") for c in (a.get("countries") or [])}   # noqa: E731
    # Every publication is listed twice (Norwegian and English site view) with the same file.
    by_file = {}
    for a in arts:
        if not a.get("pdf") or re.match(r"\s*Årsrapport", a["title"]):               # annual reports are not COI
            continue
        e = by_file.setdefault(a["pdf"], {"nb": None, "en": None})
        e["en" if "/en/" in a["permalink"] else "nb"] = a
    # An English publication that repeats the Norwegian summary of a Norwegian-language
    # publication on the same country is a translation: keep the Norwegian original only.
    originals = {}
    for e in by_file.values():
        a = e["nb"] or e["en"]
        if not is_en(a) and summ(a):
            originals.setdefault(summ(a), set()).update(cset(a))
    items = []
    for url, e in by_file.items():
        a = e["nb"] or e["en"]
        if is_en(a) and len(summ(a)) >= 25 and originals.get(summ(a), set()) & cset(a):
            continue
        d, m, y = a["publish_date"].split("/")
        names = [c["title"] for c in ((e["en"] or a).get("countries") or [])]
        items.append({"key": str(a["id"]), "date": f"{y}-{m}-{d}", "title": clean(a["title"]),
                      "country": ", ".join(dict.fromkeys(names)), "urls": [url]})
    items.sort(key=lambda i: i["date"], reverse=True)
    print(f"no: {len(items)} Landinfo publications listed ({len(by_file) - len(items)} English translations "
          f"of Norwegian reports left out)", flush=True)
    return items


def no():
    run_source("no", no_items())


# --- Denmark: Udlaendingestyrelsen -------------------------------------------

DK_LIST = "https://us.dk/publikationer/?categorizations=5130&pageNumber={}"      # 5130 = Landerapport


def dk_items():
    items, page = [], 1
    while True:
        body = fetch(DK_LIST.format(page))
        if body is None:
            raise Incomplete(f"list page {page}")
        found = re.findall(r'results-item__inner-link" href="([^"]+)">(.*?)</a>.*?<time datetime="([\d-]+)"',
                           body.decode("utf-8", "replace"), re.S)
        if not found:
            break
        for href, title, date in found:
            href = html.unescape(href)
            title = clean(title)

            def resolve(href=href):
                p = (fetch(geturl(href)) or b"").decode("utf-8", "replace")
                p = p.split('<main', 1)[-1].split('<footer', 1)[0]
                links = re.findall(r'href="([^"]+\.(?:pdf|docx?)(?:\?[^"]*)?)"', p, re.I)
                return list(dict.fromkeys(urllib.parse.urljoin(href, html.unescape(x)) for x in links))
            items.append({"key": short(href), "date": date, "title": title,
                          "country": country_of(title), "resolve": resolve})
        print(f"dk: list page {page}: {len(found)} publications", flush=True)
        page += 1
    items.sort(key=lambda i: i["date"], reverse=True)
    return items


def dk():
    run_source("dk", dk_items())


# --- Finland: Maahanmuuttovirasto, Tellus country information database ----------

FI = "https://maatieto.migri.fi"
FI_TYPES = [("5531eeb0-71dd-44b9-8c34-cc759a4fcc72", "fact-finding mission reports"),
            ("f914fc1e-c0ee-4af1-92b9-c6069c8235dd", "country information service reports"),
            ("5ab58cf1-fa51-484a-b5a1-77dc2822360d", "country information service query responses")]
FI_PAGE = 20
_fi_total = {}


def fi_pages(guid, label):
    """Yield items of one Tellus document type, in the order the database lists them (newest first)."""
    page = 1
    while True:
        body = fetch(f"{FI}/api/Migri/1.0/search", post={"Page": page, "ResultsPerPage": FI_PAGE, "DocumentType": guid},
                     timeout=600)                   # slow: every result carries the document's full text
        if body is None:
            raise Incomplete(f"{label}, list page {page}")
        d = json.loads(body)
        _fi_total[guid] = d.get("totalResults", 0)
        print(f"fi: {label}: list page {page} of {d.get('totalPages')}", flush=True)
        for r in d.get("results") or []:
            val = lambda k: (r.get(k) or {}).get("value")                            # noqa: E731
            pubs = [p.get("name", "") for p in (val("publishers") or [])]
            if pubs and not any("Migri" in p or "Maahanmuuttovirasto" in p for p in pubs):
                continue                                                             # not the agency's own
            atts = [a["contentLink"]["id"] for a in (val("attachments") or []) if a.get("contentLink")]
            title = clean(val("title") or r.get("name") or "")
            date = val("publishDate") or r.get("startPublish") or ""
            if re.match(r"\d{4}-\d\d-\d\dT2[0-3]", date):       # local midnight written in UTC: the next day
                date = time.strftime("%Y-%m-%d", time.gmtime(time.mktime(time.strptime(date[:10], "%Y-%m-%d")) + 129600))
            yield {"key": str(r["contentLink"]["id"]), "date": date[:10],
                   "title": title, "country": ", ".join(c["name"] for c in (val("country") or [])),
                   "atts": atts}
        if page >= (d.get("totalPages") or 0):
            return
        page += 1


def fi_resolver(atts):
    def resolve():
        urls = []
        for a in atts:
            meta = fetch(f"{FI}/api/episerver/v2.0/content/{a}")
            u = (json.loads(meta).get("url") or "") if meta else ""
            if u:
                urls.append(urllib.parse.urljoin(FI, u))
        return urls
    return resolve


def fi_items():
    # Reports first (all of them, newest first), then query responses for as long as the cap allows.
    cache = coi_dir("fi") / ".cache" / "reports.json"          # that listing takes about half an hour: keep it a day
    saved = load_json(cache, None) if cache.exists() and time.time() - cache.stat().st_mtime < 86400 else None
    if saved:
        reports, totals = saved
        _fi_total.update(totals)
    else:
        reports = [i for guid, label in FI_TYPES[:2] for i in fi_pages(guid, label)]
        reports.sort(key=lambda i: i["date"], reverse=True)
        save_json(cache, [reports, _fi_total])
    for it in reports:
        yield {**it, "resolve": fi_resolver(it["atts"])}
    for it in fi_pages(*FI_TYPES[2]):
        yield {**it, "resolve": fi_resolver(it["atts"])}


def fi():
    run_source("fi", fi_items(), total=lambda: sum(_fi_total.values()))


# --- Sweden: Migrationsverket, Lifos -------------------------------------------

SE = "https://lifos.migrationsverket.se"
SE_DELAY = 1.0
SE_OTHER_SCAN = ROOT / "se" / ".cache" / "scan.jsonl"       # written by download_se.py; only read here
# Lifos' certificate chain ends at "ISRG Root YR", which older trust stores lack. Let's Encrypt
# publishes that root cross-signed by ISRG Root X1; it is fetched (over normally verified TLS)
# and added as an extra CA. Verification is never switched off.
SE_CROSS_ROOT = "https://letsencrypt.org/certs/gen-y/root-yr-by-x1.pem"
SE_OWN = re.compile(r"Migrationsanalys|Lifos\b|Landinformationsenheten|land- och omvärldsanalys", re.I)
SE_LEGAL = re.compile(r"^\s*(Rätts|Styrsignal|Handbok|Test\s*$|Migrationsöverdomstolen|EU-domstolen|Europadomstolen)", re.I)


def se_ctx():
    ctx = ssl.create_default_context()
    try:
        urllib.request.urlopen(urllib.request.Request(SE + "/robots.txt", headers={"User-Agent": UA}),
                               timeout=60, context=ctx)
        return ctx
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} for {SE}")
        return ctx
    except urllib.error.URLError as e:
        if not isinstance(e.reason, ssl.SSLCertVerificationError):
            raise
    pem = coi_dir("se") / ".cache" / "root-yr-by-x1.pem"
    if not pem.exists():
        data = fetch(SE_CROSS_ROOT)                 # system trust store
        if not data or b"BEGIN CERTIFICATE" not in data:
            sys.exit("se: could not get Let's Encrypt's cross-signed root")
        pem.write_bytes(data)
    ctx.load_verify_locations(cafile=str(pem))
    return ctx


def se_parse(page):
    t = page.decode("utf-8", "replace")
    g = lambda rx: (re.search(rx, t, re.S) or [None, ""])[1]      # noqa: E731
    return {"title": clean(g(r'class="DocumentHeader">(.*?)</div>')),
            "date": clean(g(r'Upphovsdat: </div><div class="metadataDisplayRightColumn">([^<]*)')),
            "source": clean(g(r"Referens:.*?<b>(.*?)<div")).rstrip(", "),
            "subjects": clean(g(r'id="metadataDisplaySubjectword">(.*?)</div>')),
            "att": [[int(a), clean(n)] for a, n in
                    re.findall(r'href="/dokument\?documentAttachmentId=(\d+)"[^>]*>([^<]*)', t)]}


def se_read(path, recs):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                recs.setdefault(r["id"], r)
            except (ValueError, KeyError):
                pass


def se_own(r):
    """Is this Lifos record one of Migrationsverket's own country reports?"""
    src, title = r.get("source", ""), r.get("title", "")
    own = SE_OWN.search(src) or ("Migrationsverket" in src and (          # some are filed under the agency only
        re.match(r"\s*(Landinformation|Lifosrapport|Lägesanalys)", title) or "Udlændinge" in src))
    if r.get("status") != 200 or not own or SE_LEGAL.match(title):
        return False
    subj = r.get("subjects", "")
    return not re.search(r"\bPraxis\b|Rättsliga ställningstaganden|Styrsignal", subj)


def se(low=44000):
    out = coi_dir("se")
    scan = out / ".cache" / "scan.jsonl"
    scan.parent.mkdir(parents=True, exist_ok=True)
    recs = {}
    se_read(scan, recs)
    se_read(SE_OTHER_SCAN, recs)
    ctx = None
    try:
        ctx = se_ctx()
        body = fetch(SE + "/lifos-aktuellt.html", ctx=ctx, delay=SE_DELAY)
        ids = [int(x) for x in re.findall(rb"documentSummaryId=(\d+)", body or b"")]
        high = max(ids + list(recs) + [low]) + (30 if ids else 0)
        # If download_se.py is scanning downwards right now, work upwards and meet it; otherwise newest first.
        other_active = SE_OTHER_SCAN.exists() and time.time() - SE_OTHER_SCAN.stat().st_mtime < 900
        order = range(low, high + 1) if other_active else range(high, low - 1, -1)
        print(f"se: looking at document numbers {order[0]}..{order[-1]} ({len(recs)} already known)", flush=True)
        n = 0
        with open(scan, "a", encoding="utf-8") as log:
            for i in order:
                if i in recs and not (recs[i]["status"] == 404 and i > high - 60):
                    continue
                if n % 20 == 0:
                    se_read(SE_OTHER_SCAN, recs)
                    if i in recs:
                        continue
                n += 1
                try:
                    wait = SE_DELAY - (time.time() - _last.get("lifos.migrationsverket.se", 0))
                    if wait > 0:
                        time.sleep(wait)
                    req = urllib.request.Request(f"{SE}/dokument?documentSummaryId={i}",
                                                 headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
                    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
                        page = resp.read()
                        if resp.headers.get("Content-Encoding") == "gzip":
                            page = gzip.decompress(page)
                        r = {"id": i, "status": 200, **se_parse(page)}
                except urllib.error.HTTPError as e:
                    if e.code in (403, 429):
                        raise Blocked(f"HTTP {e.code} at document {i}")
                    r = {"id": i, "status": e.code}
                except Exception as e:              # noqa: BLE001 - leave the number for the next run
                    print(f"  FAILED {i}: {e}", flush=True)
                    time.sleep(10)
                    continue
                finally:
                    _last["lifos.migrationsverket.se"] = time.time()
                recs[i] = r
                log.write(json.dumps(r, ensure_ascii=False) + "\n")
                log.flush()
                if se_own(r):
                    print(f"  found {i} {r['date']} {r['title'][:90]}", flush=True)
    except Blocked as e:
        print(f"se: BLOCKED while scanning ({e}) - not retrying; saving what is known so far", flush=True)
        ctx = None
    except KeyboardInterrupt:
        print("se: scan interrupted", flush=True)
    se_read(SE_OTHER_SCAN, recs)
    looked = sorted(i for i in recs if i >= low)
    items = []
    for i in sorted(recs, reverse=True):
        r = recs[i]
        if se_own(r) and r["att"]:
            title = r["title"]
            items.append({"key": str(i), "date": r["date"], "title": title, "country": country_of(title),
                          "urls": [f"{SE}/dokument?documentAttachmentId={a}" for a, _n in r["att"]]})
    items.sort(key=lambda it: it["date"], reverse=True)
    print(f"se: {len(looked)} document numbers looked at between {low} and {max(looked) if looked else '-'}; "
          f"{len(items)} own country reports among them", flush=True)
    if ctx is None:
        items = [it for it in items if list(out.glob(f"*_{it['key']}.*"))]         # blocked: index only
    run_source("se", items, ctx=ctx, delay=SE_DELAY)


SOURCES = {"euaa": euaa, "no": no, "se": se, "dk": dk, "fi": fi}


def main():
    global MAX_FILES, MAX_BYTES
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", choices=[*SOURCES, []], help="which sources (default: all)")
    ap.add_argument("--max-files", type=int, default=MAX_FILES, help="cap per source (default 1500)")
    ap.add_argument("--max-mb", type=int, default=MAX_BYTES // 1000000, help="cap per source in MB (default 500)")
    ap.add_argument("--se-low", type=int, default=44000, help="Sweden: lowest Lifos document number to look at")
    a = ap.parse_args()
    MAX_FILES, MAX_BYTES = a.max_files, a.max_mb * 1000000
    for name in a.sources or list(SOURCES):
        try:
            if name == "se":
                se(a.se_low)
            else:
                SOURCES[name]()
        except Blocked as e:
            print(f"{name}: BLOCKED ({e}) - stopping this source, not retrying", flush=True)
        except Incomplete as e:
            print(f"{name}: listing incomplete ({e}) - nothing changed, run again later", flush=True)


if __name__ == "__main__":
    main()

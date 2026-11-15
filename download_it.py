#!/usr/bin/env python3
"""Download Italian Interior Ministry circolari on immigration, asylum and citizenship.

    python3 download_it.py

Italy has no single immigration-office manual; guidance is issued as individual
circolari. This script walks three official listings and saves the attached
documents (mostly PDF) into ./it/ :

  interno  www.interno.gov.it  Amministrazione trasparente > Circolari (2010 onwards)
  dlci     libertaciviliimmigrazione.dlci.interno.gov.it  Documentazione > Circolari
  storico  www1.interno.gov.it  historical archive of circolari (roughly 2000-2013)

Only items whose title/summary match immigration keywords are kept. Where a
listed item has no attachment, its web page is saved as .html instead.
Files already downloaded are skipped, so the script can be re-run; it/index.tsv
is rebuilt on every run. Standard library only, sequential, 0.4 s between requests.
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
OUT = ROOT / "it"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 0.4
MAX_BYTES = 1_000_000_000
MAX_FILES = 3000

INTERNO = ("https://www.interno.gov.it/it/amministrazione-trasparente/disposizioni-generali/"
           "atti-generali/atti-amministrativi-generali/circolari")
DLCI = "https://libertaciviliimmigrazione.dlci.interno.gov.it/documentazione/circolari"
STORICO = "https://www1.interno.gov.it/mininterno/export/sites/default/it/sezioni/servizi/_circolari/"
STORICO_SECTIONS = ["dip_immigrazione", "dip_pubblica_sicurezza", "ministero_interno",
                    "ministero_altri", "uffici_territoriali_governo"]

KEEP = re.compile(
    r"immigra|stranier|soggiorn|flussi|cittadinanza|asilo\b|protezione internazionale|protezione temporanea"
    r"|rifugiat|migrant|migrator|richiedenti|ricongiung|rimpatri|espulsion|respingiment|non comunitar"
    r"|extracomunitar|neocomunitar|ucrain|apolid|sportello unico|frontier|\bvisti\b|\bvisto\b|iure sanguinis"
    r"|trattenimento|accordo d.integrazione|emersione|carta blu|blu card|dublino|msna|paesi terzi"
    r"|cittadini comunitari|cittadini dell.unione|nulla osta|centri di (prima )?accoglienza|capitolato"
    r"|sprar|umanitari|schengen|rumen|bulgar|croazia|lavoratori altamente qualificati|ricerca scientifica"
    r"|\bcie\b|\bcpr\b|identificazione ed espulsione|permanenza per i rimpatri", re.I)
DROP = re.compile(
    r"protocollo d.intesa tra|siglato un protocollo|stipulato un protocollo|naufragi|plaude|presidenza italiana"
    r"|numero verde|personalit. giuridica|calendario delle festivit|avviso pubblico|esito dell.avviso"
    r"|servizio civile|vittime d|persone scomparse|spaccio|culto|patronato|beni confiscati|buone pratiche"
    r"|pi. sostegno nel mediterraneo|e bosla|basta un click|con un click|quarto rapporto"
    r"|istituita ad|operativa a |coronavirus|corona virus|unioni civili", re.I)

MONTHS = {m: i + 1 for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split())}

blocked = {}      # host -> reason; once a host answers 403/429 we stop asking it
failures = []
stats = {"new": 0, "bytes": 0}


def get(url, tries=2):
    """Return (bytes, content_type) or (None, None)."""
    host = urllib.parse.urlsplit(url).netloc
    if host in blocked:
        return None, None
    err = None
    for attempt in range(tries):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            err = e
            if e.code in (403, 429):
                blocked[host] = f"HTTP {e.code} on {url}"
                print(f"  BLOCKED by {host} (HTTP {e.code}); not asking this host again")
                return None, None
            if e.code in (404, 410):
                break
        except Exception as e:                      # noqa: BLE001 - report and retry once
            err = e
        time.sleep(3)
    print(f"  FAILED {url}: {err}")
    failures.append((url, str(err)))
    return None, None


def page(url):
    data, _ = get(url)
    return data.decode("utf-8", "replace") if data else ""


def text_of(markup):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S)
    t = html.unescape(html.unescape(re.sub(r"<[^>]+>", " ", t)))
    return re.sub(r"\s+", " ", t).strip()


def slug(s, n=70):
    s = urllib.parse.unquote(s)
    for a, b in zip("àèéìòùÀÈÉÌÒÙ’", "aeeiouAEEIOU-"):
        s = s.replace(a, b)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n].strip("-.") or "x"


def quote_url(u):
    parts = urllib.parse.urlsplit(u)
    return urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path, safe="/%")))


def date_in(s):
    """Best-effort date of the circular as written in its title; '' if none."""
    m = re.search(r"\b(\d{1,2})[°º]?\s+(%s)\s+(\d{4})" % "|".join(MONTHS), s, re.I)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d\d)\b", s)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(1)) <= 31:
        return "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1)))
    return ""


def wanted(*texts):
    t = " ".join(x for x in texts if x)
    return bool(KEEP.search(t)) and not DROP.search(t)


# ---- listings: each yields dicts {src, title, date, page, files:[(url,label)]} -------------

def interno_attachments(markup):
    return [(urllib.parse.urljoin(INTERNO, html.unescape(u)), text_of(lbl))
            for u, lbl in re.findall(r'<a href="(/sites/default/files/[^"]+)"[^>]*>(.*?)</a>', markup, flags=re.S)]


def list_interno():
    items = []
    for p in range(0, 60):
        h = page(f"{INTERNO}?page={p}%2C0")
        n = 0
        for row in h.split('<div class="views-row">')[1:]:
            t = re.search(r'views-field-title"><span class="field-content"><a href="([^"]+)"[^>]*>(.*?)</a>', row, flags=re.S)
            if not t:
                continue
            n += 1
            title = text_of(t.group(2))
            dep = re.search(r'riferimento: </strong><span class="field-content">(.*?)</span>', row, flags=re.S)
            dep = text_of(dep.group(1)) if dep else ""
            if dep.startswith("Commissario") or not wanted(title):
                continue
            d = re.search(r'datetime="(\d{4}-\d\d-\d\d)', row)
            items.append({"src": "interno", "title": title, "date": d.group(1) if d else date_in(title),
                          "page": urllib.parse.urljoin(INTERNO, t.group(1)), "files": interno_attachments(row)})
        if not n:
            break
    print(f"interno.gov.it: {len(items)} relevant circolari")
    return items


def list_dlci():
    items, seen = [], set()
    for p in range(0, 60):
        h = page(f"{DLCI}?page={p}")
        cards = re.findall(r'(\d\d)/(\d\d)/(\d{4})\s*<h2 class="card-title[^>]*><a href="([^"]+)"[^>]*><span>(.*?)</span>'
                           r'</a></h2><div class="card-text[^>]*>(.*?)</div>', h, flags=re.S)
        if not cards:
            break
        for dd, mm, yy, href, title, teaser in cards:
            url = urllib.parse.urljoin(DLCI, href.replace("/index.php/", "/"))
            title, teaser = text_of(title), text_of(teaser)
            if url in seen or not wanted(title, teaser):
                continue
            seen.add(url)
            pub = f"{yy}-{mm}-{dd}"
            # 16-17 April 2025 is when old content was bulk-migrated to the new site, not a real date
            date = date_in(title) or date_in(teaser) or ("" if pub in ("2025-04-16", "2025-04-17") else pub)
            items.append({"src": "dlci", "title": title, "date": date, "page": url, "files": None})
    print(f"DLCI site: {len(items)} relevant items")
    return items


def dlci_detail(item):
    """Fill item['files'] from its detail page; returns the page markup."""
    h = page(item["page"])
    body = h[h.find("<article"):h.find("</main")] if "<article" in h else h
    files = []
    for u, lbl in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.S):
        u = html.unescape(u)
        if "/sites/default/files/" in u and not re.search(r"\.(jpe?g|png|gif|webp|svg)(\?|$)", u, re.I):
            files.append((urllib.parse.urljoin(item["page"], u), text_of(lbl)))
        elif "interno.gov.it/" in u and "/circolari/" in u and "dlci.interno" not in u:
            files += interno_attachments(page(u))          # circular published on the ministry site
    item["files"] = list(dict.fromkeys(files))
    return h


def list_storico():
    items, seen_items = [], set()
    for sec in STORICO_SECTIONS:
        base = STORICO + sec + "/"
        todo, seen_idx, n = [base], set(), 0
        while todo:
            idx = todo.pop(0)
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            h = page(idx)
            for more in re.findall(r'href="([^"]*/_circolari/%s/index\.html_\d+\.html)"' % sec, h):
                more = urllib.parse.urljoin(idx, more)
                if more not in seen_idx:
                    todo.append(more)
            for href, title, desc in re.findall(
                    r'<tr><td>\s*<a href="([^"]+)">(.*?)</a><br\s*/?>(.*?)</td>', h, flags=re.S):
                url = urllib.parse.urljoin(idx, re.sub(r"\.html_\d+\.html$", ".html", href))
                title, desc = text_of(title), text_of(desc)
                if url in seen_items:
                    continue
                seen_items.add(url)
                # the immigration department's own section is kept unless clearly off-topic
                keep = wanted(title, desc) or (sec == "dip_immigrazione" and not DROP.search(title + " " + desc)
                                               and not re.search(r"culti|religios|minoranz|vittime", title + desc, re.I))
                if keep:
                    n += 1
                    items.append({"src": "storico", "title": (title + ". " + desc).strip(". ")[:300],
                                  "date": date_in(title) or date_in(desc) or date_in(href.replace("_", ".")),
                                  "page": url, "files": None})
        print(f"historical archive, {sec}: {n} relevant items on {len(seen_idx)} index pages")
    return items


def storico_detail(item):
    h = page(item["page"])
    files = [(urllib.parse.urljoin(item["page"], html.unescape(u)), text_of(lbl))
             for u, lbl in re.findall(r'<a[^>]*href="([^"]*/assets/files/[^"]+)"[^>]*>(.*?)</a>', h, flags=re.S)]
    seen, out = set(), []
    for u, lbl in files:                         # each link appears twice (icon + text); keep the labelled one
        if u not in seen and lbl:
            seen.add(u)
            out.append((u, lbl))
    for u, lbl in files:
        if u not in seen:
            seen.add(u)
            out.append((u, lbl))
    item["files"] = out
    return h


# ---- saving -----------------------------------------------------------------------------

def looks_wrong(name, data):
    head = data[:600].lstrip().lower()
    if name.lower().endswith(".pdf"):
        return b"%pdf" not in data[:1024].lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    existing = [f for f in OUT.iterdir() if f.is_file() and f.name != "index.tsv"]
    total_bytes = sum(f.stat().st_size for f in existing)
    total_files = len(existing)
    rows, by_url, left = [], {}, 0

    items = list_interno() + list_dlci() + list_storico()
    for n, it in enumerate(items, 1):
        prefix = f"{it['src']}_{it['date'] or 'nodate'}_{slug(it['title'], 60)}"
        if it["files"] is None:
            # detail page needed to find the attachments; skip the request if a page-only copy exists
            page_copy = OUT / (prefix + ".html")
            if page_copy.exists():
                rows.append((page_copy.name, it["title"], it["date"], it["page"]))
                continue
            markup = (dlci_detail if it["src"] == "dlci" else storico_detail)(it)
            if not markup:
                continue
            if not it["files"]:
                if total_bytes < MAX_BYTES and total_files < MAX_FILES:
                    page_copy.write_text(markup, encoding="utf-8")
                    total_bytes += page_copy.stat().st_size
                    total_files += 1
                    stats["new"] += 1
                    rows.append((page_copy.name, it["title"], it["date"], it["page"]))
                else:
                    left += 1
                continue
        for url, label in it["files"]:
            url = quote_url(url)
            if url in by_url:                      # same document listed on two sites
                continue
            base = slug(url.rsplit("/", 1)[-1].split("?")[0], 80)
            dest = OUT / f"{prefix}_{base}"
            title = it["title"] + (f" [{label}]" if label and label.lower() not in it["title"].lower() else "")
            if not (dest.exists() and dest.stat().st_size > 0):
                if total_bytes >= MAX_BYTES or total_files >= MAX_FILES:
                    left += 1
                    continue
                data, _ = get(url)
                if data is None:
                    continue
                if looks_wrong(dest.name, data):
                    print(f"  NOT A DOCUMENT (skipped) {url}")
                    failures.append((url, "response was not the expected document"))
                    continue
                dest.write_bytes(data)
                total_bytes += len(data)
                total_files += 1
                stats["new"] += 1
                stats["bytes"] += len(data)
            by_url[url] = dest.name
            rows.append((dest.name, title, it["date"], url))
        if n % 25 == 0:
            print(f"  {n}/{len(items)} items, {total_files} files, {total_bytes / 1e6:.0f} MB")

    rows.sort(key=lambda r: (r[2] or "0000", r[0]))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource URL\n")
        for r in rows:
            f.write("\t".join(re.sub(r"[\t\r\n]+", " ", c) for c in r) + "\n")

    print(f"\n{len(rows)} files indexed ({stats['new']} new this run), {total_bytes / 1e6:.1f} MB in {OUT}")
    if left:
        print(f"{left} documents NOT downloaded because the size/file limit was reached")
    for host, why in blocked.items():
        print(f"blocked: {host}: {why}")
    if failures:
        print(f"{len(failures)} failures:")
        for u, e in failures:
            print(f"  {u}: {e}")
    return 1 if (failures or blocked or left) else 0


if __name__ == "__main__":
    sys.exit(main())

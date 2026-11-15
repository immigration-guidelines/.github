#!/usr/bin/env python3
"""Download Belgian immigration circulars (circulaires / omzendbrieven) into ./be/

    python3 download_be.py

Belgium has no single procedures manual: the Immigration Office (Office des
étrangers / Dienst Vreemdelingenzaken) and the responsible ministers issue
circulars, mostly addressed to the municipalities, which are published in the
Moniteur belge / Belgisch Staatsblad.  The Office's own collection for
municipalities (gemcom.ibz.be) is behind an eID login, and dofi.ibz.be has no
public list of circulars, so this script uses the official gazette database:

  1. Search the Moniteur belge (www.ejustice.just.fgov.be/cgi/) for documents
     of type "Circulaire" with immigration words in the title or citing the
     Aliens Act of 15 December 1980, plus the Justel consolidated-legislation
     database (cgi_loi/) for "CIRCULAIRE MINISTERIELLE".
  2. Keep the titles that are about residence, registration, family
     reunification, work, students, EU citizens, regularisation, removal ...
     (see INC / EXC below); drop German translations and unrelated hits.
  3. Per document save ONE language: the French text as published in the
     Moniteur (Dutch if there is no French text; the Justel page if the
     Moniteur has no text at all).  If Justel holds a consolidated version that
     was amended later, that version is saved too (*_consolidated.html).
  4. Texts published before 1 June 1997 exist only as scans: the PDF of that
     day's Moniteur issue is saved under be/moniteur_pdf/ and the index gives
     the page to open.

Files already present are skipped, so the script can be re-run; the searches
are always repeated (about 40 requests) to pick up new circulars.
be/index.tsv lists what was saved, be/not_saved.tsv what could not be.
"""
import html
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "be"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
SITE = "https://www.ejustice.just.fgov.be"
DELAY = float(os.environ.get("BE_DELAY", "2.0"))  # seconds between requests (the server answered 429 at 0.5 s after ~350 requests)
RETRY_BLOCKED = "--retry-blocked" in sys.argv
BLOCK_BACKOFF = [int(x) for x in os.environ.get("BE_BACKOFF", "120,600,1800,3600").split(",")]
if "--delay" in sys.argv:
    DELAY = float(sys.argv[sys.argv.index("--delay") + 1])
MAX_BYTES = 1_000_000_000        # stop at roughly 1 GB ...
MAX_FILES = 3000                 # ... or 3,000 files


class Blocked(Exception):
    pass


_last = [0.0]


def get(url, tries=None):
    """Polite GET. Returns bytes, or None on failure. 403/429 stop the run unless --retry-blocked."""
    if tries is None:
        tries = 1 + len(BLOCK_BACKOFF) if RETRY_BLOCKED else 2
    err = None
    for attempt in range(tries):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            _last[0] = time.time()
            return data
        except urllib.error.HTTPError as e:
            _last[0] = time.time()
            if e.code in (403, 429):
                if not RETRY_BLOCKED or attempt == tries - 1:
                    raise Blocked(f"{e.code} for {url}")
                pause = BLOCK_BACKOFF[min(attempt, len(BLOCK_BACKOFF) - 1)]
                print(f"  {e.code} for {url}; waiting {pause}s (attempt {attempt + 1}/{tries})", flush=True)
                time.sleep(pause)
                continue
            err = e
            if e.code == 404:
                break
        except Exception as e:                      # noqa: BLE001 - report and retry once
            _last[0] = time.time()
            err = e
        time.sleep(5)
    print(f"  FAILED {url}: {err}")
    return None


def plain(markup):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()


def fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


# ---------------------------------------------------------------- selection

INC = (r"etranger|sejour|ressortissant|eloignement|asile|regularisation|citoyens? de l'union|"
       r"citoyens? de l'ue|\bvisa\b|etudiant|refugie|regroupement familial|registre d'attente|apatrid|"
       r"non accompagne|permis de travail|permis unique|15 decembre 1980|carte bleue|schengen|"
       r"rapatriement|protection temporaire|protection subsidiaire|kosovar|bosniaque|"
       r"resident de longue duree|vacances-travail|main-d'oeuvre etrangere|"
       r"travailleurs? (salaries? )?(clandestin|migrant)|c\.e\.e|communaute economique europeenne|"
       r"espace economique europeen|mariages? (de complaisance|simule|blanc)|"
       r"cohabitations? (legales? )?(de complaisance|simulee)|reconnaissance frauduleuse|"
       r"centres? fermes?|traite des etres humains|engagement de prise en charge|brexit|ukrain")
EXC = (r"traduction allemande|langue allemande|election(?! de domicile)|electeur|electoral|"
       r"algorithmes cryptographiques|sejours? (de vacances|hospitalier|en plein air|pedagogique)|"
       r"sejour en (hopital|institution|maison)|taxe|budget|fiscal|impot|precompte|marches publics|"
       r"police integree|zones? de police|militaire|pension|allocations familiales|"
       r"\benseignement|minerval|permis de conduire|aide sociale|c\.p\.a\.s|cpas|centres publics|"
       r"integration sociale|legalisation|etudiants?\. vote|frais de (deplacement|parcours|sejour)|"
       r"engagement d'etudiants|handicap|deverser|extradition|police integre|a l'etranger|"
       r"teletravail|casiers? judiciaire|objecteurs de conscience|politique d'integration|"
       r"parcours d'accueil|acces (des etrangers )?a(ux)? (des )?emplois|lois sur la nationalite|"
       r"droit d'inscription|membres du personnel|securite sociale|droit applicable au nom")
# Dutch titles: only used for documents that have no French entry at all.
INC_NL = (r"vreemdeling|verblijf|buitenlandse werknemers|arbeidskaart|gecombineerde vergunning|"
          r"economische migratie|gezinshereniging|onderdanen|asiel|verwijdering|regularisatie")
EXC_NL = (r"duitse vertaling|verkiezing|kiezer|belasting|begroting|onderwijs|ziekenhuis|"
          r"maatschappelijk|ocmw|o\.c\.m\.w|politiezone|pensioen|verblijfs(taks|belasting)|legalisatie")

Q_MONITEUR_FR = [
    {"exp": "15 décembre 1980"}, {"exp": "Office des étrangers"}, {"exp": "registre des étrangers"},
    {"htit": "étrangers"}, {"htit": "étranger"}, {"htit": "séjour"}, {"htit": "regroupement familial"},
    {"htit": "ressortissants"}, {"htit": "éloignement"}, {"htit": "asile"}, {"htit": "régularisation"},
    {"htit": "citoyens Union"}, {"htit": "visa"}, {"htit": "étudiants"}, {"htit": "réfugiés"},
    {"htit": "registre attente"}, {"htit": "cohabitation"}, {"htit": "mariage"},
    {"htit": "permis de travail"}, {"htit": "travailleurs étrangers"}, {"htit": "kosovars"},
    {"htit": "résident longue durée"}, {"htit": "non accompagnés"}, {"htit": "protection temporaire"},
    {"htit": "Ukraine"}, {"htit": "Royaume-Uni"}, {"htit": "traite êtres humains"},
    {"htit": "prise en charge"}, {"htit": "vacances-travail"},
]
Q_MONITEUR_NL = [
    {"htit": "vreemdelingen"}, {"htit": "verblijf"}, {"htit": "buitenlandse werknemers"},
    {"htit": "arbeidskaart"}, {"htit": "gecombineerde vergunning"}, {"htit": "economische migratie"},
]
Q_JUSTEL_FR = [{"text1": "etrangers"}, {"text1": "sejour"}, {"text1": "ressortissants"},
               {"text1": "eloignement"}]

MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
          "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
          "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7,
          "augustus": 8, "september": 9, "oktober": 10, "december": 12}


def title_date(title):
    m = re.match(r"\s*(\d{1,2})\s*(?:er)?\s+([a-z]+)\s+(\d{4})", fold(title))
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return ""


def search(base, lang, params):
    """Run one search and yield (numac, department, title, publication date) for every hit."""
    p = {"language": lang, "trier": "promulgation", "choix1": "et", "choix2": "et"}
    p.update(params)
    qs = urllib.parse.urlencode(p, encoding="latin-1")
    page, hits = 1, []
    while page <= 40:
        raw = get(f"{SITE}/{base}/list.pl?{qs}&page={page}")
        if raw is None:
            break
        t = raw.decode("latin-1")
        items = t.split('<div class="list-item">')[1:]
        for it in items:
            m = re.search(r'href="article\.pl\?([^"]*)"\s*class="list-item--title">(.*?)</a>', it, re.S)
            if not m:
                continue
            q = urllib.parse.parse_qs(html.unescape(m.group(1)))
            dep = re.search(r'list-item--subtitle">(.*?)</p>', it, re.S)
            hits.append((q.get("numac_search", [""])[0], plain(dep.group(1)) if dep else "",
                         plain(m.group(2)), q.get("pd_search", [""])[0]))
        if not items or f"page={page + 1}&" not in t.replace("&amp;", "&"):
            break
        page += 1
    return hits


def collect():
    docs = {}                                         # numac -> dict
    for label, base, lang, queries, extra in (
            ("Moniteur FR", "cgi", "fr", Q_MONITEUR_FR, {"dt": "Circulaire", "fr": "f"}),
            ("Justel FR", "cgi_loi", "fr", Q_JUSTEL_FR, {"dt": "CIRCULAIRE MINISTERIELLE", "fr": "f"}),
            ("Moniteur NL", "cgi", "nl", Q_MONITEUR_NL, {"dt": "Omzendbrief", "nl": "n"})):
        for q in queries:
            hits = search(base, lang, dict(extra, **q))
            new = 0
            for numac, dep, title, pd in hits:
                if numac and numac not in docs:
                    docs[numac] = {"numac": numac, "dep": dep, "title": title, "pd": pd, "lang": lang}
                    new += 1
                elif numac and not docs[numac]["pd"]:
                    docs[numac]["pd"] = pd
            print(f"search {label} {q}: {len(hits)} hits, {new} new", flush=True)
    keep = []
    for d in docs.values():
        t = fold(d["title"])
        inc, exc = (INC, EXC) if d["lang"] == "fr" else (INC_NL, EXC_NL)
        if re.search(inc, t) and not re.search(exc, t):
            keep.append(d)
    keep.sort(key=lambda d: (title_date(d["title"]) or d["pd"], d["numac"]))
    print(f"{len(docs)} distinct search hits, {len(keep)} kept as immigration circulars")
    return keep


# ---------------------------------------------------------------- download

def moniteur_url(numac, pd, lang):
    return (f"{SITE}/cgi/article.pl?language={lang}&lg_txt={lang[0]}&pd_search={pd}"
            f"&numac_search={numac}&caller=list")


def justel_url(numac, lang):
    return f"{SITE}/cgi_loi/article.pl?language={lang}&lg_txt={lang[0]}&numac_search={numac}&caller=list"


def moniteur_text_len(page):
    m = re.search(r'<main[^>]*article-text[^>]*>(.*?)</main>', page, re.S)
    body = plain(m.group(1)) if m else ""
    if re.search(r"n'est pas disponible dans cette langue|niet beschikbaar in deze taal|"
                 r"uniquement au format PDF|enkel (raadpleegbaar|beschikbaar) in PDF", plain(page), re.I):
        return 0
    return len(body)


def justel_text_len(page):
    t = plain(page)
    i = t.find(" Texte ", t.find("Table des mati"))
    if i < 0:
        i = t.find(" Tekst ", t.find("Inhoudstafel"))
    j = max(t.find(" Liens ", i), t.find(" Links ", i))
    return len(t[i:j]) if i >= 0 else 0


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "moniteur_pdf").mkdir(exist_ok=True)
    keep = collect()
    if "--list" in sys.argv:                          # only show what would be downloaded
        for d in keep:
            print(d["numac"], d["pd"], d["title"], sep="\t")
        return
    rows, missing = [], []
    cache_file = OUT / ".justel_checked.tsv"          # numac -> link to the gazette PDF (may be empty)
    cache = dict(l.rstrip("\n").split("\t", 1) for l in cache_file.read_text().splitlines() if "\t" in l) \
        if cache_file.exists() else {}
    blocked = ""
    done = set()                                      # (date, publication date, start of title) already saved
    total = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file() and "coi" not in f.relative_to(OUT).parts[:1])
    nfiles = sum(1 for f in OUT.rglob("*") if f.is_file() and "coi" not in f.relative_to(OUT).parts[:1])
    stopped = False

    def write(dest, data):
        nonlocal total, nfiles
        dest.write_bytes(data)
        total += len(data)
        nfiles += 1

    for n, d in enumerate(keep, 1):
      try:
        numac, pd, title = d["numac"], d["pd"], d["title"]
        date = title_date(title)
        stem = f"{date or pd or 'undated'}_{numac}"
        norm = re.sub(r"circulaire|ministerielle|[^a-z0-9]", "", fold(title))
        key = (date, pd, re.sub(r"^\d+(er)?[a-z]+?\d{4}", "", norm)[:50])
        if key in done:                               # same circular under a second NUMAC
            continue
        other = lambda lg: "nl" if lg == "fr" else "fr"             # noqa: E731
        base = dict(title=title, date=date, numac=numac, published=pd, dep=d["dep"])
        if total > MAX_BYTES or nfiles > MAX_FILES:
            stopped = True
            missing.append(dict(base, reason="size/file limit reached", url=moniteur_url(numac, pd, "fr")))
            continue

        # 1. text as published in the Moniteur: French, else Dutch
        saved = None
        for lg in ("fr", "nl"):
            dest = OUT / f"{stem}_{lg}.html"
            if dest.exists() and dest.stat().st_size > 0:
                saved = (dest, lg, moniteur_url(numac, pd, lg), "")
                break
        pre1997 = bool(pd) and pd < "1997-06-01"
        if not saved and pd and not pre1997:
            for lg in ("fr", "nl"):
                raw = get(moniteur_url(numac, pd, lg))
                if raw and moniteur_text_len(raw.decode("latin-1")) > 300:
                    dest = OUT / f"{stem}_{lg}.html"
                    write(dest, raw)
                    saved = (dest, lg, moniteur_url(numac, pd, lg), "")
                    break

        # 2. Justel: consolidated version if amended later; fallback text; link to the gazette PDF
        jdest = OUT / f"{stem}_fr_consolidated.html"
        pdf_ref = ""
        if jdest.exists():
            rows.append(dict(base, file=jdest.name, url=justel_url(numac, "fr"), lang="fr",
                             note="Justel consolidated version (amended after publication)"))
        if numac not in cache or (not saved and not cache[numac]):
            raw = get(justel_url(numac, "fr"))
            page = raw.decode("latin-1") if raw else ""
            m = re.search(r'href="?(/mopdf/[^" >]+)', page)
            pdf_ref = m.group(1) if m else ""
            jlen = justel_text_len(page) if page else 0
            if saved and page and re.search(r"versions? archiv", page) and jlen > 1500 and not jdest.exists():
                write(jdest, raw)
                rows.append(dict(base, file=jdest.name, url=justel_url(numac, "fr"), lang="fr",
                                 note="Justel consolidated version (amended after publication)"))
            if not saved and jlen > 1500:
                dest = OUT / f"{stem}_fr_justel.html"
                write(dest, raw)
                saved = (dest, "fr", justel_url(numac, "fr"), "text from Justel database")
            if raw is not None:
                cache[numac] = pdf_ref
                with open(cache_file, "a") as cf:
                    cf.write(f"{numac}\t{pdf_ref}\n")
        else:
            pdf_ref = cache[numac]
        if not saved:
            dest = OUT / f"{stem}_fr_justel.html"
            if dest.exists():
                saved = (dest, "fr", justel_url(numac, "fr"), "text from Justel database")

        # 3. no electronic text: the scanned Moniteur issue (bilingual PDF)
        if not saved and not pdf_ref and pd:
            pdf_ref = f"/mopdf/{pd[:4]}/{pd[5:7]}/{pd[8:10]}_1.pdf"
        if not saved and pdf_ref:
            path, _, frag = pdf_ref.partition("#")
            dest = OUT / "moniteur_pdf" / ("moniteur_" + path.split("/mopdf/")[1].replace("/", "-"))
            if not (dest.exists() and dest.stat().st_size > 0):
                raw = get(SITE + path)
                if raw and raw[:5] == b"%PDF-":
                    write(dest, raw)
            if dest.exists() and dest.stat().st_size > 0:
                pg = re.sub(r"\D", "", frag)
                rows.append(dict(base, file=f"moniteur_pdf/{dest.name}", url=SITE + pdf_ref, lang="fr+nl",
                                 note=f"scan of the whole Moniteur issue of {pd}; circular starts at PDF page {pg or '?'}"))
                print(f"[{n}/{len(keep)}] {numac} scan {dest.name} p.{pg}", flush=True)
                continue
        if saved:
            dest, lg, url, note = saved
            done.add(key)
            o = other(lg)
            note = "; ".join(x for x in (note, f"{o.upper()} version: {moniteur_url(numac, pd, o)}") if x)
            rows.append(dict(base, file=dest.name, url=url, lang=lg, note=note))
            print(f"[{n}/{len(keep)}] {numac} {dest.name}", flush=True)
        else:
            missing.append(dict(base, reason="no text and no PDF found", url=moniteur_url(numac, pd, "fr")))
            print(f"[{n}/{len(keep)}] {numac} NOT SAVED", flush=True)
      except Blocked as e:                            # 403/429: do not insist, write the index and stop
        blocked = str(e)
        missing.append(dict(base, reason="server refused: " + blocked, url=moniteur_url(numac, pd, "fr")))
        for d2 in keep[n:]:
            missing.append(dict(title=d2["title"], date=title_date(d2["title"]), numac=d2["numac"],
                                published=d2["pd"], reason="not attempted after server refusal",
                                url=moniteur_url(d2["numac"], d2["pd"], "fr")))
        break

    cl = lambda s: re.sub(r"[\t\r\n]+", " ", str(s))               # noqa: E731
    rows.sort(key=lambda r: (r["date"] or r["published"], r["numac"], r["file"]))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tnumac\tpublished\tlanguage\tdepartment\tnote\n")
        for r in rows:
            f.write("\t".join(cl(r[k]) for k in ("file", "title", "date", "url", "numac", "published",
                                                 "lang", "dep", "note")) + "\n")
    with open(OUT / "not_saved.tsv", "w", encoding="utf-8") as f:
        f.write("title\tdate\tsource_url\tnumac\tpublished\treason\n")
        for r in missing:
            f.write("\t".join(cl(r[k]) for k in ("title", "date", "url", "numac", "published", "reason")) + "\n")
    print(f"\n{len(rows)} index rows, {len(missing)} not saved, {nfiles} files, {total / 1e6:.1f} MB in {OUT}")
    if blocked:
        print(f"BLOCKED by the server ({blocked}); stopped without retrying. See not_saved.tsv")
    if stopped:
        print("STOPPED at the size/file limit; see not_saved.tsv")


if __name__ == "__main__":
    try:
        main()
    except Blocked as e:
        sys.exit(f"Blocked by the server ({e}); stopping without retrying.")

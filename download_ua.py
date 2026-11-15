#!/usr/bin/env python3
"""Ukraine: what the State Migration Service (Державна міграційна служба, DMS) publishes for its
own officials on handling foreigners' cases.

    python3 download_ua.py            # everything
    python3 download_ua.py kartky     # one source: kartky | zbirnyk

Source (the only official host that accepts this client):
    https://dmsu.gov.ua   robots.txt: only /search.html and /akamai/ are disallowed for "*".
      /diyalnist/legal-acts/nakazi-dms.html  (20 pages)   "Накази та плани діяльності ДМС"
      /poslugi/tipovi-texnologichni-ta-informaczijni-kartki-poslug.html
      /diyalnist/legal-acts/zakon.html

  kartky   DMS orders approving the "typical information cards and model technological cards" of
           administrative services. The technological card is the step-by-step internal workflow
           (stage, responsible official, time limit) that every territorial body must follow; the
           information card is the standard description of the service. These are departmental
           orders addressed to the territorial bodies, not registered legal acts: kind = guidance.
           Only the orders that cover services for foreigners and stateless persons are taken
           (No 7 of 2021, No 245 of 2022, No 291 of 2025 and its amendments). The other card
           orders on the same pages (No 355 of 2016, 12 of 2017, 33 and 94 of 2020, 22 of 2021,
           11 of 2022, 144 of 2023, 17 of 2024, 336 of 2026) concern Ukrainian citizens' passports,
           residence registration or apostilles and are left out.
  zbirnyk  "Збірник законодавства" (2018), the two-volume compendium of migration legislation
           that the DMS compiled for its staff. It reprints the Cabinet and Ministry procedures
           (порядки, інструкції, правила) that are the working rules: kind = procedural act.

Not fetched, on purpose: zakon.rada.gov.ua (robots.txt "User-Agent: * Disallow: /"; the host also
does not answer from this network), www.kmu.gov.ua/npas/ (robots.txt disallows /npas/),
mvs.gov.ua (robots.txt "Disallow: /"). See ua/not-obtained.tsv.

Standard library only; sequential; files already present are skipped; index.tsv is rewritten.
"""
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

OUT = Path(__file__).resolve().parent / "ua"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.5
DOC = "https://dmsu.gov.ua/assets/files/doc/"
P_KARTKY = "https://dmsu.gov.ua/poslugi/tipovi-texnologichni-ta-informaczijni-kartki-poslug.html"
P_NAKAZY = "https://dmsu.gov.ua/diyalnist/legal-acts/nakazi-dms.html"
P_ZAKON = "https://dmsu.gov.ua/diyalnist/legal-acts/zakon.html"
CARDS = "типових інформаційних карток і зразків технологічних карток адміністративних послуг"
CARDS_EN = "typical information cards and model technological (workflow) cards of administrative services"

# (source, file, date, kind, title, title_en, url, listing page, note)
ITEMS = [
    ("kartky", "kartky/2021-01-25_nakaz-dms-7.pdf", "2021-01-25", "guidance",
     f"Наказ ДМС від 25.01.2021 №7 «Про затвердження {CARDS} ДМС стосовно іноземців та осіб без громадянства»",
     f"DMS Order No 7 of 25 January 2021 approving {CARDS_EN} of the DMS concerning foreigners and stateless persons",
     DOC + "n_2021_7.pdf", P_NAKAZY + "?page=16", ""),
    ("kartky", "kartky/2022-12-02_nakaz-dms-245.zip", "2022-12-02", "guidance",
     f"Наказ ДМС від 02.12.2022 №245 «Про затвердження {CARDS} ДМС стосовно іноземців та осіб без громадянства»",
     f"DMS Order No 245 of 2 December 2022 approving {CARDS_EN} of the DMS concerning foreigners and stateless persons",
     DOC + "n_2022_245.zip", P_NAKAZY + "?page=13", "ZIP archive as published"),
    ("kartky", "kartky/2025-10-23_nakaz-dms-291.zip", "2025-10-23", "guidance",
     f"Наказ ДМС від 23.10.2025 №291 «Про затвердження {CARDS} ДМС стосовно іноземців та осіб без громадянства»",
     f"DMS Order No 291 of 23 October 2025 approving {CARDS_EN} of the DMS concerning foreigners and stateless persons (the set in force)",
     DOC + "n_2025_291.zip", P_KARTKY, "ZIP archive as published"),
    ("kartky", "kartky/2026-03-19_nakaz-dms-79.zip", "2026-03-19", "guidance",
     f"Наказ ДМС від 19.03.2026 №79 «Про внесення змін до наказу ДМС від 23.10.2025 №291 \"Про затвердження {CARDS} ДМС стосовно іноземців та осіб без громадянства\"»",
     "DMS Order No 79 of 19 March 2026 amending Order No 291 of 23 October 2025 (cards for services to foreigners and stateless persons)",
     DOC + "n_2026_79.zip", P_KARTKY, "ZIP archive as published"),
    ("kartky", "kartky/2026-07-07_nakaz-dms-230.zip", "2026-07-07", "guidance",
     f"Наказ ДМС від 07.07.2026 №230 «Про внесення змін до наказу ДМС від 23.10.2025 №291 \"Про затвердження {CARDS} ДМС стосовно іноземців та осіб без громадянства\"»",
     "DMS Order No 230 of 7 July 2026 amending Order No 291 of 23 October 2025 (cards for services to foreigners and stateless persons)",
     DOC + "n_2026_230.zip", P_KARTKY, "ZIP archive as published"),
    ("zbirnyk", "zbirnyk/2018-12_zbirnyk-zakonodavstva-chastyna-1.pdf", "2018-12", "procedural act",
     "Збірник законодавства (частина 1): нормативно-правові акти у сферах громадянства, реєстрації фізичних осіб, паспортних документів",
     "Compendium of legislation, part 1 (DMS, 2018, 683 pp.): laws, decrees, Cabinet and Ministry procedures on citizenship, "
     "registration of residence and identity documents, as compiled by the DMS for its staff",
     DOC + "urist_1.pdf", P_ZAKON,
     "compilation: reprints statutes as well as the procedures; state of the law at December 2018"),
    ("zbirnyk", "zbirnyk/2018-12_zbirnyk-zakonodavstva-chastyna-2.pdf", "2018-12", "procedural act",
     "Збірник законодавства (частина 2): нормативно-правові акти у сферах імміграції, протидії нелегальній міграції, біженців та інших категорій мігрантів",
     "Compendium of legislation, part 2 (DMS, 2018, 787 pp.): laws, Cabinet and Ministry procedures and instructions on immigration, "
     "residence permits, extension of stay, voluntary and forced return, expulsion, detention, refugees and complementary protection",
     DOC + "urist_2.pdf", P_ZAKON,
     "compilation: reprints statutes as well as the procedures; state of the law at December 2018"),
]

_last = {}
_robots = {}


def allowed(url):
    """robots.txt of the host is read first, once, in a request of its own."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"{parts.scheme}://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                rp.parse(["User-agent: *", "Disallow: /"])     # a refused robots.txt closes the host
            else:
                rp.parse([])
        except Exception as e:                                  # noqa: BLE001
            print(f"  robots.txt of {host} unreachable ({e}); host skipped")
            rp.parse(["User-agent: *", "Disallow: /"])
        _robots[host] = rp
        _last[host] = time.time()
    return _robots[host].can_fetch("*", url)


def fetch(url, dest):
    """One request, no retry. Returns None on success or the reason."""
    if not allowed(url):
        return "robots.txt"
    host = urllib.parse.urlsplit(url).netloc
    wait = DELAY - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    part = dest.with_name(dest.name + ".part")
    try:
        req = urllib.request.Request(urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~"), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        part.unlink(missing_ok=True)
        return f"HTTP {e.code}"
    except Exception as e:                                      # noqa: BLE001
        part.unlink(missing_ok=True)
        return str(e)
    finally:
        _last[host] = time.time()
    head = part.read_bytes()[:8]
    ok = head.startswith(b"%PDF") if dest.suffix == ".pdf" else head.startswith(b"PK")
    if not ok:
        part.unlink()
        return "not a PDF/ZIP (error page?)"
    part.rename(dest)
    return None


def main():
    want = set(sys.argv[1:])
    failed = []
    for src, name, date, kind, title, title_en, url, page, note in ITEMS:
        dest = OUT / name
        if dest.exists() or (want and src not in want):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        why = fetch(url, dest)
        print(("saved  " if why is None else f"FAILED ({why})  ") + name)
        if why:
            failed.append((title, date, url, why))
    rows = ["file\ttitle\tdate\tsource_url\tkind\ttitle_en\tlisting_page\tnote"]
    for src, name, date, kind, title, title_en, url, page, note in ITEMS:
        if (OUT / name).exists():
            rows.append("\t".join([name, title, date, url, kind, title_en, page, note]))
    (OUT / "index.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"index.tsv: {len(rows) - 1} rows; {len(failed)} failed this run")
    for f in failed:
        print("  not obtained:", f[2], f[3])


if __name__ == "__main__":
    main()

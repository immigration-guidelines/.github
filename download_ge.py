#!/usr/bin/env python3
"""Georgia: the procedural acts that officials deciding foreigners' and citizenship cases work
from. Georgia publishes no guidance (manual, instruction, methodological letter) for them.

    python3 download_ge.py            # everything
    python3 download_ge.py sda        # one source: sda | matsne

Sources
  sda     https://sda.gov.ge  (Public Service Development Agency, Ministry of Justice: decides
          residence permits, citizenship and stateless status). robots.txt is not served (the
          address redirects to the home page), so nothing is excluded.
          Page "სამართლებრივი აქტები > მოქალაქეობა / მიგრაცია":
          https://sda.gov.ge/legal-acts/მოქალაქეობა-მიგრაცია/  - the Agency's own PDF copies of
          the government resolutions, ministerial orders and Citizenship Commission decisions
          that set its procedures (the laws on the same page are not taken).
  matsne  https://matsne.gov.ge  (Legislative Herald, official consolidated texts). robots.txt:
          Crawl-delay 10, document pages allowed. Ministry of Internal Affairs orders that set the
          procedure of its Migration Department (asylum requests, expulsion, detention), and the
          government resolutions on stateless status and visas. The current consolidated PDF is
          taken: "/ka/document/download/<id>/<N>/ge/pdf" with N the latest publication listed
          on the document page.

Every item is a legal act that works as the procedure manual: kind = procedural act.

Not used: migration.commission.ge (State Commission on Migration Issues) answers every
request, robots.txt included, with a JavaScript cookie challenge; police.ge (Ministry of
Internal Affairs) did not answer from this network. See ge/not-obtained.tsv.

Standard library only; sequential; files already present are skipped; index.tsv is rewritten.
"""
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

OUT = Path(__file__).resolve().parent / "ge"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.5
SDA = "https://sda.gov.ge/wp-content/uploads/2024/11/"
SDA_PAGE = ("https://sda.gov.ge/legal-acts/%e1%83%9b%e1%83%9d%e1%83%a5%e1%83%90%e1%83%9a%e1%83%90%e1%83%a5"
            "%e1%83%94%e1%83%9d%e1%83%91%e1%83%90-%e1%83%9b%e1%83%98%e1%83%92%e1%83%a0%e1%83%90%e1%83%aa%e1%83%98%e1%83%90/")
MATSNE = "https://matsne.gov.ge/ka/document/"
PA = "procedural act"

# (source, file, date, title, title_en, url, listing page, note)
ITEMS = [
    ("sda", "sda/2014-09-01_dadgenileba-520-binadroba.pdf", "2014-09-01",
     "საქართველოს მთავრობის დადგენილება №520, 2014 წლის 1 სექტემბერი: საქართველოში ბინადრობის ნებართვის გაცემის საკითხის განხილვისა და გადაწყვეტის წესის დამტკიცების შესახებ",
     "Government Resolution No 520 of 1 September 2014 approving the rule for examining and deciding applications for residence permits in Georgia",
     SDA + "საქართველოში-ბინადრობის-ნებართვის-გაცემის-საკითხის-განხილვისა-და-გადაწყვეტის-წესი.pdf", SDA_PAGE,
     "consolidated copy published by the Agency (PDF created 2025-10-08)"),
    ("sda", "sda/2026-02-20_dadgenileba-70-shromiti-sakmianoba.pdf", "2026-02-20",
     "საქართველოს მთავრობის დადგენილება №70, 2026 წლის 20 თებერვალი: შრომით იმიგრანტსა და თვითდასაქმებულ უცხოელზე შრომითი საქმიანობის უფლების გაცემის წესის დამტკიცების შესახებ",
     "Government Resolution No 70 of 20 February 2026 approving the rule for granting the right to work to labour immigrants and self-employed foreigners",
     SDA + "შრომით-იმიგრანტსა-და-თვითდასაქმებულ-უცხოელზე-შრომითი-საქმიანობის-უფლების-გაცემის-წესი.pdf", SDA_PAGE, ""),
    ("sda", "sda/2018-09-04_komisiis-dadgenileba-2-mokalakeoba.pdf", "2018-09-04",
     "მოქალაქეობის საკითხთა კომისიის დადგენილება №2, 2018 წლის 4 სექტემბერი: საქართველოს მოქალაქეობის საკითხთა განხილვისა და გადაწყვეტის შესახებ დებულების დამტკიცების თაობაზე",
     "Citizenship Commission Decision No 2 of 4 September 2018 approving the regulation on examining and deciding Georgian citizenship matters",
     SDA + "საქართველოს-მოქალაქეობის.pdf", SDA_PAGE, "consolidated copy published by the Agency (PDF created 2025-10-02)"),
    ("sda", "sda/2018-09-04_komisiis-dadgenileba-1-debuleba.pdf", "2018-09-04",
     "მოქალაქეობის საკითხთა კომისიის დადგენილება №1, 2018 წლის 4 სექტემბერი: მოქალაქეობის საკითხთა კომისიის დებულების დამტკიცების შესახებ",
     "Citizenship Commission Decision No 1 of 4 September 2018 approving the Commission's rules of procedure",
     SDA + "მოქალაქეობის-საკითხთა-კომისიის-დებულება-2.pdf", SDA_PAGE, ""),
    ("sda", "sda/2024-04-30_brdzaneba-996-mokalakeobis-gamocda.pdf", "2024-04-30",
     "საქართველოს იუსტიციის მინისტრის ბრძანება №996, 2024 წლის 30 აპრილი: საქართველოს მოქალაქეობის მინიჭებით დაინტერესებული პირის მიერ საქართველოს სახელმწიფო ენის, საქართველოს ისტორიისა და სამართლის ძირითადი საფუძვლების ცოდნის დონის შესამოწმებლად განცხადების წარდგენის პროცედურის, მისი ცოდნის დონის შემოწმების წესისა და შესაბამისი მომსახურების საფასურის ოდენობის განსაზღვრის შესახებ",
     "Order No 996 of the Minister of Justice of 30 April 2024 on the procedure for applying for, and the rules for conducting, the test of Georgian language, history and basic law for applicants for citizenship",
     SDA + "N-996.pdf", SDA_PAGE, ""),
    ("sda", "sda/2023-01-17_brdzaneba-888-tsxovrebis-pakti.pdf", "2023-01-17",
     "საქართველოს იუსტიციის მინისტრის ბრძანება №888, 2023 წლის 17 იანვარი: პირის მუნიციპალიტეტის ტერიტორიაზე ცხოვრების (ყოფნის) ფაქტის დამდგენი კომისიის ტიპური დებულების დამტკიცების შესახებ",
     "Order No 888 of the Minister of Justice of 17 January 2023 approving the model regulation of the municipal commissions that establish the fact of a person's residence (for citizenship cases)",
     SDA + "პირის-მუნიციპალიტეტის-ტერიტორიაზე-ცხოვრების-ყოფნის-ფაქტის-დამდგენი-კომისიის-ტიპური.pdf", SDA_PAGE, ""),
    ("matsne", "matsne/2014-09-01_dadgenileba-523-mokalakeobis-armkone.pdf", "2014-09-01",
     "საქართველოს მთავრობის დადგენილება №523, 2014 წლის 1 სექტემბერი: საქართველოში მოქალაქეობის არმქონე პირის სტატუსის დადგენის წესის დამტკიცების შესახებ",
     "Government Resolution No 523 of 1 September 2014 approving the procedure for determining stateless status in Georgia",
     MATSNE + "view/2483498", MATSNE + "view/2483498", "current consolidated text"),
    ("matsne", "matsne/2015-06-23_dadgenileba-280-viza.pdf", "2015-06-23",
     "საქართველოს მთავრობის დადგენილება №280, 2015 წლის 23 ივნისი: საქართველოს ვიზის გაცემის, მისი მოქმედების ვადის გაგრძელებისა და მოქმედების შეწყვეტის წესის დამტკიცების თაობაზე",
     "Government Resolution No 280 of 23 June 2015 approving the rules for issuing, extending and terminating Georgian visas",
     MATSNE + "view/2882028", MATSNE + "view/2882028", "current consolidated text"),
    ("matsne", "matsne/2025-10-06_shss-brdzaneba-102-sazgvris-gadmokveta.pdf", "2025-10-06",
     "საქართველოს შინაგან საქმეთა მინისტრის ბრძანება №102, 2025 წლის 6 ოქტომბერი: უცხოელის ან მოქალაქეობის არმქონე პირის მიერ საქართველოს სახელმწიფო საზღვრის უკანონოდ გადმოკვეთის შემთხვევაში საერთაშორისო დაცვის მოთხოვნის იდენტიფიცირებისა და საქართველოს შინაგან საქმეთა სამინისტროს მიგრაციის დეპარტამენტსა და სახელმწიფო საქვეუწყებო დაწესებულება – საქართველოს სასაზღვრო პოლიციას შორის ინფორმაციის გაცვლის წესის დამტკიცების შესახებ",
     "Order No 102 of the Minister of Internal Affairs of 6 October 2025 on identifying requests for international protection by foreigners who crossed the border irregularly, and on information exchange between the Migration Department and the Border Police",
     MATSNE + "view/6640490", MATSNE + "view/6640490", "current consolidated text"),
    ("matsne", "matsne/2025-10-06_shss-brdzaneba-103-shss-dawesebuleba.pdf", "2025-10-06",
     "საქართველოს შინაგან საქმეთა მინისტრის ბრძანება №103, 2025 წლის 6 ოქტომბერი: უცხოელის ან მოქალაქეობის არმქონე პირის მიერ საერთაშორისო დაცვის საქართველოს შინაგან საქმეთა სამინისტროს სისტემის შესაბამის დაწესებულებაში მოთხოვნის შემთხვევაში საქართველოს შინაგან საქმეთა სამინისტროს სათანადო დანაყოფებს შორის ინფორმაციის გაცვლის წესის დამტკიცების შესახებ",
     "Order No 103 of the Minister of Internal Affairs of 6 October 2025 on information exchange between Ministry units when international protection is requested at a Ministry institution",
     MATSNE + "view/6640235", MATSNE + "view/6640235", "current consolidated text"),
    ("matsne", "matsne/2025-10-06_shss-brdzaneba-105-sazgvari.pdf", "2025-10-06",
     "საქართველოს შინაგან საქმეთა მინისტრის ბრძანება №105, 2025 წლის 6 ოქტომბერი: უცხოელის ან მოქალაქეობის არმქონე პირის მიერ საქართველოს სახელმწიფო საზღვარზე საერთაშორისო დაცვის მოთხოვნის იდენტიფიცირებისა და საქართველოს შინაგან საქმეთა სამინისტროს შესაბამის დანაყოფებს შორის ინფორმაციის გაცვლის წესის დამტკიცების შესახებ",
     "Order No 105 of the Minister of Internal Affairs of 6 October 2025 on identifying requests for international protection made at the state border and on information exchange between Ministry units",
     MATSNE + "view/6639951", MATSNE + "view/6639951", "current consolidated text"),
    ("matsne", "matsne/2025-11-14_shss-brdzaneba-112-gadzeveba.pdf", "2025-11-14",
     "საქართველოს შინაგან საქმეთა მინისტრის ბრძანება №112, 2025 წლის 14 ნოემბერი: უცხოელის საქართველოდან გაძევების საკითხის განხილვისა და უცხოელის ან თავშესაფრის მაძიებლის დაკავებისა და დროებითი მოთავსების იზოლატორში ან/და დროებითი განთავსების ცენტრში მოთავსების წესის დამტკიცების შესახებ",
     "Order No 112 of the Minister of Internal Affairs of 14 November 2025 approving the procedure for examining the expulsion of a foreigner from Georgia and for detaining a foreigner or asylum seeker in a temporary isolation facility or temporary accommodation centre",
     MATSNE + "view/6670618", MATSNE + "view/6670618", "current consolidated text"),
    ("matsne", "matsne/2025-11-28_shss-brdzaneba-116-dakaveba.pdf", "2025-11-28",
     "საქართველოს შინაგან საქმეთა მინისტრის ბრძანება №116, 2025 წლის 28 ნოემბერი: უცხოელის ან მოქალაქეობის არმქონე პირის/თავშესაფრის მაძიებლის დაკავებისა და დროებითი განთავსების ცენტრში მოთავსების წესის დამტკიცების შესახებ",
     "Order No 116 of the Minister of Internal Affairs of 28 November 2025 approving the procedure for detaining a foreigner, stateless person or asylum seeker and placing them in the temporary accommodation centre",
     MATSNE + "view/6677840", MATSNE + "view/6677840", "current consolidated text"),
]

_last = {}
_robots = {}
_delay = {}


def allowed(url):
    """robots.txt of the host is read first, once, in a request of its own."""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"{parts.scheme}://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
                # sda.gov.ge redirects /robots.txt to its home page: no rules
                rp.parse([] if "<html" in body[:2000].lower() else body.splitlines())
        except urllib.error.HTTPError as e:
            rp.parse(["User-agent: *", "Disallow: /"] if e.code in (401, 403, 429) else [])
        except Exception as e:                                  # noqa: BLE001
            print(f"  robots.txt of {host} unreachable ({e}); host skipped")
            rp.parse(["User-agent: *", "Disallow: /"])
        _robots[host] = rp
        _delay[host] = max(DELAY, float(rp.crawl_delay("*") or 0))
        _last[host] = time.time()
    return _robots[host].can_fetch("*", url)


def get(url, timeout=180):
    """One request, no retry. Returns (body or None, reason)."""
    if not allowed(url):
        return None, "robots.txt"
    host = urllib.parse.urlsplit(url).netloc
    wait = _delay[host] - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(urllib.parse.quote(url, safe=":/?&=%+()#,;@!$'*~"), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:                                      # noqa: BLE001
        return None, str(e)
    finally:
        _last[host] = time.time()


def fetch(src, url, dest):
    if src == "matsne":
        page, why = get(url)
        if page is None:
            return why
        doc_id = url.rstrip("/").rsplit("/", 1)[1]
        # the page lists every consolidated version as "?publication=N"; the highest N is the
        # text in force ("/download/<id>/0/..." would be the original version)
        pubs = [int(n) for n in re.findall(rf"view/{doc_id}\?publication=(\d+)", page.decode("utf-8", "replace"))]
        url = f"https://matsne.gov.ge/ka/document/download/{doc_id}/{max(pubs, default=0)}/ge/pdf"
    body, why = get(url)
    if body is None:
        return why
    if not body.startswith(b"%PDF"):
        return "not a PDF (error page?)"
    dest.write_bytes(body)
    return None


def main():
    want = set(sys.argv[1:])
    failed = []
    for src, name, date, title, title_en, url, page, note in ITEMS:
        dest = OUT / name
        if dest.exists() or (want and src not in want):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        why = fetch(src, url, dest)
        print(("saved  " if why is None else f"FAILED ({why})  ") + name)
        if why:
            failed.append((title, date, url, why))
    rows = ["file\ttitle\tdate\tsource_url\tkind\ttitle_en\tlisting_page\tnote"]
    for src, name, date, title, title_en, url, page, note in ITEMS:
        if (OUT / name).exists():
            rows.append("\t".join([name, title, date, url, PA, title_en, page, note]))
    (OUT / "index.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"index.tsv: {len(rows) - 1} rows; {len(failed)} failed this run")
    for f in failed:
        print("  not obtained:", f[2], f[3])


if __name__ == "__main__":
    main()

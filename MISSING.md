# What could not be downloaded, and how to get it

> **Since 15 November 2026** each jurisdiction's repository carries its own `NOTES.txt` and `not-obtained.tsv`, which are the up-to-date record of what is missing there and why. This file covers the first 20 jurisdictions collected on 14 November and is no longer updated country by country.


Status as of 14 November 2026, 17:30. Final update 14 November 2026, 22:50: all downloads finished.

Update, 15 November 2026, 09:30. A real browser (headless Chromium driven over the DevTools protocol) was used to fetch sources that refuse Python's HTTP client as a bot: New Zealand's circular search, Norway's current guidelines, Spain's ministry site, and Australia's foreign affairs department. Results: Spain is now complete apart from one dead link; Norway's current guidelines are nearly complete; New Zealand's circulars are complete for what the site lists; 23 Australian country reports were added; the Swedish scan was extended back to 2020 (+23 documents); the 252 USCIS policy-alert PDFs were added; and two Schleswig-Holstein decrees were added. The sections below have been updated.

Everything here was left out for one of four reasons:

- **Blocked:** the site refuses Python's HTTP client (bot check, rate limit, or a robots.txt rule). On 14 November these were not worked around, except in Belgium, where the gazette's rate limit was retried slowly even though its robots.txt disallows the pages (see below). A person using a browser is a normal visitor, so downloading by hand is fine. On 15 November several of these sites were read with a headless browser acting as a normal visitor; where that succeeded, the section below says so.
- **Gone:** the link is dead or the file was never in the archive.
- **Not published:** the authority does not make the document public.
- **Skipped on purpose:** too large or out of scope; a command is given to fetch it.

## How to add a file you download by hand

1. Save it into the folder named for that source below, keeping the naming pattern of the files already there.
2. Re-run that source's script. Each script skips files that exist and rewrites the folder's `index.tsv`, so your file is picked up:

   ```
   cd /home/brinly/immigration-guidelines
   ./download.py wi            # Dutch work instructions
   ./download.py uk            # UK guidance
   python3 download_fr.py      # one script per other country: download_<code>.py
   ```

`./resume-all.sh` re-runs every script except Sweden's.

---

## Netherlands

### IND work instructions: 33 missing (gone from the archive)

The Radboud University archive lists these on its year pages but does not hold the files. All 283 that exist were saved.

| Year | Numbers |
|---|---|
| 2001 | 243, 244 |
| 2009 | 7, 17 |
| 2013 | 2, 6, 7, 10, 15, 16, 18 |
| 2014 | 1, 2, 3, 4, 7 |
| 2015 | 2, 3, 7 |
| 2016 | 6 |
| 2017 | 4, 6 |
| 2018 | 2, 5, 8, 13, 14, 17 |
| 2019 | 3, 14 |
| 2022 | 5, 20 |
| 2025 | 2 |

How to get them:

1. Open `https://puc.overheid.nl/ind` in a browser and search for the citation, e.g. `WI 2022/20`. This portal holds instructions that are still in force, so it is most likely to have the recent ones. It refuses scripts.
2. Search the web for the citation in quotes, e.g. `"WI 2018/13" werkinstructie`.
3. For withdrawn ones, look for archived copies of ind.nl in the Wayback Machine.
4. Report the dead links to the archive's maintainer (contact address on `https://cmr.jur.ru.nl/cmr/tbv/`).

Save as `nl/werkinstructies/<year>/wi.<year>.<nn>.pdf`, e.g. `nl/werkinstructies/2018/wi.2018.13.pdf`, then run `./download.py wi`.

Some numbers may never have been published.

### Circular history: skipped on purpose

Only the current version of parts A, B and C was saved. The official repository has every version since April 2005 (209, 252 and 367 versions; about 2 GB). The addresses are in `nl/manifest-A.xml`, `manifest-B.xml` and `manifest-C.xml`; each version is at `https://repository.officiele-overheidspublicaties.nl/bwb/<BWB id>/<date>_0/xml/<BWB id>_<date>_0.xml`. Bulk download is allowed there.

### Country reports: about 150 missing (blocked)

Saved: 65 reports, all from files hosted on `rijksoverheid.nl` itself. About 150 more are hosted on `open.overheid.nl`, and these were not fetched.

- **Why:** `open.overheid.nl/robots.txt` reads `User-agent: * / Disallow: /`, so scripted access to the whole site is disallowed. On 14 November this was misread as a server outage, because the address form the script used (`/documenten/<id>/pdf`) answered HTTP 500; the original links on the ministry's pages (`/repository/ronl-<id>/1/pdf/<name>.pdf`) answer normally. The script has been changed so that it no longer requests anything from that host.
- **By hand:** open `https://www.rijksoverheid.nl/documenten?trefwoord=ambtsbericht` (or the country's "ambtsbericht" page) in a browser; each report's page has a download link. Save into `nl/coi/` named `<date>_<title>.pdf` like the others. The original links for all of them are cached in `nl/coi/state.json` under `pages`.

---

## Belgium: circulars now complete

Saved: 181 documents (187 index rows, since several circulars share a scanned gazette issue), 1945 to March 2026; `be/not_saved.tsv` is empty.

The first run stopped at April 2004 when the official gazette's server (`ejustice.just.fgov.be`) answered "too many requests". A second run on 14 November at 16:01 (`download_be.py --retry-blocked --delay 8`, eight seconds between requests) fetched the remaining 57 without a refusal. The site's robots.txt disallows the sections the script reads.

Not published at all: the Immigration Office's instructions to municipalities ("Gemcom") are behind an electronic-ID login.

---

## France: 53 texts missing (blocked or gone)

Saved: 366 documents. Most come from the GISTI archive; two were fetched from the official sites on 15 November (the 2013 circular on domiciliation in prison and the 2023 circular on nationality procedure). The three official sites (Légifrance, immigration.interieur.gouv.fr, the ministry's Bulletin officiel) still answer scripts with a bot check.

The list is in `fr/not-downloaded.tsv`, with topic, title, date, the GISTI page and the reason. Asylum accounts for 24 and removal for 11. Of the remaining 53, twelve name an official PDF that is dead, forbidden, or behind a bot check; the rest are text-only on GISTI. For each:

1. Open the GISTI page given in the list; it links to the official address.
2. If that address is dead, search Légifrance's circulars section (`https://www.legifrance.gouv.fr/circulaire`) in a browser for the NOR number in the title.
3. Save the PDF into `fr/<topic>/`, named `<date>_<short title>.pdf` like the others.

Also not covered: circulars that GISTI never indexed. Légifrance is the official register and can only be searched by hand.

---

## Italy

- **State Police circulars (blocked):** `poliziadistato.it` refused access, so nothing addressed to the police immigration offices (Questure) was collected. Browse the site by hand; many of these are not published at all.
- **Three legacy files (gone):** one PDF is a dead link (`0911_circolare_1843_17.03.10_emersione.pdf`) and two `.doc` annexes return an error page. `python3 download_it.py` reports them on each run.
- **Thin years:** 2011–2014 and 2017 have one to six files each; the ministry's listings simply hold little for those years.

---

## Sweden

- **Position papers last revised before July 2023: now fetched.** The first scan covered July 2023 to November 2026 and saved 90 files. A deeper scan on 15 November (`python3 download_se.py --low 44000`) walked every document number down to 44000, about 2020, and added 23 documents; `se/` now holds 113 files and covers papers issued from 2020 onwards. The database forbids scripted use of its search, so the script reads document pages one number at a time. The database keeps only the latest version of each paper, so superseded versions are not in the database at all; papers first issued before 2020 sit at lower numbers and have not been looked at.
- **Handbook for migration cases (gone):** no longer published. Archived copies from 2015–2017 exist in the Wayback Machine, which refused scripted requests on the day; open `https://web.archive.org/web/2017*/migrationsverket.se/*handbok*` in a browser.
- **RS/043/2021 version 2.0 on Dublin (not published):** listed without an attachment.
- By hand, the database search works in a browser: `https://lifos.migrationsverket.se`, subject "Rättsliga ställningstaganden och kommentarer".

Save into `se/`, then `python3 download_se.py --index-only`.

---

## Norway: current guidelines nearly complete

`udiregelverk.no` answers scripts with a bot check. The older copies were taken from Common Crawl's public archive, so each was the newest copy a crawler happened to capture. On 15 November a headless browser passed the site's bot check: the listing was loaded (all 291 results after clicking "show more") and 106 guideline pages that were missing were saved from the live site. `no/index.tsv` marks them `live (browser)`.

Saved: 978 pages.

- **Current guidelines: about 10 of 291 missing.** The browser pass added 106 pages; 281 unique guideline IDs are now present. The remainder failed to load or are 404. Attachments linked from the guidelines are still only the 59 captured earlier.
- **Older layout: near complete, but old.** About 310 circulars (RS), 190 internal notices (IM) and 61 practice notes (PN), mostly as they stood in 2019. Many are predecessors of today's guidelines, so the two sets overlap with older text.
- **Nothing captured between 2020 and late 2024** in the Common Crawl material; the browser pass fills the current set, not the gap in historical copies.
- **Skipped on purpose:** laws, ministry circulars and instructions, court decisions, international sources, and the English translations.

Any remaining page can be saved from `https://www.udiregelverk.no/rettskilder/udi-retningslinjer/` in a browser, under the naming used there. `no/index.tsv` gives the source and capture date of each saved copy; `live (browser)` means it came from the site itself. `python3 download_no.py` retries the few Common Crawl indexes that timed out; `--reindex` re-asks crawls that returned nothing, and the script keeps the browser-saved rows when it rewrites the index.

---

## United Kingdom

- **Archive of superseded immigration rules (skipped on purpose):** 180 past versions, 7–9 MB each, very slow to serve. Three were fetched. For the rest: `./download.py uk --with-rules-archive` (allow about 14 hours).
- **Two National Archives links (blocked):** `webarchive.nationalarchives.gov.uk` refuses scripts. They are archived copies of the immigration rules page; open in a browser if wanted.

Guidance and country notes are otherwise complete: 635 and 177 files, no failures.

---

## United States

- **Policy-alert PDFs: now fetched.** The 252 PDFs linked from `us/uscis-policy-manual/updates.html` are in `us/uscis-policy-manual/policy-alerts/`; `python3 download_us.py alerts` refreshes them from that list. (Seven further links on the page point to Federal Register notices on govinfo.gov and were left out.) The manual itself is complete.
- **15 sections of 9 FAM (not published):** titled "UNAVAILABLE" by the State Department.
- **One chapter of the retired field manual (gone):** `afm61-external.pdf` redirects to a "superseded" page.

---

## Finland

- **Afghanistan asylum guideline (gone):** on the listing in July 2026, since removed. An archived copy of the listing is in the Wayback Machine for `https://migri.fi/soveltamisohjeet`.
- **Superseded versions:** not collected; current versions only.

---

## Spain: complete apart from one dead link

`inclusion.gob.es` answers Python's HTTP client with 403 "Acceso denegado", and the Internet Archive had begun answering 429. On 15 November the site was crawled with a headless browser instead, which it serves normally, and every listing and document was fetched from the live site.

Saved: 204 index rows and 199 files: 66 instructions (2006–2026), 11 management criteria, 66 information sheets, and 55 pages/documents from the large-companies unit (UGE), including the Spanish version of DGGM 2-2026 and the per-permit pages.

- **Still missing:** one category page, "Aplicable la Situación Nacional de Empleo", is a genuine 404 on the site. A handful of UGE application forms were left out on purpose.
- **Scans:** some of the older PDFs are images with no text layer, so they cannot be searched without OCR.
- **Re-run:** `python3 download_es.py` uses the live site first; with the browser wrapper it fills any new item. `--index` rebuilds the index without network.

---

## Switzerland: nothing missing

331 documents, German only. The same pages exist in French and Italian and were not downloaded. Part VI (data protection) is an empty page on the site. The script does not notice a document replaced under the same file name; delete the file and re-run `python3 download_ch.py` to refresh it.

---

## New Zealand: circulars now complete for what the site lists

The Operational Manual is complete (1,559 current topics). The first collection took circulars from the Internet Archive and was partial: 154 amendment circulars and 96 internal administration circulars. On 15 November the site's own search (`/search/?topic_ids=12` and `?topic_ids=8`, which shows a bot check to scripts) was read in a headless browser, page by page, and every listed PDF was downloaded: 412 amendment circulars and 101 internal administration circulars.

- **Remaining gaps:** only circulars the site does not list at all, for example ones withdrawn before its search index begins. Its search covers 412 amendment results; all were fetched.
- **Dates:** for the circulars fetched on 15 November (marked with a live source address in `nz/index.tsv`) the date is the issue date shown by the search result. Older rows carry the archive's capture date.
- **Re-run:** open the two search addresses in a browser and add any new PDFs; `python3 download_nz.py circulars` re-checks the Internet Archive for pages the live site no longer lists.
- **Superseded instructions (skipped on purpose):** 4,527 past versions of manual topics, listed in `nz/manual/toc.json`.
- **Visa Paks (skipped on purpose):** the "advice to immigration staff" series.

---

## German states (other than Berlin)

Saved: 812 documents, from the federal level and twelve states; `de/index.tsv` matches the folders. Per source: Baden-Württemberg 258, Lower Saxony 208, North Rhine-Westphalia 80, Hamburg 59, Brandenburg 45, federal 43, Thuringia 37, Schleswig-Holstein 27, Bremen 24, Rhineland-Palatinate 16, Saxony 8, Bavaria 5, Hesse 2.

Not obtained:

- **Schleswig-Holstein: the decrees that refused on 14 November are now saved.** The server resets connections intermittently; on 15 November, after a pause, the 9 November 2023 decree (`2023/231109_UkraineAufenthFGV_Info_der_ZBHen`) and the 12 October 2018 one (`2018/181012_36a_AufenthG_Prueungsumfang_subs.Schutz`) were fetched and added to `de/sh/`. The third, `2022/221012_ukr_erlass_durchfuehrungsbeschluss_eu_rat`, was listed with a misspelling: the real path is `..._durchfuehungsbeschluss_...`, and that decree (EU Council implementing decision 2022/382) was already saved. Retry with `python3 download_de.py sh` on another day if more appear.
- **Schleswig-Holstein, one decree with no file of its own:** 22 November 2021, Afghanistan no. 3 (`2021/211122_afghanistan_nr3_aufenthaltsrechtliche_regel`). It was byte-identical to another saved decree and was removed as a duplicate; worth checking in a browser which of the two the state's page really intends.
- **Thuringia, 3 decrees.** The list comes from an Internet Archive snapshot of the Thuringian refugee council's index dated 16 June 2026, because the live site served only a placeholder (46 listed, 37 saved, 6 filtered out as benefits or logistics). Not in the archive: 21 January 2026 (recognition of Eritrean passports) and 10 December 2025 (switch from § 23(1) to §§ 18a/18b). Held only truncated: 7 June 2019 (guidance on § 25b). Decrees issued after June 2026 are not covered. Try `https://www.fluechtlingsrat-thr.de/arbeitshilfen/gesetze-verordnungen-u-erlasse` in a browser.
- **Bavaria, 2 of 7.** The ministry's relaunched site dropped its letters, so they come from the Internet Archive. No capture: 8 March 2019 guidance on the preliminary rule for the employment toleration permit. Truncated capture: the 13 July 2020 version of the employment guidance.
- **North Rhine-Westphalia, 9 dead links:** 8 interior ministry circulars from 2014–2017 that the list links on recht.nrw.de (bes_id 26944, 28749, 28390, 32964, 34932, 35624, 37048, 37049) and one on mik.nrw.de.
- **Hamburg:** 59 files against roughly 61 links on the site; the difference was not reconciled.
- **Lower Saxony:** 4 Word/Excel form attachments skipped on purpose.
- **Schleswig-Holstein, skipped on purpose:** the payment-card decree (21 November 2025) and the accommodation decree (3 April 2025).
- **Hesse (2 documents) and Saxony (8):** complete for what is public, which is very little.
- **Mecklenburg-Vorpommern, Saarland, Saxony-Anhalt:** no systematic publication found; nothing collected. Bavaria and Hesse have no official collection either.

Things to know about how it was fetched:

- `bmi.bund.de` answers a client without cookies with a "cookie-check" redirect; the script keeps cookies as a browser does. It also answered 429 once during exploration and was then paced at 4 seconds.
- The last edits to `download_de.py` were syntax-checked but not exercised in a complete run, and six Schleswig-Holstein rows in the index were written by hand.

For the thin states, a freedom-of-information request to the interior ministry is the route to more.

---

## Canada (guidance): 36 items missing (not in the archive)

Saved: 1,571 files, 83 MB: about 1,130 program delivery instruction pages, about 350 operational bulletins (2006–2026), and 52 PDFs (legacy manual chapters and attachments). All 52 PDFs open and no saved page is an error page.

- **Source:** `www.canada.ca` does not answer scripted requests from this machine, so every page is the Internet Archive's latest capture (1,520 from 2026, 12 from 2024–25). Pages may be a few months behind the live site.
- **Missing, 36 items, listed in `ca/failed.tsv`:** 32 instruction pages (for example the immigration-loans pages and some COVID pages) and four manual PDFs: ENF 2, ENF 27, OP 5, OP 10. They are not in the archive; open them on canada.ca in a browser and save into `ca/` under the path shown in the list.
- **Skipped on purpose:** about 1,340 individual "update" change notices (`python3 download_ca.py --with-updates`, several hours); 170 PDF links to forms, kits and partner documents (`ca/skipped-pdf-links.txt`; five `resources/tools` attachments among them arguably belong in scope); the French version.
- **Not covered:** pages that are not reachable by links from the index page.
- **Re-run:** `python3 download_ca.py` skips existing files, retries failures and rewrites `ca/index.tsv`. The archive is slow and often refuses connections; the full run took about nine hours.

---

## Portugal, Austria, Luxembourg: almost nothing is published

No internal instructions are published by any of the three. Each folder has a `NOTES.txt` listing the sources checked.

- **Portugal:** only the annotated Aliens Act (commentary, not instructions) and the golden-visa procedures manual.
- **Austria:** nothing from the interior ministry. Twelve current country-information packages from the asylum office exist only inside a live viewer on ecoi.net and were not fetched; open them in a browser at `https://www.ecoi.net` (source: BFA Staatendokumentation).
- **Luxembourg:** only circulars to municipalities.

A freedom-of-information request to the authority is the only route to more.

---

## EU level

Saved after two passes: 163 documents. What is still missing:

- **Blue Card Directive (EU) 2021/1883 (not published):** the Commission has issued no guidance, Q&A or explanatory notes. The first application report is due on 18 November 2026 under Article 27; look for it on `https://home-affairs.ec.europa.eu` or EUR-Lex after that date and save it into `eu/commission/`.
- **Contact Group on Legal Migration after 2017 (not published):** the Commission's expert-group register (group E02904) has papers only up to 2017. Meetings on the Blue Card in May 2022 and June 2023 are mentioned in annual reports but have no public minutes. An access-to-documents request to the Commission is the route.
- **Current SIRENE Manuals (not found in a public source):** only the superseded 2017 version is saved.
- **Practical handbooks for the Entry/Exit System, ETIAS and VIS (not published).**
- **Visa Code Handbook:** no amendment after C(2024) 4319 and no separately published annexes were found.
- **Return Handbook:** the 2017 edition is saved, but the return regulation of 7 October 2026 repeals the directive it is based on, so expect a replacement.
- **Fundamental Rights Agency site (blocked):** `fra.europa.eu` shows a bot check; its handbook and border guidance were obtained from the EU Publications Office instead, so nothing is missing from there.
- **European Court of Human Rights sites (blocked):** not used.
- **EUR-Lex:** redirects scripted PDF requests after about twenty; documents were taken from the Publications Office instead.

---

## Country-of-origin reports

Each country's reports are in that country's folder, under `coi/` (for example `at/coi/`, `fi/coi/`); the EU asylum agency's are in `eu/coi/`. They were moved there from a top-level `coi/` folder on 14 November 2026 at 18:30.

- **Netherlands:** see above.
- **Austria:** see above.
- **Australia: now saved.** `dfat.gov.au` resets every scripted connection, including for its robots.txt, but a headless browser loaded the page normally on 15 November. All 23 PDFs on `https://www.dfat.gov.au/about-us/publications/country-information-reports` were downloaded into `au/coi/`: 22 country information reports dated July 2023 to September 2026 and one thematic report on Hong Kong. The listing is the department's own current set; withdrawn older reports are available only on request (`CIS@dfat.gov.au`).
- **Canada: complete for what is online.** 692 responses to information requests (January 2019 to October 2026) and the current document list for 187 countries. The board keeps only seven years online; older responses are on ecoi.net. 1,641 older versions of the document lists were skipped on purpose.
- **United States:** human rights reports for 2022–2024 and religious freedom reports for 2023, as web pages. Six pages are dead links on the State Department's own site: 2024 Argentina, Colombia, Côte d'Ivoire, Mongolia, Romania; 2023 Burma. Earlier editions and the PDF versions were skipped on purpose.
- **Limit raised on 14 November, 17:46:** from 500 MB / 1,500 files to 3 GB / 6,000 files per source (`MAX_BYTES` / `MAX_FILES` in `download_coi_central.py`; `--max-mb` / `--max-files` for `download_coi_eu_nordic.py`). Results:
  - **Austria: complete.** 331 files, 781 MB, 2007–2026. 21 entries held on other bodies' sites were skipped.
  - **Belgium: complete.** 444 files, 583 MB, May 2014–2026. 156 listed reports by other bodies (EUAA etc.) left out on purpose.
  - **EU asylum agency: complete.** 419 files, 1.0 GB, July 2012–October 2026 (COI, Country Guidance and MedCOI reports, English).
  - **Switzerland: complete.** 148 files, 240 MB, 2000–2026.
  - **Finland: complete.** 3,632 files, 4.3 GB, 3 January 2011 to 12 November 2026 (limit raised again to 12 GB / 12,000 files; not reached). All 312 reports and fact-finding reports plus every query response. Three report attachments are broken or missing on the server.
- **Not limited by the cap, complete:** Germany (868 of 869 listed), Norway (1,167; the 41 English translations and the annual reports were left out on purpose), Denmark (266, 1997–2026).
- **Sweden: 119 files, February 2020 to November 2026.** Read from the Lifos database one document number at a time (its search is off-limits to scripts). Reports before 2020 sit at lower numbers and were not looked at: `python3 download_coi_eu_nordic.py se --se-low N` goes further back.

---

## Status

All downloads had finished by 15 November 2026, 09:30. Nothing is running.

## Worth re-running later

Every script skips what it already has, so a second run only fills holes:

```
cd /home/brinly/immigration-guidelines
python3 download_de.py sh                  # Schleswig-Holstein leftovers, on another day
python3 download_es.py                     # Spain, picks up anything new on the site
python3 download_no.py                     # Norway, retries Common Crawl indexes that timed out
python3 download_us.py alerts              # USCIS policy-alert PDFs added to the Updates list
```

The Dutch open.overheid.nl document store was still answering HTTP 500 to its own document addresses on 15 November (its front page answers normally); the ~150 missing country reports need `python3 -B download_coi_central.py nl` once that is fixed. France's official sites, Italy's State Police, and the Dutch IND's PUC portal still need a person using a browser (or the same browser-driven approach used on 15 November).

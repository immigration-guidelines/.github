#!/usr/bin/env python3
"""Lithuania: procedure descriptions and agency-head criteria applied by immigration decision-makers.

    ./download_lt.py

Lithuania publishes no informal case-officer manual. What officials of the Migration
Department (Migracijos departamentas prie VRM), the State Border Guard Service (VSAT),
the police and the consulates work from are "procedure descriptions" (tvarkos aprašai),
criteria and one methodology (metodika) approved by order of a minister or of the head of
the agency and registered in the Register of Legal Acts (TAR, e-tar.lt).

The websites e-tar.lt, e-seimas.lrs.lt and migracija.lrv.lt answer scripts with a
Cloudflare bot check (HTTP 403), so they are NOT used. The texts come from the official
open-data copy of the register published by the Office of the Seimas:
    https://get.data.gov.lt/datasets/gov/lrsk/teises_aktai/   (robots.txt: allowed, Crawl-delay 5)
For each act in DOCS the script saves the text field of the consolidated version now in
force (model Suvestine), or of the act as adopted when the register has no consolidated
version (model Dokumentas), byte for byte as plain UTF-8 text. Annexes (mostly forms)
are not fetched.

Existing files are skipped, so the script can be re-run. Standard library only.
"""
import datetime
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

OUT = Path(__file__).resolve().parent / "lt"
UA = "immigration-guidelines-collector/1.0 (research archive)"
HOST = "https://get.data.gov.lt"
BASE = HOST + "/datasets/gov/lrsk/teises_aktai/"
DELAY = 5.0          # robots.txt Crawl-delay
G, P = "guidance", "procedural act"

# (adopted, number, issuer, kind, register id, file slug, Lithuanian title, English gloss)
# kind "guidance": criteria / methodology / instructions issued by the head of the deciding
#   agency for its own officials (formally still registered normative orders).
# kind "procedural act": ministerial orders approving the procedure description that is the
#   working manual for a type of case.
DOCS = [
    # --- Migration Department director ---
    ("2014-04-14", "3K-33", "MD", G, "ecc9f4e0c3a711e38c43fee5c144a67d", "entry-ban-period-criteria",
     "Dėl Kriterijų, kuriais vadovaujamasi nustatant ar sutrumpinant draudimo užsieniečiui atvykti į Lietuvos Respubliką laikotarpį arba išbraukiant duomenis apie užsienietį iš Užsieniečių, kuriems draudžiama atvykti į Lietuvos Respubliką, nacionalinio sąrašo, vertinimo tvarkos patvirtinimo",
     "Assessment of the criteria for setting or shortening an entry-ban period or removing an alien from the national list of aliens banned from entry"),
    ("2018-03-01", "3K-54", "MD", G, "ab5a8ee01d2e11e88e8fef3b3f51dc2f", "illegal-migration-risk-criteria",
     "Dėl Kriterijų, kuriais vadovaujamasi nustatant, ar yra rimtas pagrindas manyti, kad gali kilti užsieniečio nelegalios migracijos grėsmė, vertinimo tvarkos aprašo patvirtinimo",
     "Procedure for assessing the criteria for deciding whether there are serious grounds to believe an alien poses a risk of illegal migration"),
    ("2024-12-31", "3K-369", "MD", G, "e320cb20c76b11efa5ddd96c482819f5", "identity-establishment-methodology",
     "Dėl Asmens tapatybės nustatymo Migracijos departamente prie Lietuvos Respublikos vidaus reikalų ministerijos metodikos patvirtinimo",
     "Methodology for establishing a person's identity at the Migration Department"),
    ("2017-05-17", "3K-56", "MD", G, "78d30e403aec11e7b66ae890e1368363", "dublin-art-17-1-application",
     "Dėl 2013 m. birželio 26 d. Europos Parlamento ir Tarybos reglamento (ES) Nr. 604/2013 17 straipsnio 1 dalies taikymo",
     "On applying Article 17(1) (discretionary clause) of the Dublin III Regulation (EU) No 604/2013"),
    ("2019-06-28", "3K-94", "MD", G, "e5d67040999a11e9ae2e9d61b1f977b3", "minor-offence-criteria",
     "Dėl kriterijų, kuriais vadovaujantis administracinis nusižengimas laikomas mažai pavojingu, nustatymo",
     "Criteria by which an administrative offence is treated as minor"),
    ("2014-03-06", "3K-24", "MD", G, "a5fe4430a53911e3aeb49a67165e3ad3", "dublinet-reference-number",
     "Dėl „DubliNet“ sistema siunčiamuose dokumentuose naudojamo nuorodos numerio struktūros patvirtinimo ir suteikimo tvarkos",
     "Structure and assignment of the reference number used in documents sent through DubliNet"),
    ("2023-04-24", "3K-110", "MD", G, "9f53c070e25f11ed9978886e85107ab2", "international-sanctions-implementation",
     "Dėl Tarptautinių sankcijų, priskirtų Migracijos departamento prie Lietuvos Respublikos vidaus reikalų ministerijos kompetencijai, įgyvendinimo užtikrinimo tvarkos aprašo patvirtinimo",
     "Procedure for implementing the international sanctions that fall within the Migration Department's competence"),
    # --- State Border Guard Service commander ---
    ("2010-04-01", "4-232", "VSAT", G, "TAR.19ACBC2DCCE1", "visa-refusal-annulment-revocation-decisions-2010",
     "Dėl sprendimų dėl atsisakymo išduoti vizą, vizos panaikinimo bei vizos atšaukimo priėmimo",
     "On taking decisions to refuse, annul or revoke a visa (border guard, 2010)"),
    ("2019-07-10", "4-321", "VSAT", G, "dc890650a6c011e9b474d97de297fe08", "visa-refusal-annulment-revocation-decisions",
     "Dėl Sprendimų dėl atsisakymo išduoti vizą, vizos panaikinimo bei vizos atšaukimo priėmimo",
     "On taking decisions to refuse, annul or revoke a visa (border guard, 2019)"),
    ("2024-03-25", "4-139", "VSAT", G, "ee0024b0ea8911ee9f5b8ffa077f9188", "threat-checks-and-conclusions",
     "Dėl Duomenų apie užsieniečio keliamos grėsmės viešajai tvarkai ar visuomenei ir užsieniečio nelegalios migracijos grėsmės tikrinimo bei išvados dėl grėsmių rengimo tvarkos aprašo patvirtinimo",
     "Procedure for checking data on an alien's threat to public order or society and illegal-migration risk and for drawing up the conclusion on threats"),
    ("2024-11-18", "4-432", "VSAT", G, "70d7c891a5b811ef90b5ee8931e5ce5e", "identity-establishment-border-guard",
     "Dėl Užsieniečio asmens tapatybės nustatymo Valstybės sienos apsaugos tarnyboje prie Lietuvos Respublikos vidaus reikalų ministerijos tvarkos aprašo patvirtinimo",
     "Procedure for establishing an alien's identity at the State Border Guard Service"),
    ("2026-06-17", "4-235", "VSAT", G, "f5c474606a4011f1b53dfa020e517810", "assessment-and-return-decision-form",
     "Dėl užsieniečio įvertinimo atlikimo ir Sprendimo dėl įpareigojimo grįžti į užsienio valstybę, iš kurios atvykta, pavyzdinės formos patvirtinimo",
     "On carrying out the assessment of an alien and the model decision obliging return to the foreign state of arrival"),
    ("2026-06-26", "4-250", "VSAT", G, "fa064c20713811f1b53dfa020e517810", "screening-of-aliens-border-guard",
     "Dėl Užsieniečio tikrinimo Valstybės sienos apsaugos tarnyboje prie Lietuvos Respublikos vidaus reikalų ministerijos tvarkos aprašo patvirtinimo",
     "Procedure for the screening of aliens at the State Border Guard Service"),
    ("2012-04-20", "4-332", "VSAT", G, "TAR.DBFB7B62455B", "return-escorts",
     "Dėl Grąžinamų užsieniečių palydų organizavimo ir vykdymo tvarkos aprašo patvirtinimo",
     "Procedure for organising and carrying out escorts of returned aliens"),
    # --- Police commissioner general ---
    ("2015-08-31", "5-V-758", "PD", G, "64ebe690509c11e5b0f2b883009b2d06", "police-public-order-threat-checks-visa-consultation",
     "Dėl Duomenų apie užsienietį tikrinimo, siekiant nustatyti, ar užsienietis kelia grėsmę viešajai tvarkai ar visuomenei, išvados dėl grėsmės viešajai tvarkai ar visuomenei rengimo ir konsultacijos dėl vizos išdavimo tvarkos aprašo patvirtinimo",
     "Police procedure for checking whether an alien is a threat to public order or society, drawing up the conclusion and visa consultation"),
    # --- ministerial procedure descriptions (the working manuals) ---
    ("2004-12-24", "1V-429", "VRM", P, "TAR.6D1D7406D3E8", "return-expulsion-transit-decisions",
     "Dėl Sprendimų dėl užsieniečio įpareigojimo išvykti, išsiuntimo, grąžinimo ir vykimo tranzitu per Lietuvos Respublikos teritoriją priėmimo ir jų vykdymo tvarkos aprašo patvirtinimo",
     "Procedure for taking and enforcing decisions on obligation to leave, expulsion, return and transit of aliens"),
    ("2005-10-12", "1V-329", "VRM", P, "TAR.7CB7682A04DB", "temporary-residence-permits",
     "Dėl Leidimų laikinai gyventi Lietuvos Respublikoje užsieniečiams išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing temporary residence permits to aliens"),
    ("2005-12-21", "1V-445", "VRM", P, "TAR.AB0C074487E8", "long-term-resident-permits",
     "Dėl Lietuvos Respublikos ilgalaikio gyventojo leidimo gyventi Europos Sąjungoje išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing the long-term resident's permit to reside in the EU (permanent residence)"),
    ("2004-11-10", "1V-357", "VRM", P, "TAR.34A5B6DE6A4C", "aliens-passport",
     "Dėl Užsieniečio paso išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing an alien's passport"),
    ("2005-11-24", "1V-393", "VRM", P, "TAR.F5614710EB3E", "stateless-travel-document",
     "Dėl Asmens be pilietybės kelionės dokumento išdavimo taisyklių patvirtinimo",
     "Rules for issuing a stateless person's travel document"),
    ("2016-02-24", "1V-131", "VRM", P, "ebc768d0dadd11e583a295d9366c7ab3", "asylum-granting-and-withdrawal",
     "Dėl Prieglobsčio Lietuvos Respublikoje suteikimo ir panaikinimo tvarkos aprašo patvirtinimo",
     "Procedure for granting and withdrawing asylum in Lithuania (the asylum procedure manual)"),
    ("2019-02-22", "1V-194", "VRM", P, "5ed870e0367411e99595d005d42b863e", "eu-citizen-residence-certificate",
     "Dėl Teisės laikinai ar nuolat gyventi Lietuvos Respublikoje pažymėjimo išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing the certificate of the right of temporary or permanent residence (EU citizens)"),
    ("2019-06-28", "1V-594", "VRM", P, "e1cacab099a811e9ae2e9d61b1f977b3", "union-citizen-family-member-card",
     "Dėl Sąjungos piliečio šeimos nario leidimo laikinai ar nuolat gyventi šalyje kortelės išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing the residence card of a family member of a Union citizen"),
    ("2022-12-23", "1V-799", "VRM", P, "c8486f20829d11ed8df094f359a60216", "digital-temporary-residence-permit",
     "Dėl Skaitmeninio leidimo laikinai gyventi Lietuvos Respublikoje išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing the digital temporary residence permit"),
    ("2023-06-29", "1V-401", "VRM", P, "703670e0164311ee9f7ec2ffce8b47bc", "national-visa",
     "Dėl Nacionalinės vizos išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing a national visa"),
    ("2023-07-04", "V-227", "URM", P, "5a9d0b301a6311eeb233e8b04dc9bb3d", "schengen-visa",
     "Dėl Šengeno vizos išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing a Schengen visa (Ministry of Foreign Affairs)"),
    ("2025-03-10", "1V-159", "VRM", P, "755e6781fdaf11ef8619bb348379608d", "travel-authorisation",
     "Dėl Kelionės leidimo išdavimo tvarkos aprašo patvirtinimo",
     "Procedure for issuing a travel authorisation"),
    ("2026-06-23", "1V-461", "VRM", P, "c7a8bc616ebb11f1b53dfa020e517810", "alien-registration-certificate",
     "Dėl Užsieniečio registracijos pažymėjimo formos ir Užsieniečio registracijos pažymėjimo išdavimo tvarkos aprašo patvirtinimo",
     "Form of and procedure for issuing the alien's registration certificate"),
    ("2007-11-21", "V-101/1V-397", "URM+VRM", P, "TAR.380178B9C7A6", "travel-document-recognition",
     "Dėl Kelionės dokumentų, kurie suteikia teisę užsieniečiui atvykti į Lietuvos Respubliką, pripažinimo tvarkos aprašo ir Kelionės dokumentų, kurie suteikia teisę užsieniečiui atvykti į Lietuvos Respubliką, sąrašo patvirtinimo",
     "Procedure for recognising travel documents entitling an alien to enter Lithuania, and the list of such documents"),
    ("2021-09-21", "V-392", "URM", P, "94ae23101ad111ec93af8a5fb475d9bd", "asylum-applications-at-embassies",
     "Dėl Užsieniečių prašymų suteikti prieglobstį pateikimo Lietuvos Respublikos diplomatinėse atstovybėse ir konsulinėse įstaigose tvarkos aprašo patvirtinimo",
     "Procedure for lodging asylum applications at Lithuanian diplomatic missions and consular posts"),
    ("2023-02-07", "1V-45", "VRM", P, "9e6956f0a6f711ed8df094f359a60216", "aliens-relocated-for-work",
     "Dėl užsieniečių, kurie perkeliami dirbti į Lietuvos Respubliką",
     "On aliens who are relocated to work in Lithuania"),
    ("2021-08-14", "10V-31", "VRM", P, "26812960fcf811eb9f09e7df20500045", "accommodation-sites-and-procedural-actions",
     "Dėl Užsieniečių apgyvendinimo vietų administravimo, vidaus tvarkos ir procedūrinių veiksmų atlikimo taisyklių",
     "Rules on administration of aliens' accommodation sites, internal order and procedural actions (2021 mass-influx emergency)"),
    ("2014-04-23", "A1-229/1V-289/V-491", "SADM+VRM+SAM", P, "1df77b90cb7411e387b1ebf12f4d03ee", "unaccompanied-minors-age-assessment",
     "Dėl Lietuvos Respublikoje nustatytų nelydimų nepilnamečių užsieniečių, kurie nėra prieglobsčio prašytojai, amžiaus nustatymo, apgyvendinimo ir kitų procedūrinių veiksmų bei paslaugų jiems teikimo tvarkos aprašo patvirtinimo",
     "Procedure for age assessment, accommodation and other procedural steps for unaccompanied alien minors who are not asylum seekers"),
    ("2015-04-10", "1V-279/1A-196", "VRM+SADM", P, "bb3def10e1c611e4a4809231b4b55019", "expulsion-monitoring",
     "Dėl Užsieniečių išsiuntimo iš Lietuvos Respublikos stebėsenos vykdymo tvarkos aprašo patvirtinimo",
     "Procedure for monitoring the expulsion of aliens from Lithuania"),
    ("2007-10-04", "1V-340", "VRM", P, "TAR.416A9F142BD3", "detention-conditions-border-guard",
     "Dėl Sulaikytų užsieniečių laikymo Valstybės sienos apsaugos tarnyboje prie Lietuvos Respublikos vidaus reikalų ministerijos sąlygų ir tvarkos aprašo patvirtinimo",
     "Conditions and procedure for holding detained aliens at the State Border Guard Service"),
    ("2016-05-06", "1V-346", "VRM", P, "caf7f150135a11e6a23dfca0984f2ff9", "asylum-seekers-at-border-crossing-points",
     "Dėl Laikino prieglobsčio prašytojų apgyvendinimo pasienio kontrolės punktuose ir Valstybės sienos apsaugos tarnybos prie Lietuvos Respublikos vidaus reikalų ministerijos struktūriniuose padaliniuose sąlygų ir tvarkos aprašo patvirtinimo",
     "Conditions and procedure for temporary accommodation of asylum seekers at border crossing points and border guard units"),
    ("2007-01-29", "A1-22", "SADM", P, "TAR.F5E4D2AF23D8", "sufficient-means-of-subsistence",
     "Dėl pragyvenimo Lietuvos Respublikoje lėšų dydžio, kuris gali būti laikomas pakankamu pragyventi Lietuvos Respublikoje, užsieniečiui, prašančiam išduoti leidimą gyventi, nustatymo",
     "Amount of means of subsistence regarded as sufficient for an alien applying for a residence permit"),
]

# Known but not fetched (written to not-obtained.tsv together with any failures of this run).
NOT_FETCHED = [
    ("Original published files (DOCX/PDF) and annexes of the acts in index.tsv",
     "e-tar.lt answers scripts with a Cloudflare bot check (HTTP 403); text taken from the open-data copy instead; annexes (mostly forms) not fetched",
     "https://www.e-tar.lt/"),
    ("Migration Department website: legal information, FAQ and any guidance pages",
     "migracija.lrv.lt answers scripts with a Cloudflare bot check (HTTP 403 on robots.txt and all pages); not fetched",
     "https://migracija.lrv.lt/"),
    ("Seimas legal acts database copies of the same acts",
     "e-seimas.lrs.lt answers scripts with a Cloudflare bot check (HTTP 403); not fetched",
     "https://e-seimas.lrs.lt/"),
    ("Migration Department director's order 3K-319 (2020) on client service and 3K-195 (2024) on family-ties data requests",
     "front-office service rules, not decision guidance; left out on purpose",
     "https://www.e-tar.lt/"),
]


class Blocked(Exception):
    pass


_last = [0.0]


def api(path, *parts):
    """One polite GET against the open-data API; returns the parsed JSON."""
    url = BASE + path
    if parts:
        url += "?" + "&".join(urllib.parse.quote(p, safe='(),=._') for p in parts)
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        _last[0] = time.time()
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} from {HOST}") from e
        raise
    _last[0] = time.time()
    return json.loads(data), url


def fname(date, nr, slug):
    return f"{date}_{nr.replace('/', '_')}_{slug}.txt"


def fetch(doc_id):
    """Return (text, api_url, version note) for the consolidated version in force, else the act as adopted."""
    today = datetime.date.today().isoformat()
    rows, _ = api("Suvestine", f'dokumento_id="{doc_id}"',
                  "select(_id,suvestines_id,galioja_nuo,galioja_iki)", "limit(1000)")
    rows = [r for r in rows["_data"] if (r.get("galioja_nuo") or "")[:10] <= today]
    if rows:
        cur = max(rows, key=lambda r: r["galioja_nuo"])
        rec, url = api("Suvestine/" + cur["_id"])
        if rec.get("tekstas_lt"):
            return rec["tekstas_lt"], url, "consolidated version in force from " + cur["galioja_nuo"][:10]
    rows, url = api("Dokumentas", f'dokumento_id="{doc_id}"', "select(_id)", "limit(5)")
    if not rows["_data"]:
        return None, url, "not found in open data"
    rec, url = api("Dokumentas/" + rows["_data"][0]["_id"])
    return rec.get("tekstas_lt"), url, "as adopted (no consolidated version in the register)"


def main():
    OUT.mkdir(exist_ok=True)
    rp = urllib.robotparser.RobotFileParser(HOST + "/robots.txt")
    rp.read()
    if not rp.can_fetch(UA, BASE + "Dokumentas"):
        sys.exit("robots.txt of get.data.gov.lt disallows the dataset path; nothing fetched")
    _last[0] = time.time()

    meta_path = OUT / ".versions.json"          # remembers source URL and version of files already saved
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    failed = []
    try:
        for date, nr, issuer, kind, doc_id, slug, title, gloss in DOCS:
            name = fname(date, nr, slug)
            dest = OUT / name
            if dest.exists() and dest.stat().st_size > 0 and name in meta:
                continue
            try:
                text, url, note = fetch(doc_id)
            except Blocked:
                raise
            except Exception as e:                              # noqa: BLE001 - report, no retry
                print(f"  FAILED {nr}: {e}")
                failed.append((title, f"download failed: {e}", f"https://e-tar.lt/portal/lt/legalAct/{doc_id}"))
                continue
            if not text or len(text) < 200:
                print(f"  NO TEXT for {nr} ({note})")
                failed.append((title, "no text in the open-data record", f"https://e-tar.lt/portal/lt/legalAct/{doc_id}"))
                continue
            dest.write_text(text, encoding="utf-8")
            meta[name] = {"source_url": url, "note": note}
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  saved {name} ({len(text):,} chars; {note})")
    except Blocked as e:
        print(f"STOPPED: {e}. Host not used further in this run.")

    present = 0
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        for date, nr, issuer, kind, doc_id, slug, title, gloss in DOCS:
            name = fname(date, nr, slug)
            if not (OUT / name).exists() or name not in meta:
                if not any(t == title for t, _, _ in failed):
                    failed.append((title, "not downloaded in this run", f"https://e-tar.lt/portal/lt/legalAct/{doc_id}"))
                continue
            present += 1
            note = (f"{issuer} order No {nr}; {meta[name]['note']}; register page "
                    f"https://e-tar.lt/portal/lt/legalAct/{doc_id}")
            f.write("\t".join([name, title, date, meta[name]["source_url"], kind, gloss, note]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\treason\turl\n")
        for row in failed + NOT_FETCHED:
            f.write("\t".join(row) + "\n")
    print(f"lt: {present} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

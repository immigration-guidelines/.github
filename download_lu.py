#!/usr/bin/env python3
"""Luxembourg: ministerial circulars to the communes that concern the handling of foreigners.

    ./download_lu.py

Luxembourg publishes no procedures manual, service notes or guidelines of the
Direction générale de l'immigration (DGIM). The only published administrative
instructions on immigration case handling are the circulars that the Ministry of
Home Affairs sends to the communes (which take arrival declarations and issue
registration certificates), published since 2019 at
https://maint.gouvernement.lu/fr/circulaires.html (2023 onwards) and
https://maint.gouvernement.lu/fr/circulaires-old.html (2019-2022).
The list below is the hand-picked immigration subset of those ~1,600 circulars.

Files already downloaded are skipped, so the script can be re-run.
"""
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "lu"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
BASE = "https://maint.gouvernement.lu/dam-assets/circulaires/"

# (file name, title, date, path below BASE)
DOCS = [
    ("2019_circulaire-3689.pdf", "Circulaire n° 3689 - Déclaration d'arrivée de jeunes sous couvert d'un visa vacances-travail",
     "2019-04-04", "2019/janvier-juin/3689.pdf"),
    ("2019_circulaire-3692.pdf", "Circulaire n° 3692 - Conséquences du « BREXIT »",
     "2019-04-04", "2019/janvier-juin/3692.pdf"),
    ("2020_circulaire-3766.pdf", "Circulaire n° 3766 - Conséquences du « Brexit »",
     "2020-02-04", "2020/janvier-juin/3766.pdf"),
    ("2020_circulaire-3935.pdf", "Circulaire n° 3935 - Brexit et titres de séjour",
     "2020-12-16", "2020/juillet-decembre/3935.pdf"),
    ("2020_circulaire-3935_annexe-brexit.pdf", "Circulaire n° 3935 - annexe « Brexit »",
     "2020-12-15", "2020/juillet-decembre/3935-Brexit.pdf"),
    ("2020_circulaire-3935_annexe-titres-de-sejour.pdf", "Circulaire n° 3935 - annexe « Titres de séjour »",
     "2020-12-15", "2020/juillet-decembre/3935-Titres-de-sejour.pdf"),
    ("2021_circulaire-4001.pdf", "Circulaire n° 4001 - Mise en oeuvre du Règlement 2019/1157 - refonte du format des documents "
     "de séjour pour citoyens de l'Union et leurs membres de famille", "2021-06-11", "2021/janvier-juin/4001.pdf"),
    ("2021_circulaire-4027.pdf", "Circulaire n° 4027 - Mise en oeuvre du Règlement 2019/1157 - refonte du format des documents "
     "de séjour pour citoyens de l'Union et leurs membres de famille (complément)", "2021-08-02",
     "2021/juillet-decembre/4027.pdf"),
    ("2022_circulaire-4114.pdf", "Circulaire n° 4114 - Accueil des réfugiés ukrainiens qui fuient la guerre dans leur pays",
     "2022-03-04", "2022/janvier-juin/4114.pdf"),
    ("2022_circulaire-4119.pdf", "Circulaire n° 4119 - Protection temporaire pour les personnes ayant fui la guerre en Ukraine",
     "2022-03-11", "2022/janvier-juin/4119.pdf"),
    ("2022_circulaire-4136.pdf", "Circulaire n° 4136 - Informations sur le statut de protection temporaire pour les personnes "
     "ayant fui la guerre en Ukraine", "2022-04-22", "2022/janvier-juin/4136.pdf"),
    ("2023_circulaire-2023-085.pdf", "Circulaire n° 2023-085 - Mise en ligne de démarches électroniques dans le cadre des "
     "procédures d'immigration et échange des documents de séjour pour ressortissants de pays tiers", "2023-07-07",
     "2023/2023-085.pdf"),
    ("2024_circulaire-2024-027.pdf", "Circulaire n° 2024-027 - Modification des documents de la Direction de l'immigration, "
     "devenue la Direction générale de l'immigration", "2024-03-26", "2024/mars/2024-027.pdf"),
    ("2024_circulaire-2024-088.pdf", "Circulaire n° 2024-088 - Formulaires d'engagement de prise en charge d'une personne en vue "
     "d'un séjour au Grand-Duché de Luxembourg", "2024-11-28", "2024/novembre/2024-088.pdf"),
    ("2024_circulaire-2024-091.pdf", "Circulaire n° 2024-091 - Prolongation du régime de la protection temporaire accordée aux "
     "personnes ayant fui la guerre en Ukraine et nouveau format des documents de séjour", "2024-11-29",
     "2024/novembre/2024-091.pdf"),
    ("2025_circulaire-2025-044.pdf", "Circulaire n° 2025-044 - Inscription des étrangers sur le RNPP",
     "2025-07-10", "2025/2025-044.pdf"),
    ("2025_circulaire-2025-044_annexes-tableau-rnpp.pdf", "Circulaire n° 2025-044 - annexes 1 et 2 (tableau récapitulatif de la "
     "DGIM des cas d'inscription)", "2025-07-10", "2025/2025-044-tableau-rnpp-annexe1-et-2.pdf"),
    ("2026_circulaire-2026-076.pdf", "Circulaire 2026-076 - Modification concernant les autorisations de séjour temporaires pour "
     "les ressortissants de pays tiers pour un séjour supérieur à 90 jours", "2026-09-23", "2026/2026-076.pdf"),
    ("2026_circulaire-2026-076_annexe.pdf", "Circulaire 2026-076 - annexe (récapitulatif des cas d'inscription au RNPP à partir du 1er octobre 2026)", "2026-09-23", "2026/2026-076-annexe.pdf"),
]


def save(url, dest):
    """Download url to dest unless it is already there. Returns True if the file exists afterwards."""
    if dest.exists() and dest.stat().st_size > 0:
        return True
    time.sleep(0.5)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except Exception as e:                          # noqa: BLE001 - report and carry on, no retry
        print(f"  FAILED {url}: {e}")
        return False
    if not data.startswith(b"%PDF"):
        print(f"  NOT A PDF, skipped: {url}")
        return False
    dest.write_bytes(data)
    return True


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, title, date, path in DOCS:
        url = BASE + path
        if save(url, OUT / name):
            rows.append((name, title, date, url))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    print(f"lu: {len(rows)} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

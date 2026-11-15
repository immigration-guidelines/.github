#!/usr/bin/env python3
"""Austria: what little is published. See at/NOTES.txt for the sources checked.

    ./download_at.py

The Interior Ministry (BMI) publishes none of its decrees (Erlässe), circulars
(Rundschreiben) or handbooks on the Niederlassungs- und Aufenthaltsgesetz (NAG),
Fremdenpolizeigesetz or Asylgesetz: the federal decree collection in RIS
("Erlässe der Bundesministerien") holds no BMI document at all. The only decrees
in RIS that deal with aliens-law procedure are two of the Justice Ministry, addressed
to courts and prosecutors, on what they must report to the aliens authorities.
They are related material, not immigration-office instructions, and are saved
under at/related-bmj/.

Files already downloaded are skipped, so the script can be re-run.
"""
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "at"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
RIS = "https://ogd.ris.bka.gv.at/Dokumente/Erlaesse/"

# (file name, title, date, path below RIS)
DOCS = [
    ("related-bmj/2002-11-18_BMJ_Verstaendigung-der-Fremdenpolizei.pdf",
     "BMJ, Erlass vom 18. November 2002 über die Verständigung der Fremdenpolizei vom Verfahrensausgang im Wege einer "
     "Mitteilung an die Justizanstalt (JMZ 490001/105/II3/02)", "2002-11-18",
     "ERL_BMJ_20021118_490001_105_II3_02/ERL_BMJ_20021118_490001_105_II3_02.pdf"),
    ("related-bmj/2002-11-18_BMJ_Verstaendigung-der-Fremdenpolizei_Beilage-A.pdf",
     "BMJ, Erlass vom 18. November 2002 (JMZ 490001/105/II3/02) - Beilage A", "2002-11-18",
     "ERL_BMJ_20021118_490001_105_II3_02/07_20021118_490001105II302_A.pdf"),
    ("related-bmj/2002-11-18_BMJ_Verstaendigung-der-Fremdenpolizei_Beilage-B.pdf",
     "BMJ, Erlass vom 18. November 2002 (JMZ 490001/105/II3/02) - Beilage B", "2002-11-18",
     "ERL_BMJ_20021118_490001_105_II3_02/07_20021118_490001105II302_B.pdf"),
    ("related-bmj/2017-10-31_BMJ_Verstaendigungspflichten-in-Strafverfahren-gegen-Fremde.pdf",
     "BMJ, Erlass vom 31. Oktober 2017 über die Verständigungspflichten in Strafverfahren gegen Fremde "
     "(BMJ-S490.001/0007-IV 3/2017)", "2017-10-31",
     "ERL_BMJ_20171031_BMJ_S490_001_0007_IV_372017/ERL_BMJ_20171031_BMJ_S490_001_0007_IV_372017.pdf"),
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
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, title, date, path in DOCS:
        url = RIS + path
        if save(url, OUT / name):
            rows.append((name, title, date, url))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    print(f"at: {len(rows)} of {len(DOCS)} documents present")


if __name__ == "__main__":
    main()

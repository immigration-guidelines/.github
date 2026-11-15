#!/usr/bin/env python3
"""Turkey: the little case-handling guidance that is published, plus the implementing
regulations that officials actually work from. See tr/NOTES.txt for what was checked.

    python3 download_tr.py

The Presidency of Migration Management (Göç İdaresi Başkanlığı, goc.gov.tr) does not
publish its circulars (genelge), instructions (talimat) or directives (yönerge) on
residence permits, international protection, temporary protection or removal. Its
"Mevzuat" pages list only laws, regulations and one Prime Ministry circular, and every
file it hosts lies under /kurumlar/, which its robots.txt closes to scripts.

What this script saves into tr/:
  guidance        - two circulars printed in the Official Gazette (resmigazete.gov.tr)
                    and the Labour Ministry's published work-permit assessment criteria
                    and implementation guide (csgb.gov.tr);
  procedural act  - the consolidated implementing regulations (mevzuat.gov.tr), kept
                    because they are the working manual in the absence of anything else
                    (PDF where the site offers one, otherwise its Word file).

Rules followed: robots.txt is read for every host before the first request and obeyed;
requests are sequential with a pause; a host that answers 403 or 429 is dropped for the
rest of the run; nothing is retried. Files that exist are skipped, so re-running only
fills gaps. tr/index.tsv and tr/not-obtained.tsv are rewritten on every run.
Standard library only (pdfinfo is used to check PDFs when it is installed).
"""
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

OUT = Path(__file__).resolve().parent / "tr"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
DELAY = 1.5                      # seconds between requests to the same host

RG = "https://www.resmigazete.gov.tr/eskiler/"
MV = "https://www.mevzuat.gov.tr/MevzuatMetin/"
CSGB = "https://csgb.gov.tr/"

# (file, Turkish title, English gloss, date, url, kind, official, text that must be in an HTML page)
DOCS = [
    # --- guidance ---------------------------------------------------------------------
    ("2014-04-16_Basbakanlik-Genelgesi-2014-6_Geri-Kabul-Anlasmasi.htm",
     "Başbakanlık Genelgesi 2014/6 - Geri Kabul Anlaşması (Resmî Gazete 16.04.2014, sayı 28974)",
     "Prime Ministry Circular 2014/6 on the EU-Turkey Readmission Agreement: tasks of the migration "
     "administration and other bodies in preparing for readmission",
     "2014-04-16", RG + "2014/04/20140416-10.htm", "guidance", "yes", b"GENELGE"),
    ("2025-01-25_Cumhurbaskanligi-Genelgesi-2025-2_Goc-Yonetiminde-Koordinasyon.pdf",
     "Göç Yönetiminde Koordinasyon ile İlgili 2025/2 Sayılı Cumhurbaşkanlığı Genelgesi "
     "(Resmî Gazete 25.01.2025, sayı 32793)",
     "Presidential Circular 2025/2 on coordination in migration management (entry, stay, protection "
     "and removal work to be coordinated by the Presidency of Migration Management)",
     "2025-01-25", RG + "2025/01/20250125-5.pdf", "guidance", "yes", None),
    ("2021-11_UIGM_Gecici-Koruma-Calisma-Izni-Uygulama-Rehberi.pdf",
     "Geçici Koruma Sağlanan Yabancıların Çalışma İzni ve Çalışma İzni Muafiyetine Dair Uygulama Rehberi "
     "(Uluslararası İşgücü Genel Müdürlüğü, Kasım 2021)",
     "Implementation guide on work permits and work-permit exemptions for foreigners under temporary "
     "protection (Directorate General of International Labour Force, November 2021)",
     "2021-11", CSGB + "Media/11ep3re3/" + urllib.parse.quote(
         "geçici-koruma-sağlanan-yabancıların-çalışma-izinlerine-dair-uygulama-rehber.pdf"),
     "guidance", "yes", None),
    ("2024-10-01_UIGM_Calisma-Izni-Degerlendirme-Kriterleri.html",
     "Çalışma İzni Başvurusu Değerlendirme Kriterleri (Uluslararası İşgücü Genel Müdürlüğü; "
     "01.10.2024 tarihinde yürürlüğe giren kriterler, web sayfası)",
     "Work-permit application assessment criteria applied by the Directorate General of International "
     "Labour Force (criteria in force from 1 October 2024; web page as published)",
     "2024-10-01", CSGB + "uigm/calisma-izni/calisma-izni-degerlendirme-kriterleri/",
     "guidance", "yes", "Mali yeterlilik kriteri".encode()),
    # --- procedural acts: the working manual, consolidated texts ------------------------
    ("2014-04-22_Yonetmelik_Kabul-ve-Barinma-Merkezleri-ile-Geri-Gonderme-Merkezleri.doc",
     "Kabul ve Barınma Merkezleri ile Geri Gönderme Merkezlerinin Kurulması, Yönetimi, İşletilmesi, "
     "İşlettirilmesi ve Denetimi Hakkında Yönetmelik (güncel metin)",
     "Regulation on the establishment, management, operation and inspection of reception and "
     "accommodation centres and removal centres (consolidated text)",
     "2014-04-22", MV + "yonetmelik/7.5.19614.doc", "procedural act", "yes", None),
    ("2014-10-22_Yonetmelik_Gecici-Koruma-Yonetmeligi.pdf",
     "Geçici Koruma Yönetmeliği (2014/6883; güncel metin)",
     "Temporary Protection Regulation (consolidated text)",
     "2014-10-22", MV + "21.5.20146883.pdf", "procedural act", "yes", None),
    ("2016-01-15_Yonetmelik_Gecici-Koruma-Saglanan-Yabancilarin-Calisma-Izinleri.pdf",
     "Geçici Koruma Sağlanan Yabancıların Çalışma İzinlerine Dair Yönetmelik (2016/8375; güncel metin)",
     "Regulation on work permits of foreigners under temporary protection (consolidated text)",
     "2016-01-15", MV + "3.5.20168375.pdf", "procedural act", "yes", None),
    ("2016-03-17_Yonetmelik_YUKK-Uygulanmasina-Iliskin-Yonetmelik.pdf",
     "Yabancılar ve Uluslararası Koruma Kanununun Uygulanmasına İlişkin Yönetmelik (güncel metin)",
     "Regulation on the implementation of the Law on Foreigners and International Protection: visas, "
     "residence permits, removal, international protection procedure (consolidated text)",
     "2016-03-17", MV + "yonetmelik/7.5.21460.pdf", "procedural act", "yes", None),
    ("2016-03-17_Yonetmelik_Insan-Ticaretiyle-Mucadele-ve-Magdurlarin-Korunmasi.doc",
     "İnsan Ticaretiyle Mücadele ve Mağdurların Korunması Hakkında Yönetmelik (güncel metin)",
     "Regulation on combating human trafficking and protecting victims, incl. victim identification "
     "and residence permits (consolidated text)",
     "2016-03-17", MV + "yonetmelik/7.5.21459.doc", "procedural act", "yes", None),
    ("2016-04-26_Yonetmelik_Uluslararasi-Koruma-Basvuru-ve-Statu-Sahiplerinin-Calismasi.doc",
     "Uluslararası Koruma Başvuru Sahibi ve Uluslararası Koruma Statüsü Sahibi Kişilerin Çalışmasına Dair "
     "Yönetmelik (güncel metin)",
     "Regulation on the employment of international protection applicants and status holders "
     "(consolidated text)",
     "2016-04-26", MV + "yonetmelik/7.5.21517.doc", "procedural act", "yes", None),
    ("2022-02-02_Yonetmelik_Uluslararasi-Isgucu-Kanunu-Uygulama-Yonetmeligi.pdf",
     "Uluslararası İşgücü Kanunu Uygulama Yönetmeliği (güncel metin)",
     "Implementing Regulation of the International Labour Force Law: work-permit procedure "
     "(consolidated text)",
     "2022-02-02", MV + "yonetmelik/7.5.39337.pdf", "procedural act", "yes", None),
]

# Items known to exist that this script does not fetch: (item, date, reason, url)
NOT_OBTAINED = [
    ("Göç İdaresi Başkanlığı / Genel Müdürlüğü genelgeleri (circulars of the migration authority, e.g. 2014/11, "
     "2014/13, 2016/8, 2017/10, 2019/1 and others cited in court decisions and NGO reports)", "",
     "not published by the authority; no official text exists online", "https://www.goc.gov.tr/ulusal-mevzuat"),
    ("180 Gün İçinde 90 Gün Kalış Kuralının Uygulanması Genelgesi 2014/14 (GİGM circular on the 90/180-day rule)",
     "2014-05-21", "only copy found is in a commercial legal database behind a subscription wall (unofficial)",
     "https://www.lexpera.com.tr/mevzuat/genelgeler/180-gun-icinde-90-gun-kalis-kuralinin-uygulanmasi-genelgesi-2014-14"),
    ("İnsani İkamet İzni Genelgesi 2017/1 (GİGM circular on humanitarian residence permits)", "2017",
     "only copy found is in a commercial legal database behind a subscription wall (unofficial)",
     "https://www.lexpera.com.tr/mevzuat/genelgeler/insani-ikamet-izni-genelgesi-2017-1-1"),
    ("Göç İdaresi Genel Müdürlüğü Mesleki Etik Kurallarına İlişkin Usul ve Esaslar Genelgesi 2015/5 "
     "(staff ethics circular)", "2015",
     "only copy found is in a commercial legal database behind a subscription wall (unofficial)",
     "https://www.lexpera.com.tr/mevzuat/genelgeler/goc-idaresi-genel-mudurlugu-mesleki-etik-kurallarina-iliskin-usul-ve-esaslar-genelgesi-2015-5"),
    ("Göç İdaresi Genel Müdürlüğü Taşra Teşkilatı Birimleri Görev ve Çalışma Yönergesi; Gönüllü Geri Dönüş "
     "Büroları Görev ve Çalışma Yönergesi; Geçici Barınma Merkezlerinin Kurulması, Yönetilmesi ve "
     "İşletilmesine İlişkin Yönerge (internal directives)", "",
     "only copies found are in a commercial legal database behind a subscription wall (unofficial)",
     "https://www.lexpera.com.tr/mevzuat/yonergeler/goc-idaresi-genel-mudurlugu-tasra-teskilati-birimleri-gorev-ve-calisma-yonergesi-3"),
    ("Geçici Koruma Yönetmeliği - İngilizce (official English translation of the Temporary Protection Regulation)",
     "2014-10-22", "robots.txt of goc.gov.tr disallows /kurumlar/ for all user agents",
     "https://www.goc.gov.tr/kurumlar/goc.gov.tr/Gecici-Koruma-Yonetmeligi-Ingilizce.pdf"),
    ("Geçici Koruma Yönetmeliği - Arapça (official Arabic translation)", "2014-10-22",
     "robots.txt of goc.gov.tr disallows /kurumlar/ for all user agents",
     "https://www.goc.gov.tr/kurumlar/goc.gov.tr/Gecici-Koruma-Yonetmeligi-Arapca.pdf"),
    ("AFAD Genelgesi 2014/4 - Geçici Koruma Altındaki Yabancılara İlişkin Hizmetlerin Yürütülmesi "
     "(disaster agency circular on services for foreigners under temporary protection)", "2014-12-18",
     "robots.txt pattern /kurumlar/ (same government web platform); the host's TLS certificate also failed "
     "verification from this machine",
     "https://www.afad.gov.tr/kurumlar/afad.gov.tr/2311/files/Gecici-Koruma_Altindaki_Yabancilara_Iliskin_Hizmetlerin_Yurutulmesi_2014-4_.pdf"),
    ("NVİGM talimatı - Yabancılara kimlik numarası verilmesi ve adres kayıtlarının tutulması "
     "(population directorate instruction on foreigners' identity numbers and address records)", "",
     "robots.txt of nvi.gov.tr disallows /kurumlar/ for all user agents",
     "https://www.nvi.gov.tr/kurumlar/nvi.gov.tr/mevzuat/nufusmevzuat/talimat/yabancilarakimliknumarasiverilmesiveadreskayitlarinintutulmasi.pdf"),
    ("NVİGM talimatı - Yabancıların adres bildirim işlemleri (24.11.2016)", "2016-11-24",
     "robots.txt of nvi.gov.tr disallows /kurumlar/ for all user agents",
     "https://www.nvi.gov.tr/kurumlar/nvi.gov.tr/mevzuat/nufusmevzuat/talimat/adresislemleri/24112016-yabancilarinadresbildirimislemleri.pdf"),
    ("NVİGM talimatı - Mülteciler ve geçici koruma altına alınanların evlenme ve çocuklarının tanınması işlemleri",
     "2015", "robots.txt of nvi.gov.tr disallows /kurumlar/ for all user agents",
     "https://nvi.gov.tr/kurumlar/nvi.gov.tr/mevzuat/nufusmevzuat/talimat/multecilergecicikorumaaltinaalinanlarinevlenmecocuklarinintaninmasi.pdf"),
    ("YÖK yazısı 02.08.2026 (Göç İdaresi Başkanlığının 29.07.2026 tarihli yazısını aktarır) - Türkiye'de "
     "yükseköğrenimini tamamlayanlara verilecek kısa dönem ikamet izni", "2026-08-02",
     "left out on purpose: the document is marked HİZMETE ÖZEL (for official use only) and is only on a "
     "university site (unofficial copy)",
     "https://gevhernesibe.erciyes.edu.tr/EditorUpload/Files/turkiyede-yuksekogrenimini-tamamlayanlara-verilecek-kisa-donem-ikamet-izni-hk_mOcRxd1nk60.pdf"),
    ("Göç İdaresi Başkanlığı yazısı 27.06.2024, E-18664661-000-272105 - Yasal kalış hakkı bulunmayan yabancılar "
     "(letter to the Council of Higher Education on university admissions)", "2024-06-27",
     "left out on purpose: addressed to universities, not to case officers; only on a university site "
     "(unofficial copy)",
     "https://sbu.edu.tr/uploads/e4ad3128-e5e5-1ff4-89b0-3a0814c580b4/yasal_kals_hakk_bulunmayan_yabanclar.pdf"),
    ("İçişleri Bakanlığı Genelge No. 57 (22.06.2006) 'Uygulama Talimatı' and Genelge 2010/18, 2010/19 "
     "(pre-2013 asylum implementation instructions, superseded)", "2006-06-22",
     "no official copy found online; an English translation was hosted on refworld.org, which answers "
     "scripted requests with a bot check (HTTP 403)", "https://www.refworld.org/"),
]


class Site:
    """One host: robots.txt read once, sequential paced requests, dropped on 403/429."""
    sites = {}

    def __init__(self, host):
        self.host = host
        self.blocked = None
        self.last = 0.0
        self.rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"https://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                self.rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                self.blocked = f"robots.txt answered HTTP {e.code}"
            else:
                self.rp.parse([])                  # no robots.txt: nothing is disallowed
        except Exception as e:                     # noqa: BLE001
            self.blocked = f"robots.txt not readable: {e}"
        self.last = time.time()

    @classmethod
    def of(cls, url):
        host = urllib.parse.urlsplit(url).netloc
        if host not in cls.sites:
            cls.sites[host] = cls(host)
        return cls.sites[host]

    def get(self, url):
        """Returns (data, None) or (None, reason)."""
        if self.blocked:
            return None, self.blocked
        if not self.rp.can_fetch("*", url):
            return None, "disallowed by robots.txt"
        time.sleep(max(0.0, DELAY - (time.time() - self.last)))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                self.blocked = f"HTTP {e.code} from {self.host}; host dropped for this run"
            return None, f"HTTP {e.code}"
        except Exception as e:                     # noqa: BLE001 - report, no retry
            return None, str(e)
        finally:
            self.last = time.time()
        return data, None


def pdf_ok(path):
    """True if the file is a readable PDF (pdfinfo when available, else the header)."""
    with open(path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            return False
    if shutil.which("pdfinfo"):
        return subprocess.run(["pdfinfo", str(path)], capture_output=True).returncode == 0
    return True


def save(url, dest, marker):
    """Download url to dest unless present. Returns None on success, else the reason."""
    if dest.exists() and dest.stat().st_size > 0:
        return None
    data, why = Site.of(url).get(url)
    if data is None:
        return why
    if dest.suffix == ".pdf":
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        if not pdf_ok(tmp):
            tmp.unlink()
            return "not a valid PDF (error page?)"
        tmp.rename(dest)
    elif dest.suffix == ".doc":
        # mevzuat.gov.tr serves either a binary Word file or Word's UTF-16 HTML export as ".doc"
        word_html = data.startswith(b"\xff\xfe") and "YÖNETMEL".encode("utf-16-le") in data
        if not (data.startswith(b"\xd0\xcf\x11\xe0") or word_html):
            return "not a Word document (error page?)"
        dest.write_bytes(data)
    else:
        if marker and marker not in data:
            return "page does not contain the expected text (error or bot-check page?)"
        dest.write_bytes(data)
    return None


def main():
    OUT.mkdir(exist_ok=True)
    rows, failed = [], []
    for name, title, gloss, date, url, kind, official, marker in DOCS:
        why = save(url, OUT / name, marker)
        if why is None:
            rows.append((name, title, date, url, kind, official, gloss))
        else:
            print(f"  NOT SAVED {name}: {why}")
            failed.append((title, date, why, url))
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\tofficial\ttitle_en\n")
        for row in rows:
            f.write("\t".join(row) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("item\tdate\treason\turl\n")
        for row in failed + NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    guid = sum(1 for r in rows if r[4] == "guidance")
    print(f"tr: {len(rows)} of {len(DOCS)} documents present "
          f"({guid} guidance, {len(rows) - guid} procedural acts); "
          f"{len(failed) + len(NOT_OBTAINED)} items listed in not-obtained.tsv")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Czech Republic: the little internal guidance on residence and temporary protection that the
Ministry of the Interior has released, plus its own statements about (not) having any.

    ./download_cz.py

The Department for Asylum and Migration Policy (OAMP) of the Ministry of the Interior decides
residence permits, long-term visas, temporary protection and asylum. It publishes no manual,
methodological instructions or circulars. What reaches the public does so through answers to
freedom-of-information requests (Act 106/1999), which the Ministry must publish:
    https://mv.gov.cz/106---cizinecka-problematika            (2026 onwards)
    https://archiv.mv.gov.cz/clanek/informace-podle-zakona-106.aspx   (frozen archive, 2010 - 2026)
Both hosts' robots.txt allow everything ("Disallow:" empty); the script reads them first.

Saved by this script (lists below were picked by hand after reading the listings):
  cz/                GUIDANCE - the released staff manual "Ukrajina - dočasná ochrana a rozhodování"
                     and one methodological statement of OAMP; PROCEDURAL - the rules of
                     procedure of the appeal Commission. These three are in index.tsv.
  cz/foi-replies/    the Ministry's FOI answers that ask about internal instructions and
                     methodologies (mostly: none exists / refused). Evidence, not guidance;
                     listed in foi-replies.tsv, not in index.tsv.

Files already downloaded are skipped, so the script can be re-run. Standard library only.
"""
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

OUT = Path(__file__).resolve().parent / "cz"
UA = "immigration-guidelines-collector/1.0 (research archive)"
DELAY = 1.5
ARCH = "https://archiv.mv.gov.cz/soubor/"

# (file, date, kind, title, English gloss, url, note)
MAIN = [
    ("2024-02-09_ukrajina-docasna-ochrana-a-rozhodovani_MV-103504-3-OAM-2024-priloha.pdf", "2024-02-09", "guidance",
     "Ukrajina – dočasná ochrana a rozhodování (verze 9. února 2024)",
     "Ukraine - temporary protection and decision-making (version of 9 February 2024): 90-page OAMP staff manual on "
     "granting, extending and withdrawing temporary protection and on tolerated-stay visas",
     ARCH + "mv-103504-3-oam-2024-priloha.aspx",
     "internal staff manual released (with redactions) under Act 106/1999 on 22 July 2024, ref. MV-103504-3/OAM-2024; "
     "listing page https://archiv.mv.gov.cz/clanek/poskytnuti-informace-material-ukrajina-docasna-ochrana-a-rozhodovani.aspx"),
    ("2026-07-13_metodicke-vyjadreni-bankovni-potvrzeni_MV-6912-58-OAM-2026.pdf", "2026-07-13", "guidance",
     "Žádost o metodické vyjádření – odpověď (zajišťování bankovních potvrzení třetími osobami pro účely vízových a pobytových řízení), č. j. MV-6912-58/OAM-2026",
     "Methodological statement of OAMP: bank confirmations arranged by third parties as proof of funds in visa and "
     "residence proceedings are circumvention of the law and ground for refusal or revocation",
     "https://mv.gov.cz/documents/mv-116350-2oam-2026-priloha3?disposition=attachment",
     "2-page statement addressed to an outside requester, published as attachment 3 of FOI answer MV-116350-2/OAM-2026; "
     "listing page https://mv.gov.cz/poskytnuti-informace---zadost-o-metodicke-vyjadreni--kdo-jej-podal"),
    ("2020-09-10_jednaci-rad-komise-pro-rozhodovani-ve-vecech-pobytu-cizincu.pdf", "2020-09-10", "procedural act",
     "Jednací řád Komise pro rozhodování ve věcech pobytu cizinců",
     "Rules of procedure of the Commission for Decisions on the Residence of Foreigners (the appeal body)",
     ARCH + "jednaci-rad-komise-pro-rozhodovani-ve-vecech-pobytu-cizincu.aspx",
     "internal rules adopted by the Commission under § 170a(9) of Act 326/1999 and Minister's Instruction No 2/2011; "
     "date is the PDF creation date; listing page https://archiv.mv.gov.cz/clanek/komise-pro-rozhodovani-ve-vecech-pobytu-cizincu.aspx"),
]

# (file, date, reference, title of the published answer, English gloss, url, listing page)
FOI = [
    ("2020-06-23_MV-100357-2-OAM-2020.pdf",
     "2020-06-23",
     "MV-100357-2/OAM-2020",
     "Poskytnutí informace - cizinecká a azylová problematika",
     "Aliens and asylum matters (states that no internal rule governs the allocation of case files)",
     "https://archiv.mv.gov.cz/soubor/mv-100357-2-oam-2020.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-cizinecka-a-azylova-problematika.aspx"),
    ("2020-08-17_MV-132199-2-OAM-2020.pdf",
     "2020-08-17",
     "MV-132199-2/OAM-2020",
     "Poskytnutí informace - interní akty odboru azylové a migrační politiky",
     "Internal acts of OAMP (states that the Ministry issues no internal acts, directives or written instructions on applying the Residence of Foreigners Act; staff follow the Act alone)",
     "https://archiv.mv.gov.cz/soubor/mv-132199-2-oam-2020.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-interni-akty-odboru-azylove-a-migracni-politiky.aspx"),
    ("2020-09-16_MV-146776-2-OAM-2020.pdf",
     "2020-09-16",
     "MV-146776-2/OAM-2020",
     "Poskytnutí informace - statistiky dlouhodobých víz a dlouhodobých pobytů",
     "Statistics on long-term visas and residence (the answer also addresses whether a methodological instruction exists for certain visa applications over 90 days)",
     "https://archiv.mv.gov.cz/soubor/mv-146776-2-oam-2020.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-statistiky-dlouhodobych-viz-a-dlouhodobych-pobytu.aspx"),
    ("2020-11-30_MV-187216-2-OAM-2020.pdf",
     "2020-11-30",
     "MV-187216-2/OAM-2020",
     "Poskytnutí informace - fungování pracovišť OAMP během nouzového stavu",
     "Operation of OAMP offices during the state of emergency (says Director's Instructions No 21 and 22 of 2020 were sent to the requester; the attachments are not published)",
     "https://archiv.mv.gov.cz/soubor/mv-187216-2-oam-2020.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-fungovani-pracovist-oamp-behem-nouzoveho-stavu.aspx"),
    ("2021-03-24_MV-49456-2-OAM-2021.pdf",
     "2021-03-24",
     "MV-49456-2/OAM-2021",
     "Poskytnutí informace - výpočet čistého měsíčního příjmu u cizinců podnikatelů, na které dopadly omezení v souvislosti s",
     "Calculating the net monthly income of self-employed foreigners affected by COVID-19 measures (no methodological instruction issued)",
     "https://archiv.mv.gov.cz/soubor/mv-49456-2-oam-2021.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-vypocet-cisteho-mesicniho-prijmu-u-cizincu-podnikatelu-na-ktere-dopadly-omezeni-v-souvislosti-s-epidemii-covid19.aspx"),
    ("2022-01-27_MV-23456-2-OAM-2022.pdf",
     "2022-01-27",
     "MV-23456-2/OAM-2022",
     "Poskytnutí informace - výjezdní příkaz po zániku zaměstnanecké karty",
     "Departure order after an employee card lapses (procedure not regulated by internal instructions)",
     "https://archiv.mv.gov.cz/soubor/mv-23456-2-oam-2022.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-vyjezdni-prikaz-po-zaniku-zamestnanecke-karty.aspx"),
    ("2022-08-17_MV-149568-OAM-2022.pdf",
     "2022-08-17",
     "MV-149568/OAM-2022",
     "Poskytnutí informace - dokument \"Ukrajina - dočasná ochrana a rozhodování\"",
     "Document 'Ukraine - temporary protection and decision-making' (partial refusal to release the staff manual, version valid from 24 June 2022)",
     "https://archiv.mv.gov.cz/soubor/mv-149568-oam-2022.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-dokument-ukrajina-docasna-ochrana-a-rozhodovani.aspx"),
    ("2022-12-13_MV-218562-2-OAM-2022.pdf",
     "2022-12-13",
     "MV-218562-2/OAM-2022",
     "Poskytnutí informace - zprostředkování zaměstnání pro cizince agenturou práce",
     "Employment agencies arranging work for foreigners (request for an opinion or internal instruction)",
     "https://archiv.mv.gov.cz/soubor/mv-218562-2-oam-2022.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-zprostredkovani-zamestnani-pro-cizince-agenturou-prace.aspx"),
    ("2023-01-19_MV-13811-2-OAM-2023.pdf",
     "2023-01-19",
     "MV-13811-2/OAM-2023",
     "Poskytnutí informace - dotaz na metodiku infolinky k objednávání cizinců pobývajících toho času v zahraničí",
     "Methodology of the information line for booking appointments (states that OAMP has no internal acts, directives or written instructions on this)",
     "https://archiv.mv.gov.cz/soubor/mv-13811-2-oam-2023.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-dotaz-na-metodiku-infolinky-k-objednavani-cizincu-pobyvajicich-toho-casu-v-zahranici.aspx"),
    ("2023-02-17_MV-29065-5-OAM-2023.pdf",
     "2023-02-17",
     "MV-29065-5/OAM-2023",
     "Poskytnutí informace - dokument \"Ukrajina - dočasná ochrana a rozhodování\", resp. metodické pomůcky pro rozhodování o ud",
     "Document 'Ukraine - temporary protection and decision-making' and other decision aids: fee notice describing the 79-page staff training manual",
     "https://archiv.mv.gov.cz/soubor/mv-29065-5-oam-2023.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-dokument-ukrajina-docasna-ochrana-a-rozhodovani-resp-metodicke-pomucky-pro-rozhodovani-o-udeleni-docasne-ochrany.aspx"),
    ("2023-04-24_MV-29065-5-OAM-2023_priloha.pdf",
     "2023-04-24",
     "MV-29065-5/OAM-2023 - příloha",
     "Poskytnutí informace - dokument \"Ukrajina - dočasná ochrana a rozhodování\", resp. metodické pomůcky pro rozhodování o ud",
     "Document 'Ukraine - temporary protection and decision-making': decision shelving the request because the search fee was not paid",
     "https://archiv.mv.gov.cz/soubor/mv-29065-5-oam-2023-priloha.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-dokument-ukrajina-docasna-ochrana-a-rozhodovani-resp-metodicke-pomucky-pro-rozhodovani-o-udeleni-docasne-ochrany.aspx"),
    ("2023-05-18_MV-89601-2-OAM-2023.pdf",
     "2023-05-18",
     "MV-89601-2/OAM-2023",
     "Poskytnutí informace - žádost o metodiky pro výpočet prostředků k ubytování pro účely trvalého a dlouhodobého pobytu",
     "Request for methodologies for calculating funds for accommodation for permanent and long-term residence (refused)",
     "https://archiv.mv.gov.cz/soubor/mv-89601-2-oam-2023.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-zadost-o-metodiky-pro-vypocet-prostredku-k-ubytovani-pro-ucely-trvaleho-a-dlouhodobeho-pobytu.aspx"),
    ("2023-10-13_MV-172075-OAM-2075.pdf",
     "2023-10-13",
     "MV-172075/OAM-2075",
     "Poskytnutí informace - úpravy pobytu cizinců pobývajících na území ČR za účelem činnosti au-pair",
     "Residence of foreigners working as au pairs (request for an opinion or internal instruction refused)",
     "https://archiv.mv.gov.cz/soubor/mv-172075-oam-2023.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-upravy-pobytu-cizincu-pobyvajicich-na-uzemi-cr-za-ucelem-cinnosti-au-pair.aspx"),
    ("2024-01-09_MV-15120-2-OAM-2024.pdf",
     "2024-01-09",
     "MV-15120-2/OAM-2024",
     "Poskytnutí informace - statistická data OAMP",
     "OAMP statistical data (also states that no internal act restricts long-term visas for Iranian nationals)",
     "https://archiv.mv.gov.cz/soubor/mv-15120-2-oam-2024.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-statisticka-data-oamp.aspx"),
    ("2024-07-22_MV-103504-3-OAM-2024.pdf",
     "2024-07-22",
     "MV-103504-3/OAM-2024",
     "Poskytnutí informace - materiál \"Ukrajina - dočasná ochrana a rozhodování\"",
     "Cover letter releasing the current version of the manual 'Ukraine - temporary protection and decision-making'",
     "https://archiv.mv.gov.cz/soubor/mv-103504-3-oam-2024.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-material-ukrajina-docasna-ochrana-a-rozhodovani.aspx"),
    ("2025-01-13_MV-7459-2-OAM-2025.pdf",
     "2025-01-13",
     "MV-7459-2/OAM-2025",
     "Poskytnutí informace - nařízení upravující postup povinného subjektu při rozhodování o žádostech o změnu účelu pobytu",
     "Alleged order to refuse changes of purpose from study to employee card (the Ministry states it issued no such order)",
     "https://archiv.mv.gov.cz/soubor/mv-7459-2-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-narizeni-upravujici-postup-povinneho-subjektu-pri-rozhodovani-o-zadostech-o-zmenu-ucelu-pobytu.aspx"),
    ("2025-07-08_MV-106121-4-OAM-2025.pdf",
     "2025-07-08",
     "MV-106121-4/OAM-2025",
     "Poskytnutí informace - nepřetržitý pobyt na území ČR započítatelný pro podání žádosti o trvalý pobyt",
     "Continuous residence countable towards an application for permanent residence",
     "https://archiv.mv.gov.cz/soubor/mv-106121-4-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-nepretrzity-pobyt-na-uzemi-cr-zapocitatelny-pro-podani-zadosti-o-trvaly-pobyt.aspx"),
    ("2025-07-09_MV-111100-2-OAM-2025.pdf",
     "2025-07-09",
     "MV-111100-2/OAM-2025",
     "Poskytnutí informace - (ne)zánik dočasné ochrany",
     "(Non-)termination of temporary protection (asks for the internal instructions defining which foreign visas or permits end temporary protection)",
     "https://archiv.mv.gov.cz/soubor/mv-111100-2-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-ne-zanik-docasne-ochrany.aspx"),
    ("2025-08-08_MV-127786-2-OAM-2025.pdf",
     "2025-08-08",
     "MV-127786-2/OAM-2025",
     "Poskytnutí informace - vysvětlení postupů v souvislosti s ukončením dočasné ochrany u osob zaměstnaných na území ČR",
     "Procedures connected with the end of temporary protection for persons employed in the Czech Republic",
     "https://archiv.mv.gov.cz/soubor/mv-127786-2-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-vysvetleni-postupu-v-souvislosti-s-ukoncenim-docasne-ochrany-u-osob-zamestnanych-na-uzemi-cr.aspx"),
    ("2025-08-11_MV-128851-2-OAM-2025.pdf",
     "2025-08-11",
     "MV-128851-2/OAM-2025",
     "Poskytnutí informace - povinnost osobní účasti dětí mladších 12 let při podání žádosti o pobytové oprávnění (2)",
     "Obligation of children under 12 to attend in person when an application is filed (request for internal rules)",
     "https://archiv.mv.gov.cz/soubor/mv-128851-2-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-povinnost-osobni-ucasti-deti-mladsich-12-let-pri-podani-zadosti-o-pobytove-opravneni-2.aspx"),
    ("2025-08-11_MV-128863-2-OAM-2025.pdf",
     "2025-08-11",
     "MV-128863-2/OAM-2025",
     "Poskytnutí informace - povinnost osobní účasti dětí mladších 12 let při podání žádosti o pobytové oprávnění",
     "Obligation of children under 12 to attend in person when an application is filed (request for internal rules, second answer)",
     "https://archiv.mv.gov.cz/soubor/mv-128863-2-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-povinnost-osobni-ucasti-deti-mladsich-12-let-pri-podani-zadosti-o-pobytove-opravneni.aspx"),
    ("2025-11-25_MV-182757-2-OAM-2025.pdf",
     "2025-11-25",
     "MV-182757-2/OAM-2025",
     "Poskytnutí informace - vzor rozhodnutí o zamítnutí žádosti o vydání zaměstnanecké karty",
     "Template decision refusing an employee card and an opinion of the methodology unit (answer)",
     "https://archiv.mv.gov.cz/soubor/mv-182757-2-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-vzor-rozhodnuti-o-zamitnuti-zadosti-o-vydani-zamestnanecke-karty.aspx"),
    ("2025-11-25_MV-182757-3-OAM-2025.pdf",
     "2025-11-25",
     "MV-182757-3/OAM-2025",
     "Poskytnutí informace - vzor rozhodnutí o zamítnutí žádosti o vydání zaměstnanecké karty",
     "Template decision refusing an employee card and an opinion of the methodology unit (partial refusal)",
     "https://archiv.mv.gov.cz/soubor/mv-182757-3-oam-2025.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-vzor-rozhodnuti-o-zamitnuti-zadosti-o-vydani-zamestnanecke-karty.aspx"),
    ("2026-01-29_MV-12347-3-OAM-2026.pdf",
     "2026-01-29",
     "MV-12347-3/OAM-2026",
     "Poskytnutí informace - dokument !Možnost realizace extradice a trestu vyhoštění na území Ukrajiny v kontextu probíhající",
     "Request for the current version of the manual 'Ukraine - temporary protection and decision-making' (refused, January 2026)",
     "https://archiv.mv.gov.cz/soubor/mv-12347-3-oam-2026.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-dokument-moznost-realizace-extradice-a-trestu-vyhosteni-na-uzemi-ukrajiny-v-kontextu-probihajiciho-ozbrojeneho-konfliktu-v-dusledku-agrese-ruske-federace-proti-ukrajine.aspx"),
    ("2026-03-06_MV-33913-2-OAM-2026.pdf",
     "2026-03-06",
     "MV-33913-2/OAM-2026",
     "Poskytnutí informace - výjezdní příkaz",
     "Departure order (asks for the internal methodology on its content; answer)",
     "https://mv.gov.cz/documents/mv-33913-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---vyjezdni-prikaz"),
    ("2026-03-06_MV-33913-3-OAM-2026.pdf",
     "2026-03-06",
     "MV-33913-3/OAM-2026",
     "Poskytnutí informace - výjezdní příkaz",
     "Departure order (asks for the internal methodology on its content; refusal)",
     "https://mv.gov.cz/documents/mv-33913-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---vyjezdni-prikaz"),
    ("2026-04-17_MV-61858-2-OAM-2026.pdf",
     "2026-04-17",
     "MV-61858-2/OAM-2026",
     "Poskytnutí informace - započitatelná doba délky pobytu do trvalého pobytu",
     "Countable length of residence for permanent residence (refusal; no internal instructions on Article 13 of Directive 2003/109/EC)",
     "https://archiv.mv.gov.cz/soubor/mv-61858-2-oam-2026.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-zapocitatelna-doba-delky-pobytu-do-trvaleho-pobytu.aspx"),
    ("2026-04-29_MV-71931-2-OAM-2026.pdf",
     "2026-04-29",
     "MV-71931-2/OAM-2026",
     "Poskytnutí informace - zkracování délky DP podle ubytování",
     "Shortening the validity of long-term residence according to the accommodation proof (asks for the internal rule; refused)",
     "https://mv.gov.cz/documents/mv-71931-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---zkracovani-delky-dp-podle-ubytovani"),
    ("2026-04-30_MV-61858-2-OAM-2026_priloha.pdf",
     "2026-04-30",
     "MV-61858-2/OAM-2026 - příloha",
     "Poskytnutí informace - započitatelná doba délky pobytu do trvalého pobytu",
     "Countable length of residence for permanent residence (follow-up information after payment of the search fee)",
     "https://archiv.mv.gov.cz/soubor/mv-61858-2-oam-2026-priloha.aspx",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-zapocitatelna-doba-delky-pobytu-do-trvaleho-pobytu.aspx"),
    ("2026-05-06_MV-68099-2-OAM-2026.pdf",
     "2026-05-06",
     "MV-68099-2/OAM-2026",
     "Poskytnutí informace - platné interní metodické pokyny, manuály, směrnice a další vnitřní předpisy",
     "Valid internal methodological instructions, manuals and directives (the Ministry states it has none on assessing integration or on 'reasons worthy of special consideration')",
     "https://mv.gov.cz/documents/mv-68099-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---platne-interni-metodicke-pokyny-manualy-smernice-a-dalsi-vnitrni-predpisy"),
    ("2026-06-05_MV-116350-2-OAM-2026_priloha2.pdf",
     "2026-06-05",
     "MV-116350-2/OAM-2026 - příloha 2",
     "Poskytnutí informace - žádost o metodické vyjádření + kdo jej podal",
     "Original request for a methodological statement on third parties arranging bank confirmations for visa and residence proceedings",
     "https://mv.gov.cz/documents/mv-116350-2oam-2026-priloha2?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---zadost-o-metodicke-vyjadreni--kdo-jej-podal"),
    ("2026-06-09_MV-90419-2-OAM-2026.pdf",
     "2026-06-09",
     "MV-90419-2/OAM-2026",
     "Poskytnutí informace - žádost o sdělení změn v rozhodovací praxi ve věci DV strpěn",
     "Changes in decision practice on long-term visas for tolerated stay (asks for all internal directives)",
     "https://mv.gov.cz/documents/mv-90419-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---zadost-o-sdeleni-zmen-v-rozhodovaci-praxi-ve-veci-dv-strpen"),
    ("2026-06-24_MV-68107-2-OAM-2026.pdf",
     "2026-06-24",
     "MV-68107-2/OAM-2026",
     "Poskytnutí informace - rezident EU s MO přechod na TP v ČR po ztrátě MO",
     "EU long-term resident with international protection moving to permanent residence after losing protection (no methodology exists)",
     "https://mv.gov.cz/documents/mv-68107-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---rezident-eu-s-mo-prechod-na-tp-v-cr-po-ztrate-mo"),
    ("2026-07-27_MV-108009-3-OAM-2026.pdf",
     "2026-07-27",
     "MV-108009-3/OAM-2026",
     "Poskytnutí informace - rozsah zpracování osobních údajů",
     "Scope of personal data processing (asks for internal rules, methodologies and work procedures)",
     "https://mv.gov.cz/documents/mv-108009-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---rozsah-zpracovani-osobnich-udaju"),
    ("2026-07-27_MV-108876-3-OAM-2026.pdf",
     "2026-07-27",
     "MV-108876-3/OAM-2026",
     "Poskytnutí informace - prokazování totožnosti prostřednictvím aplikace eDoklady",
     "Proving identity through the eDoklady app (asks for any internal instruction or methodology)",
     "https://mv.gov.cz/documents/mv-108876-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---prokazovani-totoznosti-prostrednictvim-aplikace-edoklady"),
    ("2026-08-04_MV-116350-2-OAM-2026.pdf",
     "2026-08-04",
     "MV-116350-2/OAM-2026",
     "Poskytnutí informace - žádost o metodické vyjádření + kdo jej podal",
     "Request for the methodological statement on bank confirmations and the identity of its requester (cover reply)",
     "https://mv.gov.cz/documents/mv-116350-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---zadost-o-metodicke-vyjadreni--kdo-jej-podal"),
    ("2026-08-14_MV-126721-2-OAM-2026.pdf",
     "2026-08-14",
     "MV-126721-2/OAM-2026",
     "Poskytnutí informace - volný pohyb dlouhodobě pobývajícího rezidenta do druhého členského státu",
     "Mobility of long-term residents to a second Member State (states that no internal instruction, methodology or opinion exists)",
     "https://mv.gov.cz/documents/mv-126721-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---volny-pohyb-dlouhodobe-pobyvajiciho-rezidenta-do-druheho-clenskeho-statu"),
    ("2026-08-24_MV-122012-3-OAM-2012.pdf",
     "2026-08-24",
     "MV-122012-3/OAM-2012",
     "Poskytnutí informace - prokazování totožnosti",
     "Proving identity at OAMP offices (asks for internal instructions, methodologies, interpretations)",
     "https://mv.gov.cz/documents/mv-122012-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---prokazovani-totoznosti"),
    ("2026-08-24_MV-122018-3-OAM-2018.pdf",
     "2026-08-24",
     "MV-122018-3/OAM-2018",
     "Poskytnutí informace - pořizování kopií dokladů a profesních/služebních průkazů při úředním úkonu",
     "Copying of identity documents and service cards during official acts (asks for internal instructions)",
     "https://mv.gov.cz/documents/mv-122018-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---porizovani-kopii-dokladu-a-profesnichsluzebnich-prukazu-pri-urednim-ukonu"),
    ("2026-08-24_MV-122023-3-OAM-2023.pdf",
     "2026-08-24",
     "MV-122023-3/OAM-2023",
     "Poskytnutí informace - identifikace úředních osob při úředním styku",
     "Identification of officials in official dealings (asks for internal rules and instructions)",
     "https://mv.gov.cz/documents/mv-122023-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---identifikace-urednich-osob-pri-urednim-styku"),
    ("2026-08-26_MV-129452-2-OAM-2026.pdf",
     "2026-08-26",
     "MV-129452-2/OAM-2026",
     "Poskytnutí informace - situace na OPC v Liberci",
     "Situation at the OAMP office in Liberec: refusal to accept a permanent residence application (asks for the internal instruction relied on; refused)",
     "https://mv.gov.cz/documents/mv-129452-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---situace-na-opc-v-liberci"),
    ("2026-09-01_MV-129299-4-OAM-2026.pdf",
     "2026-09-01",
     "MV-129299-4/OAM-2026",
     "Poskytnutí informace - dočasná ochrana pro muže v branném věku",
     "Temporary protection for men of conscription age (asks for any instruction or methodology)",
     "https://mv.gov.cz/documents/mv-129299-4oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---docasna-ochrana-pro-muze-v-brannem-veku"),
    ("2026-09-04_MV-129458-3-OAM-2026.pdf",
     "2026-09-04",
     "MV-129458-3/OAM-2026",
     "Poskytnutí informace - pobyt, dočasná ochrana a branná povinnost na Ukrajině",
     "Residence, temporary protection and conscription duty in Ukraine (asks for all valid internal methodological instructions)",
     "https://mv.gov.cz/documents/mv-129458-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---pobyt-docasna-ochrana-a-branna-povinnost-na-ukrajine"),
    ("2026-09-17_MV-116350-2-OAM-2026_priloha1.pdf",
     "2026-09-17",
     "MV-116350-2/OAM-2026 - příloha 1",
     "Poskytnutí informace - žádost o metodické vyjádření + kdo jej podal",
     "Request for the methodological statement on bank confirmations (decision partly refusing identity data)",
     "https://mv.gov.cz/documents/mv-116350-2oam-2026-priloha1?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---zadost-o-metodicke-vyjadreni--kdo-jej-podal"),
    ("2026-09-17_MV-119516-2-OAM-2026.pdf",
     "2026-09-17",
     "MV-119516-2/OAM-2026",
     "Poskytnutí informace - vízum strpění a cestování do Chorvatska",
     "Tolerated-stay visa and travel to Croatia (asks for methodological instructions or binding interpretations; refused)",
     "https://mv.gov.cz/documents/mv-119516-2oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---vizum-strpeni-a-cestovani-do-chorvatska"),
    ("2026-09-17_MV-97853-3-OAM-2026.pdf",
     "2026-09-17",
     "MV-97853-3/OAM-2026",
     "Poskytnutí informace - všechny metodiky, rozhodnutí a statistiky",
     "All methodologies, decisions and statistics on the residence of foreigners (request refused as too general)",
     "https://mv.gov.cz/documents/mv-97853-3oam-2026?disposition=attachment",
     "https://mv.gov.cz/poskytnuti-informace---vsechny-metodiky-rozhodnuti-a-statistiky"),
]

# Known to exist but not published / not fetched.
NOT_OBTAINED = [
    ("Pokyn ředitelky OAMP č. 21 (27 Oct 2020) and č. 22 (23 Nov 2020) on operation of OAMP offices during the state of emergency",
     "sent to an FOI requester as attachments of MV-187216-2/OAM-2020 but the attachments were not published with the answer",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-fungovani-pracovist-oamp-behem-nouzoveho-stavu.aspx"),
    ("Manual 'Ukrajina – dočasná ochrana a rozhodování', version valid from 24 June 2022",
     "FOI request partly refused (internal instructions, § 11(1)(a) of Act 106/1999); the released part is not published",
     "https://archiv.mv.gov.cz/clanek/poskytnuti-informace-dokument-ukrajina-docasna-ochrana-a-rozhodovani.aspx"),
    ("Manual 'Ukrajina – dočasná ochrana a rozhodování', version of early 2023 (79 pages)",
     "FOI request shelved because the search fee was not paid; never released",
     "https://archiv.mv.gov.cz/soubor/mv-29065-5-oam-2023.aspx"),
    ("Manual 'Ukrajina – dočasná ochrana a rozhodování', current version (requested January 2026)",
     "FOI request refused (MV-12347-3/OAM-2026)",
     "https://archiv.mv.gov.cz/soubor/mv-12347-3-oam-2026.aspx"),
    ("Opinions of the OAMP methodology unit (oddělení metodiky) given in individual cases, e.g. in file MV-7459/OAM-2025",
     "FOI request partly refused (MV-182757-3/OAM-2025); not published",
     "https://archiv.mv.gov.cz/soubor/mv-182757-3-oam-2025.aspx"),
    ("OAMP opinions MV-3653-4/OAM-2025 (18 Mar 2025) and MV-36358-2/OAM-2025",
     "provided to FOI requesters as attachments in 2026 (MV-106293-2/OAM-2026, MV-90405-2/OAM-2026) but only the cover letters are published",
     "https://mv.gov.cz/106---cizinecka-problematika"),
    ("Internal acts of the Police (závazné pokyny policejního prezidenta) on the Foreign Police Service, e.g. No 134/2001 and 154/2001",
     "requested under Act 106/1999 from the Police; only the request and answer text is published, not the acts",
     "https://archiv.policie.gov.cz/clanek/interni-akty-rizeni-558221.aspx"),
    ("Methodological materials on acquiring Czech citizenship for regional authorities (FOI answers MV-1109-60/VS-2024, MV-1477-13/OSO-2026)",
     "citizenship is outside the scope (visa, residence, asylum); not downloaded",
     "https://archiv.mv.gov.cz/clanek/informace-podle-zakona-106.aspx"),
]


class Blocked(Exception):
    pass


_last = {}
_robots = {}
_resets = {}


def allowed(url):
    host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:      # an error here aborts: no robots.txt, no fetching
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
        _robots[host] = rp
        _last[host] = time.time()
    return _robots[host].can_fetch(UA, url)


def save(url, dest):
    """Download url to dest unless it is already there. Returns '' on success, else the reason."""
    if dest.exists() and dest.stat().st_size > 0:
        return ""
    host = urlsplit(url).netloc
    if _resets.get(host, 0) >= 3:
        return "host given up after three connection errors in a row"
    if not allowed(url):
        return "disallowed by robots.txt"
    wait = DELAY - (time.time() - _last.get("https://" + host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
        _resets[host] = 0
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} from {host}") from e
        return f"HTTP {e.code}"
    except Exception as e:                                  # noqa: BLE001 - report and carry on, no retry
        _resets[host] = _resets.get(host, 0) + 1
        return f"download failed: {e}"
    finally:
        _last["https://" + host] = time.time()
    if not data.startswith(b"%PDF"):
        return "server did not return a PDF"
    dest.write_bytes(data)
    print(f"  saved {dest.name} ({len(data):,} bytes)")
    return ""


def main():
    (OUT / "foi-replies").mkdir(parents=True, exist_ok=True)
    failed = []
    try:
        for name, date, kind, title, gloss, url, note in MAIN:
            why = save(url, OUT / name)
            if why:
                print(f"  NOT SAVED {name}: {why}")
                failed.append((title, why, url))
        for name, date, ref, title, gloss, url, page in FOI:
            why = save(url, OUT / "foi-replies" / name)
            if why:
                print(f"  NOT SAVED {name}: {why}")
                failed.append((f"{title} ({ref})", why, url))
    except Blocked as e:
        print(f"STOPPED: {e}. No further requests in this run.")
        failed.append(("(run stopped early)", str(e), ""))

    n_main = n_foi = 0
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tkind\ttitle_en\tnote\n")
        for name, date, kind, title, gloss, url, note in MAIN:
            if (OUT / name).exists():
                n_main += 1
                f.write("\t".join([name, title, date, url, kind, gloss, note]) + "\n")
    with open(OUT / "foi-replies.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\treference\ttitle_en\tlisting_page\n")
        for name, date, ref, title, gloss, url, page in FOI:
            if (OUT / "foi-replies" / name).exists():
                n_foi += 1
                f.write("\t".join(["foi-replies/" + name, title, date, url, ref, gloss, page]) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("title\treason\turl\n")
        for row in failed + NOT_OBTAINED:
            f.write("\t".join(row) + "\n")
    print(f"cz: {n_main} of {len(MAIN)} index documents and {n_foi} of {len(FOI)} FOI replies present")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Download Taiwan's published guidance for immigration, visa and work-permit case officers.

    python3 download_tw.py                 # all sources
    python3 download_tw.py nia wda         # only the named sources
    python3 download_tw.py moj sweep       # also sweep the law database's sitemap (about 260 pages)

Sources (names usable as arguments):

  nia      National Immigration Agency (內政部移民署), www.immigration.gov.tw
           - 入出國及移民法令彙編: the agency's own compendium of the statutes, regulations,
             administrative rules (行政規則: 作業要點, 作業規定, 處理原則, 審查基準, 裁罰基準)
             and interpretive letters it applies; every edition offered (2014-2026).
           - 主管法規 pages: the administrative rules, public notices and interpretive
             orders that the agency hosts itself as files.
           The same pages link most administrative rules to the Ministry of the
           Interior's law database glrs.moi.gov.tw. That host did not answer from this
           machine (connection timeout, so its robots.txt could not be read) and is not
           used; those rules are listed in tw/not-obtained.tsv. Their text is in the
           compendium.
  wda      Workforce Development Agency, Ministry of Labor: the work-permit review
           manuals (審查作業手冊) for foreign professionals, the inter-agency consultation
           (會商) rules and the interpretive orders, from ezworktaiwan.wda.gov.tw (files
           on ws.wda.gov.tw; three interpretive orders on gazette.nat.gov.tw).
  mofa     Ministry of Foreign Affairs law database, law.mofa.gov.tw, consular
           category: the rules whose title concerns visas or visa interviews, in Chinese
           and in the official English translation.
  moj      National law database law.moj.gov.tw (robots.txt allows only
           /LawClass/LawAll.aspx): the regulations (法規命令) that are in practice the
           working rules for permits, detention and removal, and the work-permit review
           standards. Marked "procedural act".
           "python3 download_tw.py moj sweep" also walks the database's sitemap through the
           Ministry of the Interior (D0080...) and cross-strait (Q001/Q002/Q006) classes and
           keeps immigration titles; its finds of 15 Nov 2026 are pinned in MOJ_EXTRA.
  wayback  A few administrative rules of glrs.moi.gov.tw as archived by the Internet
           Archive in 2018-2022 (older versions; the archive holds few).

robots.txt of every host is read before the first request to it and obeyed (generic
agent rules, wildcards included). HTTP 403/429 ends the use of a host for the run; so
do three connection failures in a row. Requests are sequential, one per host at a time,
1.6 s apart (4 s for the Internet Archive). Files that exist are skipped. tw/index.tsv
is rewritten from what is on disk and seen; tw/not-obtained.tsv lists what is missing.
Python standard library only.
"""
import base64
import html
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "tw"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 1.6
PAUSE_IA = 4.0
MAX_FILE = 95_000_000
HEAD = ["file", "title", "date", "source_url", "kind", "title_en", "source", "note"]

NIA = "https://www.immigration.gov.tw"
NIA_LAWS = "/5385/396729/"
NIA_COMPENDIUM = "/5385/7353/7356/"
EZ = "https://ezworktaiwan.wda.gov.tw"
MOFA = "https://law.mofa.gov.tw"
MOJ = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={}"

# NIA-hosted files that are not about deciding immigration cases
NIA_SKIP = re.compile(r"新住民發展基金|發言人|國家賠償|陳情|檔案申請|通譯|直轄市長|簡任第十職等|個人資料")
# regulations worth keeping from law.moj.gov.tw (title filter)
MOJ_KEEP = re.compile(r"(辦法|標準|規則|細則)$")
MOJ_SKIP = re.compile(r"收費|規費|基金|服制|個人資料|獎勵|補助|安置|申報|公務員|協助辦法|律師|移民業務機構|安全金")
MOJ_CROSS = re.compile(r"進入臺灣地區|入境|居留|定居|收容|出境|面談|停留|觀光|探親|團聚")
MOJ_IMMIG = re.compile(r"入出國|移民|外國人|外來人口|大陸地區|香港|澳門|居留|收容|驅逐|強制出|入國|面談|人口販運|無戶籍|查察|暫時留置|戒具")
MOJ_EXTRA = ["N0090027", "N0090031", "N0090053", "N0090054",     # work-permit regulations (Ministry of Labor)
             # found by the optional sitemap sweep of 15 Nov 2026 (python3 download_tw.py moj sweep)
             "D0080129", "D0080140", "D0080154", "D0080169", "D0080184", "D0080222", "D0080225", "Q0060003"]
# Ministry of Labor notices to keep
WDA_KEEP = re.compile(r"審查作業要點|解釋令|核釋")
WDA_SKIP = re.compile(r"收費標準|第47條")
# glrs.moi.gov.tw pages held by the Internet Archive: (id, capture, title, date of capture)
WAYBACK = [
    ("FL046788", "20210121112432", "https://glrs.moi.gov.tw/LawContent.aspx?id=FL046788",
     "入出國及移民法與臺灣地區與大陸地區人民關係條例及香港澳門關係條例罰鍰案件裁罰基準"),
    ("FL004710", "20220801154559",
     "https://glrs.moi.gov.tw/LawContent.aspx?id=FL004710&KeyWord=%e7%a6%81%e6%ad%a2%e5%a4%96%e5%9c%8b%e4%ba%ba"
     "%e5%85%a5%e5%9c%8b%e4%bd%9c%e6%a5%ad%e8%a6%8f%e5%ae%9a", "禁止外國人入國作業規定"),
    ("FL046799", "20220729152248", "https://glrs.moi.gov.tw/LawContent.aspx?id=FL046799",
     "入出國及移民法罰鍰案件裁罰基準"),
    ("FL046593", "20220729152251", "https://glrs.moi.gov.tw/LawContent.aspx?id=FL046593",
     "大陸地區人民申請在臺灣地區定居案件經不予許可撤銷或廢止定居許可不得再申請期間處理原則"),
    ("GL000459", "20220729152235", "https://glrs.moi.gov.tw/LawContent.aspx?id=GL000459",
     "大陸地區人民在臺灣地區依親居留長期居留或定居許可辦法第14條、第16條、第26條、第28條等規定之解釋令"),
    ("FL004709", "20180725103710", "http://glrs.moi.gov.tw:80/LawContent.aspx?id=FL004709",
     "居住臺灣地區設有戶籍國民入出國作業要點"),
    ("FL053329", "20220729152303", "https://glrs.moi.gov.tw/LawContent.aspx?id=FL053329",
     "內政部入出國及移民署強制大陸地區人民出境審查會設置要點"),
    ("GL000066", "20220729152246", "https://glrs.moi.gov.tw/LawContent.aspx?id=GL000066",
     "大陸地區人民在臺灣地區依親居留長期居留或定居許可辦法解釋令(98年11月12日台內移字第0980960751號令)"),
]

GLOSS = [  # (substring of the Chinese title, English gloss); first match wins
    ("強制大陸地區人民出境審查會", "Directions establishing the review board on deportation of mainland residents (archived)"),
    ("台內移字第0980960751號", "Interpretive order of 12 Nov 2009 on the Regulations on dependent residence, long-term residence and settlement of mainland residents (archived)"),
    ("戒具武器", "Regulations on types and use of restraints and weapons by the immigration agency"),
    ("暫時留置", "Regulations on temporary holding of persons by the immigration agency"),
    ("實施面談辦法", "Regulations on interviews conducted by the National Immigration Agency"),
    ("查察及查察登記", "Regulations on inspections and inspection registration by the National Immigration Agency"),
    ("第七十四條之一特殊事由", "Standards for recognising special reasons and reducing penalties under art. 74-1 of the Immigration Act"),
    ("受歧視申訴審議小組", "Directions establishing the review panel on discrimination complaints by residents of Taiwan"),
    ("成年子女工作許可申請案件審查作業要點-第3點", "Review directions for work permits of adult children under arts. 15 and 26 of the Foreign Professionals Act: amended points 3 and 4"),
    ("重大經濟犯罪重大刑事案件", "Standards for refusing or barring entry and exit of nationals suspected of major economic or criminal offences"),
    ("無戶籍國民停留居留及定居", "Regulations on visits, residence and settlement of nationals without household registration"),
    ("泰國緬甸地區國軍後裔", "Regulations on residence and settlement of descendants of ROC soldiers stranded in Thailand and Myanmar"),
    ("外國人申請永久居留無不良素行", "Standards for finding good conduct in foreigners' permanent-residence applications"),
    ("航班及乘員資料通報", "Regulations on reporting and use of flight and passenger data (API/PNR)"),
    ("外國人停留居留及永久居留辦法", "Regulations governing visiting, residence and permanent residence of foreigners"),
    ("依親居留長期居留或定居許可辦法", "Regulations on dependent residence, long-term residence and settlement of mainland residents in Taiwan"),
    ("無戶籍國民申請入國居留定居", "Regulations on entry, residence and settlement of nationals without household registration"),
    ("入出國查驗及資料蒐集利用辦法", "Regulations on entry and exit inspection and the collection and use of data"),
    ("專業活動許可辦法", "Regulations on permission for mainland residents to enter Taiwan for professional activities"),
    ("商務活動許可辦法", "Regulations on permission for mainland residents to enter Taiwan for business activities"),
    ("跨國境人口販運防制", "Regulations on prevention of cross-border human trafficking and protection of victims"),
    ("入出國及移民法令彙編", "Compendium of entry, exit and immigration laws, regulations, administrative rules and interpretations (National Immigration Agency)"),
    ("快速查驗閘門", "Operating directions on use of fast-inspection gates by non-nationals on departure"),
    ("辨識個人生物特徵", "Operating directions on biometric identification of non-nationals at entry and exit"),
    ("臨時入境停留許可作業規定", "Operating rules on temporary entry and stay permits for Hong Kong and Macau residents"),
    ("香港澳門居民申請進入臺灣地區及居留定居作業規定", "Operating rules on entry, residence and settlement applications by Hong Kong and Macau residents"),
    ("居留資格審核表", "Review table of residence qualifications for Hong Kong and Macau professionals"),
    ("臨時入境停留通知單", "Notice on temporary entry permits issued on arrival in Kinmen, Matsu and Penghu to mainland visitors: who qualifies, limits, numbers and documents"),
    ("個人旅遊之數額", "Notice amending the quota of mainland residents visiting Taiwan as individual tourists"),
    ("加速處理作業程序", "Notice of the expedited procedure for group and individual tourist permits for mainland residents"),
    ("觀光活動之數額", "Notice amending the quota, scope and method for tourism by mainland residents"),
    ("第15條第1項第1款", "Interpretive order on provisions of the Regulations on dependent residence, long-term residence and settlement of mainland residents"),
    ("第14條、第16條", "Interpretive order on provisions of the Regulations on dependent residence, long-term residence and settlement of mainland residents (archived)"),
    ("外國專業人才延攬及僱用法工作許可(審查作業手冊)", "Review manual: work permits under the Act for the Recruitment and Employment of Foreign Professionals"),
    ("專門性或技術性工作(審查作業手冊)", "Review manual: specialised or technical work"),
    ("主管工作(審查作業手冊)", "Review manual: managers of businesses invested in or set up by overseas Chinese or foreigners"),
    ("補習班專任外國語文教師工作(審查作業手冊)", "Review manual: full-time foreign-language teachers at cram schools"),
    ("運動教練及運動員工作(審查作業手冊)", "Review manual: sports coaches and athletes"),
    ("藝術及演藝工作(審查作業手冊)", "Review manual: arts and performing arts work"),
    ("履約人員(審查作業手冊)", "Review manual: contract-performance personnel"),
    ("在臺畢業僑外生留臺工作(審查作業手冊)", "Review manual: overseas Chinese and foreign graduates staying to work in Taiwan (points system)"),
    ("求學期間工讀(審查作業手冊)", "Review manual: part-time work by foreign, overseas Chinese and ethnic Chinese students"),
    ("辦理解聘(審查作業手冊)", "Review manual: termination of employment of foreign professionals"),
    ("專案會商法規", "Consultation mechanism: legal basis for case-by-case inter-agency consultation"),
    ("個案會商流程說明", "Consultation mechanism: explanation of the case consultation procedure"),
    ("個案會商機制流程圖", "Consultation mechanism: flowchart of the case consultation procedure"),
    ("成年子女工作許可申請案件審查作業要點", "Review directions for work-permit applications by adult children under arts. 15 and 26 of the Foreign Professionals Act"),
    ("第5條第3款規定之解釋令", "Interpretive order on art. 5(3) of the Qualifications and Review Standards for foreigners' work under Employment Service Act art. 46(1)(1)-(6)"),
    ("第4條第15款", "Interpretive order under art. 4(15) of the Review Standards: other designated work items"),
    ("第6條第1項", "Interpretive order under art. 6(1) of the Review Standards: project approval of bachelor's-degree holders without two years' experience"),
    ("外交部及駐外館處辦理外國人與我國國民結婚申請來臺面談作業要點", "Operation directions for MOFA and overseas missions on interviews with foreigners applying to enter Taiwan for marriage to ROC citizens"),
    ("Operation Directions for Ministry of Foreign Affairs", "Operation directions for MOFA and overseas missions on interviews with foreigners applying to enter Taiwan for marriage to ROC citizens (official English translation)"),
    ("外國專業人才申請來臺尋職簽證審查及核發作業辦法", "Regulations on review and issuance of employment-seeking visas for foreign professionals"),
    ("外國護照簽證條例施行細則", "Enforcement rules of the Statute Governing Issuance of ROC Visas in Foreign Passports"),
    ("罰鍰案件裁罰基準", "Standards for fines under the Immigration Act (and the cross-strait and Hong Kong/Macau Acts) (archived)"),
    ("禁止外國人入國作業規定", "Operating rules on barring foreigners from entry (archived)"),
    ("不得再申請期間處理原則", "Principles on re-application bars after refusal or revocation of settlement of mainland residents (archived)"),
    ("設有戶籍國民入出國作業要點", "Operating directions on entry and exit of nationals with household registration (archived)"),
    ("雇主聘僱外國人許可及管理辦法", "Regulations on the permission and administration of the employment of foreign workers"),
    ("第一款至第六款工作資格及審查標準", "Qualifications and review standards for foreigners' work under Employment Service Act art. 46(1)(1)-(6)"),
    ("外國專業人才從事藝術工作許可及管理辦法", "Regulations on permission for foreign professionals to do arts work"),
    ("短期補習班聘僱外國專業人才", "Qualifications and review standards for foreign professionals teaching at cram schools"),
    ("收容聲請事件移送及遠距審理", "Regulations on transfer and remote hearing of detention petitions"),
    ("外國人強制驅逐出國處理辦法", "Regulations on the deportation of foreigners"),
    ("外國人臨時入國許可辦法", "Regulations on temporary entry permits for foreigners"),
    ("外國人收容管理規則", "Rules on the detention of foreigners"),
    ("無戶籍國民強制出國處理辦法", "Regulations on forcible departure of nationals without household registration"),
    ("入出國及移民法施行細則", "Enforcement rules of the Immigration Act"),
    ("香港澳門居民進入臺灣地區及居留定居許可辦法", "Regulations on entry, residence and settlement of Hong Kong and Macau residents"),
    ("大陸地區人民及香港澳門居民收容管理辦法", "Regulations on detention of mainland, Hong Kong and Macau residents"),
    ("大陸地區人民及香港澳門居民強制出境處理辦法", "Regulations on deportation of mainland, Hong Kong and Macau residents"),
    ("大陸地區人民進入臺灣地區許可辦法", "Regulations on permission for mainland residents to enter Taiwan"),
    ("大陸地區人民來臺從事觀光活動許可辦法", "Regulations on permission for mainland residents to visit Taiwan as tourists"),
    ("大陸地區人民按捺指紋及建檔管理辦法", "Regulations on fingerprinting of mainland residents"),
    ("大陸地區人民申請進入臺灣地區面談管理辦法", "Regulations on interviews of mainland residents applying to enter Taiwan"),
    ("人口販運被害人居留及專案永久居留許可辦法", "Regulations on residence and special permanent residence of trafficking victims"),
    ("人口販運防制法施行細則", "Enforcement rules of the Human Trafficking Prevention Act"),
    ("永久居留無不良素行認定標準", "Standards for finding good conduct in permanent-residence applications by foreign professionals and their families"),
    ("外國特定專業人才申請就業金卡許可辦法", "Regulations on Employment Gold Card applications by foreign special professionals"),
    ("退離職人員", "Regulations on mainland travel by former officials in national-security posts"),
]


class Refused(Exception):
    """The host refused (403/429/robots) or failed three times: stop using it for this run."""


_last, _fails, _closed, _robots = {}, {}, set(), {}


def _raw(url, referer=None, timeout=300):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Refused(f"{host}: closed earlier in this run")
    pause = PAUSE_IA if host.endswith("archive.org") else PAUSE
    wait = pause - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        with urllib.request.urlopen(urllib.request.Request(url, None, headers), timeout=timeout) as r:
            data = r.read()
        _fails[host] = 0
        return data
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            _closed.add(host)
            raise Refused(f"{host}: HTTP {e.code}") from None
        raise
    except (urllib.error.URLError, OSError) as e:
        _fails[host] = _fails.get(host, 0) + 1
        if _fails[host] >= 3:
            _closed.add(host)
            raise Refused(f"{host}: three connection failures in a row ({e})") from None
        raise
    finally:
        _last[host] = time.time()


def _rules(host, scheme):
    """Disallow/Allow rules for '*' from the host's robots.txt (empty when there is none)."""
    if host not in _robots:
        rules = []
        try:
            txt = _raw(f"{scheme}://{host}/robots.txt", timeout=60).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            txt = ""                                  # 404 and the like: no robots.txt
            if e.code >= 500:
                _closed.add(host)
                raise Refused(f"{host}: robots.txt answered HTTP {e.code}") from None
        except Refused:
            raise
        except Exception as e:                        # noqa: BLE001
            _closed.add(host)
            raise Refused(f"{host}: robots.txt could not be read ({e})") from None
        if txt.lstrip()[:1] == "<":
            txt = ""                                  # an HTML "not found" page
        groups, agents, fresh = [], [], True
        for line in txt.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (s.strip() for s in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if not fresh:
                    agents, fresh = [], True
                agents.append(v.lower())
                groups.append((agents, []))
            elif k in ("allow", "disallow"):
                fresh = False
                if groups and v:
                    groups[-1][1].append((k, v))
        for ags, rs in groups:
            if "*" in ags or any(a in ("claudebot", "anthropic-ai", "claude-web", "gptbot", "ccbot") for a in ags):
                rules += rs
        _robots[host] = rules
    return _robots[host]


def allowed(url):
    u = urllib.parse.urlsplit(url)
    path = u.path + ("?" + u.query if u.query else "")
    best, verdict = -1, True
    for kind, pat in _rules(u.netloc, u.scheme):
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pat.rstrip("$")) + ("$" if pat.endswith("$") else "")
        if re.match(rx, path) and (len(pat) > best or (len(pat) == best and kind == "allow")):
            best, verdict = len(pat), kind == "allow"
    return verdict


def get(url, referer=None):
    if not allowed(url):
        raise Refused(f"{urllib.parse.urlsplit(url).netloc}: robots.txt disallows {url}")
    return _raw(url, referer)


def page(url, referer=None):
    return get(url, referer).decode("utf-8", "replace")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def safe(name, limit=150):
    name = re.sub(r'[\\/:*?"<>|#%&+\s\x00-\x1f，、；：「」『』（）()〔〕【】]+', "-", name).strip("-. ")
    name = re.sub(r"-{2,}", "-", name)
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 5:
        stem, ext = name, ""
    while len(stem.encode()) > limit:
        stem = stem[:-1]
    return stem.rstrip("-") + ("." + ext.lower() if ext else "")


def roc(s):
    """'民國 113 年 07 月 29 日', '115-10-15', '113.07.29' or '（115年8月）' -> ISO date."""
    m = re.search(r"(\d{2,3})\s*[年.\-]\s*(\d{1,2})\s*[月.\-]\s*(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"(\d{2,3})\s*年\s*(\d{1,2})\s*月", s)
    if m:
        return f"{int(m.group(1)) + 1911}-{int(m.group(2)):02d}"
    return ""


def gloss(*titles):
    titles = [unicodedata.normalize("NFKC", t) for t in titles]   # some titles use CJK compatibility ideographs
    for key, en in GLOSS:
        if any(key in t for t in titles):
            return en
    return ""


def wrong(data, name, marker=None):
    ext = name.rsplit(".", 1)[-1].lower()
    if len(data) < 300:
        return "too small"
    if ext == "pdf":
        return None if data[:5] == b"%PDF-" else "not a PDF"
    if ext in ("html", "htm"):
        if marker and marker.encode() not in data:
            return f"page lacks the expected text ({marker})"
        return None
    if data.lstrip()[:1] == b"<":
        return "an HTML page, not a document"
    if ext in ("doc", "xls", "ppt") and data[:4] != b"\xd0\xcf\x11\xe0":
        return "not an Office file"
    if ext in ("docx", "xlsx", "odt", "ods", "pptx") and data[:2] != b"PK":
        return "not a ZIP container"
    return None


class Run:
    def __init__(self):
        self.rows, self.missing, self.new = {}, [], 0

    def miss(self, title, date, url, reason):
        self.missing.append((title, date, url, reason))

    def save(self, rel, url, title, date, kind, source, note="", marker=None, referer=None, en=None):
        dest = OUT / rel
        large = OUT / ".large" / rel
        row = [rel, title, date, url, kind, en or gloss(title), source, note]
        if large.exists():
            self.miss(title, date, url, f"held outside the published tree as .large/{rel} (over 95 MB)")
            return
        if not (dest.exists() and dest.stat().st_size > 0):
            try:
                data = get(url, referer)
            except Refused:
                raise
            except Exception as e:                    # noqa: BLE001
                self.miss(title, date, url, f"download failed: {e}")
                print(f"  FAILED {rel}: {e}")
                return
            why = wrong(data, rel, marker)
            if why:
                self.miss(title, date, url, f"server returned {why}")
                print(f"  REJECTED {rel}: {why}")
                return
            if len(data) > MAX_FILE:
                dest = large
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(data)
            part.replace(dest)
            self.new += 1
            print(f"  saved {dest.relative_to(OUT)} ({len(data):,} bytes)")
            if dest is large:
                self.miss(title, date, url, f"held outside the published tree as .large/{rel} (over 95 MB)")
                return
        self.rows[rel] = row


# ------------------------------------------------------------------ National Immigration Agency

def nia_list(t):
    """[(href, title, date)] of a list page of the agency's site."""
    out = []
    for href, body in re.findall(r'<li>\s*<a href="([^"]+)"[^>]*>\s*<span class="num">\d+</span>(.*?)</a>', t, re.S):
        d = re.search(r"<time>([\d-]+)</time>", body)
        out.append((html.unescape(href), text(re.sub(r"<time>.*?</time>", "", body, flags=re.S)), d.group(1) if d else ""))
    return out


def nia(run):
    print("NIA: compendium of immigration laws")
    src = NIA + NIA_COMPENDIUM
    for href, title, listed in nia_list(page(src)):
        if "/media/" not in href:
            continue
        date = roc(title) or listed
        url = NIA + urllib.parse.quote(href)
        run.save(f"nia/compendium/{date}_入出國及移民法令彙編.pdf", url, title, date, "guidance",
                 "immigration.gov.tw 入出國及移民法令彙編專區",
                 "compendium: statutes, regulations, administrative rules and interpretive letters in one volume",
                 referer=src)
    print("NIA: 主管法規 pages")
    queue, seen, moj = [NIA_LAWS], set(), {}
    while queue:
        p = queue.pop(0)
        if p in seen:
            continue
        seen.add(p)
        t = page(NIA + p)
        for href in re.findall(r'href="(' + re.escape(p) + r'\d+/)"', t):
            if href not in seen:
                queue.append(href)
        crumb = text("".join(re.findall(r'<title>(.*?)</title>', t, re.S)))
        for href, title, date in nia_list(t):
            m = re.search(r"law\.moj\.gov\.tw/LawClass/LawAll\.aspx\?pcode=(\w+)", href, re.I)
            if m:
                moj.setdefault(m.group(1), title)
            elif "glrs.moi.gov.tw" in href:
                if re.search(r"(辦法|標準|數額表|配額表)$", title) or NIA_SKIP.search(title):
                    continue                          # regulations and out-of-scope items
                run.miss(title, date, href.split("&")[0].split("#")[0],
                         "glrs.moi.gov.tw did not answer from this machine (connection timeout on every attempt, "
                         "robots.txt unreadable), so the host was not used; the text is printed in the compendium "
                         "(nia/compendium/); open the address in a browser for the current version")
            elif href.startswith("/media/") and not NIA_SKIP.search(title + href):
                ext = href.rsplit(".", 1)[-1].lower()
                mid = re.search(r"/media/(\d+)/", href).group(1)
                run.save(f"nia/{date}_{safe(title[:70])}_{mid}.{ext}", NIA + urllib.parse.quote(href), title, date,
                         "guidance", "immigration.gov.tw 主管法規", crumb.split("-")[0].strip(), referer=NIA + p)
    return moj


# ------------------------------------------------------------------ Workforce Development Agency

def wda_file(href):
    """(url, original file name, extension) of a ws.wda.gov.tw download link."""
    url = html.unescape(href)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)

    def b64(v):
        try:
            return base64.b64decode(v + "=" * (-len(v) % 4)).decode("utf-8", "replace")
        except Exception:                             # noqa: BLE001
            return ""
    name = b64(q.get("n", [""])[0])
    ext = b64(q.get("u", [""])[0]).rsplit(".", 1)[-1].lower()
    if name.lower().endswith("." + ext):
        name = name[:-len(ext) - 1]
    return url, name, ext


def wda(run):
    for label, path, sub in (("審查作業手冊", "/cp.aspx?n=D7B5F886C207D205", "wda/manuals"),
                             ("會商機制", "/cp.aspx?n=06DA2961BD6B0D76", "wda/consultation")):
        print(f"WDA: {label}")
        src = EZ + path
        t = page(src)
        upd = roc("".join(re.findall(r"更新日期：([\d-]+)", t)[:1]))
        t = t[t.find('id="Accesskey_C"'):]
        heading, n = "", 0
        for m in re.finditer(r'<h[34][^>]*>(.*?)</h[34]>|<a[^>]*href="(https://ws\.wda\.gov\.tw/Download\.ashx[^"]+)"[^>]*>(.*?)</a>', t, re.S):
            if m.group(1) is not None:
                heading = text(m.group(1)) or heading
                continue
            url, name, ext = wda_file(m.group(2))
            link = text(m.group(3))
            if ext != "pdf" or "書表" in link or "書表" in name:
                continue                              # application forms are not kept
            n += 1
            if sub.endswith("manuals"):
                run.save(f"{sub}/{upd}_{safe(name)}.pdf", url, heading or name, upd, "guidance",
                         f"ezworktaiwan.wda.gov.tw {label}",
                         f"date is the page's 'updated' date; file name on the site: {name}.pdf", referer=src)
            else:
                run.save(f"{sub}/{upd}_{n:02d}_{safe(link)}.pdf", url, f"{link}：{heading}", upd, "guidance",
                         f"ezworktaiwan.wda.gov.tw {label}", "date is the page's 'updated' date", referer=src,
                         en=gloss(link))
    print("WDA: 公告及解釋令")
    lst = EZ + "/News.aspx?n=C4CEA4239AC85576&sms=02F991407E934D54&page={}&PageSize=20"
    for pg in range(1, 15):
        t = page(lst.format(pg))
        rows = 0
        for tr in re.findall(r"<tr.*?</tr>", t, re.S):
            a = re.search(r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"', tr)
            cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if not a or len(cells) < 4:
                continue
            rows += 1
            href, title = html.unescape(a.group(1)), re.sub(r"^移至|\(另開新視窗\)$", "", html.unescape(a.group(2))).strip()
            date = roc(cells[3])
            if not ((WDA_KEEP.search(title) or cells[0] == "解釋令") and not WDA_SKIP.search(title)):
                continue
            if "gazette.nat.gov.tw" in href:
                g = page(href)
                pdf = re.search(r'href="(/EG_FileManager/[^"]+\.pdf)"', g)
                if not pdf:
                    run.miss(title, date, href, "no PDF link on the gazette page")
                    continue
                meta = re.search(r"metaid=(\d+)", href).group(1)
                run.save(f"wda/interpretations/{date}_gazette-{meta}_{safe(title[:50])}.pdf",
                         "https://gazette.nat.gov.tw" + pdf.group(1), title, date, "guidance",
                         "gazette.nat.gov.tw (linked from ezworktaiwan.wda.gov.tw 公告及解釋令)", "", referer=href)
                continue
            item = urllib.parse.urljoin(EZ + "/", href)
            d = page(item)
            sid = re.search(r"[?&]s=(\w+)", href).group(1)[:8]
            for k, h in enumerate(re.findall(r'href="(https://ws\.wda\.gov\.tw/Download\.ashx[^"]+)"', d), 1):
                url, name, ext = wda_file(h)
                if ext != "pdf":
                    continue
                run.save(f"wda/interpretations/{date}_{sid}_{k}_{safe(name)}.pdf", url, f"{title}（{name}）", date,
                         "guidance", "ezworktaiwan.wda.gov.tw 公告及解釋令", "", referer=item, en=gloss(title))
        if rows < 20:
            break


# ------------------------------------------------------------------ Ministry of Foreign Affairs

def mofa(run):
    print("MOFA: consular category of law.mofa.gov.tw")
    for pg in range(1, 10):
        t = page(f"{MOFA}/LawCategoryContentList.aspx?CategoryID=14&page={pg}")
        trs = [tr for tr in re.findall(r"<tr>.*?</tr>", t, re.S) if "LawContent.aspx?id=" in tr]
        for tr in trs:
            lid = re.search(r"LawContent\.aspx\?id=(\w+)", tr).group(1)
            cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            title = re.sub(r"\s*英$", "", cells[2]).strip()
            typ = cells[3]
            if not re.search(r"簽證|面談", title) or re.search(r"收費|互惠|廢", title + typ) or typ == "法律":
                continue
            kind = "guidance" if typ == "行政規則" else "procedural act"
            date = roc(cells[1])
            src = f"{MOFA}/LawContent.aspx?id={lid}"
            run.save(f"mofa/{date}_{lid}_{safe(title[:60])}_zh.html", src, title, date, kind,
                     "law.mofa.gov.tw 領事事務類", typ, marker="法規名稱")
            if "EngLawList.aspx" in tr:
                e = page(f"{MOFA}/EngLawList.aspx?id={lid}")
                m = re.search(r'href="(EngLawContent\.aspx\?lan=E&(?:amp;)?id=\d+)"[^>]*>(.*?)</a>', e, re.S)
                d = re.search(r"(\d{4})\.(\d\d)\.(\d\d)", text(e[e.find("公發布日 中/英文"):])) if m else None
                if m:
                    edate = "-".join(d.groups()) if d else date
                    etitle = text(m.group(2))
                    run.save(f"mofa/{edate}_{lid}_{safe(title[:60])}_en.html", f"{MOFA}/" + html.unescape(m.group(1)),
                             etitle, edate, kind, "law.mofa.gov.tw 領事事務類",
                             f"official English translation of {title}", marker="Law", en=etitle)
        if len(trs) < 10:
            break


# ------------------------------------------------------------------ national law database

def moj(run, found):
    print("MOJ: regulations from law.moj.gov.tw")
    codes = dict(found)
    for c in MOJ_EXTRA:
        codes.setdefault(c, "")
    swept = set()
    if "sweep" in sys.argv[1:]:
        # optional: sweep the Ministry of the Interior class (D0080..., police and immigration) and the
        # cross-strait classes (Q001, Q002, Q006) of the database's sitemap, keeping only immigration titles,
        # so that regulations the agency's pages do not link are found too; what it found is in MOJ_EXTRA
        try:
            sm = page("https://law.moj.gov.tw/SearchEngineSitemap.aspx")
            for c in sorted(set(re.findall(r"pcode=((?:D0080|Q001|Q002|Q006)\d+)", sm))):
                if c not in codes:
                    codes[c] = ""
                    swept.add(c)
        except Refused:
            raise
        except Exception as e:                        # noqa: BLE001
            print(f"  sitemap not read: {e}")
    for code, listed in sorted(codes.items()):
        if listed and (not MOJ_KEEP.search(listed) or MOJ_SKIP.search(listed)):
            continue
        url = MOJ.format(code)
        existing = sorted((OUT / "moj").glob(f"*_{code}_*.html")) if (OUT / "moj").exists() else []
        if existing:                                  # keep the version already saved
            old = existing[-1]
            t = old.read_text(encoding="utf-8", errors="replace")
        else:
            try:
                t = page(url)
            except Refused:
                raise
            except Exception as e:                    # noqa: BLE001
                run.miss(listed or code, "", url, f"download failed: {e}")
                continue
        title = re.sub(r"-全國法規資料庫\s*$", "", text("".join(re.findall(r"<title>(.*?)</title>", t, re.S)[:1])))
        date = roc("".join(re.findall(r"(?:修正|發布)日期：.{0,80}?民國\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日", t, re.S)[:1]))
        if "法規名稱" not in t or not title:
            run.miss(listed or code, "", url, "server returned a page without the regulation text")
            continue
        if MOJ_SKIP.search(title) or not MOJ_KEEP.search(title):
            continue
        if code.startswith("Q") and not MOJ_CROSS.search(title):
            continue                                  # cross-strait rules on trade, money, schools and the like
        if code in swept and not MOJ_IMMIG.search(title):
            continue                                  # police, firearms, pawnshops and the like
        if re.search(r"已廢止|廢止日期", t[:30000]) or title.endswith("(廢)"):
            continue                                  # repealed
        if code in swept:
            print(f"  sweep found {code} {title}")
        rel = f"moj/{date}_{code}_{safe(title[:60])}.html"
        if not existing:
            (OUT / "moj").mkdir(parents=True, exist_ok=True)
            (OUT / rel).write_bytes(t.encode("utf-8"))
            run.new += 1
            print(f"  saved {rel}")
        else:
            rel = str(existing[-1].relative_to(OUT))
        run.rows[rel] = [rel, title, date, url, "procedural act", gloss(title), "law.moj.gov.tw",
                         "regulation (法規命令); date = last amendment; annexed tables (附表) are separate files on the site and not saved"]


# ------------------------------------------------------------------ Internet Archive

def wayback(run):
    print("Wayback: archived administrative rules of glrs.moi.gov.tw")
    for lid, ts, orig, title in WAYBACK:
        date = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        url = f"https://web.archive.org/web/{ts}id_/{orig}"
        run.save(f"wayback-glrs/{date}_{lid}_{safe(title[:50])}.html", url, title, date, "guidance",
                 "glrs.moi.gov.tw via web.archive.org",
                 "date is the day of the archive capture, not of the rule; a later version may be in force",
                 marker="LawContent")


# ------------------------------------------------------------------ output

STATIC_MISSING = [
    ("內政部主管法規共用系統 移民類行政規則（about 150 entries: 作業要點, 作業規定, 處理原則, 審查基準, 裁罰基準, 解釋令）", "",
     "https://glrs.moi.gov.tw/LawCategoryMain.aspx?CategoryID=17",
     "glrs.moi.gov.tw did not answer from this machine (connection timeout, robots.txt unreadable); not used. "
     "The Internet Archive holds only about 35 of the pages, mostly statutes. Texts are in the compendium."),
    ("勞動部勞動法令查詢系統 (Ministry of Labor law database: 作業要點 and 解釋令 on employment of foreigners)", "",
     "https://laws.mol.gov.tw/", "laws.mol.gov.tw did not answer from this machine (connection timeout); not used"),
    ("大陸委員會法規資料庫 (Mainland Affairs Council law database)", "", "https://law.mac.gov.tw/",
     "law.mac.gov.tw did not answer from this machine (connection timeout); not used"),
    ("全國法規資料庫英譯法規 (official English translations of the regulations)", "",
     "https://law.moj.gov.tw/ENG/",
     "robots.txt of law.moj.gov.tw disallows everything except /LawClass/LawAll.aspx, so /ENG/ pages were not fetched"),
    ("外交部領事事務局簽證作業手冊 and internal visa instructions to overseas missions", "",
     "https://law.mofa.gov.tw/LawCategoryContentList.aspx?CategoryID=14",
     "not published: the consular category of the ministry's law database holds no visa-processing manual"),
]


def write(run, done):
    rows = dict(run.rows)
    index = OUT / "index.tsv"
    if index.exists():                                # keep rows of files saved on earlier runs
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            r = line.split("\t")
            if r[0] not in rows and (OUT / r[0]).exists():
                rows[r[0]] = r + [""] * (len(HEAD) - len(r))
                if not rows[r[0]][5]:
                    rows[r[0]][5] = gloss(rows[r[0]][1])
    with open(index, "w", encoding="utf-8") as f:
        f.write("\t".join(HEAD) + "\n")
        for k in sorted(rows):
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in rows[k]) + "\n")
    missing = list(STATIC_MISSING) + run.missing
    path = OUT / "not-obtained.tsv"
    if path.exists():                                 # a source not run this time keeps its entries
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            r = tuple(line.split("\t"))
            if len(r) == 4 and r not in missing and not any(d in r[2] or d in r[3] for d in done) \
                    and r[0] not in [m[0] for m in STATIC_MISSING]:
                missing.append(r)
    seen, out = set(), []
    for m in missing:
        if (m[0], m[2]) not in seen:
            seen.add((m[0], m[2]))
            out.append(m)
    with open(path, "w", encoding="utf-8") as f:
        f.write("title\tdate\turl\treason\n")
        for m in out:
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in m) + "\n")
    return len(rows), len(out)


def main():
    names = ["nia", "wda", "mofa", "moj", "wayback"]
    which = [a for a in sys.argv[1:] if a in names] or names
    OUT.mkdir(exist_ok=True)
    run, done, found = Run(), [], {}
    hosts = {"nia": ["immigration.gov.tw", "glrs.moi.gov.tw/LawContent", "glrs.moi.gov.tw/NewsContent"],
             "wda": ["wda.gov.tw", "gazette.nat.gov.tw"], "mofa": ["law.mofa.gov.tw/LawContent", "EngLawContent"],
             "moj": ["law.moj.gov.tw/LawClass"], "wayback": ["web.archive.org"]}
    for name in names:
        if name not in which and not (name == "nia" and "moj" in which):
            continue
        try:
            if name == "nia":
                found = nia(run)
            elif name == "moj":
                moj(run, found)
            else:
                {"wda": wda, "mofa": mofa, "wayback": wayback}[name](run)
            done += hosts[name]
        except Refused as e:
            print(f"STOPPED {name}: {e}; not retried.")
            run.miss(f"{name}: run stopped", "", "", f"{e}; host not used further in that run")
        except Exception as e:                        # noqa: BLE001
            print(f"STOPPED {name}: {e!r}")
            run.miss(f"{name}: run stopped", "", "", f"error: {e!r}")
    n, m = write(run, done)
    print(f"{run.new} new files; {n} rows in index.tsv; {m} entries in not-obtained.tsv")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Download South Korea's published immigration guidance for case officers.

    python3 download_kr.py            # both sources
    python3 download_kr.py hikorea    # only Hi Korea
    python3 download_kr.py law        # only the national law information centre

South Korea: Ministry of Justice (법무부), Korea Immigration Service
(출입국·외국인정책본부).

1. Hi Korea (www.hikorea.go.kr), notice board (공지사항). The pinned notice
   "체류자격별 통합 안내 매뉴얼(최신)" carries the current visa manual
   (사증민원 자격별 안내 매뉴얼), the current sojourn manual (체류민원 자격별 안내
   매뉴얼) and their change log, as HWP. It is replaced in place whenever the
   guidelines change, so each run of this script picks up the edition then
   current and keeps the ones saved earlier. The board is also searched by
   title for 매뉴얼 / 메뉴얼 / 지침 / 고시 / 기준 / 규정 (manuals, guidelines,
   ministerial notices, criteria, rules) and the attachments of those notices
   are saved into kr/hikorea/.
   Attachments are served by the form the site's own download link posts
   (/fileNewExistsChkAjax.pt); there is no plain file address.

2. National law information centre (www.law.go.kr), administrative rules
   (행정규칙) of the Ministry of Justice: the directives, established rules and
   notices (훈령, 예규, 고시) in force whose title concerns immigration,
   nationality or refugees. The attached full text is saved into kr/law.go.kr/
   (the PDF where a PDF and an HWP of the same name are both offered).

Both sites' robots.txt allow these paths for generic user agents (read
15 November 2026). Requests are sequential with a pause; an HTTP 403 or 429
ends the use of that host for the run. Files that already exist are skipped.
kr/index.tsv lists what is held; kr/not-obtained.tsv what is not.
"""
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "kr"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE = 1.5
MAX_FILES = 3000
MAX_BYTES = 1_000_000_000

HK = "https://www.hikorea.go.kr"
HK_NOTICE = HK + "/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ={}&page=1"
HK_KEYWORDS = ["매뉴얼", "메뉴얼", "지침", "고시", "기준", "규정"]
HK_ALWAYS = ["1062"]                # the pinned "latest manuals" notice
HK_SKIP = re.compile(r"포상|피해신고|숙소 기준 위반|no session|비고시국가|수수료|생계비|"
                     r"기술교육 사전신청|기준점수|투자유치|고용추천")

LAW = "https://www.law.go.kr"
LAW_LIST = (LAW + "/admRulSc.do?menuId=5&subMenuId=41&tabMenuId=183&tabMenuIdx=1"
            "&outmax=150&pg={}&selSort=10asc&cptOfis=1270000&lsCoDbY=N")   # 1270000 = 법무부
LAW_INFO = LAW + "/LSW/admRulInfoP.do?admRulSeq={}"
LAW_WANT = re.compile(r"출입국|출입\(국\)|외국인|사증|비자|체류|난민|국적|귀화|동포|이민|영주|"
                      r"강제퇴거|입국|출국|거소|결혼|사회통합|계절근로|APEC|보호일시해제|전자민원창구")
LAW_SKIP = re.compile(r"보호소년|국제투자분쟁|의무관|외국법자문사")

GLOSS = [  # English gloss for the core documents; other rows are left blank
    ("수정 이력", "Change log of the visa and sojourn guide manuals"),
    ("사증민원 자격별 안내 매뉴얼", "Visa guide manual by status of stay (visa issuance)"),
    ("체류민원 자격별 안내 매뉴얼", "Sojourn guide manual by status of stay (registration, extension, change of status)"),
    ("육성형 전문기술인력", "Visa and sojourn management manual, 'nurtured skilled technical workforce' scheme"),
    ("숙련기능인력(E-7-4)", "Skilled worker (E-7-4) guide manual"),
    ("국적업무처리지침", "Guidelines on handling nationality matters"),
    ("난민 이의신청", "Guidelines on receiving and handling refugee appeals"),
    ("외국인보호규칙 시행세칙", "Detailed rules implementing the Immigration Detention Rules"),
    ("출입국사범 단속과정", "Rules on due process and human rights in immigration enforcement"),
    ("출입국사범 고발규정", "Rules on criminal referral of immigration offenders"),
    ("온라인 사증발급", "Guidelines on online visa issuance and visa sponsors"),
    ("결혼동거 목적의 사증", "Notice on requirements for marriage-migrant visas and exemptions from screening"),
    ("재외동포(F-4) 자격의 취업활동", "Notice on employment restrictions for overseas Koreans (F-4)"),
    ("계절근로", "Seasonal worker programme guidelines / notice"),
    ("대행기관 관리지침", "Guidelines on managing immigration application agencies"),
    ("통고처분 및 과태료", "Guidelines on aggravated penalty notices and administrative fines"),
    ("보호일시해제", "Rules on temporary release from immigration detention"),
    ("권한의 일부위임", "Notice on the scope of powers delegated to immigration offices"),
]


class Refused(Exception):
    """The host answered 403 or 429: stop using it for this run."""


_last = {}


def request(url, data=None, referer=None):
    host = urllib.parse.urlsplit(url).netloc
    wait = PAUSE - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, body, headers), timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Refused(f"{host}: HTTP {e.code}") from None
        raise
    finally:
        _last[host] = time.time()


def page(url, data=None):
    return request(url, data).decode("utf-8", "replace")


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def safe(name, limit=180):
    """A file name that keeps the original (Korean) wording but is safe on disk."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .")
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 5:
        stem, ext = name, ""
    while len(stem.encode()) > limit:
        stem = stem[:-1]
    return stem + ("." + ext.lower() if ext else "")


def looks_wrong(data, name):
    """Reason the bytes are not the document they claim to be, or None."""
    ext = name.rsplit(".", 1)[-1].lower()
    head = data[:8]
    if len(data) < 200:
        return "too small"
    if head.lstrip()[:1] in (b"<", b"{") and ext not in ("html", "htm", "xml", "txt"):
        return "an HTML/JSON page, not a document"
    if ext == "pdf" and not head.startswith(b"%PDF"):
        return "not a PDF"
    if ext in ("hwp", "doc", "xls", "ppt") and not head.startswith(b"\xd0\xcf\x11\xe0") \
            and not head.startswith(b"PK") and not head.startswith(b"HWP Document"):
        return f"not a {ext.upper()} file"
    if ext in ("hwpx", "docx", "xlsx", "pptx", "zip") and not head.startswith(b"PK"):
        return "not a ZIP container"
    return None


def gloss(*titles):
    for key, en in GLOSS:
        if any(key in t for t in titles):
            return en
    return ""


class Run:
    def __init__(self):
        self.rows, self.missing, self.count, self.size = [], [], 0, 0
        self.new = 0

    def save(self, sub, name, fetch, row, src):
        """row = [title, date, source_url, attachment, issuer/number, source, gloss]"""
        dest = OUT / sub / name
        rel = f"{sub}/{name}"
        if not (dest.exists() and dest.stat().st_size > 0):
            if self.count >= MAX_FILES or self.size >= MAX_BYTES:
                self.missing.append((row[0], row[3], row[1], src, "not attempted: file/size limit reached"))
                return
            try:
                data = fetch()
            except Refused:
                raise
            except Exception as e:                  # noqa: BLE001
                self.missing.append((row[0], row[3], row[1], src, f"download failed: {e}"))
                print(f"  FAILED {rel}: {e}")
                return
            why = looks_wrong(data, name)
            if why:
                self.missing.append((row[0], row[3], row[1], src, f"server returned {why}"))
                print(f"  REJECTED {rel}: {why}")
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(data)
            part.replace(dest)
            self.new += 1
            print(f"  saved {rel} ({len(data):,} bytes)")
        self.count += 1
        self.size += dest.stat().st_size
        self.rows.append([rel] + row)


# ---------------------------------------------------------------- Hi Korea

def hk_notices():
    """{seq: (title, date)} for notices whose title matches a keyword."""
    found = {}
    for kw in HK_KEYWORDS:
        for pg in range(1, 40):
            t = page(HK + "/board/BoardListR.pt", {"page": pg, "BBS_SEQ": 1, "BBS_GB_CD": "BS10",
                                                    "BBS_SEQ_GB_CD": "", "CATEGORY": "TITLE",
                                                    "SEARCHMESSAGE": kw})
            n = 0
            for tr in re.findall(r"<tr.*?</tr>", t, re.S):
                m = re.search(r"boardDetailR\('?(\d+)", tr)
                if not m:
                    continue
                n += 1
                cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                date = next((c for c in reversed(cells) if re.fullmatch(r"\d{4}-\d\d-\d\d", c)), "")
                title = max(cells, key=len) if cells else ""
                found.setdefault(m.group(1), (title, date))
            if n < 10:
                break
    return found


def hk_date(orig, listed):
    """Manual files are named YYMMDD ...; use that date when it is a real one."""
    m = re.match(r"(\d\d)(\d\d)(\d\d)(?!\d)", orig)
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return listed


def hikorea(run):
    print("Hi Korea: searching the notice board")
    notices = hk_notices()
    for seq in HK_ALWAYS:
        notices.setdefault(seq, ("", ""))
    todo = sorted((s for s, (t, _) in notices.items() if s in HK_ALWAYS or not HK_SKIP.search(t)), key=int)
    print(f"Hi Korea: {len(todo)} notices")
    for seq in todo:
        title, listed = notices[seq]
        url = HK_NOTICE.format(seq)
        t = page(url)
        m = re.search(r"<th[^>]*>\s*제목\s*</th>\s*<td[^>]*>(.*?)</td>", t, re.S)
        if m:
            title = text(m.group(1))
        atts = re.findall(r"fnNewFileDownLoad\(\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',"
                          r"\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)',\s*'([^']*)'", t)
        if not atts:
            continue                                # text-only notice
        for spec, d, stored, orig, nseq, bseq, gb, apnd, skin in atts:
            stored, orig = html.unescape(stored), html.unescape(orig)
            date = hk_date(orig, listed)
            name = safe(f"{date}_ntc{seq}_{orig}" if date else f"ntc{seq}_{orig}")
            form = {"spec": spec, "dir": d, "apndFileNm": stored, "oriFileNm": orig, "BBS_GB_CD": gb,
                    "BBS_SEQ": bseq, "NTCCTT_SEQ": nseq, "APND_SEQ": apnd, "BBS_SKIN": skin}
            run.save("hikorea", name,
                     lambda form=form, url=url: request(HK + "/fileNewExistsChkAjax.pt", form, url),
                     [title, date, url, orig, "", "hikorea.go.kr 공지사항", gloss(orig, title)], url)


# ---------------------------------------------------------------- law.go.kr

def law_rules():
    rules = []
    for pg in range(1, 20):
        t = page(LAW_LIST.format(pg))
        got = re.findall(r"lawInfPop\('(\d+)'\)\">(.*?)</a>(.*?)</tr>", t, re.S)
        for seq, name, rest in got:
            cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rest, re.S)]
            d = re.search(r"발령\s*(\d{4})\.\s*(\d+)\.\s*(\d+)", " ".join(cells))
            date = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}" if d else ""
            number = " ".join(cells[:2])
            rules.append((seq, text(name), date, number))
        if len(got) < 150:
            break
    return rules


def law(run):
    print("law.go.kr: listing Ministry of Justice administrative rules")
    rules = [r for r in law_rules() if LAW_WANT.search(r[1]) and not LAW_SKIP.search(r[1])]
    print(f"law.go.kr: {len(rules)} immigration-related rules")
    for seq, title, date, number in rules:
        info = LAW_INFO.format(seq)
        t = page(LAW + "/LSW/admRulAttFlList.do", {"admRulSeq": seq})
        atts = [(fl, text(n)) for fl, n in re.findall(r'flDownload\.do\?flSeq=(\d+)"[^>]*>(.*?)</a>', t, re.S)]
        if not atts:
            run.missing.append((title, "", date, info, "no attached file; the text is only on the web page"))
            continue
        pdf_stems = {n.rsplit(".", 1)[0] for _, n in atts if n.lower().endswith(".pdf")}
        for fl, n in atts:
            stem, _, ext = n.rpartition(".")
            if ext.lower() in ("hwp", "hwpx") and stem in pdf_stems:
                continue                            # same text offered as PDF
            src = f"{LAW}/LSW/flDownload.do?flSeq={fl}"
            num = re.sub(r"\s+", "", number)
            name = safe(f"{date}_{num}_{title[:60]}_{fl}.{ext}" if ext else f"{date}_{num}_{title[:60]}_{fl}")
            run.save("law.go.kr", name, lambda src=src, info=info: request(src, None, info),
                     [title, date, src, n, number, info, gloss(title)], info)


# ---------------------------------------------------------------- output

STATIC_MISSING = [
    ("사증·체류 매뉴얼의 이전 판 (earlier editions of the visa and sojourn manuals)", "", "",
     HK_NOTICE.format(1062),
     "Hi Korea replaces the files in place and keeps no archive; downloads are form posts, so the "
     "Wayback Machine holds no copies. Each run of this script keeps the edition current on that day."),
    ("사증발급 지침 / 외국인체류 관리지침 등 내부 업무지침 (internal visa-issuance and sojourn-management "
     "guidelines, 사증발급편람 / 체류관리편람)", "", "", "https://www.law.go.kr/admRulSc.do?menuId=5&subMenuId=41&tabMenuId=183",
     "Not published: the full internal guidelines are not registered as public administrative rules; "
     "the Hi Korea manuals are the public restatement of them."),
]


def write(run, done):
    head = ["file", "title", "date", "source_url", "attachment", "issuer_number", "source", "title_en"]
    rows = {r[0]: r for r in run.rows}
    index = OUT / "index.tsv"
    if index.exists():                              # keep rows for files saved on earlier runs
        for line in index.read_text(encoding="utf-8").splitlines()[1:]:
            r = line.split("\t")
            if r[0] not in rows and (OUT / r[0]).exists():
                rows[r[0]] = r + [""] * (len(head) - len(r))
    with open(index, "w", encoding="utf-8") as f:
        f.write("\t".join(head) + "\n")
        for k in sorted(rows):
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in rows[k]) + "\n")
    missing = list(STATIC_MISSING) + run.missing
    old = OUT / "not-obtained.tsv"
    if old.exists():                                # a source not run this time keeps its entries
        for line in old.read_text(encoding="utf-8").splitlines()[1:]:
            r = tuple(line.split("\t"))
            if len(r) == 5 and not any(h in r[3] for h in done) and r not in missing \
                    and r[:1] not in [m[:1] for m in STATIC_MISSING]:
                missing.append(r)
    with open(old, "w", encoding="utf-8") as f:
        f.write("title\tattachment\tdate\turl\treason\n")
        for m in missing:
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in m) + "\n")
    return len(rows), len(missing)


def main():
    which = sys.argv[1:] or ["hikorea", "law"]
    OUT.mkdir(exist_ok=True)
    run, done = Run(), []
    for name, fn, host in (("hikorea", hikorea, "hikorea.go.kr"), ("law", law, "law.go.kr")):
        if name not in which:
            continue
        try:
            fn(run)
            done.append(host)
        except Refused as e:
            print(f"STOPPED {name}: {e}; not retried. Re-run later.")
            run.missing.append((f"{name}: run stopped", "", "", "https://www." + host, f"{e}; host not used further"))
        except Exception as e:                      # noqa: BLE001
            print(f"STOPPED {name}: {e}")
            run.missing.append((f"{name}: run stopped", "", "", "https://www." + host, f"error: {e}"))
    n, m = write(run, done)
    print(f"{run.new} new files; {n} in index.tsv ({run.size:,} bytes seen this run); "
          f"{m} entries in not-obtained.tsv")


if __name__ == "__main__":
    main()

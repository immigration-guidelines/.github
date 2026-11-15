#!/usr/bin/env python3
"""Download Japan's published immigration guidance (Immigration Services Agency, 出入国在留管理庁).

    python3 download_jp.py            # download what is missing, rewrite jp/index.tsv
    python3 download_jp.py --dry-run  # read the listing pages and print what would be saved

Source: https://www.moj.go.jp/isa/ (Ministry of Justice web site, Immigration Services Agency section).
Japan does not publish its examination manual (入国・在留審査要領) or its circulars to the
regional bureaus. What it does publish, and what this script collects, is:

  * the guidelines (ガイドライン) on change of status / extension, permanent residence and
    special permission to stay, with the published lists of approved and refused cases;
  * clarifications of the criteria for individual statuses of residence;
  * the highly-skilled-professional points material;
  * refugee recognition guidance (難民該当性判断の手引) and the agency's own country sheets;
  * the operating manuals (運用要領) and operating policies (運用方針) for the Specified
    Skilled Worker, Employment for Skill Development and Technical Intern Training schemes.

Much of the guidance is published as web pages, not PDF; those pages are saved as .html,
byte for byte. From each page the linked PDF documents are saved too, except application
forms and form templates. Word/Excel files (all forms) are not collected.

Listing pages are read on every run (that is how new documents are found); a page or
document that already exists in jp/ is never downloaded or written again.
robots.txt of www.moj.go.jp disallows only /isa/kouji/kouji2/, which is never requested.
Standard library only; one connection, sequential requests, a pause between them.
HTTP 403 or 429 stops the run.
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
OUT = ROOT / "jp"
BASE = "https://www.moj.go.jp"
ISA = BASE + "/isa/"
UA = "immigration-guidelines-archiver/1.0 (public research collection; stdlib urllib)"
PAUSE = 1.5                      # seconds between requests
MAX_BYTES = 1_000_000_000        # stop at roughly 1 GB
MAX_FILES = 3000
DISALLOWED = ("/isa/kouji/kouji2/",)   # robots.txt, read 2026-11-15

R = "applications/resources/"
# (category folder, page under /isa/, follow)
#   follow=True : the page is a hub; every agency page it links to (other than the site
#                 menu) is saved as well, with the PDFs linked from it.
#   follow=False: the page itself and the PDFs linked from it.
PAGES = [
    # permanent residence
    ("permanent-residence", R + "nyuukokukanri01_00007.html", True),
    # special permission to stay
    ("special-permission-to-stay", "deportation/resources/nyuukokukanri01_00008.html", True),
    # change of status / extension, criteria for individual statuses
    ("status-of-residence", R + "nyuukokukanri01_00006.html", True),
    ("status-of-residence", R + "nyuukokukanri07_00038.html", False),
    ("status-of-residence", R + "nyuukokukanri07_00013.html", False),
    ("status-of-residence", R + "nyuukokukanri07_00001.html", False),
    ("status-of-residence", R + "nyuukokukanri07_00119.html", False),
    ("status-of-residence", R + "nyukan_nyukan47.html", False),
    ("status-of-residence", "applications/procedures/torikeshi_00002.html", False),
    ("status-of-residence/epa-nurses", "policies/bill/nyukan_hourei_h10.html", False),
    ("status-of-residence/epa-nurses", "policies/bill/nyukan_hourei_h11.html", False),
    ("status-of-residence/epa-nurses", "policies/bill/nyuukokukanri07_00073.html", False),
    ("status-of-residence/epa-nurses", "policies/bill/nyuukokukanri07_00071.html", False),
    ("status-of-residence/epa-nurses", "policies/bill/nyuukokukanri07_00072.html", False),
    ("status-of-residence/epa-nurses", "policies/bill/nyuukokukanri07_00164.html", False),
    # highly skilled professionals
    ("highly-skilled", R + "newimmiact_3_index.html", False),
    ("highly-skilled", R + "newimmiact_3_system_index.html", False),
    ("highly-skilled", R + "newimmiact_3_evaluate_index.html", False),
    ("highly-skilled", R + "newimmiact_3_preferential_index.html", False),
    ("highly-skilled", R + "newimmiact_3_qa.html", False),
    ("highly-skilled", R + "nyuukokukanri01_00009.html", False),
    # refugee recognition
    ("refugee", "refugee/procedures/nanmin_00001.html", False),
    ("refugee", "refugee/procedures/07_00037.html", False),
    ("refugee", "refugee/procedures/higo_00001.html", False),
    ("refugee", "refugee/resources/nyuukokukanri03_00110.html", False),
    ("refugee", "refugee/resources/nyuukokukanri08_00041.html", False),
    ("refugee", "refugee/resources/nyuukokukanri03_00555.html", False),
    ("refugee", "refugee/resources/nyuukokukanri03_00116.html", False),
    ("refugee", "refugee/resources/nyukan_nyukan58.html", False),
    ("refugee", "refugee/resources/07_00040.html", False),
    ("refugee/country-information", "refugee/resources/07_00047.html", False),
    # deportation: supervisory measures, provisional release, departure orders
    ("deportation", "08_00045.html", False),
    ("deportation", "08_00051.html", False),
    ("deportation", "08_00053.html", False),
    ("deportation", "08_00050.html", False),
    ("deportation", "deportation/resources/seido01.html", False),
    # Specified Skilled Worker: operating manual, basic and sector policies
    ("specified-skilled-worker/manual", "applications/ssw/nyuukokukanri07_00201.html", False),
    ("specified-skilled-worker/policy", "applications/ssw/nyuukokukanri01_00132.html", False),
    ("specified-skilled-worker", "10_00262.html", False),
    ("specified-skilled-worker", "10_00233.html", False),
    # Employment for Skill Development (育成就労): operating manual, policies
    ("employment-for-skill-development/manual", "applications/nyuukokukanri07_00002.html", False),
    ("employment-for-skill-development/policy", "03_00169.html", False),
    # Technical Intern Training: operating manual
    ("technical-intern-training/manual", "applications/titp/nyuukokukanri07_00125.html", False),
]

# Single documents that are linked only from pages full of forms or statistics.
EXTRA_DOCS = [
    ("refugee", "content/001407458.pdf", "難民該当性判断の手引（令和５年１２月一部改訂）", "refugee/procedures/16-6.html"),
    ("refugee", "content/001444381.pdf", "難民該当性判断の手引（令和５年１２月一部改訂）（英語）", "refugee/procedures/16-6.html"),
    ("refugee", "content/930003127.pdf", "難民認定制度の運用の見直しの概要について（英語版）", "refugee/resources/index.html"),
    ("specified-skilled-worker", "content/001467866.pdf", "２号特定技能外国人の業務内容について", "applications/ssw/index.html"),
    ("specified-skilled-worker", "content/001440485.pdf", "介護分野に係る指定書の取扱いについて", "applications/ssw/index.html"),
]

# Pages linked from the hubs that are not case-officer guidance (statistics, reports,
# notices to schools, scheme home pages handled elsewhere, ministers' press conferences).
SKIP_CHILD = re.compile(
    r"/(10_00024|nyukan_nyukan89|nyuukokukanri07_00217|nyuukokukanri07_00218|nyukan95|10_00087|"
    r"nyuukokukanri07_00213|nyuukokukanri05_00014|10_00015|nyukan_nyukan62|nyuukokukanri07_00155|"
    r"nyuukokukanri10_00058|nyuukokukanri07_00222|16-4)\.html$")

# PDFs that are forms, templates, leaflets or filled-in examples: not collected.
FORM = re.compile(
    r"申請書|届出書|誓約書|様式|記載例|名簿|同意書|証明書|確認書|確認表|説明書|チェック|リーフレット|"
    r"パンフレット|ポスター|報告書|通知書|概要書|承諾書|提出書類|記入例|作成例|規程例|"
    r"履歴書|契約書|申告書|申立書|推薦状|理由書|計画書|一覧表|記載要領|立証資料")
KEEP = re.compile(r"^別紙|運用要領|ガイドライン|方針|基準について|新旧対照|一部改正")
GENERIC = re.compile(
    r"^(全体版|本文|別表|本文・別表|表紙・目次|こちら|概要|PDF|ＰＤＦ|Word|English|英語版?|"
    r"ＰＤＦはこちら|PDFはこちら|詳細はこちら|こちらを御覧ください。?)?$", re.I)

GLOSS = {
    "nyuukokukanri07_00058.html": "Guidelines for permission for change of status of residence and extension of period of stay",
    "nyukan_nyukan66.html": "Examples of refusals of extension / change of status applications",
    "nyuukokukanri07_00057.html": "Cases of change from Spouse of Japanese/Permanent Resident to Long-Term Resident: approved and refused",
    "nyukan_nyukan69.html": "Clarification of the Engineer/Specialist in Humanities/International Services status",
    "nyukan_nyukan43.html": "Clarification of the criteria for foreign business managers",
    "nyukan_nyukan50.html": "Guidelines for permission for permanent residence",
    "nyukan_nyukan36.html": "Guidelines on permanent residence for persons recognised as having contributed to Japan",
    "nyukan_nyukan16.html": "Permanent residence on grounds of contribution to Japan: approved and refused cases",
    "nyukan_nyukan85_00001.html": "Guidelines on special permission to stay (announcement)",
    "08_00035.html": "Guidelines on special permission to stay",
    "001407458.pdf": "Guide to determining refugee status (rev. Dec 2023)",
    "001444381.pdf": "Guide to determining refugee status (rev. Dec 2023), English",
    "nyuukokukanri07_00201.html": "Operating manual on the acceptance of Specified Skilled Workers",
    "nyuukokukanri07_00002.html": "Operating manual of the Employment for Skill Development system",
    "nyuukokukanri07_00125.html": "Operating manual of the Technical Intern Training system",
    "nyuukokukanri01_00132.html": "Specified Skilled Worker: basic policy, sector operating policies, operating guidelines",
    "03_00169.html": "Employment for Skill Development: basic policy and sector operating policies",
    "07_00047.html": "Country-of-origin information on main claims, by country",
    "newimmiact_3_evaluate_index.html": "Points-based system for highly skilled professionals: how points are assessed",
    "nyuukokukanri07_00063.html": "Internship guidelines (Designated Activities, public notice no. 9)",
    "nyuukokukanri07_00038.html": "Guidelines on Designated Activities for graduates of Japanese universities (notice no. 46)",
    "08_00045.html": "Supervisory measures system",
    "08_00050.html": "Provisional release system",
    "nyuukokukanri03_00110.html": "Outline of the review of the operation of the refugee recognition system",
}

# Known to exist but not published by the agency (written into not-obtained.tsv).
NOT_PUBLISHED = [
    ("入国・在留審査要領 (examination manual for entry and residence)", "",
     "not published; released only on freedom-of-information request (行政文書開示請求, https://www.moj.go.jp/isa/publications/gyoseibunsyo.html). "
     "The agency's page for repeatedly disclosed documents, https://www.moj.go.jp/isa/publications/disclosure/hanpukukeizoku.html, lists nothing."),
    ("通達・通知 to regional immigration bureaus (circulars and notices)", "",
     "no list or text of circulars is published on moj.go.jp/isa; only the guidelines derived from them"),
    ("難民認定事務取扱要領 / 違反審判要領 / 仮放免取扱要領 and other internal handling manuals", "",
     "not published; freedom-of-information request only"),
    ("米国国務省報告・英国内務省報告・豪州外務貿易省報告 (Japanese translations of foreign country reports)",
     "https://www.moj.go.jp/isa/refugee/resources/nyuukokukanri03_00007.html",
     "skipped on purpose: country-of-origin material, not guidance; also .../nyuukokukanri03_00045.html and .../nyuukokukanri03_00124.html"),
    ("難民等認定手続案内 (refugee procedure booklet, 31 languages)", "https://www.moj.go.jp/isa/07_00051.html",
     "skipped on purpose: booklet for applicants"),
    ("特定技能 分野別の基準 (sector-specific criteria notices) and 関係法令", "https://www.moj.go.jp/isa/applications/ssw/nyuukokukanri05_00019.html",
     "skipped on purpose: ministerial notices, i.e. legislation"),
    ("Application forms, form templates, Word/Excel files linked from the collected pages", "",
     "skipped on purpose: forms, not guidance"),
]


class Blocked(Exception):
    pass


def get(url, tries=2):
    """Fetch url. 403/429 are never retried: the site is saying no, so the run stops."""
    if any(d in url for d in DISALLOWED):
        print(f"  robots.txt disallows {url}")
        return None
    err = None
    for _ in range(tries):
        time.sleep(PAUSE)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                expected = r.headers.get("Content-Length", "")
                if expected.isdigit() and len(data) != int(expected):
                    raise OSError(f"incomplete: {len(data)} of {expected} bytes")
                return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"HTTP {e.code} for {url}")
            err = e
            if e.code in (404, 410):
                break
        except Exception as e:                      # noqa: BLE001 - timeouts, cut transfers
            err = e
        time.sleep(15)
    print(f"  FAILED {url}: {str(err)[:200]}")
    return None


def text_of(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).replace("​", "").strip()


ZEN = str.maketrans("０１２３４５６７８９．／", "0123456789./")
ERA = {"令和": 2018, "平成": 1988, "昭和": 1925, "R": 2018, "H": 1988}
DATE_PATTERNS = [
    (re.compile(r"(令和|平成|昭和)\s*(\d+)年\s*(\d+)月\s*(\d+)日"), "era3"),
    (re.compile(r"((?:19|20)\d\d)年\s*(\d+)月\s*(\d+)日"), "ymd"),
    (re.compile(r"((?:19|20)\d\d)[./](\d{1,2})[./](\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"\b(R|H)(\d{1,2})\.(\d{1,2})\.(\d{1,2})(?!\d)"), "era3"),
    (re.compile(r"(令和|平成|昭和)\s*(\d+)年\s*(\d+)月"), "era2"),
    (re.compile(r"((?:19|20)\d\d)年\s*(\d+)月"), "ym"),
]


def find_dates(text):
    """All dates in text as (position, 'YYYY-MM-DD' or 'YYYY-MM'), in order of appearance."""
    t = text.translate(ZEN).replace("元年", "1年")
    found = {}
    for rank, (pat, kind) in enumerate(DATE_PATTERNS):
        for m in pat.finditer(t):
            g = m.groups()
            try:
                if kind == "era3":
                    y, mo, d = ERA[g[0]] + int(g[1]), int(g[2]), int(g[3])
                elif kind == "ymd":
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                elif kind == "era2":
                    y, mo, d = ERA[g[0]] + int(g[1]), int(g[2]), 0
                else:
                    y, mo, d = int(g[0]), int(g[1]), 0
            except ValueError:
                continue
            if not (1950 <= y <= 2100 and 1 <= mo <= 12 and 0 <= d <= 31):
                continue
            if m.start() not in found or found[m.start()][0] > rank:
                found[m.start()] = (rank, f"{y:04d}-{mo:02d}" + (f"-{d:02d}" if d else ""))
    return [(pos, val[1]) for pos, val in sorted(found.items())]


def first_date(text):
    d = find_dates(text)
    return d[0][1] if d else ""


def content_of(page):
    i = page.find('id="contentsArea"')
    body = page[i:] if i >= 0 else page
    j = body.find("<footer")
    return body[:j] if j >= 0 else body


def page_title(page):
    m = re.search(r"<title>(.*?)</title>", page, flags=re.S)
    return text_of(m.group(1)).split("|")[0].strip() if m else ""


def page_date(page, title):
    """Date of a guidance page: 'last amended' wording first, then the title, then a date at the
    top of the text that is labelled as a revision, publication or as-of date."""
    head = text_of(content_of(page))[:700]
    m = re.search(r"(最終改[正訂定]|改[正訂定])\s*[:：]?\s*(.{0,20})", head)
    if m and first_date(m.group(2)):
        return first_date(m.group(2))
    dates = find_dates(title)
    if dates:
        return dates[-1][1]
    t = head[:400].translate(ZEN).replace("元年", "1年")
    m = re.search(r"((?:令和|平成)\s*\d+年\s*\d+月(?:\s*\d+日)?)\s*(?:一部)?(改|策定|更新|公表|現在|掲載|作成)", t)
    return first_date(m.group(1)) if m else ""


def anchors(page, url):
    """Yield (absolute url, link text, text just before the link, heading path) for the page body.
    Headings are h2-h5 and short stand-alone <strong> lines."""
    body = content_of(page)
    heads = []
    for m in re.finditer(r"<(h[2-5]|strong|b)\b[^>]*>(.*?)</\1>", body, flags=re.S):
        text = text_of(m.group(2))
        if not text or (m.group(1) in ("strong", "b") and (len(text) > 40 or "<a" in m.group(2))):
            continue
        heads.append((m.start(), 6 if m.group(1) in ("strong", "b") else int(m.group(1)[1]), text))
    hi, path = 0, {}
    for m in re.finditer(r'<a\b[^>]*\bhref="([^"]+)"[^>]*>(.*?)</a>', body, flags=re.S):
        while hi < len(heads) and heads[hi][0] < m.start():
            level = heads[hi][1]
            path = {k: v for k, v in path.items() if k < level}
            path[level] = heads[hi][2]
            hi += 1
        target = urllib.parse.urljoin(url, html.unescape(m.group(1)).strip()).split("#")[0]
        before = body[max(0, m.start() - 700):m.start()]
        cut = max(before.rfind(t) for t in ("</a>", "<br", "<p", "</p>", "<li", "<td", "<tr", "<div", "<h", "</h", "</li>", "<dd", "<dt", "</strong>"))
        ctx = before[cut:] if cut >= 0 else before
        ctx = text_of(ctx[ctx.find(">") + 1:] if cut >= 0 else ctx)
        yield target, text_of(m.group(2)), ctx.strip(" 　・:："), [path[k] for k in sorted(path)]


def clean_label(label):
    label = re.sub(r"[（(\[【]\s*(PDF|ＰＤＦ)(形式)?\s*[:：]?\s*[\d.,]*\s*[kKＫMＭGＧ]?[BＢ]?\s*[）)\]】]", "", label)
    return label.strip(" 　・")


def existing(folder, name):
    """A file saved earlier under this name, with or without a date prefix."""
    if not folder.is_dir():
        return None
    for f in folder.iterdir():
        if f.is_file() and f.stat().st_size > 0 and (f.name == name or f.name.endswith("_" + name)):
            return f
    return None


def refresh_target(page, url):
    m = re.search(r'http-equiv="Refresh"\s+content="\d+;\s*URL=([^"]+)"', page, flags=re.I)
    return urllib.parse.urljoin(url, m.group(1)) if m else None


def main():
    dry = "--dry-run" in sys.argv
    OUT.mkdir(exist_ok=True)
    rows, failed, skipped_forms = [], [], 0
    seen = {}                                        # url -> True
    state = {"total": sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()), "count": 0, "new": 0}

    def save(category, url, title, date, section, listed_on, body=None):
        """Record one file; download it unless it exists. Returns False if it could not be saved."""
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", urllib.parse.unquote(url.rsplit("/", 1)[1]))
        folder = OUT / category
        dest = existing(folder, name)
        if dest is None:
            if state["count"] >= MAX_FILES or state["total"] >= MAX_BYTES:
                failed.append((title, url, "size/file limit reached"))
                return False
            dest = folder / (f"{date}_{name}" if date else name)
            if dry:
                print(f"  would save {dest.relative_to(OUT)}  {title[:70]}")
            else:
                if body is None:
                    body = get(url)
                if body is None:
                    failed.append((title, url, "download failed (see log); re-run to retry"))
                    return False
                is_pdf = name.lower().endswith(".pdf")
                if (is_pdf and not body.startswith(b"%PDF")) or (not is_pdf and b"contentsArea" not in body):
                    print(f"  NOT A DOCUMENT {url}")
                    failed.append((title, url, "server returned something that is not the document"))
                    return False
                folder.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
                state["total"] += len(body)
                state["new"] += 1
                print(f"  saved {dest.relative_to(OUT)} ({len(body):,} bytes)")
        state["count"] += 1
        gloss = GLOSS.get(name, "")
        rows.append((str(dest.relative_to(OUT)), title, date, url, category, section, listed_on, gloss))
        return True

    def do_page(category, url, follow, listed_on=""):
        if url in seen:
            return
        seen[url] = True
        print(url.replace(BASE, ""))
        raw = get(url)
        if raw is None:
            failed.append(("(page)", url, "page could not be fetched"))
            return
        page = raw.decode("utf-8", "replace")
        target = refresh_target(page, url)
        if target and target.startswith(ISA) and target not in seen:
            return do_page(category, target, follow, listed_on)
        title = page_title(page)
        save(category, url, title, "" if follow else page_date(page, title), "", listed_on, body=raw)
        group, last_heading, children = "", None, []
        for target, label, ctx, path in anchors(page, url):
            if path != last_heading:
                group, last_heading = "", path
            if not target.startswith(BASE + "/") or target in nav:
                continue
            low = target.lower()
            label = clean_label(label)
            if low.endswith(".pdf"):
                own = label if not GENERIC.match(label) else f"{ctx} {label}".strip()
                if FORM.search(own) and not KEEP.search(own):
                    if target not in seen:
                        skipped_forms_box[0] += 1
                    continue
                doc_title = own
                if GENERIC.match(label) and ctx.startswith(("※", "（", "(")) and group:
                    doc_title = f"{group} {own}"
                elif GENERIC.match(label) and ctx:
                    group = ctx
                if len(doc_title) < 14 or doc_title.startswith("※") or GENERIC.match(label):
                    named = [h for h in path if h not in ("更新履歴", "改正履歴")]
                    doc_title = f"{named[-1] if named else title}：{doc_title}".rstrip("：")
                if target in seen:
                    continue
                seen[target] = True
                save(category, target, doc_title, first_date(own), " / ".join(path), url)
            elif follow and low.endswith(".html") and target.startswith(ISA) and not SKIP_CHILD.search(target):
                children.append(target)
        for child in children:
            do_page(category, child, False, url)

    skipped_forms_box = [0]
    nav = set()
    try:
        raw = get(ISA + "sitemap.html")              # the site menu: links to ignore on every page
        if raw is None:
            raise Blocked("could not read the site menu page")
        for m in re.finditer(r'href="([^"]+)"', raw.decode("utf-8", "replace")):
            nav.add(urllib.parse.urljoin(ISA + "sitemap.html", html.unescape(m.group(1))).split("#")[0])
        for category, path, follow in PAGES:
            nav.discard(ISA + path)
        for category, path, follow in PAGES:
            do_page(category, ISA + path, follow)
        for category, path, title, listed in EXTRA_DOCS:
            url = ISA + path
            if url not in seen:
                seen[url] = True
                save(category, url, title, first_date(title), "", ISA + listed)
    except Blocked as e:
        print(f"BLOCKED, stopping: {e}")
        failed.append(("(run stopped)", "", str(e)))
    skipped_forms = skipped_forms_box[0]

    if dry:
        print(f"\ndry run: {state['count']} items listed, {skipped_forms} form PDFs left out")
        return
    if not rows:
        print("nothing listed; index.tsv left as it was")
        sys.exit(1)
    with open(OUT / "index.tsv", "w", encoding="utf-8") as f:
        f.write("file\ttitle\tdate\tsource_url\tcategory\tsection\tlisted_on\ttitle_en\n")
        for row in rows:
            f.write("\t".join(c.replace("\t", " ").replace("\n", " ") for c in row) + "\n")
    with open(OUT / "not-obtained.tsv", "w", encoding="utf-8") as f:
        f.write("item\turl\treason\n")
        for row in failed + NOT_PUBLISHED:
            f.write("\t".join(c.replace("\t", " ") for c in row) + "\n")
    print(f"\n{state['count']} files in index ({state['new']} new), {state['total'] / 1e6:.1f} MB in {OUT}; "
          f"{skipped_forms} form PDFs left out")
    if failed:
        print(f"{len(failed)} not saved:")
        for title, url, why in failed:
            print(f"  {url}  {why}")
        sys.exit(1)


if __name__ == "__main__":
    main()

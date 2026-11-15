#!/usr/bin/env python3
"""Vietnam: internal working procedures (quy trình) for exit-entry cases, as published by a provincial
police exit-entry office (Phòng Quản lý xuất nhập cảnh, PA08) under its ISO 9001:2015 quality system.

    python3 download_vn.py

Source:
  khanhhoa  Công an tỉnh Khánh Hòa, ISO 9001:2015, "Lĩnh vực quản lý xuất nhập cảnh"
            (https://congan.khanhhoa.gov.vn/vi/linh-vuc-quan-ly-xuat-nhap-canhiso). The page builds its
            list with script, so the files are addressed by their published names
            /FileStorage/images/ISO/XNC/QT_PA08_NN.pdf (NN = 01-16) and QTNN_XNC.pdf (older series),
            found by probing 01-22 of both series on 15 Nov 2026. Kept: the eleven procedures on
            foreigners and stateless persons (issue III of 26 Apr 2024); left out: those on passports
            and ABTC cards of Vietnamese citizens (QT.PA08.08-11, 16; QT14/16/19/20.XNC). Each procedure sets out, step by step,
            who receives, checks, proposes and approves, the time limit for each step and the records kept;
            several cite Decision 7483/QĐ-BCA of 3 Nov 2023 (internal and electronic procedures of the
            Ministry of Public Security for exit-entry administrative procedures), which is not published.

The national Immigration Department (Cục Quản lý xuất nhập cảnh) publishes no working regulations or
guidance letters of its own; see vn/NOTES.txt. robots.txt of the host is read first and obeyed
(it disallows /cgi-bin/ and /Images/ only). Sequential, 1.6 s between requests; existing files are
skipped; vn/index.tsv and vn/not-obtained.tsv are rewritten. Python standard library only.
"""
import gzip
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "vn"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
PAUSE, PAUSE_IA = 1.6, 4.0
HEAD = ["file", "title", "date", "source_url", "kind", "title_en", "source", "note"]
CONTEXT = {}

KH = "https://congan.khanhhoa.gov.vn/FileStorage/images/ISO/XNC/"
SOURCES = {"khanhhoa": "congan.khanhhoa.gov.vn ISO 9001:2015 - lĩnh vực quản lý xuất nhập cảnh"}
# (code, date, Vietnamese title, English gloss)
PROC = [
    ('QT_PA08_01', "2024-04-26", 'Quy trình khai báo tạm trú cho người nước ngoài tại Việt Nam qua trang thông tin điện tử',
     'Procedure: temporary-residence declarations for foreigners made through the web portal'),
    ('QT_PA08_02', "2024-04-26", 'Quy trình cấp thị thực cho người nước ngoài tại Việt Nam',
     'Procedure: issuing visas to foreigners in Vietnam'),
    ('QT_PA08_03', "2024-04-26", 'Quy trình gia hạn tạm trú cho người nước ngoài tại Việt Nam',
     'Procedure: extending temporary stay of foreigners in Vietnam'),
    ('QT_PA08_04', "2024-04-26", 'Quy trình gia hạn tạm trú cho người đã được cấp giấy miễn thị thực',
     'Procedure: extending temporary stay of holders of a visa-exemption certificate'),
    ('QT_PA08_05', "2024-04-26", 'Quy trình cấp thẻ tạm trú cho người nước ngoài tại Việt Nam',
     'Procedure: issuing temporary residence cards to foreigners'),
    ('QT_PA08_06', "2024-04-26", 'Quy trình cấp giấy phép xuất nhập cảnh cho người không quốc tịch cư trú tại Việt Nam',
     'Procedure: issuing exit-entry permits to stateless persons residing in Vietnam'),
    ('QT_PA08_07', "2024-04-26", 'Quy trình cấp lại giấy phép xuất nhập cảnh cho người không quốc tịch cư trú tại Việt Nam',
     'Procedure: re-issuing exit-entry permits to stateless persons residing in Vietnam'),
    ('QT_PA08_12', "2024-04-26", 'Quy trình cấp thẻ thường trú cho người nước ngoài tại Việt Nam',
     'Procedure: issuing permanent residence cards to foreigners'),
    ('QT_PA08_13', "2024-04-26", 'Quy trình cấp đổi thẻ thường trú cho người nước ngoài tại Việt Nam',
     'Procedure: renewing permanent residence cards of foreigners'),
    ('QT_PA08_14', "2024-04-26", 'Quy trình cấp lại thẻ thường trú cho người nước ngoài tại Việt Nam',
     'Procedure: re-issuing (lost or damaged) permanent residence cards of foreigners'),
    ('QT_PA08_15', "2024-04-26", 'Quy trình cấp giấy phép vào khu vực cấm, khu vực biên giới cho người nước ngoài',
     'Procedure: permits for foreigners to enter restricted and border areas')
]
ITEMS = [("khanhhoa", f"khanhhoa/{d}_{c}.pdf", KH + c + ".pdf", t, d, "guidance", en,
          f"Khánh Hòa provincial police exit-entry office, internal procedure {c.replace('_', '.')}")
         for c, d, t, en in PROC]
NOT_OBTAINED = [
    ("Quyết định 7483/QĐ-BCA ngày 03/11/2023 ban hành quy trình nội bộ, quy trình điện tử thực hiện thủ tục hành chính trong lĩnh vực xuất nhập cảnh",
     "2023-11-03", "https://bocongan.gov.vn/",
     "not published: cited in the provincial procedures, but its text is on neither the Ministry's portal nor the national legal database (vbpl.vn)"),
]
class Refused(Exception):
    pass


_last, _fails, _closed, _robots = {}, {}, set(), {}


def _raw(url, timeout=180):
    host = urllib.parse.urlsplit(url).netloc
    if host in _closed:
        raise Refused(f"{host}: closed earlier in this run")
    wait = (PAUSE_IA if host.endswith("archive.org") else PAUSE) - (time.time() - _last.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, None, {"User-Agent": UA}), timeout=timeout,
                                    context=CONTEXT.get(host)) as r:
            data = r.read()
        if data[:2] == b"\x1f\x8b":                  # some servers gzip whatever the request says
            data = gzip.decompress(data)
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
    if host not in _robots:
        try:
            txt = _raw(f"{scheme}://{host}/robots.txt", 60).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code >= 500:
                _closed.add(host)
                raise Refused(f"{host}: robots.txt answered HTTP {e.code}") from None
            txt = ""
        if txt.lstrip()[:1] == "<":
            txt = ""
        rules, groups, fresh = [], [], True
        for line in txt.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (s.strip() for s in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if fresh and groups:
                    groups[-1][0].append(v.lower())
                else:
                    groups.append(([v.lower()], []))
                fresh = True
            elif k in ("allow", "disallow"):
                fresh = False
                if groups and v:
                    groups[-1][1].append((k, v))
        for ags, rs in groups:
            if any(a in ("*", "claudebot", "anthropic-ai", "claude-web", "gptbot", "ccbot") for a in ags):
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


def get(url):
    if not allowed(url):
        raise Refused(f"robots.txt disallows {url}")
    data = _raw(url)
    if re.search(rb"Just a moment|cf-challenge|captcha", data[:4000], re.I) and data[:5] != b"%PDF-":
        _closed.add(urllib.parse.urlsplit(url).netloc)
        raise Refused(f"bot check at {url}")
    return data


def bad(data, name):
    if len(data) < 300:
        return "too small"
    ext = name.rsplit(".", 1)[-1].lower()
    if ext == "pdf" and data[:5] != b"%PDF-":
        return "not a PDF"
    if ext == "docx" and data[:2] != b"PK":
        return "not a Word file"
    return None


def fetch(rel, url, missing, title, date):
    dest = OUT / rel
    if dest.exists() and dest.stat().st_size:
        return True
    try:
        data = get(url)
    except Refused:
        raise
    except Exception as e:                                # noqa: BLE001
        missing.append((title, date, url, f"download failed: {e}"))
        print(f"  FAILED {rel}: {e}")
        return False
    why = bad(data, rel)
    if why:
        missing.append((title, date, url, f"server returned {why}"))
        print(f"  REJECTED {rel}: {why}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.with_name(dest.name + ".part").write_bytes(data)
    dest.with_name(dest.name + ".part").replace(dest)
    print(f"  saved {rel} ({len(data):,} bytes)")
    return True


def tsv(path, head, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\t".join(head) + "\n")
        for r in rows:
            f.write("\t".join(str(c).replace("\t", " ").replace("\n", " ") for c in r) + "\n")



def main():
    names = list(SOURCES)
    which = [a for a in sys.argv[1:] if a in names] or names
    OUT.mkdir(exist_ok=True)
    missing, stopped = list(NOT_OBTAINED), set()
    for src, rel, url, title, date, kind, en, note in ITEMS:
        if src in which and src not in stopped:
            try:
                fetch(rel, url, missing, title, date)
            except Refused as e:
                print(f"STOPPED {src}: {e}")
                missing.append((title, date, url, f"{e}; host not used further"))
                stopped.add(src)
        elif src in stopped and not (OUT / rel).exists():
            missing.append((title, date, url, "not attempted: host closed earlier in the run"))
    rows = [[rel, title, date, url, kind, en, SOURCES[src], note]
            for src, rel, url, title, date, kind, en, note in ITEMS if (OUT / rel).exists()]
    tsv(OUT / "index.tsv", HEAD, rows)
    tsv(OUT / "not-obtained.tsv", ["title", "date", "url", "reason"], missing)
    print(f"{len(rows)} rows in index.tsv; {len(missing)} entries in not-obtained.tsv")


if __name__ == "__main__":
    main()

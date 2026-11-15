#!/usr/bin/env python3
"""Kazakhstan: nothing is downloaded. See kz/NOTES.txt.

    python3 download_kz.py

The procedure for foreigners' cases is set by legal acts (government resolutions, orders of
the Ministers of Internal Affairs and of Labour). Their official texts are on
  https://adilet.zan.kz  - robots.txt has a group naming GPTBot, ClaudeBot, anthropic-ai,
                           Claude-Web, ... with "Disallow: /": closed to this collection;
  https://www.gov.kz     - robots.txt disallows /uploads/ (where every attachment is) for "*".
No methodological recommendations or instructions for migration officers are published.

This script re-reads both robots.txt files, one request each, and says whether the
situation has changed; it keeps kz/index.tsv as a header-only file.
Standard library only.
"""
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "kz"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
CHECKS = [
    ("https://adilet.zan.kz/robots.txt", "ClaudeBot"),
    ("https://www.gov.kz/robots.txt", "Disallow: /uploads/"),
]


def main():
    OUT.mkdir(exist_ok=True)
    for url, marker in CHECKS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            print(f"{url}: {'unchanged' if marker in body else 'CHANGED - review by hand'} ({marker!r})")
        except Exception as e:                                  # noqa: BLE001
            print(f"{url}: not read ({e})")
    (OUT / "index.tsv").write_text("file\ttitle\tdate\tsource_url\tkind\ttitle_en\n", encoding="utf-8")
    print("index.tsv: 0 rows")


if __name__ == "__main__":
    main()

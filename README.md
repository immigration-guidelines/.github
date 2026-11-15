# Immigration guidelines

Scripts and notes for a collection of the guidance that immigration authorities publish for their own case officers, gathered in November 2026 for 19 jurisdictions, plus the country-of-origin reports several of them publish.

The documents themselves are kept in one repository per country in the [immigration-guidelines organisation](https://github.com/immigration-guidelines): `at`, `au`, `be`, `ca`, `ch`, `de`, `dk`, `es`, `eu`, `fi`, `fr`, `it`, `lu`, `nl`, `no`, `nz`, `pt`, `se`, `uk`, `usa`. The scripts expect each to be checked out in a folder next to them named by the same code (the United States folder is `us`, its repository `usa`). Each and has an `index.tsv` listing every file with its title, date and source. Country-of-origin reports are in each country's `coi/` folder.

## Files here

- `profile/README.md`: the organisation's front page on GitHub.

- `MISSING.md`: what could not be downloaded for each country, why, and how to get it by hand.
- `download.py`: Netherlands (circular and work instructions), Denmark, United Kingdom.
- `download_<code>.py`: one script per other country.
- `download_coi_central.py`, `download_coi_eu_nordic.py`, `download_coi_overseas.py`: country-of-origin reports.
- `resume-all.sh`: re-runs every script.

All scripts skip files that already exist, so they can be re-run to fill gaps.

## Ground rules the scripts follow

- One connection per site, with pauses between requests.
- A site that refuses automated access (bot check, HTTP 403 or 429, robots.txt) is not worked around. Other official sources or public web archives are used instead, or the item is listed in `MISSING.md` for manual download in a browser.

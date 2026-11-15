# Immigration guidelines: scripts and notes

This repository holds the download scripts and the gap list for the [immigration-guidelines](https://github.com/immigration-guidelines) collection: the guidance that immigration authorities publish for their own case officers, and the country-of-origin reports several of them publish.

The documents are not here. Each jurisdiction has its own repository, listed on the [organisation page](https://github.com/immigration-guidelines).

## What is in this repository

| File | Purpose |
|---|---|
| [`MISSING.md`](MISSING.md) | What could not be obtained for each jurisdiction, why, and how to get it by hand |
| `download.py` | Netherlands (circular, work instructions), Denmark, United Kingdom (guidance and country notes) |
| `download_<code>.py` | One script for each other jurisdiction, named by its two-letter code |
| `download_<code>_<layer>.py` | Sub-national or extra layers: `ch_cantons`, `ca_provinces`, `be_regions`, `de_federal`, `ca_irb`, `uk_tribunal`, and `<code>_labour` for labour authorities |
| `download_coi_central.py` | Country-of-origin reports: Germany, Netherlands, Belgium, Austria, Switzerland |
| `download_coi_eu_nordic.py` | Country-of-origin reports: EU asylum agency, Norway, Sweden, Denmark, Finland |
| `download_coi_overseas.py` | Country-of-origin reports: Canada, United States |
| `resume-all.sh` | Re-runs every script except Sweden's |
| `profile/README.md` | The organisation's front page on GitHub |

## Layout the scripts expect

Check out each jurisdiction's repository in a folder next to the scripts, named by its code:

```
immigration-guidelines/
├── download.py, download_*.py, MISSING.md   (this repository)
├── at/  be/  ca/  ch/  de/  ...             (one repository each)
└── us/                                       (repository "usa")
```

- Guidance goes into the jurisdiction's folder, with an `index.tsv` listing each file, its title, date and source address.
- Country-of-origin reports go into that folder's `coi/` subfolder, with their own `coi/index.tsv`. The EU asylum agency's are in `eu/coi/`.

## Running

The scripts need Python 3 and nothing else. Every script skips files that already exist, so re-running one only fills gaps.

```
./download.py nl            # Dutch circular, parts A, B and C
./download.py wi            # Dutch work instructions
./download.py dk            # Denmark
./download.py uk            # United Kingdom guidance
./download.py ukcoi         # United Kingdom country notes
python3 download_de.py      # any other jurisdiction, by code
python3 download_de.py sh   # some scripts take one source as an argument

python3 download_coi_central.py at be
python3 download_coi_eu_nordic.py fi --max-files 12000 --max-mb 12000
python3 download_coi_overseas.py ca us
```

Options worth knowing:

- `download.py uk --with-rules-archive` adds about 180 superseded versions of the immigration rules (slow).
- `download_se.py --low N` sets how far back to scan the Swedish database; lower numbers are older.
- `download_ca.py --with-updates` adds about 1,340 individual change notices.
- The country-of-origin scripts stop at a size limit per source; `--max-mb` and `--max-files` raise it where offered.

## Rules the scripts follow

- One connection per site, with a pause between requests.
- A site that refuses automated access (a bot check, HTTP 403 or 429, or a robots.txt rule) is not worked around. Another official source or a public web archive is used instead, or the item is listed in `MISSING.md` for manual download in a browser.
- Files are saved as published, without changes.

The documents remain the work of the authorities that published them.

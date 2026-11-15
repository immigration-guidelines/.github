# Immigration guidelines

The guidance that immigration authorities publish for their own case officers, collected in November 2026 for 19 jurisdictions and the EU, together with the country-of-origin reports several of them publish. Each jurisdiction has its own repository; the files are unmodified copies of what the authority published.

| Repository | Jurisdiction | Guidance files | Country-of-origin reports |
|---|---|---|---|
| [at](https://github.com/immigration-guidelines/at) | Austria | 4 | 331 |
| [au](https://github.com/immigration-guidelines/au) | Australia | – | 23 |
| [be](https://github.com/immigration-guidelines/be) | Belgium | 181 | 444 |
| [ca](https://github.com/immigration-guidelines/ca) | Canada | 1,572 | 879 |
| [ch](https://github.com/immigration-guidelines/ch) | Switzerland | 331 | 148 |
| [de](https://github.com/immigration-guidelines/de) | Germany (federal and states) | 813 | 868 |
| [dk](https://github.com/immigration-guidelines/dk) | Denmark | 64 | 266 |
| [es](https://github.com/immigration-guidelines/es) | Spain | 119 | – |
| [eu](https://github.com/immigration-guidelines/eu) | European Union | 163 | 419 |
| [fi](https://github.com/immigration-guidelines/fi) | Finland | 20 | 3,632 |
| [fr](https://github.com/immigration-guidelines/fr) | France | 364 | – |
| [it](https://github.com/immigration-guidelines/it) | Italy | 305 | – |
| [lu](https://github.com/immigration-guidelines/lu) | Luxembourg | 19 | – |
| [nl](https://github.com/immigration-guidelines/nl) | Netherlands | 292 | 65 |
| [no](https://github.com/immigration-guidelines/no) | Norway | 872 | 1,167 |
| [nz](https://github.com/immigration-guidelines/nz) | New Zealand | 1,822 | – |
| [pt](https://github.com/immigration-guidelines/pt) | Portugal | 341 | – |
| [se](https://github.com/immigration-guidelines/se) | Sweden | 103 | 119 |
| [uk](https://github.com/immigration-guidelines/uk) | United Kingdom | 635 | 177 |
| [usa](https://github.com/immigration-guidelines/usa) | United States | 346 | 770 |

## Berlin

The Berlin immigration office's guidance (Verfahrenshinweise zum Aufenthalt in Berlin, VAB) has a version history, so it is kept in two places:

- [de, folder `berlin/`](https://github.com/immigration-guidelines/de/tree/main/berlin): the source PDF of every known version from 2007 to 2026.
- [berlin_vab](https://github.com/immigration-guidelines/berlin_vab): the text of those versions, one commit and one tag per version, so changes can be read as diffs.

## How to use a repository

- `index.tsv` lists every file with its title, date and source address.
- Country-of-origin reports are in the `coi/` folder, with their own `coi/index.tsv`.
- Counts above are as committed; some collections are partial. [MISSING.md](https://github.com/immigration-guidelines/.github/blob/main/MISSING.md) says, country by country, what could not be obtained, why, and how to get it by hand.

## How it was collected

The download scripts are in [this organisation's `.github` repository](https://github.com/immigration-guidelines/.github). They use one connection per site with pauses between requests. A site that refuses automated access (bot check, HTTP 403 or 429, robots.txt) was not worked around: another official source or a public web archive was used instead, or the item was left for manual download and listed in `MISSING.md`.

The documents remain the work of the authorities that published them.

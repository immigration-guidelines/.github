# Immigration guidelines

The guidance that immigration authorities publish for their own case officers, collected from November 2026 for jurisdictions worldwide, together with the country-of-origin reports several of them publish. Each jurisdiction has its own repository; the files are unmodified copies of what the authority published.

Repositories by region. "Nothing obtainable" is a finding too: it means the authority publishes nothing for its officers, or that its sites refuse automated access; the repository's `NOTES.txt` says which, and lists what is known to exist.

### Europe

| Repository | Jurisdiction | Guidance files | Country-of-origin reports | Note |
|---|---|---|---|---|
| [at](https://github.com/immigration-guidelines/at) | Austria | 4 | 331 |  |
| [be](https://github.com/immigration-guidelines/be) | Belgium | 183 | 444 | federal; `regions/` for work permits |
| [cy](https://github.com/immigration-guidelines/cy) | Cyprus | – | – | nothing obtainable; see NOTES |
| [cz](https://github.com/immigration-guidelines/cz) | Czech Republic | 49 | – |  |
| [dk](https://github.com/immigration-guidelines/dk) | Denmark | 64 | 266 |  |
| [ee](https://github.com/immigration-guidelines/ee) | Estonia | 11 | – |  |
| [eu](https://github.com/immigration-guidelines/eu) | European Union | 163 | 419 |  |
| [fi](https://github.com/immigration-guidelines/fi) | Finland | 20 | 3,632 |  |
| [fr](https://github.com/immigration-guidelines/fr) | France | 363 | – |  |
| [de](https://github.com/immigration-guidelines/de) | Germany | 948 | 868 | federal and 13 states; `berlin/` holds every VAB version |
| [gr](https://github.com/immigration-guidelines/gr) | Greece | 226 | – |  |
| [is](https://github.com/immigration-guidelines/is) | Iceland | 21 | – |  |
| [ie](https://github.com/immigration-guidelines/ie) | Ireland | 176 | 931 |  |
| [it](https://github.com/immigration-guidelines/it) | Italy | 305 | – |  |
| [lt](https://github.com/immigration-guidelines/lt) | Lithuania | 37 | – |  |
| [lu](https://github.com/immigration-guidelines/lu) | Luxembourg | 19 | – |  |
| [mt](https://github.com/immigration-guidelines/mt) | Malta | – | – | nothing obtainable; see NOTES |
| [nl](https://github.com/immigration-guidelines/nl) | Netherlands | 292 | 65 |  |
| [no](https://github.com/immigration-guidelines/no) | Norway | 872 | 1,167 |  |
| [pt](https://github.com/immigration-guidelines/pt) | Portugal | 341 | – |  |
| [es](https://github.com/immigration-guidelines/es) | Spain | 119 | – |  |
| [se](https://github.com/immigration-guidelines/se) | Sweden | 113 | 119 |  |
| [ch](https://github.com/immigration-guidelines/ch) | Switzerland | 406 | 148 | federal directives; `cantons/` for 11 cantons |
| [uk](https://github.com/immigration-guidelines/uk) | United Kingdom | 635 | 177 |  |

### Americas

| Repository | Jurisdiction | Guidance files | Country-of-origin reports | Note |
|---|---|---|---|---|
| [ca](https://github.com/immigration-guidelines/ca) | Canada | 1,812 | 879 | federal; `provinces/` incl. Quebec's procedures guide |
| [cl](https://github.com/immigration-guidelines/cl) | Chile | 80 | – |  |
| [co](https://github.com/immigration-guidelines/co) | Colombia | 95 | – |  |
| [usa](https://github.com/immigration-guidelines/usa) | United States | 436 | 770 |  |

### Asia and Pacific

| Repository | Jurisdiction | Guidance files | Country-of-origin reports | Note |
|---|---|---|---|---|
| [au](https://github.com/immigration-guidelines/au) | Australia | – | 23 | guidance is paywalled; contributions welcome |
| [id](https://github.com/immigration-guidelines/id) | Indonesia | – | – | nothing obtainable; see NOTES |
| [jp](https://github.com/immigration-guidelines/jp) | Japan | 578 | – |  |
| [nz](https://github.com/immigration-guidelines/nz) | New Zealand | 1,821 | – |  |
| [ph](https://github.com/immigration-guidelines/ph) | Philippines | 56 | – |  |
| [kr](https://github.com/immigration-guidelines/kr) | South Korea | 208 | – |  |
| [th](https://github.com/immigration-guidelines/th) | Thailand | – | – | nothing obtainable; see NOTES |

### Middle East and Africa

| Repository | Jurisdiction | Guidance files | Country-of-origin reports | Note |
|---|---|---|---|---|
| [gh](https://github.com/immigration-guidelines/gh) | Ghana | 3 | – |  |
| [il](https://github.com/immigration-guidelines/il) | Israel | 509 | – |  |
| [ke](https://github.com/immigration-guidelines/ke) | Kenya | 2 | – |  |
| [ng](https://github.com/immigration-guidelines/ng) | Nigeria | 2 | – |  |
| [rw](https://github.com/immigration-guidelines/rw) | Rwanda | 3 | – |  |
| [za](https://github.com/immigration-guidelines/za) | South Africa | 38 | – |  |
| [tr](https://github.com/immigration-guidelines/tr) | Turkey | 11 | – |  |

More jurisdictions are being added.

## How to use a repository

- `index.tsv` lists every file with its title, date and source address.
- Country-of-origin reports are in the `coi/` folder, with their own `coi/index.tsv`.
- Germany includes Berlin: the `berlin/` folder of `de` holds every known version of the Berlin office's guidance since 2007, and [berlin_vab](https://github.com/immigration-guidelines/berlin_vab) holds their text as a history that can be read as diffs.
- Counts above are as committed; some collections are partial. [MISSING.md](https://github.com/immigration-guidelines/.github/blob/main/MISSING.md) says, country by country, what could not be obtained, why, and how to get it by hand.

## How it was collected

The download scripts are in [this organisation's `.github` repository](https://github.com/immigration-guidelines/.github). They use one connection per site with pauses between requests. A site that refuses automated access (bot check, HTTP 403 or 429, robots.txt) was not worked around: another official source or a public web archive was used instead, or the item was left for manual download and listed in `MISSING.md`.

The documents remain the work of the authorities that published them.

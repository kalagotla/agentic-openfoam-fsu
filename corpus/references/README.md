# References — offline literature repository

A small "literature library as code" for every source this repo cites:
the consultant server's `CITATION_SOURCES` and the case reference data
(Ghia, Armaly, XFOIL/Ladson, ONERA M6, …).

The goal is **offline verifiability**: a user should be able to read the
primary source behind any citation without hunting for it, and a citation
should never point at a dead or unverifiable link.

## Layout

| Path | Tracked? | What it is |
|---|---|---|
| `manifest.json` | yes | The index — one entry per source (citation, DOI/ISBN, URL, download method). Like a Zotero library file. |
| `fetch.py` | yes | Downloads every *open* source into `cache/`. Stdlib only. |
| `test_references.py` | yes | Validates the manifest is well-formed and in sync with the consultant. |
| `cache/` | **no** (gitignored) | The downloaded blobs (PDFs, archived HTML, OpenFOAM source copies). Can be large / copyrighted, so not committed. |

The manifest is the durable artifact; the blobs are regenerable.

## Fetch the sources

```sh
of2412                                  # source OpenFOAM (needed for source-code citations)
uv run python corpus/references/fetch.py       # download everything fetchable -> corpus/references/cache/
uv run python corpus/references/fetch.py --list   # preview without downloading
uv run python corpus/references/fetch.py menter_sst_2003 armaly_1983   # only specific ids
```

`fetch.py` reports one line per source:

- `OK` — downloaded into `cache/`.
- `skip` — already cached (use `--force` to refresh).
- `man` — **manual**: copyrighted book or paywalled paper that cannot be
  redistributed. The entry carries a DOI/ISBN; obtain it via your library.
- `FAIL` — an open source that didn't download (transient network/host
  issue). Re-run later.

## Access tiers

- **open** — freely downloadable (NASA TMR pages, NTRS reports, OpenFOAM
  source + User Guide, the XFOIL site).
- **open-mirror** — the canonical venue is paywalled but an open mirror
  exists (e.g. the Armaly 1983 JFM paper on a university course page); the
  manifest links the mirror and records the DOI of the original.
- **manual** — copyrighted textbooks (Versteeg, Wilcox) and paywalled
  journal papers (Ghia, Driver-Seegmiller, Le-Moin-Kim). Not downloadable;
  the manifest records the citation + DOI/ISBN. For the case data, the
  *digitized values* the repo actually uses ship in
  `cases/**/reference/*.json` — the manual entry just points to the source.

## Adding a source

1. Add an entry to `manifest.json` following the `schema` block at the top.
2. Use `download.method`: `http` (give `url` + `file`), `foam_src` (give
   `src` relative to `$FOAM_SRC` + `file`), or `manual` (give a `note`).
3. If it backs a consultant citation, set `consultant_tag` to the
   `CITATION_SOURCES` key — `test_references.py` enforces that every
   consultant tag has a manifest entry.
4. `uv run python corpus/references/fetch.py <id>` to pull it down.

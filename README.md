# Neighborhood Ledger

A Windows desktop app for Houston civic clubs and Super Neighborhood councils. It puts a neighborhood's public information in one place and helps residents act on it. It started as an office tool for the Greater Fifth Ward and now covers all 88 Houston Super Neighborhoods, each in its own workspace.

This is the **No-AI edition**: everything runs on public data sources, and no account or API key is needed.

**247 automated tests · local-only server (127.0.0.1) · one-click Windows installer**

## What it does

- **Today:** a dashboard of what changed in the neighborhood: news, City and council updates, open 311 cases and follow-ups.
- **News:**
  - Pulls current stories from local publishers, the City and the neighborhood's council districts.
  - Requires a publication date within 30 days.
  - Groups duplicate coverage of the same story into one card, conservatively.
- **311 case tracking:** looks up a City 311 case's live status and tracks the neighborhood's concerns and follow-ups.
- **Deed restriction lookup:**
  - Enter an address or HCAD account. The app reads the parcel's legal description (subdivision, section, lot, block) and searches the Harris County Clerk's real property index for restriction filings.
  - Results are ranked: this lot, this section, then subdivision-wide.
- **Plat and permit activity map:**
  - Scans the City's plat activity reports and the Permit E-Report.
  - Geocodes each record and keeps it only if it passes a point-in-polygon test against the official Super Neighborhood boundary.
  - Verified records go on a Leaflet map.
- **Minimum Lot Size application builder for residents:**
  1. Enter an address.
  2. Pick lots on a live parcel map.
  3. The app writes the block description (block number, street sides, cross streets).
  4. It calculates support by land area.
  5. It produces the filled-in City application PDF, a labeled boundary map and the 36 × 24 in notification sign.
- **Resident requests:** preparation guides and checklists for 18 City programs, such as traffic calming and sidewalks, with official links and printable briefs.
- **Newsletters, letters and certificates** built from saved records.
- **Backups:** per-neighborhood workspace export and import, plus database backups.

## How it's built

```
app/desktop.py              native window (pywebview) around a private local server; waits for saves before closing
app/neighborops_server.py   local companion service: approved public sources only, bound to 127.0.0.1, not a general proxy
app/office_server.py        office records API (SQLite) for cases, follow-ups, news, documents
app/storage.py              durable per-neighborhood storage, exports and backups
app/deed_*.py               HCAD parcel lookup + County Clerk index search and ranking
app/plat_*.py, geography.py plat/permit ingestion, geocoding, boundary tests (Shapely)
app/mls_*.py                MLS application: parcels, boundary, description text, map and PDF output (PyMuPDF, ReportLab)
app/news_*.py               news collection policy and duplicate grouping
app/*.js, *.css             single-page front end in plain JavaScript, Leaflet maps
installer.py, build_windows.py   per-user Windows installer with bundled Python (PyInstaller); no admin rights needed
tests/                      unittest suite (run_tests.py runs it against a temporary data folder)
```

Design rules that run through the code:
- **Public sources only:**
  - Every lookup shows the time it was checked and where the data came from.
  - A failed or ambiguous lookup says so instead of guessing.
- **The user stays in control:** nothing is submitted to the City or sent anywhere automatically. Drafts open for review and are saved only on request.
- **Local first:** records live on the user's computer, in a separate folder for each neighborhood.

## Run from source

```bash
pip install -r requirements-build.txt
python run_tests.py
python app/desktop.py
```

`app/mls-assets/application.pdf` is the City of Houston's published Special Minimum Lot Size application form. It's used as the fill-in template.

## Stack

Python 3 · SQLite · pywebview · JavaScript · Leaflet · Shapely · PyMuPDF · ReportLab · openpyxl · Playwright · PyInstaller

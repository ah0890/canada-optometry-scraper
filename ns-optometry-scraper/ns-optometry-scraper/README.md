# Canada Optometry Scraper — Nova Scotia (Pilot)

Collects **optician stores and optometry practices** across Nova Scotia, Canada
and exports a clean **CSV** and **Excel** file. Built to scale to every province
and territory by changing one bounding box and city list.

## Why this approach (read before running)

"Crawl the internet" sounds like scraping Google search or Yellow Pages directly.
Doing that gets your IP blocked, breaks every time a page layout changes, and is
often against those sites' Terms of Service — so it fails a paid test fast and
isn't defensible to a client. This project instead uses **structured data sources**
that are legal, stable, and built for exactly this:

| Source | Cost | API key | Coverage | Legal |
|---|---|---|---|---|
| **OpenStreetMap (Overpass)** | Free | None | Good | Open data (ODbL) |
| **Google Places API** | ~$32 USD / 1000 req (free tier first) | Yes | Best | ToS-compliant |

OSM runs immediately with no key. Add a Google key for maximum coverage. The two
sources are deduplicated and merged, so richer Google data fills gaps in OSM.

> For a client deliverable, also cross-check against the **Nova Scotia College of
> Optometrists** public "Find an Optometrist" directory — that's the authoritative
> registry of *licensed* practices. See the note at the bottom.

## Quick start (VS Code)

1. Open this folder in VS Code (`File → Open Folder`).
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Run it (free, no key needed):
   ```bash
   python src/scraper.py
   ```
4. Find your files in `data/`:
   - `nova_scotia_optometry.csv`
   - `nova_scotia_optometry.xlsx`

Or just press **F5** in VS Code and pick **"Run scraper (OSM only)"**.

## Adding Google Places (recommended for full coverage)

1. Create a Google Cloud project, enable **Places API**, create an API key.
2. Set the key as an environment variable:
   ```bash
   # Windows (then reopen terminal):
   setx GOOGLE_API_KEY "your_key_here"
   # macOS / Linux:
   export GOOGLE_API_KEY="your_key_here"
   ```
3. Run with Google enabled:
   ```bash
   python src/scraper.py --google        # OSM + Google merged
   python src/scraper.py --google-only   # Google only
   ```

## Output columns

`name, category, address, city, postal_code, province, phone, website, email,
latitude, longitude, source, place_id`

## Scaling to all provinces & territories

Each region needs only its bounding box and a city list. To extend, parameterize
`NS_BBOX` / `NS_CITIES` per province (e.g. a `provinces.py` dict) and loop. The
collect → dedupe → write pipeline is unchanged.

## Manual authoritative source (do this for the client)

The **Nova Scotia College of Optometrists** publishes a public directory of
licensed optometrists. It has no open API, so it should be collected manually or
with explicit permission, and used as the source of truth to validate the
scraped list. This keeps the deliverable accurate and defensible.

## Notes & limits

- Overpass public endpoints rate-limit; the script tries several mirrors.
- Respect each source's Terms of Service and licensing (OSM = ODbL attribution).
- Verify a sample of records before delivering to a client.

"""
Nova Scotia Optometry & Optician Scraper
=========================================
Collects optician stores and optometry practices across Nova Scotia, Canada
from multiple sources, deduplicates them, and writes CSV + Excel output.

Sources
-------
1. OpenStreetMap (Overpass API) -- free, no API key, runs immediately.
2. Google Places API           -- best coverage; requires GOOGLE_API_KEY env var.

Usage
-----
    python src/scraper.py                # OSM only (no key needed)
    python src/scraper.py --google       # OSM + Google Places (needs key)
    python src/scraper.py --google-only  # Google Places only

Set your key first (Google mode):
    Windows  : setx GOOGLE_API_KEY "your_key_here"   (reopen terminal)
    macOS/Lin: export GOOGLE_API_KEY="your_key_here"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field, asdict

import requests

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
PLACES_TEXT_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Nova Scotia bounding box (south, west, north, east)
NS_BBOX = (43.3, -66.4, 47.1, -59.7)


@dataclass
class Practice:
    name: str = ""
    category: str = ""          # optician / optometry / eyewear
    address: str = ""
    city: str = ""
    postal_code: str = ""
    province: str = "Nova Scotia"
    phone: str = ""
    website: str = ""
    email: str = ""
    latitude: float | None = None
    longitude: float | None = None
    source: str = ""
    place_id: str = ""

    def key(self) -> str:
        """Dedupe key: normalized name + rounded coordinates."""
        n = "".join(ch.lower() for ch in self.name if ch.isalnum())
        if self.latitude is not None and self.longitude is not None:
            return f"{n}|{round(self.latitude, 3)}|{round(self.longitude, 3)}"
        return f"{n}|{self.address.lower().strip()}"


# --------------------------------------------------------------------------- #
# OpenStreetMap / Overpass
# --------------------------------------------------------------------------- #
def fetch_osm() -> list[Practice]:
    s, w, n, e = NS_BBOX
    query = f"""
    [out:json][timeout:120];
    (
      node["shop"="optician"]({s},{w},{n},{e});
      way["shop"="optician"]({s},{w},{n},{e});
      node["healthcare"="optometrist"]({s},{w},{n},{e});
      way["healthcare"="optometrist"]({s},{w},{n},{e});
      node["amenity"="optometrist"]({s},{w},{n},{e});
    );
    out center tags;
    """
    print("[OSM] Querying Overpass API ...")
    resp = None
    last_err = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(
                url, data={"data": query}, timeout=180,
                headers={"User-Agent": "ns-optometry-scraper/1.0"},
            )
            resp.raise_for_status()
            print(f"[OSM] Got response from {url}")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[OSM] Mirror failed ({url}): {exc}")
            last_err = exc
            resp = None
    if resp is None:
        raise RuntimeError(f"All Overpass mirrors failed: {last_err}")
    elements = resp.json().get("elements", [])
    print(f"[OSM] Received {len(elements)} raw elements")

    results: list[Practice] = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            continue
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")

        shop = tags.get("shop", "")
        hc = tags.get("healthcare", "") or tags.get("amenity", "")
        category = "optician" if shop == "optician" else ("optometry" if "optomet" in hc else "eyewear")

        street = " ".join(
            filter(None, [tags.get("addr:housenumber", ""), tags.get("addr:street", "")])
        ).strip()

        results.append(
            Practice(
                name=name,
                category=category,
                address=street,
                city=tags.get("addr:city", ""),
                postal_code=tags.get("addr:postcode", ""),
                phone=tags.get("phone", "") or tags.get("contact:phone", ""),
                website=tags.get("website", "") or tags.get("contact:website", ""),
                email=tags.get("email", "") or tags.get("contact:email", ""),
                latitude=lat,
                longitude=lon,
                source="OpenStreetMap",
                place_id=f"osm/{el.get('type')}/{el.get('id')}",
            )
        )
    print(f"[OSM] Kept {len(results)} named practices")
    return results


# --------------------------------------------------------------------------- #
# Google Places
# --------------------------------------------------------------------------- #
NS_CITIES = [
    "Halifax", "Dartmouth", "Sydney", "Truro", "New Glasgow", "Glace Bay",
    "Kentville", "Amherst", "Bridgewater", "Yarmouth", "Antigonish",
    "New Minas", "Bedford", "Sackville NS", "Port Hawkesbury", "Digby",
    "Windsor NS", "Wolfville", "Stellarton", "Liverpool NS",
]
SEARCH_TERMS = ["optometrist", "optician", "eye care", "eyewear store"]


def fetch_google(api_key: str) -> list[Practice]:
    results: list[Practice] = []
    seen_ids: set[str] = set()

    for city in NS_CITIES:
        for term in SEARCH_TERMS:
            query = f"{term} in {city}, Nova Scotia"
            print(f"[Google] Searching: {query}")
            params = {"query": query, "region": "ca", "key": api_key}
            page = 0
            while True:
                r = requests.get(PLACES_TEXT_URL, params=params, timeout=60)
                data = r.json()
                status = data.get("status")
                if status not in ("OK", "ZERO_RESULTS"):
                    print(f"[Google] API status: {status} -- {data.get('error_message','')}")
                    break
                for item in data.get("results", []):
                    pid = item.get("place_id")
                    if not pid or pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    results.append(_google_details(pid, api_key, term))
                    time.sleep(0.05)
                token = data.get("next_page_token")
                page += 1
                if not token or page >= 3:
                    break
                time.sleep(2)  # token needs a moment to activate
                params = {"pagetoken": token, "key": api_key}
    print(f"[Google] Collected {len(results)} places")
    return results


def _google_details(place_id: str, api_key: str, term: str) -> Practice:
    fields = "name,formatted_address,formatted_phone_number,website,geometry,address_components"
    r = requests.get(
        PLACES_DETAILS_URL,
        params={"place_id": place_id, "fields": fields, "key": api_key},
        timeout=60,
    )
    d = r.json().get("result", {})
    comps = {c["types"][0]: c["long_name"] for c in d.get("address_components", []) if c.get("types")}
    loc = (d.get("geometry") or {}).get("location", {})
    category = "optometry" if "optomet" in term else ("optician" if "optician" in term else "eyewear")
    return Practice(
        name=d.get("name", ""),
        category=category,
        address=d.get("formatted_address", ""),
        city=comps.get("locality", ""),
        postal_code=comps.get("postal_code", ""),
        phone=d.get("formatted_phone_number", ""),
        website=d.get("website", ""),
        latitude=loc.get("lat"),
        longitude=loc.get("lng"),
        source="Google Places",
        place_id=place_id,
    )


# --------------------------------------------------------------------------- #
# Dedupe + output
# --------------------------------------------------------------------------- #
def deduplicate(practices: list[Practice]) -> list[Practice]:
    merged: dict[str, Practice] = {}
    for p in practices:
        k = p.key()
        if k not in merged:
            merged[k] = p
        else:
            existing = merged[k]
            # Fill blanks from the duplicate; prefer Google for richer data
            for f in ("address", "city", "postal_code", "phone", "website", "email"):
                if not getattr(existing, f) and getattr(p, f):
                    setattr(existing, f, getattr(p, f))
            if p.source not in existing.source:
                existing.source = f"{existing.source}; {p.source}"
    return list(merged.values())


def write_outputs(practices: list[Practice], outdir: str) -> None:
    import csv

    os.makedirs(outdir, exist_ok=True)
    practices.sort(key=lambda p: (p.city, p.name))
    cols = list(asdict(practices[0]).keys()) if practices else []

    csv_path = os.path.join(outdir, "nova_scotia_optometry.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in practices:
            w.writerow(asdict(p))
    print(f"[OUT] Wrote {csv_path}")

    try:
        import openpyxl
        from openpyxl.styles import Font

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Nova Scotia"
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True)
        for p in practices:
            d = asdict(p)
            ws.append([d[c] for c in cols])
        ws.freeze_panes = "A2"
        for col in ws.columns:
            width = max((len(str(c.value)) for c in col if c.value), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(width + 2, 50)
        xlsx_path = os.path.join(outdir, "nova_scotia_optometry.xlsx")
        wb.save(xlsx_path)
        print(f"[OUT] Wrote {xlsx_path}")
    except ImportError:
        print("[OUT] openpyxl not installed -- skipped Excel (run: pip install openpyxl)")


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Nova Scotia optometry scraper")
    ap.add_argument("--google", action="store_true", help="Add Google Places (needs GOOGLE_API_KEY)")
    ap.add_argument("--google-only", action="store_true", help="Use only Google Places")
    ap.add_argument("--outdir", default="data", help="Output directory")
    args = ap.parse_args()

    collected: list[Practice] = []

    if not args.google_only:
        try:
            collected += fetch_osm()
        except Exception as exc:  # noqa: BLE001
            print(f"[OSM] Failed: {exc}", file=sys.stderr)

    if args.google or args.google_only:
        key = os.environ.get("GOOGLE_API_KEY")
        if not key:
            print("[Google] GOOGLE_API_KEY not set -- skipping Google Places.", file=sys.stderr)
        else:
            try:
                collected += fetch_google(key)
            except Exception as exc:  # noqa: BLE001
                print(f"[Google] Failed: {exc}", file=sys.stderr)

    if not collected:
        print("No data collected.", file=sys.stderr)
        sys.exit(1)

    final = deduplicate(collected)
    print(f"\n[RESULT] {len(collected)} raw -> {len(final)} unique practices")
    write_outputs(final, args.outdir)


if __name__ == "__main__":
    main()

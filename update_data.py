import datetime
import json
import os
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request

SERIES = {
    "aus_cli": ("AUSLOLITOAASTSAM", "Australia OECD leading indicator", "index"),
    "us_curve": ("T10Y2Y", "US 10Y minus 2Y Treasury yield", "percentage points"),
    "us_unemployment": ("UNRATE", "US unemployment rate", "percent"),
    "us_credit": ("BAMLH0A0HYM2", "US high-yield option-adjusted spread", "percentage points"),
    "us_vix": ("VIXCLS", "CBOE volatility index", "index"),
    "us_industrial": ("INDPRO", "US industrial production", "index"),
}


def fetch_series(series_id, api_key):
    query = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": "1980-01-01",
    })
    url = "https://api.stlouisfed.org/fred/series/observations?" + query
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ECM-Dashboard/2.0"})
            with urllib.request.urlopen(req, timeout=25) as response:
                payload = json.load(response)
            points = []
            for obs in payload.get("observations", []):
                try:
                    points.append([obs["date"], float(obs["value"])])
                except (ValueError, TypeError, KeyError):
                    continue
            if not points:
                raise ValueError("API returned no numeric observations")
            return points
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(str(last_error))


def main():
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FRED_API_KEY is missing. Configure the GitHub Actions secret.")

    path = pathlib.Path(__file__).with_name("data.json")
    old = json.loads(path.read_text()) if path.exists() else {}
    sources = {}
    errors = {}
    successes = 0

    for key, (series_id, name, unit) in SERIES.items():
        try:
            points = fetch_series(series_id, api_key)
            sources[key] = {
                "id": series_id,
                "name": name,
                "unit": unit,
                "url": "https://fred.stlouisfed.org/series/" + series_id,
                "observations": points,
            }
            successes += 1
            print(f"Fetched {series_id}: {len(points)} observations")
        except Exception as exc:
            errors[key] = str(exc)
            print(f"FAILED {series_id}: {exc}")
            if key in old.get("sources", {}):
                sources[key] = old["sources"][key]

    if successes == 0:
        raise RuntimeError("No fresh series retrieved; existing data.json retained.")

    snapshot = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sources": sources,
        "errors": errors,
    }
    path.write_text(json.dumps(snapshot, separators=(",", ":")))
    print(f"Updated {successes} fresh series; {len(errors)} fetch failures")


if __name__ == "__main__":
    main()

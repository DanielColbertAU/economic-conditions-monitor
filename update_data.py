"""Refresh the ECM snapshot from FRED with bounded retries and safe diagnostics."""
import datetime
import json
import os
import pathlib
import random
import time
import urllib.error
import urllib.parse
import urllib.request

SERIES = {
    "aus_cli": ("AUSLOLITOAASTSAM", "Australia OECD leading indicator", "index"),
    "aus_unemployment": ("LRHUTTTTAUM156S", "Australia unemployment rate (OECD)", "percent"),
    "aus_employment": ("LFEMTTTTAUM647S", "Australia total employment (OECD)", "persons"),
    "aud_usd": ("DEXUSAL", "AUD/USD exchange rate", "USD per AUD"),
    "us_curve": ("T10Y2Y", "US 10Y minus 2Y Treasury yield", "percentage points"),
    "us_unemployment": ("UNRATE", "US unemployment rate", "percent"),
    "us_credit_long": ("BAA10Y", "US Moody's Baa minus 10Y Treasury spread", "percentage points"),
    "us_recession": ("USREC", "NBER US recession indicator (monthly)", "0 or 1"),
    "us_credit": ("BAMLH0A0HYM2", "US high-yield option-adjusted spread", "percentage points"),
    "us_vix": ("VIXCLS", "CBOE volatility index", "index"),
    "us_industrial": ("INDPRO", "US industrial production", "index"),
}

MAX_ATTEMPTS = 4
TIMEOUT_SECONDS = 30


class FetchError(Exception):
    """Safe-to-log diagnostic without credentials or raw response bodies."""


def fetch_series(series_id, api_key):
    params = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": "1850-01-01",
    })
    url = "https://api.stlouisfed.org/fred/series/observations?" + params
    last_error = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        retryable = True
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "ECM-Dashboard/3.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                content_type = response.headers.get("Content-Type", "").lower()
                body = response.read()
                status = response.status
            if not body.strip():
                raise FetchError(f"HTTP {status}: empty response body")
            if "json" not in content_type:
                raise FetchError(f"HTTP {status}: unexpected Content-Type {content_type[:90] or 'missing'}")
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise FetchError(f"HTTP {status}: invalid JSON response") from None
            if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
                raise FetchError("API JSON missing observations list")
            points = []
            for observation in payload["observations"]:
                try:
                    points.append([observation["date"], float(observation["value"])])
                except (ValueError, TypeError, KeyError):
                    continue
            if not points:
                raise FetchError("API returned no numeric observations")
            return points
        except urllib.error.HTTPError as exc:
            retryable = exc.code in (408, 429, 500, 502, 503, 504)
            last_error = f"HTTP {exc.code} ({'retryable' if retryable else 'non-retryable'})"
        except urllib.error.URLError as exc:
            # Avoid printing the exception: some libraries include request URLs in errors.
            last_error = f"network error ({type(exc.reason).__name__})"
        except TimeoutError:
            last_error = "connection timed out"
        except FetchError as exc:
            last_error = str(exc)
        except OSError as exc:
            last_error = f"I/O error ({type(exc).__name__})"

        print(f"{series_id}: attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}", flush=True)
        if not retryable or attempt == MAX_ATTEMPTS:
            break
        # Short exponential backoff with jitter to avoid repeated simultaneous requests.
        time.sleep(min(2 ** (attempt - 1), 12) + random.uniform(0, 0.5))
    raise FetchError(last_error)


def main():
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("FRED_API_KEY is missing; check repository Actions secrets")

    path = pathlib.Path(__file__).with_name("data.json")
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    sources, errors = {}, {}
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
            print(f"Fetched {series_id}: {len(points)} observations", flush=True)
        except FetchError as exc:
            errors[key] = str(exc)
            print(f"FAILED {series_id}: {exc}", flush=True)
            if key in old.get("sources", {}):
                sources[key] = old["sources"][key]
                print(f"Retained prior observations for {series_id}", flush=True)

    if successes == 0:
        raise RuntimeError("No fresh series retrieved; previous data.json preserved")

    snapshot = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "sources": sources,
        "errors": errors,
    }
    # Atomic replace: a partial write cannot corrupt the last good snapshot.
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    temporary.replace(path)
    print(f"Updated {successes} fresh series; {len(errors)} fetch failures", flush=True)


if __name__ == "__main__":
    main()

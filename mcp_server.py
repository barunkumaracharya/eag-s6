"""
MCP server for EAGV3 Session 6.

Nine tools, stdio transport:
    web_search, fetch_url, get_time, currency_convert,
    read_file, list_dir, create_file, update_file, edit_file

web_search:  Tavily primary, DuckDuckGo fallback. Hard-capped at 5 results.
fetch_url:   crawl4ai only — clean markdown via headless Chromium.
Usage for tavily and duckduckgo is logged to ./usage.json with monthly
rollover and a soft cap of 950/1000 on Tavily.

File tools are sandboxed under ./sandbox/. Run:  python mcp_server.py
"""

from __future__ import annotations
import aiohttp

import json
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Reconfigure stdout and stderr to utf-8 dynamically to prevent encoding errors on Windows
if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr:
    sys.stderr.reconfigure(encoding='utf-8')

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from ddgs import DDGS
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

MAX_SEARCH_RESULTS = 5  # hard cap — Tavily prices per result

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("eagv3-s6-server")

SANDBOX = Path(__file__).parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)

USAGE_PATH = Path(__file__).parent / "usage.json"
MONTHLY_CAP = 950  # leave 50/mo headroom on Tavily
_usage_lock = threading.Lock()


def _safe(path: str) -> Path:
    p = (SANDBOX / path).resolve()
    base = SANDBOX.resolve()
    if p != base and base not in p.parents:
        raise ValueError(f"Path '{path}' escapes the sandbox")
    return p


def _empty_usage(month: str) -> dict:
    return {
        "month": month,
        "tavily": {"count": 0, "errors": 0},
        "duckduckgo": {"count": 0, "errors": 0},
    }


def _load_usage() -> dict:
    month = datetime.now().strftime("%Y-%m")
    if not USAGE_PATH.exists():
        return _empty_usage(month)
    try:
        data = json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_usage(month)
    if data.get("month") != month:
        return _empty_usage(month)
    for k in ("tavily", "duckduckgo"):
        data.setdefault(k, {"count": 0, "errors": 0})
    return data


def _save_usage(data: dict) -> None:
    USAGE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _bump(provider: str, field: str = "count") -> None:
    with _usage_lock:
        data = _load_usage()
        data[provider][field] = data[provider].get(field, 0) + 1
        _save_usage(data)


def _under_cap(provider: str) -> bool:
    return _load_usage()[provider]["count"] < MONTHLY_CAP


def _tavily_search(query: str, max_results: int) -> list[dict]:
    from tavily import TavilyClient

    client = TavilyClient(os.environ["TAVILY_API_KEY"])
    resp = client.search(query=query, max_results=max_results, search_depth="advanced")
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in resp.get("results", [])
    ]


def _ddg_search(query: str, max_results: int) -> list[dict]:
    hits: list[dict] = []
    with DDGS() as ddgs:
        for backend in ("auto", "html", "lite"):
            try:
                hits = list(ddgs.text(query, max_results=max_results, backend=backend))
            except Exception:
                hits = []
            if hits:
                break
    return [
        {
            "title": h.get("title", ""),
            "url": h.get("href", ""),
            "snippet": h.get("body", ""),
        }
        for h in hits
    ]


async def _crawl4ai_fetch(url: str) -> dict:
    browser_cfg = BrowserConfig(verbose=False)
    run_cfg = CrawlerRunConfig(verbose=False)
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        r = await crawler.arun(url=url, config=run_cfg)
    # r.markdown is a str subclass (StringCompatibleMarkdown) that Pydantic
    # serializes as {} because its real field is private. Pull the raw string
    # out and force a plain str so FastMCP serializes correctly.
    md = r.markdown
    raw = (
        getattr(md, "raw_markdown", None)
        or getattr(md, "fit_markdown", None)
        or md
        or r.cleaned_html
        or r.html
        or ""
    )
    text = str(raw)
    return {
        "status": int(getattr(r, "status_code", None) or 200),
        "content_type": "text/markdown",
        "length_bytes": len(text.encode("utf-8")),
        "text": text,
    }


@mcp.tool()
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web (Tavily primary, DDG fallback). Hard-capped at 5 results. Example: web_search("python asyncio tutorial", 3)."""
    max_results = max(1, min(max_results, MAX_SEARCH_RESULTS))
    if os.environ.get("TAVILY_API_KEY") and _under_cap("tavily"):
        try:
            results = _tavily_search(query, max_results)
            if results:
                _bump("tavily")
                return results
        except Exception:
            _bump("tavily", "errors")
    results = _ddg_search(query, max_results)
    _bump("duckduckgo")
    return results


@mcp.tool()
async def fetch_url(url: str, timeout: int = 20) -> dict:
    """Fetch clean markdown from a URL via crawl4ai (headless Chromium). Example: fetch_url("https://example.com")."""
    return await _crawl4ai_fetch(url)


@mcp.tool()
def get_time(timezone: str = "UTC") -> dict:
    """Current time in a named IANA timezone. Example: get_time("Asia/Kolkata")."""
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    offset = now.utcoffset()
    offset_hours = offset.total_seconds() / 3600 if offset else 0.0
    return {
        "iso": now.isoformat(),
        "human": now.strftime("%A, %d %B %Y %H:%M:%S %Z"),
        "timezone": timezone,
        "offset_hours": offset_hours,
    }


@mcp.tool()
def get_date_for_day_in_next_week(day_name: str, city: str = "Delhi") -> str:
    """
    Get the date (YYYY-MM-DD) for a given day of the next week (e.g. 'Saturday', 'Monday')
    relative to the current date in the specified city (resolves city to timezone, falls back to UTC).
    """
    import datetime
    from zoneinfo import ZoneInfo
    import httpx
    
    day_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6
    }
    
    day_name_clean = day_name.lower().strip()
    target_weekday = day_map.get(day_name_clean)
    if target_weekday is None:
        for name, wd in day_map.items():
            if name in day_name_clean:
                target_weekday = wd
                break
    
    if target_weekday is None:
        return f"Error: Unknown day of the week '{day_name}'"
        
    timezone = "UTC"
    if city and city.lower() != "utc":
        try:
            if "/" in city:
                timezone = city
            else:
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
                with httpx.Client(timeout=10, follow_redirects=True) as client:
                    resp = client.get(geo_url)
                    if resp.status_code == 200:
                        geo_data = resp.json()
                        if "results" in geo_data and geo_data["results"]:
                            timezone = geo_data["results"][0].get("timezone", "UTC")
        except Exception:
            timezone = "UTC"
            
    try:
        tz = ZoneInfo(timezone)
        now = datetime.datetime.now(tz)
    except Exception:
        tz = ZoneInfo("UTC")
        now = datetime.datetime.now(tz)
        
    today_weekday = now.weekday()  # Monday is 0, Sunday is 6
    days_ahead = target_weekday - today_weekday
    if days_ahead < 0:
        days_ahead += 7
        
    target_date = now.date() + datetime.timedelta(days=days_ahead)
    return target_date.strftime("%Y-%m-%d")


@mcp.tool()
def get_date_relative_to_epoch(relative_days: int, source_date: str = "1970-01-01") -> str:
    """
    Get the date (YYYY-MM-DD) by adding or subtracting relative_days from a source_date (defaulting to epoch 0 '1970-01-01').
    Example: get_date_relative_to_epoch(10, '2026-05-15') returns '2026-05-25'.
    """
    from datetime import datetime, timedelta
    try:
        base_date = datetime.strptime(source_date.strip(), "%Y-%m-%d")
        target_date = base_date + timedelta(days=relative_days)
        return target_date.strftime("%Y-%m-%d")
    except (ValueError, OverflowError) as e:
        return f"Error: {str(e)}"


@mcp.tool()
def currency_convert(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert money between ISO-3 currencies via frankfurter.dev. Example: currency_convert(100, "USD", "INR")."""
    f = from_currency.upper()
    t = to_currency.upper()
    url = f"https://api.frankfurter.dev/v1/latest?amount={amount}&base={f}&symbols={t}"
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        data = r.json()
    converted = data["rates"][t]
    return {
        "amount": amount,
        "from": f,
        "to": t,
        "rate": converted / amount if amount else 0.0,
        "converted": converted,
        "date": data["date"],
        "source": "frankfurter.dev",
    }


@mcp.tool()
def read_file(path: str) -> dict:
    """Read a UTF-8 text file from the sandbox. Example: read_file("notes.txt")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    return {
        "path": path,
        "size_bytes": p.stat().st_size,
        "content": text,
        "encoding": "utf-8",
    }


@mcp.tool()
def list_dir(path: str = ".") -> list[dict]:
    """List a directory inside the sandbox. Example: list_dir(".")."""
    p = _safe(path)
    out = []
    for child in sorted(p.iterdir()):
        is_dir = child.is_dir()
        out.append({
            "name": child.name,
            "type": "dir" if is_dir else "file",
            "size_bytes": 0 if is_dir else child.stat().st_size,
        })
    return out


@mcp.tool()
def create_file(path: str, content: str) -> dict:
    """Create a new file in the sandbox; overwrites if it exists. Example: create_file("hello.txt", "hi")."""
    
    p = _safe(path)
    if p.exists():
        if p.is_file():
            p.unlink()
        else:
            raise ValueError(f"'{path}' exists and is a directory")
    if not p.parent.exists():
        raise ValueError(f"Parent directory of '{path}' does not exist")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def update_file(path: str, content: str) -> dict:
    """Overwrite an existing sandbox file. Example: update_file("hello.txt", "new body")."""
    p = _safe(path)
    if not p.exists():
        raise ValueError(f"File '{path}' does not exist")
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": path, "size_bytes": p.stat().st_size}


@mcp.tool()
def edit_file(path: str, find: str, replace: str, replace_all: bool = False) -> dict:
    """Find-and-replace inside a sandbox file. Example: edit_file("hello.txt", "foo", "bar")."""
    p = _safe(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(find)
    if count == 0:
        raise ValueError(f"'{find}' not found in '{path}'")
    if count > 1 and not replace_all:
        raise ValueError(
            f"'{find}' occurs {count} times in '{path}'; pass replace_all=True"
        )
    new_text = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
    p.write_text(new_text, encoding="utf-8")
    replacements = count if replace_all else 1
    return {
        "ok": True,
        "path": path,
        "replacements": replacements,
        "size_bytes": p.stat().st_size,
    }

@mcp.tool()
async def get_weather_forecast(city: str, date: str) -> str:
    """Get weather forecast for a city on a specific date. Example: get_weather_forecast('Kolkata', '2022-05-16')."""
    try:
        forecast_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return ValueError(f"Invalid date format: {date}. Use YYYY-MM-DD.")

    async with aiohttp.ClientSession() as session:
        # Step 1: Geocode the place to get latitude & longitude
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1"
        async with session.get(geo_url) as resp:
            if resp.status != 200:
                return ValueError(f"Error fetching location data: {resp.status}")
            geo_data = await resp.json()

        if "results" not in geo_data or not geo_data["results"]:
            return ValueError(f"Place '{city}' not found.")

        lat = geo_data["results"][0]["latitude"]
        lon = geo_data["results"][0]["longitude"]

        # Step 2: Get daily weather forecast
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode"
            f"&timezone=auto&start_date={forecast_date}&end_date={forecast_date}"
        )
        async with session.get(weather_url) as resp:
            if resp.status != 200:
                return ValueError(f"Error fetching weather data: {resp.status}")
            weather_data = await resp.json()

        if "daily" not in weather_data or not weather_data["daily"]["time"]:
            return ValueError(f"No forecast available for {city} on {date}.")

        # Extract forecast
        daily = weather_data["daily"]
        weather_code = daily['weathercode'][0]
        wmo_codes = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Drizzle: Light intensity",
            53: "Drizzle: Moderate intensity",
            55: "Drizzle: Dense intensity",
            56: "Freezing Drizzle: Light intensity",
            57: "Freezing Drizzle: Dense intensity",
            61: "Rain: Slight intensity",
            63: "Rain: Moderate intensity",
            65: "Rain: Heavy intensity",
            66: "Freezing Rain: Light intensity",
            67: "Freezing Rain: Heavy intensity",
            71: "Snow fall: Slight intensity",
            73: "Snow fall: Moderate intensity",
            75: "Snow fall: Heavy intensity",
            77: "Snow grains",
            80: "Rain showers: Slight",
            81: "Rain showers: Moderate",
            82: "Rain showers: Violent",
            85: "Snow showers: Slight",
            86: "Snow showers: Heavy",
            95: "Thunderstorm: Slight or moderate",
            96: "Thunderstorm with slight hail",
            99: "Thunderstorm with heavy hail"
        }
        try:
            wcode_val = int(weather_code)
            weather_desc = wmo_codes.get(wcode_val, "Unknown weather condition")
        except (ValueError, TypeError):
            weather_desc = "Unknown weather condition"

        forecast_text = (
            f"Weather forecast for {city} on {date}:\n"
            f"- Max Temp: {daily['temperature_2m_max'][0]}°C\n"
            f"- Min Temp: {daily['temperature_2m_min'][0]}°C\n"
            f"- Precipitation: {daily['precipitation_sum'][0]} mm\n"
            f"- Weather Code: {weather_code} ({weather_desc})"
        )

        return forecast_text
    return


if __name__ == "__main__":
    mcp.run(transport="stdio")

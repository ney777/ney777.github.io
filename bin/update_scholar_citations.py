#!/usr/bin/env python

import os
import re
import sys
import time
from datetime import datetime
from html import unescape
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def load_scholar_user_id() -> str:
    """Load the Google Scholar user ID from the configuration file."""
    config_file = "_data/socials.yml"
    if not os.path.exists(config_file):
        print(
            f"Configuration file {config_file} not found. Please ensure the file exists and contains your Google Scholar user ID."
        )
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        config_content = f.read()

    match = re.search(r"^scholar_userid:\s*([^#\n]+)", config_content, re.M)
    scholar_user_id = match.group(1).strip().strip("'\"") if match else ""
    if not scholar_user_id:
        print(
            "No 'scholar_userid' found in the configuration file. Please add 'scholar_userid' to _data/socials.yml."
        )
        sys.exit(1)
    return scholar_user_id


SCHOLAR_USER_ID: str = load_scholar_user_id()
OUTPUT_FILE: str = "_data/citations.yml"
SCHOLAR_URLS: tuple[str, ...] = (
    "https://scholar.google.com/citations",
    "https://scholar.google.com.hk/citations",
)


def strip_tags(value: str) -> str:
    """Remove HTML tags from a short Google Scholar table value."""
    return unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_int(value: str) -> int:
    """Parse citation metrics that may include commas or non-breaking spaces."""
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def fetch_profile_metrics() -> dict:
    """Fetch high-level citation metrics from the public Google Scholar profile page."""
    params = urlencode({"user": SCHOLAR_USER_ID, "hl": "en"})
    last_error = None

    for attempt in range(1, 4):
        for scholar_url in SCHOLAR_URLS:
            request = Request(
                f"{scholar_url}?{params}",
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0 Safari/537.36"
                    ),
                },
            )

            try:
                with urlopen(request, timeout=25) as response:
                    html = response.read().decode("utf-8", errors="replace")

                name_match = re.search(r'<div id="gsc_prf_in">(.*?)</div>', html, re.S)
                profile_name = strip_tags(name_match.group(1)) if name_match else ""

                metrics = {}
                rows = re.findall(
                    r'<tr>\s*<td class="gsc_rsb_sc1"[^>]*>(.*?)</td>\s*<td class="gsc_rsb_std"[^>]*>(.*?)</td>',
                    html,
                    re.S,
                )
                for label_html, value_html in rows:
                    label = strip_tags(label_html).lower()
                    metrics[label] = parse_int(strip_tags(value_html))

                if "citations" not in metrics:
                    raise RuntimeError("citation metrics were not present in the response")

                return {
                    "profile_name": profile_name,
                    "total_citations": metrics.get("citations", 0),
                    "h_index": metrics.get("h-index", 0),
                    "i10_index": metrics.get("i10-index", 0),
                }
            except Exception as error:
                last_error = error
                print(f"Attempt {attempt} via {scholar_url} failed: {error}")

        if attempt < 3:
            time.sleep(attempt * 5)

    raise RuntimeError(f"all Google Scholar fetch attempts failed: {last_error}")


def load_existing_metadata() -> dict:
    """Read the small metadata block from _data/citations.yml without external dependencies."""
    if not os.path.exists(OUTPUT_FILE):
        return {}

    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Warning: Could not read existing citation data from {OUTPUT_FILE}: {e}.")
        return {}

    metadata = {}
    for key in ("last_updated", "scholar_userid"):
        match = re.search(rf"^\s*{key}:\s*['\"]?([^'\"\n]+)", content, re.M)
        if match:
            metadata[key] = match.group(1).strip()
    return metadata


def quote_yaml(value: str) -> str:
    """Quote a short string for the generated YAML file."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_citation_data(metrics: dict, today: str) -> str:
    """Render citation metrics as the _data/citations.yml file."""
    return "\n".join(
        [
            "metadata:",
            f"  last_updated: {quote_yaml(today)}",
            f"  scholar_userid: {quote_yaml(SCHOLAR_USER_ID)}",
            f"  profile_name: {quote_yaml(metrics['profile_name'])}",
            f"  total_citations: {metrics['total_citations']}",
            f"  h_index: {metrics['h_index']}",
            f"  i10_index: {metrics['i10_index']}",
            "papers: {}",
            "",
        ]
    )


def get_scholar_citations() -> None:
    """Fetch and update Google Scholar citation data."""
    print(f"Fetching citations for Google Scholar ID: {SCHOLAR_USER_ID}")
    today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    existing_metadata = load_existing_metadata()

    # Check if the output file was already updated today
    if existing_metadata.get("last_updated"):
        print(f"Last updated on: {existing_metadata['last_updated']}")
        if (
            existing_metadata["last_updated"] == today
            and existing_metadata.get("scholar_userid") == SCHOLAR_USER_ID
        ):
            print("Citations data is already up-to-date. Skipping fetch.")
            return

    try:
        scholar_metrics = fetch_profile_metrics()
    except Exception as e:
        print(
            f"Error fetching author data from Google Scholar for user ID '{SCHOLAR_USER_ID}': {e}. Please check your internet connection and Scholar user ID."
        )
        sys.exit(1)

    print(
        "Found profile metrics: "
        f"citations={scholar_metrics['total_citations']}, "
        f"h-index={scholar_metrics['h_index']}, "
        f"i10-index={scholar_metrics['i10_index']}"
    )

    # Compare new data with existing data
    rendered_data = render_citation_data(scholar_metrics, today)
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            if f.read() == rendered_data:
                print("No changes in citation data. Skipping file update.")
                return

    if existing_metadata.get("last_updated") == today and existing_metadata.get("scholar_userid") == SCHOLAR_USER_ID:
        print("No changes in citation data. Skipping file update.")
        return

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(rendered_data)
        print(f"Citation data saved to {OUTPUT_FILE}")
    except Exception as e:
        print(
            f"Error writing citation data to {OUTPUT_FILE}: {e}. Please check file permissions and disk space."
        )
        sys.exit(1)


if __name__ == "__main__":
    try:
        get_scholar_citations()
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)

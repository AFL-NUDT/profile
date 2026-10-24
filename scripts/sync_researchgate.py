#!/usr/bin/env python3
"""Sync public ResearchGate metrics and publication titles without dependencies.

The existing JSON is never overwritten unless at least one usable metric or
three publication titles are extracted. Network failures leave it untouched.
"""

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROFILE_URL = "https://www.researchgate.net/profile/Wu-Hanshuo"
SOURCES = (
    PROFILE_URL,
    "https://r.jina.ai/https://www.researchgate.net/profile/Wu-Hanshuo",
    "https://api.allorigins.win/raw?url=" + urllib.parse.quote(PROFILE_URL, safe=""),
    "https://corsproxy.io/?" + urllib.parse.quote(PROFILE_URL, safe=""),
    "https://api.codetabs.com/v1/proxy?quest=" + urllib.parse.quote(PROFILE_URL, safe=""),
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AcademicProfileSync/1.0; +https://github.com/AFL-NUDT/profile)",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
NUMBER = r"(\d[\d,]*)"


def clean_text(value):
    value = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style\b[^>]*>[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def clean_title(value):
    value = clean_text(value).strip(" \t\r\n-–—|")
    return re.sub(r"\s+", " ", value)


def valid_title(value):
    if not 20 <= len(value) <= 500:
        return False
    lowered = value.lower()
    blocked = ("researchgate", "log in", "sign up", "publications by", "download citation")
    return not any(term in lowered for term in blocked) and len(value.split()) >= 3


def metric(text, label):
    patterns = (
        NUMBER + r"\s+" + label + r"\b",
        label + r"\s*\(\s*" + NUMBER + r"\s*\)",
        label + r"\s*[:：]\s*" + NUMBER,
    )
    values = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            values.append(int(match.group(1).replace(",", "")))
    return max(values) if values else None


def extract_metrics(document):
    text = clean_text(document)
    return {
        "publications": metric(text, "Publications?"),
        "citations": metric(text, "Citations?"),
        "reads": metric(text, "Reads?"),
    }


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_jsonld(document):
    results = []
    blocks = re.findall(
        r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>([\s\S]*?)</script>",
        document,
        flags=re.I,
    )
    for block in blocks:
        try:
            payload = json.loads(html.unescape(block))
        except (json.JSONDecodeError, ValueError):
            continue
        for item in walk_json(payload):
            kind = item.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]
            if not any(str(entry).lower() in {"scholarlyarticle", "article", "publication"} for entry in kinds):
                continue
            title = clean_title(str(item.get("headline") or item.get("name") or ""))
            url = item.get("url") if isinstance(item.get("url"), str) else None
            if valid_title(title):
                results.append((title, url))
    return results


def extract_html_links(document):
    results = []
    pattern = re.compile(
        r"<a\b[^>]*href=[\"']([^\"']*/publication/\d+[^\"']*)[\"'][^>]*>([\s\S]*?)</a>",
        flags=re.I,
    )
    for url, body in pattern.findall(document):
        title = clean_title(body)
        if valid_title(title):
            results.append((title, urllib.parse.urljoin(PROFILE_URL, html.unescape(url))))
    return results


def extract_markdown_links(document):
    results = []
    pattern = re.compile(r"\[([^\]]+)\]\((https?://(?:www\.)?researchgate\.net/publication/[^)]+|/publication/[^)]+)\)", flags=re.I)
    for raw_title, url in pattern.findall(document):
        title = clean_title(raw_title)
        if valid_title(title):
            results.append((title, urllib.parse.urljoin(PROFILE_URL, url)))
    return results


def extract_publications(document):
    candidates = extract_jsonld(document) + extract_html_links(document) + extract_markdown_links(document)
    unique = []
    seen = set()
    for title, url in candidates:
        key = re.sub(r"\W+", "", title).casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append({"title": title, "url": url})
        if len(unique) >= 30:
            break
    return unique


def categorize(title):
    lowered = title.lower()
    if re.search(r"transverse mode instability|\btmi\b|mode degradation", lowered):
        return "tmi"
    if re.search(r"amplifier|\bmopa\b", lowered):
        return "amplifier"
    if re.search(r"laser|oscillator|raman", lowered):
        return "laser"
    return "research"


def merge_publications(fresh, existing):
    previous = {
        re.sub(r"\W+", "", item.get("title", "")).casefold(): item
        for item in existing
        if isinstance(item, dict) and item.get("title")
    }
    merged = []
    for item in fresh:
        key = re.sub(r"\W+", "", item["title"]).casefold()
        old = previous.get(key, {})
        category = old.get("category") or categorize(item["title"])
        tags = old.get("tags")
        if not tags and category != "research":
            tags = [{"tmi": "TMI", "amplifier": "Fiber Amplifier", "laser": "Fiber Laser"}[category]]
        publication = {
            "title": item["title"],
            "description": old.get("description", ""),
            "category": category,
            "tags": tags or [],
        }
        if item.get("url"):
            publication["url"] = item["url"]
        merged.append(publication)
    return merged


def download(url, timeout):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def sync(output, timeout, strict):
    try:
        current = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Cannot read existing data: {error}", file=sys.stderr)
        return 1

    errors = []
    for source in SOURCES:
        try:
            print(f"Trying {source}", flush=True)
            document = download(source, timeout)
            metrics = extract_metrics(document)
            publications = extract_publications(document)
            found_metrics = {key: value for key, value in metrics.items() if value is not None}
            if not found_metrics and len(publications) < 3:
                raise ValueError("No reliable ResearchGate data found in the response")

            updated = dict(current)
            stats = dict(current.get("stats", {}))
            stats.update(found_metrics)
            updated["stats"] = stats
            if len(publications) >= 3:
                updated["publications"] = merge_publications(publications, current.get("publications", []))
            updated["updatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(output)
            print(f"Synced metrics={found_metrics}, publications={len(publications) if len(publications) >= 3 else 'kept existing'}")
            return 0
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            errors.append(f"{source}: {error}")
            print(f"Unavailable: {error}", file=sys.stderr, flush=True)
            time.sleep(1)

    print("ResearchGate sync failed; existing data was preserved.", file=sys.stderr)
    if strict:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/profile.json"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--strict", action="store_true", help="Fail when every source is unavailable")
    args = parser.parse_args()
    return sync(args.output, args.timeout, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())

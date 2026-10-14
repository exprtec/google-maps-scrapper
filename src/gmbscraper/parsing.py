from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

CID_PATTERN = re.compile(r"[?&]cid=([0-9]+)")
PLACE_ID_PATTERN = re.compile(r"(0x[a-fA-F0-9]+:0x[a-fA-F0-9]+)")
LAT_LNG_PATTERN = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
# Matches Google's relative review dates like "5 min ago", "an hour ago",
# "a day ago", "2 weeks ago", "3 months ago", "5 years ago".
# Group 1 = optional number, group 2 = unit.
RELATIVE_DATE_RE = re.compile(
    r"(?:an?\s+|(\d+)\s+)(minute|min|hour|day|week|month|year)s?\s+ago",
    re.IGNORECASE,
)
# Approximate day counts used to convert each relative unit to an absolute date.
RELATIVE_DATE_UNIT_DAYS = {
    "minute": 1 / 1440,
    "min": 1 / 1440,
    "hour": 1 / 24,
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}
COMMON_MULTI_PART_SUFFIXES = {
    "asn.au",
    "com.au",
    "edu.au",
    "gov.au",
    "id.au",
    "net.au",
    "org.au",
    "ac.nz",
    "co.nz",
    "geek.nz",
    "gen.nz",
    "govt.nz",
    "net.nz",
    "org.nz",
    "school.nz",
}
LEGAL_NAME_TOKENS = {"pty", "ltd", "limited", "inc", "incorporated"}
NAME_STOP_WORDS = LEGAL_NAME_TOKENS | {
    "a",
    "an",
    "and",
    "at",
    "au",
    "australia",
    "australian",
    "care",
    "centre",
    "center",
    "clinic",
    "co",
    "community",
    "company",
    "for",
    "group",
    "health",
    "healthcare",
    "home",
    "living",
    "nz",
    "of",
    "plc",
    "provider",
    "providers",
    "service",
    "services",
    "support",
    "supports",
    "the",
}
GENERIC_SEARCH_HEADINGS = frozenset({"results", "search results"})


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def parse_decimal(value: Any) -> Decimal | None:
    raw = normalize_text(value).replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def parse_int(value: Any) -> int | None:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else None


def parse_review_count_label(value: Any) -> int | None:
    raw = normalize_text(value).lower()
    match = re.fullmatch(r"([0-9][0-9,]*)\s+reviews?", raw)
    if match:
        return parse_int(match.group(1))
    match = re.fullmatch(r"\d(?:\.\d)?\s+\(([0-9][0-9,]*)\)", raw)
    if match:
        return parse_int(match.group(1))
    match = re.search(r"\b([0-9][0-9,]*)\s+reviews?\b", raw)
    if match:
        return parse_int(match.group(1))
    return None


def parse_relative_date(value: Any, *, reference: date | None = None) -> str:
    raw = normalize_text(value).lower()
    if raw in ("just now", "now"):
        return (reference or date.today()).isoformat()
    match = RELATIVE_DATE_RE.search(raw)
    if not match:
        return ""
    amount = int(match.group(1)) if match.group(1) else 1
    unit = match.group(2).lower()
    days = amount * RELATIVE_DATE_UNIT_DAYS[unit]
    base = reference or date.today()
    return (base - timedelta(days=days)).isoformat()


INIT_STATE_REVIEW_COUNT_RE = re.compile(r"\[null,(\d+),null,null,1\]")


def read_review_count_from_page_source(html: str) -> int | None:
    """Fallback review-count extraction from Google's embedded init-state blob.

    Useful when the visible DOM doesn't expose an aggregate review count
    (e.g. a stripped-down/limited view).
    """
    marker = "window.APP_INITIALIZATION_STATE="
    start = html.find(marker)
    chunk = html[start : start + 1_000_000] if start != -1 else html
    matches = INIT_STATE_REVIEW_COUNT_RE.findall(chunk)
    if not matches:
        return None
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return int(unique[0])
    return int(matches[0])


def normalize_phone(value: Any) -> str:
    """Normalize to a comparable local-number suffix (AU/NZ-style leading 0)."""
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("0011"):
        digits = digits[4:]
    if digits.startswith("61") and len(digits) >= 10:
        digits = "0" + digits[2:]
    if len(digits) == 9:
        digits = "0" + digits
    return digits[-9:] if len(digits) >= 9 else digits


def normalize_domain(value: Any) -> str:
    """Reduce a URL to its comparable registrable domain (unwraps Google redirects)."""
    raw = normalize_text(value).lower()
    if not raw:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw):
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.hostname and "google." in parsed.hostname and parsed.path == "/url":
        query = parse_qs(parsed.query)
        for key in ("q", "url"):
            if query.get(key):
                return normalize_domain(query[key][0])
    host = (parsed.hostname or "").removeprefix("www.").rstrip(".")
    parts = [part for part in host.split(".") if part]
    if len(parts) <= 2:
        return host
    suffix2 = ".".join(parts[-2:])
    suffix3 = ".".join(parts[-3:])
    return suffix3 if suffix2 in COMMON_MULTI_PART_SUFFIXES else ".".join(parts[-2:])


def normalize_name(value: Any) -> str:
    """Strip legal suffixes and generic industry words so names compare on the memorable part."""
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", normalize_text(value).lower().replace("&", " and "))
        if token not in NAME_STOP_WORDS
    ]
    return " ".join(tokens)


def extract_place_id(url: str) -> str:
    cid_match = CID_PATTERN.search(url or "")
    if cid_match:
        return cid_match.group(1)
    id_match = PLACE_ID_PATTERN.search(url or "")
    return id_match.group(1) if id_match else ""


def extract_lat_lng(url: str) -> tuple[Decimal | None, Decimal | None]:
    match = LAT_LNG_PATTERN.search(url or "")
    if not match:
        return None, None
    return parse_decimal(match.group(1)), parse_decimal(match.group(2))


def extract_place_name_from_url(url: str) -> str:
    match = re.search(r"/maps/place/([^/@?]+)", url or "")
    if not match:
        return ""
    return normalize_text(unquote(match.group(1).replace("+", " ")))


def is_generic_search_heading(value: str) -> bool:
    return normalize_text(value).lower() in GENERIC_SEARCH_HEADINGS

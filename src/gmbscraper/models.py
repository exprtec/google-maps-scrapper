from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class PlaceProfile:
    """Everything scraped off a single Google Maps place page."""

    rank: int = 1
    name: str = ""
    category: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    rating: Decimal | None = None
    review_count: int | None = None
    maps_url: str = ""
    place_id: str = ""
    lat: Decimal | None = None
    lng: Decimal | None = None
    match_reason: str | None = None


@dataclass
class MapsReview:
    external_id: str
    stars: int
    username: str
    text: str
    date_text: str = ""
    date: str = ""

    def resolved_external_id(self) -> str:
        if self.external_id:
            return self.external_id
        raw = f"{self.username}|{self.date_text}|{self.text[:120]}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass
class BusinessIdentity:
    """The business as known from your own records (e.g. a lead or provider)."""

    name: str
    website: str | None = None


@dataclass
class OutletIdentity:
    """A specific outlet/location of the business, used to disambiguate matches."""

    name: str
    phone: str | None = None
    address: str | None = None


@dataclass(frozen=True)
class MapsView:
    lat: float
    lng: float
    zoom: int


@dataclass(frozen=True)
class SearchWindow:
    south: float
    west: float
    north: float
    east: float
    zoom: int
    label: str

    @property
    def center_lat(self) -> float:
        return (self.south + self.north) / 2

    @property
    def center_lng(self) -> float:
        return (self.west + self.east) / 2


@dataclass(frozen=True)
class MapsSearchLink:
    maps_url: str
    fallback_name: str
    search_rank: int | None

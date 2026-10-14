from __future__ import annotations

from gmbscraper.models import BusinessIdentity, OutletIdentity, PlaceProfile
from gmbscraper.parsing import (
    normalize_domain,
    normalize_name,
    normalize_phone,
    normalize_strict_name,
)

_REASON_RANK = {
    "phone_and_domain_match": 0,
    "phone_match": 1,
    "domain_match": 2,
    "exact_name_match": 3,
}


def has_match_key(outlet: OutletIdentity, business: BusinessIdentity) -> bool:
    """Whether there's enough identity signal to attempt a match at all."""
    return bool(
        normalize_phone(outlet.phone)
        or normalize_domain(business.website)
        or normalize_name(business.name)
        or normalize_name(outlet.name)
    )


def match_place(
    place: PlaceProfile,
    outlet: OutletIdentity,
    business: BusinessIdentity,
) -> PlaceProfile | None:
    """Score a scraped place against known identity, tagging `place.match_reason` on success."""
    outlet_phone = normalize_phone(outlet.phone)
    place_phone = normalize_phone(place.phone)
    business_domain = normalize_domain(business.website)
    place_domain = normalize_domain(place.website)
    # Names are compared strictly: dropping generic words such as "care" made
    # "Connect Care Australia" and "Care Connect" both reduce to "connect".
    place_name = normalize_strict_name(place.name)
    business_name = normalize_strict_name(business.name)
    outlet_name = normalize_strict_name(outlet.name)
    phone_match = bool(outlet_phone and place_phone and outlet_phone == place_phone)
    domain_match = bool(business_domain and place_domain and business_domain == place_domain)
    exact_name_match = bool(place_name and place_name in {business_name, outlet_name})
    if not phone_match and not domain_match and not exact_name_match:
        return None
    if phone_match and domain_match:
        place.match_reason = "phone_and_domain_match"
    elif phone_match:
        place.match_reason = "phone_match"
    elif domain_match:
        place.match_reason = "domain_match"
    else:
        place.match_reason = "exact_name_match"
    return place


def is_definitive_match(place: PlaceProfile) -> bool:
    """True if the match reason is strong enough to stop searching further candidates."""
    return place.match_reason in _REASON_RANK


def pick_best_match(places: list[PlaceProfile]) -> PlaceProfile | None:
    if not places:
        return None
    return sorted(
        places,
        key=lambda item: (_REASON_RANK.get(item.match_reason or "", 99), item.rank),
    )[0]

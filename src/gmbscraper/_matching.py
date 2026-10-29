from __future__ import annotations

import re

from gmbscraper.models import BusinessIdentity, OutletIdentity, PlaceProfile
from gmbscraper.parsing import normalize_domain, normalize_name, normalize_phone

_REASON_RANK = {
    "phone_and_domain_match": 0,
    "phone_match": 1,
    "domain_match": 2,
    "exact_name_match": 3,
}
# Sites many unrelated businesses share, so they say nothing about identity.
_SHARED_SITES = frozenset(
    {
        "business.site",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "linktr.ee",
        "wixsite.com",
    }
)
# State codes and postcodes in an address segment like "Rosebery, NSW, 2018".
_ADDRESS_NOISE = re.compile(r"\b(?:act|nsw|nt|qld|sa|tas|vic|wa|\d+)\b")


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
    place_name = normalize_name(place.name)
    business_name = normalize_name(business.name)
    outlet_name = normalize_name(outlet.name)
    phone_match = bool(outlet_phone and place_phone and outlet_phone == place_phone)
    domain_match = bool(business_domain and place_domain and business_domain == place_domain)
    exact_name_match = (
        bool(place_name and place_name in {business_name, outlet_name})
        and not _is_other_website(business_domain, place_domain)
        and not _is_locality(place, place_name, outlet)
    )
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


def _is_other_website(business_domain: str, place_domain: str) -> bool:
    """Both sides list a website and it's a different one: a similar-named business.

    Only the name part counts, so acme.com, acme.com.au and ac-me.com are the same site.
    """
    business_site = _site_name(business_domain)
    place_site = _site_name(place_domain)
    return bool(business_site and place_site and business_site != place_site)


def _site_name(domain: str) -> str:
    if "." not in domain or domain in _SHARED_SITES:
        return ""
    return domain.split(".")[0].replace("-", "")


def _is_locality(place: PlaceProfile, place_name: str, outlet: OutletIdentity) -> bool:
    """Whether a name-only candidate is a suburb or landmark rather than a business.

    Searching "<business> <suburb>" often returns the suburb itself, and outlet
    names like "Rosebery Clinic" reduce to "rosebery" once generic words go.
    """
    if not (
        normalize_phone(place.phone) or normalize_domain(place.website) or place.address.strip()
    ):
        return True
    return place_name in {
        normalize_name(_ADDRESS_NOISE.sub(" ", segment.lower()))
        for segment in (outlet.address or "").split(",")
    }


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

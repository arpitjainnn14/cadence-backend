"""Known merchants: name to website domain, used for logos (Google's favicon service)."""

import re

KNOWN_MERCHANTS: dict[str, str] = {
    "netflix": "netflix.com",
    "prime video": "primevideo.com",
    "amazon prime": "primevideo.com",
    "apple": "apple.com",
    "icloud": "apple.com",
    "spotify": "spotify.com",
    "youtube": "youtube.com",
    "youtube premium": "youtube.com",
    "cult": "cult.fit",
    "cult fit": "cult.fit",
    "swiggy one": "swiggy.com",
    "zomato gold": "zomato.com",
    "hotstar": "hotstar.com",
    "jiohotstar": "hotstar.com",
    "chatgpt": "openai.com",
    "openai": "openai.com",
    "notion": "notion.so",
    "google one": "one.google.com",
    "linkedin premium": "linkedin.com",
    "audible": "audible.in",
    "zee5": "zee5.com",
    "sonyliv": "sonyliv.com",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    """Lowercase, punctuation to spaces, single-spaced."""
    return _NON_ALNUM.sub(" ", name.lower()).strip()


def resolve_domain(name: str) -> str | None:
    """Domain of the longest known merchant name contained in `name` (whole words), or None."""
    padded = f" {_normalise(name)} "
    matches = [key for key in KNOWN_MERCHANTS if f" {key} " in padded]
    return KNOWN_MERCHANTS[max(matches, key=len)] if matches else None


def logo_url(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

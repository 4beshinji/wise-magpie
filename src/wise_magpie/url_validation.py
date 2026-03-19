"""URL code point validation per the WHATWG URL Standard.

Reference: https://url.spec.whatwg.org/#url-code-points

A URL code point is:
- ASCII alphanumeric
- U+0021 (!), U+0024 ($), U+0026 (&), U+0027 ('), U+0028 ((), U+0029 ()),
  U+002A (*), U+002B (+), U+002C (,), U+002D (-), U+002E (.), U+002F (/),
  U+003A (:), U+003B (;), U+003D (=), U+003F (?), U+0040 (@), U+005F (_),
  U+007E (~)
- Code points in the range U+00A0 to U+10FFFD, inclusive,
  excluding surrogates and noncharacters.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ASCII URL code points beyond alphanumeric.
_URL_PUNCT = frozenset("!$&'()*+,-./:;=?@_~")

# Unicode noncharacters (per the Unicode Standard).
_NONCHARACTERS = frozenset(
    list(range(0xFDD0, 0xFDF0))
    + [
        p | 0xFFFE
        for p in range(0, 0x110000, 0x10000)
    ]
    + [
        p | 0xFFFF
        for p in range(0, 0x110000, 0x10000)
    ]
)


def is_url_code_point(c: str) -> bool:
    """Return True if *c* is a URL code point per WHATWG URL Standard."""
    if c.isascii():
        return c.isalnum() or c in _URL_PUNCT
    cp = ord(c)
    if cp < 0x00A0:
        return False
    # Surrogates (0xD800–0xDFFF) cannot appear in Python str, so no check
    # needed.  Noncharacters must be excluded.
    if cp in _NONCHARACTERS:
        return False
    return cp <= 0x10FFFD


class URLParseError(Exception):
    """Raised when a URL contains characters that are not URL code points."""

    def __init__(self, url: str, position: int, char: str) -> None:
        self.url = url
        self.position = position
        self.char = char
        super().__init__(
            f"Parse error at position {position}: "
            f"U+{ord(char):04X} ({char!r}) is not a URL code point and not '%'"
        )


def validate_url_code_points(url: str) -> list[URLParseError]:
    """Check *url* for characters that are not URL code points and not '%'.

    Returns a list of parse errors (one per offending character).  An empty
    list means the URL contains only valid URL code points (and '%').

    Per the WHATWG URL Standard: "If c is not a URL code point and not '%',
    parse error."
    """
    errors: list[URLParseError] = []
    for i, c in enumerate(url):
        if c == "%":
            continue
        if not is_url_code_point(c):
            err = URLParseError(url, i, c)
            errors.append(err)
            logger.debug("URL validation: %s", err)
    return errors

"""Accept header parsing and content-negotiation matching.

Supported Accept grammar (case-insensitive, no media parameters)::

    Accept        = accept-item *( "," accept-item )
    accept-item   = media-range [ ";" "q" "=" qvalue ]
    media-range   = type "/" subtype | type "/*" | "*/*"
    qvalue        = 0..1 with at most three decimal places (defaults to 1)

Anything else (media parameters such as ``text/html;level=1``, malformed
ranges, bad qvalues, empty list items, ...) is rejected with
:class:`AcceptSyntaxError`, which the API layer surfaces as HTTP 400.

Matching rules:

* a candidate (always a concrete ``type/subtype``) takes the q of the most
  specific range that matches it (``type/subtype`` > ``type/*`` > ``*/*``);
* ties in specificity are won by the earliest item in the header;
* a matched q of 0 excludes the candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# RFC 7230 token characters.
_TOKEN_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

# RFC 7231 qvalue: ("0" ["." 0*3DIGIT]) / ("1" ["." 0*3"0"]).
_QVALUE_RE = re.compile(r"^(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)$")


class AcceptSyntaxError(ValueError):
    """The Accept header does not follow the supported grammar."""


class CandidateMediaTypeError(ValueError):
    """A candidate media type is not a concrete ``type/subtype``."""


@dataclass(frozen=True)
class AcceptRange:
    """One parsed Accept item."""

    type: str
    subtype: str
    q: float
    specificity: int  # 2 = type/subtype, 1 = type/*, 0 = */*
    position: int  # 0-based position in the header

    @property
    def range(self) -> str:
        return f"{self.type}/{self.subtype}"

    def matches(self, type_: str, subtype: str) -> bool:
        return (self.type == "*" or self.type == type_) and (
            self.subtype == "*" or self.subtype == subtype
        )


def parse_accept(header: str) -> list[AcceptRange]:
    """Parse an Accept header value into an ordered list of ranges."""
    if not isinstance(header, str) or not header.strip():
        raise AcceptSyntaxError("Accept header must be a non-empty string")

    ranges: list[AcceptRange] = []
    for position, raw_item in enumerate(header.split(",")):
        item = raw_item.strip()
        if not item:
            raise AcceptSyntaxError(
                f"empty list item at position {position} in Accept header"
            )
        ranges.append(_parse_item(item, position))
    return ranges


def _parse_item(item: str, position: int) -> AcceptRange:
    media_range, *params = item.split(";")
    type_, subtype = _split_media_range(media_range.strip(), position)

    q = 1.0
    q_seen = False
    for raw_param in params:
        param = raw_param.strip()
        if not param:
            raise AcceptSyntaxError(
                f"empty parameter in Accept item {position} ({item!r})"
            )
        name, sep, value = param.partition("=")
        if not sep:
            raise AcceptSyntaxError(
                f"parameter {param!r} in Accept item {position} is not name=value"
            )
        name = name.strip().lower()
        value = value.strip()
        if name != "q":
            raise AcceptSyntaxError(
                f"unsupported parameter {name!r} in Accept item {position}: "
                "media parameters are not supported, only 'q' is allowed"
            )
        if q_seen:
            raise AcceptSyntaxError(
                f"duplicate q parameter in Accept item {position}"
            )
        q_seen = True
        if not _QVALUE_RE.fullmatch(value):
            raise AcceptSyntaxError(
                f"invalid q value {value!r} in Accept item {position}: "
                "expected a number between 0 and 1 with at most 3 decimals"
            )
        q = float(value)

    if type_ == "*":
        specificity = 0
    elif subtype == "*":
        specificity = 1
    else:
        specificity = 2
    return AcceptRange(type_, subtype, q, specificity, position)


def _split_media_range(text: str, position: int) -> tuple[str, str]:
    type_, sep, subtype = text.partition("/")
    type_ = type_.strip().lower()
    subtype = subtype.strip().lower()
    if not sep or not type_ or not subtype:
        raise AcceptSyntaxError(
            f"invalid media range {text!r} in Accept item {position}: "
            "expected type/subtype, type/* or */*"
        )
    for label, part in (("type", type_), ("subtype", subtype)):
        if part != "*" and not _TOKEN_RE.fullmatch(part):
            raise AcceptSyntaxError(
                f"invalid {label} {part!r} in Accept item {position}"
            )
    if type_ == "*" and subtype != "*":
        raise AcceptSyntaxError(
            f"invalid media range {text!r} in Accept item {position}: "
            "a wildcard type requires a wildcard subtype"
        )
    return type_, subtype


def parse_concrete_media_type(value: str) -> tuple[str, str]:
    """Validate a candidate media type; it must be a concrete type/subtype."""
    text = value.strip()
    if ";" in text:
        raise CandidateMediaTypeError(
            f"media type {value!r} must not carry parameters; "
            "expected a concrete type/subtype"
        )
    type_, sep, subtype = text.partition("/")
    type_ = type_.strip().lower()
    subtype = subtype.strip().lower()
    if not sep or not type_ or not subtype:
        raise CandidateMediaTypeError(
            f"media type {value!r} is not a valid type/subtype"
        )
    if type_ == "*" or subtype == "*":
        raise CandidateMediaTypeError(
            f"media type {value!r} must be concrete; wildcards are not allowed"
        )
    for label, part in (("type", type_), ("subtype", subtype)):
        if not _TOKEN_RE.fullmatch(part):
            raise CandidateMediaTypeError(
                f"invalid {label} {part!r} in media type {value!r}"
            )
    return type_, subtype


def best_match(
    ranges: list[AcceptRange], type_: str, subtype: str
) -> AcceptRange | None:
    """Return the most specific matching range (earliest on ties), or None."""
    best: AcceptRange | None = None
    for candidate in ranges:  # header order: strictly-more-specific replaces
        if candidate.matches(type_, subtype) and (
            best is None or candidate.specificity > best.specificity
        ):
            best = candidate
    return best

#!/usr/bin/env python3
"""Shared privacy policy for the tree viewer and report dashboard.

Two identical copies of this module ship with gedcom-tree and gedcom-report (kept
byte-identical like gedcom.py) so each skill installs standalone. Pure stdlib.

Three modes:

- ``none``    — full local output; nothing is removed (default).
- ``private`` — an *identified* family view: names, year-level dates and the
  family graph stay, but sensitive details of possibly-living people (exact
  dates, places, occupations, contacts, notes, sources, events, documents,
  links, residences) and family-event dates involving them are removed. The
  file is **not** anonymous.
- ``share``   — a *fail-closed* historical export: possibly-living and
  unknown-status people are **omitted entirely** before the payload is built,
  along with every reference to them; only deceased/presumed-deceased people
  remain, with a minimal field set.

Redaction happens in Python before serialization; the builders that know each
payload's shape do the actual field removal. This module provides the
classification, the mode context, and a payload audit that both tools run before
writing HTML (share mode aborts if any protected data leaked through).

The living-person heuristic is deliberately conservative — it prefers to protect
a deceased person by mistake over exposing a living one.
"""

import datetime
import re

HEURISTIC_VERSION = "living-v2"
LIVING_AGE_LIMIT = 110       # born within this many years -> treat as maybe-living
RECENT_MARRIAGE_LIMIT = 95   # own marriage within this many years -> maybe-living
RECENT_CHILD_LIMIT = 80      # child born within this many years -> maybe-living

# Classifications. Protected = must be hidden (private) / omitted (share).
DECEASED = "deceased"
PRESUMED_DECEASED = "presumed_deceased"
LIKELY_LIVING = "likely_living"
UNKNOWN = "unknown"
PROTECTED_RESTRICTION = "protected_restriction"

_PROTECTED = {LIKELY_LIVING, UNKNOWN, PROTECTED_RESTRICTION}

_YEAR_RE = re.compile(r"\b(\d{3,4})\b")
_RESN_RE = re.compile(r"privacy|confidential|locked", re.IGNORECASE)


def _year(value):
    """Latest plausible year in a date value, or None.

    Uses the *latest* year of a range (``BET 1900 AND 1960`` -> 1960) so that a
    person who may have been born recently is classified as possibly living —
    the conservative direction for every caller (birth, marriage, child birth).
    """
    if not value:
        return None
    v = value.strip().upper()
    if "@#" in v:                   # non-Gregorian calendar — don't guess
        return None
    years = [int(y) for y in _YEAR_RE.findall(v)]
    return max(years) if years else None


def _has_substance(node):
    """True when an event node actually asserts something.

    A bare ``1 DEAT`` with no value and no sub-records is a placeholder some
    exporters emit; treating it as death evidence would be anti-conservative.
    """
    if node is None:
        return False
    return bool((node.value or "").strip() or node.children)


def _flag_yes(indi, tag):
    node = indi.child(tag)
    return node is not None and (node.value or "").strip().upper() in ("Y", "YES")


def classify_person(tree, indi, as_of_year):
    """Return (classification, reason) for one INDI, most conservative first."""
    # 1. Explicit restriction.
    resn = indi.child("RESN")
    if resn is not None and _RESN_RE.search(resn.value or ""):
        return PROTECTED_RESTRICTION, "RESN restriction"

    # 2. Explicit living evidence.
    if _flag_yes(indi, "LIVING") or _flag_yes(indi, "_LIVING"):
        return LIKELY_LIVING, "explicit LIVING flag"
    deat = indi.child("DEAT")
    if deat is not None and (deat.value or "").strip().upper() == "N":
        return LIKELY_LIVING, "DEAT N"

    # 3. Explicit death evidence: a DEAT that asserts something (a value such as
    #    Y, or any sub-record like DATE/PLAC), or a substantive BURI/CREM.
    #    A bare placeholder node with no value and no children is NOT evidence.
    if _has_substance(deat):
        return DECEASED, "DEAT present"
    if _has_substance(indi.child("BURI")) or _has_substance(indi.child("CREM")):
        return DECEASED, "burial/cremation"

    # 4. Birth/christening year.
    byear = None
    for tag in ("BIRT", "CHR", "BAPM"):
        byear = _year(indi.value_of(tag, "DATE"))
        if byear:
            break
    if byear is not None:
        if byear > as_of_year:
            return UNKNOWN, "future birth year"
        if byear >= as_of_year - LIVING_AGE_LIMIT:
            return LIKELY_LIVING, f"born {byear} (< {LIVING_AGE_LIMIT}y ago)"
        return PRESUMED_DECEASED, f"born {byear}"

    # 5. Recent indirect evidence when birth is absent.
    for fs in indi.children_by("FAMS"):
        fam = tree.families.get(tree.norm_id(fs.value)) if fs.value else None
        if not fam:
            continue
        my = _year(fam.value_of("MARR", "DATE"))
        if my is not None and my >= as_of_year - RECENT_MARRIAGE_LIMIT:
            return LIKELY_LIVING, f"married {my}"
        for ch in fam.children_by("CHIL"):
            child = tree.people.get(tree.norm_id(ch.value)) if ch.value else None
            if not child:
                continue
            cy = _year(child.value_of("BIRT", "DATE"))
            if cy is not None and cy >= as_of_year - RECENT_CHILD_LIMIT:
                return LIKELY_LIVING, f"child born {cy}"

    # 6. No usable evidence.
    return UNKNOWN, "no death or birth evidence"


def classify_people(tree, as_of_year=None):
    if as_of_year is None:
        as_of_year = datetime.date.today().year
    out = {}
    for xid, indi in tree.people.items():
        cls, reason = classify_person(tree, indi, as_of_year)
        out[xid] = {"class": cls, "reason": reason}
    return out


class PrivacyContext:
    """Holds the chosen mode and the per-person classification."""

    def __init__(self, tree, mode="none", as_of_year=None):
        if mode not in ("none", "private", "share"):
            raise ValueError(f"unknown privacy mode {mode!r}")
        self.mode = mode
        self.as_of_year = as_of_year or datetime.date.today().year
        self.assessments = (classify_people(tree, self.as_of_year)
                            if mode != "none" else {})
        self.redacted = {}
        self.omitted_people = 0
        self.omitted_families = 0

    def is_protected(self, xid):
        a = self.assessments.get(xid)
        return bool(a) and a["class"] in _PROTECTED

    def include_person(self, xid):
        """Share mode: only non-protected people are exported."""
        if self.mode != "share":
            return True
        return not self.is_protected(xid)

    def record(self, category, n=1):
        self.redacted[category] = self.redacted.get(category, 0) + n

    def class_counts(self):
        counts = {}
        for a in self.assessments.values():
            counts[a["class"]] = counts.get(a["class"], 0) + 1
        return counts

    def summary(self, payload_audit=None):
        return {
            "mode": self.mode,
            "heuristic": HEURISTIC_VERSION,
            "as_of_year": self.as_of_year,
            "classification": self.class_counts(),
            "omitted_people": self.omitted_people,
            "omitted_families": self.omitted_families,
            "redacted": dict(self.redacted),
            "payload_audit": payload_audit or {},
        }


# --------------------------------------------------------------------------- #
# Payload audit — run on the final sanitized payload before rendering.
# --------------------------------------------------------------------------- #

_ABS_PATH_RE = re.compile(r"(^|[\"'\s])(/[^\s\"']+|[A-Za-z]:\\[^\s\"']+)")
_URL_RE = re.compile(r"https?://|mailto:|file://", re.IGNORECASE)
_CONTACT_KEYS = ("phone", "email", "address")
_DOC_EXT_RE = re.compile(r"\.(png|jpe?g|pdf|tif?f|gif|md|txt)\b", re.IGNORECASE)


def _iter_strings(obj, key=None):
    """Yield (key, string) for every string in a nested structure.

    Dict keys are yielded too (with key=None), so an id used as a mapping key —
    e.g. ``people["@I9@"]`` — is still checked for protected-id leakage.
    """
    if isinstance(obj, str):
        yield key, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield None, k
            yield from _iter_strings(v, k)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v, key)


def audit_payload(payload, context, protected_names=None, protected_ids=None):
    """Count residual privacy risks in the finished payload (counts only).

    Never returns offending strings. For share mode, any nonzero forbidden count
    means the export must be aborted.
    """
    protected_names = protected_names or set()
    protected_ids = protected_ids or set()
    audit = {
        "protected_ids": 0,
        "protected_names": 0,
        "contacts": 0,
        "external_urls": 0,
        "absolute_paths": 0,
        "document_paths": 0,
    }
    for key, s in _iter_strings(payload):
        if not s:
            continue
        if key in _CONTACT_KEYS and s.strip():
            audit["contacts"] += 1
        if _URL_RE.search(s):
            audit["external_urls"] += 1
        if _ABS_PATH_RE.search(s):
            audit["absolute_paths"] += 1
        if _DOC_EXT_RE.search(s):
            audit["document_paths"] += 1
        for pid in protected_ids:
            if pid and pid in s:
                audit["protected_ids"] += 1
                break
        for pname in protected_names:
            if pname and pname in s:
                audit["protected_names"] += 1
                break
    return audit


# Forbidden categories that must be zero in a share-mode payload.
SHARE_FORBIDDEN = ("protected_ids", "protected_names", "contacts",
                   "external_urls", "absolute_paths", "document_paths")


def share_leak_total(payload_audit):
    return sum(payload_audit.get(k, 0) for k in SHARE_FORBIDDEN)

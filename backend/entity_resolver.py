"""
Garuda v3 — Entity Resolver (entity_resolver.py)

Multi-stage resolution pipeline that converts messy LLM-extracted names
("CM", "Bhajan Lal", "CM Sharma") into a single canonical form
("Bhajan Lal Sharma") BEFORE the entity ever touches AstraDB.

Stages (fastest to slowest, short-circuit on first hit)
─────────────────────────────────────────────────────────
  1. Exact alias lookup          — "CM" → "Bhajan Lal Sharma"
  2. Normalised exact lookup     — casefold + strip titles
  3. Token-subset match          — "Bhajan Lal" ⊂ "Bhajan Lal Sharma"
  4. Abbreviation expansion      — "JMC" → "Jaipur Municipal Corporation"
  5. Fuzzy string ratio          — difflib SequenceMatcher ≥ 0.82
  6. Falls through to vector     — upsert_entity handles it via AstraDB

Public API
──────────
  resolve_canonical(name, entity_type) → canonical_name (str)
  normalise_name(name)                 → stripped/cleaned name (str)
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
#  CANONICAL ENTITIES
#  Format: { canonical_name: { "type": ..., "aliases": [...], ... } }
#  All aliases are lower-cased at runtime for fast O(1) lookup.
# ─────────────────────────────────────────────────────────────────────────────

CANONICAL_ENTITIES: dict[str, dict] = {

    # ── People ─────────────────────────────────────────────────────────────

    "Bhajan Lal Sharma": {
        "type": "person",
        "role": "Chief Minister of Rajasthan",
        "party": "BJP",
        "aliases": [
            "cm", "cm sharma", "bhajan lal", "bhajanlal", "bhajanlal sharma",
            "chief minister sharma", "cm bhajan lal", "cm bhajanlal",
            "chief minister bhajan lal sharma", "chief minister bhajan lal",
            "mukhyamantri bhajanlal", "mukhyamantri bhajan lal sharma",
            "bhajan lal sharma ji", "cm ji", "rajasthan cm",
        ],
    },
    "Diya Kumari": {
        "type": "person",
        "role": "Deputy Chief Minister of Rajasthan",
        "party": "BJP",
        "aliases": [
            "dy cm diya kumari", "deputy cm diya kumari", "diya kumari ji",
            "princess diya kumari", "diya", "deputy cm", "dyc cm",
            "diya kumari singh",
        ],
    },
    "Premchand Bairwa": {
        "type": "person",
        "role": "Deputy Chief Minister of Rajasthan",
        "party": "BJP",
        "aliases": [
            "dy cm bairwa", "deputy cm bairwa", "bairwa",
            "prem chand bairwa", "premchand bairwa ji",
        ],
    },
    "Vasundhara Raje": {
        "type": "person",
        "role": "Former Chief Minister of Rajasthan",
        "party": "BJP",
        "aliases": [
            "vasundhara", "raje", "vasundhara raje scindia",
            "former cm vasundhara", "ex cm vasundhara",
            "vasundhara raje ji", "vasundhara ji",
        ],
    },
    "Ashok Gehlot": {
        "type": "person",
        "role": "Former Chief Minister of Rajasthan",
        "party": "Congress",
        "aliases": [
            "gehlot", "cm gehlot", "ex cm gehlot", "former cm gehlot",
            "ashok gehlot ji", "gehlot ji",
        ],
    },
    "Sachin Pilot": {
        "type": "person",
        "role": "Former Deputy Chief Minister of Rajasthan",
        "party": "Congress",
        "aliases": [
            "pilot", "sachin", "former dy cm pilot", "sachin pilot ji",
        ],
    },
    "Rajyavardhan Singh Rathore": {
        "type": "person",
        "role": "Cabinet Minister, Rajasthan",
        "party": "BJP",
        "aliases": [
            "rathore", "rajyavardhan", "rajyavardhan rathore",
            "rvs rathore", "colonel rathore",
        ],
    },
    "Kirodi Lal Meena": {
        "type": "person",
        "role": "Cabinet Minister, Rajasthan",
        "party": "BJP",
        "aliases": [
            "kirodi", "kirori lal", "kirodi lal", "kirodi meena",
            "kirori lal meena",
        ],
    },
    "CP Joshi": {
        "type": "person",
        "role": "Speaker, Rajasthan Legislative Assembly",
        "party": "BJP",
        "aliases": [
            "speaker joshi", "c p joshi", "speaker cp joshi",
            "assembly speaker joshi",
        ],
    },
    "Govind Singh Dotasra": {
        "type": "person",
        "role": "President, Rajasthan Pradesh Congress Committee",
        "party": "Congress",
        "aliases": [
            "dotasra", "govind dotasra", "rpcc president dotasra",
        ],
    },

    # ── Organizations ──────────────────────────────────────────────────────

    "Bharatiya Janata Party": {
        "type": "organization",
        "aliases": [
            "bjp", "b.j.p", "b.j.p.", "bhartiya janata party",
            "bjp rajasthan", "rajasthan bjp", "ruling party",
        ],
    },
    "Indian National Congress": {
        "type": "organization",
        "aliases": [
            "congress", "inc", "i.n.c", "indian congress",
            "rajasthan congress", "rpcc", "rajasthan pradesh congress committee",
            "congress party", "opposition congress",
        ],
    },
    "Aam Aadmi Party": {
        "type": "organization",
        "aliases": ["aap", "aam aadmi party rajasthan", "a.a.p"],
    },
    "Jaipur Development Authority": {
        "type": "organization",
        "aliases": [
            "jda", "j.d.a", "jaipur vikas pradhikaran",
            "jda jaipur", "jaipur development authority jda",
        ],
    },
    "Jaipur Municipal Corporation": {
        "type": "organization",
        "aliases": [
            "jmc", "j.m.c", "jaipur nagar nigam", "nagar nigam jaipur",
            "jmc greater", "jmc heritage", "greater nagar nigam",
            "heritage nagar nigam", "jaipur mc",
        ],
    },
    "Jaipur Metro Rail Corporation": {
        "type": "organization",
        "aliases": [
            "jmrc", "jaipur metro", "metro jaipur",
            "jaipur metro rail", "j.m.r.c",
        ],
    },
    "Rajasthan Police": {
        "type": "organization",
        "aliases": [
            "police", "jaipur police", "rajasthan police department",
            "crime branch", "crime branch jaipur",
        ],
    },
    "Public Health Engineering Department": {
        "type": "organization",
        "aliases": [
            "phed", "p.h.e.d", "jaldaay vibhag", "jal vibhag",
            "public health engineering", "water department rajasthan",
        ],
    },
    "Jaipur Vidyut Vitaran Nigam Limited": {
        "type": "organization",
        "aliases": [
            "jvvnl", "jaipur discom", "jaipur electricity",
            "bijli vibhag jaipur", "electricity department jaipur",
            "jaipur power distribution",
        ],
    },
    "National Highways Authority of India": {
        "type": "organization",
        "aliases": ["nhai", "n.h.a.i", "national highway authority"],
    },
    "Sawai Man Singh Hospital": {
        "type": "organization",
        "aliases": [
            "sms hospital", "sms", "s.m.s. hospital",
            "sawai mansingh hospital", "sms medical college", "sms college",
            "sawai mansingh medical college",
        ],
    },
    "All India Institute of Medical Sciences Jodhpur": {
        "type": "organization",
        "aliases": ["aiims jodhpur", "aiims", "a.i.i.m.s"],
    },
    "Rajasthan High Court": {
        "type": "organization",
        "aliases": [
            "high court", "hc", "rajasthan hc", "jodhpur high court",
            "rajasthan high court jodhpur",
        ],
    },
    "Enforcement Directorate": {
        "type": "organization",
        "aliases": ["ed", "e.d.", "enforcement directorate india"],
    },
    "Central Bureau of Investigation": {
        "type": "organization",
        "aliases": ["cbi", "c.b.i", "central bureau"],
    },
    "Anti-Corruption Bureau Rajasthan": {
        "type": "organization",
        "aliases": ["acb", "a.c.b", "acb rajasthan", "anti corruption bureau"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
#  PRE-COMPUTED ALIAS → CANONICAL MAP
# ─────────────────────────────────────────────────────────────────────────────

_ALIAS_MAP: dict[str, str] = {}

def _build_alias_map() -> None:
    for canonical, meta in CANONICAL_ENTITIES.items():
        _ALIAS_MAP[canonical.lower()] = canonical
        for alias in meta.get("aliases", []):
            _ALIAS_MAP[alias.lower()] = canonical

_build_alias_map()


# ─────────────────────────────────────────────────────────────────────────────
#  TITLE / HONORIFIC STRIPPING
# ─────────────────────────────────────────────────────────────────────────────

_TITLE_PREFIXES = re.compile(
    r"^\s*(shri|smt|dr|mr|mrs|ms|col|maj|gen|lt|prof|adv|er|"
    r"hon|honourable|honorable|श्री|श्रीमती)\s+",
    re.IGNORECASE,
)

_TITLE_SUFFIXES = re.compile(
    r"\s+(ji|sahab|sahib|sir)\s*$",
    re.IGNORECASE,
)

_ROLE_PREFIXES = re.compile(
    r"^\s*(chief minister|cm|deputy chief minister|deputy cm|dy cm|"
    r"minister|mla|mp|speaker|mayor|councillor|inspector|sp|dsp|sho|"
    r"collector|commissioner|director|secretary|former|ex-|ex )\s+",
    re.IGNORECASE,
)

def _strip_titles(name: str) -> str:
    """Remove common titles/honorifics/role prefixes from a name."""
    for pattern in (_TITLE_PREFIXES, _TITLE_SUFFIXES, _TITLE_PREFIXES):
        name = pattern.sub("", name).strip()
    return name


def normalise_name(name: str) -> str:
    """
    Canonical normalisation:
      - Unicode → ASCII where possible (Bhājanlāl → Bhajanlal)
      - Collapse whitespace
      - Strip common titles
      - Title case
    """
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"\s+", " ", name).strip()
    name = _strip_titles(name)
    return name.title()


# ─────────────────────────────────────────────────────────────────────────────
#  FUZZY HELPERS  (no external deps — pure difflib)
# ─────────────────────────────────────────────────────────────────────────────

def _token_set_ratio(a: str, b: str) -> float:
    """
    Like fuzzywuzzy's token_set_ratio but with difflib.
    Returns 0.0–1.0.
    """
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    intersection = ta & tb
    if not intersection:
        return 0.0
    # sorted intersection vs each full string
    common = " ".join(sorted(intersection))
    sorted_a = " ".join(sorted(ta))
    sorted_b = " ".join(sorted(tb))
    scores = [
        difflib.SequenceMatcher(None, common, sorted_a).ratio(),
        difflib.SequenceMatcher(None, common, sorted_b).ratio(),
        difflib.SequenceMatcher(None, sorted_a, sorted_b).ratio(),
    ]
    return max(scores)


def _token_subset_score(a: str, b: str) -> float:
    """
    Returns > 0 if every token in the shorter string appears in the longer.
    Score = len(shorter) / len(longer)  — penalises very short matches.
    """
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if len(ta) < 2 or len(tb) < 2:
        return 0.0   # single-token names are too ambiguous for this check
    if ta <= tb:
        return len(ta) / len(tb)
    if tb <= ta:
        return len(tb) / len(ta)
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN RESOLUTION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

# Fuzzy threshold — tune this if you see false merges
_FUZZY_THRESHOLD = 0.82
# Token-subset threshold — "Bhajan Lal" ⊂ "Bhajan Lal Sharma" → 0.67
# We accept if ≥ 0.60 AND it's a person entity
_SUBSET_THRESHOLD_PERSON = 0.60
_SUBSET_THRESHOLD_ORG    = 0.70


def resolve_canonical(name: str, entity_type: str) -> str:
    """
    Resolve a raw extracted name to its canonical form.
    Returns the canonical name if matched, otherwise the cleaned input.

    This is the single entry-point called by upsert_entity().
    """
    if not name or not name.strip():
        return name

    raw      = name.strip()
    key      = raw.lower()

    # ── Stage 1: Exact alias lookup ────────────────────────────────────────
    if key in _ALIAS_MAP:
        canonical = _ALIAS_MAP[key]
        if _type_matches(canonical, entity_type):
            return canonical

    # ── Stage 2: Normalised exact lookup ──────────────────────────────────
    norm     = normalise_name(raw)
    norm_key = norm.lower()
    if norm_key in _ALIAS_MAP:
        canonical = _ALIAS_MAP[norm_key]
        if _type_matches(canonical, entity_type):
            return canonical

    # ── Stage 3: Strip role prefix then re-check ──────────────────────────
    stripped     = _ROLE_PREFIXES.sub("", norm).strip()
    stripped_key = stripped.lower()
    if stripped_key and stripped_key != norm_key:
        if stripped_key in _ALIAS_MAP:
            canonical = _ALIAS_MAP[stripped_key]
            if _type_matches(canonical, entity_type):
                return canonical

    # ── Stage 4 & 5: Fuzzy match against canonical names only ─────────────
    best_canonical: Optional[str] = None
    best_score = 0.0

    candidates = [
        c for c, m in CANONICAL_ENTITIES.items()
        if m.get("type", "").startswith(entity_type[:3])  # loose type filter
    ]

    search_name = stripped or norm_key

    for canonical in candidates:
        # Token-subset check (catches "Bhajan Lal" ⊂ "Bhajan Lal Sharma")
        subset = _token_subset_score(search_name, canonical.lower())
        threshold = (
            _SUBSET_THRESHOLD_PERSON if entity_type == "person"
            else _SUBSET_THRESHOLD_ORG
        )
        if subset >= threshold:
            if subset > best_score:
                best_score = subset
                best_canonical = canonical

        # Full fuzzy ratio (catches "Bhajanlal" vs "Bhajan Lal Sharma")
        ratio = _token_set_ratio(search_name, canonical.lower())
        if ratio >= _FUZZY_THRESHOLD and ratio > best_score:
            best_score = ratio
            best_canonical = canonical

    if best_canonical:
        return best_canonical

    # ── Stage 6: Return cleaned name (vector search handles the rest) ──────
    return norm if norm else raw


def _type_matches(canonical: str, entity_type: str) -> bool:
    """Check the canonical entity's declared type loosely matches the query."""
    meta = CANONICAL_ENTITIES.get(canonical, {})
    canon_type = meta.get("type", "")
    # person / politician / officer all start with "p" → loose match
    return (
        not canon_type
        or canon_type.startswith(entity_type[:3])
        or entity_type.startswith(canon_type[:3])
    )


def get_canonical_meta(canonical_name: str) -> dict:
    """Return role/party metadata for a known canonical entity."""
    return CANONICAL_ENTITIES.get(canonical_name, {})


# ─────────────────────────────────────────────────────────────────────────────
#  BATCH NORMALISE  (used by merge script)
# ─────────────────────────────────────────────────────────────────────────────

def batch_resolve(
    names: list[tuple[str, str]]  # [(name, entity_type), ...]
) -> list[tuple[str, str]]:       # [(original, canonical), ...]
    """Resolve a list of (name, type) pairs. Useful for the merge script."""
    return [(name, resolve_canonical(name, etype)) for name, etype in names]

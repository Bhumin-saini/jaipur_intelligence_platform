"""
Garuda v3 — Ontology Layer (ontology.py)

Defines the entity type hierarchy, relationship taxonomy, and typed
inference rules used by the knowledge graph.

Entity types form a hierarchy: BASE_TYPE → SUBTYPE
Relationship types are directional: SUBJECT → REL → OBJECT
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

# ── Entity Ontology ───────────────────────────────────────────────────────────

ENTITY_TYPES: dict[str, dict] = {
    # Persons
    "person": {
        "label": "Person",
        "color": "#60a5fa",      # blue-400
        "subtypes": ["politician", "officer", "journalist", "criminal", "official", "activist"],
        "icon": "👤",
    },
    "politician": {
        "label": "Politician",
        "parent": "person",
        "color": "#f59e0b",
        "icon": "🏛️",
    },
    "officer": {
        "label": "Law Enforcement Officer",
        "parent": "person",
        "color": "#3b82f6",
        "icon": "👮",
    },
    "official": {
        "label": "Government Official",
        "parent": "person",
        "color": "#8b5cf6",
        "icon": "🏢",
    },

    # Organizations
    "organization": {
        "label": "Organization",
        "color": "#34d399",      # green-400
        "subtypes": ["government_agency", "political_party", "ngo", "company", "police", "court", "hospital"],
        "icon": "🏢",
    },
    "government_agency": {
        "label": "Government Agency",
        "parent": "organization",
        "color": "#6ee7b7",
        "icon": "🏛️",
    },
    "political_party": {
        "label": "Political Party",
        "parent": "organization",
        "color": "#fbbf24",
        "icon": "🚩",
    },
    "police": {
        "label": "Police / Law Enforcement",
        "parent": "organization",
        "color": "#60a5fa",
        "icon": "👮",
    },
    "company": {
        "label": "Company / Business",
        "parent": "organization",
        "color": "#34d399",
        "icon": "🏗️",
    },
    "hospital": {
        "label": "Hospital / Healthcare",
        "parent": "organization",
        "color": "#f87171",
        "icon": "🏥",
    },

    # Locations
    "location": {
        "label": "Location",
        "color": "#f97316",      # orange-400
        "subtypes": ["neighborhood", "landmark", "road", "institution", "district"],
        "icon": "📍",
    },
    "neighborhood": {
        "label": "Neighborhood / Area",
        "parent": "location",
        "color": "#fb923c",
        "icon": "🏘️",
    },
    "road": {
        "label": "Road / Route",
        "parent": "location",
        "color": "#fbbf24",
        "icon": "🛣️",
    },
    "landmark": {
        "label": "Landmark / Building",
        "parent": "location",
        "color": "#f97316",
        "icon": "🏛️",
    },
    "district": {
        "label": "District / Zone",
        "parent": "location",
        "color": "#ea580c",
        "icon": "🗺️",
    },

    # Infrastructure
    "infrastructure": {
        "label": "Infrastructure",
        "color": "#a78bfa",      # violet-400
        "subtypes": ["road_project", "utility", "metro", "building"],
        "icon": "🔧",
    },
}

# ── Relationship Taxonomy ─────────────────────────────────────────────────────

RELATIONSHIP_TYPES: dict[str, dict] = {
    # Person ↔ Organization
    "works_for": {
        "label": "Works For",
        "subject_types": ["person"],
        "object_types": ["organization"],
        "inverse": "employs",
        "weight": 1.0,
    },
    "employs": {
        "label": "Employs",
        "subject_types": ["organization"],
        "object_types": ["person"],
        "inverse": "works_for",
        "weight": 1.0,
    },
    "leads": {
        "label": "Leads",
        "subject_types": ["person"],
        "object_types": ["organization"],
        "inverse": "led_by",
        "weight": 1.5,
    },
    "arrested": {
        "label": "Arrested",
        "subject_types": ["police", "organization"],
        "object_types": ["person"],
        "inverse": "arrested_by",
        "weight": 2.0,
    },

    # Person / Org ↔ Location
    "located_in": {
        "label": "Located In",
        "subject_types": ["organization", "infrastructure"],
        "object_types": ["location"],
        "inverse": "contains",
        "weight": 0.8,
    },
    "operates_in": {
        "label": "Operates In",
        "subject_types": ["organization", "person"],
        "object_types": ["location"],
        "weight": 0.9,
    },

    # Event relationships
    "involved_in": {
        "label": "Involved In",
        "subject_types": ["person", "organization"],
        "object_types": ["event"],
        "weight": 1.0,
    },
    "caused_by": {
        "label": "Caused By",
        "subject_types": ["event"],
        "object_types": ["person", "organization", "event"],
        "weight": 1.5,
    },
    "preceded_by": {
        "label": "Preceded By",
        "subject_types": ["event"],
        "object_types": ["event"],
        "inverse": "followed_by",
        "weight": 1.2,
    },
    "part_of": {
        "label": "Part Of",
        "subject_types": ["event"],
        "object_types": ["event"],
        "inverse": "contains_event",
        "weight": 1.3,
    },

    # Generic
    "associated_with": {
        "label": "Associated With",
        "subject_types": ["*"],
        "object_types": ["*"],
        "weight": 0.5,
    },
    "co_occurred_with": {
        "label": "Co-occurred With",
        "subject_types": ["*"],
        "object_types": ["*"],
        "weight": 0.6,
    },
}

# ── Event Type Ontology ───────────────────────────────────────────────────────

EVENT_TYPE_META: dict[str, dict] = {
    "crime": {
        "label": "Crime",
        "color": "#ef4444",
        "icon": "🔴",
        "likely_entities": ["police", "person", "location"],
        "typical_followups": ["police_action", "court_proceeding"],
    },
    "politics": {
        "label": "Politics",
        "color": "#f59e0b",
        "icon": "🏛️",
        "likely_entities": ["politician", "political_party", "government_agency"],
        "typical_followups": ["policy_change", "election"],
    },
    "accident": {
        "label": "Accident",
        "color": "#f97316",
        "icon": "⚠️",
        "likely_entities": ["hospital", "police", "road"],
        "typical_followups": ["investigation", "infrastructure_review"],
    },
    "infrastructure": {
        "label": "Infrastructure",
        "color": "#8b5cf6",
        "icon": "🔧",
        "likely_entities": ["government_agency", "company", "location"],
        "typical_followups": ["completion", "delay", "protest"],
    },
    "cultural": {
        "label": "Cultural",
        "color": "#ec4899",
        "icon": "🎭",
        "likely_entities": ["location", "organization"],
        "typical_followups": [],
    },
    "weather": {
        "label": "Weather",
        "color": "#06b6d4",
        "icon": "🌦️",
        "likely_entities": ["location"],
        "typical_followups": ["flooding", "infrastructure_damage"],
    },
    "business": {
        "label": "Business",
        "color": "#10b981",
        "icon": "💼",
        "likely_entities": ["company", "government_agency"],
        "typical_followups": ["investment", "employment_change"],
    },
    "health": {
        "label": "Health",
        "color": "#f87171",
        "icon": "🏥",
        "likely_entities": ["hospital", "government_agency"],
        "typical_followups": ["policy_response", "outbreak"],
    },
    "other": {
        "label": "Other",
        "color": "#6b7280",
        "icon": "📋",
        "likely_entities": [],
        "typical_followups": [],
    },
}

# ── Inference Rules ───────────────────────────────────────────────────────────

INFERENCE_RULES: list[dict] = [
    # If A leads org B, and org B is in event E → A is involved_in E
    {
        "name": "leader_inherits_org_events",
        "pattern": [
            {"subject": "?person", "rel": "leads", "object": "?org"},
            {"subject": "?org", "rel": "involved_in", "object": "?event"},
        ],
        "infer": {"subject": "?person", "rel": "involved_in", "object": "?event"},
        "confidence": 0.7,
    },
    # If person A and person B both work_for org C → A associated_with B
    {
        "name": "colleagues_associated",
        "pattern": [
            {"subject": "?personA", "rel": "works_for", "object": "?org"},
            {"subject": "?personB", "rel": "works_for", "object": "?org"},
        ],
        "infer": {"subject": "?personA", "rel": "associated_with", "object": "?personB"},
        "confidence": 0.5,
    },
]


# ── Helper Functions ──────────────────────────────────────────────────────────

def classify_entity(name: str, raw_type: str) -> str:
    """
    Refine a raw entity type (location/organization/person) into a
    more specific ontology subtype using heuristic keyword matching.
    """
    name_lower = name.lower()

    if raw_type == "person":
        if any(k in name_lower for k in ["inspector", "si ", "officer", "cop", "ips", "ias", "sp ", "dsp", "sho"]):
            return "officer"
        if any(k in name_lower for k in ["minister", "cm ", "mp ", "mla", "mayor", "councillor"]):
            return "politician"
        if any(k in name_lower for k in ["collector", "commissioner", "secretary", "director"]):
            return "official"
        return "person"

    if raw_type == "organization":
        if any(k in name_lower for k in ["police", "thana", "thane", "crime branch", "soc", "cid"]):
            return "police"
        if any(k in name_lower for k in ["bjp", "congress", "aap", "bsp", "rcp", "party"]):
            return "political_party"
        if any(k in name_lower for k in ["jda", "nhm", "jvvnl", "phed", "mc jaipur", "municipality",
                                          "nhai", "jaipur metro", "discom", "rajasthan"]):
            return "government_agency"
        if any(k in name_lower for k in ["hospital", "clinic", "medical", "health centre"]):
            return "hospital"
        if any(k in name_lower for k in ["company", "pvt", "ltd", "llp", "corp", "enterprise"]):
            return "company"
        return "organization"

    if raw_type == "location":
        if any(k in name_lower for k in ["road", "highway", "ring road", "bypass", "nager", "marg", "path"]):
            return "road"
        if any(k in name_lower for k in ["nagar", "colony", "vihar", "ward", "mohalla", "bagh", "park"]):
            return "neighborhood"
        if any(k in name_lower for k in ["fort", "palace", "temple", "mandir", "gate", "museum"]):
            return "landmark"
        if any(k in name_lower for k in ["district", "zone", "sector", "division", "taluka"]):
            return "district"
        return "location"

    return raw_type


def get_entity_meta(entity_type: str) -> dict:
    """Return display metadata for an entity type."""
    return ENTITY_TYPES.get(entity_type, ENTITY_TYPES.get("organization", {}))


def get_event_meta(event_type: str) -> dict:
    """Return display metadata for an event type."""
    return EVENT_TYPE_META.get(event_type, EVENT_TYPE_META["other"])


def get_relationship_meta(rel_type: str) -> dict:
    """Return metadata for a relationship type."""
    return RELATIONSHIP_TYPES.get(rel_type, RELATIONSHIP_TYPES["associated_with"])

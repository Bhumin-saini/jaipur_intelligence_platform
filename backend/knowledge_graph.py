"""
Garuda v3 — Knowledge Graph Layer (knowledge_graph.py)

Builds and queries a persistent knowledge graph stored in AstraDB:
  - Entity nodes  (graph_nodes collection)
  - Typed relationship edges (graph_edges collection)
  - Event-to-event links (event_links collection)
  - Community detection  (simple label propagation)
  - GraphRAG context building for LLM queries

Public API:
  upsert_node()            → str
  upsert_edge()            → str
  get_subgraph()           → dict
  link_events()            → list[dict]
  get_event_chain()        → list[dict]
  detect_communities()     → list[dict]
  build_graphrag_context() → str
  graph_stats()            → dict
"""

from __future__ import annotations
import json
import logging
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Collection accessors ──────────────────────────────────────────────────────

def _nodes():
    from astra_client import graph_nodes
    return graph_nodes()

def _edges():
    from astra_client import graph_edges
    return graph_edges()

def _event_links():
    from astra_client import event_links
    return event_links()


# ── Node (Entity) Operations ──────────────────────────────────────────────────

def upsert_node(
    entity_id: str,
    name: str,
    entity_type: str,
    raw_type: str,
    properties: dict | None = None,
) -> str:
    """
    Create or update a graph node for an entity.
    Applies ontology classification to refine entity_type.
    Returns node _id (same as entity_id).
    """
    from ontology import classify_entity, get_entity_meta

    refined_type = classify_entity(name, raw_type)
    meta = get_entity_meta(refined_type)

    node = {
        "_id":          entity_id,
        "name":         name,
        "type":         refined_type,
        "raw_type":     raw_type,
        "label":        meta.get("label", refined_type),
        "color":        meta.get("color", "#6b7280"),
        "icon":         meta.get("icon", "📌"),
        "properties":   properties or {},
        "mention_count": 0,
        "updated_at":   _utc_now(),
    }

    try:
        existing = _nodes().find_one({"_id": entity_id})
        if existing:
            _nodes().update_one(
                {"_id": entity_id},
                {"$set": {
                    "name":       name,
                    "type":       refined_type,
                    "label":      meta.get("label", refined_type),
                    "color":      meta.get("color", "#6b7280"),
                    "icon":       meta.get("icon", "📌"),
                    "updated_at": _utc_now(),
                }, "$inc": {"mention_count": 1}},
            )
        else:
            node["mention_count"] = 1
            node["created_at"] = _utc_now()
            _nodes().insert_one(node)
    except Exception as exc:
        logger.error("upsert_node error (%s): %s", entity_id, exc)

    return entity_id


def get_node(entity_id: str) -> dict | None:
    try:
        return _nodes().find_one({"_id": entity_id})
    except Exception as exc:
        logger.error("get_node error: %s", exc)
        return None


def list_nodes(
    node_type: str | None = None,
    limit: int = 100,
    min_mentions: int = 1,
) -> list[dict]:
    filt: dict = {}
    if node_type:
        filt["type"] = node_type
    if min_mentions > 1:
        filt["mention_count"] = {"$gte": min_mentions}
    try:
        return list(_nodes().find(filt, sort={"mention_count": -1}, limit=limit))
    except Exception as exc:
        logger.error("list_nodes error: %s", exc)
        return []


# ── Edge (Relationship) Operations ────────────────────────────────────────────

def upsert_edge(
    source_id: str,
    target_id: str,
    rel_type: str,
    weight: float = 1.0,
    evidence: list[str] | None = None,
    inferred: bool = False,
    confidence: float = 1.0,
    properties: dict | None = None,
) -> str:
    """
    Create or strengthen a relationship edge between two nodes.
    If an edge of the same type already exists, increments weight and
    appends evidence (up to 20 items).
    Returns the edge _id.
    """
    edge_id = f"{source_id}__{rel_type}__{target_id}"
    try:
        existing = _edges().find_one({"_id": edge_id})
        if existing:
            current_evidence = existing.get("evidence", [])
            if evidence:
                current_evidence = list(set(current_evidence + evidence))[:20]
            _edges().update_one(
                {"_id": edge_id},
                {"$set": {
                    "weight":     min(existing.get("weight", weight) + 0.5, 10.0),
                    "evidence":   current_evidence,
                    "updated_at": _utc_now(),
                }},
            )
        else:
            _edges().insert_one({
                "_id":        edge_id,
                "source_id":  source_id,
                "target_id":  target_id,
                "rel_type":   rel_type,
                "weight":     weight,
                "evidence":   evidence or [],
                "inferred":   inferred,
                "confidence": confidence,
                "properties": properties or {},
                "created_at": _utc_now(),
                "updated_at": _utc_now(),
            })
    except Exception as exc:
        logger.error("upsert_edge error: %s", exc)
    return edge_id


def get_edges(
    node_id: str,
    direction: str = "both",
    rel_types: list[str] | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Retrieve edges for a node.
    direction: 'out' | 'in' | 'both'
    """
    try:
        filt: dict = {}
        if rel_types:
            filt["rel_type"] = {"$in": rel_types}

        if direction == "out":
            filt["source_id"] = node_id
        elif direction == "in":
            filt["target_id"] = node_id
        else:
            # Both directions — fetch separately
            out_edges = list(_edges().find({**filt, "source_id": node_id}, limit=limit // 2))
            in_edges  = list(_edges().find({**filt, "target_id": node_id}, limit=limit // 2))
            return out_edges + in_edges

        return list(_edges().find(filt, limit=limit))
    except Exception as exc:
        logger.error("get_edges error: %s", exc)
        return []


def list_all_edges(limit: int = 500) -> list[dict]:
    try:
        return list(_edges().find({}, sort={"weight": -1}, limit=limit))
    except Exception as exc:
        logger.error("list_all_edges error: %s", exc)
        return []


# ── Subgraph Extraction ───────────────────────────────────────────────────────

def get_subgraph(
    center_id: str,
    depth: int = 2,
    max_nodes: int = 50,
    rel_types: list[str] | None = None,
) -> dict:
    """
    BFS from center_id up to `depth` hops.
    Returns {nodes: [...], edges: [...]} for D3 / force-graph rendering.
    """
    visited_nodes: dict[str, dict] = {}
    visited_edges: dict[str, dict] = {}
    queue = deque([(center_id, 0)])
    seen_ids: set[str] = {center_id}

    # Seed with center node
    center = get_node(center_id)
    if center:
        center["isCenter"] = True
        visited_nodes[center_id] = center

    while queue and len(visited_nodes) < max_nodes:
        node_id, current_depth = queue.popleft()
        if current_depth >= depth:
            continue

        edges = get_edges(node_id, direction="both", rel_types=rel_types, limit=20)
        for edge in edges:
            edge_id = edge["_id"]
            if edge_id not in visited_edges:
                visited_edges[edge_id] = edge

            # Determine the neighbour
            neighbour_id = (
                edge["target_id"] if edge["source_id"] == node_id
                else edge["source_id"]
            )
            if neighbour_id not in seen_ids and len(visited_nodes) < max_nodes:
                seen_ids.add(neighbour_id)
                neighbour = get_node(neighbour_id)
                if neighbour:
                    visited_nodes[neighbour_id] = neighbour
                queue.append((neighbour_id, current_depth + 1))

    # Serialise
    nodes = [_serialise_node(n, center_id) for n in visited_nodes.values()]
    edges = [_serialise_edge(e) for e in visited_edges.values()]

    return {"nodes": nodes, "edges": edges, "center": center_id}


def _serialise_node(node: dict, center_id: str) -> dict:
    return {
        "id":        node["_id"],
        "label":     node.get("name", node["_id"]),
        "type":      node.get("type", "unknown"),
        "color":     node.get("color", "#6b7280"),
        "icon":      node.get("icon", "📌"),
        "count":     node.get("mention_count", 1),
        "isCenter":  node["_id"] == center_id,
    }


def _serialise_edge(edge: dict) -> dict:
    from ontology import get_relationship_meta
    meta = get_relationship_meta(edge.get("rel_type", "associated_with"))
    return {
        "id":       edge["_id"],
        "source":   edge["source_id"],
        "target":   edge["target_id"],
        "type":     edge.get("rel_type", "associated_with"),
        "label":    meta.get("label", edge.get("rel_type", "")),
        "weight":   edge.get("weight", 1.0),
        "inferred": edge.get("inferred", False),
    }


# ── Event Linking ─────────────────────────────────────────────────────────────

def link_events(
    event_id_a: str,
    event_id_b: str,
    link_type: str = "related",
    confidence: float = 1.0,
    rationale: str = "",
) -> str:
    """
    Create a directional link between two events.
    link_type: 'related' | 'preceded_by' | 'caused' | 'part_of'
    Returns link_id.
    """
    link_id = f"{event_id_a}__{link_type}__{event_id_b}"
    try:
        existing = _event_links().find_one({"_id": link_id})
        if not existing:
            _event_links().insert_one({
                "_id":        link_id,
                "event_a":    event_id_a,
                "event_b":    event_id_b,
                "link_type":  link_type,
                "confidence": confidence,
                "rationale":  rationale,
                "created_at": _utc_now(),
            })
    except Exception as exc:
        logger.error("link_events error: %s", exc)
    return link_id


def get_event_links(event_id: str) -> list[dict]:
    """Return all event links involving event_id (in or out)."""
    try:
        out_links = list(_event_links().find({"event_a": event_id}, limit=20))
        in_links  = list(_event_links().find({"event_b": event_id}, limit=20))
        return out_links + in_links
    except Exception as exc:
        logger.error("get_event_links error: %s", exc)
        return []


def get_event_chain(event_id: str, max_hops: int = 5) -> list[dict]:
    """
    Follow 'preceded_by' and 'part_of' links to build a temporal chain.
    Returns ordered list of event descriptors.
    """
    from astra_client import events as ev_coll

    chain: list[dict] = []
    visited: set[str] = set()
    current_id = event_id

    for _ in range(max_hops):
        if current_id in visited:
            break
        visited.add(current_id)

        try:
            ev = ev_coll().find_one(
                {"_id": current_id},
                projection={"summary": 1, "event_type": 1, "severity": 1,
                            "created_at": 1, "locations": 1, "_id": 1},
            )
        except Exception:
            break

        if not ev:
            break
        chain.append(ev)

        # Find what this event was preceded by
        links = list(_event_links().find(
            {"event_a": current_id, "link_type": {"$in": ["preceded_by", "part_of"]}},
            limit=5,
        ))
        if not links:
            break
        # Pick the highest-confidence link
        links.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        current_id = links[0]["event_b"]

    return chain


def find_similar_and_link(
    event_id: str,
    event_summary: str,
    event_type: str,
    threshold: float = 0.82,
    limit: int = 5,
) -> list[str]:
    """
    Find semantically similar events and create links.
    Called from pipeline after inserting a new event.
    Returns list of linked event_ids.
    """
    from astra_client import events as ev_coll
    from embedder import embed_text

    linked: list[str] = []
    try:
        vec = embed_text(event_summary)
        results = list(ev_coll().find(
            {"event_type": event_type, "_id": {"$ne": event_id}},
            sort={"$vector": vec},
            limit=limit,
            include_similarity=True,
            projection={"_id": 1, "summary": 1, "created_at": 1, "$similarity": 1},
        ))

        for r in results:
            sim = r.get("$similarity", 0)
            if sim >= threshold:
                link_id = link_events(
                    event_id_a=event_id,
                    event_id_b=r["_id"],
                    link_type="related",
                    confidence=round(sim, 3),
                    rationale=f"Semantic similarity {sim:.3f}",
                )
                linked.append(r["_id"])
                logger.info("Event linked: %s → %s (sim=%.3f)", event_id, r["_id"], sim)

    except Exception as exc:
        logger.error("find_similar_and_link error: %s", exc)

    return linked


# ── Community Detection ───────────────────────────────────────────────────────

def detect_communities(max_nodes: int = 200) -> list[dict]:
    """
    Simple label propagation community detection on the entity graph.
    Returns list of {community_id, members, size, label} dicts.
    Stores results in a 'graph_communities' collection.
    """
    nodes = list_nodes(limit=max_nodes, min_mentions=2)
    if not nodes:
        return []

    node_ids = [n["_id"] for n in nodes]
    node_map = {n["_id"]: n for n in nodes}

    # Build adjacency from edges
    adjacency: dict[str, list[str]] = defaultdict(list)
    all_edges = list_all_edges(limit=1000)
    for edge in all_edges:
        s, t = edge["source_id"], edge["target_id"]
        if s in node_map and t in node_map:
            adjacency[s].append(t)
            adjacency[t].append(s)

    # Label propagation
    labels: dict[str, str] = {nid: nid for nid in node_ids}
    for _ in range(20):  # max iterations
        changed = False
        for nid in node_ids:
            neighbours = adjacency.get(nid, [])
            if not neighbours:
                continue
            # Pick most common label among neighbours
            label_counts: dict[str, int] = defaultdict(int)
            for n in neighbours:
                label_counts[labels.get(n, n)] += 1
            best_label = max(label_counts, key=label_counts.__getitem__)
            if best_label != labels[nid]:
                labels[nid] = best_label
                changed = True
        if not changed:
            break

    # Group into communities
    communities: dict[str, list[str]] = defaultdict(list)
    for nid, label in labels.items():
        communities[label].append(nid)

    results = []
    for comm_id, members in sorted(communities.items(), key=lambda x: -len(x[1])):
        if len(members) < 2:
            continue
        # Name community after its most-mentioned member
        best = max(
            members,
            key=lambda mid: node_map.get(mid, {}).get("mention_count", 0),
        )
        results.append({
            "community_id": comm_id,
            "label":        node_map.get(best, {}).get("name", comm_id),
            "size":         len(members),
            "members":      members,
            "top_types":    _top_types(members, node_map),
        })

    return results[:20]


def _top_types(members: list[str], node_map: dict) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for mid in members:
        t = node_map.get(mid, {}).get("type", "unknown")
        counts[t] += 1
    return [t for t, _ in sorted(counts.items(), key=lambda x: -x[1])[:3]]


# ── GraphRAG Context Builder ──────────────────────────────────────────────────

def build_graphrag_context(
    query: str,
    max_nodes: int = 15,
    max_events: int = 10,
) -> str:
    """
    Build a structured context string for LLM queries by combining:
    1. Semantically similar events
    2. Relevant entity graph neighbourhood
    3. Active trends

    Used by the analyst copilot to ground LLM responses.
    """
    from astra_client import events as ev_coll, entities as ent_coll
    from embedder import embed_text

    parts: list[str] = []

    try:
        # 1. Semantic event retrieval
        vec = embed_text(query)
        events = list(ev_coll().find(
            {},
            sort={"$vector": vec},
            limit=max_events,
            include_similarity=True,
            projection={
                "summary": 1, "event_type": 1, "severity": 1,
                "created_at": 1, "locations": 1, "organizations": 1,
                "people": 1, "_id": 1, "$similarity": 1,
            },
        ))

        if events:
            parts.append("## Relevant Events")
            for ev in events:
                date = (ev.get("created_at") or "")[:10]
                locs = ev.get("locations") or []
                if isinstance(locs, str):
                    try: locs = json.loads(locs)
                    except: locs = []
                parts.append(
                    f"- [{ev.get('severity','?').upper()}] {ev.get('event_type','?')} "
                    f"on {date}: {ev.get('summary','')[:200]}"
                    + (f" [{', '.join(locs[:2])}]" if locs else "")
                )

        # 2. Entity context — find entities mentioned in top events
        entity_names: set[str] = set()
        for ev in events[:5]:
            for field in ("organizations", "people"):
                val = ev.get(field) or []
                if isinstance(val, str):
                    try: val = json.loads(val)
                    except: val = []
                entity_names.update(str(v) for v in val[:3])

        if entity_names:
            parts.append("\n## Key Entities")
            for name in list(entity_names)[:max_nodes]:
                node = None
                try:
                    node = ent_coll().find_one(
                        {"name": name},
                        projection={"type": 1, "mention_count": 1},
                    )
                except Exception:
                    pass
                type_label = node.get("type", "entity") if node else "entity"
                parts.append(f"- {name} ({type_label})")

    except Exception as exc:
        logger.error("build_graphrag_context error: %s", exc)
        parts.append("(Context retrieval failed)")

    return "\n".join(parts)


# ── Graph Reconciliation (ADR-002 safety net) ─────────────────────────────────

def reconcile_graph_nodes(days: int = 7) -> dict:
    """
    ADR-002: Periodic safety-net reconciliation job.

    Compares `entities` with `graph_nodes` and backfills any entity that is
    present in entities but missing from graph_nodes. This catches anything
    that slipped through the in-process retry queue (e.g. items queued at
    process-restart time).

    Scheduled every 6 hours via APScheduler (registered in main.py lifespan).
    Returns a summary dict for logging / health reporting.
    """
    from astra_client import entities as ent_coll
    from datetime import timedelta

    since    = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    backfilled = 0
    errors     = 0

    try:
        # Prefer recently-seen entities; fall back to full scan on cold start
        ents = list(ent_coll().find(
            {"last_seen_at": {"$gte": since}},
            projection={"_id": 1, "name": 1, "type": 1},
            limit=5000,
        ))
        if not ents:
            ents = list(ent_coll().find(
                {},
                projection={"_id": 1, "name": 1, "type": 1},
                limit=5000,
            ))

        for ent in ents:
            try:
                existing_node = _nodes().find_one({"_id": ent["_id"]}, projection={"_id": 1})
                if not existing_node:
                    upsert_node(
                        entity_id=ent["_id"],
                        name=ent.get("name", ""),
                        entity_type=ent.get("type", "unknown"),
                        raw_type=ent.get("type", "unknown"),
                    )
                    backfilled += 1
            except Exception as exc:
                logger.warning("reconcile_graph_nodes: error on %s — %s", ent["_id"], exc)
                errors += 1

    except Exception as exc:
        logger.error("reconcile_graph_nodes: scan failed — %s", exc)
        return {"backfilled": 0, "errors": 1, "scanned": 0, "status": "error"}

    summary = {
        "backfilled": backfilled,
        "errors":     errors,
        "scanned":    len(ents),
        "status":     "ok",
    }
    if backfilled:
        logger.warning("reconcile_graph_nodes: backfilled %d missing node(s)", backfilled)
    else:
        logger.info("reconcile_graph_nodes: all nodes present (%d scanned)", len(ents))
    return summary


# ── Build graph from existing entities ───────────────────────────────────────

def build_graph_from_entities(days: int = 30) -> int:
    """
    Scan existing event_entities and build graph nodes + edges.
    Run this as a one-time migration or periodic job.
    Returns count of edges created.
    """
    from astra_client import event_entities as ee_coll, entities as ent_coll
    from datetime import timedelta

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    edges_created = 0

    try:
        # Build entity nodes from existing entities collection
        ents = list(ent_coll().find({}, projection={"_id": 1, "name": 1, "type": 1}, limit=2000))
        for ent in ents:
            upsert_node(
                entity_id=ent["_id"],
                name=ent.get("name", ""),
                entity_type=ent.get("type", "unknown"),
                raw_type=ent.get("type", "unknown"),
            )

        # Build co-occurrence edges from event_entities
        ee_docs = list(ee_coll().find(
            {"created_at": {"$gte": since}},
            projection={"event_id": 1, "entity_id": 1},
            limit=10000,
        ))

        event_to_ents: dict[str, list[str]] = defaultdict(list)
        for doc in ee_docs:
            event_to_ents[doc["event_id"]].append(doc["entity_id"])

        for eid_list in event_to_ents.values():
            unique = list(set(eid_list))
            for i in range(len(unique)):
                for j in range(i + 1, len(unique)):
                    upsert_edge(
                        source_id=unique[i],
                        target_id=unique[j],
                        rel_type="co_occurred_with",
                        weight=0.6,
                        evidence=[],
                        inferred=True,
                        confidence=0.8,
                    )
                    edges_created += 1

    except Exception as exc:
        logger.error("build_graph_from_entities error: %s", exc)

    logger.info("Graph built: %d edges created", edges_created)
    return edges_created


# ── Graph Statistics ──────────────────────────────────────────────────────────

def graph_stats() -> dict:
    """Return summary stats about the current knowledge graph."""
    try:
        node_count = _nodes().count_documents({})
        edge_count = _edges().count_documents({})
        link_count = _event_links().count_documents({})

        type_dist: dict[str, int] = defaultdict(int)
        for node in _nodes().find({}, projection={"type": 1}, limit=2000):
            type_dist[node.get("type", "unknown")] += 1

        rel_dist: dict[str, int] = defaultdict(int)
        for edge in _edges().find({}, projection={"rel_type": 1}, limit=2000):
            rel_dist[edge.get("rel_type", "unknown")] += 1

        return {
            "total_nodes":         node_count,
            "total_edges":         edge_count,
            "total_event_links":   link_count,
            "node_type_distribution": dict(type_dist),
            "rel_type_distribution":  dict(rel_dist),
        }
    except Exception as exc:
        logger.error("graph_stats error: %s", exc)
        return {"total_nodes": 0, "total_edges": 0, "total_event_links": 0}

"""
Garuda v3 — Analyst Copilot (copilot.py)

Natural language intelligence interface that combines:
  - GraphRAG context from the knowledge graph
  - Semantic event retrieval
  - Analyst role-play with Jaipur domain expertise

Public API:
  query()          → dict   ← Main copilot query
  get_history()    → list[dict]
  clear_history()  → None
"""

from __future__ import annotations
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODELS  = ["gemini-2.0-flash", "gemini-1.5-flash-latest"]
GEMINI_BASE    = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:generateContent?key={key}"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history():
    from astra_client import copilot_history
    return copilot_history()


SYSTEM_PROMPT = """\
You are GARUDA, a senior intelligence analyst specialising in Jaipur, Rajasthan, India.
You have access to a real-time intelligence database of local news events, entity relationships,
and trend analysis for Jaipur city.

Your role:
- Answer analyst questions about Jaipur events, entities, trends, and patterns
- Reference specific events, locations, people, and organizations when they exist in the context
- Provide actionable intelligence assessments, not just summaries
- Identify patterns, risks, and connections that might not be obvious
- Be precise about what you know from the data vs. what you are inferring

Tone: Professional intelligence analyst. Concise, factual, specific.
Language: English only.
Format: Use structured sections when appropriate. Avoid markdown in short answers.
"""


def _build_prompt(user_query: str, context: str, history: list[dict]) -> list[dict]:
    """Build the conversation messages for Gemini."""
    messages = [{"role": "user", "parts": [{"text": SYSTEM_PROMPT}]}]

    # Add conversation history (last 6 turns)
    for turn in history[-6:]:
        messages.append({
            "role": "user",
            "parts": [{"text": turn["query"]}],
        })
        messages.append({
            "role": "model",
            "parts": [{"text": turn["response"]}],
        })

    # Current query with context
    full_query = f"""{user_query}

---
INTELLIGENCE CONTEXT (from live database, use this to ground your answer):
{context}
---
"""
    messages.append({"role": "user", "parts": [{"text": full_query}]})
    return messages


def query(
    user_query: str,
    session_id: str | None = None,
    include_context: bool = True,
) -> dict:
    """
    Main copilot query function.
    Returns {query_id, response, context_used, session_id, sources}.
    """
    if not GEMINI_API_KEY:
        return {
            "query_id":     str(uuid.uuid4()),
            "response":     "Copilot is unavailable: GEMINI_API_KEY is not configured.",
            "context_used": False,
            "session_id":   session_id or str(uuid.uuid4()),
            "sources":      [],
        }

    session_id = session_id or str(uuid.uuid4())
    query_id   = str(uuid.uuid4())

    # Load conversation history for this session
    history: list[dict] = []
    try:
        history = list(_history().find(
            {"session_id": session_id},
            sort={"created_at": 1},
            limit=10,
        ))
    except Exception:
        pass

    # Build GraphRAG context
    context = ""
    sources: list[str] = []
    if include_context:
        try:
            from knowledge_graph import build_graphrag_context
            context = build_graphrag_context(user_query, max_nodes=15, max_events=10)
            sources = ["knowledge_graph", "semantic_search"]
        except Exception as exc:
            logger.warning("GraphRAG context failed: %s", exc)
            # Fallback: simple semantic search
            try:
                from analyst import semantic_search
                events = semantic_search(user_query, limit=8)
                if events:
                    parts = ["## Relevant Events"]
                    for ev in events:
                        parts.append(
                            f"- [{ev.get('severity','?').upper()}] {ev.get('event_type','?')}: "
                            f"{ev.get('summary','')[:200]}"
                        )
                    context = "\n".join(parts)
                    sources = ["semantic_search"]
            except Exception:
                pass

    messages = _build_prompt(user_query, context, history)

    response_text: str = ""
    for model in GEMINI_MODELS:
        url = GEMINI_BASE.format(model=model, key=GEMINI_API_KEY)
        try:
            resp = httpx.post(
                url,
                json={
                    "contents": messages,
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 2048,
                    },
                },
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                response_text = "".join(p.get("text", "") for p in parts).strip()
            if response_text:
                break
        except Exception as exc:
            logger.warning("Copilot model %s failed: %s", model, exc)
            continue

    if not response_text:
        response_text = (
            "I was unable to generate a response at this time. "
            "Please check the Gemini API configuration and try again."
        )

    # Store in history
    try:
        _history().insert_one({
            "_id":          query_id,
            "session_id":   session_id,
            "query":        user_query,
            "response":     response_text,
            "context_used": bool(context),
            "sources":      sources,
            "created_at":   _utc_now(),
        })
    except Exception as exc:
        logger.warning("Copilot history store error: %s", exc)

    return {
        "query_id":     query_id,
        "session_id":   session_id,
        "query":        user_query,
        "response":     response_text,
        "context_used": bool(context),
        "sources":      sources,
    }


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Retrieve copilot conversation history for a session."""
    try:
        return list(_history().find(
            {"session_id": session_id},
            sort={"created_at": 1},
            limit=limit,
            projection={"query": 1, "response": 1, "created_at": 1, "_id": 1},
        ))
    except Exception as exc:
        logger.error("get_history error: %s", exc)
        return []


def get_all_sessions(limit: int = 20) -> list[dict]:
    """Return recent session summaries."""
    try:
        # Get distinct session IDs with latest message
        docs = list(_history().find(
            {},
            sort={"created_at": -1},
            limit=limit * 3,
            projection={"session_id": 1, "query": 1, "created_at": 1},
        ))

        seen: set[str] = set()
        sessions = []
        for doc in docs:
            sid = doc.get("session_id")
            if sid and sid not in seen:
                seen.add(sid)
                sessions.append({
                    "session_id":   sid,
                    "last_query":   doc.get("query", "")[:80],
                    "last_message": doc.get("created_at", ""),
                })
            if len(sessions) >= limit:
                break
        return sessions
    except Exception as exc:
        logger.error("get_all_sessions error: %s", exc)
        return []


def clear_history(session_id: str) -> None:
    """Delete all history for a session."""
    try:
        docs = list(_history().find({"session_id": session_id}, projection={"_id": 1}))
        for doc in docs:
            _history().delete_one({"_id": doc["_id"]})
    except Exception as exc:
        logger.error("clear_history error: %s", exc)

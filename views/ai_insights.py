"""AI Insights tab with deterministic-first incident analysis."""

from __future__ import annotations

import hashlib
import json
import os

import streamlit as st

from analysis.ai_insights import (
    build_insights_context,
    build_rule_based_narrative,
    compose_ai_summary,
    configured_model,
    generate_ai_summary,
    serialize_insights_context,
)

_CACHE_LIMIT = 8
_CACHE_VERSION = "deterministic-sequence-only-v1"


def _cache_key(payload: str, model: str, selections: dict) -> str:
    selection_signature = json.dumps(
        {
            key: sorted(str(value) for value in selections.get(key, []))
            for key in (
                "services",
                "caller_types",
                "topics",
                "db_instances",
                "event_ids",
                "infra_tiers",
            )
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{_CACHE_VERSION}\0{model}\0{payload}\0{selection_signature}".encode("utf-8")
    ).hexdigest()
    return digest


def _store_result(cache: dict, key: str, summary: str) -> None:
    cache[key] = summary
    while len(cache) > _CACHE_LIMIT:
        cache.pop(next(iter(cache)))


def render_ai_insights(
    current,
    baseline,
    changes,
    start_day,
    end_day,
    selections,
):
    """Render a rule-based summary first and an explicit, optional AI summary."""
    context = build_insights_context(
        current,
        baseline,
        changes,
        start_day,
        end_day,
        selections,
    )
    payload = serialize_insights_context(context)
    rule_narrative = build_rule_based_narrative(json.loads(payload))
    model = configured_model()
    cache_key = _cache_key(payload, model, selections)
    api_key = os.environ.get("OPENAI_API_KEY")

    st.subheader("Incident summary")
    st.caption("Rule-based")
    st.markdown(rule_narrative)

    with st.expander("What was sent to the model"):
        st.caption(
            f"Compact filtered summary · {len(payload.encode('utf-8'))} bytes. "
            "No raw metric rows or credentials are included."
        )
        st.code(payload, language="json")

    if not api_key:
        st.info(
            "AI summaries are disabled because OPENAI_API_KEY is not configured. "
            "Add it in Replit Tools → Secrets to enable generation."
        )

    if st.session_state.get("ai_insights_cache_version") != _CACHE_VERSION:
        # Discard responses generated before the deterministic sequence semantics
        # were added so the old Oct 9 summary cannot be reused.
        st.session_state["ai_insights_cache"] = {}
        st.session_state["ai_insights_cache_version"] = _CACHE_VERSION

    cache = st.session_state.setdefault("ai_insights_cache", {})
    if not isinstance(cache, dict):
        cache = {}
        st.session_state["ai_insights_cache"] = cache

    clicked = st.button(
        "Generate AI summary",
        key="ai_insights_generate",
        disabled=not api_key,
    )
    if clicked and api_key:
        if cache_key in cache:
            st.info("Using the cached AI summary for these filters.")
        else:
            try:
                with st.spinner("Generating the AI summary…"):
                    summary = generate_ai_summary(payload, api_key, model)
                _store_result(cache, cache_key, summary)
            except Exception as error:
                st.warning(
                    f"AI summary unavailable ({type(error).__name__}). "
                    "The rule-based summary above remains available."
                )

    cached_summary = cache.get(cache_key)
    if cached_summary:
        st.divider()
        composed_summary = compose_ai_summary(cached_summary, json.loads(payload))
        if composed_summary is None:
            st.caption("Rule-based")
            st.info(
                "The AI response did not include all required sections; "
                "the rule-based summary remains authoritative."
            )
            st.markdown(rule_narrative)
        else:
            st.caption(f"AI-generated ({model})")
            st.markdown(composed_summary)

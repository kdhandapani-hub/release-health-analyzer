"""Compact, deterministic incident context and optional AI narration."""

from __future__ import annotations

import json
import math
import numbers
import os

import pandas as pd

from analysis.api_metrics import failure_reason_breakdown
from analysis.database_metrics import detect_plan_regressions
from analysis.infrastructure import summarize_infrastructure
from analysis.metrics import summarize
from analysis.root_cause import analyze_root_cause

DEFAULT_LLM_MODEL = "gpt-5.4-mini"
MAX_CONTEXT_BYTES = 3000
COMPACT_CONTEXT_BYTES = 2900

SYSTEM_PROMPT = (
    "You are an SRE incident analyst. Use ONLY the summarized JSON in the user "
    "message. Do not contradict the deterministic correlation result, including "
    "its likely trigger, onset/critical sequence, cleared changes, or "
    "infrastructure classifications. Do not guess; say 'insufficient data' "
    "when evidence is missing. If no layer breaches are reported and layer "
    "coverage is available, say the period was healthy and list any isolated "
    "events. If coverage is missing, say so. Return plain English using these "
    "section headings, in this order: What happened, Sequence, Likely root cause, "
    "Ruled out, Recommended next checks."
)


def configured_model() -> str:
    """Return the requested model name, or the current low-cost default."""
    return os.environ.get("LLM_MODEL", "").strip() or DEFAULT_LLM_MODEL


def _short_text(value, limit=96):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text or None


def _number(value, digits=2):
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return _short_text(value)
    if math.isnan(numeric):
        return None
    if math.isinf(numeric):
        return "infinite" if numeric > 0 else "-infinite"
    return round(numeric, digits)


def _timestamp(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return None


def _filtered_values(selections, key):
    values = selections.get(key) or []
    if not values:
        return "all"
    compact = [_short_text(value, 40) for value in values[:3]]
    if len(values) > 3:
        compact.append(f"+{len(values) - 3} more")
    return compact


def _paired_metric(current, baseline, key):
    current_value = current.get(key)
    baseline_value = baseline.get(key)
    current_is_number = isinstance(current_value, numbers.Real)
    baseline_is_number = isinstance(baseline_value, numbers.Real)
    if current_is_number and baseline_is_number:
        current_number = float(current_value)
        baseline_number = float(baseline_value)
        return {
            "current": _number(current_number),
            "baseline": _number(baseline_number),
            "delta": _number(current_number - baseline_number),
        }
    return {
        "current": _number(current_value) if current_is_number else _short_text(current_value),
        "baseline": (
            _number(baseline_value)
            if baseline_is_number
            else _short_text(baseline_value)
        ),
    }


def _layer_kpis(current, baseline):
    current_metrics = summarize(current["api"], current["kafka"], current["db"])
    baseline_metrics = summarize(
        baseline["api"], baseline["kafka"], baseline["db"]
    )
    kpis = {
        "API": {
            "pass_rate_pct": _paired_metric(
                current_metrics, baseline_metrics, "api_pass_rate"
            ),
            "p95_latency_ms": _paired_metric(
                current_metrics, baseline_metrics, "api_p95_latency"
            ),
        },
        "Messaging": {
            "max_consumer_lag_messages": _paired_metric(
                current_metrics, baseline_metrics, "kafka_max_lag"
            ),
            "avg_error_rate_pct": _paired_metric(
                current_metrics, baseline_metrics, "kafka_avg_error_rate"
            ),
        },
        "Database": {
            "avg_sql_elapsed_ms": _paired_metric(
                current_metrics, baseline_metrics, "db_avg_elapsed"
            ),
            "slowest_sql_elapsed_ms": _paired_metric(
                current_metrics, baseline_metrics, "db_max_sql_elapsed"
            ),
            "slowest_sql_id": _paired_metric(
                current_metrics, baseline_metrics, "db_slowest_sql_id"
            ),
            "top_wait_class": _paired_metric(
                current_metrics, baseline_metrics, "db_top_wait_class"
            ),
            "avg_active_sessions": _paired_metric(
                current_metrics, baseline_metrics, "db_active_sessions"
            ),
        },
    }

    if "infra" in current:
        current_infra = summarize_infrastructure(current["infra"])
        baseline_infra = summarize_infrastructure(
            baseline.get("infra", current["infra"].iloc[0:0])
        )
        kpis["Infrastructure"] = {
            "peak_cpu_pct": _paired_metric(
                current_infra, baseline_infra, "peak_cpu_pct"
            ),
            "peak_memory_pct": _paired_metric(
                current_infra, baseline_infra, "peak_memory_pct"
            ),
            "total_restarts": _paired_metric(
                current_infra, baseline_infra, "total_restarts"
            ),
            "unhealthy_pods_or_hosts": _paired_metric(
                current_infra, baseline_infra, "unhealthy_assets"
            ),
        }
    return kpis


def build_insights_context(
    current,
    baseline,
    changes: pd.DataFrame,
    start_day,
    end_day,
    selections: dict,
) -> dict:
    """Build a compact summary from already-filtered current and baseline data."""
    root = analyze_root_cause(
        current["api"],
        current["kafka"],
        current["db"],
        changes,
        start_day,
        end_day,
        selected_event_ids=selections.get("event_ids", []),
        infra=current.get("infra"),
    )

    trigger = root["trigger"]
    root_summary = {
        "likely_trigger": (
            {
                "change_id": _short_text(trigger.get("change_id"), 48),
                "type": _short_text(trigger.get("change_type"), 48),
                "time_utc": _timestamp(trigger.get("timestamp")),
                "description": _short_text(trigger.get("description"), 110),
            }
            if trigger
            else None
        ),
        "first_critical_breach": (
            {
                "layer": root["first_breach"]["layer"],
                "time_utc": _timestamp(root["first_breach"]["timestamp"]),
            }
            if root["first_breach"]
            else None
        ),
        "sequence": [
            {
                "layer": item["layer"],
                "onset_utc": _timestamp(item["onset_timestamp"]),
                "critical_utc": _timestamp(item["critical_timestamp"]),
            }
            for item in root["sequence"]
        ],
        "cleared_changes": [
            {
                "change_id": _short_text(item.get("change_id"), 48),
                "type": _short_text(item.get("change_type"), 48),
                "time_utc": _timestamp(item.get("timestamp")),
            }
            for item in root["event_assessments"]
            if item["status"] == "cleared"
        ][:8],
        "inconclusive_changes": [
            {
                "change_id": _short_text(item.get("change_id"), 48),
                "type": _short_text(item.get("change_type"), 48),
                "time_utc": _timestamp(item.get("timestamp")),
            }
            for item in root["event_assessments"]
            if item["status"] == "inconclusive"
        ][:8],
        "infrastructure_classifications": [
            {
                "classification": _short_text(item.get("classification"), 40),
                "component": _short_text(item.get("component"), 48),
                "onset_utc": _timestamp(item.get("onset_timestamp")),
                "end_utc": _timestamp(item.get("end_timestamp")),
            }
            for item in root.get("infrastructure_assessments", [])
        ][:6],
        "no_layer_breaches": not root["sequence"],
    }

    plan_frames = [
        frame
        for frame in (baseline.get("db"), current.get("db"))
        if frame is not None and not frame.empty
    ]
    plan_source = (
        pd.concat(plan_frames, ignore_index=True)
        if plan_frames
        else current["db"].iloc[0:0]
    )
    plan_regressions = detect_plan_regressions(
        plan_source, start_day=start_day, end_day=end_day
    )
    plan_changes = [
        {
            "sql_id": _short_text(item.sql_id, 32),
            "old_plan": _short_text(item.old_plan, 32),
            "new_plan": _short_text(item.new_plan, 32),
            "change_time_utc": _timestamp(item.change_time),
            "elapsed_before_ms": _number(item.elapsed_before_ms),
            "elapsed_after_ms": _number(item.elapsed_after_ms),
            "regression_factor": _number(item.regression_factor),
        }
        for item in plan_regressions.head(6).itertuples(index=False)
    ]

    failure_reasons = failure_reason_breakdown(current["api"])
    top_failures = [
        {
            "reason": _short_text(item.failure_reason, 84),
            "failed_runs": int(item.failed_runs),
            "failure_pct": _number(item.failure_pct),
        }
        for item in failure_reasons.head(5).itertuples(index=False)
    ]

    lanes = root["lanes"]
    context = {
        "date_range_utc": {
            "start": str(start_day),
            "end": str(end_day),
        },
        "filters": {
            "services": _filtered_values(selections, "services"),
            "caller_types": _filtered_values(selections, "caller_types"),
            "topics": _filtered_values(selections, "topics"),
            "db_instances": _filtered_values(selections, "db_instances"),
            "change_events": _filtered_values(selections, "event_ids"),
            "infra_tiers": _filtered_values(selections, "infra_tiers"),
        },
        "coverage_hours": {
            layer: int(len(frame)) for layer, frame in lanes.items()
        },
        "root_cause": root_summary,
        "plan_change_detections": plan_changes,
        "layer_kpis_vs_baseline": _layer_kpis(current, baseline),
        "top_api_failure_reasons": top_failures,
    }
    return context


def serialize_insights_context(context: dict) -> str:
    """Serialize compact JSON, enforcing a strict 3 KB UTF-8 payload budget."""
    compact = json.loads(json.dumps(context, ensure_ascii=False, default=str))
    payload = json.dumps(
        compact, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    if len(payload.encode("utf-8")) > COMPACT_CONTEXT_BYTES:
        root = compact["root_cause"]
        root["cleared_changes"] = root["cleared_changes"][:4]
        root["inconclusive_changes"] = root["inconclusive_changes"][:4]
        root["infrastructure_classifications"] = root[
            "infrastructure_classifications"
        ][:3]
        compact["plan_change_detections"] = compact[
            "plan_change_detections"
        ][:3]
        compact["top_api_failure_reasons"] = compact[
            "top_api_failure_reasons"
        ][:3]
        for key, value in compact["filters"].items():
            if isinstance(value, list):
                compact["filters"][key] = value[:4]
        payload = json.dumps(
            compact, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    if len(payload.encode("utf-8")) > COMPACT_CONTEXT_BYTES:
        root = compact["root_cause"]
        root["cleared_changes"] = root["cleared_changes"][:2]
        root["inconclusive_changes"] = root["inconclusive_changes"][:2]
        root["infrastructure_classifications"] = root[
            "infrastructure_classifications"
        ][:2]
        compact["plan_change_detections"] = compact[
            "plan_change_detections"
        ][:2]
        compact["top_api_failure_reasons"] = compact[
            "top_api_failure_reasons"
        ][:2]
        if root["likely_trigger"]:
            root["likely_trigger"].pop("description", None)
        payload = json.dumps(
            compact, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    if len(payload.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ValueError("Summarized AI context exceeds the 3 KB payload limit.")
    return payload


def _metric_sentence(name, metric, unit, delta_unit=None):
    if not metric or metric.get("current") is None:
        return None
    current = metric["current"]
    baseline = metric.get("baseline")
    delta = metric.get("delta")
    value_text = f"{current}{unit}" if unit == "%" else f"{current} {unit}"
    sentence = f"{name}: {value_text}"
    if baseline is not None:
        baseline_text = (
            f"{baseline}{unit}" if unit == "%" else f"{baseline} {unit}"
        )
        sentence += f" vs {baseline_text} baseline"
        if delta is not None:
            delta_label = delta_unit or unit
            delta_text = (
                f"{delta:+g}{delta_label}"
                if delta_label == "%"
                else f"{delta:+g} {delta_label}"
            )
            sentence += f" ({delta_text})"
    return sentence + "."


def build_rule_based_narrative(context: dict) -> str:
    """Create the always-available incident summary from summarized JSON only."""
    root = context["root_cause"]
    sequence = root["sequence"]
    infra = root["infrastructure_classifications"]
    coverage = context["coverage_hours"]
    have_layer_data = any(coverage.get(layer, 0) for layer in ("Database", "API", "Messaging"))
    complete_layer_data = all(
        coverage.get(layer, 0) for layer in ("Database", "API", "Messaging")
    )
    no_breaches = root["no_layer_breaches"]
    if no_breaches and not have_layer_data:
        what_happened = (
            "Insufficient data to confirm whether the period was healthy; "
            "no layer breach can be assessed from the available metrics."
        )
        sequence_text = "No layer breaches are present in the available data."
        likely_cause = "Insufficient data to identify a likely trigger."
    elif no_breaches and not complete_layer_data:
        what_happened = (
            "No layer breaches were detected in the available metrics, but "
            "coverage is incomplete, so the period cannot be confirmed healthy."
        )
        sequence_text = "No layer breaches were detected in the available data."
        likely_cause = "Insufficient data to identify a likely trigger."
    elif no_breaches:
        what_happened = (
            "The period was healthy across the monitored application layers; "
            "no warning or critical layer breaches were detected."
        )
        sequence_text = "No layer breaches occurred in this range."
        likely_cause = "No likely trigger was identified because no layer breach occurred."
    else:
        critical = root["first_critical_breach"]
        if critical:
            what_happened = (
                f"The first critical degradation was in {critical['layer']} at "
                f"{critical['time_utc']}."
            )
        else:
            first = sequence[0]
            what_happened = (
                f"Warning-level degradation began in {first['layer']} at "
                f"{first['onset_utc']}; no critical breach was recorded."
            )
        sequence_text = " → ".join(
            f"{item['layer']}: onset {item['onset_utc']}, critical "
            f"{item['critical_utc'] or 'not reached'}"
            for item in sequence
        )
        trigger = root["likely_trigger"]
        if trigger:
            likely_cause = (
                f"{trigger['change_id']} ({trigger['type']}) at "
                f"{trigger['time_utc']} is the likely trigger under the "
                "deterministic correlation rule."
            )
        else:
            likely_cause = (
                "Insufficient data to attribute the degradation to a preceding change."
            )

        kpis = context["layer_kpis_vs_baseline"]
        metric_specs = {
            "API": (
                ("pass_rate_pct", "API pass rate", "%", "percentage points"),
                ("p95_latency_ms", "API p95 latency", "ms", None),
            ),
            "Messaging": (
                ("max_consumer_lag_messages", "Maximum consumer lag", "messages", None),
                ("avg_error_rate_pct", "Average messaging error rate", "%", None),
            ),
            "Database": (
                ("avg_sql_elapsed_ms", "Average SQL elapsed time", "ms", None),
                ("slowest_sql_elapsed_ms", "Slowest SQL elapsed time", "ms", None),
            ),
        }
        kpi_details = []
        for layer in dict.fromkeys(item["layer"] for item in sequence):
            for key, label, unit, delta_unit in metric_specs.get(layer, ()):
                detail = _metric_sentence(
                    label, kpis.get(layer, {}).get(key), unit, delta_unit
                )
                if detail:
                    kpi_details.append(detail)
        if kpi_details:
            what_happened += " " + " ".join(kpi_details)
        if kpi_details and not any(
            metric.get("baseline") is not None
            for layer in dict.fromkeys(item["layer"] for item in sequence)
            for metric in kpis.get(layer, {}).values()
        ):
            what_happened += " Prior-period baseline is unavailable for this range."

    if infra:
        infra_sentences = []
        for event in infra:
            classification = event["classification"]
            if classification == "Symptom":
                infra_sentences.append(
                    f"{event['component']} was classified as an infrastructure symptom "
                    f"starting {event['onset_utc']}."
                )
            else:
                infra_sentences.append(
                    f"{event['component']} was classified as {classification.lower()} "
                    f"starting {event['onset_utc']}."
                )
        likely_cause += " " + " ".join(infra_sentences)

    plan_changes = context["plan_change_detections"]
    if plan_changes:
        first_plan = plan_changes[0]
        likely_cause += (
            f" Plan evidence: {first_plan['sql_id']} changed from plan "
            f"{first_plan['old_plan']} to {first_plan['new_plan']} at "
            f"{first_plan['change_time_utc']} with a "
            f"{first_plan['regression_factor']}× elapsed-time regression."
        )

    ruled_out = [
        f"{item['change_id']} was cleared at {item['time_utc']}."
        for item in root["cleared_changes"]
    ]
    ruled_out.extend(
        f"{item['component']} was isolated at {item['onset_utc']}."
        for item in infra
        if item["classification"] == "Isolated infra event"
    )
    ruled_out.extend(
        f"{item['change_id']} remains inconclusive at {item['time_utc']}."
        for item in root["inconclusive_changes"]
    )
    if not ruled_out:
        ruled_out.append("No change event was classified as cleared or isolated.")

    checks = []
    if plan_changes:
        checks.append(
            f"Review the execution-plan change for {plan_changes[0]['sql_id']} "
            "and compare its before/after elapsed time."
        )
    critical_layers = {
        item["layer"] for item in sequence if item["critical_utc"] is not None
    }
    if "API" in critical_layers:
        checks.append(
            "Inspect the affected API service, its top failure reasons, and p95 latency."
        )
    if "Messaging" in critical_layers:
        checks.append(
            "Check consumer-group lag growth, partition throughput, and recovery."
        )
    if "Database" in critical_layers and not plan_changes:
        checks.append(
            "Inspect the slowest SQL and database wait classes around the first breach."
        )
    for event in infra:
        if event["classification"] in ("Symptom", "Isolated infra event"):
            checks.append(
                f"Review {event['component']} resource metrics around "
                f"{event['onset_utc']}."
            )
    if not checks:
        checks.append(
            "Continue monitoring the filtered range and confirm metric coverage."
        )

    reasons = context["top_api_failure_reasons"]
    if reasons and not no_breaches:
        reason_text = ", ".join(
            f"{item['reason']} ({item['failed_runs']} runs)"
            for item in reasons[:3]
        )
        checks.append(f"Confirm the leading API failure reasons: {reason_text}.")

    return (
        f"### What happened\n{what_happened}\n\n"
        f"### Sequence\n{sequence_text}\n\n"
        f"### Likely root cause\n{likely_cause}\n\n"
        f"### Ruled out\n- " + "\n- ".join(ruled_out) + "\n\n"
        f"### Recommended next checks\n- " + "\n- ".join(checks)
    )


def generate_ai_summary(payload: str, api_key: str, model: str) -> str:
    """Make exactly one bounded OpenAI Responses API request."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=payload,
        max_output_tokens=600,
    )
    summary = (response.output_text or "").strip()
    if not summary:
        raise RuntimeError("The model returned an empty summary.")
    return summary

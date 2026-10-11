#!/usr/bin/env python3
"""Generate deterministic synthetic release-health CSVs."""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean


SEED = 179166
INFRA_SEED = SEED + 1
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
HOURS = 14 * 24
OUT_DIR = Path(__file__).resolve().parent

SERVICES = ("accounts", "payments", "customer", "documents", "notifications")
ENDPOINTS = {
    "accounts": (("GET", "/accounts"), ("GET", "/accounts/{id}"), ("POST", "/accounts")),
    "payments": (("GET", "/payments/{id}"), ("POST", "/payments"), ("POST", "/payments/{id}/refund")),
    "customer": (("GET", "/customers/{id}"), ("GET", "/customers"), ("PUT", "/customers/{id}")),
    "documents": (("GET", "/documents/{id}"), ("POST", "/documents"), ("DELETE", "/documents/{id}")),
    "notifications": (("GET", "/notifications"), ("POST", "/notifications"), ("PUT", "/notifications/{id}")),
}
TOPICS = {
    "account-events": ("accounts-consumer",),
    "payment-events": ("payments-consumer",),
    "customer-updates": ("customer-consumer",),
    "document-events": ("documents-consumer",),
    "notification-events": ("notifications-consumer",),
}
INSTANCES = ("ORA-PRD-1", "ORA-PRD-2")
SQL_BY_SERVICE = {
    "accounts": ("ACCQRY01", "ACCDML02"),
    "payments": ("PAYQRY01", "PAYDML02"),
    "customer": ("CUSQRY01", "CUSDML02"),
    "documents": ("DOCQRY01", "DOCDML02"),
    "notifications": ("NOTQRY01", "NOTDML02"),
}
SQL_TYPES = {
    "ACCQRY01": "SELECT", "ACCDML02": "UPDATE",
    "PAYQRY01": "SELECT", "PAYDML02": "INSERT",
    "CUSQRY01": "SELECT", "CUSDML02": "UPDATE",
    "DOCQRY01": "SELECT", "DOCDML02": "MERGE",
    "NOTQRY01": "SELECT", "NOTDML02": "INSERT",
}
OLD_PLAN = "9482716301"
REGRESSED_PLAN = "1175038842"
DB_PATCH_AT = datetime(2026, 10, 9, 10, tzinfo=timezone.utc)
INCIDENT_START = datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
INCIDENT_END = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
API_INCIDENT_START = INCIDENT_START + timedelta(hours=1)
API_INCIDENT_END = INCIDENT_END + timedelta(hours=1)
KAFKA_INCIDENT_START = INCIDENT_START + timedelta(hours=2)
KAFKA_DRAIN_FACTORS = (0.70, 0.40, 0.12)
OCT5_BROKER_INCIDENT_START = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
OCT5_BROKER_RESTART_AT = datetime(2026, 10, 5, 16, tzinfo=timezone.utc)
OCT5_BROKER_RECOVERY_AT = datetime(2026, 10, 5, 17, tzinfo=timezone.utc)
OCT5_BROKER2_TOPICS = {"account-events", "customer-updates"}
APP_NODES = ("node-a1", "node-a2", "node-a3")


def iso(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def write_csv(name: str, columns: tuple[str, ...], rows: list[dict]) -> None:
    path = OUT_DIR / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def current_release(timestamp: datetime) -> str:
    if timestamp >= datetime(2026, 10, 9, 6, tzinfo=timezone.utc):
        return "R2026.10.09"
    if timestamp >= datetime(2026, 10, 5, 9, tzinfo=timezone.utc):
        return "R2026.10.05"
    return "R2026.10.01"


def generate_api(rng: random.Random) -> list[dict]:
    rows = []
    failure_codes = (400, 401, 404, 500, 503, 504)
    run_number = 1
    for hour_index in range(HOURS):
        timestamp = START + timedelta(hours=hour_index)
        for service, endpoints in ENDPOINTS.items():
            repetitions = 34 if service == "payments" else 8
            affected = service == "payments" and API_INCIDENT_START <= timestamp < API_INCIDENT_END
            # Vary 1–3 failed assertions across 102 baseline payments runs so
            # hourly pass rates naturally range from about 97.1% to 99.0%.
            baseline_payment_failures = (
                set(rng.sample(range(len(endpoints) * repetitions), rng.randint(1, 3)))
                if service == "payments" and not affected
                else set()
            )
            test_index = 0
            for method, endpoint in endpoints:
                for _ in range(repetitions):
                    if affected:
                        # Degradation begins after the DB plan changes, then eases near the end.
                        elapsed_hours = (timestamp - API_INCIDENT_START).total_seconds() / 3600
                        severity = 1.0 - 0.22 * max(0, elapsed_hours - 5) / 4
                        latency = int(clamp(rng.lognormvariate(7.45, 0.42) * severity, 500, 12000))
                        failure_probability = 0.30 + 0.12 * severity
                    else:
                        latency = int(clamp(rng.lognormvariate(5.55, 0.24), 90, 900))
                        failure_probability = 0.016

                    if service == "payments" and not affected:
                        failed = test_index in baseline_payment_failures
                    else:
                        failed = rng.random() < failure_probability
                    if failed:
                        if affected:
                            status = rng.choices((500, 503, 504), weights=(0.24, 0.28, 0.48))[0]
                            reason = "timeout" if status == 504 else "5xx"
                        else:
                            status = rng.choice(failure_codes)
                            reason = {
                                400: "schema mismatch", 401: "auth failure",
                                404: "not found", 500: "5xx", 503: "service unavailable",
                                504: "timeout",
                            }[status]
                    else:
                        status = 201 if method == "POST" else 200
                        reason = ""

                    rows.append({
                        "run_id": f"run-{run_number:07d}",
                        "timestamp": iso(timestamp + timedelta(minutes=rng.randrange(60))),
                        "release_tag": current_release(timestamp),
                        "service": service,
                        "endpoint": endpoint,
                        "method": method,
                        "status_code": status,
                        "passed": not failed,
                        "latency_ms": latency,
                        "failure_reason": reason,
                    })
                    run_number += 1
                    test_index += 1
    return rows


def generate_kafka(rng: random.Random) -> list[dict]:
    rows = []
    payment_lag_by_partition = {}
    for hour_index in range(HOURS):
        timestamp = START + timedelta(hours=hour_index)
        for topic, consumer_groups in TOPICS.items():
            for consumer_group in consumer_groups:
                for partition in range(6):
                    lag = max(0, int(rng.gauss(28, 13)))
                    throughput = max(0.1, rng.gauss(82, 12))
                    error_rate = max(0.0, rng.gauss(0.12, 0.08))

                    if topic == "payment-events" and KAFKA_INCIDENT_START <= timestamp < INCIDENT_END:
                        hours_into = (timestamp - KAFKA_INCIDENT_START).total_seconds() / 3600
                        # The lag accumulates as the consumer's database writes slow down.
                        lag = int(450 + 850 * hours_into + partition * 37 + rng.randint(0, 260))
                        payment_lag_by_partition[partition] = lag
                        error_rate = round(clamp(rng.gauss(3.5 + 0.55 * hours_into, 0.7), 1.5, 9.0), 3)
                        throughput = max(5.0, rng.gauss(56 - 3.2 * hours_into, 8))
                    elif (
                        topic == "payment-events"
                        and INCIDENT_END <= timestamp < INCIDENT_END + timedelta(hours=len(KAFKA_DRAIN_FACTORS))
                    ):
                        hours_after = int((timestamp - INCIDENT_END).total_seconds() / 3600)
                        previous_lag = payment_lag_by_partition.get(partition, lag)
                        lag = int(lag + max(0, previous_lag - lag) * KAFKA_DRAIN_FACTORS[hours_after])
                        payment_lag_by_partition[partition] = lag

                    # These topics are assigned to broker-2 in the Oct 5
                    # red-herring scenario. Only their lag changes; throughput
                    # and error-rate samples stay on their original RNG path.
                    if topic in OCT5_BROKER2_TOPICS:
                        if timestamp == OCT5_BROKER_RESTART_AT:
                            lag = 900 + partition * 45
                        elif timestamp == OCT5_BROKER_RECOVERY_AT:
                            lag = 550 + partition * 20

                    rows.append({
                        "timestamp": iso(timestamp),
                        "topic": topic,
                        "consumer_group": consumer_group,
                        "partition": partition,
                        "lag": lag,
                        "msgs_per_sec": round(throughput, 3),
                        "error_rate": round(error_rate, 3),
                    })
    return rows


def generate_db(rng: random.Random) -> list[dict]:
    rows = []
    for hour_index in range(HOURS):
        timestamp = START + timedelta(hours=hour_index)
        for service in SERVICES:
            for caller_type in ("API", "CONSUMER"):
                db_user = f"SVC_{service.upper()}_{caller_type}"
                for sql_id in SQL_BY_SERVICE[service]:
                    for instance in INSTANCES:
                        affected = (
                            service == "payments"
                            and sql_id == "PAYQRY01"
                            and INCIDENT_START <= timestamp < INCIDENT_END
                        )
                        executions = max(1, int(rng.gauss(260 if caller_type == "API" else 120, 35)))
                        elapsed_ms = clamp(rng.gauss(115 if sql_id.endswith("QRY01") else 72, 14), 25, 250)
                        cpu_ms = elapsed_ms * rng.uniform(0.25, 0.62)
                        wait_class = rng.choices(
                            ("CPU", "User I/O", "Concurrency", "Commit", "Application"),
                            weights=(42, 24, 14, 12, 8),
                        )[0]
                        wait_pct = clamp(rng.gauss(27, 8), 3, 58)
                        active_sessions = clamp(rng.gauss(1.5, 0.45), 0.1, 4.0)
                        plan_hash = OLD_PLAN

                        if affected:
                            elapsed_ms = clamp(elapsed_ms * rng.uniform(6.2, 8.2), 700, 1600)
                            cpu_ms = elapsed_ms * rng.uniform(0.10, 0.22)
                            wait_class = "User I/O"
                            wait_pct = clamp(rng.gauss(76, 6), 58, 94)
                            active_sessions = clamp(rng.gauss(5.2, 1.0), 2.5, 9.0)
                            plan_hash = REGRESSED_PLAN

                        rows.append({
                            "timestamp": iso(timestamp),
                            "db_instance": instance,
                            "db_user": db_user,
                            "sql_id": sql_id,
                            "sql_type": SQL_TYPES[sql_id],
                            "executions": executions,
                            "avg_elapsed_ms": round(elapsed_ms, 2),
                            "cpu_ms": round(cpu_ms, 2),
                            "top_wait_class": wait_class,
                            "wait_time_pct": round(wait_pct, 2),
                            "active_sessions": round(active_sessions, 2),
                            "plan_hash_value": plan_hash,
                        })
    return rows


def generate_infra(rng: random.Random) -> list[dict]:
    """Generate hourly app, broker, and database-host metrics independently."""
    rows = []
    pod_layout = {}
    for service_index, service in enumerate(SERVICES):
        pod_count = rng.randint(1, 2)
        pod_layout[service] = [
            {
                "pod": f"{service}-{rng.randrange(1000, 10000)}-x{pod_index + 1}",
                "node": APP_NODES[(service_index + pod_index) % len(APP_NODES)],
            }
            for pod_index in range(pod_count)
        ]

    broker_topics = (
        ("kafka-broker-1", "kafka-node-1", "broker-1"),
        ("kafka-broker-2", "kafka-node-2", "broker-2"),
        ("kafka-broker-3", "kafka-node-3", "broker-3"),
    )
    db_hosts = (
        ("ORA-PRD-1", "db-host-1"),
        ("ORA-PRD-2", "db-host-2"),
    )

    def make_row(timestamp, tier, component, node, pod="", **overrides):
        values = {
            "timestamp": iso(timestamp),
            "tier": tier,
            "component": component,
            "node": node,
            "pod": pod,
            "cpu_pct": round(rng.uniform(30, 55), 2),
            "memory_pct": round(rng.uniform(50, 70), 2),
            "io_wait_pct": round(rng.uniform(1, 9), 2),
            "restarts": 0,
            "oom_kills": 0,
            "status": "Ready" if tier != "db" else "Up",
        }
        values.update(overrides)
        rows.append(values)

    for hour_index in range(HOURS):
        timestamp = START + timedelta(hours=hour_index)

        for service, pods in pod_layout.items():
            for pod in pods:
                cpu_pct = rng.uniform(30, 55)
                if (
                    service == "payments"
                    and datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
                    <= timestamp
                    <= INCIDENT_END
                ):
                    cpu_pct = rng.uniform(65, 70)
                make_row(
                    timestamp,
                    "app",
                    service,
                    pod["node"],
                    pod["pod"],
                    cpu_pct=round(cpu_pct, 2),
                )

        for component, node, _ in broker_topics:
            overrides = {}
            if component == "kafka-broker-2":
                if timestamp == OCT5_BROKER_INCIDENT_START:
                    overrides["memory_pct"] = round(rng.uniform(93, 96), 2)
                elif timestamp == OCT5_BROKER_RESTART_AT:
                    overrides.update(
                        memory_pct=round(rng.uniform(94, 97), 2),
                        restarts=1,
                        oom_kills=1,
                        status="NotReady",
                    )
            make_row(timestamp, "kafka", component, node, component, **overrides)

        for component, node in db_hosts:
            overrides = {}
            if (
                node == "db-host-1"
                and datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
                <= timestamp
                <= INCIDENT_END
            ):
                overrides["io_wait_pct"] = round(rng.uniform(35, 45), 2)
            make_row(timestamp, "db", component, node, **overrides)

    return rows


def generate_changes() -> list[dict]:
    return [
        {
            "timestamp": "2026-10-01T09:00:00Z",
            "change_id": "R2026.10.01",
            "change_type": "app_release",
            "description": "Application release 2026.10.01",
        },
        {
            "timestamp": "2026-10-05T09:00:00Z",
            "change_id": "R2026.10.05",
            "change_type": "app_release",
            "description": "Application release 2026.10.05",
        },
        {
            "timestamp": "2026-10-09T06:00:00Z",
            "change_id": "R2026.10.09",
            "change_type": "app_release",
            "description": "Application release; no immediate degradation observed",
        },
        {
            "timestamp": iso(DB_PATCH_AT),
            "change_id": "DBPATCH-1009",
            "change_type": "db_patch",
            "description": "Production database patch; payments query plan regressed",
        },
    ]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def print_summary(api_rows: list[dict], kafka_rows: list[dict], db_rows: list[dict]) -> None:
    api_incident = [
        row for row in api_rows
        if row["service"] == "payments"
        and API_INCIDENT_START <= datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < API_INCIDENT_END
    ]
    api_before = [
        row for row in api_rows
        if row["service"] == "payments"
        and datetime(2026, 10, 9, 0, tzinfo=timezone.utc)
        <= datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        < INCIDENT_START
    ]
    db_baseline = [
        row["avg_elapsed_ms"] for row in db_rows
        if row["sql_id"] == "PAYQRY01"
        and datetime(2026, 10, 1, tzinfo=timezone.utc)
        <= datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        < datetime(2026, 10, 9, tzinfo=timezone.utc)
    ]
    db_incident = [
        row["avg_elapsed_ms"] for row in db_rows
        if row["sql_id"] == "PAYQRY01"
        and INCIDENT_START
        <= datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        < INCIDENT_END
    ]
    kafka_incident = [
        row for row in kafka_rows
        if row["topic"] == "payment-events"
        and INCIDENT_START + timedelta(hours=2)
        <= datetime.strptime(row["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        < INCIDENT_END
    ]

    api_pass_before = sum(row["passed"] for row in api_before) / len(api_before) * 100
    api_pass_incident = sum(row["passed"] for row in api_incident) / len(api_incident) * 100
    db_baseline_avg = mean(db_baseline)
    db_incident_avg = mean(db_incident)
    peak_lag = max(row["lag"] for row in kafka_incident)
    avg_kafka_error = mean(row["error_rate"] for row in kafka_incident)
    api_p95_before = percentile([row["latency_ms"] for row in api_before], 0.95)
    api_p95_incident = percentile([row["latency_ms"] for row in api_incident], 0.95)

    print("\nDay-9 incident summary (2026-10-09 UTC):")
    print("  06:00 app release R2026.10.09; no immediate degradation.")
    print("  10:00 DBPATCH-1009; PAYQRY01 changes plan at 11:00 for both payments DB users.")
    print(
        f"  11:00–19:00 DB elapsed: {db_baseline_avg:.0f} ms baseline → "
        f"{db_incident_avg:.0f} ms incident ({db_incident_avg / db_baseline_avg:.1f}x), "
        "wait shifts to User I/O."
    )
    print(
        f"  12:00–20:00 payments API: pass rate {api_pass_before:.1f}% → "
        f"{api_pass_incident:.1f}%; p95 latency {api_p95_before:.0f} ms → "
        f"{api_p95_incident:.0f} ms."
    )
    print(
        f"  13:00–19:00 payment-events: peak lag {peak_lag:,} messages; "
        f"average error rate {avg_kafka_error:.2f}%."
    )
    print("  Degradation order: DB plan regression → payments API → Kafka consumer lag.")


def main() -> None:
    rng = random.Random(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    api_rows = generate_api(rng)
    kafka_rows = generate_kafka(rng)
    db_rows = generate_db(rng)
    change_rows = generate_changes()
    infra_rows = generate_infra(random.Random(INFRA_SEED))

    datasets = (
        ("api_test_runs.csv", ("run_id", "timestamp", "release_tag", "service", "endpoint", "method",
                              "status_code", "passed", "latency_ms", "failure_reason"), api_rows),
        ("kafka_metrics.csv", ("timestamp", "topic", "consumer_group", "partition", "lag",
                              "msgs_per_sec", "error_rate"), kafka_rows),
        ("db_metrics.csv", ("timestamp", "db_instance", "db_user", "sql_id", "sql_type",
                            "executions", "avg_elapsed_ms", "cpu_ms", "top_wait_class",
                            "wait_time_pct", "active_sessions", "plan_hash_value"), db_rows),
        ("change_events.csv", ("timestamp", "change_id", "change_type", "description"), change_rows),
        ("infra_metrics.csv", ("timestamp", "tier", "component", "node", "pod", "cpu_pct",
                               "memory_pct", "io_wait_pct", "restarts", "oom_kills",
                               "status"), infra_rows),
    )
    print(
        f"Generated CSVs in {OUT_DIR} (seed={SEED}, infra seed={INFRA_SEED}; "
        f"UTC window={iso(START)} to 2026-10-15T00:00:00Z):"
    )
    for filename, columns, rows in datasets:
        write_csv(filename, columns, rows)
        print(f"  {filename}: {len(rows):,} rows")
    print_summary(api_rows, kafka_rows, db_rows)


if __name__ == "__main__":
    main()

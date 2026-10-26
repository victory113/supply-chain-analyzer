"""Prometheus metrics.

Logs say what happened to one request. Metrics say what is happening to all of
them: how many uploads this hour, how long analyses take, how often the agent
calls each tool. Prometheus scrapes ``/api/v1/metrics`` on an interval and
stores the numbers as time series, which is what makes "is this worse than last
week?" answerable.

Two rules shape everything below.

**Label values must come from a small fixed set.** Prometheus stores one time
series per unique combination of labels, so labelling a request by its raw path
would create a new series for every upload ID that has ever been fetched —
millions of series, and a dead Prometheus. HTTP metrics are therefore labelled
by the *route template* (``/api/v1/uploads/{upload_id}``), never the path.

**Metrics are cheap counters, not an audit log.** They record how much and how
long, never who or what. Anything identifying a user or a dataset stays out.
"""

from __future__ import annotations

# The content type and the generator must agree. `generate_latest` emits the
# classic Prometheus text format; pairing it with the OpenMetrics content type
# would advertise a format whose trailing "# EOF" marker is missing, and a
# strict scraper rejects the payload.
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

# An explicit registry rather than the global default: the default also carries
# process and GC collectors that are registered on import, which makes the
# metric set depend on import order and breaks tests that assert on output.
REGISTRY = CollectorRegistry()

# ── HTTP ──────────────────────────────────────────────────────────────

http_requests_total = Counter(
    "sca_http_requests_total",
    "HTTP requests handled, by route template and outcome.",
    ["method", "route", "status"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "sca_http_request_duration_seconds",
    "Wall-clock time to handle an HTTP request.",
    ["method", "route"],
    # Tuned to this app: most reads are tens of milliseconds, uploads run for
    # seconds, and an agent chat can take ten. The default buckets top out at
    # 10s, which would put every chat request in +Inf and hide the tail.
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

# ── Ingestion ─────────────────────────────────────────────────────────

uploads_total = Counter(
    "sca_uploads_total",
    "CSV uploads accepted.",
    registry=REGISTRY,
)

rows_ingested_total = Counter(
    "sca_rows_ingested_total",
    "Shipment rows parsed and stored.",
    registry=REGISTRY,
)

rows_rejected_total = Counter(
    "sca_rows_rejected_total",
    "Rows skipped because every recognised column was empty.",
    registry=REGISTRY,
)

delays_derived_total = Counter(
    "sca_delays_derived_total",
    "Delays computed from a date pair because the file had no delay column.",
    registry=REGISTRY,
)

# ── Analysis ──────────────────────────────────────────────────────────

analyses_total = Counter(
    "sca_analyses_total",
    "Analyses that reached a terminal state.",
    ["status"],  # completed | failed
    registry=REGISTRY,
)

analysis_duration_seconds = Histogram(
    "sca_analysis_duration_seconds",
    "End-to-end time to compute metrics and generate the narrative.",
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
    registry=REGISTRY,
)

# ── Agent ─────────────────────────────────────────────────────────────

agent_tool_calls_total = Counter(
    "sca_agent_tool_calls_total",
    "Tools the chat agent chose to call.",
    ["tool", "ok"],
    registry=REGISTRY,
)

llm_tokens_total = Counter(
    "sca_llm_tokens_total",
    "Tokens billed by the model API.",
    ["direction"],  # input | output
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """The scrape payload and its content type."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def observe_request(method: str, route: str, status: int, duration_seconds: float) -> None:
    """Record one finished HTTP request."""
    http_requests_total.labels(method=method, route=route, status=str(status)).inc()
    http_request_duration_seconds.labels(method=method, route=route).observe(duration_seconds)


def observe_tokens(input_tokens: int, output_tokens: int) -> None:
    llm_tokens_total.labels(direction="input").inc(input_tokens)
    llm_tokens_total.labels(direction="output").inc(output_tokens)

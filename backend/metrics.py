import time

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
except ImportError:
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    Counter = Histogram = None
    generate_latest = None


if Counter and Histogram:
    REQUEST_COUNT = Counter(
        "studentspend_http_requests_total",
        "Total HTTP requests.",
        ["method", "path", "status"],
    )
    REQUEST_LATENCY = Histogram(
        "studentspend_http_request_duration_seconds",
        "HTTP request latency.",
        ["method", "path"],
    )
    JOB_COUNT = Counter(
        "studentspend_queue_jobs_total",
        "Queue job executions.",
        ["task_name", "status"],
    )
else:
    REQUEST_COUNT = REQUEST_LATENCY = JOB_COUNT = None


def observe_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    if not REQUEST_COUNT or not REQUEST_LATENCY:
        return
    normalized_path = path if path != "/metrics" else "/metrics"
    REQUEST_COUNT.labels(method=method, path=normalized_path, status=str(status_code)).inc()
    REQUEST_LATENCY.labels(method=method, path=normalized_path).observe(duration_seconds)


def observe_job(task_name: str, status: str) -> None:
    if JOB_COUNT:
        JOB_COUNT.labels(task_name=task_name, status=status).inc()


def metrics_response() -> tuple[bytes, str]:
    if generate_latest:
        return generate_latest(), CONTENT_TYPE_LATEST
    fallback = f"# prometheus_client_not_installed {int(time.time())}\n".encode("utf-8")
    return fallback, CONTENT_TYPE_LATEST

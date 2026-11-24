"""A simple load test: many clients asking the API for similar companies at the same time.

Start the API first (`just serve`), then: just load-test

For each level of concurrency (how many clients send requests at once), it sends requests for random active
companies and prints throughput (requests per second), latency percentiles and errors. The client runs on the
same machine as the API, so treat the numbers as a rough guide, not a capacity figure.
"""

import random
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import psycopg

from app.config import DATABASE_URL

API_URL = "http://localhost:8000"
# (clients at once, total requests) for each level
LEVELS = [(1, 500), (10, 1000), (50, 1000), (100, 2000), (500, 2500)]


def one_request(number: str) -> tuple[float, int]:
    """Ask for one company's similar companies. Returns (milliseconds, HTTP status); 0 means no answer at all."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(f"{API_URL}/companies/{number}/similar", timeout=30) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except OSError:
        status = 0
    return (time.perf_counter() - start) * 1000, status


def run_level(numbers: list[str], clients: int, requests: int) -> str:
    """Send `requests` requests from `clients` clients at once; return one table row."""
    chosen = [random.choice(numbers) for _ in range(requests)]
    with ThreadPoolExecutor(max_workers=clients) as pool:
        start = time.perf_counter()
        results = list(pool.map(one_request, chosen))
        seconds = time.perf_counter() - start

    timings = [ms for ms, status in results if status == 200]
    errors = {}
    for _, status in results:
        if status != 200:
            errors[status] = errors.get(status, 0) + 1
    error_text = ", ".join(f"{count} x {status or 'no answer'}" for status, count in errors.items()) or "none"

    if len(timings) < 2:
        return f"| {clients} | {requests / seconds:.0f} | - | - | - | {error_text} |"
    p = statistics.quantiles(timings, n=100)  # p[49] is the 50th percentile, p[94] the 95th, p[98] the 99th
    return f"| {clients} | {requests / seconds:.0f} | {p[49]:.0f} ms | {p[94]:.0f} ms | {p[98]:.0f} ms | {error_text} |"


def main() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute("SELECT registration_number FROM companies WHERE NOT struck_off").fetchall()
    numbers = [row[0] for row in rows]

    print("| Clients at once | Requests/second | p50 | p95 | p99 | Errors |")
    print("|---|---|---|---|---|---|")
    for clients, requests in LEVELS:
        print(run_level(numbers, clients, requests), flush=True)


if __name__ == "__main__":
    main()

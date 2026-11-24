"""Measure how long the API takes to answer, over every active company. Start the API first (`just serve`).

Usage: just latency
"""

import statistics
import time
import urllib.request

import psycopg

from app.config import DATABASE_URL

API_URL = "http://localhost:8000"


def main() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        rows = connection.execute("SELECT registration_number FROM companies WHERE NOT struck_off").fetchall()
    numbers = [row[0] for row in rows]

    timings_ms = []
    for number in numbers:
        start = time.perf_counter()
        with urllib.request.urlopen(f"{API_URL}/companies/{number}/similar") as response:
            response.read()
        timings_ms.append((time.perf_counter() - start) * 1000)

    percentiles = statistics.quantiles(timings_ms, n=100)  # 99 cut points: percentiles[49] is p50, and so on
    print(f"{len(timings_ms)} requests, one at a time")
    print(f"p50 {percentiles[49]:.1f} ms | p95 {percentiles[94]:.1f} ms | p99 {percentiles[98]:.1f} ms")
    print(f"max {max(timings_ms):.1f} ms")


if __name__ == "__main__":
    main()

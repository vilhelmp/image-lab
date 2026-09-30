"""Load test for the Create flow against a running app (fakes only, no keys).

    uv run python scripts/load_test.py --url https://magnusp-image-lab.hf.space
    uv run python scripts/load_test.py --url http://127.0.0.1:7860 --duration 30

The target needs `access.expose_api: true` so the Gradio client may call events; turn it off
again afterwards. When the app asks for a login, set LOAD_TEST_PASSWORD (the workshop password;
never pass it on the command line).

Each worker is one simulated visitor with its own Gradio session and device id. Exit code 1 if any
Create fails or takes longer than --stall-seconds.
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from gradio_client import Client

API_NAME = "/on_create"
IDEAS = (
    "a dragon that loves pancakes",
    "en robot som spelar fotboll",
    "a treehouse on the moon",
    "en katt i en rymddräkt",
    "a castle made of ice cream",
)


@dataclass
class Stats:
    latencies: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    stalls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, seconds: float, error: str | None, stalled: bool) -> None:
        with self.lock:
            if error:
                self.failures.append(error)
            else:
                self.latencies.append(seconds)
            self.stalls += stalled


def one_create(client: Client, device: object) -> tuple[str | None, object]:
    """Returns (error description or None, device id to send next time)."""
    idea = random.choice(IDEAS)
    new_device, status, image = client.predict(idea, device, api_name=API_NAME)
    # Outputs are Gradio updates: a refused Create still returns a truthy dict, without a value.
    if not (isinstance(image, dict) and image.get("value")):
        message = status.get("value") if isinstance(status, dict) else status
        return f"no image: {str(message)[:80]}", new_device
    return None, new_device


def worker(args: argparse.Namespace, deadline: float, stats: Stats) -> None:
    password = os.environ.get("LOAD_TEST_PASSWORD")
    auth = (args.username, password) if password else None
    client = Client(args.url, auth=auth, verbose=False)
    device: object = None
    while time.monotonic() < deadline:
        start = time.monotonic()
        try:
            error, device = one_create(client, device)
        except Exception as exc:  # any failure counts against the run
            error = f"{type(exc).__qualname__}: {str(exc).split(' for url')[0][:120]}"
        elapsed = time.monotonic() - start
        stats.record(elapsed, error, elapsed > args.stall_seconds)
        time.sleep(random.uniform(args.min_think_seconds, args.think_seconds))


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--duration", type=float, default=600, help="seconds")
    parser.add_argument("--think-seconds", type=float, default=30, help="max pause between Creates")
    parser.add_argument(
        "--min-think-seconds", type=float, default=10, help="min pause; keep it above the cooldown"
    )
    parser.add_argument("--username", default="workshop")
    parser.add_argument("--stall-seconds", type=float, default=30)
    args = parser.parse_args()

    stats = Stats()
    deadline = time.monotonic() + args.duration
    print(f"{args.workers} visitors for {args.duration:.0f}s against {args.url}")
    with ThreadPoolExecutor(args.workers) as pool:
        for _ in range(args.workers):
            pool.submit(worker, args, deadline, stats)

    total = len(stats.latencies) + len(stats.failures)
    print(f"creates: {total}  ok: {len(stats.latencies)}  failed: {len(stats.failures)}")
    print(f"stalls (> {args.stall_seconds:.0f}s): {stats.stalls}")
    if stats.latencies:
        print(
            f"latency s: median {statistics.median(stats.latencies):.1f}  "
            f"p95 {percentile(stats.latencies, 0.95):.1f}  max {max(stats.latencies):.1f}"
        )
    for message in sorted(set(stats.failures))[:5]:
        print(f"  {stats.failures.count(message)}x {message[:200]}")
    return 1 if stats.failures or stats.stalls or not total else 0


if __name__ == "__main__":
    sys.exit(main())

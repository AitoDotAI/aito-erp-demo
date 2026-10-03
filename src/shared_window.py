"""Scripts that query shared Aito refuse to run 08:00-10:00 Helsinki.

That is the shared environment's batch window, when other teams' jobs
run. The rule was kept by habit, and habit failed twice: a scheduled
check and a hand-run verification both landed inside it. So every
script that sends queries to shared Aito calls `refuse_in_batch_window`
first and exits with a clear message.

The deployed demo is NOT covered: it serves visitors around the clock
and its load is theirs. This guards evals, loads, sweeps and probes —
work someone chose to start.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

HELSINKI = ZoneInfo("Europe/Helsinki")
WINDOW_START_HOUR, WINDOW_END_HOUR = 8, 10


def in_batch_window(now: datetime | None = None) -> bool:
    local = (now or datetime.now(HELSINKI)).astimezone(HELSINKI)
    return WINDOW_START_HOUR <= local.hour < WINDOW_END_HOUR


def refuse_in_batch_window(what: str, now: datetime | None = None) -> None:
    """Exit before any query is sent if it is 08:00-10:00 Helsinki."""
    if in_batch_window(now):
        local = (now or datetime.now(HELSINKI)).astimezone(HELSINKI)
        raise SystemExit(
            f"{what}: refused at {local:%H:%M} Helsinki — 08:00-10:00 is the "
            f"shared Aito batch window. Run it after 10:00.")


if __name__ == "__main__":
    # `python -m src.shared_window <what>` — for shell commands in ./do.
    import sys
    refuse_in_batch_window(sys.argv[1] if len(sys.argv) > 1 else "this command")

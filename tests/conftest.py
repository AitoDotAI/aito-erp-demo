"""Live tests do not query shared Aito in its 08:00-10:00 batch window.

Scripts call `refuse_in_batch_window` in main(); the test suite has no
main. On 2026-10-03 two full runs at 08:0x sent the live booktests'
~150 predicts into the window — the second AFTER a function-scoped
guard was added, because the booktest ranks its sample in a
MODULE-scoped fixture, which runs before any function-scoped one.

So the guard is installed when this file is imported, before any
fixture of any scope: the client's two send seams skip the test instead
of sending. Mocked clients never reach them, so only tests that would
really query Aito are affected, and the skip says why.
"""

import pytest

from src import aito_client
from src.shared_window import in_batch_window


def _refuse(*_args, **_kwargs):
    pytest.skip("live Aito query refused: 08:00-10:00 Helsinki is the shared batch window")


def install_batch_window_guard() -> bool:
    """Replace the send seams if it is the batch window. Returns whether it did."""
    if not in_batch_window():
        return False
    aito_client._TimedAitoClientV2.request = _refuse
    aito_client.AitoClient._request = _refuse
    return True


install_batch_window_guard()

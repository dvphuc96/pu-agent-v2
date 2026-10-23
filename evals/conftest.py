import sys
from pathlib import Path

import pytest

# evals/ sits next to pu/, not inside it — make both importable when
# running `pytest evals` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _reset_session_principal():
    """A test may authenticate a session on a contextvar. Clear it after each test."""
    from pu.identity.session import reset_session_principal
    from pu.identity.worker_job import reset_worker_grant

    reset_session_principal()
    reset_worker_grant()
    yield
    reset_session_principal()
    reset_worker_grant()


@pytest.fixture(autouse=True)
def _reset_bound_harness():
    """A test may bind a read harness on a contextvar. Clear it around each test."""
    from pu.harness.gateway import clear_bound_harness

    clear_bound_harness()
    yield
    clear_bound_harness()

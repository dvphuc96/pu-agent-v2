import sys
from pathlib import Path

import pytest

# evals/ sits next to pu/, not inside it — make both importable when
# running `pytest evals` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _reset_principal_seam():
    """Phase 1 tests attach a principal on a contextvar. Clear it after each test."""
    from pu.identity.seam import reset_attached_principal

    reset_attached_principal()
    yield
    reset_attached_principal()

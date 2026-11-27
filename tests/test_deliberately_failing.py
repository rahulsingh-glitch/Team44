"""A deliberately-failing test, skipped by default.

Purpose: prove the CI pipeline turns RED on a real failure. Remove the
`@pytest.mark.skip` decorator (or run `pytest -m "" --no-header`) and CI fails.
Keep it skipped on main so the board stays green.
"""

import pytest


@pytest.mark.skip(reason="intentionally failing; unskip to prove CI goes red")
def test_ci_goes_red_when_unskipped():
    assert 1 == 2, "if you see this fail in CI, the red-path works as designed"

"""The same result normalization examples are consumed by native command tests."""
import json
from pathlib import Path

import pytest

from clo3d_mcp.contracts import FAILURE_FLAGS, export_paths

CONTRACTS = json.loads((Path(__file__).parent / "fixtures/result_contracts.json").read_text())


@pytest.mark.parametrize("case", CONTRACTS["export_paths"])
def test_shared_export_paths(case):
    if case.get("error"):
        with pytest.raises(ValueError):
            export_paths(case["input"])
    else:
        assert export_paths(case["input"]) == case["output"]


def test_shared_failure_flags():
    assert FAILURE_FLAGS == set(CONTRACTS["failure_flags"])

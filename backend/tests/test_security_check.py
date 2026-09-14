from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "deployment" / "scripts" / "check-sensitive-files.py"
SPEC = importlib.util.spec_from_file_location("check_sensitive_files", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    "filename",
    [
        ".env",
        "deployment/.env.production",
        "secrets/robot-token.txt",
        "certs/client.key",
        "state/control.db",
        ".ssh/id_ed25519",
        ".ssh/authorized_keys",
    ],
)
def test_sensitive_paths_are_rejected(filename: str) -> None:
    assert MODULE.is_sensitive(filename)


@pytest.mark.parametrize(
    "filename",
    [
        ".env.example",
        "deployment/env.example",
        "deployment/robots.ros.example.yaml",
        "backend/tests/test_auth.py",
    ],
)
def test_sanitized_examples_and_source_files_are_allowed(filename: str) -> None:
    assert not MODULE.is_sensitive(filename)

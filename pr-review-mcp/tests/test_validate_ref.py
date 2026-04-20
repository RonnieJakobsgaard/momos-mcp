"""Tests for _validate_ref — git ref validation and injection guard."""
import subprocess
import pytest
from unittest.mock import patch, MagicMock
import server


def _mock_run(returncode: int):
    mock = MagicMock()
    mock.returncode = returncode
    return mock


def test_valid_ref_returns_none():
    with patch("server.subprocess.run", return_value=_mock_run(0)):
        assert server._validate_ref("main") is None


def test_invalid_ref_returns_error_string():
    with patch("server.subprocess.run", return_value=_mock_run(1)):
        result = server._validate_ref("nonexistent-branch")
        assert isinstance(result, str)
        assert "invalid ref" in result


def test_error_string_includes_ref_name():
    with patch("server.subprocess.run", return_value=_mock_run(1)):
        result = server._validate_ref("bad-ref")
        assert "bad-ref" in result


def test_injection_attempt_passed_as_list_arg():
    """Verify the ref is passed as a list element, not shell-interpolated."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _mock_run(1)

    with patch("server.subprocess.run", side_effect=fake_run):
        server._validate_ref("main; rm -rf /")

    assert captured["cmd"] == ["git", "rev-parse", "--verify", "main; rm -rf /"]


def test_shell_false_by_default():
    """subprocess.run must not use shell=True."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["kwargs"] = kwargs
        return _mock_run(0)

    with patch("server.subprocess.run", side_effect=fake_run):
        server._validate_ref("main")

    assert not captured["kwargs"].get("shell", False)

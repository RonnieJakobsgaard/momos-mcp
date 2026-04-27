"""Windows-specific compatibility tests.

Guards against regressions in the Windows fixes:
  - stdin=DEVNULL on all subprocess calls (prevents stdin pipe inheritance)
  - WindowsSelectorEventLoopPolicy in main() (fixes IocpProactor/stdio issues)

The stdin tests run on all platforms; the asyncio policy test is Windows-only.
"""
import asyncio
import subprocess
import sys
import pytest
from unittest.mock import MagicMock, patch


def _ok(stdout="", stderr=""):
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    m.stderr = stderr
    return m


def _fail(stderr="error"):
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# stdin=DEVNULL regression guards
# ---------------------------------------------------------------------------

class TestStdinDevnull:
    """Every subprocess.run call must include stdin=subprocess.DEVNULL.

    On Windows, the MCP server communicates over stdio. If subprocess.run
    inherits the parent stdin, child processes block waiting on the MCP pipe.
    """

    def test_validate_ref(self):
        captured = []
        with patch("momos_mcp._git.subprocess.run",
                   side_effect=lambda cmd, **kw: (captured.append(kw), _ok())[1]):
            from momos_mcp._git import _validate_ref
            _validate_ref("main")
        assert captured, "subprocess.run was not called"
        assert all(kw.get("stdin") == subprocess.DEVNULL for kw in captured)

    def test_approve_and_commit(self):
        from momos_mcp.state import state
        from momos_mcp import server

        state.reset()
        captured = []

        def fake_run(cmd, **kw):
            captured.append({"cmd": list(cmd), "stdin": kw.get("stdin")})
            if "add" in cmd:
                return _ok()
            return _ok(stdout="[main abc1234] msg\n")

        with patch("momos_mcp.server.subprocess.run", side_effect=fake_run), \
             patch("momos_mcp.server._persist_review"):
            server.approve_and_commit("test commit")

        assert len(captured) == 2, f"Expected 2 subprocess calls, got {len(captured)}: {captured}"
        assert all(c["stdin"] == subprocess.DEVNULL for c in captured), (
            f"Not all calls had stdin=DEVNULL: {captured}"
        )

    def test_create_review_git_diff(self):
        from momos_mcp import server
        captured = []

        def fake_run(cmd, **kw):
            captured.append({"cmd": list(cmd), "stdin": kw.get("stdin")})
            return _fail("no repo")

        # Patch _validate_ref directly so its subprocess call doesn't conflict
        # with the subprocess.run patch below (both share the same module object).
        with patch("momos_mcp.server._validate_ref", return_value=None), \
             patch("momos_mcp.server.subprocess.run", side_effect=fake_run):
            server.create_review()

        diff_calls = [c for c in captured if "diff" in c["cmd"]]
        assert diff_calls, "git diff was not called"
        assert all(c["stdin"] == subprocess.DEVNULL for c in diff_calls)


# ---------------------------------------------------------------------------
# Windows asyncio event loop policy
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only: tests actual policy behavior")
def test_main_sets_windows_selector_policy():
    """main() must apply WindowsSelectorEventLoopPolicy before starting the server."""
    from momos_mcp import server

    asyncio.set_event_loop_policy(None)  # reset to platform default

    with patch("momos_mcp.server._resolve_port", return_value=19998), \
         patch("momos_mcp.server.threading.Thread"), \
         patch("momos_mcp.server._start_hot_reload_watcher"), \
         patch("momos_mcp.server.mcp.run"):
        server.main()

    assert isinstance(
        asyncio.get_event_loop_policy(),
        asyncio.WindowsSelectorEventLoopPolicy,
    )

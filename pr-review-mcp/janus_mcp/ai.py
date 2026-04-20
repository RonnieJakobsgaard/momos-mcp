import json
import os
import sys

try:
    import anthropic as _anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

from janus_mcp.state import state


_COMMIT_MSG_PROMPT = """\
Generate a conventional commit message for the git diff below.
Format: <type>(<optional scope>): <short imperative subject> (max 72 chars)

Types: feat, fix, refactor, style, test, docs, chore.
Output only the commit message — no explanation, no backticks, no blank lines.
"""

_AI_REVIEW_PROMPT = """\
You are a code reviewer. Analyze the git diff below and identify specific issues: bugs, logic errors, security problems, unclear variable names, or missing edge-case handling. Skip style nits and formatting.

For each issue, respond with a JSON object on its own line (NDJSON), with these fields:
  file    — the filename (must match exactly)
  line    — the new-file line number closest to the issue (integer)
  comment — a concise, actionable description of the issue (1–3 sentences)

If there are no issues, output an empty line. Do not include any prose outside the JSON lines.

Diff:
"""


def _run_ai_pre_review(diff_text: str) -> None:
    """Send the diff to Claude and inject any issues as AI-sourced comments."""
    if not _HAS_ANTHROPIC:
        print("WARNING: anthropic package not installed, skipping AI pre-review", file=sys.stderr, flush=True)
        return
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("WARNING: ANTHROPIC_API_KEY not set, skipping AI pre-review", file=sys.stderr, flush=True)
        return
    try:
        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": _AI_REVIEW_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": [
                {
                    "type": "text",
                    "text": diff_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]}],
        )
        text = response.content[0].text if response.content else ""
        injected = 0
        for raw_line in text.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
                file = str(obj.get("file", "")).strip()
                line = int(obj.get("line", 0))
                comment = str(obj.get("comment", "")).strip()
                if file and comment:
                    state.add_comment(file, line, comment, source="ai")
                    injected += 1
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
        print(f"AI pre-review: injected {injected} comment(s)", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"WARNING: AI pre-review failed: {e}", file=sys.stderr, flush=True)


def _suggest_commit_message(diff_text: str) -> str | None:
    """Return a suggested conventional commit message, or None on failure."""
    if not _HAS_ANTHROPIC:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        client = _anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=128,
            system=[{
                "type": "text",
                "text": _COMMIT_MSG_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": [
                {
                    "type": "text",
                    "text": diff_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]}],
        )
        text = response.content[0].text.strip() if response.content else ""
        return text or None
    except Exception as e:
        print(f"WARNING: commit message suggestion failed: {e}", file=sys.stderr, flush=True)
        return None

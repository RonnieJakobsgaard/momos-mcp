# momos-mcp

![momos-mcp](assets/readme-banner.png)

A local MCP server that brings an interactive, browser-based PR review loop to Claude Code.

Instead of committing blindly, Claude opens a GitHub-style diff UI in your browser after
making changes. You leave inline comments on specific lines, click "Request Changes" or
"Approve", and Claude responds — fixing each comment, marking it resolved, and looping
until you're satisfied. Only then does it commit.

## How it works

1. Claude makes code changes and calls `create_review()` → browser opens with the diff
2. You add inline comments on any line, then click **Request Changes** or **Approve**
3. If changes were requested, Claude fixes each comment, calls `mark_comment_resolved()`, and opens a fresh review
4. Once you click **Approve**, Claude calls `approve_and_commit()` and the commit is made

## Prerequisites

- Python 3.10+
- Claude Code CLI

## Setup

```bash
cd momos-mcp
bash setup.sh
```

`setup.sh` creates a `.venv`, installs `mcp`, and prints the exact config snippet to add.

## Register with Claude Code

Add the snippet printed by `setup.sh` to your MCP config. You can use either:

- **Global** (`~/.claude.json` under `mcpServers`) — available in all projects
- **Per-project** (`.claude/settings.json` under `mcpServers`) — only in that project

Example (paths filled in by `setup.sh`):

```json
{
  "mcpServers": {
    "momos": {
      "command": "/path/to/momos-mcp/.venv/bin/momos-mcp"
    }
  }
}
```

Verify it's registered: run `/mcp` in Claude Code and confirm `momos` appears.

## CLAUDE.md setup

Paste this into your project's `CLAUDE.md` (or your global `~/.claude/CLAUDE.md`):

~~~markdown
## PR Review with momos

All changes must happen on a short-lived branch — never commit directly to main.

### Branch discipline

Before writing any code, create a branch:

```
git checkout -b work/<short-name>
```

Use `work/` prefix and a short kebab-case name describing the change (e.g. `work/fix-auth`, `work/add-dark-mode`).

### Review loop (momos MCP server)

When the `momos` MCP server is available (verify with `/mcp`):

1. Make changes on the `work/` branch
2. Call `create_review()` — browser opens with the diff
3. Call `wait_for_approval()` and block until the user responds
4. If status is `"changes_requested"`: fix each comment, call `mark_comment_resolved(comment_id)` per fix, then loop back to step 2
5. Once status is `"approved"`: call `approve_and_commit(message)` — this commits and merges
6. Delete the work branch after merge

Never merge without going through the review loop.

### Fallback (momos not available)

If the MCP server is not connected:

1. Show a `git diff main...HEAD` summary
2. Discuss changes with the user
3. Merge and delete the branch only after explicit approval
~~~

## MCP Tools

### Review loop

| Tool | Description |
|------|-------------|
| `create_review(base_ref="main", head_ref="HEAD", title="", ai_pre_review=False)` | Diffs against base ref, opens browser UI |
| `wait_for_approval(timeout_seconds=86400)` | Blocks until approved or changes requested |
| `get_comments()` | Returns current comments and status |
| `mark_comment_resolved(comment_id)` | Marks a comment resolved after fixing it |
| `approve_and_commit(message)` | Commits — only works when all comments resolved |

### Per-file approval

| Tool | Description |
|------|-------------|
| `approve_file(filename)` | Approves a single file; auto-approves the whole review once all files are approved |

### Review history

| Tool | Description |
|------|-------------|
| `list_reviews()` | Returns summaries of past review sessions, newest first |
| `get_review(commit_hash)` | Returns the full review record for a specific commit |

## AI pre-review

Pass `ai_pre_review=True` to `create_review()` to have Claude analyze the diff before you open the browser. AI comments appear inline with a purple **🤖 AI** badge and can be dismissed individually.

```python
create_review(ai_pre_review=True)
```

**Requirements:**
- `anthropic` package: `pip install momos-mcp[ai]` (or `pip install anthropic`)
- `ANTHROPIC_API_KEY` environment variable set

**Model:** `claude-opus-4-7` — looks for bugs, logic errors, security issues, and missing edge-case handling. Skips style/formatting nits.

**Cost estimate:** ~$0.01–0.05 per review depending on diff size (Opus 4.7 pricing with prompt caching).

**Setup:**

```bash
pip install "momos-mcp[ai]"
export ANTHROPIC_API_KEY=sk-ant-...
```

If `ANTHROPIC_API_KEY` is not set or `anthropic` is not installed, `ai_pre_review=True` is silently skipped — the review opens normally without AI comments.

## Manual smoke test

After setup, run through this checklist to confirm everything works:

- [ ] Run `setup.sh` and confirm it prints a config snippet with absolute paths
- [ ] Add the snippet to `~/.claude.json` and restart Claude Code
- [ ] Run `/mcp` — `momos` should appear as connected
- [ ] Ask Claude to make a small change, then call `create_review()` — browser opens showing the diff
- [ ] Click a line in the diff — a comment form appears anchored to that line
- [ ] Submit a comment — it appears in the sidebar and inline below the line
- [ ] Scroll a wide file horizontally — line numbers stay fixed on the left
- [ ] Set status to "changes_requested" — `wait_for_approval()` returns with the comment
- [ ] Claude fixes the comment and calls `mark_comment_resolved()` — comment shows resolved badge
- [ ] Approve — `wait_for_approval()` returns `"approved"` and `approve_and_commit()` creates the commit
- [ ] Run `--resume` and confirm the MCP server reconnects automatically

## Manual testing (curl)

```bash
# See current state
curl http://localhost:<port>/comments

# Add a comment
curl -X POST http://localhost:<port>/comments \
  -H 'Content-Type: application/json' \
  -d '{"file":"foo.py","line":10,"comment":"This needs a null check"}'

# Approve
curl -X POST http://localhost:<port>/status \
  -H 'Content-Type: application/json' \
  -d '{"status":"approved"}'
```

The port is printed by `create_review()` and shown in the browser URL bar.

## Troubleshooting

**Browser doesn't open automatically**
Run `create_review()` and open the URL it returns manually.

**Port conflict**
The server picks a random free port on startup — conflicts are unlikely. If `server.py`
fails to start, check that Python can bind to localhost (firewall / WSL network issues).

**"No changes found" error**
Make sure you have uncommitted changes or commits ahead of your base branch. Try
`git diff main` in the terminal to confirm there's a diff.

**"not a git repository" error**
Run Claude Code from inside a git repo, or pass the correct `base_branch` to
`create_review()`.

**MCP server not showing up in `/mcp`**
Confirm the `command` path in your config points to `.venv/bin/python` (not system Python)
and the `args` path to `server.py` is absolute and correct.

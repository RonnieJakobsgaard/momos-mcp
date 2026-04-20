# pr-review-mcp

A local MCP server that gives Claude Code an interactive browser-based PR review loop.

After Claude makes code changes, it opens a browser UI showing the diff, waits for your
inline comments, fixes them, and loops until you approve.

## Prerequisites

- Python 3.10+
- Claude Code CLI

## Setup

```bash
cd pr-review-mcp
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
    "pr-review": {
      "command": "/path/to/pr-review-mcp/.venv/bin/python",
      "args": ["/path/to/pr-review-mcp/server.py"]
    }
  }
}
```

Verify it's registered: run `/mcp` in Claude Code and confirm `pr-review` appears.

## Add to your project's CLAUDE.md

Paste this into your project's `CLAUDE.md` so Claude uses the review loop automatically:

```
## Code Review Workflow

After making any significant code changes:
1. Call `create_review()` to open the browser review UI
2. Call `wait_for_approval()` immediately after — do not proceed until it returns
3. If status is "changes_requested":
   - Fix each comment
   - Call `mark_comment_resolved(comment_id)` after fixing each one
   - Call `create_review()` again, then `wait_for_approval()` — repeat until approved
4. Once approved, call `approve_and_commit(message)` to commit
```

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

## Manual smoke test

After setup, run through this checklist to confirm everything works:

- [ ] Run `setup.sh` and confirm it prints a config snippet with absolute paths
- [ ] Add the snippet to `~/.claude.json` and restart Claude Code
- [ ] Run `/mcp` — `pr-review` should appear as connected
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

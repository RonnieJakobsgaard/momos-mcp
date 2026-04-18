# git-pr-mcp-server

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

## Getting started

```bash
cd pr-review-mcp
bash setup.sh
```

Follow the printed instructions to register the MCP server with Claude Code, then add the
CLAUDE.md workflow snippet to any project where you want the review loop active.

See [`pr-review-mcp/README.md`](pr-review-mcp/README.md) for full setup and usage details.


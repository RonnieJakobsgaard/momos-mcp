#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Creating virtual environment..."
python3 -m venv .venv

echo "Installing janus-mcp..."
.venv/bin/pip install --quiet -e .

ENTRY="$SCRIPT_DIR/.venv/bin/janus-mcp"

echo ""
echo "Setup complete!"
echo ""
echo "Add the following to your Claude Code MCP config (~/.claude.json under 'mcpServers'"
echo "for global, or .claude/settings.json under 'mcpServers' for per-project):"
echo ""
cat <<EOF
{
  "mcpServers": {
    "janus": {
      "command": "$ENTRY"
    }
  }
}
EOF
echo ""
echo "Once published to PyPI, you can skip setup.sh entirely and use:"
echo ""
cat <<'EOF'
{
  "mcpServers": {
    "janus": {
      "command": "uvx",
      "args": ["janus-mcp"]
    }
  }
}
EOF

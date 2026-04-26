#!/usr/bin/env pwsh
#Requires -Version 5.1
<#
.SYNOPSIS
    Installs momos-mcp and registers it in Claude Code global settings.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- Check Python ---
$python = $null
foreach ($cmd in @('python3', 'python')) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -match '^(\d+)\.(\d+)$') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $python = $cmd
                break
            }
        }
    }
}

if (-not $python) {
    Write-Error "Python 3.10+ not found. Install from https://python.org and ensure it is on PATH."
    exit 1
}

Write-Host "Using Python: $python ($ver)"

# --- Create venv ---
$venvDir = Join-Path $ScriptDir '.venv'
if (-not (Test-Path $venvDir)) {
    Write-Host "Creating virtual environment..."
    & $python -m venv $venvDir
} else {
    Write-Host "Virtual environment already exists, skipping creation."
}

# --- Install package ---
$pip = Join-Path $venvDir 'Scripts\pip.exe'
if (-not (Test-Path $pip)) {
    # Fallback for non-Windows pwsh (e.g. WSL calling pwsh)
    $pip = Join-Path $venvDir 'bin/pip'
}

Write-Host "Installing momos-mcp..."
# Kill any running instance so pip can overwrite the .exe
Get-Process -Name 'momos-mcp' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
& $pip install --quiet -e $ScriptDir
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed (exit $LASTEXITCODE)."
    exit 1
}

$entry = Join-Path $venvDir 'Scripts\momos-mcp.exe'
if (-not (Test-Path $entry)) {
    $entry = Join-Path $venvDir 'bin/momos-mcp'
}

# Escape backslashes for JSON
$entryJson = $entry -replace '\\', '\\'

Write-Host ""
Write-Host "Installation complete!"
Write-Host ""
Write-Host "To register the MCP server, run this in Claude Code:"
Write-Host ""
Write-Host "  claude mcp add -s user momos `"$entry`""
Write-Host ""
Write-Host "Or manually add the following to the 'mcpServers' section of"
Write-Host "~/.claude/settings.json:"
Write-Host ""
Write-Host "  `"momos`": {"
Write-Host "    `"type`": `"stdio`","
Write-Host "    `"command`": `"$entryJson`","
Write-Host "    `"env`": {}"
Write-Host "  }"
Write-Host ""

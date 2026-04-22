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
& $pip install --quiet -e $ScriptDir

$entry = Join-Path $venvDir 'Scripts\momos-mcp.exe'
if (-not (Test-Path $entry)) {
    $entry = Join-Path $venvDir 'bin/momos-mcp'
}

# --- Patch ~/.claude/settings.json ---
$settingsPath = Join-Path $HOME '.claude\settings.json'
if ($IsLinux -or $IsMacOS) {
    $settingsPath = Join-Path $HOME '.claude/settings.json'
}

$mcpEntry = @{
    command = $entry
}

if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
} else {
    $settings = [PSCustomObject]@{}
}

# Ensure mcpServers key exists
if (-not ($settings.PSObject.Properties.Name -contains 'mcpServers')) {
    $settings | Add-Member -MemberType NoteProperty -Name 'mcpServers' -Value ([PSCustomObject]@{})
}

# Idempotent: only add if not already present
if (-not ($settings.mcpServers.PSObject.Properties.Name -contains 'momos')) {
    $settings.mcpServers | Add-Member -MemberType NoteProperty -Name 'momos' -Value $mcpEntry
    $settings | ConvertTo-Json -Depth 10 | Set-Content $settingsPath -Encoding UTF8
    Write-Host "Registered 'momos' MCP server in $settingsPath"
} else {
    Write-Host "'momos' MCP server already registered in $settingsPath - skipping."
}

Write-Host ""
Write-Host "Setup complete! Restart Claude Code to load the MCP server."

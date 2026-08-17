[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$venv = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path -LiteralPath $venv)) {
    python -m venv $venv
}

$python = Join-Path $venv "Scripts\python.exe"
& $python -m pip install --disable-pip-version-check --requirement (Join-Path $PSScriptRoot "requirements.lock")
& $python -m pip install --disable-pip-version-check --no-deps --editable $PSScriptRoot
Write-Host "KnowledgeVault Automation installed."
Write-Host "Run: .\vaultctl.ps1 doctor"

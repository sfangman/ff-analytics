# Pull ESPN data and rebuild output/site/index.html
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

uv run --env-file .env metrics.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run dashboard.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

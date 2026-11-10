# Download all raw training datasets (public zips + Roboflow when key is set).
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
$py = (Get-Command py -ErrorAction SilentlyContinue)
if (-not $py) { throw "Python launcher 'py' not found" }

& py -3.12 training/scripts/download_public_zips.py
& py -3.12 training/scripts/check_roboflow_key.py
if ($LASTEXITCODE -ne 0) {
  Write-Host "Skipping Roboflow packs until ROBOFLOW_API_KEY is set in env or .env"
  exit 0
}
& py -3.12 -m pip install "roboflow>=1.1.0" -q
& py -3.12 training/scripts/download_roboflow_raw.py

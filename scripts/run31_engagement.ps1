# Run 31: 5 recent VODs + Die For You + engagement captions (A+B+C).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Videos = @(
  "D:\Videos\Valorant\Valorant 2026.10.24 - 18.04.52.27.DVR.mp4",
  "D:\Videos\Valorant\Valorant 2026.10.23 - 23.07.34.24.DVR.mp4",
  "D:\Videos\Valorant\Valorant 2026.10.23 - 22.55.57.23.DVR.mp4",
  "D:\Videos\Valorant\Valorant 2026.10.23 - 22.53.05.22.DVR.mp4",
  "D:\Videos\Valorant\Valorant 2026.10.23 - 22.23.24.21.DVR.mp4"
)
$Music = "C:\Users\aasid\Music\Die For You ft. Grabbitz  Official Music Video  VALORANT Champions 2021.mp3"
$Out = Join-Path $Root "artifacts\run31"

foreach ($v in $Videos) {
  if (-not (Test-Path $v)) { throw "Missing video: $v" }
}
if (-not (Test-Path $Music)) { throw "Missing music: $Music" }

$PyCandidates = @(
  "$env:USERPROFILE\.conda\envs\valorant-montage\python.exe",
  "$env:LOCALAPPDATA\anaconda3\envs\valorant-montage\python.exe",
  "$env:USERPROFILE\miniconda3\envs\valorant-montage\python.exe"
)
$Python = $PyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) {
  throw "valorant-montage conda env python not found. Recreate it before rendering."
}

Write-Host "Python: $Python"
Write-Host "Out: $Out"
& $Python scripts\run_local_pipeline.py --video @Videos --music $Music --out $Out --config config\default.yaml
exit $LASTEXITCODE

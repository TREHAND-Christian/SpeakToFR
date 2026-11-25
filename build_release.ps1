Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-ExePath {
    param([string]$Path)
    if (Test-Path $Path) { return (Resolve-Path $Path).Path }
    return $null
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Resolve-ExePath "$root\.venv\Scripts\python.exe"
if (-not $python) {
    throw "Python du venv introuvable (.venv\Scripts\python.exe)."
}

Write-Host "== PyInstaller =="
# "python -m PyInstaller" plutot que pyinstaller.exe : le lanceur du venv peut pointer vers un ancien dossier
& $python -m PyInstaller --noconfirm ".\SpeakToFR.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller a echoue (code $LASTEXITCODE)."
}

$iscc = Resolve-ExePath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not $iscc) {
    $iscc = Resolve-ExePath "C:\Program Files\Inno Setup 6\ISCC.exe"
}
if (-not $iscc) {
    throw "ISCC introuvable. Installe Inno Setup 6."
}

Write-Host "== Inno Setup =="
& $iscc ".\SetupSpeakToFR.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup a echoue (code $LASTEXITCODE)."
}

Write-Host "OK: exe dans .\dist\SpeakToFR.exe"
Write-Host "OK: setup dans .\Output\SetupSpeakToFR.exe"

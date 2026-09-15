[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$frontendRoot = Join-Path $repoRoot "frontend"
$backendRoot = Join-Path $repoRoot "backend"
$buildRoot = Join-Path $repoRoot "build\windows-portable"
$venvRoot = Join-Path $buildRoot "venv"
$stageRoot = Join-Path $buildRoot "stage"
$pyinstallerWork = Join-Path $buildRoot "pyinstaller"
$distRoot = Join-Path $repoRoot "dist"
$portableRoot = Join-Path $distRoot "DatasetManager"
$zipPath = Join-Path $distRoot "DatasetManager-windows-x64-portable.zip"

if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw "构建必须在 Windows x64 系统上的 64 位 PowerShell 中运行。"
}

New-Item -ItemType Directory -Force -Path $buildRoot, $stageRoot, $distRoot | Out-Null

Push-Location $frontendRoot
try {
    npm ci
    npm run build
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $venvRoot "Scripts\python.exe"))) {
    & $Python -m venv $venvRoot
}
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --disable-pip-version-check "$backendRoot" "pyinstaller>=6.10,<7"

if (-not $SkipTests) {
    & $venvPython -m pip install --disable-pip-version-check pytest
    Push-Location $backendRoot
    try {
        & $venvPython -m pytest -q
    } finally {
        Pop-Location
    }
}

$env:DATASET_MANAGER_PORTABLE_FRONTEND = (Resolve-Path (Join-Path $frontendRoot "dist")).Path
& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $distRoot `
    --workpath $pyinstallerWork `
    (Join-Path $PSScriptRoot "dataset-manager.spec")

Copy-Item -Force (Join-Path $PSScriptRoot "使用说明.txt") (Join-Path $portableRoot "使用说明.txt")
if (Test-Path (Join-Path $repoRoot "LICENSE")) {
    Copy-Item -Force (Join-Path $repoRoot "LICENSE") (Join-Path $portableRoot "LICENSE")
}

Compress-Archive -Force -Path $portableRoot -DestinationPath $zipPath
$zipHash = (Get-FileHash -Algorithm SHA256 $zipPath).Hash
[IO.File]::WriteAllText(
    "$zipPath.sha256.txt",
    "$zipHash *$(Split-Path -Leaf $zipPath)`r`n",
    [Text.Encoding]::ASCII
)
Write-Host "便携版构建完成：$zipPath"
Write-Host "SHA-256：$zipHash"

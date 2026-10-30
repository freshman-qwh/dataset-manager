[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipTests,
    [string]$OutputName = "DatasetManager-windows-x64-portable.zip"
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
if ($OutputName -notmatch '^[A-Za-z0-9._-]+\.zip$') { throw "输出名必须是简单 ZIP 文件名。" }
$zipPath = Join-Path $distRoot $OutputName

if (-not [Environment]::Is64BitOperatingSystem -or -not [Environment]::Is64BitProcess) {
    throw "构建必须在 Windows x64 系统上的 64 位 PowerShell 中运行。"
}

New-Item -ItemType Directory -Force -Path $buildRoot, $stageRoot, $distRoot | Out-Null

Push-Location $frontendRoot
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败。" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端构建失败。" }
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $venvRoot "Scripts\python.exe"))) {
    & $Python -m venv $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "创建构建环境失败。" }
}
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
& $venvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "更新构建依赖失败。" }
& $venvPython -m pip install --disable-pip-version-check "$backendRoot" "pyinstaller>=6.10,<7"
if ($LASTEXITCODE -ne 0) { throw "安装打包依赖失败。" }

if (-not $SkipTests) {
    & $venvPython -m pip install --disable-pip-version-check pytest
    if ($LASTEXITCODE -ne 0) { throw "安装验证工具失败。" }
    Push-Location $backendRoot
    try {
        & $venvPython -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "后端测试失败，停止打包。" }
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
if ($LASTEXITCODE -ne 0) { throw "便携版打包失败。" }

Copy-Item -Force (Join-Path $PSScriptRoot "使用说明.txt") (Join-Path $portableRoot "使用说明.txt")
if (Test-Path (Join-Path $repoRoot "LICENSE")) {
    Copy-Item -Force (Join-Path $repoRoot "LICENSE") (Join-Path $portableRoot "LICENSE")
}

$sourceCommit = (& git -C $repoRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw "无法记录源码提交。" }
$trackedChanges = & git -C $repoRoot status --porcelain --untracked-files=no
$manifest = [ordered]@{
    product = "Dataset Manager"
    channel = "industrial-trial"
    source_commit = $sourceCommit
    tracked_changes_present = [bool]$trackedChanges
    built_at_utc = [DateTime]::UtcNow.ToString("o")
    tests_run_in_build = (-not $SkipTests)
    protocol = "image-level anomaly; capture/hash isolation; independent train/val/test"
    reader = "anomalib==2.7.0; separate environment"
    clean_windows_acceptance = "pending"
    real_user_acceptance = "pending"
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $portableRoot "build-manifest.json")
Copy-Item (Join-Path $repoRoot "docs\industrial-trial-guide.md") (Join-Path $portableRoot "工业试用指南.md") -Force
Compress-Archive -Force -Path $portableRoot -DestinationPath $zipPath
$zipHash = (Get-FileHash -Algorithm SHA256 $zipPath).Hash
[IO.File]::WriteAllText(
    "$zipPath.sha256.txt",
    "$zipHash *$(Split-Path -Leaf $zipPath)`r`n",
    [Text.Encoding]::ASCII
)
Write-Host "便携版构建完成：$zipPath"
Write-Host "SHA-256：$zipHash"

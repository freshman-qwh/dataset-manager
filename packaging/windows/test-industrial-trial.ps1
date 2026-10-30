[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ZipPath,
    [string]$ReaderPython = "",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$acceptanceRoot = Join-Path $repoRoot "output\acceptance\工业便携验收 $runId"
$expanded = Join-Path $acceptanceRoot "程序 中文路径"
$dataRoot = Join-Path $acceptanceRoot "应用数据 中文路径"
New-Item -ItemType Directory -Force -Path $acceptanceRoot | Out-Null
Expand-Archive -LiteralPath (Resolve-Path $ZipPath).Path -DestinationPath $expanded
$programRoot = Join-Path $expanded "DatasetManager"
$exePath = Join-Path $programRoot "DatasetManager.exe"
$manifest = Get-Content (Join-Path $programRoot "build-manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.tracked_changes_present -or -not $manifest.tests_run_in_build) { throw "候选包缺少已提交源码/构建测试证据。" }

function Start-Candidate([string]$Workspace = "") {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $exePath
    $info.WorkingDirectory = $programRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.EnvironmentVariables["DATASET_MANAGER_NO_BROWSER"] = "1"
    $info.EnvironmentVariables["DATASET_MANAGER_DATA_ROOT"] = $dataRoot
    $info.EnvironmentVariables["LOCALAPPDATA"] = (Join-Path $acceptanceRoot "Local AppData")
    $info.EnvironmentVariables["PATH"] = "$env:SystemRoot\System32;$env:SystemRoot"
    if ($Workspace) { $info.Arguments = '--workspace "' + $Workspace + '"' }
    return [Diagnostics.Process]::Start($info)
}

function Wait-Candidate([string]$Root) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $runtime = Get-Content (Join-Path $Root "config\runtime.json") -Raw -Encoding UTF8 | ConvertFrom-Json
            $health = Invoke-RestMethod -TimeoutSec 2 -Uri "$($runtime.url)/health"
            if ($health.application -eq "dataset-manager") { return $runtime }
        } catch {}
        Start-Sleep -Milliseconds 200
    }
    throw "便携候选未就绪：$Root"
}

function Stop-Candidate($Runtime, $Process) {
    if (-not $Runtime -or $Process.HasExited) { return }
    $control = Invoke-RestMethod -Uri "$($Runtime.url)/api/system/portable-runtime"
    Invoke-RestMethod -Method Post -Uri "$($Runtime.url)/api/system/portable-runtime/shutdown" -Headers @{ "X-Dataset-Manager-Control-Token" = $control.control_token } | Out-Null
    if (-not $Process.WaitForExit(10000)) { throw "候选安全退出超时。" }
}

function Post-Json([string]$Url, $Value) {
    $body = [Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 12))
    # Windows PowerShell 5 defaults JSON responses without charset to ANSI.
    $response = Invoke-WebRequest -UseBasicParsing -Method Post -ContentType "application/json; charset=utf-8" -Body $body -Uri $Url -TimeoutSec $TimeoutSeconds
    return ([Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray()) | ConvertFrom-Json)
}

function Wait-Job([string]$Url, [int]$JobId) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $job = Invoke-RestMethod -Uri "$Url/api/jobs/$JobId"
        if ($job.status -eq "succeeded") { return $job }
        if ($job.status -in @("failed", "cancelled", "interrupted")) { throw ($job | ConvertTo-Json -Depth 10) }
        Start-Sleep -Milliseconds 200
    }
    throw "任务未完成：$JobId"
}

$process = $null
$runtime = $null
try {
    Write-Host "[1/5] 启动真实 ZIP，生成带工件组的合成示例和快照"
    $process = Start-Candidate
    $runtime = Wait-Candidate $dataRoot
    $url = $runtime.url
    $startup = Invoke-RestMethod -Uri "$url/api/system/startup-status"
    if ($startup.needs_upgrade) { throw "启动器未完成结构升级。" }
    $dataset = Post-Json "$url/api/datasets/industrial-example" @{}
    if ($dataset.sample_count -ne 16) { throw "示例样本数不符。" }
    $originalHashes = Get-ChildItem -LiteralPath $dataset.root_path -File | Get-FileHash -Algorithm SHA256
    $snapshot = Post-Json "$url/api/datasets/$($dataset.id)/snapshots" @{ name = "portable-frozen" }

    Write-Host "[2/5] 工件隔离协议与训练 ZIP 导出"
    $plan = Post-Json "$url/api/datasets/$($dataset.id)/industrial/anomaly-previews" @{}
    if ($plan.summary.blocked) { throw ($plan.summary | ConvertTo-Json -Depth 8) }
    $export = Post-Json "$url/api/datasets/$($dataset.id)/industrial/export-jobs" @{ plan_id = $plan.plan_id; plan_hash = $plan.plan_hash }
    $job = Wait-Job $url $export.job.id
    $trainingZip = Join-Path $acceptanceRoot "training.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "$url/api/jobs/$($job.id)/artifact" -OutFile $trainingZip | Out-Null
    $packageRoot = Join-Path $acceptanceRoot "训练包 中文 空格"
    Expand-Archive -LiteralPath $trainingZip -DestinationPath $packageRoot
    if ($ReaderPython) {
        $ReaderPython = (Resolve-Path $ReaderPython).Path
        Push-Location $env:SystemRoot
        try {
            & $ReaderPython (Join-Path $packageRoot "load_anomalib.py") > (Join-Path $acceptanceRoot "reader-check.log") 2>&1
            if ($LASTEXITCODE -ne 0) { throw "真实包完整读取失败，检查 reader-check.log。" }
        } finally { Pop-Location }
    }

    Write-Host "[3/5] 元数据与外部快照 ZIP 备份及新位置恢复"
    $backup = Post-Json "$url/api/system/workspace-backup-jobs" @{}
    $backupJob = Wait-Job $url $backup.job.id
    $backupZip = Join-Path $acceptanceRoot "metadata.zip"
    Invoke-WebRequest -UseBasicParsing -Uri "$url/api/jobs/$($backupJob.id)/artifact" -OutFile $backupZip | Out-Null
    $restored = Post-Json "$url/api/system/restore-workspace" @{ archive_path = $backupZip }
    Stop-Candidate $runtime $process
    $runtime = $null

    Write-Host "[4/5] 使用 --workspace 打开恢复位置并读取历史快照"
    $process = Start-Candidate $restored.target_directory
    $runtime = Wait-Candidate $restored.target_directory
    $again = Invoke-RestMethod -Uri "$($runtime.url)/api/datasets/$($dataset.id)"
    $document = Invoke-RestMethod -Uri "$($runtime.url)/api/datasets/$($dataset.id)/snapshots/$($snapshot.id)/content"
    if ($again.sample_count -ne 16 -or $document.content.schema_version -ne 2 -or $document.content.sample_count -ne 16) { throw "恢复内容与原记录不一致。" }
    $restoredPlan = Post-Json "$($runtime.url)/api/datasets/$($dataset.id)/industrial/anomaly-previews" @{}
    if ($restoredPlan.summary.blocked) { throw "恢复后工件分组或判定不可用。" }

    Write-Host "[5/5] 核对原始文件 hash、记录候选源码与 ZIP hash"
    foreach ($item in $originalHashes) {
        if ((Get-FileHash -LiteralPath $item.Path -Algorithm SHA256).Hash -ne $item.Hash) { throw "原始文件内容发生变化。" }
    }
    $report = [ordered]@{ zip_sha256 = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash; source_commit = $manifest.source_commit; samples = 16; snapshot_schema = 2; restored_workspace_started = $true; reader_checked = [bool]$ReaderPython; raw_hashes_unchanged = $true; clean_windows_acceptance = "pending"; real_user_acceptance = "pending"; evidence_root = $acceptanceRoot }
    $report | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $acceptanceRoot "acceptance-report.json") -Encoding UTF8
    Write-Host ($report | ConvertTo-Json -Depth 8)
} finally {
    if ($process -and $runtime) { Stop-Candidate $runtime $process }
}

[CmdletBinding()]
param([string]$PortableRoot = "", [int]$TimeoutSeconds = 45)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
$acceptanceRoot = Join-Path $env:TEMP "Dataset Manager 便携验收 $runId"
$installRoot = Join-Path $acceptanceRoot "程序 中文路径"
$localAppData = Join-Path $acceptanceRoot "Local AppData 中文"
$sourceRoot = Join-Path $acceptanceRoot "客户 原始数据"
New-Item -ItemType Directory -Force -Path $installRoot, $localAppData, $sourceRoot | Out-Null
if (-not $PortableRoot) {
    $expandedRoot = Join-Path $acceptanceRoot "ZIP 解压 中文路径"
    Expand-Archive -Path (Join-Path $repoRoot "dist\DatasetManager-windows-x64-portable.zip") -DestinationPath $expandedRoot
    $PortableRoot = Join-Path $expandedRoot "DatasetManager"
}
$PortableRoot = (Resolve-Path $PortableRoot).Path
Copy-Item -Recurse -Force (Join-Path $PortableRoot "*") $installRoot
$exePath = Join-Path $installRoot "DatasetManager.exe"
if (-not (Test-Path $exePath)) { throw "未找到便携版程序：$exePath" }

$sourceFile = Join-Path $sourceRoot "样本 01.png"
[IO.File]::WriteAllBytes($sourceFile, [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))
$sourceHash = (Get-FileHash -Algorithm SHA256 $sourceFile).Hash

function Start-PortableProcess {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $exePath
    $info.WorkingDirectory = $installRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.EnvironmentVariables["LOCALAPPDATA"] = $localAppData
    $info.EnvironmentVariables["DATASET_MANAGER_NO_BROWSER"] = "1"
    $info.EnvironmentVariables["PATH"] = "$env:SystemRoot\System32;$env:SystemRoot"
    return [Diagnostics.Process]::Start($info)
}

function Wait-Runtime([int]$DifferentPid = 0) {
    $runtimeFile = Join-Path $localAppData "DatasetManager\config\runtime.json"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $runtimeFile) {
            try {
                $state = Get-Content -Raw -Encoding UTF8 $runtimeFile | ConvertFrom-Json
                if ($state.pid -ne $DifferentPid) {
                    $health = Invoke-RestMethod -TimeoutSec 2 -Uri "$($state.url)/health"
                    if ($health.application -eq "dataset-manager") { return $state }
                }
            } catch {}
        }
        Start-Sleep -Milliseconds 200
    }
    throw "便携版服务未在 $TimeoutSeconds 秒内就绪。"
}

function Stop-Safely($state, $process) {
    $runtime = Invoke-RestMethod -TimeoutSec 5 -Uri "$($state.url)/api/system/portable-runtime"
    $headers = @{ "X-Dataset-Manager-Control-Token" = $runtime.control_token }
    Invoke-RestMethod -Method Post -Headers $headers -TimeoutSec 5 -Uri "$($state.url)/api/system/portable-runtime/shutdown" | Out-Null
    if (-not $process.WaitForExit(10000)) { throw "安全退出超时。" }
}

$occupied = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 8765)
$occupied.Start()
try {
    Write-Host "[1/4] 验证端口冲突、单端口页面与重复启动"
    $first = Start-PortableProcess
    $firstState = Wait-Runtime
    if ($firstState.port -eq 8765) { throw "端口冲突时未选择备用端口。" }
    $rootPage = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $firstState.url
    if ($rootPage.StatusCode -ne 200 -or $rootPage.Content -notmatch "Dataset Manager") { throw "单端口前端页面未正确提供。" }
    $duplicate = Start-PortableProcess
    if (-not $duplicate.WaitForExit(10000)) { throw "重复启动没有及时退出。" }
    if ($first.HasExited) { throw "重复启动影响了已有服务。" }

    $datasetBody = @{ name = "便携升级验收"; root_path = $sourceRoot } | ConvertTo-Json
    $dataset = Invoke-RestMethod -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($datasetBody)) -Uri "$($firstState.url)/api/datasets"
    $scanBody = @{ folder_path = $sourceRoot } | ConvertTo-Json
    $scan = Invoke-RestMethod -Method Post -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($scanBody)) -Uri "$($firstState.url)/api/datasets/$($dataset.id)/scan"
    if ($scan.imported -ne 1) { throw "原始数据扫描验收失败。" }
    Stop-Safely $firstState $first
} finally { $occupied.Stop() }

Write-Host "[2/4] 验证异常退出恢复与数据库保留"
$second = Start-PortableProcess
$secondState = Wait-Runtime
$crashedPid = $secondState.pid
$second.Kill()
$second.WaitForExit()
$third = Start-PortableProcess
$thirdState = Wait-Runtime -DifferentPid $crashedPid
$datasets = Invoke-RestMethod -Uri "$($thirdState.url)/api/datasets"
if (@($datasets).Count -ne 1 -or $datasets[0].id -ne $dataset.id -or $datasets[0].sample_count -ne 1) { throw "异常退出后数据库内容未保留。" }
Stop-Safely $thirdState $third

Write-Host "[3/4] 验证覆盖升级与应用数据保留"
$sentinel = Join-Path $localAppData "DatasetManager\config\upgrade-sentinel.txt"
"keep-me" | Set-Content -Encoding UTF8 $sentinel
Copy-Item -Recurse -Force (Join-Path $PortableRoot "*") $installRoot
$fourth = Start-PortableProcess
$fourthState = Wait-Runtime
if ((Get-Content -Raw -Encoding UTF8 $sentinel).Trim() -ne "keep-me") { throw "覆盖升级后应用数据未保留。" }
if ((Get-FileHash -Algorithm SHA256 $sourceFile).Hash -ne $sourceHash) { throw "便携版运行期间原始文件发生变化。" }
Stop-Safely $fourthState $fourth
Write-Host "[4/4] 验证原始文件哈希保持不变"
Write-Host "便携版验收通过。"
Write-Host "验收目录（保留供复核）：$acceptanceRoot"

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ZipPath,
    [string]$AcceptanceRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$archivePath = (Resolve-Path -LiteralPath $ZipPath).Path
if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf) -or [IO.Path]::GetExtension($archivePath) -ne ".zip") {
    throw "ZipPath 必须指向已构建的真实 ZIP 文件。"
}
if (-not $AcceptanceRoot) {
    $AcceptanceRoot = Join-Path $repoRoot ("output\release-20261106\daily-tools-" + [Guid]::NewGuid().ToString("N"))
}
$AcceptanceRoot = [IO.Path]::GetFullPath($AcceptanceRoot)
if (Test-Path -LiteralPath $AcceptanceRoot) { throw "验收目录必须不存在，以免覆盖已有内容：$AcceptanceRoot" }
New-Item -ItemType Directory -Path $AcceptanceRoot | Out-Null
$expandedRoot = Join-Path $AcceptanceRoot "ZIP 解压 中文路径"
$localAppData = Join-Path $AcceptanceRoot "Local AppData 中文"
$workspaceRoot = Join-Path $localAppData "DatasetManager"
$sourceRoot = Join-Path $AcceptanceRoot "合成 原始图片"
$temporaryRoot = Join-Path $AcceptanceRoot "临时 文件"
New-Item -ItemType Directory -Path $localAppData, $sourceRoot, $temporaryRoot | Out-Null
$script:assertionCount = 0
$script:baseUrl = $null
$startedProcess = $null
$runtimeProcess = $null
$controlRuntime = $null
$completed = $false
$evidence = [ordered]@{ archive = [IO.Path]::GetFileName($archivePath); archive_sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash; passed = $false }

function Assert-Equal($Actual, $Expected, [string]$Message) {
    if ($Actual -ne $Expected) { throw "$Message；期望=$Expected，实际=$Actual" }
    $script:assertionCount += 1
}

function Assert-Condition([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:assertionCount += 1
}

function Invoke-Api([string]$Path, [string]$Method = "Get", $Body = $null) {
    $request = @{ Uri = "$($script:baseUrl)$Path"; Method = $Method; TimeoutSec = 30; UseBasicParsing = $true }
    if ($null -ne $Body) {
        $request.ContentType = "application/json; charset=utf-8"
        $request.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 12 -Compress))
    }
    # FastAPI JSON has no charset; Windows PowerShell 5 otherwise decodes
    # Chinese response values as ANSI, including the verified workspace path.
    $response = Invoke-WebRequest @request
    return ([Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray()) | ConvertFrom-Json)
}

# Small valid 4x4 PNGs; using PNG bytes in the official .JPG paths deliberately
# avoids needing Python, Pillow, GDI+, downloads, or tools outside the real ZIP.
$normalPng = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGOUWxDFAANMcBZeDgA3eAEgFOL+uQAAAABJRU5ErkJggg==")
$anomalyPng = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGO8Y27DAANMcBZeDgBDEgFXnY3TZwAAAABJRU5ErkJggg==")
$maskPng = [Convert]::FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAE0lEQVR4nGP8//8/AwwwwVl4OQCWbgMF7ZjH1AAAAABJRU5ErkJggg==")

function Write-Fixture([string]$Root, [string]$RelativePath, [byte[]]$Bytes) {
    $path = Join-Path $Root $RelativePath
    New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($path)) | Out-Null
    [IO.File]::WriteAllBytes($path, $Bytes)
}

function New-MvtecFixture([string]$Root) {
    Write-Fixture $Root "bottle\train\good\000.png" $normalPng
    Write-Fixture $Root "bottle\test\good\001.png" $normalPng
    Write-Fixture $Root "bottle\test\broken\002.png" $anomalyPng
    Write-Fixture $Root "bottle\ground_truth\broken\002_mask.png" $maskPng
    Write-Fixture $Root "cable\train\good\000.png" $normalPng
    Write-Fixture $Root "cable\test\good\001.png" $normalPng
}

function Get-SourceHashes {
    $values = @{}
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -File -Recurse) {
        $values[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
    return $values
}

function Get-OwnedRuntimeProcess($State, $Started) {
    $processId = [int]$State.pid
    $candidate = [Diagnostics.Process]::GetProcessById($processId)
    Assert-Condition ($candidate.StartTime -ge $Started.StartTime.AddSeconds(-2)) "runtime PID 的启动时间不属于本次验收。"
    Assert-Equal ([IO.Path]::GetFullPath($candidate.MainModule.FileName)) $exePath "runtime PID 的可执行文件不属于解压包"
    if ($processId -ne $Started.Id) {
        # Some PyInstaller modes have a bootstrap parent; accept only its direct child.
        $record = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $processId"
        Assert-Equal ([int]$record.ParentProcessId) $Started.Id "runtime PID 不是本次启动进程或其直接子进程"
    }
    return $candidate
}

function Wait-PortableRuntime($Started) {
    $runtimeFile = Join-Path $workspaceRoot "config\runtime.json"
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $runtimeFile -PathType Leaf) {
            try { $state = Get-Content -Raw -Encoding UTF8 -LiteralPath $runtimeFile | ConvertFrom-Json }
            catch { Start-Sleep -Milliseconds 200; continue }
            Assert-Equal $state.application "dataset-manager" "runtime 文件应用标识错误"
            Assert-Equal $state.url ("http://127.0.0.1:" + [int]$state.port) "runtime URL 必须是本机回环地址"
            $script:runtimeProcess = Get-OwnedRuntimeProcess $state $Started
            try { $health = Invoke-RestMethod -TimeoutSec 2 -Uri "$($state.url)/health" }
            catch { Start-Sleep -Milliseconds 200; continue }
            if ($health.application -eq "dataset-manager" -and $health.status -eq "ok") { return $state }
        }
        if ($Started.HasExited) { throw "包内程序提前退出，可能有现有便携实例占用单实例锁；请先正常退出该实例后重试。" }
        Start-Sleep -Milliseconds 200
    }
    throw "包内程序未在 120 秒内就绪；验收目录已保留供查看日志。"
}

function Assert-BenchmarkPreview($Preview, [string]$Format, [int]$Images, [int]$Masks, [int]$Train, [int]$Test) {
    Assert-Equal $Preview.detected_format $Format "预览识别格式错误"
    Assert-Equal $Preview.image_count $Images "预览图片数错误"
    Assert-Equal $Preview.mask_count $Masks "预览 mask 数错误"
    Assert-Equal $Preview.official_split_counts.train $Train "预览官方 train 数错误"
    Assert-Equal $Preview.official_split_counts.test $Test "预览官方 test 数错误"
}

function Assert-Imported($Scan, [string]$Format, [int]$Images, [int]$Masks) {
    Assert-Equal $Scan.detected_format $Format "导入格式错误"
    Assert-Equal $Scan.imported $Images "导入图片数错误"
    Assert-Equal $Scan.benchmark_images $Images "基准图片数错误"
    Assert-Equal $Scan.linked_masks $Masks "关联 mask 数错误"
    Assert-Equal $Scan.error_count 0 "导入出现错误"
    Assert-Condition ($Scan.assigned_batch_id -gt 0) "导入没有关联批次。"
}

function Assert-Comparison($Value, [int]$CategoryId, [int]$BatchId, [int]$Normal, [int]$Anomaly) {
    Assert-Equal $Value.category_id $CategoryId "对照类别错误"
    Assert-Equal $Value.batch_id $BatchId "对照批次错误"
    Assert-Equal $Value.normal.total $Normal "对照正常数错误"
    Assert-Equal $Value.anomaly.total $Anomaly "对照异常数错误"
    Assert-Equal $Value.excluded_count 0 "新导入合成样本不应被对照排除"
    foreach ($sample in @($Value.normal.items) + @($Value.anomaly.items)) {
        Assert-Equal $sample.category_id $CategoryId "对照混入其他类别"
        Assert-Equal $sample.batch_id $BatchId "对照混入其他批次"
    }
}

function Assert-MaskReadable([int]$SampleId, [string]$ExpectedPath, [string]$Name) {
    $download = Join-Path $AcceptanceRoot "$Name-mask.png"
    $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 -Uri "$($script:baseUrl)/api/samples/$SampleId/mask" -OutFile $download -PassThru
    Assert-Equal $response.StatusCode 200 "mask 接口未返回成功"
    Assert-Condition ($response.Headers["Content-Type"] -like "image/png*") "mask 接口没有返回 PNG。"
    Assert-Equal ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash) ((Get-FileHash -LiteralPath $ExpectedPath -Algorithm SHA256).Hash) "mask 下载内容与合成原文件不同"
}

try {
    Write-Host "[1/5] 解压真实 ZIP 并核对离线 VisA 资源"
    Expand-Archive -LiteralPath $archivePath -DestinationPath $expandedRoot
    $installRoot = Join-Path $expandedRoot "DatasetManager"
    $exePath = [IO.Path]::GetFullPath((Join-Path $installRoot "DatasetManager.exe"))
    Assert-Condition (Test-Path -LiteralPath $exePath -PathType Leaf) "真实 ZIP 中没有 DatasetManager/DatasetManager.exe。"
    $csvCandidates = @((Join-Path $installRoot "_internal\app\data\visa\1cls.csv"), (Join-Path $installRoot "app\data\visa\1cls.csv"))
    $csvPaths = @($csvCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    Assert-Equal $csvPaths.Count 1 "ZIP 内应有唯一的 VisA 官方离线索引"
    $officialRows = @(Import-Csv -LiteralPath $csvPaths[0] -Encoding UTF8)
    $trainRows = @($officialRows | Where-Object { $_.image -eq "candle/Data/Images/Normal/0836.JPG" })
    $testRows = @($officialRows | Where-Object { $_.image -eq "candle/Data/Images/Anomaly/000.JPG" })
    Assert-Equal $trainRows.Count 1 "离线 CSV 缺少已知正常行"
    Assert-Equal $testRows.Count 1 "离线 CSV 缺少已知异常行"
    Assert-Equal $trainRows[0].split "train" "已知正常行的官方划分错误"
    Assert-Equal $trainRows[0].label "normal" "已知正常行的官方标签错误"
    Assert-Equal $testRows[0].split "test" "已知异常行的官方划分错误"
    Assert-Equal $testRows[0].label "anomaly" "已知异常行的官方标签错误"
    Assert-Equal $testRows[0].mask "candle/Data/Masks/Anomaly/000.png" "已知异常行的 mask 路径错误"

    $mvtecFirst = Join-Path $sourceRoot "MVTec 第一批"
    $mvtecSecond = Join-Path $sourceRoot "MVTec 第二批"
    New-MvtecFixture $mvtecFirst
    New-MvtecFixture $mvtecSecond
    $visaRoot = Join-Path $sourceRoot "VisA\candle"
    Write-Fixture $visaRoot "Data\Images\Normal\0836.JPG" $normalPng
    Write-Fixture $visaRoot "Data\Images\Anomaly\000.JPG" $anomalyPng
    Write-Fixture $visaRoot "Data\Masks\Anomaly\000.png" $maskPng
    $sourceHashes = Get-SourceHashes

    Write-Host "[2/5] 使用受限 PATH 启动包内程序与全新隔离工作区"
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $exePath
    $info.WorkingDirectory = $installRoot
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    foreach ($key in @("DATASET_MANAGER_DATA_ROOT", "DATABASE_URL", "STORAGE_ROOT", "DATASET_MANAGER_FRONTEND_DIR", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")) { $info.EnvironmentVariables.Remove($key) }
    $info.EnvironmentVariables["LOCALAPPDATA"] = $localAppData
    $info.EnvironmentVariables["DATASET_MANAGER_NO_BROWSER"] = "1"
    $info.EnvironmentVariables["PATH"] = "$env:SystemRoot\System32;$env:SystemRoot"
    $info.EnvironmentVariables["TEMP"] = $temporaryRoot
    $info.EnvironmentVariables["TMP"] = $temporaryRoot
    # --workspace intentionally omitted: it accepts verified restored workspaces
    # only. Fresh first-run workspaces are selected via isolated LOCALAPPDATA.
    $startedProcess = [Diagnostics.Process]::Start($info)
    $state = Wait-PortableRuntime $startedProcess
    $script:baseUrl = $state.url
    $describedRuntime = Invoke-Api "/api/system/portable-runtime"
    Assert-Equal $describedRuntime.enabled $true "包内程序不是便携模式"
    Assert-Equal $describedRuntime.pid $runtimeProcess.Id "便携控制接口 PID 与本次进程不一致"
    Assert-Equal ([IO.Path]::GetFullPath($describedRuntime.data_root)) ([IO.Path]::GetFullPath($workspaceRoot)) "程序没有使用隔离工作区"
    Assert-Condition (-not [string]::IsNullOrWhiteSpace($describedRuntime.control_token)) "安全退出控制令牌缺失。"
    $controlRuntime = $describedRuntime
    Assert-Condition (Test-Path -LiteralPath (Join-Path $workspaceRoot "database\app.db") -PathType Leaf) "隔离 SQLite 数据库未创建。"
    Assert-Equal (@(Invoke-Api "/api/datasets").Count) 0 "全新隔离工作区不应已有数据集"
    $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 -Uri $script:baseUrl
    Assert-Equal $page.StatusCode 200 "包内前端首页不可读"
    Assert-Condition ($page.Content -match "Dataset Manager") "包内没有提供预期前端首页。"

    Write-Host "[3/5] 验收 MVTec 两类别、两批次和官方真值"
    $project = Invoke-Api "/api/projects" "Post" @{ name = "真实 ZIP 日常工具验收" }
    $dataset = Invoke-Api "/api/datasets" "Post" @{ name = "MVTec 合成两批次"; root_path = $mvtecFirst; workflow_profile = "industrial_anomaly"; project_id = $project.id }
    $datasetId = [int]$dataset.id
    $preview = Invoke-Api "/api/datasets/$datasetId/import-preview" "Post" @{ import_format = "auto" }
    Assert-BenchmarkPreview $preview "mvtec_ad" 5 1 2 3
    Assert-Equal ((@($preview.categories) | Sort-Object) -join ",") "bottle,cable" "MVTec 类别识别错误"
    $first = Invoke-Api "/api/datasets/$datasetId/scan" "Post" @{ import_format = "auto"; new_batch_name = "第一批" }
    Assert-Imported $first "mvtec_ad" 5 1
    $batchTwo = Invoke-Api "/api/datasets/$datasetId/batches" "Post" @{ name = "第二批" }
    $second = Invoke-Api "/api/datasets/$datasetId/scan" "Post" @{ folder_path = $mvtecSecond; import_format = "mvtec_ad"; batch_id = $batchTwo.id }
    Assert-Imported $second "mvtec_ad" 5 1
    Assert-Equal $second.assigned_batch_id $batchTwo.id "选择已有批次导入未生效"
    $organization = Invoke-Api "/api/datasets/$datasetId/organization"
    Assert-Equal $organization.project.id $project.id "项目关联错误"
    Assert-Equal (@($organization.categories).Count) 2 "项目内类别数错误"
    Assert-Equal (@($organization.batches).Count) 2 "项目内批次数错误"
    $bottle = @($organization.categories | Where-Object { $_.name -eq "bottle" })[0]
    $cable = @($organization.categories | Where-Object { $_.name -eq "cable" })[0]
    Assert-Equal $bottle.sample_count 6 "bottle 样本数错误"
    Assert-Equal $cable.sample_count 4 "cable 样本数错误"
    foreach ($batch in $organization.batches) { Assert-Equal $batch.sample_count 5 "批次样本数错误" }
    $card = Invoke-Api "/api/datasets/$datasetId/card"
    foreach ($pair in @(@("sample_count", 10), @("image_count", 10), @("normal_count", 8), @("anomaly_count", 2), @("mask_count", 2), @("category_count", 2), @("batch_count", 2), @("pending_count", 0), @("unavailable_count", 0))) {
        Assert-Equal $card.summary.($pair[0]) $pair[1] ("MVTec 名片统计错误：" + $pair[0])
    }
    Assert-Equal $card.summary.splits.train 4 "名片 train 数错误"
    Assert-Equal $card.summary.splits.test 6 "名片 test 数错误"
    Assert-Condition (@($card.preview_samples).Count -gt 0 -and @($card.preview_samples).Count -le 8) "名片代表图数量不正确。"
    foreach ($category in @($bottle, $cable)) {
        foreach ($batchId in @([int]$first.assigned_batch_id, [int]$batchTwo.id)) {
            $anomalyCount = 0
            if ($category.id -eq $bottle.id) { $anomalyCount = 1 }
            $comparison = Invoke-Api "/api/datasets/$datasetId/comparison?category_id=$($category.id)&batch_id=$batchId"
            Assert-Comparison $comparison $category.id $batchId 2 $anomalyCount
            $browse = Invoke-Api "/api/datasets/$datasetId/browse?recursive=true&all_sources=true&file_type=image&category_id=$($category.id)&batch_id=$batchId&page_size=200"
            Assert-Equal $browse.total (2 + $anomalyCount) "目录浏览的类别/批次过滤数错误"
            Assert-Equal (@($browse.items).Count) (2 + $anomalyCount) "目录浏览返回数量错误"
            foreach ($sample in $browse.items) {
                Assert-Equal $sample.category_id $category.id "目录浏览混入其他类别"
                Assert-Equal $sample.batch_id $batchId "目录浏览混入其他批次"
                Assert-Equal $sample.official_split $sample.split "官方划分没有应用到首次导入"
                Assert-Condition ($sample.official_split -in @("train", "test")) "原图缺少官方划分。"
                Assert-Condition ($sample.benchmark_label -in @("normal", "anomaly")) "原图缺少官方标签。"
            }
        }
    }
    $allBrowse = Invoke-Api "/api/datasets/$datasetId/browse?recursive=true&all_sources=true&file_type=image&page_size=200"
    Assert-Equal $allBrowse.total 10 "跨来源浏览总数错误"
    Assert-Equal (@($allBrowse.sources).Count) 2 "没有保留两个原始来源"
    $masked = @($allBrowse.items | Where-Object { $_.batch_id -eq $first.assigned_batch_id -and $_.mask_path })[0]
    Assert-MaskReadable $masked.id (Join-Path $mvtecFirst "bottle\ground_truth\broken\002_mask.png") "mvtec"
    $evidence.mvtec = @{ dataset_id = $datasetId; image_count = $card.summary.image_count; categories = 2; batches = 2; normal = 8; anomaly = 2; masks = 2 }

    Write-Host "[4/5] 验收包内 VisA 官方 CSV 的离线预览和导入"
    Assert-Condition (-not (Test-Path -LiteralPath (Join-Path $visaRoot "split_csv\1cls.csv"))) "VisA 验收不应使用本地 CSV 覆盖包内资源。"
    $visa = Invoke-Api "/api/datasets" "Post" @{ name = "VisA 离线索引合成子集"; root_path = $visaRoot; workflow_profile = "industrial_anomaly"; project_id = $project.id }
    $visaId = [int]$visa.id
    $visaPreview = Invoke-Api "/api/datasets/$visaId/import-preview" "Post" @{ import_format = "auto" }
    Assert-BenchmarkPreview $visaPreview "visa" 2 1 1 1
    Assert-Condition ((@($visaPreview.warnings) -join "`n") -like "*随软件附带*VisA*1cls*") "VisA 预览没有使用包内官方索引。"
    $visaScan = Invoke-Api "/api/datasets/$visaId/scan" "Post" @{ import_format = "visa"; new_batch_name = "官方子集" }
    Assert-Imported $visaScan "visa" 2 1
    $visaOrganization = Invoke-Api "/api/datasets/$visaId/organization"
    Assert-Equal (@($visaOrganization.categories).Count) 1 "VisA 类别数错误"
    Assert-Equal $visaOrganization.categories[0].name "candle" "VisA 类别识别错误"
    Assert-Equal $visaOrganization.categories[0].sample_count 2 "VisA 类别样本数错误"
    $visaComparison = Invoke-Api "/api/datasets/$visaId/comparison?category_id=$($visaOrganization.categories[0].id)&batch_id=$($visaScan.assigned_batch_id)"
    Assert-Comparison $visaComparison $visaOrganization.categories[0].id $visaScan.assigned_batch_id 1 1
    $visaBrowse = Invoke-Api "/api/datasets/$visaId/browse?recursive=true&all_sources=true&file_type=image&category_id=$($visaOrganization.categories[0].id)&batch_id=$($visaScan.assigned_batch_id)"
    Assert-Equal $visaBrowse.total 2 "VisA 浏览数量错误"
    $visaNormal = @($visaBrowse.items | Where-Object { $_.filename -eq "0836.JPG" })[0]
    $visaAnomaly = @($visaBrowse.items | Where-Object { $_.filename -eq "000.JPG" })[0]
    Assert-Equal $visaNormal.official_split "train" "VisA 正常图没有读取官方 train 划分"
    Assert-Equal $visaNormal.benchmark_label "normal" "VisA 正常标签错误"
    Assert-Equal $visaAnomaly.official_split "test" "VisA 异常图没有读取官方 test 划分"
    Assert-Equal $visaAnomaly.benchmark_label "anomaly" "VisA 异常标签错误"
    Assert-MaskReadable $visaAnomaly.id (Join-Path $visaRoot "Data\Masks\Anomaly\000.png") "visa"
    $visaCard = Invoke-Api "/api/datasets/$visaId/card"
    Assert-Equal $visaCard.summary.image_count 2 "VisA 名片数量错误"
    Assert-Equal $visaCard.summary.normal_count 1 "VisA 名片正常数错误"
    Assert-Equal $visaCard.summary.anomaly_count 1 "VisA 名片异常数错误"
    Assert-Equal $visaCard.summary.mask_count 1 "VisA 名片 mask 数错误"
    $evidence.visa = @{ image_count = 2; normal = 1; anomaly = 1; masks = 1; official_train = 1; official_test = 1; bundled_csv = $true }

    Write-Host "[5/5] 检查合成原图未变并安全退出"
    $afterHashes = Get-SourceHashes
    Assert-Equal $afterHashes.Count $sourceHashes.Count "原始目录出现文件新增或删除"
    foreach ($path in $sourceHashes.Keys) { Assert-Equal $afterHashes[$path] $sourceHashes[$path] "合成原图或 mask 被修改" }
    $completed = $true
} finally {
    $shutdownSucceeded = $false
    try {
        if ($null -ne $controlRuntime -and $null -ne $runtimeProcess -and -not $runtimeProcess.HasExited) {
            # Never write the control token or runtime instance_id to evidence.
            $headers = @{ "X-Dataset-Manager-Control-Token" = $controlRuntime.control_token }
            Invoke-RestMethod -Method Post -Headers $headers -TimeoutSec 5 -Uri "$($script:baseUrl)/api/system/portable-runtime/shutdown" | Out-Null
            $shutdownSucceeded = $runtimeProcess.WaitForExit(15000)
        } elseif ($null -ne $runtimeProcess) { $shutdownSucceeded = $runtimeProcess.HasExited }
    } catch { Write-Warning "安全退出接口失败，将只停止本次启动且已确认归属的进程。" }
    foreach ($ownedProcess in @($runtimeProcess, $startedProcess)) {
        if ($null -eq $ownedProcess) { continue }
        try {
            if (-not $ownedProcess.HasExited) { $ownedProcess.Kill(); [void]$ownedProcess.WaitForExit(5000) }
        } catch { Write-Warning "本次验收进程未能退出，请查看保留的验收目录。" }
    }
    $evidence.passed = $completed -and $shutdownSucceeded
    $evidence.assertions = $script:assertionCount
    $evidence.clean_shutdown = $shutdownSucceeded
    [IO.File]::WriteAllText((Join-Path $AcceptanceRoot "daily-tools-result.json"), ($evidence | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
    Write-Host "验收目录（保留供复核）：$AcceptanceRoot"
    if ($completed -and -not $shutdownSucceeded) { throw "接口验收已通过，但安全退出失败；本次真实 ZIP 验收不能记为通过。" }
}
Write-Host "真实 ZIP 日常工具验收通过，共 $($script:assertionCount) 项断言。"

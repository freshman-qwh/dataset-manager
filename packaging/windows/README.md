# Windows x64 便携版构建

在 Windows x64 上从仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\build-portable.ps1
```

构建机需要 Python 3.11+、Node.js 和 npm。脚本会构建前端、创建隔离 Python 环境、运行自动化测试，并使用 PyInstaller 目录模式生成 `dist/DatasetManager/`、`dist/DatasetManager-windows-x64-portable.zip` 和对应的 `.sha256.txt` 校验文件。最终用户不需要安装 Python 或 Node.js。

`v0.5.0-rc.1` 外部测试交付使用同一构建内容的带版本文件名 `DatasetManager-v0.5.0-rc.1-windows-x64-portable.zip`，并附同名 `.sha256.txt`。这是测试候选而非正式发布；测试人员应在全新 Windows 10/11 x64 环境解压运行，记录系统版本、启动/导入/导出结果和问题复现步骤。不要把包含个人数据的 `%LOCALAPPDATA%\DatasetManager` 目录一并分发。

调试构建时可传入 `-SkipTests`，发布构建不要跳过测试。

真实 ZIP 验收：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\test-portable.ps1
```

脚本解压 ZIP 到含中文和空格的隔离目录，以受限 PATH 运行 EXE，并验证端口冲突、重复启动、异常恢复、覆盖升级、数据保留及原始文件哈希。验收目录会保留并输出路径，便于人工复核。

## 带版本的 GitHub 预发行

先提交已验证的源码，再构建到独立版本目录，避免覆盖旧候选。下例以 `v0.5.0-rc.3` 为例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/build-portable.ps1 -Python backend/.venv/Scripts/python.exe -ReleaseTag v0.5.0-rc.3 -OutputDirectory dist/releases/v0.5.0-rc.3 -OutputName DatasetManager-v0.5.0-rc.3-windows-x64-portable.zip
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/windows/test-daily-tools.ps1 -ZipPath dist/releases/v0.5.0-rc.3/DatasetManager-v0.5.0-rc.3-windows-x64-portable.zip
```

`build-manifest.json` 记录版本标记、源码提交、受控文件是否有改动、构建测试状态及能力清单。基础回归另用 `test-portable.ps1 -PortableRoot <本次ZIP解压后的DatasetManager目录>` 执行，不能误用旧版默认 ZIP。通过后将版本 ZIP 和 `.sha256.txt` 一起上传 GitHub Release；算法环境、权重、用户数据库和原图不上传。

独立干净 Windows 10/11 与真实用户验收完成前，标记为 prerelease；本机隔离测试通过不等于正式产线定版。当前 Linux/macOS 可从源码验证基础 Web 功能，便携启动器与发行包尚未适配；可选算法环境也需要各平台独立验证。

## 工业试用候选

可通过 `-OutputName DatasetManager-industrial-trial-20261030-windows-x64.zip` 输出独立文件，避免混淆旧候选。包内 `build-manifest.json` 记录对应源码提交、是否有未提交改动、是否运行构建测试和待完成的外部验收；ZIP 的 `.sha256.txt` 用于核对最终文件。

训练读取脚本和依赖文件会随程序打包，但训练框架不进入应用依赖。新版图像级训练包可在独立 Anomalib 2.7.0 环境读取三个固定集合。

安全退出程序后，用 `DatasetManager.exe --workspace "恢复目录"` 可打开已通过恢复校验的新工作区；直接双击仍打开默认位置。原图与下载产物不包含在元数据 ZIP，请按包内《工业试用指南》另行保留。

工业候选从真实 ZIP 开始的自动化验收：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ./packaging/windows/test-industrial-trial.ps1 -ZipPath ./dist/DatasetManager-industrial-trial-20261030-windows-x64.zip -ReaderPython '独立读取环境的 python.exe'
```

脚本记录源码、ZIP hash、独立读取结果和恢复位置启动结果。本机隔离验收结果与外部定版条件见 `docs/industrial-trial-delivery-2026-10-30.md`。

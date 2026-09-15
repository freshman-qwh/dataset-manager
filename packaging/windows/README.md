# Windows x64 便携版构建

在 Windows x64 上从仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\build-portable.ps1
```

构建机需要 Python 3.11+、Node.js 和 npm。脚本会构建前端、创建隔离 Python 环境、运行自动化测试，并使用 PyInstaller 目录模式生成 `dist/DatasetManager/`、`dist/DatasetManager-windows-x64-portable.zip` 和对应的 `.sha256.txt` 校验文件。最终用户不需要安装 Python 或 Node.js。

调试构建时可传入 `-SkipTests`，发布构建不要跳过测试。

真实 ZIP 验收：

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\test-portable.ps1
```

脚本解压 ZIP 到含中文和空格的隔离目录，以受限 PATH 运行 EXE，并验证端口冲突、重复启动、异常恢复、覆盖升级、数据保留及原始文件哈希。验收目录会保留并输出路径，便于人工复核。

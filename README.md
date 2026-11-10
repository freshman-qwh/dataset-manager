# Dataset Manager

**把产线图片整理成可复核、可交付的数据集。**

Dataset Manager 是一个在本机运行的工业视觉数据工作台。无论是整理散落在不同文件夹的质检照片，还是给算法同事准备一份异常检测训练包，都可以从扫描现有图片目录开始。

[下载 Windows 便携版](https://github.com/freshman-qwh/dataset-manager/releases/tag/v0.5.0-rc.3) · [从源码运行](docs/development-workflow.md#安装与启动) · [使用文档](docs/README.md#使用产品)

## 快速上手

### Windows x64 便携版

1. 在发行页下载 Windows x64 ZIP，完整解压。
2. 双击 `DatasetManager\DatasetManager.exe`，程序就绪后会打开默认浏览器。
3. 在首页点击 **体验合成示例**，或创建自己的 **工业异常检测** 项目并添加图片。

便携版自带运行环境，浏览、分拣和导出无需另装 Python 或 Node.js。GitHub 提供的是预发行版，功能以对应的发行说明为准。

### 从源码运行

准备 Python 3.11+、Node.js 和 npm，按开发指南启动后端与前端。下面的工作流程以当前源码为准。[安装与启动](docs/development-workflow.md#安装与启动)

## 从一批图片开始

1. **登记和浏览**。扫描本地目录，按项目、类别和采集批次查看图片。再次扫描可补充新到的文件。
2. **分拣和复核**。逐张确认正常、异常或待定，按需对照正常与缺陷样本。下次在同一浏览器打开，可以从上次的分拣进度继续。
3. **按工件分组**。一起查看同一工件的正面、侧面和连拍图。纳入交付的同组图片会留在同一个集合，避免同一工件同时出现在训练和评估中。
4. **检查后交付**。查看哪些样本需要复核、哪些被排除，以及还缺哪些类别或工件，再导出带划分和清单的训练 ZIP。也可配置独立算法环境，在本机建立异常检测基线并复核结果。
5. **接收下一批**。复用已保存的导入格式、目录类别映射和工件规则。预览匹配结果，确认后只补齐空字段，保留已有人工判定。

[工业试用指南](docs/industrial-trial-guide.md) · [批次接收](docs/project-category-batch.md#新批次接收方案) · [本地快速验证](docs/quick-validation-guide.md)

## 其他使用场景

- **日常看图**。浏览多级目录，连续翻看大图，用原始像素检查细节，或生成一张可分享的数据集名片。[日常浏览与对照](docs/daily-tools.md)
- **试用公开数据**。从数据集图书馆找到 MVTec AD、VisA、Real-IAD 等数据的官方入口。导入 MVTec AD 和 VisA 时可以预览识别出的类别、官方划分和 Mask。[数据集图书馆](docs/anomaly-dataset-library.md)
- **准备通用视觉数据**。为分类样本整理标签，为检测和分割图像做几何标注，并按需导出 COCO、YOLO 等格式。[标注与导出](docs/annotation-format-export-contract.md)

## 数据保存在本机

原图留在原目录，应用在本机保存路径、判定、分组和标注。需要交付图片时，导出会把选定文件复制到新的目录或 ZIP。便携版默认工作区位于 `%LOCALAPPDATA%\DatasetManager`，页面左下角的 **便携版** 菜单可打开数据目录或安全退出。原图可单独备份。[备份与恢复](docs/industrial-trial-guide.md#备份恢复和原图迁移)

## 文档与反馈

- [文档导航](docs/README.md) · [产品范围](docs/product-scope.md) · [更新日志](CHANGELOG.md)
- [开发与验证](docs/development-workflow.md) · [Windows 打包](packaging/windows/README.md)
- [报告问题或建议](https://github.com/freshman-qwh/dataset-manager/issues)

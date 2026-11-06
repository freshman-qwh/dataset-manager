# 异常检测数据集图书馆

资料核对：2026-11-06。入口为首页的“数据集图书馆”（`/library`），与“我的数据集”分开：图书馆帮助了解和获取公开数据，“我的数据集”管理已经登记的本地文件。

## 首批目录

只收录工业视觉异常检测，优先二维真实图片；三维数据作为明确标记的扩展资源。类别和图数是作者提供的口径，不代表本应用已经验证完整下载包。

| 数据集 | 规模与用途 | 官方主页 | 获取入口 |
| --- | --- | --- | --- |
| MVTec AD | 15 类、5,354 图；物体和纹理缺陷基础基准 | [MVTec](https://www.mvtec.com/research-teaching/datasets/mvtec-ad) | 官方页表单；规模与概览见[作者论文](https://link.springer.com/article/10.1007/s11263-020-01400-4) |
| VisA | 12 类、10,821 图；PCB、食品、多实例 | [Amazon Science](https://github.com/amazon-science/spot-diff) | [官方 S3 TAR](https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar) |
| Real-IAD | 30 类、约 150K 图；同一工件五视角 | [作者项目](https://realiad4ad.github.io/Real-IAD/) | [官方 Hugging Face](https://huggingface.co/datasets/Real-IAD/Real-IAD/tree/main)；需登录同意访问条件 |
| MVTec LOCO AD | 5 类、3,644 图；结构和逻辑异常 | [MVTec](https://www.mvtec.com/research-teaching/datasets/mvtec-loco-ad) | 官方页获取 |
| MVTec AD 2 | 8 场景、8,000+ 图；光照、细小缺陷、透明与重叠物体 | [MVTec](https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2) | 官方表单；私有测试使用[评测服务器](https://benchmark.mvtec.com/) |
| BTAD | 3 类、作者仓库约 1.8K 图；工业产品表面缺陷 | [作者仓库](https://github.com/pankajmishra000/VT-ADL) | [作者提供 ZIP](https://avires.dimi.uniud.it/papers/btad/btad.zip) |
| MPDD | 6 类、1,000+ 图；金属零件与复杂采集条件 | [作者仓库](https://github.com/stepanje/MPDD) | README 中的 SharePoint 下载入口 |
| MVTec 3D-AD | 10 类、4,000+ 次扫描；几何与外观 | [MVTec](https://www.mvtec.com/research-teaching/datasets/mvtec-3d-ad) | 官方页获取；应用当前不解析点云 |

来源差异需保留：

- VisA 作者区分原始布局与 `split_csv` 的不同设置，使用前先选择协议。数据许可为 CC BY 4.0，不能用代码许可替代。
- Real-IAD 的 1024 版约 53 GB、原始版约 507 GB，见作者项目页；同一工件多个视角不可跨训练与评估集合。
- BTAD 作者 README 列 400、1,000、399 张，二手基准常见其他数量。目录保留作者约数；[作者声明](https://github.com/pankajmishra000/VT-ADL#beantech-anomaly-detection-dataset---btad)为 CC BY-SA 4.0，不套用第三方库中的许可描述。
- MPDD 的[作者 LICENSE](https://github.com/stepanje/MPDD/blob/main/LICENSE)为 CC BY-NC-SA 4.0。这里指 Metal Parts Defect Detection，不是其他同名缩写。
- MVTec 系列的公开数据许可见各官网，均标 CC BY-NC-SA 4.0；AD 2 的部分测试真值不公开，不能据此声称可在本应用完成官方私有评测。

## 概览与操作

- 每张卡片提供真实的官方/作者样例总览、用途、规模、获取方式、许可和来源日期。图片可点开完整查看；加载失败保留来源页入口。
- 预览来自作者项目页、README 或论文图，按原图链接展示并署名，不生成看似真实的合成数据样例。论文图片的许可和数据许可分别看待。
- 搜索名称、用途和说明；按表面缺陷、逻辑异常、多视角或 3D 筛选。空结果可清除条件。
- 官方表单、登录和访问条款由用户在官方页面处理。不会后台下载整个数据集、自动解压或修改本地项目。
- 下载解压后可回首页创建本地项目并扫描。此路径仅登记文件；目录层次、train/val/test、normal/anomaly 与 mask 不会因图书馆入口被自动识别或导入。使用官方 benchmark 时先核对协议，尤其不要把 mask 目录当普通图片一起扫描。

## 维护约定

目录事实源为 [datasetLibrary.ts](../frontend/src/data/datasetLibrary.ts)，页面为 [DatasetLibraryPage.tsx](../frontend/src/pages/DatasetLibraryPage.tsx)。新增条目需提供作者/官方主页、可追溯获取入口、实际预览图来源、任务差异、许可依据和核对日期。

首版不做全学科目录、镜像托管、自动下载器、下载状态数据库或统一 benchmark 导入适配。没有完整下载数据，因此“入口已核对”不等于压缩包完整性或所有网络中的链接可用性验证。少量精选目录可在本地运行的应用中离线检索，远程图片和下载需要联网。

export interface DatasetLibraryEntry {
  id: string;
  name: string;
  year: number;
  summary: string;
  categoryCount: number;
  imageCountLabel: string;
  focus: "surface" | "logical" | "multiview" | "3d";
  highlights: string[];
  homepageUrl: string;
  downloadUrl: string;
  downloadLabel: string;
  accessNote: string;
  licenseLabel: string;
  licenseUrl?: string;
  previewUrl?: string;
  previewAlt: string;
  previewSourceUrl: string;
  previewCredit: string;
  notes: string[];
  verifiedAt: string;
}

// Editorial catalog: official dataset/project pages and author-published figures.
// This is resource discovery, not a downloader or a benchmark import adapter.
export const datasetLibrary: DatasetLibraryEntry[] = [
  {
    id: "mvtec-ad",
    name: "MVTec AD",
    year: 2019,
    summary: "物体与纹理表面缺陷的经典基准，适合先建立二维异常检测基线。",
    categoryCount: 15,
    imageCountLabel: "5,354 张图片",
    focus: "surface",
    highlights: ["物体与纹理", "正常训练", "像素标注"],
    homepageUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-ad",
    downloadUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-ad",
    downloadLabel: "官方获取入口",
    accessNote: "在官方页面填写表单后获取下载；不代填申请信息。",
    licenseLabel: "CC BY-NC-SA 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    previewUrl: "https://media.springernature.com/lw685/springer-static/image/art%3A10.1007%2Fs11263-020-01400-4/MediaObjects/11263_2020_1400_Fig2_HTML.png",
    previewAlt: "MVTec AD 作者论文中的 15 类物体和纹理正常、异常样例概览",
    previewSourceUrl: "https://link.springer.com/article/10.1007/s11263-020-01400-4",
    previewCredit: "Bergmann 等 · IJCV 2021 图 2（文章 CC BY 4.0）",
    notes: ["正常训练图片与含正常/异常的测试图片分开发布。", "官方默认划分不等于本应用要求的独立验证与测试方案；使用前应核对评估协议。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "visa",
    name: "VisA",
    year: 2022,
    summary: "覆盖 PCB、食品和多实例场景，适合观察复杂结构与位置变化下的异常。",
    categoryCount: 12,
    imageCountLabel: "10,821 张图片",
    focus: "surface",
    highlights: ["PCB", "多实例", "像素标注"],
    homepageUrl: "https://github.com/amazon-science/spot-diff",
    downloadUrl: "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar",
    downloadLabel: "官方 TAR 下载",
    accessNote: "Amazon 官方 S3 文件；下载较大，请在浏览器中选择保存位置。",
    licenseLabel: "CC BY 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
    previewUrl: "https://raw.githubusercontent.com/amazon-science/spot-diff/main/figures/VisA_samples.png",
    previewAlt: "VisA 官方 12 类物体、正常图片与异常样例概览",
    previewSourceUrl: "https://github.com/amazon-science/spot-diff#data-description",
    previewCredit: "Zou 等 / Amazon Science · VisA_samples",
    notes: ["含 9,621 张正常和 1,200 张异常图片。", "原始布局与作者提供的 1-class 划分不同；按官方 split_csv 选择协议，不把所有图片直接重新随机混分。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "real-iad",
    name: "Real-IAD",
    year: 2024,
    summary: "真实工业物体的多视角检测，适合研究同一工件不同相机视角的异常。",
    categoryCount: 30,
    imageCountLabel: "约 150,000 张图片",
    focus: "multiview",
    highlights: ["五视角", "工件分组", "真实工业"],
    homepageUrl: "https://realiad4ad.github.io/Real-IAD/",
    downloadUrl: "https://huggingface.co/datasets/Real-IAD/Real-IAD/tree/main",
    downloadLabel: "Hugging Face 获取",
    accessNote: "需登录 Hugging Face 并同意访问条件；作者页面说明申请自动批准。",
    licenseLabel: "CC BY-NC-SA 4.0",
    licenseUrl: "https://huggingface.co/datasets/Real-IAD/Real-IAD/blob/main/LICENSE.txt",
    previewUrl: "https://realiad4ad.github.io/Real-IAD/assets/images/sample_data.png",
    previewAlt: "Real-IAD 官方多类别工业物体与不同拍摄视角概览",
    previewSourceUrl: "https://realiad4ad.github.io/Real-IAD/",
    previewCredit: "Wang 等 · Real-IAD 项目页",
    notes: ["同一工件的多个视角必须作为一组处理，避免跨训练与评估集合。", "作者推荐的 1024 版本约 53 GB，原始高分辨率版本约 507 GB；下载前选择需要的分辨率。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "mvtec-loco-ad",
    name: "MVTec LOCO AD",
    year: 2022,
    summary: "同时考察结构缺陷和数量、位置、组合关系错误，适合逻辑异常研究。",
    categoryCount: 5,
    imageCountLabel: "3,644 张图片",
    focus: "logical",
    highlights: ["逻辑约束", "结构异常", "独立验证集"],
    homepageUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-loco-ad",
    downloadUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-loco-ad",
    downloadLabel: "官方获取入口",
    accessNote: "通过 MVTec 官方数据集页面获取，依页面要求填写表单。",
    licenseLabel: "CC BY-NC-SA 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    previewUrl: "https://media.springernature.com/lw685/springer-static/image/art%3A10.1007%2Fs11263-022-01578-9/MediaObjects/11263_2022_1578_Fig3_HTML.png",
    previewAlt: "MVTec LOCO AD 作者论文展示的五类场景与结构、逻辑异常",
    previewSourceUrl: "https://link.springer.com/article/10.1007/s11263-022-01578-9/figures/3",
    previewCredit: "Bergmann 等 · IJCV 2022 图 3（文章 CC BY 4.0）",
    notes: ["物体表面看似完好，也可能因数量、位置或组合不正确而属于异常。", "沿用官方正常训练/验证与测试语义，不将结构和逻辑异常混为同一难度结论。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "mvtec-ad-2",
    name: "MVTec AD 2",
    year: 2025,
    summary: "更具挑战的高分辨率场景，覆盖光照变化、透明物体、重叠和细小缺陷。",
    categoryCount: 8,
    imageCountLabel: "8,000+ 张图片",
    focus: "surface",
    highlights: ["高分辨率", "光照变化", "私有测试真值"],
    homepageUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2",
    downloadUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2",
    downloadLabel: "官方获取入口",
    accessNote: "官方表单获取数据；私有测试部分通过 MVTec 评测服务器评估。",
    licenseLabel: "CC BY-NC-SA 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    previewUrl: "https://arxiv.org/html/2503.21622v1/figure_mad2_objects.png",
    previewAlt: "MVTec AD 2 作者论文展示的八种工业异常检测场景",
    previewSourceUrl: "https://arxiv.org/html/2503.21622v1",
    previewCredit: "Heckler-Kram 等 · MVTec AD 2 作者预印本图 1",
    notes: ["训练和验证集均为无缺陷图片；公开与私有测试数据分别管理。", "本地应用可整理公开图片，不能代替官方私有测试评测；无公开真值的部分不能计算本地监督指标。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "btad",
    name: "BTAD",
    year: 2021,
    summary: "三类工业产品的 RGB 缺陷图片，规模较小，便于熟悉异常定位流程。",
    categoryCount: 3,
    imageCountLabel: "约 1.8K 张（作者仓库口径）",
    focus: "surface",
    highlights: ["工业产品", "RGB", "像素标注"],
    homepageUrl: "https://github.com/pankajmishra000/VT-ADL",
    downloadUrl: "https://avires.dimi.uniud.it/papers/btad/btad.zip",
    downloadLabel: "作者 ZIP 下载",
    accessNote: "作者仓库指向的大学托管 ZIP。",
    licenseLabel: "CC BY-SA 4.0（作者声明）",
    licenseUrl: "https://creativecommons.org/licenses/by-sa/4.0/",
    previewUrl: "https://raw.githubusercontent.com/pankajmishra000/VT-ADL/master/image/bt_anomaly_dataset.png",
    previewAlt: "BTAD 作者仓库中的三类工业产品正常和缺陷样例",
    previewSourceUrl: "https://github.com/pankajmishra000/VT-ADL#beantech-anomaly-detection-dataset---btad",
    previewCredit: "Mishra 等 / BeanTech · VT-ADL 项目页",
    notes: ["作者 README 列出 400、1,000、399 张图片；其他基准常见不同统计口径，实验应记录实际所用版本。", "许可按作者数据集说明查看，不使用算法代码的 MIT 许可代替数据许可。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "mpdd",
    name: "MPDD",
    year: 2021,
    summary: "金属零件缺陷检测，包含复杂姿态和背景，适合观察实际采集条件的影响。",
    categoryCount: 6,
    imageCountLabel: "1,000+ 张图片",
    focus: "surface",
    highlights: ["金属零件", "复杂背景", "像素标注"],
    homepageUrl: "https://github.com/stepanje/MPDD",
    downloadUrl: "https://vutbr-my.sharepoint.com/:f:/g/personal/xjezek16_vutbr_cz/EhHS_ufVigxDo3MC6Lweau0BVMuoCmhMZj6ddamiQ7-FnA?e=oHKCxI",
    downloadLabel: "作者下载入口",
    accessNote: "作者 README 提供的 SharePoint 文件夹；若分享失效，可从官方仓库查最新入口。",
    licenseLabel: "CC BY-NC-SA 4.0（作者仓库）",
    licenseUrl: "https://github.com/stepanje/MPDD/blob/main/LICENSE",
    previewUrl: "https://raw.githubusercontent.com/stepanje/MPDD/main/samples.png",
    previewAlt: "MPDD 作者提供的六类金属零件及其缺陷样例概览",
    previewSourceUrl: "https://github.com/stepanje/MPDD",
    previewCredit: "Jezek 等 · MPDD 作者仓库",
    notes: ["作者将异常无关训练样本与含正常/异常的评估子集分开发布。", "此处 MPDD 指 Metal Parts Defect Detection，不是同缩写的其他学科数据集。"],
    verifiedAt: "2026-11-06"
  },
  {
    id: "mvtec-3d-ad",
    name: "MVTec 3D-AD",
    year: 2022,
    summary: "提供工业传感器采集的三维形状与外观，供 RGB 与几何信息联合研究。",
    categoryCount: 10,
    imageCountLabel: "4,000+ 次高分辨率扫描",
    focus: "3d",
    highlights: ["三维几何", "RGB", "扩展阅读"],
    homepageUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-3d-ad",
    downloadUrl: "https://www.mvtec.com/research-teaching/datasets/mvtec-3d-ad",
    downloadLabel: "官方获取入口",
    accessNote: "通过官方页面获取；本应用当前不解析点云或运行三维算法。",
    licenseLabel: "CC BY-NC-SA 4.0",
    licenseUrl: "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    previewUrl: "https://arxiv.org/html/2112.09045v1/dataset_overview.jpg",
    previewAlt: "MVTec 3D-AD 作者论文展示的十类物体与三维扫描样例",
    previewSourceUrl: "https://arxiv.org/abs/2112.09045",
    previewCredit: "Bergmann、Sattlegger、Steger · MVTec 3D-AD 作者论文图 2",
    notes: ["当前作为资源介绍收录，不代表应用已支持 3D 数据解析或三维评估。", "数据包含无缺陷训练/验证及带缺陷的测试扫描，使用时保持其几何与外观的对应关系。"],
    verifiedAt: "2026-11-06"
  }
];

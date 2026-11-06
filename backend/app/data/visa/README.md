# VisA 官方单类划分索引

`1cls.csv` 原样来自 Amazon Science 的 SPot-the-Difference / VisA 仓库：

- 来源：https://github.com/amazon-science/spot-diff/blob/6dbf63c1f0ac62140e506753e68b4fecb437a5ff/split_csv/1cls.csv
- 对应文件提交：`6dbf63c1f0ac62140e506753e68b4fecb437a5ff`
- 获取日期：2026-11-06
- 作者：Yang Zou、Jongheon Jeong、Latha Pemula、Dongqing Zhang、Onkar Dabeer。

只捆绑对象、图片相对路径、正常/异常标签、训练/测试划分及 mask 相对路径，不含任何图片。用于本地 VisA 原始目录缺少 `split_csv/1cls.csv` 时离线识别官方单类协议；用户目录中的同名索引优先。不会随机重划分或制造验证集。

官方 NOTICE 将数据声明为 CC BY 4.0，工具代码为 Apache-2.0；本目录保留 `NOTICE`、`LICENSE-DATASET` 及仓库 `LICENSE`。本文件为 Dataset Manager 添加的来源说明，CSV 未修改。

# ELI CHEN 2025 文件夹分配测试

日期：2026-11-10。负责人：用户指定 `jacqueline`。客户年度工作区 ID：2。

来源：用户指定的共享目录 `\\caryserver\onedrive - ta\Cary Database\Tax Returns Prior Years\2025 TAX RETURN\2025 CHEN,ELI`。共享原件未修改，`Thumbs.db` 忽略。原始资料路径已写入 CRM。

## 资料分配

| 资料项目 | 来源 | 关联 |
|---|---|---|
| W-2 · AT&T Services, Inc. | W-2 PDF，两页 | 第1页为表格，第2页为说明 |
| W-2 · SHOGUN INC. | JPG，一张 | 原始 JPG 路径 + 本机生成的 PDF 预览副本 |
| Robinhood · 1099-DIV | 综合1099，32页 | 第3页 |
| Robinhood · 1099-INT | 同上 | 第4页，另关联第25页 |
| Robinhood · 1099-B | 同上 | 第5页开始；第5–23页需进一步判断汇总与交易明细 |

`8879 signed.pdf` 另登记为签字授权文件，不创建收入记录；未验证签字的有效性。当前没有完整1040或ProSeries客户文件，因此税表文件夹和ProSeries路径未臆造。

共管理4份PDF（其中1份为JPG预览副本）、36页、5个已收资料项目、7条文件/页面关联。两份W-2属于不同雇主，分别保留。

## 识别实际结果与限制

PDF读取采用PyMuPDF；扫描OCR入口使用Tesseract。本机未检测到Tesseract，AT&T扫描W-2和JPG不能宣称自动识别成功。两条W-2记录为人工查看原页后填入的待核对候选，备注和审计事件已注明；所有记录保持待核对，空白不自动当零，未将本次测试作为审核通过。

Robinhood的部分页面可以直接读取文字，但提取规则不覆盖全部证券版式。汇总/明细及不同子账户需要人工核对，不能将所有页面候选重复计入。此次验证的是资料分配、文件关联和负责人设置，不是完整税务复核。

JPG在共享目录保留原件；系统备份保存的是生成的PDF预览副本，不包含该外部JPG原件。外部路径登记不等于外部文件备份。

## 负责人功能

新增侧栏“负责人名单”，可添加名称；客户概况的负责人改为下拉选择，并有“新增负责人”入口。新增后选中仍需保存概况，避免无意修改客户。名单不会创建登录账号；只读员工不能新增。名称去重不区分大小写，旧负责人可迁移到名单。

## 验证

- 62项自动测试通过，含新增名单去重、旧数据迁移、认证API权限验证。
- 页面JavaScript语法检查通过。
- 实际导入检查：4份文件均处理完成、5个项目、7条关联，负责人为jacqueline。
- 结果：`.sample-1040-qa/chen-eli/result.json`。
- 导入前完整备份：`.sample-1040-qa/pre-chen-eli-import.zip`。包含私密客户资料，不用于分发。

详细OCR组件：Tesseract 官方仓库 <https://github.com/tesseract-ocr/tesseract>；PyMuPDF 官方仓库 <https://github.com/pymupdf/PyMuPDF>。表格分类和字段提取为本项目 `core.py`、`extract.py` 中的规则。

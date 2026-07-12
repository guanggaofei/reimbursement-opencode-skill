---
name: reimbursement
description: "Trigger when the user indicates they are executing the reimbursement workflow."
---

# 报销流程（Windows）

本入口与 Unix 版使用相同的数据契约和输出布局。所有相对路径均以 `--root` 指定的项目根目录解析。

## 核心规则

1. 默认顺序执行；bundled 脚本出现未说明错误时停止。
2. 所有值必须来自 PDF、截图 OCR、用户确认或脚本结果。
3. `invoice_results.json` 仅允许通过修复脚本更新；`invoice_results_sorted.json` 和 `invoice_errors.json` 只读。
4. 不复制、改名或迁移 `super_invoice.py` 生成的三个 JSON 与 `output/`。
5. 安装 Python 包前列出包名、原因和完整命令，并等待用户批准。

## 文件布局

根目录保存 `invoices/`、`images/`、`output/`、三个发票 JSON、`OCR缓存.json`、`匹配记录.json`、历史报账单、`支出记录OCR整理结果.md`、`待审核截图/`、两份最终 Office 文件、可选 ZIP、可选支付说明报告和合并 PDF。

`报销工作文件/` 保存 `invoice_errors_raw.json`、`invoice_fixes.json`、`行程单数据.json`、OCR 匹配明细、DOCX 技术报告、action JSON、未打包的支付材料和解包/XML 调试文件。

## 自动化流程

### 1. 清理派生产物

保留原始输入、`OCR缓存.json`、`匹配记录.json`、历史报账单和 skill 文件：

```powershell
Remove-Item -Recurse -Force output, 报销工作文件, 待审核截图 -ErrorAction SilentlyContinue
Remove-Item -Force invoice_results.json, invoice_results_sorted.json, invoice_errors.json, 支出记录OCR整理结果.md, 支付说明生成结果.md -ErrorAction SilentlyContinue
Remove-Item -Force 'Hello World 2026报账单填写结果.xlsx', 'Hello World 2026支出记录填写结果.docx', 支付说明与支付记录.zip, 辰景发票.zip, 合并发票_纵向居中.pdf -ErrorAction SilentlyContinue
```

### 2. 输入、提取与修复

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\check_taxi_pairs.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\super_invoice.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\check_invoice_errors.py --root .
```

错误列表位于 `报销工作文件/invoice_errors_raw.json`。`@fix-invoice-errors` 将修复写入 `报销工作文件/invoice_fixes.json`，随后运行：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_invoice_fixes.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\check_invoice_errors.py --root .
```

错误数不下降或字段无法可靠确定时停止。历史报账单存在时运行 `cross_batch_dedup.py --root .`，再重新生成最终 `invoice_results_sorted.json`、`invoice_errors.json` 和 `output/`。

### 3. 行程、OCR 与匹配

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\extract_trip_sheets.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\organize_expense_records.py --root .
```

行程 JSON 与 OCR 技术明细写入 `报销工作文件/`；缓存、匹配状态和 `支出记录OCR整理结果.md` 保留在根目录。subagent action JSON 写入 `报销工作文件/`，并通过下列命令合入：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_match_actions.py --root . --actions 报销工作文件\<agent-name>.actions.json
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root . --update-report
```

仍未匹配的原图复制到根目录 `待审核截图/`，不移动或重命名 `images/` 原图。

### 4. 生成文档

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_expense_record_docx.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_record_docx.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_explanations.py --root . --date YYYY-M-D
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_reimbursement_xlsx.py --root .
```

最终 DOCX/XLSX 和需要保留的支付说明报告位于根目录；支付记录、支付说明、DOCX 技术报告及解包调试文件位于 `报销工作文件/`。

### 5. 打包和合并

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\package_final_outputs.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\merge_output_pdfs.py --root .
```

支付材料 DOCX 打包为根目录 `支付说明与支付记录.zip`；`output/4_辰景发票/` 的 PDF 打包为根目录 `辰景发票.zip`。空内容不会生成 ZIP，并会删除旧 ZIP。合并脚本只读取 `output/1_材料费/` 和 `output/2_打车费/`，在根目录生成 `合并发票_纵向居中.pdf`。

### 6. 验证

验证 Office 文件和 ZIP 结构；确认 ZIP 仅含目标 DOCX/PDF，`super_invoice.py` 输出名称不变，内部文件均进入 `报销工作文件/`，空材料不会留下旧 ZIP。

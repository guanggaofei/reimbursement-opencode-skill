---
name: reimbursement
description: "Trigger when the user indicates they are executing the reimbursement workflow."
---

# 报销流程（Linux/macOS）

## 核心规则

1. 默认从步骤 1 顺序执行；仅在用户明确指定起点时跳转。
2. bundled 脚本出现未说明的错误时停止并报告。
3. 所有写入值必须来自 PDF、截图 OCR、用户确认或脚本结果，不猜测。
4. `invoice_results.json` 仅允许通过修复脚本更新；`invoice_results_sorted.json` 和 `invoice_errors.json` 只读。
5. 不复制、重命名或迁移 `super_invoice.py` 生成的三个 JSON 与 `output/`。

## 环境

使用项目 `.venv`。安装 Python 包前必须列出包名、原因和完整命令，并等待用户批准。所需能力包括 `pdfplumber`、`rapidocr-onnxruntime`、`onnxruntime`、`Pillow`、`pypinyin`、`pypdf`、`python-docx`、`lxml`；系统需提供 `pdftotext`。

## 路径约定

根目录保存输入、稳定状态、用户报告和最终产物：

- `invoices/`、`images/`、`output/`
- `invoice_results.json`、`invoice_results_sorted.json`、`invoice_errors.json`
- `OCR缓存.json`、`匹配记录.json`
- 历史 `第x批报账单.xlsx`
- `支出记录OCR整理结果.md`、`待审核截图/`
- `支付说明生成结果.md`（存在相应分组时）
- `Hello World 2026报账单填写结果.xlsx`
- `Hello World 2026支出记录填写结果.docx`
- `支付说明与支付记录.zip`、`辰景发票.zip`（有内容时）
- `合并发票_纵向居中.pdf`

`报销工作文件/` 仅保存代理内部文件：

- `invoice_errors_raw.json`、`invoice_fixes.json`、`行程单数据.json`
- `支出记录OCR匹配明细.md`、`支出记录DOCX生成结果.md`、`OCR缓存原文.md`
- 所有 subagent action JSON
- `支付记录/`、`支付说明/` 及其中的 DOCX
- DOCX 解包、XML 调试文件和其他临时产物

## 自动化流程

### 1. 清理本轮派生产物

保留 `invoices/`、`images/`、`OCR缓存.json`、`匹配记录.json`、历史报账单和 skill 文件。清理其余本轮派生产物：

```bash
rm -rf output/ 报销工作文件/ 待审核截图/
rm -f invoice_results.json invoice_results_sorted.json invoice_errors.json
rm -f 支出记录OCR整理结果.md 支付说明生成结果.md
rm -f 'Hello World 2026报账单填写结果.xlsx' 'Hello World 2026支出记录填写结果.docx'
rm -f 支付说明与支付记录.zip 辰景发票.zip 合并发票_纵向居中.pdf
```

### 2. 验证输入与出租车配对

确认 `invoices/` 和 `images/` 存在，然后运行：

```bash
python .opencode/skills/reimbursement/scripts/check_taxi_pairs.py --root .
```

### 3. 运行发票提取并修复字段

```bash
python .opencode/skills/reimbursement/scripts/super_invoice.py --root .
python .opencode/skills/reimbursement/scripts/check_invoice_errors.py --root .
```

`check_invoice_errors.py` 写入 `报销工作文件/invoice_errors_raw.json`。若其中 `error_count > 0`，调用 `@fix-invoice-errors`；subagent 只读取该错误列表，并写入 `报销工作文件/invoice_fixes.json`。然后执行：

```bash
python .opencode/skills/reimbursement/scripts/apply_invoice_fixes.py --root .
python .opencode/skills/reimbursement/scripts/check_invoice_errors.py --root .
```

最多修复 3 轮；错误数不下降或字段无法可靠确定时停止。若根目录存在历史 `第x批报账单.xlsx`，运行 `cross_batch_dedup.py --root .`，然后重新执行本步骤。最终再次运行 `super_invoice.py --root .`，确认它仍只生成根目录 `invoice_results.json`、`invoice_results_sorted.json`、`invoice_errors.json` 和 `output/`。

### 4. 提取行程数据

```bash
python .opencode/skills/reimbursement/scripts/extract_trip_sheets.py --root .
```

输出 `报销工作文件/行程单数据.json`。

### 5. OCR 与截图匹配

OCR 可能耗时很长，禁止由代理直接运行 `organize_expense_records.py`，以免 opencode 超时终止进程。代理必须暂停流程，请用户在自己的终端中运行，并等待用户确认完成后再继续。

面向不熟悉终端的用户时，按以下方式说明：

1. 告诉用户按 `Ctrl+Alt+T` 打开终端；macOS 用户按 `Command+空格`，输入“终端”并打开。
2. 根据当前项目根目录生成一条可直接复制的完整命令，路径必须替换为实际绝对路径，不得保留占位符：

```bash
cd "/实际的项目根目录" && .venv/bin/python .opencode/skills/reimbursement/scripts/organize_expense_records.py --root .
```

3. 告诉用户把整行命令复制到终端，按回车后不要关闭终端，等待看到“OCR 处理完成”。
4. 告诉用户完成后回到 opencode 回复“运行完成”。用户确认前不得继续后续步骤。
5. 告诉用户如果运行意外中断，重新执行同一行命令即可；脚本会读取 `OCR缓存.json`，已识别的图片不需要重做。

读取根目录输入、三个 JSON、`output/` 与稳定缓存，写入：

- 根目录 `OCR缓存.json`、`匹配记录.json`、`支出记录OCR整理结果.md`
- `报销工作文件/支出记录OCR匹配明细.md`

新增少量截图时也由用户按上述方式运行单行命令，并在末尾添加 `--scan-only`。对于金额歧义、行程歧义、重复截图和无截图发票，分别调用对应 subagent。每个 subagent 将 action JSON 写入 `报销工作文件/`，再用：

```bash
python .opencode/skills/reimbursement/scripts/apply_match_actions.py --root . --actions 报销工作文件/<agent-name>.actions.json
```

运行覆盖率检查并刷新根目录用户报告：

```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root . --update-report
```

将仍在 `匹配记录.json` 的 `未匹配截图[]` 中的原图复制到根目录 `待审核截图/`，不移动或改名原图。

### 6. 生成 DOCX 与 XLSX

```bash
python .opencode/skills/reimbursement/scripts/generate_expense_record_docx.py --root .
python .opencode/skills/reimbursement/scripts/generate_payment_record_docx.py --root .
python .opencode/skills/reimbursement/scripts/generate_payment_explanations.py --root . --date YYYY-M-D
python .opencode/skills/reimbursement/scripts/generate_reimbursement_xlsx.py --root .
```

生成位置：

- 根目录 `Hello World 2026支出记录填写结果.docx`
- `报销工作文件/支出记录DOCX生成结果.md`
- `报销工作文件/支付记录/*.docx`
- `报销工作文件/支付说明/*.docx` 及其解包调试目录
- 根目录 `支付说明生成结果.md`（存在需要确认或查看的分组时保留）
- 根目录 `Hello World 2026报账单填写结果.xlsx`

支付说明仅以 `invoice_errors.json` 中明确要求同时添加支付说明与支付记录的分组为入口。无法可靠确定收款方时停止该组，不猜测。

### 7. 打包与合并 PDF

```bash
python .opencode/skills/reimbursement/scripts/package_final_outputs.py --root .
python .opencode/skills/reimbursement/scripts/merge_output_pdfs.py --root .
```

`package_final_outputs.py`：

- 将 `报销工作文件/支付记录/` 与 `报销工作文件/支付说明/` 中的 DOCX 打包为根目录 `支付说明与支付记录.zip`。
- 将 `output/4_辰景发票/` 中的 PDF 打包为根目录 `辰景发票.zip`。
- 空内容不生成 ZIP，并删除残留的同名旧 ZIP。

`merge_output_pdfs.py` 只读取根目录 `output/1_材料费/` 和 `output/2_打车费/`，生成根目录 `合并发票_纵向居中.pdf`。

### 8. 验证

确认最终 DOCX/XLSX/ZIP 可作为 ZIP 打开；ZIP 仅包含目标 DOCX/PDF。确认 `super_invoice.py` 的四类输出目录和三个 JSON 文件名未改变，内部文件均位于 `报销工作文件/`，且空材料不会留下旧 ZIP。

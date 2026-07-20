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

## 环境

先运行 `py -3 --version`，确认 Python 为 3.10 或更高版本且可使用 `venv` 和 `pip`。使用项目 `.venv`；不存在时运行 `py -3 -m venv .venv`，创建失败时停止并报告。所需 Python 包包括 `pdfplumber`、`rapidocr-onnxruntime`、`onnxruntime`、`Pillow`、`pypinyin`、`pypdf`、`python-docx`、`lxml`。

开始流程前通过 `Get-Command pdftotext,pdftoppm` 确认两个 Poppler 命令均可执行；任一缺失时停止并告知用户安装 Poppler 并将其 `Library\bin` 加入 `PATH`，不自行安装系统软件。
源 PDF 使用未嵌入的中文字体时，Poppler 必须能访问对应字体；出现字体创建失败时停止并报告具体 PDF，不继续生成缺字文档。

缺少 Python 包时，先向用户列出缺少的包、用途和完整安装命令并等待批准。完整环境安装命令为：

```powershell
.\.venv\Scripts\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pdfplumber rapidocr-onnxruntime onnxruntime Pillow pypinyin pypdf python-docx lxml
```

只缺少部分包时仅安装缺少项，不重复安装全部依赖。所有 Python 脚本必须通过 `.\.venv\Scripts\python.exe` 调用，禁止使用系统 `python` 或 `python3`。

## 文件布局

根目录保存 `invoices/`、`images/`、`output/`、三个发票 JSON、`OCR缓存.json`、`匹配记录.json`、历史报账单、`支出记录OCR整理结果.md`、`待审核截图/`、两份最终 Office 文件、可选支付说明报告和合并 PDF。

`报销工作文件/` 保存 `invoice_errors_raw.json`、`invoice_fixes.json`、`行程单数据.json`、`截图问题统计.json`、OCR 匹配明细、DOCX 技术报告、action JSON、未打包的支付材料和解包/XML 调试文件。

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

最多修复 3 轮；错误数不下降或字段无法可靠确定时停止。历史报账单存在时运行 `cross_batch_dedup.py --root .`，再重新生成最终 `invoice_results_sorted.json`、`invoice_errors.json` 和 `output/`。

### 3. 行程、OCR 与匹配

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\extract_trip_sheets.py --root .
```

OCR 可能耗时很长，禁止由代理直接运行 `organize_expense_records.py`，以免 opencode 超时终止进程。代理必须暂停流程，请用户在自己的终端中运行，并等待用户确认完成后再继续。

面向不熟悉终端的用户时，按以下方式说明：

1. 告诉用户按 `Win+R`，输入 `powershell`，再按回车打开终端。
2. 根据当前项目根目录生成一条可直接复制的完整命令，路径必须替换为实际绝对路径，不得保留占位符：

```powershell
Set-Location -LiteralPath 'C:\实际的项目根目录'; & .\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\organize_expense_records.py --root .
```

3. 告诉用户把整行命令复制到 PowerShell，按回车后不要关闭窗口，等待看到“OCR 处理完成”。
4. 告诉用户完成后回到 opencode 回复“运行完成”。用户确认前不得继续后续步骤。
5. 告诉用户如果运行意外中断，重新执行同一行命令即可；脚本会读取 `OCR缓存.json`，已识别的图片不需要重做。

新增少量截图时也由用户运行同一条单行命令，并在末尾添加 `--scan-only`。

行程 JSON 与 OCR 技术明细写入 `报销工作文件/`；缓存、匹配状态和 `支出记录OCR整理结果.md` 保留在根目录。subagent 只写 action JSON，由主流程通过下列命令合入：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_match_actions.py --root . --actions 报销工作文件\<agent-name>.actions.json
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root . --update-report --issue-summary-json 报销工作文件\截图问题统计.json
```

按“店铺名称歧义 → 行程歧义 → 重复截图”的顺序处理，禁止并行写 action。对应 subagent 分别为 `@fix-shop-name-ambiguity`、`@fix-trip-ambiguity`、`@fix-duplicate-screenshots`。

每一类型最多处理 3 轮。每轮读取 `截图问题统计.json` 中该类型的轮前数量，只把当前仍未解决的条目交给一个新的同类型 subagent；应用 action 后重新运行覆盖率检查。轮后数量下降且仍大于 0 时继续；降为 0 时完成；数量未下降、无可靠 action 或达到 3 轮时停止该类型并报告残留。

`@fix-bearing-invoice` 只处理“完全无截图发票”，在上述循环之后最多调用一次，不执行收敛重试。应用其 action 后再次刷新报告与分类计数。

仍未匹配的原图复制到根目录 `待审核截图/`，不移动或重命名 `images/` 原图。

### 4. 生成文档

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_expense_record_docx.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_record_docx.py --root .
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_explanations.py --root . --date YYYY-M-D
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_reimbursement_xlsx.py --root .
```

最终 DOCX/XLSX 和需要保留的支付说明报告位于根目录；支付记录、支付说明、DOCX 技术报告及解包调试文件位于 `报销工作文件/`。

报账单的“数量”和“单价”按以下规则填写：从原发票 PDF 读取第一条项目的数量；数量为非整数时取 `int`，数量栏为空时填 `1`；单价填写“价税合计金额 ÷ 处理后的数量”。处理后的数量必须大于 0，单价不得超过 1000 元，否则停止并报告。

上述 DOCX 与 XLSX 命令完成后、进入步骤 5 前，必须立即读取最新的 `支出记录OCR整理结果.md` 和 `匹配记录.json`，向用户告知截图匹配缺口：

- 逐张列出完全未匹配或截图不完整的发票，包括 `invoices/<原发票文件名>`、输出中的发票文件名、金额和缺失位置（`支付记录` 或 `账单截图`）。
- 打车发票必须精确到行程序号，并列出该行程缺少的截图位置。
- 对每个缺失位置，列出 `匹配记录.json` 中原因明确指向该发票或行程的候选截图原路径，如 `images/IMG_1234.png`；没有可靠候选时明确写“未找到候选截图”，不得仅凭相同金额猜测。
- 另列出仍在 `未匹配截图[]` 中的每张截图原路径和原因，确保用户能精确定位需要核对的图片。
- 即使没有缺口，也要明确告知“所有发票截图已完整匹配”。该告知是进度通知，不中断后续合并流程，除非用户要求暂停。

### 5. 合并 PDF

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\merge_output_pdfs.py --root .
```

命令完成后，提示用户检查 `报销工作文件/支付记录/` 和 `报销工作文件/支付说明/` 中的 DOCX，将文件名及文档内容里的 `xxx` 改为自己的姓名。

### 6. 验证

确认最终 DOCX/XLSX 可作为 ZIP 打开。确认报账单中每行数量和单价已填写、数量为正数、单价不超过 1000 元，且数量乘单价与发票金额在允许精度内一致。确认合并 PDF 可正常打开且页面内容完整。确认 `super_invoice.py` 输出名称不变，内部文件均进入 `报销工作文件/`。不自动创建任何 ZIP。

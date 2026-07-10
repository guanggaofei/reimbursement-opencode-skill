---
name: reimbursement
description: "Trigger when the user indicates they are executing the reimbursement workflow."
---

# 报销流程

## 核心规则

1. 你必须严格遵守流程，始终从步骤 1 开始顺序执行整个流程，不跳过任何步骤。除非用户明确指定从某一步开始。
2. **遇到未知错误立即停止。** 如果 bundled 脚本产生的错误信息不在本 skill 描述范围内，立即停止并向用户询问。
3. **绝不猜测 — 每个值必须有来源。** 如果任何字段含义、匹配规则、文件路径或操作决策存在歧义，直接询问用户。不要推断、假设或编造任何值。每一个写入的值必须可追溯到 PDF、截图 OCR 文本、用户确认或脚本输出。
4. **JSON 文件权限：**
   - `invoice_results.json` — 在修复 `ERROR` / `需人工校验` 字段时允许修改（中间产物）。
   - `invoice_results_sorted.json` — 只读。绝不修改。
   - `invoice_errors.json` — 只读。绝不修改。
5. 生成标题或文件名时，使用 `xxx` 代替任何人名。

## 环境准备

### Python 环境

本文件适用于 Linux 和 macOS。项目依赖安装在 `.venv` 中的 Python 包。opencode 自身执行脚本时会自动使用 `.venv`。**当告知 Linux/macOS 用户手动运行命令时（如 OCR 步骤），必须在命令前加上 `source .venv/bin/activate &&`** 以确保使用正确的虚拟环境。

若用户未指定且项目根目录不存在 `.venv` 目录，自动创建：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 所需 Python 包

- `pdftotext`（**系统二进制**，来自 Poppler，通过 `subprocess` 调用）用于 PDF 文本提取。Linux 可通过 `apt install poppler-utils` 安装；macOS 可通过 `brew install poppler` 安装。
- `pdfplumber` 作为 PDF 回退读取方案（当 pdftotext 不可用时）。
- `rapidocr-onnxruntime` 和 `onnxruntime` 用于费用截图 OCR。
- `Pillow` 用于生成 DOCX 时的图片处理。
- `pypinyin` 用于 `super_invoice.py` 中的汉字转拼音。
- `python-docx` 用于生成支付记录 DOCX。
- `lxml` 用于 XML 级别的 xlsx 和 DOCX 编辑。

安装任何 Python 包前，说明包名、原因和安装命令，请求用户批准并等待明确确认。安装命令必须使用清华大学 PyPI 镜像源：`-i https://pypi.tuna.tsinghua.edu.cn/simple`。

### 内置脚本

| 脚本 | 用途 |
|--------|---------|
| `scripts/check_taxi_pairs.py` | 验证行程单文件名与对应发票文件名是否配对（步骤3）。 |
| `scripts/super_invoice.py` | 发票提取、排序、PDF 分类。 |
| `scripts/cross_batch_dedup.py` | 与之前的 `第x批报账单.xlsx` 进行跨批去重。 |
| `scripts/organize_expense_records.py` | 费用截图的 OCR 和匹配。维护 `匹配记录.json`，所有截图引用使用 `images/` 原文件名；`--scan-only` 增量处理新增图片。 |
| `scripts/generate_expense_record_docx.py` | 费用记录 DOCX 表格生成器。 |
| `scripts/generate_payment_record_docx.py` | 支付记录 DOCX 生成器。 |
| `scripts/generate_reimbursement_xlsx.py` | XML 级别的报销 xlsx 填充器。 |
| `scripts/generate_payment_explanations.py` | XML 级别的支付说明 DOCX 生成器。 |
| `scripts/extract_trip_sheets.py` | 从行程单 PDF 中提取行程数据到 JSON。 |
| `scripts/check_invoice_errors.py` | 遍历 `invoice_results.json`，检测 `ERROR`、`需人工校验` 和空 `开票时间`，输出 `invoice_errors_raw.json`。 |
| `scripts/apply_invoice_fixes.py` | 将 `invoice_fixes.json` 中的修复批量写入 `invoice_results.json`（步骤 5）。 |
| `scripts/apply_match_actions.py` | 将 subagent 生成的截图匹配 action JSON 合入 `匹配记录.json`，并强制截图唯一性规则。 |
| `scripts/verify_screenshot_coverage.py` | 验证截图覆盖率，读取 `匹配记录.json` 与 `invoice_results_sorted.json` + `行程单数据.json` 交叉比对，输出缺失报告（步骤 8）。 |

### 内置 subagent（文件位于 `.opencode/agents/`）

| subagent | 用途 |
|----------|------|
| `fix-invoice-errors.md` | 修复 `invoice_errors_raw.json` 中列出的发票 ERROR / 需人工校验 / 空开票时间字段（步骤 5）。 |
| `fix-shop-name-ambiguity.md` | 金额对应多个候选发票时，通过店铺名称消除歧义（类型 A） |
| `fix-trip-ambiguity.md` | 金额对应多个候选行程时，通过服务商+时间消除歧义（类型 B） |
| `fix-duplicate-screenshots.md` | 多张截图匹配同一发票时，检查是否为重复截图（类型 C） |
| `fix-bearing-invoice.md` | 完全无截图的发票，通过搜索 OCR 关键词找到缺失截图（类型 D） |

### 内置资源

- `assets/templates/` — 内置模板；无需在根目录放置模板。

### 项目输入目录

以下目录预设于项目根目录（`--root`），在运行任何工作流步骤前必须存在：

- `invoices/` 存放发票 PDF 和出租车行程单。
- `images/` 存放运行 OCR 时的费用截图。

## 发票工作流

**必须遵守核心规则**

### 1. 清理输出文件

若非用户指定起始步骤，则删除工作流输出的所有产物，确保从干净状态开始：

**不要查看文件内容，直接删除**

```bash
rm -rf output/
rm -f invoice_results.json invoice_results_sorted.json invoice_errors.json
rm -f 行程单数据.json
rm -f 支出记录OCR整理结果.md 支出记录OCR匹配明细.md
rm -f Hello World 2026报账单填写结果.xlsx Hello World 2026支出记录填写结果.docx 支出记录DOCX生成结果.md
rm -rf 支付记录/ 支付说明/
```

保留 `invoices/`、`images/`、`OCR缓存.json`、`匹配记录.json`、`第x批报账单.xlsx`、`.opencode/skills/reimbursement/` 和 `.venv/` 不受影响。`匹配记录.json` 是跨批次复用的稳定匹配状态，不得在清理步骤删除。

### 2. 确认项目结构

验证项目根目录存在 `invoices/` 和 `images/`，验证python环境正常。

### 3. 检查出租车发票配对

你必须运行脚本自动验证行程单 ↔ 发票的文件名配对：

```bash
python .opencode/skills/reimbursement/scripts/check_taxi_pairs.py --root .
```

- exit 0：全部配对成功，直接进入下一步。
- exit 1：列出缺失发票的行程单，告知用户自行修改文件名后重新运行。

### 4. 清理 + 运行 super_invoice

发票数量任何变化都会使下游输出失效。手动删除过期输出：

```bash
rm -rf output/
rm -f invoice_results.json invoice_results_sorted.json invoice_errors.json
```

然后运行 super_invoice：

```bash
python .opencode/skills/reimbursement/scripts/super_invoice.py --root .
```

`super_invoice.py` 自动处理批内去重 — 它会检测重复的发票号码，将其从 `invoice_results.json` 中移除，并将对应的 PDF 重命名为 `.backup`。将重复发票号码警告视为去重操作，而非导入失败。

`OCR缓存.json` 在多次运行间保留 — 任何步骤都不会删除它。

super_invoice 运行后，若存在 `invoice_fixes.json`（先前修复记录），自动套用：

```bash
if [ -f invoice_fixes.json ]; then
    python .opencode/skills/reimbursement/scripts/apply_invoice_fixes.py --root .
fi
```

#### 4.5. 自动检测发票错误

`super_invoice.py` 运行后，无论 stdout 是否出现 `ERROR`，都必须运行结构化错误检测：

```bash
python .opencode/skills/reimbursement/scripts/check_invoice_errors.py --root .
```

该脚本写入 `invoice_errors_raw.json`。退出码 0 表示无错误；退出码 1 表示检测到需要修复的字段；退出码 2 表示检测脚本自身失败。若退出码 2，立即停止并报告用户。若 `invoice_errors_raw.json` 中 `error_count > 0`，进入步骤 5；否则跳过步骤 5。

### 5. 修复 ERROR / 需人工校验

当 `invoice_errors_raw.json` 中 `error_count > 0` 时，使用 subagent `@fix-invoice-errors` 修复。主流程不要手工 grep 或重组错误列表；subagent 必须直接读取 `invoice_errors_raw.json`，只修复其中 `errors[]` 列出的字段，并将修复写入 `invoice_fixes.json`。

修复循环最多执行 3 轮：

1. 记录当前 `invoice_errors_raw.json.error_count`。
2. 调用 `@fix-invoice-errors`。
3. 若 subagent 报告无法处理的错误，立即停止并报告用户。
4. 主流程运行 `apply_invoice_fixes.py` 写入修复：
   ```bash
   python .opencode/skills/reimbursement/scripts/apply_invoice_fixes.py --root .
   ```
   脚本执行类型校验（金额非负、税号长度≥15等），写入修复并保留 `invoice_fixes.json` 作为审计记录。若脚本失败，立即停止并报告用户。
5. 再次运行错误检测：
   ```bash
   python .opencode/skills/reimbursement/scripts/check_invoice_errors.py --root .
   ```
6. 若新的 `error_count == 0`，步骤 5 完成。
7. 若新的 `error_count > 0` 但没有下降，立即停止并报告用户，不要无限重试。
8. 若新的 `error_count > 0` 且有下降，继续下一轮修复。

超过 3 轮仍有错误时，停止并向用户展示 `invoice_errors_raw.json` 中剩余错误。

### 6. 跨批去重

若项目根目录存在 `第x批报账单.xlsx` 文件：

```bash
python .opencode/skills/reimbursement/scripts/cross_batch_dedup.py --root .
```

该脚本读取之前 xlsx 的 K 列（`发票号码`），与 `invoice_results.json` 交叉引用，并将重复的 PDF 从 `invoices/` 备份（重命名为 `.backup`）。去重后，**返回步骤 4**（清理 + 重新运行 `super_invoice.py`）。步骤 4 会自动套用 `invoice_fixes.json` 中的先前修复，未被去重的文件无需重新修复。仅当仍存在剩余 ERROR 时才进入步骤 5 处理新增错误。

### 7. 重新运行 super_invoice（最终）

`invoice_results.json` 干净且跨批去重完成后，**无需清理**直接重新运行 `super_invoice.py` 以生成最终下游文件：

```bash
python .opencode/skills/reimbursement/scripts/super_invoice.py --root .
```

这将生成 `invoice_results_sorted.json`、`output/` 和 `invoice_errors.json`。`invoice_results_sorted.json` 和 `invoice_errors.json` 是只读的 — 不要修改。

继续前再次运行 `check_invoice_errors.py --root .`，确认 `invoice_results.json` 没有 `ERROR`、`需人工校验` 或空 `开票时间`。

#### 7.5. 提取行程数据

运行行程单解析器以构建所有行程的可搜索 JSON（服务商、车型、上车时间、金额）：

```bash
python .opencode/skills/reimbursement/scripts/extract_trip_sheets.py --root .
```

写入 `行程单数据.json`。当 `output/` 发生变化时（例如重新运行 super_invoice 后）重新生成。

**执行完以上内容后整理上下文**，但是要记住现在是第几步。

### 8. OCR 整理费用截图

> **注意：** 对 300 多张截图运行 OCR 需要 10 分钟以上，可能被 CLI 超时中断。**始终让用户手动运行此步骤** — opencode 不得执行此命令。

读取 `images/`、`invoice_results_sorted.json` 和 `output/`。写入 `匹配记录.json`、`支出记录OCR整理结果.md`、`支出记录OCR匹配明细.md`。维护 `OCR缓存.json` 以支持增量运行 — 仅对新增或修改的截图重新 OCR。**不创建额外的截图整理目录，不复制、不重命名图片。**

**注意：** `OCR缓存.json` 以 `images/<原图片名>` 作为键，条目内保留 `sha256` 用于判断文件内容是否变化。要查询截图 OCR 文本，直接用 `images/IMG_xxx.png` 索引缓存。

脚本将截图分为四类：
- `非打车支付记录` / `非打车账单截图` — 与发票总金额匹配。
- `打车支付记录` / `打车账单截图` — 与行程单明细行匹配（高德 vs 滴滴家族按文件名区分）。
- 明确唯一匹配 → 写入 `匹配记录.json` 的 `发票映射`。
- 多个匹配 / 零匹配 → 写入 `匹配记录.json` 的 `未匹配截图[]`。

#### 8.1. 首次运行

清除过期的 OCR 报告。**不要删除 `匹配记录.json`**。若需强制重跑 OCR，先删除 `OCR缓存.json`：

```bash
rm -f 支出记录OCR整理结果.md 支出记录OCR匹配明细.md OCR缓存.json
```

然后让用户手动运行 OCR。给用户的提示必须包含以下操作步骤：

1. 打开当前项目文件夹，也就是能看到 `invoices/`、`images/`、`README.md` 的文件夹。
2. 在文件夹空白处右键。
3. 选择“在终端中打开”或类似选项。
4. 复制下面命令，粘贴到终端，按回车运行。

```bash
source .venv/bin/activate && python .opencode/skills/reimbursement/scripts/organize_expense_records.py --root .
```

提醒用户：OCR 可能需要较长时间，运行期间不要关闭终端。运行完成后把终端输出告诉 Agent。

**增量添加图片：** OCR 首次运行完成且手动修复结束后，若需添加少量新截图到 `images/`：

给用户的提示同样必须要求他们在当前项目文件夹空白处右键打开终端，然后复制下面命令运行：

```bash
source .venv/bin/activate && python .opencode/skills/reimbursement/scripts/organize_expense_records.py --root . --scan-only
```

`--scan-only` 模式：
- **只处理 OCR 缓存中不存在的新图片**（已处理过的完全跳过）
- **能自动匹配的** → 直接追加到 `匹配记录.json` 的 `发票映射`
- **无法匹配/冲突的** → 输出结构化报告（可匹配/待人工识别/冲突三类）
- **不清理、不覆盖** 现有 `匹配记录.json` 和报告
- 之后若有待处理项，进入 subagent 分析（同 8.2-8.6）

#### 8.2. 查看结果并报告给用户

`organize_expense_records.py` 首次运行时生成两份报告（仅列**未匹配**项），**此后不再通过任何方式更新**：
- `支出记录OCR整理结果.md` — 供人工查看的三个汇总表（未匹配发票、截图不完整发票、未匹配行程明细）。
- `支出记录OCR匹配明细.md` — 详细待处理图片列表，含原因列（如"金额对应多个候选发票"、"同时匹配同一发票"等）。

**注意：** 这两份报告是 OCR 运行时的快照，查看当前状态请使用 `verify_screenshot_coverage.py`（见第 8.8 节）。

**阅读原始报告**，然后向用户展示：
1. 哪些发票完全无截图（类型为材料费/打车费）。
2. 哪些发票截图不完整（缺支付记录或账单截图）。
3. 哪些行程明细缺少截图。
4. **说明可分析的问题类型：**
   - 类型 A: `金额对应多个候选发票` — 通过比较 OCR 文本中的店铺名称来消除歧义（非打车）。
   - 类型 B: `金额对应多个候选行程` — 通过匹配 OCR 中的乘车时间/服务商与行程单数据来消除歧义（打车）。
   - 类型 C: `同时匹配同一发票` — 检查截图是否互为重复。
   - 类型 D: `未匹配到截图的发票` — 完全无截图的发票，通过搜索 OCR 关键词寻找缺失截图。
5. 询问用户先修复哪种类型。一次只修复一种类型。对每种类型，必须使用对应的 subagent（`@fix-shop-name-ambiguity` / `@fix-trip-ambiguity` / `@fix-duplicate-screenshots` / `@fix-bearing-invoice`）。subagent 的具体方法以 `.opencode/agents/<name>.md` 为准。

**重要（匹配记录机制）：** 主流程每次调用 subagent 前，必须重新读取当前 `匹配记录.json`、`OCR缓存.json`、`invoice_results_sorted.json`，打车问题还要读取 `行程单数据.json`。传给 subagent 的待处理内容必须来自最新状态，不要复用上一次报告中的旧列表。

subagent 不直接编辑 `匹配记录.json`。它们写各自的 action 文件（如 `fix-shop-name-ambiguity.actions.json`），再运行：

```bash
python .opencode/skills/reimbursement/scripts/apply_match_actions.py --root . --actions <agent-name>.actions.json
```

合入脚本负责更新 `匹配记录.json`，并强制所有发票路径使用 `invoices/<invoice_results_sorted.json 的 文件名 字段值>`，截图路径使用 `images/<原截图文件名>`。除 `fix-bearing-invoice` 和主流程人工确认外，同一材料费发票、同一打车行程最多只能有一张 `支付记录` 和一张 `账单截图`。如果脚本输出 `ERROR`、非零退出，或 subagent 报告其无法处理的错误信息，立即停止并把错误报告给用户，不要自行猜测修复。

#### 8.3. 分析：`金额对应多个候选发票`（店铺名称比较）

主流程先从最新 `匹配记录.json` 的 `未匹配截图[]`、`OCR缓存.json`、`invoice_results_sorted.json` 和 `支出记录OCR匹配明细.md` 中整理仍然属于 `金额对应多个候选发票` 的图片及候选发票，再调用 `@fix-shop-name-ambiguity`。不要传入已经不在 `未匹配截图[]` 中的图片。subagent 写 action 文件并运行合入脚本；若返回错误，报告用户。

##### 8.3.1. 查看当前状态

subagent 执行后，运行验证脚本查看当前缺失状态：
```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root .
```
阅读输出了解哪些发票/行程仍未匹配，并向用户展示摘要，然后询问是否继续下一步。

#### 8.4. 分析：`金额对应多个候选行程`（出租车行程消除歧义）

主流程先从最新 `匹配记录.json` 的 `未匹配截图[]`、`OCR缓存.json`、`行程单数据.json` 和 `支出记录OCR匹配明细.md` 中整理仍然属于 `金额对应多个候选行程` 的图片及候选行程，再调用 `@fix-trip-ambiguity`。不要传入已经不在 `未匹配截图[]` 中的图片。subagent 写 action 文件并运行合入脚本；若返回错误，报告用户。

##### 8.4.1. 查看当前状态

subagent 执行后，运行验证脚本查看当前缺失状态：
```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root .
```
阅读输出了解哪些发票/行程仍未匹配，并向用户展示摘要，然后询问是否继续下一步。

#### 8.5. 分析：`同时匹配同一发票`（重复检测）

主流程先从最新 `匹配记录.json`、`OCR缓存.json`、`行程单数据.json` 和 `支出记录OCR匹配明细.md` 中整理仍然属于 `同时匹配同一发票，需人工识别` 或已违反唯一性规则的图片组，再调用 `@fix-duplicate-screenshots`。subagent 写 action 文件并运行合入脚本；若返回错误，报告用户。

##### 8.5.1. 查看当前状态

subagent 执行后，运行验证脚本查看当前缺失状态：
```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root .
```
阅读输出了解哪些发票/行程仍未匹配，并向用户展示摘要，然后询问是否继续下一步。

#### 8.6. 分析：`未匹配到截图的发票`（关键词搜索+金额组合）

使用 subagent `@fix-bearing-invoice` 分析。主流程先运行 `verify_screenshot_coverage --update-report` 获取最新缺失列表，将未匹配的稳定发票路径（如 `invoices/example.pdf`，其中 `example.pdf` 来自 `invoice_results_sorted.json` 的 `文件名` 字段）传入 subagent。subagent 写 action 文件并运行合入脚本。`fix-bearing-invoice` 是唯一允许在有明确 `exception_reason` 时为同一发票同类型写入多张截图的 subagent；若返回错误，报告用户。

##### 8.6.1. 主流程处理 subagent 输出

subagent 分析返回后，主流程：
1. 解析 subagent 最终消息中 `---UNMATCHED_BELOW---` 之后的 JSON，获取无法匹配的条目列表
2. 向用户展示这些条目（发票序号、金额、类型、原因）
3. 运行 `verify_screenshot_coverage.py --root . --update-report` 刷新报告。

#### 8.7. 补写购买日期

购买日期现在存放在 `匹配记录.json` 每个发票 entry 的 `购买日期` 字段中。subagent 写入支付记录时应同步填充；若缺失，直接从 `OCR缓存.json["images/<支付记录原图>"]["payment_date"]` 补入 `匹配记录.json`。

#### 8.8. 手动处理

三种类型的 subagent 分析全部用尽后，`匹配记录.json` 的 `未匹配截图[]` 中任何剩余图片必须由用户处理。**在此处停止**。

不要再展示待人工识别图片列表。而是运行验证脚本查看当前状态（使用 `--update-report` 同步更新给人看的报告）：
```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root . --update-report
```

向用户展示三类未匹配问题：

| 报告章节 | 含义 | 说明 |
|:--------|:-----|:-----|
| **未匹配到截图的发票** | 发票完全没有截图 | 该发票的所有截图（支付记录+账单截图）都缺失 |
| **截图不完整的发票** | 发票缺少支付记录或账单截图 | 至少有一类截图存在，另一类缺失 |
| **未匹配到截图的行程单明细** | 打车行程缺少截图 | 行程单中某个具体行程行没有截图 |

针对每类缺失，向用户说明还需要提供什么（如"序号X 发票缺少支付记录截图，金额 XXX 元"），而不是列出 `未匹配截图[]` 的详细图片文件名。只有用户明确询问时，才展示详细图片列表。

提醒用户如果需要补充截图，可以放入 `images/` 并通过 `--scan-only` 增量处理。给用户的提示必须说明：打开当前项目文件夹，在空白处右键选择“在终端中打开”，再复制下面命令运行：

```bash
source .venv/bin/activate && python .opencode/skills/reimbursement/scripts/organize_expense_records.py --root . --scan-only
```

##### 8.8.1. 冲突截图处理

`--scan-only` 输出的"冲突"项表示新增截图的目标位置已被已有截图占用。处理方法：

1. 从 `--scan-only` 输出中读取冲突图片的**金额**和**类型**（支付记录/账单截图、打车/非打车）
2. 运行 `verify_screenshot_coverage --update-report` 查看当前缺失项
3. 若冲突图片的金额 + 类型 + 分类与某缺失项匹配，直接将 `images/<原图片名>` 写入 `匹配记录.json` 对应发票 entry
4. 若金额相同但类型或分类不匹配，不动

在用户确认手动匹配完成前，**不要**继续执行步骤 8。

#### 8.9. 验证

所有匹配解决完毕后，验证完整性。优先使用覆盖率检查脚本，并更新给人看的报告文件：

```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root . --update-report
```

脚本返回退出码 0 表示所有发票和行程都有完整的 `支付记录` + `账单截图`。
返回 1 表示仍有缺失项，向用户展示缺失列表并等待修复。

#### 8.10. 复制未匹配截图到待审核目录

所有 subagent 分析完成后，复制 `匹配记录.json` 的 `未匹配截图[]` 中引用的原图片到 `待审核截图/`，方便人工集中审核。只复制，不移动，`images/` 原文件不受影响；文件名保持不变，方便对照 `支出记录OCR匹配明细.md` 中的原因。

```bash
mkdir -p 待审核截图
python -c "
import json, shutil
with open('匹配记录.json', encoding='utf-8') as f:
    data = json.load(f)
for item in data.get('未匹配截图', []):
    img = item['图片']
    dst = '待审核截图/' + img.split('/')[-1]
    shutil.copy2(img, dst)
    print(f'{img} -> {dst}')
"
```

### 9. 生成费用记录 DOCX

```bash
python .opencode/skills/reimbursement/scripts/generate_expense_record_docx.py --root .
```

读取 `invoice_results_sorted.json` 和 `匹配记录.json`，使用 `images/` 中的原始截图路径插图，使用模板 `assets/templates/Hello World 2026支出记录模板V1.0.docx`。写入 `Hello World 2026支出记录填写结果.docx` 和 `支出记录DOCX生成结果.md`。

图片按比例缩放到 9cm 宽。验证：`python -c "import zipfile; assert zipfile.ZipFile('Hello World 2026支出记录填写结果.docx').testzip() is None; print('OK')"`

### 10. 生成支付记录和支付说明 DOCX

**触发条件：** `invoice_errors.json` 中有条目的 `问题原因` 包含 `需要额外添加支付说明与支付记录`。

对每个符合条件的条目：

#### 支付记录

自动模式（推荐）：读取 `invoice_errors.json`，发现所有连号发票分组，从 `匹配记录.json` 收集对应发票的 `支付记录` 原图路径，为每组生成一个 DOCX。

```bash
python .opencode/skills/reimbursement/scripts/generate_payment_record_docx.py --root .
```

手动模式（回退）：如果自动模式遗漏了任何分组，手动提供路径：

```bash
python .opencode/skills/reimbursement/scripts/generate_payment_record_docx.py --root . \
  --title 'xxx <序号范围> 支付记录' \
  --images <支付记录截图路径...> \
  --output 支付记录/xxx_<序号范围>_支付记录.docx
```

跳过没有匹配到支付记录的发票。一个加粗居中的大标题 + 约 4cm 宽的图片。使用 `unzip -t` 验证。

#### 支付说明

仅在以下情况生成：OCR 中的收款方名称 ≠ 发票销售方名称。脚本从 `匹配记录.json` 找到每张发票的支付记录原图路径，再用 `OCR缓存.json["images/<原图片名>"]` 读取 OCR 文本，并扫描包含 `**` 的行（例如 `固万**店`）。如果分组中所有发票的收款方一致，则自动使用。

**如果收款方名称与发票销售方名称相同，则无需生成支付说明，直接跳过。**

```bash
python .opencode/skills/reimbursement/scripts/generate_payment_explanations.py --root . --date YYYY-M-D
```

**自动检测失败时：** 如果脚本输出 `[跳过] 无法自动识别收款方`，说明该组截图中未找到 `**` 掩码行（如支付记录显示完整公司名）。**必须向用户报告无法自动生成的组**，列出销售方、序号范围、金额及原因，询问用户如何处理，不能自行跳过。检查该组支付记录的 OCR 文本中的 `商户全称` / `收款方全称` 字段：

- **收款方 == 销售方** → 向用户说明"该组收款方与销售方一致，无需支付说明"，经用户确认后跳过
- **收款方 ≠ 销售方** → 向用户展示 OCR 中的收款方名称，用 `--payee '销售方=收款方'` 指定（e.g. `--payee '广东铨洲科技有限公司=铨洲**店'`）并加上 `--date` 重跑

跳过的组会记录在 `支付说明生成结果.md` 的"跳过的组"章节中。提示用户手动查看这些内容

如果脚本无法自动检测且支付记录缺失，回退到手动映射：

```bash
python .opencode/skills/reimbursement/scripts/generate_payment_explanations.py --root . --date 2026-6-26 --payee '安庆市固基五金有限公司=固万**店'
```

仅编辑 `word/document.xml`。`发票内容` ≤ 8 个中文字符。使用 `unzip -t` 验证。

### 11. 生成报销 XLSX

```bash
python .opencode/skills/reimbursement/scripts/generate_reimbursement_xlsx.py --root .
```

读取 `invoice_results_sorted.json`、`匹配记录.json` 和模板 `assets/templates/Hello World 2026报账单模板V1.1.xlsx`。写入 `Hello World 2026报账单填写结果.xlsx`。

直接编辑 `xl/worksheets/sheet1.xml`。映射：`C=购买日期`、`D=支出内容`、`E=项目类别`、`F=支出类别`、`I=发票金额`、`K=发票号码`。填充 `A=报销批次` 为 `n`，`B=序号` 从 1 开始。`购买日期` 来自 OCR 的 `支付时间`，缺失时留空。`支出内容` ≤ 5 个中文字符，从商品文本推断。出租车：`项目类别=差旅`、`支出类别=差旅费`。非出租车：`项目类别=步兵机器人`、`支出类别=机械标准件`。发票号码作为 Excel 公式字符串。`实际支出金额` 留空。使用 `unzip -t` 验证。

### 12. 验证

预期成功状态：
- `check_invoice_errors.py --root .` 返回无错误，且 `invoice_results_sorted.json` 没有 `ERROR` 或 `需人工校验`。
- `output/` 包含分类后的发票和出租车行程单。
- `匹配记录.json` 包含 OCR 自动匹配和人工匹配后的截图关系，所有截图路径指向 `images/` 原文件。
- `Hello World 2026报账单填写结果.xlsx` 和 `Hello World 2026支出记录填写结果.docx` 存在且通过 zipfile 验证。
- 任何生成的 `支付记录/` 和 `支付说明/` DOCX 文件通过 zipfile 验证。

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

本项目依赖安装在 `.venv` 中的 Python 包。opencode 自身执行脚本时会自动使用 `.venv`。**当告知 Windows 用户手动运行命令时（如 OCR 步骤），必须直接调用 `.\.venv\Scripts\python.exe`**，不要使用 Linux/macOS 的 `source .venv/bin/activate`。

若用户未指定且项目根目录不存在 `.venv` 目录，自动创建：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
```

### 所需 Python 包

- `pdftotext`（**系统二进制**，来自 Poppler，脚本通过 `subprocess` 调用）用于 PDF 文本提取。Windows 可通过 `winget install oschwartz10612.Poppler` 安装，并确保 `pdftotext.exe` 在 `PATH` 中。
- `pdfplumber` 作为 PDF 回退读取方案（当 pdftotext 不可用时）。
- `rapidocr-onnxruntime` 和 `onnxruntime` 用于费用截图 OCR。
- `Pillow` 用于生成 DOCX 时的图片处理。
- `pypinyin` 用于 `super_invoice.py` 中的汉字转拼音。
- `python-docx` 用于生成支付记录 DOCX。
- `lxml` 用于 XML 级别的 xlsx 和 DOCX 编辑。

安装任何 Python 包前，说明包名、原因和安装命令，请求用户批准并等待明确确认。

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
| `scripts/apply_invoice_fixes.py` | 将 `invoice_fixes.json` 中的修复批量写入 `invoice_results.json`（步骤 5）。 |
| `scripts/apply_file_operations.py` | 兼容旧 `文件操作指令.json`，将手动匹配操作写入 `匹配记录.json`；不移动、不删除图片（步骤 8）。 |
| `scripts/verify_screenshot_coverage.py` | 验证截图覆盖率，读取 `匹配记录.json` 与 `invoice_results_sorted.json` + `行程单数据.json` 交叉比对，输出缺失报告（步骤 8）。 |

### 内置 subagent（文件位于 `.opencode/agents/`）

| subagent | 用途 |
|----------|------|
| `fix-invoice-errors.md` | 修复发票 ERROR / 需人工校验字段（步骤 5）。模板中的 `{错误位置信息由主流程在此处填充}` 由主流程替换为实际错误列表后传入 subagent。 |
| `fix-shop-name-ambiguity.md` | 金额对应多个候选发票时，通过店铺名称消除歧义（类型 A） |
| `fix-trip-ambiguity.md` | 金额对应多个候选行程时，通过服务商+时间消除歧义（类型 B） |
| `fix-duplicate-screenshots.md` | 多张截图匹配同一发票时，检查是否为重复截图（类型 C） |
| `fix-bearing-invoice.md` | 完全无截图的发票，通过搜索 OCR 关键词找到缺失截图（类型 D） |

### 内置资源

- `assets/templates/` — 内置模板；无需在根目录放置模板。
- `assets/image_samples/` — 示例截图。

### 项目输入目录

以下目录预设于项目根目录（`--root`），在运行任何工作流步骤前必须存在：

- `invoices/` 存放发票 PDF 和出租车行程单。
- `images/` 存放运行 OCR 时的费用截图。

## 发票工作流

**必须遵守核心规则**

### 1. 清理输出文件

若非用户指定起始步骤，则删除工作流输出的所有产物，确保从干净状态开始：

**不要查看文件内容，直接删除**

```powershell
Remove-Item -Recurse -Force output, 支出记录整理, 支付记录, 支付说明 -ErrorAction SilentlyContinue
Remove-Item -Force invoice_results.json, invoice_results_sorted.json, invoice_errors.json -ErrorAction SilentlyContinue
Remove-Item -Force 行程单数据.json -ErrorAction SilentlyContinue
Remove-Item -Force 支出记录OCR整理结果.md, 支出记录OCR匹配明细.md, 支出记录购买日期.json -ErrorAction SilentlyContinue
Remove-Item -Force 'Hello World 2026报账单填写结果.xlsx', 'Hello World 2026支出记录填写结果.docx', 支出记录DOCX生成结果.md -ErrorAction SilentlyContinue
```

保留 `invoices/`、`images/`、`OCR缓存.json`、`匹配记录.json`、`第x批报账单.xlsx`、`.opencode/skills/reimbursement/` 和 `.venv/` 不受影响。`匹配记录.json` 是跨批次复用的稳定匹配状态，不得在清理步骤删除。

### 2. 确认项目结构

验证项目根目录存在 `invoices/` 和 `images/`，验证python环境正常。

### 3. 检查出租车发票配对

你必须运行脚本自动验证行程单 ↔ 发票的文件名配对：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\check_taxi_pairs.py --root .
```

- exit 0：全部配对成功，直接进入下一步。
- exit 1：列出缺失发票的行程单，告知用户自行修改文件名后重新运行。

### 4. 清理 + 运行 super_invoice

发票数量任何变化都会使下游输出失效。手动删除过期输出：

```powershell
Remove-Item -Recurse -Force output -ErrorAction SilentlyContinue
Remove-Item -Force invoice_results.json, invoice_results_sorted.json, invoice_errors.json -ErrorAction SilentlyContinue
```

然后运行 super_invoice：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\super_invoice.py --root .
```

`super_invoice.py` 自动处理批内去重 — 它会检测重复的发票号码，将其从 `invoice_results.json` 中移除，并将对应的 PDF 重命名为 `.backup`。将重复发票号码警告视为去重操作，而非导入失败。

`OCR缓存.json` 在多次运行间保留 — 任何步骤都不会删除它。

super_invoice 运行后，若存在 `invoice_fixes.json`（先前修复记录），自动套用：

```powershell
if (Test-Path invoice_fixes.json) {
    .\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_invoice_fixes.py --root .
}
```

然后检查退出码（非零）或输出是否包含 `ERROR`。若存在错误，进入步骤 5；若无错误，跳过步骤 5。

### 5. 修复 ERROR / 需人工校验

super_invoice 输出包含 `ERROR` 时，使用 subagent `@fix-invoice-errors` 修复：

1. **主流程定位错误位置** — 遍历 `invoice_results.json` 中 `发票信息[]` 的所有条目，收集所有 `ERROR` / `需人工校验` 字段，整理为结构化错误描述（含文件名、字段路径、当前值）。
2. **构造提示词** — 读取 `.opencode/agents/fix-invoice-errors.md`，将其中的 `{错误位置信息由主流程在此处填充}` 替换为步骤 1 整理出的错误列表，传入 subagent。subagent 只修正这些指定位置的字段，从 PDF 提取正确值，**直接写入** `invoice_fixes.json`。
3. 主流程运行 `apply_invoice_fixes.py` 写入修复：
   ```powershell
   .\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_invoice_fixes.py --root .
   ```
   脚本执行类型校验（金额非负、税号长度≥15等），写入修复并保留 `invoice_fixes.json` 作为审计记录。

### 6. 跨批去重

若项目根目录存在 `第x批报账单.xlsx` 文件：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\cross_batch_dedup.py --root .
```

该脚本读取之前 xlsx 的 K 列（`发票号码`），与 `invoice_results.json` 交叉引用，并将重复的 PDF 从 `invoices/` 备份（重命名为 `.backup`）。去重后，**返回步骤 4**（清理 + 重新运行 `super_invoice.py`）。步骤 4 会自动套用 `invoice_fixes.json` 中的先前修复，未被去重的文件无需重新修复。仅当仍存在剩余 ERROR 时才进入步骤 5 处理新增错误。

### 7. 重新运行 super_invoice（最终）

`invoice_results.json` 干净且跨批去重完成后，**无需清理**直接重新运行 `super_invoice.py` 以生成最终下游文件：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\super_invoice.py --root .
```

这将生成 `invoice_results_sorted.json`、`output/` 和 `invoice_errors.json`。`invoice_results_sorted.json` 和 `invoice_errors.json` 是只读的 — 不要修改。

继续前确认 `invoice_results.json` 和 `invoice_results_sorted.json` 都没有 `ERROR` 或 `需人工校验`。

#### 7.5. 提取行程数据

运行行程单解析器以构建所有行程的可搜索 JSON（服务商、车型、上车时间、金额）：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\extract_trip_sheets.py --root .
```

写入 `行程单数据.json`。当 `output/` 发生变化时（例如重新运行 super_invoice 后）重新生成。

**执行完以上内容后整理上下文**，但是要记住现在是第几步。

### 8. OCR 整理费用截图

> **注意：** 对 300 多张截图运行 OCR 需要 10 分钟以上，可能被 CLI 超时中断。**始终让用户手动运行此步骤** — opencode 不得执行此命令。

读取 `images/`、`invoice_results_sorted.json` 和 `output/`。写入 `匹配记录.json`、`支出记录OCR整理结果.md`、`支出记录OCR匹配明细.md`。维护 `OCR缓存.json` 以支持增量运行 — 仅对新增或修改的截图重新 OCR。**不再生成 `支出记录整理/`，不复制、不重命名图片。**

**注意：** `OCR缓存.json` 以 `images/<原图片名>` 作为键，条目内保留 `sha256` 用于判断文件内容是否变化。要查询截图 OCR 文本，直接用 `images/IMG_xxx.png` 索引缓存。

脚本将截图分为四类：
- `非打车支付记录` / `非打车账单截图` — 与发票总金额匹配。
- `打车支付记录` / `打车账单截图` — 与行程单明细行匹配（高德 vs 滴滴家族按文件名区分）。
- 明确唯一匹配 → 写入 `匹配记录.json` 的 `发票映射`。
- 多个匹配 / 零匹配 → 写入 `匹配记录.json` 的 `未匹配截图[]`。

#### 8.1. 首次运行

清除过期的 OCR 报告。**不要删除 `匹配记录.json`**。若需强制重跑 OCR，先删除 `OCR缓存.json`：

```powershell
Remove-Item -Force 支出记录OCR整理结果.md, 支出记录OCR匹配明细.md, OCR缓存.json -ErrorAction SilentlyContinue
```

然后让用户手动运行 OCR。给用户的提示必须包含以下操作步骤：

1. 打开当前项目文件夹，也就是能看到 `invoices/`、`images/`、`README.md` 的文件夹。
2. 在文件夹空白处右键。
3. 选择“在终端中打开”或“在 PowerShell 中打开”。
4. 复制下面命令，粘贴到 PowerShell，按回车运行。

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\organize_expense_records.py --root .
```

提醒用户：OCR 可能需要较长时间，运行期间不要关闭终端。运行完成后把终端输出告诉 Agent。

**增量添加图片：** OCR 首次运行完成且手动修复结束后，若需添加少量新截图到 `images/`：

给用户的提示同样必须要求他们在当前项目文件夹空白处右键打开 PowerShell，然后复制下面命令运行：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\organize_expense_records.py --root . --scan-only
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
5. 询问用户先修复哪种类型。一次只修复一种类型。对每种类型，必须使用对应的 subagent（`@fix-shop-name-ambiguity` / `@fix-trip-ambiguity` / `@fix-duplicate-screenshots` / `@fix-bearing-invoice`）。提示词已经在 `.opencode/agents/` 文件夹中写好，你必须按照该文件夹中的文件来输出提示词。

**重要（匹配记录机制）：** subagent 直接维护 `匹配记录.json`。它只保存原发票名、原图片名和归属关系；金额、类型、平台、服务商、车型、当前排序名等都从 `invoice_results_sorted.json`、`OCR缓存.json`、`行程单数据.json` 或行程单 PDF 读取，不写入 `匹配记录.json`。每次确认匹配后，写入 `发票映射`，并从 `未匹配截图[]` 删除对应图片；重复或废弃图片写入 `忽略截图[]`。所有路径必须使用原名：`invoices/<原发票文件名>` 和 `images/<原截图文件名>`。示例：
```json
{
  "发票映射": {
    "invoices/example.pdf": {
      "支付记录": ["images/IMG_2615.PNG"],
      "账单截图": ["images/IMG_2616.PNG"],
      "行程明细": [
        {"行程序号": 1, "支付记录": ["images/IMG_2615.PNG"], "账单截图": []}
      ],
      "购买日期": "2026/7/7"
    }
  },
  "未匹配截图": [{"图片": "images/IMG_0001.PNG", "原因": "金额不匹配任何发票或行程"}],
  "忽略截图": [{"图片": "images/IMG_2763.PNG", "原因": "重复截图"}]
}
```
- 非打车截图写入发票 entry 的 `支付记录` / `账单截图`。
- 打车截图写入对应发票 entry 的 `行程明细[]`。
- `购买日期` 从支付记录 OCR 缓存的 `payment_date` 取值。
- `未匹配截图[]` 只写 `图片` 和 `原因`；需要金额、类型、打车平台时查 `OCR缓存.json`。
- 不要把 `更新后文件名`、`发票序号`、金额、类型、打车平台、服务商、车型、上车时间写入 `匹配记录.json`。
- 不删除 `images/` 中任何文件。

兼容旧 subagent 输出时，可运行以下脚本将 `文件操作指令.json` 转写到 `匹配记录.json`。正常新流程不需要它：
```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_file_operations.py .
```
脚本不会清空 `文件操作指令.json`，只会为已处理操作打 `已执行` 标记。

#### 8.3. 分析：`金额对应多个候选发票`（店铺名称比较）

使用 subagent `@fix-shop-name-ambiguity` 分析。subagent 直接更新 `匹配记录.json`。

subagent 提示词：

当一张截图的 OCR 金额匹配多张发票时，通过比较 OCR 文本中的店铺名称与发票销售方名称来消除歧义。

**检测关键字：** 用 `Select-String -Path 支出记录OCR匹配明细.md -Pattern '金额对应多个候选发票'` 查找

**数据查询方法：**
- 查找候选发票 — 在 `invoice_results_sorted.json` 的 `发票信息[]` 中按原始 `文件名` 匹配，提取候选发票的 `销售方名称`、`项目列表`。`更新后文件名` 和序号只作展示，不作状态索引。
- 查找 OCR 文本 — `OCR缓存.json` 以 `images/<原图片名>` 为键，提取 `ocr_text`、`kind`（支付记录/账单截图）。

**店铺名称比较方法：**
1. **支付记录** — 在 OCR 原文中查找简短的中文行（收款方提示），通常带有 `**` 掩码（如 `鸿康**店`、`深圳**行`）。
2. **账单截图** — OCR 原文通常包含完整的店铺名称（如 `鸿康明五金旗舰店`、`翰哲电子商行`）。
3. **发票销售方名称** — 来自每张候选发票的 `销售方名称` 字段（如 `深圳市鸿康明科技有限公司`）。
4. **按部分名称重叠匹配** — 去除地级市前缀，比较支付记录提示、账单截图店铺名称和发票销售方名称中的关键词。

**注意：** 匹配决策由 agent 根据店铺名称、商品描述等文本含义自行判断。

**部分匹配先行输出：** 对每张截图独立判断。能确认归属的输出匹配结果；无法确认的单独列出原因。

**特殊情况处理：** 如果多张截图竞争同一发票位置且无法区分，将该组全部标记为"无法解决"并报告给主进程。

##### 8.3.1. 查看当前状态

subagent 执行后，运行验证脚本查看当前缺失状态：
```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root .
```
阅读输出了解哪些发票/行程仍未匹配，并向用户展示摘要，然后询问是否继续下一步。

#### 8.4. 分析：`金额对应多个候选行程`（出租车行程消除歧义）

使用 subagent `@fix-trip-ambiguity` 分析。subagent 直接更新 `匹配记录.json`。

subagent 提示词：

当一张截图的 OCR 金额匹配多个行程明细行时，通过比较 OCR 字段与行程单数据来消除歧义。

**检测关键字：** 用 `Select-String -Path 支出记录OCR匹配明细.md -Pattern '金额对应多个候选行程'` 查找

**相关数据：**
- `行程单数据.json` — 包含每张行程单的行程明细（序号、服务商、车型、上车时间、起点终点、金额）。部分滴滴行程的 `服务商` 字段为空字符串，此时用 `车型` 字段作识别依据。
- `OCR缓存.json` — `ocr_category` 为 `打车支付记录` 或 `打车账单截图`，`kind` 为 `支付记录` 或 `账单截图`。

**方法：**
1. 全文搜索 `支出记录OCR匹配明细.md` 中所有该金额的 pending 图片（支付记录+账单截图都要），不要只抓一组。
2. 从 `行程单数据.json` 中搜索同一金额的所有候选行程。
3. **支付记录** → 用 `images/<原图片名>` 查 `OCR缓存.json`，提取 OCR 原文中的 `乘车时间`。
4. **账单截图** → 用 `images/<原图片名>` 查 `OCR缓存.json`，提取 OCR 原文中的 `服务商-车型` 及路线/地点信息。
5. **行程单** → 读取 `行程单数据.json` 提取候选行程的 `上车时间`、`服务商`、`起点终点`。
6. **交叉匹配（agent 自行判断）：**
   - 账单截图中的**服务商** ≈ 行程单的**服务商**（主要匹配依据）
   - 支付记录中的**乘车时间** ≈ 行程单的**上车时间**（时间差通常 15 分钟内）
7. **路径比较作为兜底** — 仅当服务商和时间均无法区分时使用。
8. **部分匹配先行输出** — 能确认归属的输出匹配结果；无法确认的单独列出原因。

##### 8.4.1. 查看当前状态

subagent 执行后，运行验证脚本查看当前缺失状态：
```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root .
```
阅读输出了解哪些发票/行程仍未匹配，并向用户展示摘要，然后询问是否继续下一步。

#### 8.5. 分析：`同时匹配同一发票`（重复检测）

使用 subagent `@fix-duplicate-screenshots` 分析。subagent 直接更新 `匹配记录.json`。

subagent 提示词：

当多张截图匹配同一张发票时，首先检查它们是否是同一笔交易的重复截图。

**检测关键字：** 用 `Select-String -Path 支出记录OCR匹配明细.md -Pattern '同时匹配同一发票，需人工识别'` 查找

**相关数据：**
- `OCR缓存.json` — `ocr_category` 含 `打车支付记录|非打车支付记录|打车账单截图|非打车账单截图`，`kind` 为 `支付记录|账单截图`。
- `行程单数据.json` — 含行程明细（服务商、车型、上车时间、起点终点、金额）。部分滴滴行程 `服务商` 为空字符串时用 `车型` 字段识别。

**步骤：**
1. 从报告输出中按匹配的发票对冲突图片分组。
2. 对每组，用 `images/<原图片名>` 查 `OCR缓存.json` 获取每张图片的 OCR 文本。
3. 由 agent 自行比较：**店铺名称、金额、日期时间、商品描述、订单号**，判断是否为同一笔交易。
4. 如果所有关键字段相同 → 判断为重复，保留质量较好的（`IMG_xxx.PNG` 优于 `Weixin Image_xxx.jpg` / `img_v3_xxx.jpg`）。
5. 如果截图不同：
   - **非打车** → 回退到店铺名称比较，参照 `fix-shop-name-ambiguity` 的方法。
   - **打车** → 不是重复，而是不同行程的巧合相同金额。回退到服务商+乘车时间匹配（参照 `fix-trip-ambiguity` 的方法）：
     a. 支付记录：提取乘车时间与 `行程单数据.json` 同金额候选行程的上车时间比较。
     b. 账单截图：提取服务商名称与候选行程的服务商比较。
     c. 路线信息作为兜底。
     d. 匹配成功 → 写入 `匹配记录.json`；匹配失败 → 留在 `未匹配截图[]`。
6. **部分匹配先行输出** — 对每张截图独立判断，能确认多少就先输出多少。

##### 8.5.1. 查看当前状态

subagent 执行后，运行验证脚本查看当前缺失状态：
```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root .
```
阅读输出了解哪些发票/行程仍未匹配，并向用户展示摘要，然后询问是否继续下一步。

#### 8.6. 分析：`未匹配到截图的发票`（关键词搜索+金额组合）

使用 subagent `@fix-bearing-invoice` 分析。主流程先运行 `verify_screenshot_coverage --update-report` 获取缺失列表，将未匹配的原始发票路径（如 `invoices/example.pdf`）传入 subagent。subagent 直接更新 `匹配记录.json`。完成后，主流程展示无法匹配的条目并刷新覆盖率报告。

subagent 提示词：

当一张或多张发票完全没有已匹配的截图时，通过搜索 OCR 文本中的商品/店铺关键词来寻找待人工识别中可能属于该发票的截图，再用金额组合验证。

**输入：**

主流程传入要处理的原始发票路径列表，如 `"invoices/example.pdf,invoices/example2.pdf"`。序号和 `更新后文件名` 只作展示，不作状态索引。

**相关数据：**
- `invoice_results_sorted.json` — 获取所有发票的原始 `文件名`、`销售方名称`、`价税合计金额`、`项目列表`
- `OCR缓存.json` — 以 `images/<原图片名>` 为键，提取 `ocr_text`、`kind`（支付记录/账单截图）、`payment_date`
- `匹配记录.json` — 已匹配图片和 `未匹配截图[]`，用于跳过已完整的发票并搜索待处理图片

**方法：**

第 1 步：确定待处理发票
1. 从 `invoice_results_sorted.json` 读取所有发票
2. 只处理主流程指定的原始发票路径
3. 跳过 `匹配记录.json` 中已有支付记录和账单截图的发票

第 2 步：关键词提取
从每张发票的 `项目列表` 和 `销售方名称` 中提取搜索关键词：
- 销售方核心词（如"铨洲"、"绿林"、"恒沪橡塑"）
- 项目名称中的商品描述词（如"铝合金螺母"、"PP板"、"从动同步轮"）

第 3 步：关键词搜索
1. 遍历 `匹配记录.json` 的 `未匹配截图[]`
2. 对每个 `images/<原图片名>` 查 `OCR缓存.json` 获取 `ocr_text`
3. 若 `ocr_text` 包含任一关键词，进入候选
4. 记录候选文件的金额、kind、ocr_text

第 4 步：归属判断
对每个候选文件，由你自行判断它属于哪张发票：
- 店铺名称是否与销售方匹配（如 `绿林**店` → 绿林工具）
- 商品描述与发票项目的匹配程度
- 排除店铺名称明显不符的文件

**注意：** 同张图片只能归属一张发票，不可重复使用。

第 5 步：金额组合验证
1. 对每张发票，将归属的图片按 `kind` 分组
2. 用 Python 做组合搜索，寻找和接近发票金额的组合
3. **价格容差：** 组合金额与发票金额差距在 **±10% 以内** 即算通过
4. 优先找偏差最小的组合
5. **尽可能多找** — 支付记录和账单截图数量不必强制一致。例如找到 3 张支付记录但只有 2 张账单截图也全部提交，缺失的那类在无法匹配条目中报告

**输出：**

每处理完一组发票后，直接更新 `匹配记录.json`：
- 匹配成功图片写入 `发票映射["invoices/<原发票名>"]["支付记录"|"账单截图"]`
- 购买日期从匹配的支付记录中取最早的，写入该发票 entry 的 `购买日期`
- 无法匹配的图片继续保留在 `未匹配截图[]`，其中只写 `图片` 和 `原因`
- 所有路径保持 `images/<原图片名>`，不重命名

**无法匹配条目报告：**

所有操作输出完毕后，在最终消息中用 `---UNMATCHED_BELOW---` 分隔，输出无法完全匹配的 JSON 列表：
```json
{"未匹配条目": [
  {"发票序号": 36, "金额": 229.12, "类型": "账单截图", "原因": "无候选图片"},
  {"发票序号": 38, "金额": 523.32, "类型": "账单截图", "原因": "支付记录已匹配3张共¥229.10，账单截图只找到2张共¥200.00，缺1张约¥29.10"}
]}
```
- **完全找不到候选图片的** → 原因填"无候选图片匹配"
- **找到了候选但金额验证失败的** → 说明候选总额和差距
- **归属判断无法确认的** → 说明冲突的候选图片
- **支付记录和账单截图数量不一致的** → 说明已匹配数量和差额
- **能匹配多少就先输出多少操作指令**，不需要等全部完成再输出

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
```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root . --update-report
```

向用户展示三类未匹配问题：

| 报告章节 | 含义 | 说明 |
|:--------|:-----|:-----|
| **未匹配到截图的发票** | 发票完全没有截图 | 该发票的所有截图（支付记录+账单截图）都缺失 |
| **截图不完整的发票** | 发票缺少支付记录或账单截图 | 至少有一类截图存在，另一类缺失 |
| **未匹配到截图的行程单明细** | 打车行程缺少截图 | 行程单中某个具体行程行没有截图 |

针对每类缺失，向用户说明还需要提供什么（如"序号X 发票缺少支付记录截图，金额 XXX 元"），而不是列出 `未匹配截图[]` 的详细图片文件名。只有用户明确询问时，才展示详细图片列表。

提醒用户如果需要补充截图，可以放入 `images/` 并通过 `--scan-only` 增量处理。给用户的提示必须说明：打开当前项目文件夹，在空白处右键选择“在 PowerShell 中打开”，再复制下面命令运行：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\organize_expense_records.py --root . --scan-only
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

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\verify_screenshot_coverage.py --root . --update-report
```

脚本返回退出码 0 表示所有发票和行程都有完整的 `支付记录` + `账单截图`。
返回 1 表示仍有缺失项，向用户展示缺失列表并等待修复。

### 9. 生成费用记录 DOCX

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_expense_record_docx.py --root .
```

读取 `invoice_results_sorted.json` 和 `匹配记录.json`，使用 `images/` 中的原始截图路径插图，使用模板 `assets/templates/Hello World 2026支出记录模板V1.0.docx`。写入 `Hello World 2026支出记录填写结果.docx` 和 `支出记录DOCX生成结果.md`。

图片按比例缩放到 9cm 宽。验证：`.\.venv\Scripts\python.exe -c "import zipfile; assert zipfile.ZipFile('Hello World 2026支出记录填写结果.docx').testzip() is None; print('OK')"`

### 10. 生成支付记录和支付说明 DOCX

**触发条件：** `invoice_errors.json` 中有条目的 `问题原因` 包含 `需要额外添加支付说明与支付记录`。

对每个符合条件的条目：

#### 支付记录

自动模式（推荐）：读取 `invoice_errors.json`，发现所有连号发票分组，从 `匹配记录.json` 收集对应发票的 `支付记录` 原图路径，为每组生成一个 DOCX。

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_record_docx.py --root .
```

手动模式（回退）：如果自动模式遗漏了任何分组，手动提供路径：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_record_docx.py --root . `
  --title 'xxx 序号范围 支付记录' `
  --images '支付记录截图路径1' '支付记录截图路径2' `
  --output '支付记录/xxx_序号范围_支付记录.docx'
```

跳过没有匹配到支付记录的发票。一个加粗居中的大标题 + 约 4cm 宽的图片。使用 Python 的 `zipfile.testzip()` 验证 DOCX。

#### 支付说明

仅在以下情况生成：OCR 中的收款方名称 ≠ 发票销售方名称。脚本从 `匹配记录.json` 找到每张发票的支付记录原图路径，再用 `OCR缓存.json["images/<原图片名>"]` 读取 OCR 文本，并扫描包含 `**` 的行（例如 `固万**店`）。如果分组中所有发票的收款方一致，则自动使用。

**如果收款方名称与发票销售方名称相同，则无需生成支付说明，直接跳过。**

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_explanations.py --root . --date YYYY-M-D
```

**自动检测失败时：** 如果脚本输出 `[跳过] 无法自动识别收款方`，说明该组截图中未找到 `**` 掩码行（如支付记录显示完整公司名）。检查该组支付记录的 OCR 文本中的 `商户全称` / `收款方全称` 字段：

- **收款方 == 销售方** → 跳过即可（无需生成支付说明），用 `--date` 重跑跳过即结束
- **收款方 ≠ 销售方** → 用 `--payee '销售方=收款方'` 指定（e.g. `--payee '广东铨洲科技有限公司=铨洲**店'`）并加上 `--date` 重跑

跳过的组会记录在 `支付说明生成结果.md` 的"跳过的组"章节中。

如果脚本无法自动检测且支付记录缺失，回退到手动映射：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_payment_explanations.py --root . --date 2026-6-26 --payee '安庆市固基五金有限公司=固万**店'
```

仅编辑 `word/document.xml`。`发票内容` ≤ 8 个中文字符。使用 Python 的 `zipfile.testzip()` 验证 DOCX。

### 11. 生成报销 XLSX

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\generate_reimbursement_xlsx.py --root .
```

读取 `invoice_results_sorted.json`、`匹配记录.json` 和模板 `assets/templates/Hello World 2026报账单模板V1.1.xlsx`。写入 `Hello World 2026报账单填写结果.xlsx`。

直接编辑 `xl/worksheets/sheet1.xml`。映射：`C=购买日期`、`D=支出内容`、`E=项目类别`、`F=支出类别`、`I=发票金额`、`K=发票号码`。填充 `A=报销批次` 为 `n`，`B=序号` 从 1 开始。`购买日期` 来自 OCR 的 `支付时间`，缺失时留空。`支出内容` ≤ 5 个中文字符，从商品文本推断。出租车：`项目类别=差旅`、`支出类别=差旅费`。非出租车：`项目类别=步兵机器人`、`支出类别=机械标准件`。发票号码作为 Excel 公式字符串。`实际支出金额` 留空。使用 Python 的 `zipfile.testzip()` 验证。

### 12. 验证

预期成功状态：
- `invoice_results.json` 和 `invoice_results_sorted.json` 没有 `ERROR` 或 `需人工校验`。
- `output/` 包含分类后的发票和出租车行程单。
- `匹配记录.json` 包含 OCR 自动匹配和人工匹配后的截图关系，所有截图路径指向 `images/` 原文件。
- `Hello World 2026报账单填写结果.xlsx` 和 `Hello World 2026支出记录填写结果.docx` 存在且通过 zipfile 验证。
- 任何生成的 `支付记录/` 和 `支付说明/` DOCX 文件通过 zipfile 验证。

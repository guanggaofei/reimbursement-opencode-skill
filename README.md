# 报销材料整理使用说明

推荐使用opencode

本项目用于把发票 PDF、打车行程单和费用截图整理成报销所需材料，包括：

- 分类后的发票文件
- 截图匹配记录
- 支出记录 DOCX
- 报账单 XLSX
- 连号发票需要的支付记录 DOCX
- 必要时的支付说明 DOCX

## 安装到 opencode 项目

这个仓库包含一个 opencode skill 和配套 subagent。安装到新的报销项目时，只需要复制两部分内容：

```text
.opencode/skills/reimbursement/
.opencode/agents/
```

推荐让 opencode agent 执行安装。可以直接对 agent 说：

```text
请从 GitHub 仓库安装 reimbursement opencode skill：
1. 将 .opencode/skills/reimbursement 复制到当前项目的 .opencode/skills/reimbursement
2. 将 .opencode/agents 下的 fix-*.md 复制到当前项目的 .opencode/agents
3. 不要复制 invoices、images、OCR缓存.json、匹配记录.json 或任何报销结果文件
4. 安装后读取 README.md，按说明检查 invoices/ 和 images/ 输入目录
```

手动安装时，在目标项目根目录放置为：

```text
目标项目/
├── .opencode/
│   ├── skills/
│   │   └── reimbursement/
│   └── agents/
│       ├── fix-bearing-invoice.md
│       ├── fix-duplicate-screenshots.md
│       ├── fix-invoice-errors.md
│       ├── fix-shop-name-ambiguity.md
│       └── fix-trip-ambiguity.md
├── invoices/
└── images/
```

安装后，用户只需要向 `invoices/` 和 `images/` 添加文件。`匹配记录.json`、`OCR缓存.json` 和最终报销材料会在流程运行时生成。

## 目录结构

使用时主要关注这些目录和文件：

```text
invoice/
├── invoices/            # 放入发票 PDF、打车电子发票、行程单 PDF
├── images/              # 放入支付记录截图、账单截图
├── example_images/      # 示例截图，仅供参考，不需要修改
├── 第x批报账单.xlsx      # 可选：历史批次报账单，用于跨批去重
├── OCR缓存.json          # 自动生成：截图 OCR 缓存
├── 匹配记录.json          # 自动生成：发票和截图的匹配关系
└── invoice_fixes.json   # 自动生成：历史发票字段修复记录
```

日常使用只需要准备 `invoices/` , `images/` 和 `第x批报账单.xlsx` 。

不要手动删除这些文件，除非你明确想重置对应状态：

- `OCR缓存.json`：截图 OCR 缓存，避免重复识别。
- `匹配记录.json`：稳定的发票/截图匹配关系，跨批次复用。
- `invoice_fixes.json`：历史发票字段修复记录。

## 准备发票和行程单

把所有 PDF 放入 `invoices/`。

材料费发票：

- 直接放入 `invoices/`。
- 文件名可以保持下载时的原名。

打车发票和行程单：

- 打车电子发票和对应行程单都要放入 `invoices/`。
- 打车类文件名需要能让脚本识别发票和行程单的配对关系，例如为“滴滴发票.pdf”和“滴滴行程单.pdf”，除“发票”和“行程单”外其它内容一致。
- 运行流程时会先执行配对检查；如果配对失败，按脚本提示修改文件名后重新运行。

## 准备截图文件夹

把所有截图原图放入 `images/`，示例截图文件见 `example_images/`。

截图可以使用 `.png`、`.jpg`、`.jpeg` 等常见图片格式。建议保留手机截图原图，不要裁剪、压缩或重命名到很复杂的路径。

每张发票通常需要两类截图：

- 支付记录：支付宝、微信账单详情页，能看到金额、支付时间、付款对象或交易说明。
- 账单截图：淘宝的订单详情页，淘宝截图需要下滑到能看见“实付款”和“订单信息”。

打车费用通常也需要两类截图：

- 打车支付记录：支付宝/微信账单详情页，能看到高德打车、滴滴出行、金额、支付时间、乘车时间。
- 打车账单截图：高德/滴滴行程结束页，能看到服务商、车型、金额、起终点或行程时间。高德账单截图需要上滑隐藏地图。

（仅机械）对于铨洲的账单截图：

- 截图范围如下所示：

![alt text](<example_images/铨洲截图.png>)

截图质量建议：

- 金额必须清晰可见。
- 支付时间或乘车时间必须清晰可见。
- 店铺名、商户名、商品名、服务商、车型尽量完整显示。
- 不要遮挡金额、时间、店铺名、订单信息。
- 对长订单页，可以多截几张，但每张图最好包含金额或商品/行程关键信息。
- 如果同一笔交易有支付宝和微信两张类似截图，只保留能说明问题的一张，避免重复冲突。

## 常见截图识别规则

脚本会通过 OCR 自动识别截图类型和金额。

非打车支付记录：

- 常见于支付宝/微信账单详情。
- 脚本会从截图顶部状态栏以下、支付时间以上的区域提取第一个金额，避免把手机时间或支付日期识别成金额。

非打车账单截图：

- 需要包含 `订单信息`，且包含 `微信支付金额`、`支付宝支付金额` 或 `交易成功` 中的至少一个。
- 金额优先从 `微信支付金额` / `支付宝支付金额` 字段读取。（为了识别铨洲账单截图）

高德打车支付记录：

- 需要出现 `账单详情` 和 `高德打车`。
- 金额从支付时间上方区域读取。

高德打车账单截图：

- 需要出现 `支付成功` 和 `费用说明`。
- 金额从 `开发票` 和 `费用说明` 之间读取带 `元` 的金额。

滴滴支付记录：

- 需要出现 `账单` 和 `滴滴出行`。
- 金额从支付时间上方区域读取。

滴滴账单截图：

- 需要出现 `行程已结束`。
- 金额从 `费用明细` 附近读取，多个数字时取最大值，避免选到优惠金额。

如果脚本无法确认截图归属，会把图片留在 `匹配记录.json` 的 `未匹配截图[]` 中，并在报告里说明原因。

## 增量添加截图

如果首次 OCR 后又补充了少量截图：

1. 把新截图放入 `images/`。
2. 不要删除 `OCR缓存.json`。
3. 不要删除 `匹配记录.json`。
4. 告知Agent你新增了截图。

## 强制重新 OCR

只有在 OCR 规则更新、图片内容替换或缓存明显错误时才需要强制重跑。如有需要需告知Agent。

## 输出文件说明

主要中间文件：

- `invoice_results.json`：发票提取结果，可被修复脚本更新。
- `invoice_results_sorted.json`：最终排序后的发票信息，只读。
- `invoice_errors.json`：发票检查问题汇总，只读。
- `行程单数据.json`：从打车行程单提取的行程明细。
- `OCR缓存.json`：截图 OCR 缓存，包含 `sha256`、OCR 文本、OCR 坐标、金额、分类。
- `匹配记录.json`：发票和截图的匹配关系，是截图匹配的核心状态文件。
- `支出记录OCR整理结果.md`：截图覆盖率摘要报告。
- `支出记录OCR匹配明细.md`：未匹配截图明细。

最终交付文件：

- `Hello World 2026支出记录填写结果.docx`
- `Hello World 2026报账单填写结果.xlsx`
- `支付记录/*.docx`
- `支付说明/*.docx`

## 验证输出

验证支出记录 DOCX：

```bash
python -c "import zipfile; assert zipfile.ZipFile('Hello World 2026支出记录填写结果.docx').testzip() is None; print('DOCX OK')"
```

验证报账单 XLSX：

```bash
python -c "import zipfile; assert zipfile.ZipFile('Hello World 2026报账单填写结果.xlsx').testzip() is None; print('XLSX OK')"
```

验证支付记录和支付说明 DOCX：

```bash
python - <<'PY'
import zipfile
from pathlib import Path
for pattern in ['支付记录/*.docx', '支付说明/*.docx']:
    for path in Path('.').glob(pattern):
        assert zipfile.ZipFile(path).testzip() is None, path
        print(path, 'OK')
PY
```

## 常见问题

### OCR 把年份识别成金额怎么办？

当前脚本对支付记录只在截图顶部状态栏以下、`支付时间` 上方区域取金额，通常可以避免把 `2026` 识别成金额。如果仍然出现错误，查看 `OCR缓存.json` 中对应图片的 `ocr_text` 和 `ocr_boxes`。

### 为什么某张截图没有自动匹配？

常见原因：

- OCR 金额和发票金额不一致。
- 同一个金额对应多张发票。
- 截图缺少店铺名、商品名、服务商或时间，无法确认归属。
- 截图是账单截图，但页面里没有 `订单信息`、支付金额、`费用说明`、`费用明细` 等关键字段。
- 截图重复，和另一张图竞争同一个发票位置。

先运行：

```bash
python .opencode/skills/reimbursement/scripts/verify_screenshot_coverage.py --root . --update-report
```

再查看：

```bash
支出记录OCR整理结果.md
支出记录OCR匹配明细.md
```

### 新增截图后要不要重新跑全部流程？

通常不需要。把新截图放入 `images/` 后运行：

```bash
python .opencode/skills/reimbursement/scripts/organize_expense_records.py --root . --scan-only
```

### 可以修改图片文件名吗？

可以，但不建议频繁改。`OCR缓存.json` 的 key 使用 `images/<原图片名>`，文件名变化会让脚本把它当成新图片处理。

### 可以删除 images 里的原图吗？

不要删除已经匹配的原图。最终 DOCX 会直接从 `images/` 原路径读取图片。

### 可以手动编辑匹配记录吗？

可以，但要小心保持路径格式：

- 发票路径：`invoices/<原发票文件名>`
- 图片路径：`images/<原截图文件名>`

非打车截图写入对应发票的 `支付记录` 或 `账单截图`。打车截图写入对应发票的 `行程明细[]`。

## 推荐工作习惯

- 每次开始前先备份或提交重要状态文件。
- 不要把 `OCR缓存.json` 和 `匹配记录.json` 当作临时文件随手删除。
- 截图尽量一次性收齐，但后续补图用 `--scan-only`。
- 每次补图或人工修复后都运行覆盖率检查。
- 最终生成 DOCX/XLSX 后做 zip 校验。

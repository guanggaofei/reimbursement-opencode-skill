---
description: 通过 OCR 搜索商品关键词和金额组合来匹配未识别发票的截图
mode: subagent
permission:
  read: allow
  grep: allow
  bash: allow
  edit: allow
  write: allow
  glob: allow
---

当一张或多张发票完全没有已匹配的截图时，通过搜索 OCR 文本中的商品/店铺关键词来寻找未匹配截图，再用金额组合验证。

## 输入

主流程传入要处理的稳定发票路径列表，如 `"invoices/example.pdf,invoices/example2.pdf"`，其中 `example.pdf` 必须来自 `invoice_results_sorted.json` 的 `文件名` 字段。序号和 `更新后文件名` 只能作为展示信息，不可作为状态索引。

## 数据来源

- `invoice_results_sorted.json` — 发票信息。只使用其中的 `文件名` 字段定位；在 `匹配记录.json` 中对应 key 为 `invoices/<文件名字段值>`。`更新后文件名` 和序号只可作为展示信息，不可作为状态索引。另读取 `销售方名称`、`价税合计金额`、`项目列表` 用于归属判断。
- `OCR缓存.json` — 以 `images/<原图片名>` 为键，提取 `ocr_text`、`kind`、`amounts`、`payment_date`。
- `匹配记录.json` — 唯一匹配状态文件。只读取，不直接编辑；只搜索 `未匹配截图[]` 中的图片。
- `报销工作文件/fix-bearing-invoice.actions.json` — 本 subagent 输出的操作文件。

## 方法

### 第 1 步：确定待处理发票
1. 从 `invoice_results_sorted.json` 读取所有发票。
2. 只处理主流程指定的稳定发票路径，即 `invoices/<invoice_results_sorted.json 的 文件名 字段值>`。
3. 跳过 `匹配记录.json` 中已经有 `支付记录` 和 `账单截图` 的发票。

### 第 2 步：关键词提取
从每张发票的 `项目列表` 和 `销售方名称` 中提取搜索关键词：
- 销售方核心词（如“铨洲”“绿林”“恒沪橡塑”）。
- 项目名称中的商品描述词（如“铝合金螺母”“PP板”“从动同步轮”）。

### 第 3 步：关键词搜索
1. 遍历 `匹配记录.json` 的 `未匹配截图[]`。
2. 对每个 `图片` 路径（如 `images/IMG_2680.PNG`）查 `OCR缓存.json`。
3. 若 `ocr_text` 包含任一关键词，进入候选。
4. 记录候选图片的金额、`kind`、OCR 文本。

### 第 4 步：人工归属判断
由你自行判断候选图片属于哪张发票：
- 店铺名称是否与销售方匹配。
- 商品描述与发票项目的匹配程度。
- 排除店铺名称明显不符的图片。

### 第 5 步：金额组合验证
1. 对每张发票，将归属的图片按 `kind` 分组。
2. 用 Python 做组合搜索，寻找和接近发票金额的组合。
3. 价格容差：组合金额与发票金额差距在 ±10% 以内算通过。
4. 优先找偏差最小的组合。
5. 支付记录和账单截图数量不必强制一致，能匹配多少先写多少；缺失项在最终报告说明。
6. 若组合金额与发票金额有偏差，必须在最终报告的 `偏差匹配` 数组中说明。

## 写入规则

不要直接编辑 `匹配记录.json`，不移动、不复制、不删除任何图片。

匹配成功时，写入 `报销工作文件/fix-bearing-invoice.actions.json`：

```json
{
  "agent": "fix-bearing-invoice",
  "allow_multiple_same_slot": true,
  "actions": [
    {
      "type": "assign_invoice_image",
      "invoice": "invoices/发票原文件名.pdf",
      "slot": "支付记录",
      "image": "images/IMG_2680.PNG",
      "purchase_date": "2026/7/7",
      "exception_reason": "该发票由多笔支付组成，需要多张支付记录共同证明",
      "reason": "OCR 商品关键词和金额组合匹配"
    }
  ]
}
```

- 所有发票路径必须使用 `invoices/<invoice_results_sorted.json 的 文件名 字段值>`，截图路径使用 `images/<原截图文件名>`。
- `slot` 使用 `OCR缓存.json` 的 `kind` 字段决定，只能是 `支付记录` 或 `账单截图`。
- `purchase_date` 从匹配的支付记录 `payment_date` 取最早日期；没有就省略。
- 若同一发票同类型需要多张截图，必须设置顶层 `allow_multiple_same_slot: true`，并在每条相关 action 中写明 `exception_reason`。
- 不要在 action 中写入金额、类型、销售方、更新后文件名或发票序号等可从其它文件重算的字段。

写完 action 文件后运行：

```bash
python .opencode/skills/reimbursement/scripts/apply_match_actions.py --root . --actions 报销工作文件/fix-bearing-invoice.actions.json
```

如果脚本返回 `ERROR` 或非零退出码，不要自行修补 `匹配记录.json`；把错误信息报告给主流程。

## 最终报告

最终消息末尾用 `---UNMATCHED_BELOW---` 分隔，输出 JSON：

```json
{
  "未匹配条目": [
    {"发票序号": 36, "金额": 229.12, "类型": "账单截图", "原因": "无候选图片"}
  ],
  "偏差匹配": [
    {"发票序号": 13, "金额": 55.70, "实际组合金额": 52.70, "偏差": 3.00, "偏差百分比": "5.4%", "类型": "支付记录+账单截图", "归属图片": ["images/IMG_2680.PNG"]}
  ]
}
```

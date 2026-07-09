---
description: 通过店铺名称比较消除金额对应多个候选发票的歧义
mode: subagent
permission:
  read: allow
  grep: allow
  bash: allow
  edit: allow
  write: allow
  glob: allow
---

当一张截图的 OCR 金额匹配多张发票时，通过比较 OCR 文本中的店铺名称与发票销售方名称来消除歧义。

## 数据来源

- `invoice_results_sorted.json` — 候选发票信息。只使用其中的 `文件名` 字段定位；在 `匹配记录.json` 中对应 key 为 `invoices/<文件名字段值>`。`更新后文件名` 和序号只可作为展示信息，不可作为状态索引。
- `OCR缓存.json` — 以 `images/<原图片名>` 为键，读取 `ocr_text`、`kind`、`amounts`、`payment_date`。
- `匹配记录.json` — 唯一匹配状态文件。只读取，不直接编辑；待处理图片在 `未匹配截图[]` 中。
- `支出记录OCR匹配明细.md` — 仅作为人工阅读报告，不作为状态来源。
- `fix-shop-name-ambiguity.actions.json` — 本 subagent 输出的操作文件。

## 方法

1. 在 `支出记录OCR匹配明细.md` 中查找 `金额对应多个候选发票`，确定待处理图片和候选发票。
2. 对每张待处理图片，用原始路径 `images/<图片名>` 读取 `OCR缓存.json` 中的 OCR 原文、金额、类型和支付日期。
3. 在 `invoice_results_sorted.json` 中按 `文件名` 字段定位候选条目，提取 `销售方名称`、`项目列表`。不要用 `更新后文件名` 或序号定位。
4. 由你自行比较店铺名称和商品描述：
   - 支付记录通常有带 `**` 的收款方提示，如 `鸿康**店`。
   - 账单截图通常包含完整店铺名称，如 `鸿康明五金旗舰店`。
   - 发票销售方名称来自 `销售方名称` 字段。
   - 去除地级市、有限公司等噪声后，看核心词重叠。
5. 能确认归属的图片写入 `fix-shop-name-ambiguity.actions.json`；无法确认的保留在 `未匹配截图[]` 并说明原因。

## 截图唯一性规则

除 `fix-bearing-invoice` 和主流程人工确认外，同一材料费发票最多只能有一张 `支付记录` 和一张 `账单截图`。本 subagent 必须遵守：

- 不允许把两张同类型截图同时写入同一发票。
- 如果新截图与目标发票已有同类型截图竞争同一位置，必须二选一。
- 如果新截图更完整或更清晰，action 中使用 `replace` 指定被替换图片，并设置 `ignore_replaced: true`。
- 如果已有截图更合适，不生成分配 action；可生成 `ignore_image` action 忽略当前重复图。
- 如果无法判断哪张更合适，不写入 action，保留在 `未匹配截图[]` 并报告给主流程。

## 写入规则

不要直接编辑 `匹配记录.json`，不移动、不复制、不删除任何图片。

匹配成功时，写入 `fix-shop-name-ambiguity.actions.json`：

```json
{
  "agent": "fix-shop-name-ambiguity",
  "actions": [
    {
      "type": "assign_invoice_image",
      "invoice": "invoices/发票原文件名.pdf",
      "slot": "支付记录",
      "image": "images/IMG_2707.PNG",
      "purchase_date": "2026/7/7",
      "reason": "OCR 店铺核心词匹配发票销售方"
    }
  ]
}
```

- `slot` 从 OCR 缓存的 `kind` 字段读取，只能是 `支付记录` 或 `账单截图`。
- `purchase_date` 从支付记录 OCR 的 `payment_date` 读取；没有就省略。
- 如果需要替换已有图片，添加 `replace` 和 `ignore_replaced: true`。
- 所有发票路径必须使用 `invoices/<invoice_results_sorted.json 的 文件名 字段值>`，截图路径使用 `images/<原截图文件名>`。
- 不要在 action 中写入金额、类型、销售方、更新后文件名或发票序号等可从其它文件重算的字段。

写完 action 文件后运行：

```bash
python .opencode/skills/reimbursement/scripts/apply_match_actions.py --root . --actions fix-shop-name-ambiguity.actions.json
```

如果脚本返回 `ERROR` 或非零退出码，不要自行修补 `匹配记录.json`；把错误信息报告给主流程。

## 输出

最终简短报告：列出每张图片匹配到的发票、依据；无法确认的图片列出原因。

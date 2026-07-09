---
description: 通过服务商和乘车时间比较消除金额对应多个候选行程的歧义
mode: subagent
permission:
  read: allow
  grep: allow
  bash: allow
  edit: allow
  write: allow
  glob: allow
---

当一张截图的 OCR 金额匹配多个行程明细行时，通过比较 OCR 字段与行程单数据来消除歧义。

## 数据来源

- `invoice_results_sorted.json` — 发票信息。只使用其中的 `文件名` 字段定位；在 `匹配记录.json` 中对应 key 为 `invoices/<文件名字段值>`。`更新后文件名` 和序号只可作为展示信息，不可作为状态索引。
- `行程单数据.json` — 行程明细（序号、服务商、车型、上车时间、起点终点、金额）。
- `OCR缓存.json` — 以 `images/<原图片名>` 为键，读取 OCR 原文、`kind`、`taxi_platform`、`payment_date`。
- `匹配记录.json` — 唯一匹配状态文件。只读取，不直接编辑；待处理图片在 `未匹配截图[]` 中，匹配成功后通过 action 合入对应发票的 `行程明细[]`。
- `支出记录OCR匹配明细.md` — 仅作为人工阅读报告。
- `fix-trip-ambiguity.actions.json` — 本 subagent 输出的操作文件。

## 方法

1. 全文查找 `支出记录OCR匹配明细.md` 中 `金额对应多个候选行程` 的图片。
2. 用 `images/<图片名>` 查 `OCR缓存.json`：
   - 读取 `taxi_platform` 区分高德/滴滴。
   - 支付记录：提取 OCR 原文中的乘车时间。
   - 账单截图：提取 OCR 原文中的服务商、车型、路线/地点。
3. 从 `行程单数据.json` 查同金额候选行程：服务商、车型、上车时间、起点终点。
4. 由你自行交叉判断：
   - 账单截图服务商 ≈ 行程单服务商，是主要依据。
   - 支付记录乘车时间 ≈ 行程单上车时间，通常 15 分钟内。
   - 路线信息仅作兜底。
5. 能确认归属的图片写入 `fix-trip-ambiguity.actions.json`；无法确认的保留未匹配并说明原因。

## 截图唯一性规则

除 `fix-bearing-invoice` 和主流程人工确认外，同一打车行程最多只能有一张 `支付记录` 和一张 `账单截图`。本 subagent 必须遵守：

- 不允许把两张同类型截图同时写入同一发票的同一 `行程序号`。
- 如果新截图与目标行程已有同类型截图竞争同一位置，必须二选一。
- 如果新截图更完整或更清晰，action 中使用 `replace` 指定被替换图片，并设置 `ignore_replaced: true`。
- 如果已有截图更合适，不生成分配 action；可生成 `ignore_image` action 忽略当前重复图。
- 如果无法判断哪张更合适，不写入 action，保留在 `未匹配截图[]` 并报告给主流程。

## 写入规则

不要直接编辑 `匹配记录.json`，不移动、不复制、不删除任何图片。

打车行程匹配成功时，写入 `fix-trip-ambiguity.actions.json`：

```json
{
  "agent": "fix-trip-ambiguity",
  "actions": [
    {
      "type": "assign_trip_image",
      "invoice": "invoices/打车发票原文件名.pdf",
      "trip_seq": 1,
      "slot": "支付记录",
      "image": "images/IMG_2615.PNG",
      "purchase_date": "2026/7/7",
      "reason": "OCR 乘车时间与行程单上车时间匹配"
    }
  ]
}
```

- `slot` 从 OCR 缓存的 `kind` 字段读取。
- `purchase_date` 从支付记录 OCR 的 `payment_date` 读取；没有就省略。
- 如果需要替换已有图片，添加 `replace` 和 `ignore_replaced: true`。
- 所有发票路径必须使用 `invoices/<invoice_results_sorted.json 的 文件名 字段值>`，截图路径使用 `images/<原截图文件名>`。
- 不要在 action 中写入金额、打车平台、服务商、车型、上车时间、更新后文件名或发票序号等可从其它文件重算的字段。

写完 action 文件后运行：

```bash
python .opencode/skills/reimbursement/scripts/apply_match_actions.py --root . --actions fix-trip-ambiguity.actions.json
```

如果脚本返回 `ERROR` 或非零退出码，不要自行修补 `匹配记录.json`；把错误信息报告给主流程。

## 输出

最终简短报告：列出每张图片匹配到的发票和行程序号、依据；无法确认的图片列出原因。

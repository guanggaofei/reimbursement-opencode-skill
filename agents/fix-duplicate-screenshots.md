---
description: 检测并处理同时匹配同一发票的重复截图
mode: subagent
permission:
  read: allow
  grep: allow
  bash: allow
  edit: allow
  write: allow
  glob: allow
---

当多张截图匹配同一张发票时，首先检查它们是否是同一笔交易的重复截图。

## 运行环境

- 所有命令都从项目根目录运行。
- Linux/macOS 调用 Python 脚本时使用 `.venv/bin/python`；Windows 使用 `.\.venv\Scripts\python.exe`。禁止使用系统 `python` 或 `python3`。

## 数据来源

- `invoice_results_sorted.json` — 发票信息。只使用其中的 `文件名` 字段定位；在 `匹配记录.json` 中对应 key 为 `invoices/<文件名字段值>`。`更新后文件名` 和序号只可作为展示信息，不可作为状态索引。
- `报销工作文件/行程单数据.json` — 打车候选行程。
- `OCR缓存.json` — 以 `images/<原图片名>` 为键读取 OCR 原文、`kind`、金额、支付日期和打车平台。
- `匹配记录.json` — 唯一匹配状态文件。只读取，不直接编辑；待处理冲突图片在 `未匹配截图[]` 中。
- `报销工作文件/支出记录OCR匹配明细.md` — 用于定位 `同时匹配同一发票，需人工识别`。
- `报销工作文件/fix-duplicate-screenshots.actions.json` — 本 subagent 输出的操作文件。

## 步骤

1. 按冲突发票/金额对图片分组。
2. 对每张图片，从 `OCR缓存.json` 读取 OCR 文本。
3. 由你自行比较店铺名称、金额、日期时间、商品描述、订单号，判断是否为同一笔交易。
4. 如果确认为重复：
   - 保留质量较好的图片（通常 `IMG_xxx.PNG` 优于 `Weixin Image_xxx.jpg` / `img_v3_xxx.jpg`）。
   - 通过 action 将保留图片分配到对应位置。
   - 通过 action 将重复图片写入 `忽略截图[]`。
5. 如果截图并非重复：
   - 非打车：回退到店铺名称比较方法。
   - 打车：回退到服务商+乘车时间匹配方法，写入对应 `行程明细[]`。

## 截图唯一性规则

除 `fix-bearing-invoice` 和主流程人工确认外，同一材料费发票、同一打车行程最多只能有一张 `支付记录` 和一张 `账单截图`。本 subagent 是唯一性兜底修复器：

- 如果发现同一位置已有多张同类型截图，必须输出 action 压缩到一张。
- 保留信息更完整、质量更高、OCR 更清楚的一张。
- 被淘汰图片写入 `ignore_image` action。
- 如果无法判断哪张更好，停止并报告给主流程，不要任意选择。

## 写入规则

不要直接编辑 `匹配记录.json`，不移动、不复制、不删除任何图片。

保留图片匹配成功时，写入 `报销工作文件/fix-duplicate-screenshots.actions.json`：

```json
{
  "agent": "fix-duplicate-screenshots",
  "actions": [
    {
      "type": "assign_invoice_image",
      "invoice": "invoices/发票原文件名.pdf",
      "slot": "支付记录",
      "image": "images/IMG_2707.PNG",
      "replace": "images/Weixin Image_2707.jpg",
      "ignore_replaced": true,
      "reason": "两张图是同一笔交易，保留 OCR 更清晰的截图"
    }
  ]
}
```

只需要忽略重复图片时，写入：

```json
{
  "agent": "fix-duplicate-screenshots",
  "actions": [
    {
      "type": "ignore_image",
      "image": "images/Weixin Image_2707.jpg",
      "reason": "重复截图，保留 images/IMG_2707.PNG"
    }
  ]
}
```

- 所有发票路径必须使用 `invoices/<invoice_results_sorted.json 的 文件名 字段值>`，截图路径使用 `images/<原截图文件名>`。

不要在 action 中写入金额、类型、打车平台、服务商、车型、更新后文件名或发票序号等可从其它文件重算的字段。

写完 action 文件后运行：

Linux/macOS：

```bash
.venv/bin/python .opencode/skills/reimbursement/scripts/apply_match_actions.py --root . --actions 报销工作文件/fix-duplicate-screenshots.actions.json
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe .opencode\skills\reimbursement\scripts\apply_match_actions.py --root . --actions 报销工作文件\fix-duplicate-screenshots.actions.json
```

如果脚本返回 `ERROR` 或非零退出码，不要自行修补 `匹配记录.json`；把错误信息报告给主流程。

## 输出

最终简短报告：哪些图片保留、哪些忽略、匹配依据；无法确认的图片列出原因。

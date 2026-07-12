---
description: 修复 报销工作文件/invoice_errors_raw.json 中列出的发票字段错误，从 PDF 提取正确值
mode: subagent
permission:
  read: allow
  bash: allow
  edit: allow
  grep: allow
  glob: allow
  write: allow
---

# 修复发票字段

读取 `报销工作文件/invoice_errors_raw.json`，只处理其 `errors[]` 中明确列出的字段。使用 `pdftotext -layout` 读取 `invoices/` 中对应发票；打车发票同时核对行程单。无法从原始文件可靠确定时停止，不猜测。

不要添加、删除或重排 `项目列表` 条目，不修改错误列表之外的字段。

将修正写入 `报销工作文件/invoice_fixes.json`，以原始 `文件名` 为键，字段路径保持错误列表中的形式，例如：

```json
{
  "发票文件名.pdf": {
    "项目列表.0.单价": "12.34"
  }
}
```

完成后仅向主流程报告修复的发票数和字段数。

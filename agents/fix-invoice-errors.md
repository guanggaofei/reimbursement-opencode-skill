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

## 错误位置

从 `报销工作文件/invoice_errors_raw.json` 读取错误列表。该文件由 `check_invoice_errors.py` 生成，格式如下：

```json
{
  "has_error": true,
  "error_count": 2,
  "errors": [
    {
      "文件名": "example.pdf",
      "字段": "项目列表.0.单价",
      "当前值": "ERROR",
      "错误类型": "ERROR"
    }
  ]
}
```

## 修复要求

### 范围限制
- **只修正 `报销工作文件/invoice_errors_raw.json` 的 `errors[]` 中列出的字段**。其他任何字段（包括非 ERROR 的 `项目名称`、`价税合计金额`、`销售方名称`、`发票号码`、`开票时间` 等）一律不碰。
- 不要添加、删除或修改 `项目列表` 中的条目总数，只修正 `单价` 的值。
- 保持现有 JSON 结构，不要引入新键。
- 如果 `报销工作文件/invoice_errors_raw.json` 不存在、不是有效 JSON、`error_count` 为 0，或其中某个错误无法从 PDF/行程单可靠修复，立即停止并向主流程报告，不要猜测。

### 从 PDF 提取正确值

如果是打车发票，需同时看发票 PDF 和对应的行程单 PDF 来提取正确的单价。

```bash
pdftotext -layout invoices/<文件名.pdf> -
pdftotext -layout invoices/<对应行程单文件名.pdf> -
```

- 发票上每行 `项目名称` 对应一次行程，`单价` 为该行程金额。
- 行程单上列出了每次行程的明细金额，用行程单中的金额来修正发票上对应行程的 `单价`。
- 如果行程单中的次数和发票条目数不对应，检查发票总金额验证。

### 输出

将修正值**直接写入** `报销工作文件/invoice_fixes.json`，以 `文件名` 为键：

```json
{
  "发票文件名.pdf": {
    "需要修正的字段": "正确值"
  }
}
```

`字段` 已经是 `apply_invoice_fixes.py` 支持的路径格式。嵌套字段必须原样使用，例如 `项目列表.0.单价`、`项目列表.0.项目名称`。顶层字段使用字段名本身，例如 `开票时间`、`发票号码状态`。

`项目列表` 必须包含原始所有条目（不增不减），只修改 `单价` 的值。只写入需要修改的发票。

输出一条简短摘要（如修复了 N 张发票中的 M 个字段）。

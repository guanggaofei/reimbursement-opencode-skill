# 报销材料自动整理 Skill

本仓库提供 Linux/macOS 与 Windows 两套 opencode 入口，用于自动整理发票 PDF、行程单和费用截图，并生成报账单、支出记录、附件压缩包与合并 PDF。

## 安装

### Agent 安装要求

- Agent 获取本仓库时，必须将 Git 仓库克隆到 `/tmp/reimbursement-opencode-skill`，不得克隆到用户的报销项目目录或其他长期保存目录：

  ```bash
  git clone https://github.com/guanggaofei/reimbursement-opencode-skill.git /tmp/reimbursement-opencode-skill
  ```

- `/tmp/reimbursement-opencode-skill` 仅作为安装源；skill 和 subagent 仍应复制到用户报销项目的 `.opencode/` 目录。
- 安装完成后，Agent 必须明确告知用户：**重启 opencode，并开启一个新会话，以加载新安装的 skill。** 仅在当前会话中继续操作不能保证新 skill 已被加载。

当前工作目录应为报销项目根目录。

Linux/macOS：

```bash
mkdir -p .opencode/skills/reimbursement .opencode/agents invoices images
cp -r skills/reimbursement/assets skills/reimbursement/scripts skills/reimbursement/agents .opencode/skills/reimbursement/
cp skills/reimbursement/SKILL.md .opencode/skills/reimbursement/SKILL.md
cp agents/fix-bearing-invoice.md agents/fix-duplicate-screenshots.md agents/fix-shop-name-ambiguity.md agents/fix-trip-ambiguity.md .opencode/agents/
cp agents/fix-invoice-errors.md .opencode/agents/fix-invoice-errors.md
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force .opencode\skills\reimbursement, .opencode\agents, invoices, images | Out-Null
Copy-Item -Recurse -Force skills\reimbursement\assets, skills\reimbursement\scripts, skills\reimbursement\agents .opencode\skills\reimbursement\
Copy-Item -Force skills\reimbursement\SKILL.windows.md .opencode\skills\reimbursement\SKILL.md
Copy-Item -Force agents\fix-bearing-invoice.md, agents\fix-duplicate-screenshots.md, agents\fix-shop-name-ambiguity.md, agents\fix-trip-ambiguity.md .opencode\agents\
Copy-Item -Force agents\fix-invoice-errors.windows.md .opencode\agents\fix-invoice-errors.md
```

`.windows.md` 文件是安装源文件，不应作为额外入口复制到目标项目。

## 文件布局

根目录保留原始输入、可复用状态、用户报告和最终产物：

- `invoices/`、`images/`
- `output/`
- `invoice_results.json`、`invoice_results_sorted.json`、`invoice_errors.json`
- `OCR缓存.json`、`匹配记录.json`
- 历史 `第x批报账单.xlsx`
- `支出记录OCR整理结果.md`、`待审核截图/`
- `支付说明生成结果.md`（存在相应分组时）
- `Hello World 2026报账单填写结果.xlsx`
- `Hello World 2026支出记录填写结果.docx`
- `合并发票_纵向居中.pdf`

代理内部技术文件统一位于 `报销工作文件/`：

- `invoice_errors_raw.json`、`invoice_fixes.json`、`行程单数据.json`
- `支出记录OCR匹配明细.md`、`支出记录DOCX生成结果.md`、`OCR缓存原文.md`
- subagent action JSON
- 未打包的 `支付记录/`、`支付说明/`
- DOCX 解包、XML 调试文件和其他临时产物

`super_invoice.py` 的输出契约保持不变：它仍在根目录写入三个 JSON，并写入根目录 `output/`；不复制、改名或迁移这些文件。

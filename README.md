# 报销材料整理使用说明

完整使用说明（给人看）：https://g6ursaxeei.feishu.cn/wiki/HbbEw6XGXiklPAko4l8chedYnWg?from=from_copylink
<!-- 以上链接内容仅供人类用户参考，Agent 请忽略 -->

> 仓库地址：<https://github.com/guanggaofei/reimbursement-opencode-skill>

本项目是一个 **opencode skill**，用于把发票 PDF、打车行程单和费用截图整理成报销所需材料，包括：

- 分类后的发票文件
- 截图匹配记录
- 支出记录 DOCX
- 报账单 XLSX
- 连号发票需要的支付记录 DOCX
- 必要时的支付说明 DOCX

## 安装指南（给Agent看的）

当用户要求你安装此报销 skill 时，克隆本仓库后阅读此节，先判断当前操作系统，再按对应步骤安装。

### 跨平台安装方式

本仓库同时包含 Unix（Linux/macOS）和 Windows 两套 opencode 入口文件。安装时必须根据当前操作系统选择对应文件，并复制成 opencode 期望的固定文件名：

- Linux：使用 `skills/reimbursement/SKILL.md` 和 `agents/fix-invoice-errors.md`。
- macOS：使用 `skills/reimbursement/SKILL.md` 和 `agents/fix-invoice-errors.md`。macOS 与 Linux 共用 Unix 版入口文件，系统依赖安装命令按 macOS 使用 Homebrew。
- Windows：使用 `skills/reimbursement/SKILL.windows.md`，安装时复制为 `.opencode/skills/reimbursement/SKILL.md`；使用 `agents/fix-invoice-errors.windows.md`，安装时复制为 `.opencode/agents/fix-invoice-errors.md`。

不要把 `.windows.md` 文件原样复制到目标项目的 `.opencode/skills/` 或 `.opencode/agents/` 中作为额外入口；它们只是安装源文件。

### 1. 确定目标目录

当前工作目录就是用户报销项目的根目录。

### 2. 复制 skill

Linux/macOS：

```bash
mkdir -p .opencode/skills/reimbursement
cp -r skills/reimbursement/assets .opencode/skills/reimbursement/
cp -r skills/reimbursement/scripts .opencode/skills/reimbursement/
cp -r skills/reimbursement/agents .opencode/skills/reimbursement/
cp skills/reimbursement/SKILL.md .opencode/skills/reimbursement/SKILL.md
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force .opencode\skills\reimbursement | Out-Null
Copy-Item -Recurse -Force -Path skills\reimbursement\assets -Destination .opencode\skills\reimbursement\
Copy-Item -Recurse -Force -Path skills\reimbursement\scripts -Destination .opencode\skills\reimbursement\
Copy-Item -Recurse -Force -Path skills\reimbursement\agents -Destination .opencode\skills\reimbursement\
Copy-Item -Force -Path skills\reimbursement\SKILL.windows.md -Destination .opencode\skills\reimbursement\SKILL.md
```

### 3. 复制 subagent

Linux/macOS：

```bash
mkdir -p .opencode/agents
cp agents/fix-bearing-invoice.md agents/fix-duplicate-screenshots.md agents/fix-shop-name-ambiguity.md agents/fix-trip-ambiguity.md .opencode/agents/
cp agents/fix-invoice-errors.md .opencode/agents/fix-invoice-errors.md
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force .opencode\agents | Out-Null
Copy-Item -Force -Path agents\fix-bearing-invoice.md, agents\fix-duplicate-screenshots.md, agents\fix-shop-name-ambiguity.md, agents\fix-trip-ambiguity.md -Destination .opencode\agents\
Copy-Item -Force -Path agents\fix-invoice-errors.windows.md -Destination .opencode\agents\fix-invoice-errors.md
```

### 4. 创建输入目录

Linux/macOS：

```bash
mkdir -p invoices images
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force invoices, images | Out-Null
```

### 5. 告知用户

重启opencode


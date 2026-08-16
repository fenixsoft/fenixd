---
name: fenix-process
description: Use when the user wants to check detailed progress of a specific SPEC. Invoked via /fenix-process <spec-name>.
---

# Fenix Process — 任务进展查看器

查看指定 SPEC 的详细进展，包括 tasks.md 进度、fenixd 时间线、工作区状态。

## 用法

用户输入 `/fenix-process <spec-name>`，其中 `<spec-name>` 是 SPEC 的 kebab-case 名称。

## 步骤

执行进展脚本并展示结果：

```bash
python3 .fenix/bin/fenix_process.py "<用户提供的 spec-name>"
```

脚本自动输出：
1. 基本信息（状态、优先级、依赖）
2. tasks.md 分组进度（每组完成/总数 + 每项状态）
3. fenixd 日志时间线
4. 工作区文件变更
5. 下一步预期动作

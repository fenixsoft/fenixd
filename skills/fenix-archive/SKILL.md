---
name: fenix-archive
description: Use when the user wants to archive a completed SPEC/change into spec/archive/. Invoked via /fenix-archive.
---

# Fenix: 归档

将 `spec/changes/` 下已完成的 change 归档到 `spec/archive/YYYY-MM-DD-<name>`。
归档只移动目录，不修改 STATE.md 中的历史记录（已完成 SPEC 的状态字段本就是终态）。

## 流程

### 1. 列出未归档的 changes

```bash
ls -d spec/changes/*/
```

对每个未归档 change，读取其 `tasks.md` 统计未完成任务数（`- [ ]` 计数，含 `- [x]` 对比）：

```bash
for d in $(ls -d spec/changes/*/); do
  name=$(basename "$d")
  total=$(grep -c '^- \[ \]' "$d/tasks.md" 2>/dev/null || echo 0)
  echo "$name: ${total} 个未完成任务"
done
```

### 2. 用户选择

使用 **AskUserQuestion** 让用户选择要归档的 change（一次一个或多个）。

### 3. 提示未完成任务（不阻塞）

对用户选中的 change，若步骤 1 统计到未完成任务，提示数量并请用户确认；
用户确认后仍执行归档（不强制要求全部完成）。

### 4. 执行归档

```bash
python3 .fenix/bin/fenix_archive.py <name>
```

输出 JSON `{ok, from, to, error}`：
- `ok` 为 true：目录已移动到 `to`，告知用户归档路径。
- `ok` 为 false（如目标已存在）：根据 `error` 提示改名或改日再归档，原目录未被改动。

### 5. 展示结果

- 归档成功：列出 `from` → `to`，说明该 change 已进入归档目录，历史实现记录不受影响。
- 若用户归档后需要创建同名新 SPEC，可正常使用 `/fenix-new`（归档目录中的旧 change 不会与新 change 冲突）。

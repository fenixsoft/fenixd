---
name: fenix-approve
description: Use when the user wants to review completed SPECs and approve them for push. This is the only human gate in the Fenix framework. Invoked via /fenix-approve.
---

# Fenix: 审批与推送

审查已完成的工作并推送到远程仓库。这是 Fenix 框架中**唯一的人工门禁点**。

## 步骤

### 1. 列出待推送的 SPEC

```bash
python3 -c "
import sys; sys.path.insert(0, '.fenix')
from pathlib import Path
from core.state_machine import StateMachine

sm = StateMachine(Path('STATE.md'), None)
done_specs = sm.get_by_status('done')

if not done_specs:
    print('No SPECs ready for push.')
    exit(0)

print(f'{len(done_specs)} SPEC(s) ready for push:')
for name, entry in done_specs:
    print(f'  {name}: priority={entry.get(\"priority\")}, branch={entry.get(\"branch\")}')
"
```

### 2. 展示变更摘要

```bash
for branch in $(git branch --list 'fenix/*' | sed 's/[* ]*//'); do
    echo "=== $branch ==="
    git diff --stat main..."$branch" 2>/dev/null || echo "(no diff)"
done
```

### 3. 用户选择

使用 **AskUserQuestion** 让用户选择：全部推送 / 选择个别 / 取消。

### 4. 执行推送

对每个选中的 SPEC：
```bash
git push origin "fenix/<spec-name>"
```

然后更新状态：
```bash
python3 -c "
import sys; sys.path.insert(0, '.fenix')
from pathlib import Path
from core.state_machine import StateMachine
sm = StateMachine(Path('STATE.md'), None)
sm.transition('<spec-name>', 'pushed')
"
```

### 5. 汇总

列出已推送的 SPEC 和当前状态。

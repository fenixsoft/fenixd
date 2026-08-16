---
name: fenix-status
description: Use when the user wants to check Fenix framework status, view all SPEC progress, check daemon health, or see recent project activity. Invoked via /fenix-status.
---

# Fenix: 状态面板

展示 Fenix Loop Engineering Framework 运行状态。**禁止 echo 输出 ASCII 装饰横幅**，但内容需详细完整。

## 输出要求

- **一句话总结**：在开头用一句话概括当前整体状态（全部完成/进行中/卡住/停止等）
- 守护进程状态 + PID
- 每行一个 SPEC：图标、名称、状态、优先级、依赖、错误摘要
- 按优先级排序，done/pushed 的排在最后
- 状态统计：总数、done数、进行中数、阻塞数
- 活跃 Claude 进程数
- 验证进度文件内容（如有）
- 阻塞检测结果
- 待推送提示

## 步骤

### 1. 守护进程状态

```bash
echo -n "守护进程: "
if tmux has-session -t fenixd 2>/dev/null; then
    pid=$(tmux list-panes -t fenixd -F '#{pane_pid}' 2>/dev/null | head -1)
    echo "🟢 运行中 (PID: ${pid:-unknown})"
else
    echo "🔴 已停止 — 运行 /fenix-setup 启动"
fi
```

### 2. 总体状态总结

```bash
python3 << 'PYEOF'
import sys; sys.path.insert(0, '.fenix')
from pathlib import Path
from datetime import datetime, timezone
from core.state_machine import StateMachine
sm = StateMachine(Path('STATE.md'), None)
specs = sm.read_all()
total = len(specs)
done_cnt = sum(1 for e in specs.values() if e.get('status') in ('done','pushed'))
active_cnt = sum(1 for e in specs.values() if e.get('status') in ('implementing','testing'))
verified_cnt = sum(1 for e in specs.values() if e.get('status') == 'verified')
blocked_cnt = sum(1 for e in specs.values() if e.get('error') and e.get('status') not in ('done','pushed'))

# 检查卡住的任务：基于验证进度文件 mtime（而非 updated 时间戳，后者在实现/验证运行期间不更新）
now = datetime.now(timezone.utc)
# 识别「等待 fix SPEC 完成」的父 SPEC：存在活跃 fix-<name> 时，父 SPEC 不算卡住
active_fix_parents = {n[4:] for n, e in specs.items() if n.startswith('fix-') and e.get('status') not in ('done','pushed')}
stuck = []
for name, entry in specs.items():
    st = entry.get('status','')
    if st in ('done','pushed'): continue
    if name in active_fix_parents: continue  # 等待 fix 完成，不算卡住
    # testing：验证进度文件 mtime 超过 30 分钟未更新 → 验证停滞
    if st == 'testing':
        pf = Path('.fenix/verify-progress') / f'{name}.json'
        if pf.exists():
            try:
                m = (now - datetime.fromtimestamp(pf.stat().st_mtime, tz=timezone.utc)).total_seconds() / 60
                if m > 30: stuck.append(f'{name}(验证停滞{int(m)}分钟)')
            except: pass
    # implementing：不再用 updated 时间戳判卡住（daemon 有 attempt 重试机制兜底）

import subprocess
daemon_ok = subprocess.run(['tmux','has-session','-t','fenixd'], capture_output=True).returncode == 0

# 生成总结
parts = []
if not daemon_ok:
    parts.append('🔴 守护进程已停止')
elif total == 0:
    parts.append('📭 暂无 SPEC')
elif done_cnt == total:
    parts.append(f'🎯 全部完成 — {total}/{total} 个 SPEC 已就绪，等待推送')
elif active_cnt > 0:
    parts.append(f'🔨 开发进行中 — {active_cnt} 个 SPEC 正在开发')
    if done_cnt > 0: parts[-1] += f'，{done_cnt} 个已完成'
else:
    remaining = total - done_cnt
    parts.append(f'📌 {remaining} 个 SPEC 待处理')
    if done_cnt > 0: parts[-1] += f'，{done_cnt} 个已完成'
    if verified_cnt > 0: parts[-1] += f'，{verified_cnt} 个已验证'

if blocked_cnt > 0:
    parts.append(f'⚠️ {blocked_cnt} 个 SPEC 有未解决错误')
if stuck:
    parts.append(f'🔴 卡住: {", ".join(stuck)}')

print('📋 ' + ' | '.join(parts))
PYEOF
```

### 3. SPEC 列表 + 状态统计

```bash
python3 << 'PYEOF'
import sys, subprocess; sys.path.insert(0, '.fenix')
from pathlib import Path
from core.state_machine import StateMachine
sm = StateMachine(Path('STATE.md'), None)
specs = sm.read_all()
icons = {'drafted':'📝','ready':'📌','implementing':'🔨','implemented':'🧪','testing':'🔍','verified':'✅','bug-found':'🐛','done':'🎯','pushed':'🚀'}
counts = {}; done_count = 0; active_count = 0

# Sort: non-done first by priority, then done at the end
items = sorted(specs.items(), key=lambda x: (x[1].get('status') in ('done','pushed'), x[1].get('priority', 999)))

for name, entry in items:
    st = entry.get('status','?'); pri = entry.get('priority','?')
    counts[st] = counts.get(st,0) + 1
    if st in ('done','pushed'): done_count += 1
    if st in ('implementing','testing'): active_count += 1
    deps = entry.get('depends_on')
    dep_info = f' → 依赖: {deps}' if deps and deps != 'null' else ''
    print(f'  {icons.get(st,"❓")} {name}: {st} (P{pri}{dep_info})')
    err = entry.get('error')
    if err: print(f'     ⚠️ {str(err)[:120]}')

blocked = sum(1 for e in specs.values() if e.get('error') and e.get('status') not in ('done','pushed'))
pending_push = sum(1 for e in specs.values() if e.get("status") == 'done')
c = subprocess.run(['ps','aux'], capture_output=True, text=True).stdout.count('claude ')
print(f'\n📊 总计 {len(specs)} 个 SPEC | ✅ {done_count} 完成 | 🔨 {active_count} 进行中 | ⚠️ {blocked} 阻塞 | Claude 进程: {c}')
if pending_push > 0: print(f'🚀 {pending_push} 个 SPEC 等待推送 — 运行 /fenix-approve')
PYEOF
```

### 4. 验证进度

```bash
python3 << 'PYEOF'
from pathlib import Path
import json
progress_dir = Path('.fenix/verify-progress')
files = list(progress_dir.glob('*.json'))
if files:
    print('验证进度:')
    for f in files:
        d = json.loads(f.read_text())
        done = d.get('done',0); total = d.get('total',0)
        pct = f'({int(done/total*100)}%)' if total > 0 else ''
        print(f'  🔍 {f.stem}: {done}/{total} {pct} — {d.get("current","")[:60]}')
else:
    print('验证进度: (无活跃验证任务)')
PYEOF
```

### 5. 阻塞检测

```bash
python3 << 'PYEOF'
import sys; sys.path.insert(0, '.fenix')
from pathlib import Path
from datetime import datetime, timezone
from core.state_machine import StateMachine
sm = StateMachine(Path('STATE.md'), None)
now = datetime.now(timezone.utc)
specs = sm.read_all()
# 识别「等待 fix SPEC 完成」的父 SPEC：存在活跃 fix-<name> 时，父 SPEC 不算卡住
active_fix_parents = {n[4:] for n, e in specs.items() if n.startswith('fix-') and e.get('status') not in ('done','pushed')}
found = False
for name, entry in specs.items():
    st = entry.get('status','')
    if st in ('done','pushed'): continue
    if name in active_fix_parents: continue  # 等待 fix 完成，不算卡住
    # testing：验证进度文件 mtime 超过 30 分钟未更新 → 验证停滞
    if st == 'testing':
        pf = Path('.fenix/verify-progress') / f'{name}.json'
        if pf.exists():
            try:
                m = (now - datetime.fromtimestamp(pf.stat().st_mtime, tz=timezone.utc)).total_seconds() / 60
                if m > 30: print(f'  🔴 {name}: 验证停滞 {int(m)} 分钟（进度文件未更新）'); found = True
            except: pass
    if entry.get('error') and st in ('ready', 'bug-found'):
        print(f'  🟡 {name}: {st} 状态有未解决错误 — {str(entry["error"])[:80]}'); found = True
if not found: print('  ✅ 无阻塞, 所有活跃 SPEC 正常推进')
PYEOF
```

### 6. 快捷命令

```
/fenix-new "需求"    — 创建新需求
/fenix-approve       — 审查并推送完成的 SPEC
/fenix-setup         — 重启 fenixd
```

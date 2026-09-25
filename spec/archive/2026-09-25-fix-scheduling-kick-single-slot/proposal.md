## Why

Dashboard「设置拾取时间」清空定时（`start_after` 置 null）时，写侧会写下即时唤醒
文件信号 `.fenix/scheduling_kick_request.json`，daemon 主循环 1s 粒度消费后立即
派发——这是 `ed8fd880`「清空 start_after 即时唤醒派发」刻意加入的路径，意图是
让「清除定时」不等 30 分钟周期扫描。

但该信号是**单文件单槽位**，且写入失败被静默吞掉：

```python
# core/dashboard/data/admin_actions.py — set_spec_start_after 清空分支
if normalized is None:
    _write_scheduling_kick_signal(proot, spec)   # ← 返回值被丢弃
return {"ok": True, "found": True, "start_after": normalized}
```

而 `_write_scheduling_kick_signal` 在槽位被占时**直接放弃**：

```python
if req_path.exists():
    return {"ok": False, "conflict": True, ...}   # ← 不覆盖、不排队
```

**根因**：两个 SPEC 在一个消费窗口内先后清空定时 → 第二个的唤醒信号被丢弃 →
该 SPEC 退回 30 分钟周期扫描兜底。而调用方无视 `conflict`、接口照样返回
200/`ok:true`，前端弹「已清除定时，**立即恢复调度**」——**假成功**。

**实证（2026-09-20）**：`fix-agent-lane-efficiency` 于 12:36:55（UTC）在 Dashboard
清空定时，但「消费 scheduling_kick 信号」日志中**从未出现该 SPEC**；同窗口内
`add-test-regression-tab` 占用了唯一的唤醒消费（12:37:15）。该 SPEC 最终在
12:59:31 才由一次 30 分钟周期扫描（`_recover_one` 的 `drafted` 分支）捞起，
延迟 22.5 分钟。已本地复现：连续清空两个 SPEC 时两者都返回 `ok:true`，实际
只有第一个的 `spec` 出现在信号文件中。

**二次缺陷**：单槽位文件一旦被写入而无人消费（daemon 未运行 / 消费前崩溃），
会**永久占槽**，此后该项目所有清空定时的即时唤醒全部失效。现场已有实例
（`/root/activation-showcase/.fenix/scheduling_kick_request.json`，写于 09-18
且至今未被消费）。

## What Changes

- **信号载体由单文件单槽位改为**每 SPEC 一个文件：`.fenix/scheduling_kick/<spec>.json`。
  同一 SPEC 重复清空幂等覆盖自身文件；**不同 SPEC 互不阻塞**——从根上消除跨 SPEC 的
  「槽位冲突导致静默丢弃」。daemon 消费侧改为扫描目录、逐条消费、逐条删除。
- **写侧如实回报**：`set_spec_start_after` / `activate_spec` 的返回值携带唤醒信号的
  写入结果（成功 / 失败原因）；写入异常不再被吞掉。API 响应透传该结果，前端据此
  选择诚实文案——信号写出失败时提示「已清除定时，但即时唤醒信号写入失败，将由
  下次扫描（缺省 ≤30 分钟，即 `schedule.poll_interval_minutes`）派发」，MUST NOT 再无条件
  宣称「立即恢复调度」。
- **陈旧信号自动回收**：daemon 启动时与周期清扫中对信号目录执行对账——残留条目
  一律消费（唤醒语义幂等，重复唤醒被既有 handler 吸收）后删除；损坏/非法 JSON
  删除防卡死；`created` 早于回收阈值的条目判为陈旧信号，仅清理不唤醒（防御
  daemon 长期停机后的病态积压）。回收阈值与既有时序常量同族（代码常量，不进配置）。
  旧单文件路径的兼容消费同受该阈值约束，避免存量陈旧文件在项目恢复时触发过时派发。
- **兼容旧信号路径**：消费侧仍识别并消费旧单槽位文件 `.fenix/scheduling_kick_request.json`
  （存量项目一次性迁移），消费后删除；新写入方一律走新目录。

## Capabilities

### New Capabilities

- `scheduling-kick-signal`: 「清空 start_after / 激活 SPEC 触发即时唤醒」这一文件信号
  机制本身——信号载体形态（每 SPEC 一文件）、写入语义（幂等覆盖、失败如实回报）、
  消费语义（逐条消费、逐条删除、损坏即删）、陈旧回收与旧路径兼容。

### Modified Capabilities

- `scheduled-spec-pickup`: 「定时门控为实时评估而非一次性」Requirement 中，
  「到期后的推进复用既有放行侧通道 …清空/激活时的 kick 信号
  （`.fenix/scheduling_kick_request.json`）」一句把信号载体硬编码为单文件路径，
  且未声明写入失败时的行为。改为引用 `scheduling-kick-signal` 能力定义的载体与
  写入契约，并明确「信号写出失败时退回周期扫描兜底（延迟 ≤ 一个扫描周期）」。
- `spec-manual-activation`: 「激活 = start_after 置 null 并即时唤醒派发」Requirement
  同样硬编码了 `.fenix/scheduling_kick_request.json` 单文件路径与「daemon 在秒级内
  拾取并派发」的无条件承诺。改为引用 `scheduling-kick-signal` 能力的载体定义，
  并把「秒级拾取」限定为「信号成功写出时」。

## Impact

- **信号层（新增中性模块落点）**：`core/signals.py`（新增
  `SCHEDULING_KICK_DIR` 常量、`write_scheduling_kick` 写入函数——放中性模块以
  对齐 `request_admin_invoke` 既有搬迁先例，daemon 与 dashboard 双端共用同一份
  定义，不产生 dashboard → 根 daemon 的反向依赖）。
- **写入侧**：`core/dashboard/data/admin_actions.py`（`_write_scheduling_kick_signal`
  改为委托新助手并回传结果；`set_spec_start_after` / `activate_spec` 返回值新增
  信号写入结果字段）；`core/dashboard/data/__init__.py`（门面 re-export）。
- **消费侧**：`fenixd.py`（`_check_scheduling_kick_requests` 由单文件改为目录扫描
  + 旧路径兼容；新增陈旧回收逻辑挂在启动清扫与周期计时段）。
- **API 层**：`core/dashboard/routes/spec_routes.py`（`_api_spec_start_after` /
  `_api_spec_activate` 透传信号写入结果，失败时带 `warning` 字段）。
- **CLI 入口**：`bin/fenix_cli.py`（`cmd_activate` 按信号写入结果分支输出——与
  Dashboard 并列的第二个「动作方」，不得再无条件宣称「立即进入调度」）。
- **前端**：`core/dashboard/static/src/services/dashboard.ts`（结果类型新增字段）、
  `core/dashboard/static/src/pages/projects/list.tsx`（清空文案按写入结果分支）、
  `core/dashboard/static/src/pages/projects/components/SpecStatusModal.tsx`（激活动作
  同款分支）；`core/dashboard/static/dist/index.html`（构建产物，reference）。
- **测试**：`tests/test_dashboard_api.py`（新增连续清空两 SPEC 的多槽位用例、
  写入失败诚实回报用例）、`tests/test_spec_scheduling.py`（消费侧目录扫描 +
  旧路径兼容 + 陈旧回收用例）、`tests/test_start_after_gate.py`（路径断言同步）。
- **文档**：`docs/help/06-governance.md`（信号载体、失败语义、陈旧回收）。

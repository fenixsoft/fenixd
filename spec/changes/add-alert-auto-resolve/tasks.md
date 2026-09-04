# Tasks: add-alert-auto-resolve

实现依据（实施 agent 必读）：
- 能力定义 `specs/alert-lifecycle/spec.md`；设计决策 design.md D1-D6
- 告警写入点：`.fenix/core/pm_engine.py` `_send_human_escalation_alert`（约 1079 行）
- 存储层：`.fenix/core/admin_store.py`（AdminStore，含原子写与 .lock；复用其方法，不绕过锁）
- 扫描接入点：`.fenix/core/pm_engine.py` 周期状态扫描（复用当轮 STATE.md 读取结果，不新增线程）
- 视图：Dashboard admin 页告警列表（数据管道不变，仅前端分组）
- 优先级 P9：最小闭环实现，禁止范围蔓延

## 1. 闭环引擎与埋点

- [x] 1.1 新增 `.fenix/core/alert_lifecycle.py`：输入（告警列表、spec 状态表）→ 输出（可闭环条目及 resolve_note）；仅实现 `spec_terminal_or_unblocked` 一种 condition（spec 状态 ∈ {pushed, done} 或离开 blocked 即解除）；未识别 condition / 无 spec 字段 / handled=True 一律跳过
- [x] 1.2 `_send_human_escalation_alert` 增加 `trigger` 结构化字段写入（type/spec/condition），既有调用点传入对应 condition
- [x] 1.3 pm_engine 周期扫描接入闭环判定：调用 alert_lifecycle 判定，有闭环项时经 AdminStore 写回（handled=True、handled_by="auto-resolve"、handled_at、resolve_note）；无闭环项零写回（mtime 不变）

## 2. 存量回填

- [x] 2.1 daemon 启动首轮扫描执行回填：对无 trigger 字段的存量告警按 `signal_type ∈ {verify_fail_escalation, blocked_stuck}` + spec 字段存在推断 condition 并走同一闭环路径，resolve_note 注明「存量回填」

## 3. 单元测试

- [x] 3.1 覆盖：条件解除（pushed/done/离开 blocked）→ 自动闭环且字段正确；handled=True（人工）不被覆盖；未识别 condition 与无 spec 字段不闭环；全闭环时零写回
- [x] 3.2 存量回填：6 条 2026-08-29 真实告警形态的夹具（verify_fail_escalation + blocked_stuck、spec 已 pushed）→ 全部自动闭环；无 spec 字段的夹具保持原状

## 4. 视图分组

- [x] 4.1 Dashboard admin 页告警列表按 handled 分组：待处理置顶展开，已解决折叠为可展开区（自动解决/人工处理徽标 + resolve_note + handled_at）
- [x] 4.2 浏览器实测：含待处理与已解决混合数据时默认视图只显著展示待处理项

## 5. 验证与打包

- [x] 5.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [x] 5.2 执行 `bash scripts/package.sh` 生成最新扩展包

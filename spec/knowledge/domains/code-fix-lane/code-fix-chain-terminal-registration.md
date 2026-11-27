# code-fix 链终态收口登记

<!-- knowledge: capability=code-fix-chain-terminal-registration rev=1
     sources=spec/changes/evo-add-code-fix-chain-terminal-registration -->

code-fix 修复链以 disabled 终态收口（自动修复总开关关闭终止 live 链）时，在 admin 告警与 todo 待办两面留登记，消除「链已终止、无人知晓」的静默悬置面；重新触发后再次停摆能再次登记。

## 规则

- **disabled 终态收口登记**：checkpoint 收口为 disabled 终态（`running=false`、`phase=blocked`、`reason=disabled`、批不在飞）时同时落一条 admin 告警（`signal_type=code_fix_disabled_terminal`，severity=warning）与一条 todo 待办登记。两者均含三要素：终态原因（自动修复总开关已关闭）、剩余未修复条数、重新触发入口提示（dashboard `POST /api/code-review/fix-run`，override_enabled 临时授权）。剩余条数取台账 open 数实时值（`count_open_items`）；读台账失败回退进度快照 `total-done`（该快照是上一次派发写点的陈旧合计，链在飞期间台账可新增条目，直接用会低报剩余量）。
- **批在飞不登记**：总开关关闭后批仍在飞时，checkpoint 仅写 `reason=disabled` 的提示性进度（保留 `running=true`），MUST NOT 登记——链未终止，且每轮 full scan 都命中该分支，登记会持续刷屏。
- **同一 disabled 期去重**：终态写点仅在上一链状态 `running=true` 时可达，落盘后自然不再进入；若加防御性判重，谓词 MUST 为 `running is False ∧ phase == "blocked" ∧ reason == "disabled"` 三者同时满足——MUST NOT 仅以 `reason=="disabled"` 判重（在飞提示写点同写该 reason，会吞掉终态登记），MUST NOT 以「同 signal_type 未处置信号在场」判重（旧信号未处置会吞掉重新触发后的新登记）。人工重新触发后进度翻回 `running=true`，去重窗口自然重置；链再次撞 disabled 落新登记。
- **登记 fail-open**：登记在终态进度落盘成功之后执行；告警与 todo 两通道各自独立 fail-open——任一通道异常仅 warning 留痕，MUST NOT 上穿 checkpoint、MUST NOT 回退已落盘的终态进度或改变返回值（`{"triggered": false, "reason": "disabled"}`），登记写点不长时间阻塞 checkpoint 关键段。
- **todo 写点独立**：todo 登记走专用追加写点（持 `.fenix/.todo.md.lock` 伴生锁），MUST NOT 复用失败预算耗尽的既有 todo 追加助手——其标题正是失败登记闭环核销的定位锚，新块标题 MUST 与之逐字不同，防被消费侧改写或误核销。登记块不承诺自动核销：每个 disabled 期一条，人工重新触发后旧块由人工处置。
- **空闲态边界**：总开关在无 live 链（`running=false`）时被关闭不产生终态收口事件、不登记——该形态仍依赖 dashboard 被动展示端点，本能力不改变。

## 代码锚点

- 主实现：`core/code_fix.py`（`CODE_FIX_DISABLED_TERMINAL_SIGNAL_TYPE`、`_register_disabled_terminal`、`_append_disabled_terminal_todo_entry`、`_is_disabled_terminal_progress`）
- 守卫测试：`tests/test_code_fix_disabled_terminal_registration.py`
- 关联形态：人工停车落终态的字段形态与本终态同构（见 [code-fix-safe-stop](code-fix-safe-stop.md)）

## 溯源

- 2026-11-27 evo-add-code-fix-chain-terminal-registration（spec/changes/evo-add-code-fix-chain-terminal-registration/） — 新建本能力：disabled 终态收口双面登记（告警+todo、三要素文案、台账 open 实时口径读失败回退进度快照）、三谓词判重与重触发窗口重置、双通道独立 fail-open、批在飞提示写点与空闲态不登记（动因：2026-11-22 总开关关闭后链悬置超 31 小时、747 条存量发现中 561 条无修复出口且告警与 todo 零登记）

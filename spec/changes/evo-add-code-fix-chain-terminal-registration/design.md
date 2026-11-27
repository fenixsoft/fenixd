## 落点

core/code_fix.py `checkpoint()` 的 **非在飞 disabled 终态写点**（当前 5072-5085 行：`write_progress(running=False, phase="blocked", reason="disabled", current="自动修复总开关已关闭，链终止（可重新触发）", **self._chain_terminal_fields("disabled"))` 所在路径）。

同一 disabled 守卫内还有 **批在飞提示写点**（当前 5045-5071：`_code_fix_running()` 为真时只写 `reason="disabled"` 的提示性 `current`，保留 `running=true` 与批上下文）——该路径 **MUST NOT 登记**：批仍在飞、链未终止，且每轮 full scan 都会命中该分支，登记会持续刷屏。

## 设计

1. **登记面**：告警经 `_emit_signal`（`kind=SIGNAL`、`source=code-fix-lane`、新增 `signal_type=code_fix_disabled_terminal`、`severity="warning"`），形态对齐 `_write_zero_progress_alert`；todo 走**专用追加写点**（如 `_append_disabled_terminal_todo_entry`），持 `.fenix/.todo.md.lock` 追加（与 `_append_todo_entry` 同一把伴生 flock）。MUST NOT 直接复用 `_append_todo_entry`——其标题/文案是「失败批已达自动重试上限」且要求 item_ids，且该标题正是失败登记闭环核销的定位锚（`_TODO_ENTRY_TITLE`，code_fix.py:1565-1566；`_rewrite_todo_entry_consumed` 1720 起），误用会被消费侧改写或误核销。新块标题 MUST 与 `_TODO_ENTRY_TITLE` 逐字不同。

   文案包含三要素：终态原因（自动修复总开关已关闭）、剩余未修复条数、重新触发入口提示（dashboard `POST /api/code-review/fix-run`，override_enabled 临时授权）。

2. **剩余条数口径**：取 `count_open_items(self.project_root)` 的实时台账 open 数；读台账异常时回退进度快照 `total-done`（`prev_chain` 已在 5037 读出）。原因：disabled 分支在 `total_open = count_open_items(root)`（5102）之前早退，进度里的 `total`/`done` 是上一次 dispatch 写点的快照（`total = done + 当时 open`，5439），链在飞期间台账可新增条目，直接用 `total-done` 会低报剩余量。

3. **去重**：同一 disabled 期只登记一次由既有入口结构保证——终态写点仅在 `prev_chain.running=true` 时可达（5045），写点落 `running=false` 后后续 checkpoint 不再进入该分支。实现 MUST NOT 仅以 `reason=="disabled"` 判重（在飞提示写点也写该 reason 但保留 `running=true`，会造成终态登记被误跳过）；MUST NOT 用「同 signal_type 未处置信号在场」判重（旧信号未处置会吞掉重新触发后的新登记，破坏 R3）。若额外加防御性检查，谓词 MUST 为 `running is False ∧ phase == "blocked" ∧ reason == "disabled"`。

4. **重新触发的窗口重置**：override_enabled 手动触发经 5816 写点落 `running=true, phase="selecting", reason=""`，去重谓词自然失效；链此后再次撞 disabled 时落新登记。

5. **fail-open / 锁纪律**：登记在终态 `write_progress` 成功之后执行；告警与 todo 两通道各自独立 fail-open——任一通道异常（AdminStore 拒写/IO 异常、todo 写失败）只 `warning` 留痕，MUST NOT 上穿 `checkpoint()`、MUST NOT 回退已落盘的终态进度或改变返回值 `{"triggered": False, "reason": "disabled"}`。告警侧用 fail-safe 包装（对齐 `_write_zero_progress_alert_safe`，code_fix.py:6239）；todo 侧对齐 `_append_todo_entry` 的 OSError 容错。登记写点不得长时间阻塞 checkpoint 关键段（可先完成终态写盘，再在守卫块尾部执行登记）。

6. **兼容性**：不动 disabled 分支既有 `write_progress` 语义与 `_chain_terminal_fields` 内容；对 fix-progress.json 结构零改动。

## 边界与非目标

- 仅覆盖「有 live 链时总开关被关闭 → disabled 终态收口」。开关在**无 live 链（running=false）**时被关闭不产生终态写点、不登记（空闲态无收口事件，留待其他感知面）；本 SPEC 不改变该面。
- 不承诺登记块自动核销：每个 disabled episode 一条 todo 登记，人工重新触发后旧块保留，由人工勾选/处置（与既有 todo 语义一致）。

## 测试策略

单测构造 checkpoint disabled 场景，stub AdminStore/todo 写入器，覆盖五种形态：

1. 首收口落双登记（告警+todo 各一条，含剩余量、终态原因与触发提示，severity=warning）；
2. disabled 后重复 checkpoint 零新增；
3. 批在飞提示路径（`_code_fix_running()` 为真）只写提示、不登记；
4. override_enabled 重新触发（进度翻回 running=true）后再次 disabled 落新登记；
5. 告警或 todo 写点抛异常时，终态进度仍落盘、checkpoint 返回值不变（fail-open）。

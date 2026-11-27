## 落点

core/code_fix.py checkpoint() 的 disabled 终态分支（现 5008-5053 行附近，write_progress(phase="blocked", reason="disabled", current="…链终止（可重新触发）", **self._chain_terminal_fields("disabled")) 所在路径）。

## 设计

1. 登记面复用既有形态：告警写 AdminStore（对齐零进度护栏 _zero_progress_guard_fields 的告警形态），todo 走 _append_todo_entry 同款追加。文案包含：终态原因（disabled/自动修复总开关已关闭）、剩余未修复条数（total-done）、重新触发入口提示（dashboard 修复链手动触发端点）。
2. 去重：登记前检查现存 progress 已是 disabled 终态则跳过（同一 disabled 期只登记一次）。重新触发路径（override_enabled=True，fenixd.py:5637 调 checkpoint）把链翻回 live、phase 离开 disabled，去重窗口自然重置——链此后再次撞 disabled 时落新登记。
3. severity 取 warning：链整体停摆值得人工注意但不紧急，与既有 info 级预算越线告警区分。
4. 兼容性：不动 disabled 分支既有的 write_progress 语义与 _chain_terminal_fields 内容，只在其后追加登记调用；对 fix-progress.json 结构零改动。

## 测试策略

单测直接构造 checkpoint disabled 场景，stub AdminStore 与 todo 写入器，断言三形态：首收口落双登记（告警+todo 各一条且含剩余量与触发提示）、disabled 后重复 checkpoint 零新增、override_enabled 再触发后再 disabled 落新登记。
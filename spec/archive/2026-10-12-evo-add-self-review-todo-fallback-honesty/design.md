## 方案

判定点放在组装侧而非 prompt_builder 兜底：core/self_review.py 组装 detail 处（1261-1268 附近）已知 read_todo 取值——read_todo=false 时直接给 todo_entries 一个显式未收集字符串（如「（read_todo 关闭，未收集既有条目）」），使其不再落入 prompt_builder.py:1669 的「（近3日窗口内无既有条目）」兜底；read_todo=true 走 render_todo_entries 既有渲染（空清单文案不变，此时该文案为真结论）。同步核对 core/agent_runner/maintenance_runs.py:571-572 的 None→空串归一不会吞掉显式字符串。

## 权衡

- 不动缺省值：read_todo=false 是 config.py:82 注释明示的有意缺省，改缺省影响所有项目行为；本 SPEC 只消除误导性陈述，把「要不要开」留给配置层。
- 向下兼容：agents/self-review.md 模板对 {todo_entries} 无格式假设，文案变更不影响模板结构。
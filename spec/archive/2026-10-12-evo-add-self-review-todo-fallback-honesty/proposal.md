## 背景

每日自省输入摘要的「近 3 日既有条目」段在两种完全不同的状态下输出同一句「（近3日窗口内无既有条目）」：read_todo=true 且真收集为空（此时是可核实的结论，core/self_review.py:1142 render_todo_entries 空清单渲染），与 read_todo=false 根本未收集（core/agent_runner/prompt_builder.py:1669 的 or-fallback 兜底）。后者是对回看 agent 的误导性陈述。

实证：2026-10-05 potplayer-base 轮次（生效配置 read_todo=false，用户级 /root/.fenix/config.yaml 显式取值）在该文案下让回顾 agent 声称「近 3 日窗口内无既有条目」，而 .fenix/todo.md 实存 21 条窗口内条目；resolved 闭环亦因 self_review.py:1744 对空 entries 短路整轮失效，事后需回源读盘才能纠正。

## 目标

- read_todo=false 时，{todo_entries} 段输出可核实的状态陈述（归因 read_todo 关闭、未收集），与「真收集为空」的文案可分辨。
- read_todo=true 的收集与注入行为不变。

## 非目标

- 不改 read_todo 的缺省值（core/config.py:82 注释明示缺省 false 为「纯增量、零行为变化」的有意取舍）；开启注入属配置动作（dashboard SelfReviewPanel 已有开关）。
- 不改 resolved 移除机制的匹配算法与 todo.md 的清理策略。
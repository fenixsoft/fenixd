"""todo_format.py — todo.md 结构契约单源（code-review item 8455037f0c1f）。

todo.md 的写入方 core/self_review.py（_append_todo / _render_entry_lines）与
解析方 core/evolution.py（parse_todo_entries 等条目解析 / 闭环移除 / 处理标
记回写）共享同一结构契约。历史上两侧各持同值副本，对齐纯靠注释里的人工纪
律维持：任一侧调整 todo.md 结构（节标题/占位文案/字段标签），另一侧解析即
静默分叉（条目解析/闭环移除/处理标记回写全部失配）。收口到本模块后格式演
进改一处即全链生效。

两个消费方 MUST 直接从本模块导入使用，MUST NOT 另立同值副本。
"""

import re

# todo.md 结构标题正则：## YYYY-MM-DD 日期节 / ### 小节。
TODO_DATE_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
TODO_SECTION_RE = re.compile(r"^### (.+?)\s*$")

# 空小节占位（self_review._append_todo 写入；evolution 解析侧收集闭环判定
# 条目时排除）。
EMPTY_MARKER = "（当日无）"

# 条目四字段标签+键映射：self_review._render_entry_lines 的渲染标签 =
# evolution.parse_todo_entries 的解析标签，两侧逐字一致。
FIELD_LABELS = (
    ("影响", "impact"),
    ("证据", "evidence"),
    ("调查评估", "analysis"),
    ("建议", "suggestion"),
)

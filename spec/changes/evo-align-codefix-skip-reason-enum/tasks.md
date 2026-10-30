## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: agents/code-fix.md
  kind: modify
- path: tests/test_code_fix_skip_reason_alignment.py
  kind: new
```

## 1. 读侧白名单前缀归一

- [ ] 1.1 core/code_fix.py：_split_fix_rows（:2999-3028，白名单判定 :3025）对 status=skipped 产物行的 skip_reason 判定改为「strip 后以 IGNORE_ELIGIBLE_SKIP_REASONS 任一枚举值开头即命中」（保留整串相等快路径；skip_reason 缺失或非字符串按未命中处理，MUST NOT 抛异常），命中时把 skip_reason 完整原文与可选 reason 字段组装进传给 mark_ignored 的 reasons（调用点 :3051-3055），裸枚举行为不变
- [ ] 1.2 core/code_fix.py：skipped 且脱靶（非空字符串、既不命中白名单也不属既有 skipped 词汇表 unfixable/needs_human）的产物行记 warning 日志（含 item_id 与 skip_reason 原文），消除静默丢弃；unfixable/needs_human 与缺省保持现状静默；不改变脱靶行不进豁免硬出口的语义
- [ ] 1.3 core/code_fix.py：各链终局写点（统一经 _chain_terminal_fields → _emit_chain_rollup，:5425-5467；出账后链级计数归零，rollup 值即逐轮增量）维护同链连续零进度（当轮 rollup 的 resolved+ignored=0）轮数并随链级进度字段持久化（沿用 phase=blocked 既有落盘与文案分流体系）；连续 2 轮即经既有告警通道发 admin 信号并暂停该链自动重派，解除与归零条件按 spec R4（进度恢复、人工处置或新一轮评审产出台账变更；解除复核挂 select_batch 选批扫描与人工处置入口）

## 2. 模板契约对齐

- [ ] 2.1 agents/code-fix.md：skip_reason 收紧为只允许裸枚举、解释文本挪新增可选字段 reason；:106 的 (no_marker) 规则改为「skip_reason 保持裸值、(no_marker) 信息写 reason」；:24 的「在 skip_reason 或回复中说明」表述同步修正；:83-90 产物 schema 增补 reason 字段
- [ ] 2.2 core/code_fix.py：产物行解析兼容读取 reason 字段，1.1 命中时并入 ignored 理由原文

## 3. 测试

- [ ] 3.1 tests/test_code_fix_skip_reason_alignment.py：带后缀 skip_reason 命中白名单且完整原文入 reasons、reason 字段并入 ignored 理由、裸枚举行为不回归、(no_marker) 后缀命中、脱靶值 warning 留痕且不进 ignored、unfixable/needs_human/缺省/非字符串 skip_reason 静默且不抛异常
- [ ] 3.2 tests/test_code_fix_skip_reason_alignment.py：链级护栏——连续 2 轮零进度触发 admin 信号并暂停重派；仅 1 轮零进度不触发；出现 resolved 或 ignored 大于 0 的轮次后计数归零、解除路径生效

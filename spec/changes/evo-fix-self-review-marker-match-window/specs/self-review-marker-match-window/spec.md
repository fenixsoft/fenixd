# self-review-marker-match-window 规格

## ADDED Requirements

### Requirement: 失败声明窗口匹配

_business_fail_marker SHALL 仅在 result 文本前 100 字符窗口内做 _BUSINESS_FAIL_PATTERNS 子串匹配；窗口外的功能词复述 SHALL NOT 触发失败降级。

### Requirement: 假成功抓取语义保持

result 终态文本开头即为失败声明形态（如「SPEC 内容缺失，无法实现」「预算已耗尽，无法继续实现」）的 run SHALL 仍判 failed；本收敛 SHALL NOT 推翻 evo-add-self-review-run-semantics 确立的双源判据及其 pinned 用例。

### Requirement: 信号护栏终态邻近收窄（修订 2026-09-24 code-review，与实现对齐）

_signal_evidence 终态邻近 3 行护栏 SHALL 仅扫描 result 终态之外的事件行（lines[:-1]）：result 终态自身（正文及该行其余字段）SHALL NOT 再作为信号源；信号词位于事件行时 SHALL 仍经 _signal_evidence 兜底判 failed。_scan_run_signals 只补 detail、不改写 category 的既有语义 SHALL 保持不变。

#### Scenario: 成功摘要中段功能词不降级

- WHEN result 终态 is_error=False 且 subtype=success，「预算耗尽」仅出现在摘要中段（如「预算耗尽发一次性 warning」）
- THEN 该 run 计 succeeded，不入失败样本列表

#### Scenario: 开头失败声明仍降级

- WHEN result 终态文本开头即出现失败声明（如「预算已耗尽，无法继续实现」）
- THEN 仍判 failed 且 detail=marker=命中词

#### Scenario: 无信息 result 的信号兜底保持

- WHEN result 为无信息文本且终态邻近 3 行中的事件行（非 result 终态自身）存在预算耗尽类结构信号
- THEN 仍经 _signal_evidence 兜底判 failed

#### Scenario: 信号词仅在 result 终态行时不降级（接受项边界）

- WHEN 结构性失败信号词仅出现在 result 终态行——正文落在 100 字符 marker 窗口之外、或位于该行非 result 字段——且终态邻近事件行无信号
- THEN 该 run 计 succeeded（此形态无检测路径，为已接受敞口，原 lines 全量信号扫描行为不再保留）

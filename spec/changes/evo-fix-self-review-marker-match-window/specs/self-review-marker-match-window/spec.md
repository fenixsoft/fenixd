# self-review-marker-match-window 规格

## ADDED Requirements

### Requirement: 失败声明窗口匹配

_business_fail_marker SHALL 仅在 result 文本前 100 字符窗口内做 _BUSINESS_FAIL_PATTERNS 子串匹配；窗口外的功能词复述 SHALL NOT 触发失败降级。

### Requirement: 假成功抓取语义保持

result 终态文本开头即为失败声明形态（如「SPEC 内容缺失，无法实现」「预算已耗尽，无法继续实现」）的 run SHALL 仍判 failed；本收敛 SHALL NOT 推翻 evo-add-self-review-run-semantics 确立的双源判据及其 pinned 用例。

### Requirement: 信号护栏语义不变

_signal_evidence 终态邻近 3 行护栏与 _scan_run_signals 只补 detail 的既有语义 SHALL 保持不变。

#### Scenario: 成功摘要中段功能词不降级

- WHEN result 终态 is_error=False 且 subtype=success，「预算耗尽」仅出现在摘要中段（如「预算耗尽发一次性 warning」）
- THEN 该 run 计 succeeded，不入失败样本列表

#### Scenario: 开头失败声明仍降级

- WHEN result 终态文本开头即出现失败声明（如「预算已耗尽，无法继续实现」）
- THEN 仍判 failed 且 detail=marker=命中词

#### Scenario: 无信息 result 的信号兜底保持

- WHEN result 为无信息文本且终态邻近 3 行存在预算耗尽类结构信号
- THEN 仍经 _signal_evidence 兜底判 failed

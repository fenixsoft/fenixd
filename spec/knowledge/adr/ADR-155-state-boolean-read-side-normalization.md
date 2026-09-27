# ADR-155：STATE 布尔字段读侧必须显式归一化，禁裸真值判定

date: 2026-09-25
status: accepted

## Context

STATE.md 以 Python 字面量序列化，dashboard 独立进程的解析器读回的是字符串——`False` 是真值字符串。解析器只对登记过的字段（如 `frozen`）做归一化；新增布尔字段若裸 `bool(entry.get(...))` 判定，会把全部带该字段的非保持条目误判为保持态。StateMachine 侧归一化与 dashboard 解析器是两个进程两套读法，不可互推。

## Decision

- 新增 STATE 布尔字段（尤其 `_` 前缀保持态标记）MUST 登记进读侧归一化表，或按统一口径判定（`str(v).strip().lower() in ("true","1","yes")`），禁裸真值/`bool()` 判定。
- 摘要指纹取值白名单 MUST 随新增读取字段同步登记：该白名单是摘要缓存失效判定的唯一取值源，漏登记则「仅该字段变化」不失效、返回陈旧摘要。
- 前端 TS 接口同步声明新字段（弹窗以摘要接口为 props 类型，缺声明即编译失败，构成机械兜底）。
- 用例 MUST 含负例：字段写作大写 `False` 文本时判定为假、对应动作幂等拒绝。

## Consequences

保持态类布尔在 daemon 与 dashboard 两侧判定一致，存量条目零迁移；摘要缓存不因新增读取字段产生陈旧窗口；新字段接入有机械兜底（编译期+负例用例）。

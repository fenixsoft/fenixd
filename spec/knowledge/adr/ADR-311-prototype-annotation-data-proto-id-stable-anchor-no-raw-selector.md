# ADR-311：批注锚定 data-proto-id 稳定锚，禁挂裸 selector

date: 2026-11-02
status: accepted

## Context

原型批注需要精确指向页面元素。裸 CSS selector 在原型重生成后必然漂移（组件树重排、类名重建），旧批注会错位到无关元素；批注错位让整条迭代闭环失真且难以察觉。

## Decision

批注一律以语义化 `data-proto-id` 稳定锚为主键，MUST NOT 引用裸 CSS selector。原型生成时关键区块 MUST 打锚；重生成时 MUST 解析旧原型锚集合，未被需求变更波及的区块 MUST 沿用原锚（MUST 级），被波及的区块允许换锚，批注附带的元素文本快照辅助人工核对换锚错位。锚同时是评审对照键（code-review 检查关键区块与锚的对应）。

## Consequences

- 锚名成为批注主键、重生成保持目标与评审对照键的三重身份，任何触及原型生成、批注器或反馈 schema 的后续 SPEC 都必须维持 `data-proto-id` 通道。
- 锚保持是启发式而非完备：波及区块换锚依赖文本快照人工核对，这是接受的剩余风险。
- 生成 prompt 必须内嵌打锚要求；锚缺失即批注环上游断供，属生成侧缺陷而非批注侧缺陷。

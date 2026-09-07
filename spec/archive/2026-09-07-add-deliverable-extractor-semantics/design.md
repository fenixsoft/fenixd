# Design: add-deliverable-extractor-semantics

## Context

交付物守卫（add-implementer-deliverable-gate）的 `extract_paths` 输出平面路径列表，无法区分「新建交付物」与「既有文件引用」。add-interaction-contract-and-per-assert-triage 的 tasks.md 头部「实现依据（实施 agent 必读）」段引用了 4 个 `.fenix/core/*.py` 既有框架文件——全部被当作交付物；叠加 `.fenix` 自引用符号链接在分支树中是链接 blob（`git cat-file` 类树查找失败），4 轮实现成功全部被误判缺件（2026-08-30 复盘）。热修 4461231 加了归一化复检但无测试覆盖。

## Goals / Non-Goals

- Goals：结构化两类提取；引用语境不阻断；`.fenix/` 归一化正式化 + 测试；引用缺失审计留痕
- Non-Goals：不做自然语言级语义理解（规则表驱动）；不改动守卫的阻断语义与重派路径（只改输入分类）；不改 spec 文档格式要求（现有 tasks.md 结构即兼容）

## Decisions

### D1 语境规则表驱动，保守兜底
`deliverables.py` 内维护语境分区规则：tasks.md 头部至第一个 `## ` 标题之间的说明段、含「实现依据/挂钩点/插入点/真实夹具/上游依赖/参考」关键词的段落 → references；`- [ ]`/`- [x]` 勾选行与「新增/创建」动词行 → deliverables；proposal.md 仅提取「交付/新增」语境。无法判定 → deliverables（保守，宁误拦不漏放——误拦有 3 次封顶 + 引用软校验兜底，漏放则假成功）。

### D2 API 兼容包装
新增 `extract_paths_typed(spec_dir) -> {"deliverables": [...], "references": [...]}`；旧 `extract_paths` 保留为 `deliverables + references` 的拼接（既有调用方/测试不破坏）。守卫调用点改用 typed 版本。

### D3 归一化下沉到校验函数
`.fenix/` 归一化从热修所在的调用点内联逻辑下沉到 `deliverables.py` 的 `normalize_check_path(p)` 纯函数，守卫调用它——逻辑单点 + 可测。热修行为不变。

### D4 引用软校验的日志落点
references 缺失走 `logger.warning("deliverable-reference-missing", ...)`（既有 logger 体系），不进告警系统（避免噪音——引用缺失通常无害）。

## Risks / Trade-offs

- 语境规则表可能漏判非常规写法 → 保守兜底归 deliverables，误拦有既有的 3 次封顶 + 人工解冻路径
- 引用软校验让「文档引用错误」不再被拦截 → 引用错误本就不该阻断实现，审计留痕足够

## Migration Plan

1. deliverables.py：typed 提取 + normalize_check_path + 语境规则（一次提交）
2. 守卫调用点切换 + 引用软校验日志
3. 单测与真实夹具回归（interaction-contract 分支）
无配置变更、无数据迁移。

## Open Questions

（无）

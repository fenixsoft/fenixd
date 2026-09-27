# ADR-036：交付物结构守卫 merge 前零 LLM 校验，提取器语境分类保守兜底

date: 2026-09-07
status: accepted

## Context

实现 run 的成功判定链中 agent 自述成功是唯一输入，实证页面文件未创建仍报成功。引入结构守卫后又实证两类误判：tasks.md 头部「实现依据」段引用的既有框架文件被当作交付物；`.fenix` 自引用符号链接在分支树中是链接 blob，树查找失败——多轮真实成功被误判缺件。

## Decision

- 守卫插在 `is_success` 分支内、merge_back 之前、零变更哨之后；缺件走失败收工（error 记精准缺件清单、ready + 队首重派），复用零变更哨的 3 次封顶与升级告警语义；全程零 LLM 成本。
- 校验基准 = worktree 工作树逐路径存在性检查，不要求已提交（提交由 merge 前既有步骤收口）。
- 提取器为纯函数模块 `core/deliverables.py`，按语境规则表分两类输出：勾选行与「新增/创建」动词行 → deliverables（硬校验）；说明段及含「实现依据/挂钩点/插入点/参考」等关键词的段落 → references（缺失仅 logger.warning 审计留痕，不阻断）。
- 无法判定语境 → 归 deliverables（保守兜底）：宁误拦不漏放——误拦有 3 次封顶 + 引用软校验兜底，漏放即假成功。
- `.fenix/` 路径归一化下沉为 `normalize_check_path` 单点纯函数；守卫走 `extract_paths_typed`，旧 `extract_paths` 保留为两类拼接的兼容包装。
- 缺件重派时上轮 error 注入下轮任务上下文，agent 无需重新考古即知补什么。

## Consequences

- 假成功被结构性拦截且免 LLM 成本；引用错误不再阻断实现（本就不该阻断），留痕即可。
- 非常规写法可能漏识别 → 退化为现状行为（不校验），不会误杀；「方案变更后有意不落地」的路径由 agent 修正任务书后二次提取自然收敛。

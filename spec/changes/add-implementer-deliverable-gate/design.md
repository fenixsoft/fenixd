# Design: add-implementer-deliverable-gate

## Context

实现 run 的成功判定链在 `.fenix/core/pm_engine.py` `_run_agent_worker`：`is_success` → 零变更哨 → `merge_back_from_branch` → `transition(implemented)`。agent 自述成功是唯一输入；v2-config-page 事故中 agent 在页面文件未创建的情况下报成功（其自测受 8787 主仓限制，已由 add-worktree-test-server 解决环境侧），框架缺一道廉价的结构性校验。

## Goals / Non-Goals

- Goals：缺件 run 不 merge 不推进，error 带精准缺件清单；零 LLM 成本；向后兼容（无路径 SPEC 跳过）
- Non-Goals：不做交付物内容/语义校验；不校验测试通过（那是验证链职责）；不触碰验证链与状态机转换规则

## Decisions

### D1 守卫位置：merge 之前、零变更哨之后
插入点在 `is_success` 分支内、`merge_back_from_branch` 调用前。缺件走「失败收工」路径：`_retry_count` 递增、error 记缺件清单、status 置 ready 并 `_enqueue_front` 重派（复用零变更哨的既有重试机制与 3 次封顶语义——封顶后 blocked 升级告警，防缺件死循环烧钱）。

### D2 提取器为纯函数模块 `core/deliverables.py`
输入 SPEC 目录（tasks.md + proposal.md 文本），输出去重路径列表。提取规则：反引号/代码块/「路径」字段中匹配 `^(core|tests|\.fenix|scripts)/` 的条目；排除以 `/` 开头的绝对路径、通配符与目录（以 `/` 结尾）条目。单测夹具直接复用 v2-config-page 真实文档。

### D3 校验基准是 worktree 工作树（含未提交变更）
在 worktree 路径下逐一 `os.path.exists`。不要求已提交——agent 报成功时允许未 commit 的新文件，与 merge 流程（merge 前由既有提交步骤收口）不冲突。

### D4 缺件重派携带上下文
error 字段写明「交付物守卫：缺件 [路径…]」，重派 run 的任务书生成处（agent_runner prompt 构建）把上轮 error 注入上下文，agent 无需重新考古即知补什么。

## Risks / Trade-offs

- 提取器可能漏识别非常规写法的路径 → 保守方向（漏识别=不校验=行为退化到现状，不会误杀）
- 路径写了但实现方案变更为不落地该文件 → agent 收工时补一行说明即可被「声明清单」机制覆盖（tasks 勾选变更）……首版不做文档反写，缺件重派后 agent 自行修正任务书，第二次提取自然收敛
- 3 次封顶可能拦住「需要第 4 次」的合法场景 → 与零变更哨共用阈值，人工可解冻，先保守

## Migration Plan

单次提交：deliverables.py + _run_agent_worker 插入点 + 单测。无数据迁移、无配置变更。

## Open Questions

（无）

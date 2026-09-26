## Deliverables

```yaml
- path: docs/help/05-verification.md
  kind: modify
- path: docs/help/06-governance.md
  kind: modify
- path: docs/help/07-safeguards.md
  kind: modify
- path: docs/help/08-dashboard.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: docs/help/README.md
  kind: modify
- path: docs/help/02-concepts.md
  kind: modify
- path: docs/help/03-lifecycle.md
  kind: modify
- path: docs/help/12-faq.md
  kind: modify
```

## 1. 验证体系章修正（docs/help/05-verification.md）

- [ ] 1.1 verdict 四分类表：blocked-env 行流向改写为两级豁免握手口径（级一 judge 前全批 → inconclusive；级二 judge 后断言归因全 env 在采纳前拦截不落 verified；豁免须 admin DISPOSITION 放行，信号 `inconclusive_loop`），锚点 escalation.py:46,70,1316,1564 / pipeline.py:1009；inconclusive 行流向改写为自动重验链（回 implemented 重派，≤`verify_engine.inconclusive_max_attempts` 缺省 3 轮，第 4 轮停等人工），锚点 escalation.py:88-101,1410-1422；改前实读锚点核对数值
- [ ] 1.2 三步流水线段与时序图说明：出题时机改为「spec 进 ready 即并行出题（与实现并行）」，删除「implemented 后串行出题」语义的表述；机制细节不展开（由姊妹 SPEC 补齐）
- [ ] 1.3 场景冻结与跨轮复用节：变更通道由两条改三条，新增契约版本迁移自动通道一句（`contract_version`，v2=web 必含 navigate，旧集自动合成或回落出题），保留原两条通道描述
- [ ] 1.4 全文 grep 自检：无「回 testing 重派新 attempt」（blocked-env 旧流向）、「不产生 verdict 信号」（inconclusive 旧流向）、「只设计一次……绝不重新出题」之外与并行出题矛盾的旧串行表述残留；相对链接与标题锚点保持有效

## 2. 治理规则章修正（docs/help/06-governance.md）

- [ ] 2.1 「优先级与并发」节整段改写为宽松优先级并行口径：任务 X 可派发当且仅当没有比 X 更重要的活动任务（min(active_priorities) >= X）；同档并行至 max_concurrent；不同档可并发；不抢占；队列老化（effective 档位、活动集合记 base 原值、同级 FCFS、仅内存态），锚点 queue.py:496-520,226-275；删除「不同优先级之间不并行，低优先级必须等所有高优先级 SPEC 完成后才会启动」
- [ ] 2.2 「相关参数」表 `agents.max_concurrent` 默认值 2 → 5（实读 queue.py 缺省核对）
- [ ] 2.3 全文 grep 自检：无「严格优先级」「不同优先级之间不并行」残留；12-faq 引用旧调度口径处同步修正（第 1 条根因列表如涉及）

## 3. 保障机制章修正（docs/help/07-safeguards.md）

- [ ] 3.1 autostash 回收段：删除「冲突时自动解决（UU → add）」，改写三分诊（git merge-file 三方重试 → 逐文件 checkout --theirs + commit --only 留审计 → 兜底落工作区 + 登记 disposition；stash 条目一律保留记账），锚点 stash_guard.py:134-165,274-360
- [ ] 3.2 状态机转移门节：「SPEC 的十状态生命周期」→「11 状态」（含 reviewing），括号内状态清单补 reviewing
- [ ] 3.3 全文 grep 自检：无「十状态」「UU → add」残留

## 4. Dashboard 章修正（docs/help/08-dashboard.md）

- [ ] 4.1 「质量」页签第一张卡片描述：收尾代码审查形态改写为框架侧异步并行车道（merge-back 成功 + tester 派发时点框架启动、不占 agent turn、实现者不等待、产物硬门已摘除）；删除「实现者在……写结果文件之前调用 ocr」内联表述
- [ ] 4.2 审查三运行参数段：`--concurrency` 由「经提示词命令示例承载（软约束）」改为「经车道命令注入、确定性生效」，缺省 2 → 4（实读 config.py 核对）；`--effort` 软约束表述保留核对（effort 仍经提示词承载则以代码为准）
- [ ] 4.3 「项目架构」分面段：超时表述由「1800 秒硬超时，超时会整组击杀」改为两段式——探索段 ≤720s、出图段 ≤1080s 分段击杀（总预算 1800s 不变）；补 HEAD 指纹一致时重试跳过探索段、status 增 `stage` 键各一句；错误文案提及阶段前缀
- [ ] 4.4 全文 grep 自检：无「1800 秒硬超时」残留（两段式表述中的「总预算 1800」不算）；无「写结果文件之前调用 ocr」残留

## 5. 配置参考章修正（docs/help/09-config.md）

- [ ] 5.1 agents 键表 `max_concurrent` 默认值 2 → 5（实读核对）
- [ ] 5.2 admin.code_review_fix 节回归失败处置描述整段重写：定向重试 ≤`targeted_retry_max`（缺省 3，1-5 越界回退）轮、只重跑失败子集（映射失败 fail-closed 回全量）；耗尽现场即弃（cleanup+放锁）入失败档案；FAIL_RETRY_MAX=3 预算内新链自动重试、达上限一次性告警 + todo；删除「自动重试一次」「worktree 保留待人工」「release_failed_batch」旧世界表述；键表补 `targeted_retry_max` 行
- [ ] 5.3 同节「跑全量回归」→「首轮全量、定向轮只重跑失败子集」；「30 分钟 full scan 周期兜底」→ 标注 `schedule.poll_interval_minutes`（缺省 30，非 code-fix 专属键）
- [ ] 5.4 admin.shutdown_drain_seconds 双侧行为说明补规划性重启豁免（restart_request 在场时按 `agents.run_drain_max_seconds` 排水、不被 0 夹紧；快速停机仅非规划性关停），与 14-pipeline-throughput-ops.md 口径一致
- [ ] 5.5 verify 段 `impl_code_review_concurrency`：缺省 2 → 4、「经提示词命令示例承载（软约束）」→「经车道命令注入硬生效」；`impl_code_review_effort` 承载方式按代码实况核对后表述
- [ ] 5.6 agents.models 节：「键取十个角色」→ 11 角色，键清单补 `code-fix`；code-fix 模型链描述与既有 admin.code_review_fix 节交叉引用核对
- [ ] 5.7 admin.code_review 节审查路径：「再由 agent 逐文件落 `out-<run_id>.jsonl`」→ 分片直写口径（子代理各写 `out-<run_id>-b<N>.jsonl`，读侧聚合，主产物仅兜底），锚点 code_review.py:56-129
- [ ] 5.8 全文 grep 自检：无「保留待人工」「release_failed_batch」「十个角色」残留；「模板值与代码缺省不一致」表与本节新口径不冲突

## 6. 目录与概念章口径修正（docs/help/README.md、02-concepts.md）

- [ ] 6.1 README.md 目录表 03 行简介「10 状态全景与合法转移」→「11 状态全景与合法转移」
- [ ] 6.2 02-concepts.md 架构图 Agent Pool 标题「十一类 Agent」→「十二类 Agent」，表格补 code-fix 行（职责：按批修复 code-review 台账 open 条目、独立 worktree 修复+全量回归通过才合回；触发：审查收尾产生新 open 条目 / full scan 周期兜底 / 项目页手动触发）；正文「十一类」字样同步
- [ ] 6.3 全文 grep 自检：两文件无「10 状态」「十一类」残留

## 7. 事件枚举口径修正（docs/help/03-lifecycle.md、12-faq.md）

- [ ] 7.1 03-lifecycle.md「状态变化事件与 Hook」节：「事件类型即目标状态（十状态枚举）」→「（11 状态枚举，另含项目级伪事件 `all-done`）」；补 all-done 一句语义（全部 SPEC 到达终态时发布的项目级伪事件，实读 hook_engine.py 核对）
- [ ] 7.2 12-faq.md 第 11 条：「events 拼写不在十状态枚举内」→「不在 11 状态枚举（含 all-done 伪事件）内」
- [ ] 7.3 全文 grep 自检：两文件无「十状态」残留；hook 章节交叉引用（09-config hooks 段「十状态枚举」字样）一并核对修正

## Context

读端硬门：core/verify_engine/scenarios.py:1545-1547（load_scenarios，:1524 起）顶层非数组抛 ValueError；归因与反馈：core/pm_engine/verification/pipeline.py:2097-2105（env_error=「场景文件验收失败: …」）、REPLAN_FEEDBACK 写点 :2748-2754（「重新输出全部场景」硬编码，通过后 :3133 unlink）；并行出题隔离先例 _quarantine_parallel_product（core/pm_engine/engine.py:961-985，rename 保留现场）。提示词：agents/planner-plan.md:7-8 仅顺带式「合法 JSON 数组」；core/agent_runner/prompt_builder.py 的 _scenario_schema_section（:2262 起，单源表运行时渲染）与 _result_gate_section planner 段（:2648-2662，仅要求「可解析的非空 JSON」）。混淆源：同目录 scenarios.json 为 dict（core/verify_scenarios.py:279-284）。实证：round-4 会话持久化枚举文件（potplayer-base/.fenix/agent-config/…/tool-results/bkf3rt1ul.txt，31KB）自证被拒产物当时在盘且 25 场景可完整枚举。

## Goals / Non-Goals

- Goals：顶层形状成为静态模板+运行时注入的双侧显式契约；「一层包裹错误」在验收路径内零成本闭环；格式类拒收反馈引导最小修复。
- Non-Goals：不做条目级 schema 变更；不动冻结层 scenario_gate 语义；不建产物快照/回收站机制；不改 judge 结果文件生命周期（evo-add-judge-result-predispatch-rename 非目标已显式排除 scenarios 产物，两侧互补）。

## Decisions

- D1 拯救形态收窄到「顶层 dict 且含 scenarios 数组」唯一形态：该形态语义无歧义（round-3 实锤形态），解包后必须重过既有全部场景校验才落地，等价于零成本重验；其余非数组顶层（字符串/数字/列表套列表等）不拯救，照常拒收。拯救助手放 core/verify_engine/scenarios.py（load_scenarios 旁），由 pipeline 验收路径显式调用，load_scenarios 本体语义不变。落地 = 以解包后的纯数组**原子重写 test_scenarios.json**，不是仅内存采纳：仅内存采纳会让其余 load_scenarios 读端（fastlane.py:429/466、verdict_evidence.py:1310、pipeline.py:1619/2150）在后续轮仍撞顶层硬门，冻结层顶层读端（scenario_gate.py:167-173）也会持续按「顶层非列表」告警跳过；重写为纯数组后这些读端按既有语义自然恢复，故拯救单点接入验收归因点即可，其余读端不接助手。
- D2 契约双侧注入：agents/planner-plan.md 静态模板（工作流语义层）+ _scenario_schema_section 单源表（运行时强约束，仅 planner-plan agent_type 生效），与归档 evo-planner-scenario-schema-alignment 的单源渲染架构同构；_result_gate_section 的 planner 段不动（其按 agent_type 分派的语义只管结果门）。
- D3 REPLAN_FEEDBACK 分类文案在既有写点生成：格式类（顶层形状/条目结构 ValueError）→「最小修复」指引（错误类别+修复动作）；内容类（场景缺失等）→ 保留全量重建指示。分类依据按失败发生阶段判定（顶层形状→拯救路径；解包后条目校验失败→格式类），不新增错误文本解析器——验收异常为纯文本 ValueError（core/verify_engine/scenarios.py 无结构化类别字段），不存在可「复用」的现成错误类别字段；取宽口径——凡可通过小改动修复的归格式类，误判代价是多给一条修复指引，不阻塞重建路径。
- D4 解包落地必须留痕：解包属框架改写 agent 产物，在日志/进度留痕（解包前顶层键、条目数、落地结果），便于事后审计「验收器替 agent 修了什么」；同时契约已双侧明示，再现 dict 包裹即 agent 违约，反馈仍会指出——解包只作一次性止损，不弱化契约约束。

## Risks / Trade-offs

- 机械解包可能被 agent 依赖成「包错也无妨」：以「双侧契约+留痕+反馈仍指出错误类别」对冲；解包仅覆盖唯一无歧义形态。
- 格式/内容分类边界存在模糊（如「条目缺字段」两可）：宽口径归类，代价有限。
- 解包重写产物文件与并发冻结写回竞态：落地点在验收失败路径（该路径下产物本将被 replan 覆盖），竞态窗口与既有 replan 写点相同，不新增暴露面。
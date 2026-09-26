## Context

08-29~09-22 期间全部真实人工裁决复盘（admin_alerts.json 150 条 + 轮转日志）表明：裁决本质是选择题（继续修 / 人工修完重验 / 接受现状推进 / 撤销 / 知情），但当前告警只有「查看 / 清除 / 唤起 Administrator」三个动作，真正裁决必须登录 claude code 手工改 STATE.md。dashboard 后端动词已很全（`admin_actions.py` 19 个），缺的是：告警↔动作关联、3 个裁决动词（重置验证/豁免推进/跳过评审门）、Administrator 开放散文处置与人工裁决共用同一空间。

信号分诊结论（本 SPEC 范围界定）：桶 0 知情/自愈类（stale_code、瞬断风暴、run_infra 恢复、run_cancelled、误报）不出选择题只出「知道了」；桶 1 框架可自愈缺机制类已由存量 spec 补完（evo-orphaned-state-probe-calibration、evo-stash-pop-conflict-triage、evo-admin-disposition-reschedule 等均 pushed），不在本 SPEC 范围；本 SPEC 只做桶 2 真裁决类。

## Goals / Non-Goals

- Goals：告警内嵌下拉选择；一次选择=动作执行+状态推进+handled+留痕的完整闭环；Administrator 与人工共用同一裁决空间
- Non-Goals：不改动信号发射/冻结判定的触发逻辑（阈值、熔断条件不动）；不做桶 1 机制补全（signal_type 透传缺口另立 fix-manual-invoke-signal-type-passthrough）；不做裁决选项的动态/LLM 生成；不实现完整 /fenix-approve 工作流（只做 force_advance 最小等价）

## Decisions

- **D1 静态注册表而非告警内联硬编码**：choices 映射集中在 `adjudication_choices.py`，发射点只引用。理由：注册表是 Administrator 契约与前端渲染的共同事实源；分散内联会让三处漂移。
- **D2 choices 存进告警记录而非渲染时现查**：写告警时快照 choices 进记录（`admin_alerts.json` 新增可选字段），渲染/resolve 端点优先用记录内值。理由：告警是历史事实，注册表后续演进不应改写历史告警的选项集；resolve 校验以记录内 choices 为准，缺失时回退注册表。
- **D3 resolve 端点编排而非前端多次调用**：动作执行+状态推进+handled+留痕全部在 `/api/alert-resolve` 单次调用内完成。理由：前端多次调用无原子性，中途失败会产生「解冻了但没推进」的中间态。
- **D4 force_advance 走状态机合法推进路径**：不绕过 StateMachine 直写 STATE.md；目标状态缺省 done 但校验目标可达性，不可达时经显式豁免通道（对齐既有 update_spec 携 frozen=False 的显式传参语义）。
- **D5 Administrator 契约改 prompt 段落**：在 `agents/administrator.md` 增补 choices 消费段（契约段=动态段+agents/*.md 既有范式），处置记录结构化字段新增 `choice_id` / `suggested_choice` 两个可选键，读取路径按缺省 None 兼容。

## Risks / Trade-offs

- [choices 快照与注册表漂移] → resolve 校验以记录内 choices 为准；注册表演进不回写历史告警，文档标注。
- [force_advance 被滥用绕过质量门] → 前置校验仅限冻结/blocked 态；留痕强制含「人工豁免」标记；abandon/skip_review_gate 前端二次确认。
- [reset_verification 删运行时文件误伤] → 仅删 `.fenix/verify-progress/<spec>/` 下该 spec 自己的场景/进度文件，路径按 spec 名精确匹配（吸取「僵尸 dashboard 删 runs」事故教训，禁止通配清理）。
- [emit 点改造遗漏] → 注册表覆盖的 signal_type 列表即测试清单，逐信号断言告警记录含 choices。

## Migration Plan

存量告警无 choices 字段按无选项渲染（兼容读取）；daemon 无需重启顺序约束（发射点与读取端同步合入，字段可选向后兼容）。

## Open Questions

- 配置裁决类（build_artifact_paths_missing）的「open_config」选项跳转 settings 表单的交互形态，实现期按现有 settings 路由定，不阻塞本 SPEC。

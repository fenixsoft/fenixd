## 2026-09-28

### 失误
- （当日无）

### 可改进
- **affinity-batching 首验证批均降 25% 条均反升 22% 未收敛**
  - 自进化：问题成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：affinity-batching（code-fix 批次的选批亲和性聚类机制）生效后首个全量消化窗口：7 个 code-fix 批消化 163 条台账共 2253 轮，批均 322 轮较基线批均约 430 轮降 25%，但条均 13.8 轮较基线 11.3 轮不降反升 22%，仍为同组中位（96.5 轮）的 3 倍以上——消化成本未实质收敛，复发敞口为每轮审查消化 2000+ 轮级 runner 消耗。
  - 证据：run metrics：code-fix-1790471986（730 轮）、1790473640（408）、1790474787（415）、1790476127（379）、1790477784（182）、1790479244（18）、1790481526（121），合计 2253 轮；对应 09-27 本地 09:42-12:17 的批次「fix: 修复 code-review 台账条目（code-fix batch）」提交与 4 次 merge code-review-fix-*（10:28/10:55/11:20/12:22）；基线见既有条目 2026-09-27#可改进#2：5 批 290-562 轮、批均约 430 消化 191 条。
  - 调查评估：本窗口批次全部跑在 add-codefix-affinity-batching（09-26 23:44 落地）生效之后，构成该机制的首个对照样本。已核实：批均轮数下降（批切分更均匀，出现 18 轮小批），但单位条目成本不降反升，7 批中 5 批（379-730 轮）仍为组中位的 3.9-7.6 倍离群。结论：affinity-batching 的「批间均衡」目标见效、「降条均成本」目标未兑现，既有条目 2026-09-27#可改进#2 建议的下一步（仍离群则上预聚类）触发条件已成立，该既有条目不判闭环。
  - 建议：按 2026-09-27#可改进#2 原建议推进：先抽样 2 个大批（730/415 轮）逐轮归因确认轮数花在哪（读代码 vs 自检重跑），再决定台账 ingest 时按严重度/文件亲和性预聚类（同文件多条合并单批）的方案；预聚类立项后以本窗口条均 13.8 轮为对照基线。

## 2026-09-29

### 可改进
- **消化条均轮数三连升至 15.0 预聚类决策条件已成立（恶化）**
  - 自进化：问题部分成立 / 建议部分合理 / ✓ 值得立项 · 处理：接受 · 删除：否
  - 影响：affinity-batching（code-fix 批次选批亲和性聚类机制）生效后第二个全量消化窗口：12 个成功批消化约 252 条台账共 3786 轮，条均约 15.0 轮、约 0.33 美元，较基线 11.3 轮累计上升 33%；535、487、480、429 轮的四个大批单批 8.5 至 13.6 美元——消化成本恶化趋势未扭转，复发敞口为每轮审查消化 4000 轮级 runner 消耗。
  - 证据：本窗口 13 个 code-fix run 轮数：307、299、535、278、487、429、366（失败）、480、32、230、388、49、272；消化来源为周期审查 code-review-1790528604 出账 233 条（fenixd.log 2026-09-27T18:20:42Z「inserted=233, shards=13」）加 429 死亡审查抢救的 19 条，共约 252 条；基线对比：2026-09-27 条目批均约 430 轮、条均 11.3，上一窗口批均 322、条均 13.8。
  - 调查评估：本条为 2026-09-28#可改进#1 的重述（恶化）：本窗口批均 3786 除以 12 批约 316 轮，与上窗口 322 持平，条均 15.0 较 13.8 续升 9%——「批间均衡见效、条均成本不降」的判断在第二个窗口继续成立且恶化，原条目预设「仍离群则上预聚类（同文件多条合并单批）」的触发条件进一步坐实。已核实：evo-add-codefix-digest-cost-metrics（消化链成本指标 SPEC）已于 09-28 02:56 merge（提交 9580f37c），链级 rollup（每链 run 数、总轮数、工具调用合计的落盘汇总与结构化日志）从此可用，本窗口批次跑在其生效当天、未产出 rollup 数据。结论：归因的数据机制已就位，预聚类立项的决策输入已齐。
  - 建议：用新落地的 rollup 指标抽样 535 轮与 487 轮两个大批做轮数构成归因（读代码与自检重跑占比），据此决策台账入库时按严重度与文件亲和性预聚类；立项后以条均 15.0 轮为对照基线。

## 2026-09-30

### 知识真相源
- [ ] knowledge-distill 重试：归档 2026-09-30-evo-fix-worktree-name-collision-retry — 校验违规经 3 轮 run 仍未通过

- audit 语义项转写失败：contradiction（spec/knowledge/domains/dashboard-platform/v2-data-adapters.md × spec/knowledge/domains/dashboard-platform/v2-sdk-vendor.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/dashboard-platform/v2-data-adapters.md × spec/knowledge/domains/dashboard-platform/v2-legacy-coexist.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/dashboard-frontend/task-progress-phase-display.md × spec/knowledge/domains/implementer-lane/artifact-path-declaration.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/code-review-lane/impl-code-review-tuning.md × spec/knowledge/domains/dispatch-scheduling/dispatch-concurrency-tuning.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/code-fix-lane/code-fix-manual-trigger.md × spec/knowledge/domains/code-review-lane/code-review-trigger-ack.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/code-fix-lane/code-fix-config.md × spec/knowledge/domains/dispatch-scheduling/dispatch-concurrency-tuning.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/code-fix-lane/code-fix-config.md × spec/knowledge/domains/code-review-lane/impl-code-review-tuning.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/agent-runtime/long-task-foreground-wait.md × spec/knowledge/domains/verify-pipeline/blocked-reverify-gate.md），请人工核查

- audit 语义项转写失败：contradiction（spec/knowledge/domains/admin-ops/stuck-signal-hygiene.md × spec/knowledge/domains/self-evolution/stale-selfheal-cooldown.md），请人工核查

## 2026-10-01

### 知识真相源
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/code-fix-lane/code-fix-config.md × spec/knowledge/domains/dispatch-scheduling/dispatch-concurrency-tuning.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核
- audit 语义项转写失败：contradiction（spec/knowledge/domains/code-fix-lane/code-fix-config.md × spec/knowledge/domains/code-review-lane/repo-review-concurrency.md），请人工核查
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/code-fix-lane/code-fix-config.md × spec/knowledge/domains/code-review-lane/impl-code-review-tuning.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/agent-runtime/long-task-foreground-wait.md × spec/knowledge/domains/verify-pipeline/blocked-reverify-gate.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核
- audit 疑点升级待人工：contradiction（spec/knowledge/domains/admin-ops/stuck-signal-hygiene.md × spec/knowledge/domains/self-evolution/stale-selfheal-cooldown.md）连续 2 轮复核无确定性判定，请人工仲裁；消费后删除 .fenix/knowledge_audit_findings.json 对应条目即恢复自动复核

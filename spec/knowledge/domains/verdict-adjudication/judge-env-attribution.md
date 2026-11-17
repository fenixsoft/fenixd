# judge env 归因证据门（量测 + 窗外对照）
<!-- knowledge: capability=judge-env-attribution rev=1 sources=spec/changes/evo-env-attribution-evidence-gate -->

judge 对场景失败作出 env 归因的接受门：accept 须同时引用可复核环境量测与验证窗口外对照样本，缺证降级 requeue 进回炉重检闭环——无对照的 env 结论不得入档、不得驱动豁免握手把真问题以环境豁免放行。

## 规则

- 双证据要件：judge 给出 env 归因时，evidence MUST 同时具备，两者缺一不得给出 env accept——①至少一项可复核环境量测（负载/CPU/内存/温度/驱动版本/网关错误码等具体数值及其来源）；②至少一个验证窗口外的对照样本（同宿主历史轮次或窗口外重跑数据）。两轮同窗自测数值不构成对照——窗口内重跑共享同一负载条件，无法排除高负载互扰。
- 判据单源与结构化字段优先：证据门判据单源 `judge_files.judge_env_evidence_gate`——优先校验条目结构化字段 `measurement_refs`（量测引用列表，每项含数值与来源）与 `control_samples`（对照样本引用列表）非空，缺失时回退检查归因文本的量测数值模式与窗外对照引用。
- 主门（accept 条目构造）：归因查重阶段对 env 分类、证据门不过的非 PASS 场景，拒绝并入查重结果 requeue 子集（requeue_ids/violations/counts/ok 同步改写），不落 accept；缺失要件写入条目注记与 violations 理由；条目 status 词表保持 accept/requeue 不变（降级以 requeue 表达，不新增第三状态）。pass 场景无归因对象不受门约束；引擎级联豁免合成条目（归因非 judge 产出）不参与本门。
- 辅门（截断恢复判据）：`_scenario_classified` 对 env 条目加验证据门——缺证据字段不视为「已归因存档」，截断恢复不沿用该条目、重试 judge 重裁决（迁移期历史 checkpoint 中无证据字段的 env 条目会被重裁决一次）。
- 降级接线与出口：降级条目按 requeue 状态进入既有回炉重检闭环（`_handle_scenario_requeue` → 回炉清单 → 轻量重合成 judge run 只重做 requeue 子集 → 回灌完整校验链，各轮次共用同一归因门入口）；重合成轮回灌即对补充证据后的归因重新评估，量测与对照齐全才 accept。降级条目 MUST NOT 直接驱动豁免握手（env 三选一）或以 env-accept 语义进入收尾；blocked-env 全批 inconclusive 通道（`_handle_env_blocked_inconclusive`）语义不变，见 [inconclusive-loop-escalation](inconclusive-loop-escalation.md)、[verdict-env-exemption-handshake](verdict-env-exemption-handshake.md)。
- 与媒体词汇证据门叠加：env 结论含媒体管线词汇（帧/解码/编码/推流等）时另有送帧/解码双段证据门（见 verdict-env-exemption-handshake 页），两门叠加适用，共同方向为宁降级不误 accept。
- schema 向后兼容：judge_attribution.json 条目新增可选字段 `measurement_refs` / `control_samples`；读取侧缺失字段按空处理，旧文件可读、消费方零改动。
- 治理失败隔离：证据门自身异常只记 warning、既有查重结果照常返回（附加治理失败 MUST NOT 丢弃查重结果）；降级回炉为轻量重合成（不重跑 tester），受回炉预算、查重递归上限与 inconclusive 重验上限约束，成本有界。

## 代码锚点

- 证据门判据单源：`core/verify_engine/judge_files.py`（`judge_env_evidence_gate`、`measurement_refs` / `control_samples` 字段常量）
- 主门（拒绝并入查重）：`core/pm_engine/verification/verdict_evidence.py`（`_merge_env_evidence_gate_rejections`）
- 辅门（截断恢复判据）：`core/agent_runner/prompt_builder.py`（`_scenario_classified`）
- 提示词双要件：`agents/planner-judge.md`（env 归因双要件与反例段）
- 守卫测试：`tests/test_env_attribution_gate.py`

## 溯源

- 2026-11-17 evo-env-attribution-evidence-gate（spec/changes/evo-env-attribution-evidence-gate/） — 新建本页：env 归因 accept 双要件（可复核量测+窗外对照）、主门拒绝并入 requeue 回炉闭环（不驱动豁免握手）、辅门截断恢复判据收紧与产物 schema 证据引用字段（向后兼容）。动因实测：judge 仅凭两轮同窗自测 fps 即把失败归因 env 并 accept 入档，驱动豁免握手与 judge_rerun_cap 二次冻结后仍需人工收口，真缺陷以 env-accept 进终态

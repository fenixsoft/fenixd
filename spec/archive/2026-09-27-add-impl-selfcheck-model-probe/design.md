# add-impl-selfcheck-model-probe 设计

## Context

实现失败重做占全历史 207h（8.6%），三类实证重烧源：

- **契约类**：`core/agent_runner/result_gate.py` 的 `_validate_code_review_report` 逐条 `isinstance(disp, dict)` 校验 dispositions，字符串数组被拒 → 整轮判失败原地重派；agent 在 run 内看不到 daemon 侧报错，r1/r2/r3 照抄坏形状（add-impl-ocr-parallel-lane 实烧两轮）。处方已在项目记忆中验证：「收工前直接调生产校验体自证」，本 SPEC 将其产品化。
- **拒模型**：maomaoai/deepseek-v4.1-flash 返回 `[claude-code:unrecognized_model]` → Exit 1 零 token；近 48h 内 22 个 impl run 秒死，fix-relocation-writeback-layer 一晚 12 个、同因重派每 2-5 分钟一个。现状澄清（评审实核，修订原断言）：add-provider-failover 已把 unrecognized_model 归为**切换类错误**（`core/agent_runner/provider_circuit.py` 的 `SWITCH_ERROR_TEXT_PATTERNS` / `classify_switch_error`），同 run 内驱动链前进 + 300s switch 冷却，并非「当 transient 延迟重派同模型」。循环的真根因是：冷却到期即复位优先、run 失败归因不含「全链模型不可用」语义，派发器按既有同因重派继续——每 2-5 分钟（≈冷却 300s）重派再撞同一拒模型条目。处方因此不是新造 failover，而是补齐归因/计数语义 + 链摘除断根。
- **回归双跑**：implementer run 内手工跑 `bin/run_full_suite.py`（实测 8-10m/次，占成功 run 时长可观比例），框架侧回归模块（`core/regression.py`，与 `bin/run_full_suite.py` 共享主机级 fcntl 锁）在 testing 阶段必然再跑。add-quality-gates-visibility 已把 run 内自查 3 项（full-suite / frontend-build / interaction-contract）落盘 `quality-gates.json`，`full-suite` 门目前以 run 内自查为数据源。

## Goals / Non-Goals

**Goals:**

- agent 收工前能自证结果文件合法，契约类失败在 run 内修复而非重派整轮。
- unrecognized_model 秒死不再产生同因重派循环，链上 failover 一次到位。
- 全量回归判定责任单点化到验证链，impl run 不再内联必跑回归。

**Non-Goals:**

- 不改 result_gate 任何判定逻辑本身（只暴露入口，daemon 侧硬门原样保留作兜底）。
- 不做派发前主动 LLM 探测（成本高；只处理 provider 已明确返回的拒模型错误）。
- 不改其他 provider 错误（5xx/超时/黑洞）的处理路径（已有瞬断熔断治理）。
- 不动 quality-gates.json 的文件路径、键名全集与状态枚举（只改 full-suite 数据源优先级）。

## Decisions

1. **自检入口形态 = result_gate 模块的 `__main__` CLI**：`python3 -m core.agent_runner.result_gate --selfcheck <结果文件路径>`（worktree 内可跑、零网络、零 daemon 依赖），复用生产校验体（同一函数对象，非复制逻辑），退出码 0=PASS / 1=FAIL，违规明细逐条打 stderr。备选「独立 lint 脚本」被否：逻辑复制必然漂移（键名契约缺口事故的教训）。prompt 注入位置：`prompt_builder.py` implementer 收尾检查段，措辞含「结果文件写完必须先跑自检、非零退出不得收工、按 stderr 明细修复后重跑至退出码 0」。

2. **正反例进任务书模板（prompt_builder 注入）**：dispositions 合法形态 `[{"disposition": "fixed"}, {"disposition": "deferred", "reason": "..."}]` vs 非法形态 `["fixed", "fixed"]`，逐字对照；同步覆盖 `status` 枚举与必填键，防同类形状陷阱。`agents/implementer.md` 静态模板只放通用原则（动态契约段经 prompt_builder 注入，与 quality-gates 契约同模式），避免静态/动态双源漂移。

3. **拒模型 failover 增强挂在既有链前进机制上**：`unrecognized_model` 错误（provider_marker 后 stderr 出现 `[claude-code:unrecognized_model]` 或等价结构化类别）沿用既有 `classify_switch_error` 判别（复用 add-provider-failover 的候选链前进与 switch 冷却机制，MUST NOT 新建平行切换路径），增量在三处：①识别命中即记 WARNING（含 provider/model/run_id，供摘除决策）；②链尾模型仍被拒时，失败归因 MUST 含「全链模型不可用」语义，派发器不得对该归因走同因重派（这是阻断 2-5 分钟循环的关键）；③切换不递增 transient 熔断/同因重派计数。备选「派发前主动 probe」被否：每次 run 前多一次 LLM 往返，成本与延迟不划算，且拒模型是 provider 明确返回的类别，事后识别零成本。

4. **链卫生：模板确认 + 运行时人工摘除**：`.fenix/config.template.yaml` 经评审实核**本就不含任何活动模型链定义**（非注释内容全为调度参数，`maomaoai` 全文零命中），链仅存在于运行时 `.fenix/config.yaml`（各 agent 链 4 条目，maomaoai/deepseek-v4.1-flash 排第三）。故模板侧交付为「确认无该组合条目 + models 注释示例处加一行拒模型警示注释」（模板唯一实际改动，满足交付物 modify）；运行时 `.fenix/config.yaml` 摘除该条目是人工运维步骤——写入 `docs/help/13-model-chain-ops.md`（并在 `docs/help/README.md` 索引登记；含摘除理由、恢复条件、修改步骤，及「在 `.fenix/todo.md` 登记提醒」的指示）。**不进 tasks.md 门禁**（主树运行时配置/todo.md，Agent 在 worktree 内改不到生效副本，implementer 车道亦无主树写授权）。

5. **full-suite 门数据源优先级：框架侧回归产物 > run 内自查 > pending（fail-open）**：读侧合成处（`core/dashboard/data/` 门禁合成）先查框架侧回归车道产物（`core/regression.py` 落盘的回归结果快照，含分支指纹校验，模式对齐 ocr 门的 `(branch, base, head_commit)` 指纹语义）；产物不可见或指纹陈旧时回退读 quality-gates.json 的 run 内自查值（兼容存量与降级路径）；两者皆无 → pending。**状态枚举与键名全集零变化**（`quality-gates-progress` 能力 delta 仅扩展数据源，不破坏既有读侧）。

6. **implementer 收尾自查从「必跑回归」改「降级路径」**：prompt 注入措辞改为「全量回归由验证链执行；仅当确认框架侧回归产物不可用（如验证链被冻结/跳过）时才在 run 内执行并落盘」。frontend-build / interaction-contract 两项自查不变。agent 无法确证框架侧产物是否可用时默认不跑（信任验证链），漏跑由读侧 pending 呈现而非打回——**不得**因 full-suite 项 pending 新增任何打回门。

## Risks / Trade-offs

- **自检被 agent 忽略** → prompt 强注入 + daemon 侧 result_gate 硬门原样保留（双保险，最坏回到现状打回路径，不劣化）。
- **failover 误判**（把其他错误当 unrecognized_model）→ 仅严格匹配该结构化类别；误判后果 = 跳过一个本可用的模型，链上还有 3 个备选，可恢复。
- **回归外包后 impl 失去快速回归反馈** → frontend-build/交互契约自查仍在；回归缺陷走既有 bug-found 环。权衡记录：省 8-10m/轮 × 重试轮数 vs 反馈延迟一个验证阶段，吞吐优先。
- **`agents/implementer.md`、`core/agent_runner/provider_circuit.py` 主树存在未提交 WIP** → merge-back 冲突风险；实现分支基于最新 main 创建可规避大部分；冲突时按混合工作区手术式提交处方处理。
- **框架侧回归产物契约现状** → 路径已固化：项目级单快照 `.fenix/regression/last-run.json`（`core/regression.py` 的 `read_result`/`write_result`，缺失/损坏返回 `never_run`/`parse_error`），但快照**无分支指纹字段**——本 SPEC 须在写侧 stamp `(branch, merge_base, head_commit)`（`core/regression.py` 入交付清单），无指纹字段的存量快照按「不可见」处理（回退 run 内自查值），不阻塞。

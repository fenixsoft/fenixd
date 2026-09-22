# add-impl-selfcheck-model-probe 设计

## Context

实现失败重做占全历史 207h（8.6%），三类实证重烧源：

- **契约类**：`core/agent_runner/result_gate.py` 的 `_validate_code_review_report` 逐条 `isinstance(disp, dict)` 校验 dispositions，字符串数组被拒 → 整轮判失败原地重派；agent 在 run 内看不到 daemon 侧报错，r1/r2/r3 照抄坏形状（add-impl-ocr-parallel-lane 实烧两轮）。处方已在项目记忆中验证：「收工前直接调生产校验体自证」，本 SPEC 将其产品化。
- **拒模型**：maomaoai/deepseek-v4.1-flash 返回 `[claude-code:unrecognized_model]` → Exit 1 零 token；近 48h 内 22 个 impl run 秒死，fix-relocation-writeback-layer 一晚 12 个、同因重派每 2-5 分钟一个。现有路径把这类失败当 provider-transient 处理（延迟重派同模型），结构性无解。
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

3. **拒模型 failover 挂在模型链选择/重试判定处**：`unrecognized_model` 错误（provider_marker 后 stderr 出现 `[claude-code:unrecognized_model]` 或等价结构化类别）识别为**确定性失败**而非 transient：当前模型立即标记不可用（记 WARNING 含 provider/model），直接沿链取下一个模型原地继续（不整轮重派、不消耗同因重派计数、不计入 transient 熔断）。链尾仍失败才按既有失败路径收场。备选「派发前主动 probe」被否：每次 run 前多一次 LLM 往返，成本与延迟不划算，且拒模型是 provider 明确返回的类别，事后识别零成本。

4. **模板默认链摘除 maomaoai/deepseek-v4.1-flash**：`.fenix/config.template.yaml`（入库文件）各 agent 链删除该条目。运行时 `.fenix/config.yaml` 的同步修改是人工运维步骤——写入 `docs/help/` 运维文档（含摘除理由与恢复条件），并在 `.fenix/todo.md` 登记提醒；**不进 tasks.md**（主树运行时配置，Agent 在 worktree 内改不到生效副本）。

5. **full-suite 门数据源优先级：框架侧回归产物 > run 内自查 > pending（fail-open）**：读侧合成处（`core/dashboard/data/` 门禁合成）先查框架侧回归车道产物（`core/regression.py` 落盘的回归结果快照，含分支指纹校验，模式对齐 ocr 门的 `(branch, base, head_commit)` 指纹语义）；产物不可见或指纹陈旧时回退读 quality-gates.json 的 run 内自查值（兼容存量与降级路径）；两者皆无 → pending。**状态枚举与键名全集零变化**（`quality-gates-progress` 能力 delta 仅扩展数据源，不破坏既有读侧）。

6. **implementer 收尾自查从「必跑回归」改「降级路径」**：prompt 注入措辞改为「全量回归由验证链执行；仅当确认框架侧回归产物不可用（如验证链被冻结/跳过）时才在 run 内执行并落盘」。frontend-build / interaction-contract 两项自查不变。agent 无法确证框架侧产物是否可用时默认不跑（信任验证链），漏跑由读侧 pending 呈现而非打回——**不得**因 full-suite 项 pending 新增任何打回门。

## Risks / Trade-offs

- **自检被 agent 忽略** → prompt 强注入 + daemon 侧 result_gate 硬门原样保留（双保险，最坏回到现状打回路径，不劣化）。
- **failover 误判**（把其他错误当 unrecognized_model）→ 仅严格匹配该结构化类别；误判后果 = 跳过一个本可用的模型，链上还有 3 个备选，可恢复。
- **回归外包后 impl 失去快速回归反馈** → frontend-build/交互契约自查仍在；回归缺陷走既有 bug-found 环。权衡记录：省 8-10m/轮 × 重试轮数 vs 反馈延迟一个验证阶段，吞吐优先。
- **`agents/implementer.md`、`core/agent_runner/provider_circuit.py` 主树存在未提交 WIP** → merge-back 冲突风险；实现分支基于最新 main 创建可规避大部分；冲突时按混合工作区手术式提交处方处理。
- **框架侧回归产物路径当前未固化契约** → 本 SPEC 的读侧对接以 `core/regression.py` 现状为准（实现期探明），指纹校验缺失时按「不可见」处理（回退 run 内自查值），不阻塞。

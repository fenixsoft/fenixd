# Findings — 维护车道 provider failover 现场取证（task 1.1）

> 取证时间：2026-11-10；数据源：主树 `.fenix/runs/archive/`（run jsonl 逐行解析）与用户级 `/root/.fenix/config.yaml`。取证脚本：`.history/fp_forensics.py`（run 内临时产物，不入库）。

## F1 六条涉事 run 的 provider_marker 全部 `chain_index=0 / chain_len=1`

| run（均在 archive/） | 车道 agent_type | 窗口（UTC） | provider_marker |
| --- | --- | --- | --- |
| `code-review-1794240196` | code-review | 16:03:16 – 16:03:21 | bigmodel.cn / glm-5.3-flash，`chain_index=0, chain_len=1` |
| `code-review-1794240502` | code-review（429 重派 run） | 16:08:22 – 16:08:26 | bigmodel.cn / glm-5.3-flash，`chain_index=0, chain_len=1` |
| `admin-harden-arbiter-lane-resilience-1794231891` | administrator | 13:44:51 – 13:44:55 | bigmodel.cn / glm-5.3-flash，`chain_index=0, chain_len=1` |
| `admin-harden-arbiter-lane-resilience-1794231896` | administrator | 13:44:56 – 13:45:00 | bigmodel.cn / glm-5.3-flash，`chain_index=0, chain_len=1` |
| `arbiter-harden-arbiter-lane-resilience-1794231901` | arbiter | 13:45:01 – 13:45:05 | bigmodel.cn / glm-5.3-flash，`chain_index=0, chain_len=1` |
| `review-2026-11-10` | self-review | 16:03:17 – 16:03:20 | bigmodel.cn / glm-5.3-flash，`chain_index=0, chain_len=1` |

六个 run 每个只写 **1 条** provider_marker：车道取 `assignment[0]` 直连后一次失败即终态，`_write_lane_provider_marker` / 判官范式手动写点把 `0/1` 硬编码（maintenance_runs.py `_write_lane_provider_marker` 传 `0, 1`；runner.py `run_spec_review:1899` / `run_dispute_judge:1674` 同）。

## F2 429 证据所在事件（三处分布，降噪后 error 不可判）

以 `code-review-1794240196` 为例（其余五个 run 形态相同，429 文案均为 `API Error: Request rejected (429) · [1310][您已达到每周/每月使用上限，您的限额将在 2026-11-10 10:43:04 重置。…]`）：

1. **assistant 事件**（`message.model="<synthetic>"`，content text）：429 正文原样在场；
2. **result 事件**：`api_error_status=429`（int）、`is_error=true`、`subtype="success"`，`result` 字段携带同一 429 正文——**结构化归因双源（① 修复的 `_switch_signal_text`）消费的就是这里**；
3. **error 终态事件**：仅 `Exit code: 1`（`_denoise_stderr` 之后 429 文本不在场）——若闸门只读降噪 error 文本，`classify_switch_error` 恒 False。

## F3 与 ① 修复（commit `d08d2fbd0`）的边界

`d08d2fbd0`（「切链闸门复用结构化双源信号」）只改 **dispatch attempt 环**的判定读点：`runner.py` 的 attempt 循环切链闸门（现 `runner.py:3955` `switch_signal = self._switch_signal_text(error, e)`）与 `_record_4xx_or_transient` 的拒模型回退。六条维护车道与两条判官范式车道**不经 attempt 环**——`maintenance_runs.py` 各 run 函数直接调 `runner._run_agent` 单次（ administrator `:433`、arbiter `:817`、self-review `:1193`、evolution `:2119`、code-review `:2755`、code-fix `:4300` 附近），runner.py 判官范式 `run_spec_review:1913` / `run_dispute_judge:1688` 同——① 修复对它们零覆盖，故本 SPEC（②）必要。

## F4 链配置双候选但车道只跑链首（对照证据）

用户级 `/root/.fenix/config.yaml` `agents.models`：`administrator` / `self-review` / `arbiter` / `code-review` / `code-fix` / `spec-review` / `dispute-judge` 等全部角色均配置**双候选链** `[bigmodel.cn/glm-5.3-flash, deepseek/deepseek-flash]`。而 F1 六 run 的 provider_marker 恒 `bigmodel.cn/glm-5.3-flash` 且 `chain_len=1`——deepseek 兜底候选对车道不可见，链配置形同虚设。

## F5 429 重派固定复用链首的直接实证

`code-review-1794240196` 的 `ratelimit_redispatch` 意图行：`cooldown_until_epoch=1794240502.87`（≈首跑 +300s）；重派 run id 即 `code-review-1794240502`（epoch 对齐，冷却到期秒级触发）。重派 run 复跑**再次解析到同一链首** bigmodel.cn（`_consume_code_review_redispatch` → `run_code_review` 重新走 `assignment[0]`），再次 429（F1/F2 同形态），重派额度（`RATELIMIT_REDISPATCH_MAX=1`）就此耗尽——R4「重派按链解析、跳过冷却候选」的直接事故形态。

## F6 结论

事故根因闭环：链配置有兜底（F4）→ 车道只取链首 + marker 恒 0/1（F1）→ 429 证据只在 result/assistant 事件（F2）→ ① 只修 dispatch 环、车道无环可切（F3）→ 重派仍复跑链首（F5）→ 整夜 429。本 SPEC 接入候选环（R1–R6）后，上述每一环均有对应修复点与回归场景（见 specs/ 两份 delta）。

## F7 R6 消费侧零改动结论（tasks.md 4.1 后半，deliverables 声明差异说明）

deliverables 声明 `core/admin_monitor.py kind: modify`，实施后该文件零改动——这是设计结论而非遗漏：R6 后半「复跑前重新解析链并按当时冷却状态跳过候选（不固定复用 `assignment[0]`）」由 Task 3.4 改造自然满足——`_consume_code_review_redispatch` 复调 `run_code_review`，后者经 `_run_lane_agent_with_failover` 每轮重新 `_get_agent_model_assignment` 解析链并进候选环，`_select_chain_candidate` 按当时 switch/限流冷却跳过候选；admin_monitor 的守卫链/Timer 延迟计算/重派上限记账均无需触碰。R6 前半「重派意图携带 chain_len/失败候选」落在 runner `_ratelimit_redispatch_on_terminal` 与 run_code_review 的意图登记传参（additive）。回归证据：tests/test_maintenance_lane_failover.py `TestRatelimitRedispatchChain.test_redispatch_reparse_skips_cooled_first_candidate`（首轮全链 429 → 清第二候选冷却复跑 → 实际使用第二候选，MUST NOT 固定复用链首）与 tests/test_provider_failover.py 既有 TestRatelimitRedispatch 消费侧用例全绿（admin_monitor 守卫链行为不变）。

## F8 验证修复轮（原地打回第 1 轮）：复核结论与修复记录

失败场景 ring-model-rejected-both-tail-attribution 复核结论：**真实产品 Bug（复核成立，非场景缺陷）**——SPEC 场景「拒模型换候选并在链尾归因」（specs/maintenance-lane-provider-failover/spec.md:19-21）明文要求「HTTP 400 拒模型正文（只在 result 事件 result 字段）」失败时框架调用 `_record_unrecognized_model` 记账并换候选；产品实际仅换候选、无记账。根因：`UNRECOGNIZED_MODEL_TEXT_PATTERNS` 仅含 unrecognized_model 两形态，「Model not found: <model>」正文只命中切换类词表第三条——换候选/链尾归因/双候选冷却均正常（5/7 断言过），唯记账 WARNING 缺失。断言与 SPEC 一致，判产品缺陷，修产品代码。

修复（单源共享正则）：`provider_circuit.py` 把切换类词表第三条的收窄正则提升为 `MODEL_NOT_FOUND_TEXT_PATTERN` 常量，`UNRECOGNIZED_MODEL_TEXT_PATTERNS` 扩纳同款——「拒模型 ⊆ 切换类」真子集保持，本地错误形态（model file not found 等）不命中。车道候选环 `_record_unrecognized_model` 记账恢复；dispatch 侧 `_record_4xx_or_transient` 对 result-only「Model not found」形态同时由「误入 4xx 熔断计数」转为拒模型确定性收窄（与该函数既有注释口径对齐，2026-11-09 事故修复同批补的拒模型 result 事件双源回退自此覆盖该正文形态）。测试同步：test_provider_circuit 半开探针夹具改纯配额 404（`model_not_found` 形态自本轮起属拒模型类，不再充当「纯 404」夹具）；test_transient_backoff 增拒模型判定正/反例（网关三形态命中、本地/纯配额形态不命中、真子集保持）；test_maintenance_lane_failover 增网关拒模型正文形态候选环回归（每候选记账 WARNING + 换候选 + marker 真实链下标 + 双候选 switch 冷却 + 链尾 `[model-chain-unavailable]` 归因）。

重跑证据：冻结场景集 27/27 全过（24 探针 + 4 reg 套件），定向 pytest 套件 244 passed；探针重跑结果与摘要见主树 `.fenix/verify-evidence/add-maintenance-lane-provider-failover/scenario_probe_rerun_round2.json`（含 `.summary.md`）。

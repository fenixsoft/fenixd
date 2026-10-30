# 幻影在跑防护（日报 run 终态分类）

<!-- knowledge: capability=phantom-running-guard rev=1 sources=spec/archive/2026-10-30-evo-fix-self-review-phantom-running -->

自省日报对窗口内 run 的读侧终态分类与残余在跑对账：弃置件与非成功终态不混入「在跑」计数，真实卡死在日报中可分辨。

## 规则

- 弃置件单列：产物末行为 `superseded` 终态的 run 计入独立桶位 `superseded`（弃置/重试件——同一逻辑 run 的中间弃置分片，最终结果活在后续 attempt 分片），不计入 running、不计入 succeeded。典型形态为原地重试弃置件（末两行 `transient_retry` + `superseded`）。
- 非成功终结单列：末行为 `interrupted` / `cancelled` / `frozen-terminated` / `gate-blocked` 的 run 计入独立桶位 `ended`（已终结但非成功交付），不计入 running、不入失败样本；detail 保留原 type 词。
- 词表单源：终态识别集合引用 `core.dashboard.data.runs.RUN_TERMINAL_STATUS_MAP` 键集（result/error/interrupted/cancelled/frozen-terminated/superseded/gate-blocked），以模块内延迟导入消费、不复制定义新词表；禁止消费 `core.agent_runner.liveness.RUN_TERMINAL_EVENT_TYPES`（该集合为存活判定、故意排除 superseded 以防退避窗双派发，语义不适用于事后统计，见 [ADR-299](../../adr/ADR-299-terminal-vocabulary-dual-set-no-unification.md)）。
- result/error 分支语义不变：result 型终态的业务失败解析（marker 声明窗口、终态邻近信号、超时/秒挂签名）沿用 [self-review](self-review.md) 与 [self-review-run-semantics](self-review-run-semantics.md) 口径；本能力只决定其余终态词的去向。
- 残余 running 双源对账：末行非任何已知终态（running 判定）的 run 按双源细分——产物 mtime 距统计时刻超过 `RUN_STALE_SECONDS`（1800s，dashboard 读侧同款单源）且 `_run_terminal_success` 未返回 True → 计 `stale`（无终态残留）；查得 terminal=success → 计 succeeded（run 实际收尾、产物断尾，如 daemon 崩溃截断收尾）；mtime 新鲜 → 维持 running 不改判（真实在跑或近瞬状态，宁可不拦不可误伤）。对账仅对 running 判定触发（终态 run 零额外 IO）；mtime 基准为聚合启动冻结的 window_end 快照，pre_classified 直调路径（window_end=None）沿用入口冻结 now_utc 兜底。
- 非 success 指标终态走 stale 通道：`_run_terminal_success` 返回 None（指标索引查无）或 False（查得非 success 终态——run_metrics 的 terminal 值域为 success/failure/frozen/cancelled/circuit）一律同走 stale 通道；非 success 终态不按成功提升为 succeeded、不改计 failed——失败样本归因以产物 marker/信号为源，指标侧无归因 detail，强行改计将造成计数与失败样本口径分叉。数据缺失不改判。
- 计数粒度不变：每个产物分片仍计 1 个 run（维持与历史日报可比）；attempt 分片去重（按逻辑 run 归一计）属另一口径变更，不在本能力内。
- 计数桶同步扩展：counts 初始 dict 含全部桶位键（total/succeeded/failed/instant_hang/timeout/dropped/running/superseded/ended/stale），未知 category 落 counts 抛 KeyError 属禁止形态；失败样本通道仅收 category=failed（新桶天然不入失败样本），`_is_phantom_signal_failure` 幻影失败守卫只对 failed 生效、与新桶无交互。
- 日报第 2 节口径透明：「丢弃/空」与「在跑/无终态」之间渲染「弃置/重试件」「其他终态」「无终态残留」三行；「在跑/无终态」行保留，语义收窄为「末行非任何已知终态且未触发 stale 对账改判」；既有行文案不变，各行计数之和等于总 run 数。

## 溯源

- 2026-10-30 evo-fix-self-review-phantom-running（spec/archive/2026-10-30-evo-fix-self-review-phantom-running） — 新增本页：superseded/ended/stale 三桶分类、词表引 RUN_TERMINAL_STATUS_MAP 单源并禁消费 liveness 集合、残余 running 的 mtime×指标终态双源 stale 对账、日报第 2 节三行渲染（治读侧终态词表缺口——窗口 22 run 中 8 个弃置件被计为在跑、真卡死不可分辨）

# verifier 进程级基础设施死亡分流

<!-- knowledge: capability=verifier-infra-death-triage rev=1
     sources=spec/archive/2026-10-30-evo-add-verifier-infra-death-triage -->

verifier agent 本体的进程级死亡（0 assistant 轮/启动期秒死）与真实验证不通过分流到不同出口：前者走限次廉价重派与超限暂挂，不被裁决消费误判成 bug-found 原地打回烧零产出复核 run。

## 规则

- **进程级死亡不进 bug-found 出口**：verifier run 终局失败且满足进程级死亡特征——终局结果 assistant 轮数为 0，或全部 attempt 存活时长低于秒挂判定阈值（60 秒；存活口径取终局结果 `duration_seconds`，其为 run 级总存活、构成全部 attempt 存活的严格上界；attempt 级侧账仅辅助标注）——MUST NOT 判 bug-found：不触发原地打回、不消耗实现尝试预算。主判据是进程级死亡特征而非错误词表：ENOENT 等启动期错误指纹仅作台账辅助标注，MUST NOT 作为命中条件（形态级词表天然追不上新错误形态）。有 assistant 轮次且存活达秒挂阈值、或场景执行有产物的正常失败路径不变（既有 bug-found/降级路径零变化）。
- **infra 台账限次重派**：分流命中的验证失败复用既有 infra-retry 台账语义（`resolve_infra_retry_decision`）——限次（缺省 2 次）廉价重派，不计 env 冻结轮、不产生 admin 升级；台账清零点与既有验证 PASS + unfreeze_spec 清单同点；MUST NOT 新增平行台账。
- **超限验证暂挂**：重派超限置验证暂挂（freeze_for_human → blocked+frozen+admin 信号，对齐 env 阻塞既有升级形态）而非 bug-found；保留 `reclassify_infra_rounds` 人工回拨兜底。
- **判别素材补齐**：runner 构造的终局失败结果回填真实累计 assistant 轮数（使消费层可区分「全无产出」与「有进度后失败」）；verifier 车道结果对象带结构化 `stderr_tail`/`exit_code`（对齐 spec-review 车道既有回填机制，同机制只扩消费方）。
- **防伪边界**：verified 方向闸门（`_verified_gate_refuses`、verdict 证据校验、`_verifier_result_is_stale`）全部不动；分流出口只有「廉价重派」与「blocked 暂挂」两个方向，结构上不产出假 verified。场景执行期 env 阻塞分类（env_gate/engine 探针车道）、prepare 短路 infra-retry 车道、新流程 planner 死亡 raise → 降级 legacy 的既有语义均不动。

## 溯源

- 2026-10-30 evo-add-verifier-infra-death-triage（spec/archive/2026-10-30-evo-add-verifier-infra-death-triage） — 新增本能力：进程级死亡特征主判据（0 轮或全部 attempt 存活 <60s）在裁决消费前分流、infra 台账限次重派与超限冻结暂挂、终局轮数回填与 stderr_tail/exit_code 推广到 verifier 车道（动因实测：ENOENT 秒死被词表漏判 → bug-found 原地打回烧掉 468 秒/9.8 万 token 零产出复核 run，metrics 时代 0 轮死亡 → bug-found 转化率 2/2）

<!-- knowledge: capability=model-chain-health-probe rev=1 sources=spec/archive/2026-09-27-add-impl-selfcheck-model-probe -->

# 模型链健康探测（拒模型快速 failover）

`unrecognized_model` 是确定性模型失败而非 provider 瞬断：立即沿模型链切换，不做同因重派、不计瞬断计数。

## 规则

- provider 返回 `unrecognized_model` 类错误（stderr 出现 `[claude-code:unrecognized_model]` 或等价结构化类别）时，归类为确定性模型失败而非 provider-transient：先记 WARNING 告警（含 provider、model、run_id）。
- 告警后沿该 agent 类型配置的模型链原地切换到下一个可用模型继续当前 run：不终止 run、不以同因重派方式重新派发整个 run、不递增 transient 熔断/同因重派计数。
- 链尾模型同样拒模型时按既有失败路径收场：失败归因含「全链模型不可用」语义，后续走既有失败治理，不进入同因重派循环。
- 其余 provider 错误（5xx、超时、黑洞等）处理路径保持既有瞬断语义不变（见 [provider-transient-backoff](provider-transient-backoff.md)）。
- 链卫生：入库模板 `.fenix/config.template.yaml` 不得含实测拒模型条目（provider `maomaoai` + model `deepseek-v4.1-flash`），并在 models 注释示例处保留拒模型警示注释；活动链仅存在于运行时 `.fenix/config.yaml`。
- 运行时链摘除拒模型条目为人工运维步骤（摘除后各 agent 链剩余条目数 ≥3，链尾 failover 语义不受影响）：摘除理由、恢复条件与修改步骤记录于运维文档 `docs/help/13-model-chain-ops.md`，含「在 `.fenix/todo.md` 登记提醒」的人工指示；实现车道无主树写授权，不得直接改主树运行时配置或 todo.md。

## 溯源

- 2026-09-27 add-impl-selfcheck-model-probe — 将 unrecognized_model 从瞬断类改归确定性模型失败并建立链上立即 failover 契约，固化模板拒模型警示与运行时链人工摘除的运维文档处方

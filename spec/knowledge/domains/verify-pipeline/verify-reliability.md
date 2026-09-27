# 验证可靠性
<!-- knowledge: capability=verify-reliability rev=2 sources=spec/archive/2026-09-19-evo-judge-rerun-stability,spec/archive/2026-09-19-evo-verifier-result-single-source -->

验证裁决的稳定性与结果读取纪律：verdict 稳定即复用、verified 一次性放行、裁决读取单一来源带 role 隔离。

## 现行规则

- judge 重跑治理：对同一 spec 的 planner-judge 重跑次数按 verdict 序列计数；连续两轮 judge verdict 完全一致（含 status 与失败场景清单）即判定 verdict 已稳定，后续验证轮直接复用最近一次结果，不新起 judge run；单 spec 窗口内 judge run 总数设硬上限，超出后进入人工裁决通道。
- verified 一次性放行：`verify-progress/<spec>/.fenix-run-result.json` 落盘 status=verified 后，pm_engine 的 legacy 与新验证两条路径均不得再将该 spec 判定为 blocked/bug-found/unknown-status；唯一例外是场景集或实现 commit 变化（spec 戳变化）失效后重新验证。
- 裁决读取单一来源：verifier 裁决一律读 `verify-progress/<spec>/.fenix-run-result.json`；主树 `.fenix/.fenix-run-result.json` 仅作兼容回退，且回退须通过 role=verifier + spec 戳匹配 + mtime 新鲜度校验，任一不通过视为失效、不得作为裁决依据；role 校验不依赖 run_id 可解析（run_id 不匹配 `-\d{10,}-a\d+$` 时判陈旧，不留 fail-open）。
- 写入语义隔离：主树共享结果文件的唯一写入点是 runner 成功路径拷回（`_execute_agent`），写入时按 agent_type 强制带 role 字段（implementer | verifier | planner | judge | repair）与 spec 戳，role 缺失视为旧格式遗留；implementer 结果由 engine 写 `verify-progress/<spec>/impl-result.json`，主树共享文件不再承载 implementer 语义。
- 隔离的作用域：读侧对 role≠verifier 的主树共享文件的丢弃仅限裁决读路径，不影响 implementer / planner 主树回退与 fast-track 上轮结论读取的既有采信。
- 可观测：STATE.md 记录 judge_rerun_count；run 收尾时记录本次是否复用缓存 verdict。

## 溯源

- 2026-09-19 evo-judge-rerun-stability — 新增 judge verdict 稳定复用与 verified 一次性放行（验证已通过后 judge/verify/legacy 多路径互踩空转，单 spec 实测 11 次 judge + 4 次 admin 处置、+$24.6）
- 2026-09-19 evo-verifier-result-single-source — 裁决读取收敛单一来源并引入 role 字段写入隔离（implementer 残留 status=success 污染主树共享文件曾被误当裁决判 blocked，同根因两度复发）

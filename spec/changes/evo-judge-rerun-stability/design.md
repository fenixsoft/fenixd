# 设计 — judge-rerun-stability

## 裁决缓存
- 在 verify-progress/<spec>/verdict_stability.json 持久化最近两轮 verdict（status + 失败场景 id 集 + spec 戳 + report.json mtime）。
- **必须使用独立文件名 verdict_stability.json**：`verdict_cache.json` 已被场景级指纹缓存占用（core/verdict_check.py 的
  `save_verdict_cache`/`load_verdict_cache`，schema 为 `{scenario_id: {fingerprint, classification, evidence, assertion_triage}}`，
  由 prompt_builder._verdict_cache_section 在 judge 派发前读取注入）。若写入同一路径，_persist_verdict_cache
  （verification.py 每轮整体重写）会覆盖稳定性缓存，且 prompt_builder 读到 status/failed_ids 格式会破坏场景指纹匹配。
- 复用判据：spec 戳未变 && report.json mtime 未变 && 两轮 verdict 一致 → 直接复用，不重派 judge。
- spec 戳定义：`spec/changes/<spec>/spec.md` 与 `specs/scenarios.json` 的内容哈希（sha256 前 16 位，同 scenario_fingerprint 风格）。
  场景集变更（_apply_scenario_freeze 重写）或 spec.md 修改即改变 spec 戳 → 缓存失效重新验证。

## verified 放行
- 在 pm_engine 裁决应用处（verification.py 的 _apply_* 与 _run_legacy_verification 公共出口）加一道「verified 门」：读 .fenix-run-result.json 若 status=verified 且 spec 戳匹配当前 spec、无场景集变更，任何路径不得覆盖为 blocked。
- 与既有 fail-closed（D4/D5）对称：fail-closed 管「不可读不得晋级」，本设计管「已 verified 不得降级」。

## 计数
- judge_rerun_count 写入 STATE.md 增量时间线，run 收尾时增量。
- 与既有 _verify_fail_rounds（MAX_VERIFY_FAIL_ROUNDS=3，冻结 blocked）正交：
  judge_rerun_count 计 judge 派发次数（含被缓存复用跳过但未实际派发的判定次数），
  _verify_fail_rounds 计验证失败轮次（bug-found 应用后递增）。两者可共存，
  但 hard cap 触发转人工时须同时冻结两计数器。

## 改动点
- core/pm_engine/verification.py：verified 放行门 + verdict 稳定性缓存复用判断。
  verified 门与既有 D6 stale-result 防护共存：D6 在 _apply_status != "testing"
  时丢弃结果（对已 verified/done 的 spec 天然有效）；verified 门额外防护
  "人工 reset 回 testing 后 legacy 误判 blocked" 的边缘场景，两层不冲突。
- core/pm_engine/verification.py（而非 family.py）：judge 重跑计数与硬上限。
  judge 派发位于 verification.py:2239（run_planner(spec_name, "judge")），
  计数与上限拦截应就近放置，family.py 负责 fix 家族治理，不承担 judge 生命周期。
- core/verify_report.py：verdict_stability.json 读写（含 spec 戳计算）。
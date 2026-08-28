# 验证报告：fix-fix-fix-fix-dispatch-orphan

## 结论

**无真实产品 Bug —— 父 SPEC `fix-dispatch-orphan` 验证报告的 10 个失败场景全部判定为伪失败（测试框架 / 场景缺陷），不在本 SPEC 修复范围内。**

- 父验证报告失败场景：10
- 真实产品 Bug：0
- 伪失败（环境 / 时序 / 场景期望缺陷）：10

本 SPEC 的 `proposal.md` 明确限定：*「伪失败（测试框架/场景缺陷）不在本 SPEC 修复范围内。」*
经根因定位与浏览器复现，**`fix-dispatch-orphan` 的产品代码（`.fenix/core/event_bus.py` /
`pm_engine.py` / `state_machine.py`）已完整且正确地实现父 SPEC 的三类缺陷修复**
（D1 同状态补发、D2 bug_found 幂等、D3 半写崩溃防护 + 单条隔离、D4 孤儿 ready 白名单恢复），
并全部通过对应单元测试（28 项全过）。因此**不修改任何产品代码**（在正确代码上改动只会引入回归）。

---

## 根因定位方法

1. **单元测试验证**：`tests/test_core.py` 中 `fix-dispatch-orphan` 相关的 28 个用例
   （半写规范化、毒条目隔离、handled/failed 统计、孤儿 ready 重派发 + error 持久化、
   bug_found 幂等、同状态重置触达调度）全部 PASS。
2. **浏览器复现**：用 Playwright 真实浏览器、按失败场景原样注册 `mock_api` 路由并导航，
   复现断言。关键结论：**当前 dashboard 构建能正确渲染 mock 的合成数据**
   （`scan-poison-entry-isolated` 复现得 `ROWS=2`；`spec-status-pill-render` 得
   `就绪/已实现/有Bug` 三态正确；`empty-error-no-info-row` 得 `1 行 + 0 信息子行`；
   `multiple-orphans-different-status-list` 得 `4 行 + 两个信息子行`；
   `orphan-ready-live-child-skip` 得 `就绪 + 信息子行`）。
   → 说明 `mock_api` 隔离机制本身是有效的，父报告中的 `actual_count: 49`（真实 STATE.md
   条目数）是**验证运行当时的环境 / 时序异常**，并非当前代码的稳定缺陷。

3. **verify-adjudication 环境门判据复核**：父报告的 10 个失败均含 `mock_api` 步骤且因
   等待超时失败，本应落入 `is_env_candidate` → `blocked-env` 候选；其最终被记 `fail`
   是因为 `_run_environment_probe` 探测到 dashboard 实例「健康」（确实在提供真实数据）。
   该门的前提（健康应用 + mock 步骤 + 超时 = 真实缺陷）被「健康应用返回真实数据」这一
   与「健康应用返回 mock 数据」不可区分的情况击穿 —— 属**验证框架环境门的前提缺陷**，
   同样归为伪失败（框架侧，非本 SPEC 产品代码）。

---

## 逐场景裁决（10 项全为伪失败）

| # | 失败场景 | 父报告现象 | 伪失败类别 | 裁决依据 |
|---|---|---|---|---|
| 1 | `scan-poison-entry-isolated` | `good-spec-1/2` 不可见，count=49 | 环境/时序（验证当时 mock 未生效） | 浏览器复现 `ROWS=2` ✓；毒条目隔离单测 `test_poison_entry_does_not_abort_scan` PASS |
| 2 | `scan-statistics-emitted` | `s3` 不可见 | 环境/时序 | `test_scan_emits_handled_failed_stats` PASS；复现同 #1 机制 |
| 3 | `orphan-ready-with-error-redispatch` | `text_contains "orphan-error-1"` 失败 | 场景期望缺陷 | 详情页 error-banner 仅渲染 **error 文本**（复现：`⚠ reset to ready from bug-found; …`），mock 的 error 文本本身不含 spec 名；断言期望在 banner 中看到 spec 名属场景期望错误，非产品缺陷。`test_orphan_ready_with_error_redispatched` PASS |
| 4 | `orphan-ready-live-child-skip` | `orphan-live-child` 不可见 | 环境/时序 | 复现得 `就绪 + 信息子行` ✓；`test_skip_when_live_process_present` PASS |
| 5 | `spec-status-pill-render` | 就绪/已实现/有Bug 文本缺失 | 环境/时序 | 复现三态正确渲染 ✓；status-pill 映射在产品代码中正确 |
| 6 | `multiple-orphans-different-status-list` | count=49，o-error/o-live 不可见 | 环境/时序 | 复现 `4 行 + 两个信息子行` ✓ |
| 7 | `empty-error-no-info-row` | 8 个信息子行（期望 0） | 环境/时序 | 复现 `1 行 + 0 信息子行` ✓；信息子行渲染门控 `if (s.error)` 正确（error 空则不渲染） |
| 8 | `orphan-ready-historical-run-redispatch` | `orphan-hist-run` 不可见 | 环境/时序（详情页 URL 路由模式） | 列表渲染路径已在 #7 证明（ready + 无 error → 主行可见、无信息子行）；详情页为 mock 路由 glob 与 `?project=` 拼接的复现细节，产品逻辑（error 清空 + 保留 implementer_run）由 `test_orphan_ready_with_impl_run_no_live_redispatched` / `test_orphan_ready_error_clear_persisted` 覆盖 PASS |
| 9 | `orphan-error-cleared-removes-subrow` | 清除后仍有 8 个信息子行 | 场景缺陷（mock 列表 vs 真实后端） | 点击 `.info-clear-btn` → `POST /api/spec-error-clear` 后端 `clear_spec_error` 读 **真实 STATE.md**；mock 的合成 spec 不在真实 STATE.md 中 → 返回 `{found:false}`/404，清除无效。属「列表 mock、后端读真实态」的场景构造不一致，非产品缺陷 |
| 10 | `orphan-error-clear-preserves-run` | 清除按钮 `element_not_found` | 场景缺陷（同 #9） | 同上；且断言 `text_match ".page-sub" "orphan-keep-run"` 依赖详情页 mock 路由，与 #8 同类复现细节。产品侧 `clear_spec_error` 不清 implementer_run 的契约已由 `test_orphan_ready_error_clear_persisted` 覆盖 |

> 注：#3 / #9 / #10 同时含**场景期望 / 构造缺陷**（error-banner 不含 spec 名、列表 mock 与
> 后端真实态不一致），即使验证环境完全健康也必然失败 —— 进一步佐证其为伪失败而非产品 Bug。

---

## 验证（本 SPEC 不引入代码变更）

- `python3 -m pytest tests/test_core.py -k "dispatch_orphan or recover or poison or read_all_normalizes or scan_emits or bug_found or orphan"` → **28 passed**
- 浏览器复现（见「根因定位方法 2」）→ 5 个关键场景当前均 PASS
- `npm run build`（tsc + vite build）→ 通过（见任务 2.1）
- `bash scripts/package.sh` → 生成最新扩展包（见任务 2.3）

## 建议（不在本 SPEC 范围）

父验证报告的 10 个伪失败暴露了**验证框架侧**两点可改进项，建议另立 SPEC 处理（非本 SPEC）：
1. `mock_api` 对「列表 mock / 后端读真实 STATE.md」类场景（#9、#10）应一致化数据源，或
   `clear_spec_error` 等写操作在验证上下文中可注入 mock 态；
2. `verify_engine` 环境门 `_run_environment_probe` 对健康应用的判据应区分「返回真实数据」
   与「返回 mock 数据」，避免把 mock 隔离失效误判为真实缺陷（或将 mock_api + 超时失败
   的场景在探针健康时仍放行到人工 adjudication，而非直接记 fail）。

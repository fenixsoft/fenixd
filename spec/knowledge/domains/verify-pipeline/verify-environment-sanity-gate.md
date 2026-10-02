# 验证环境健全性门

<!-- knowledge: capability=verify-environment-sanity-gate rev=3
     sources=spec/archive/2026-09-02-improve-scheduling-noise-governance,spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake -->

mock 环境下等待类断言失败的健全性探针与 blocked-env 换算：环境性失联不计为产品失败，「失败全部为环境性」的轮次按两级判据整体判 inconclusive 重验。

## 规则

- 健全性探针：场景步骤序列含 `mock_api` 类步骤、且失败断言属纯 DOM/SSE 等待超时（Locator.wait_for Timeout 等无业务信息错误）时，verify_engine 在判 fail 前对被测 dashboard 实例执行环境健全性探针（连通 + 推流检查）。
- 降级与维持：探针证实实例失联/推流中断 → 该场景记 `blocked-env` 计入 warning 统计而非 fail（`report.summary.blocked_env` 加一，failed 计数不含它）；探针确认实例在线且推流正常 → 维持 fail 判定不变。
- 报告与门禁换算：`report.summary.blocked_env` 字段与「有效失败 = failed - blocked_env」口径不变；inconclusive 判定按两级判据：
  - 级一（judge 前原始 summary 口径）：全部原始失败均为 blocked-env 时整体判 `inconclusive`，命中即短路，judge 不再重复判定。
  - 级二（judge 裁决采纳尾段）：全部失败断言（含混合形态中原始 failed>0 的部分）按断言级 `assertion_triage` 归类（场景缺该字段时回退场景级 `classification`）均为 env——不存在 product-bug / test-defect 条目，blocked_env 形态场景天然视为环境性。级二先于既有场景级 env 洗白门禁判定（后者行为不变），命中处理与级一同源：回 implemented 排队重验新 attempt，不判 bug-found、不产生 repeated_failures。
  - flaky 归类维持既有豁免放行，不纳入级二；既有重验上限与 B7 升级阈值对两级统一适用。级二命中后的补救与 admin 确认链路见 [verdict-env-exemption-handshake](../verdict-adjudication/verdict-env-exemption-handshake.md)。
- 重验不烧信号预算：inconclusive 重派不计入 repeated_failures 困境信号的失败次数（连续多轮 inconclusive 不唤醒 Administrator）；重验轮次中探针转为健康后同场景再次失败，按真实 bug-found 流程流转。

## 溯源

- 史前复原（存量基线） — 验证环境不健全归类 blocked-env 并按 inconclusive 重派，不计为产品失败、不流转 bug-found
- 2026-09-02 2026-09-02-improve-scheduling-noise-governance（spec/archive/2026-09-02-improve-scheduling-noise-governance） — 新增 mock 环境健全性探针、`blocked_env` 统计字段与 inconclusive 重验换算（mock_api 斩断 SSE 曾造成整批假阴性，每轮假阴性派生 fix 子 SPEC 空转完整实现+验证周期）。
- 2026-10-03 2026-10-03-fix-verdict-env-exemption-admin-handshake（spec/archive/2026-10-03-fix-verdict-env-exemption-admin-handshake） — inconclusive 判据由「全批 blocked-env」单级扩展为两级：级一维持 judge 前原始口径不变，级二在裁决采纳尾段按断言级归类判「失败全部环境性」（覆盖 19 passed + 2 failed + 1 blocked_env 类混合形态），两级共享重验上限与升级阈值。

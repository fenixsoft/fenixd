# 验证环境健全性门
<!-- knowledge: capability=verify-environment-sanity-gate rev=1 sources=spec/archive/2026-09-02-improve-scheduling-noise-governance -->

mock 环境下等待类断言失败的健全性探针与 blocked-env 换算：环境性失联不计为产品失败，整批失联按 inconclusive 重派。

## 现行规则

- 健全性探针：场景步骤序列含 `mock_api` 类步骤、且失败断言属纯 DOM/SSE 等待超时（Locator.wait_for Timeout 等无业务信息错误）时，verify_engine 在判 fail 前对被测 dashboard 实例执行环境健全性探针（连通 + 推流检查）。
- 降级与维持：探针证实实例失联/推流中断 → 该场景记 `blocked-env` 计入 warning 统计而非 fail（`report.summary.blocked_env` 加一，failed 计数不含它）；探针确认实例在线且推流正常 → 维持 fail 判定不变。
- 报告与门禁换算：验证放行门禁与 done 判定使用「有效失败 = failed - blocked_env」；全部原始失败均为 blocked-env 时整体结果判 `inconclusive`，处理为保持 testing 并重新派发新 attempt，不产生 bug-found。
- 重验不烧信号预算：inconclusive 重派不计入 repeated_failures 困境信号的失败次数（连续多轮 inconclusive 不唤醒 Administrator）；重验轮次中探针转为健康后同场景再次失败，按真实 bug-found 流程流转。

## 溯源

- 史前复原（存量基线） — 验证环境不健全归类 blocked-env 并按 inconclusive 重派，不计为产品失败、不流转 bug-found
- [2026-09-02 improve-scheduling-noise-governance](spec/archive/2026-09-02-improve-scheduling-noise-governance/) — 新增 mock 环境健全性探针、`blocked_env` 统计字段与 inconclusive 重验换算（mock_api 斩断 SSE 曾造成整批假阴性，每轮假阴性派生 fix 子 SPEC 空转完整实现+验证周期）

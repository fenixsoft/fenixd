# 机械快道裁决来源戳

<!-- knowledge: capability=verify-result-stamp-contract rev=1
     sources=spec/archive/2026-10-02-fix-verify-late-result-terminal-clobber -->

机械三阶段验证快道写出的裁决产物必须带 role 来源戳，使其通过读侧结果归属校验——快道产物与 LLM verifier 产物在读侧同为合法验证车道产物，`mechanical: true` 另行标识机械来源。

## 规则

- 快道裁决 payload 契约：`_all_green_fast_path` 写 `.fenix/verify-progress/<spec>/.fenix-run-result.json` 的 payload 必须含 `"role": "verifier"`，并保留既有 `mechanical: true`、`spec`、`status`、`bugs`、`summary` 字段；快道写回失败退化为常规 judge 的既有语义不变。
- role 门放行依据：读侧 `_verifier_result_is_stale` 对 role 缺失一律判「不采信」；带戳后快道产物是合法的验证车道产物，`mechanical: true` 保留机械来源的可辨识性。
- 其余判据不变：跨 spec 防护不变——`spec` 戳与当前 SPEC 不符仍拒，即使带 `role=verifier`；mtime 判据不变——文件早于在飞 run 启动时刻 5 秒以上仍判「本轮验证器未曾写回」。
- 只读消费方兼容：`verify_report.py` 等只读消费方对多余键天然兼容，无需改动。
- 同轮快道先出的采信窗口：同 SPEC 同轮机械快道先写裁决、在飞 LLM verifier 后完成时，其 stale 校验放行并采信快道裁决——同 spec 同轮、均为验证车道产物，可接受；且 LLM verifier 完成时先写自己的结果文件覆盖之，窗口极窄。

## 溯源

- 2026-10-02 fix-verify-late-result-terminal-clobber（spec/archive/2026-10-02-fix-verify-late-result-terminal-clobber） — 快道裁决 payload 补 `role: "verifier"` 来源戳（此前缺戳使同 SPEC 在飞 LLM verifier 完成时该文件必然被读侧判 foreign-role，为迟到结果覆写终态事故的误判土壤）

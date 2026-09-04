# Tasks: add-verify-report-gate

实现依据（实施 agent 必读）：
- 能力定义 `specs/verify-report-gate/spec.md`；设计决策 design.md D1-D3
- 现行裁决 prompt：`.fenix/core/agent_runner.py` 裁决 prompt（Step 4/5 写结果与报告）
- 报告格式解析方：`.fenix/core/dashboard/data.py` `parse_verdict`（约 770 行起）——合成输出 MUST 兼容
- 注意：本 SPEC 不触碰 `_ensure_fix_spec_files`（fix 派生入口校验已撤销，该路径将由 add-inplace-bug-repair 退役）

## 1. 共享合成器

- [x] 1.1 在 `.fenix/core/` 新增合成 helper（单一实现）：输入 spec 名，读取 `.fenix/verify-progress/<spec>/report.json` 与 `.fenix-run-result.json`，渲染并写入 `openspec/changes/<spec>/verification-report.md`；结构化数据缺失/不可解析时返回失败而非写空报告
- [x] 1.2 合成输出兼容 `parse_verdict`：含 `## 结论：`标题行（内联 ❌/✅ 状态）、`**状态:**` 详情行、`| 通过 | N |` 形式的汇总表格、以及「真实产品 Bug」章节（bug-found 时含 description/root_cause/evidence）

## 2. 裁决放行入口接入闸门

- [x] 2.1 验证裁决采纳处（status=verified/bug-found 即将推进）：校验报告文件存在；缺失→调用合成器并产生 human-escalation-alerts 告警（措辞含「裁决 Agent 未写报告，已由框架合成」）；合成失败→阻断推进、error 记因、发人工升级告警；文件已存在→不动（不覆盖、不改 mtime）

## 3. 单元测试

- [x] 3.1 覆盖三种路径：缺报告+数据完整→合成且告警；报告在→内容与 mtime 不变；数据不可用→阻断+告警
- [x] 3.2 合成报告能被 `parse_verdict` 正确解析出 status/conclusion/summary（用 v2-shell-hash-router 事故的真实 report.json 作为测试夹具）

## 4. 验证与打包

- [x] 4.1 运行 `python3 -m pytest .fenix/tests/ -v` 确认无回归
- [x] 4.2 执行 `bash scripts/package.sh` 生成最新扩展包

# 验证管线
> 最后更新：2026-10-06 06:35 UTC+8

验证管线。本域能力条目清单如下（能力页由存量回填批次逐步产出，落盘后此处升级为链接）。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [verify-runner-engine](verify-runner-engine.md) | 验证执行引擎（runner） | 2026-10-03 04:59 |
| [verification-pipeline-modules](verification-pipeline-modules.md) | 验证管线模块化结构 | 2026-10-03 04:59 |
| [verify-process-lifecycle](verify-process-lifecycle.md) | 验证进程生命周期管理 | 2026-10-03 04:59 |
| [verify-preflight-gate](verify-preflight-gate.md) | 验证预检门 | 2026-10-03 04:59 |
| [verify-environment-sanity-gate](verify-environment-sanity-gate.md) | 验证环境健康门（探针、blocked-env 换算与两级 inconclusive 判据） | 2026-10-03 05:45 |
| [verify-lane-slot-exemption](verify-lane-slot-exemption.md) | 验证车道槽位豁免 | 2026-10-03 04:59 |
| [verify-unreachable-failfast](verify-unreachable-failfast.md) | 被测服务不可达快速失败 | 2026-10-03 04:59 |
| [verify-deps-provision-default](verify-deps-provision-default.md) | 验证依赖供给缺省 | 2026-10-03 04:59 |
| [main-tree-deps-provision](main-tree-deps-provision.md) | 主树依赖供给 | 2026-10-03 04:59 |
| [worktree-test-server](worktree-test-server.md) | worktree 被测服务供给 | 2026-10-03 04:59 |
| [serve-scope-matrix](serve-scope-matrix.md) | 被测实例 serve 范围矩阵 | 2026-10-03 04:59 |
| [serving-dist-freshness-probe](serving-dist-freshness-probe.md) | verify run 前 dist 新鲜度探针与自动重建 | 2026-10-03 05:45 |
| [verify-serving-reclaim](verify-serving-reclaim.md) | 验证服务磁盘回收 | 2026-10-03 04:59 |
| [verify-contract-autodraft](verify-contract-autodraft.md) | 验证契约（verify.yaml）自主起草 | 2026-10-03 04:59 |
| [verify-contract-autodraft-ui](verify-contract-autodraft-ui.md) | 契约 AI 生成按钮 | 2026-10-03 04:59 |
| [verify-contract-signal-dispatch](verify-contract-signal-dispatch.md) | 验证契约信号派发 | 2026-10-03 04:59 |
| [autodraft-dispatch-dedup](autodraft-dispatch-dedup.md) | 契约自主起草派发去重 | 2026-10-03 04:59 |
| [verify-scenario-freeze](verify-scenario-freeze.md) | 验证场景冻结 | 2026-10-03 04:59 |
| [verification-scenario-freeze](verification-scenario-freeze.md) | 场景冻结契约版本化 | 2026-10-03 04:59 |
| [frozen-scenario-schema-migration](frozen-scenario-schema-migration.md) | 冻结场景结构迁移 | 2026-10-03 04:59 |
| [scenario-schema-single-source](scenario-schema-single-source.md) | 场景结构单源 | 2026-10-03 04:59 |
| [scenario-write-schema-gate](scenario-write-schema-gate.md) | 场景写入结构门 | 2026-10-03 04:59 |
| [scenario-static-defect-scan](scenario-static-defect-scan.md) | 场景静态缺陷扫描 | 2026-10-03 04:59 |
| [scenario-defect-reroute-gate](scenario-defect-reroute-gate.md) | 场景缺陷改道门 | 2026-10-03 04:59 |
| [scenario-defect-reroute-stoploss](scenario-defect-reroute-stoploss.md) | 场景缺陷改道止损 | 2026-10-03 04:59 |
| [scenario-replan-consumption-gate](scenario-replan-consumption-gate.md) | 重规划场景消费门 | 2026-10-03 04:59 |
| [multi-kind-scenario-model](multi-kind-scenario-model.md) | 多类型验证场景模型 | 2026-10-03 04:59 |
| [multi-kind-planning-guidance](multi-kind-planning-guidance.md) | 多类型场景规划指引 | 2026-10-03 04:59 |
| [multi-kind-report-compat](multi-kind-report-compat.md) | 多类型验证报告兼容 | 2026-10-03 04:59 |
| [parallel-scenario-planning](parallel-scenario-planning.md) | 并行场景规划 | 2026-10-03 04:59 |
| [interaction-contract](interaction-contract.md) | 交互契约与逐断言分诊 | 2026-10-03 04:59 |
| [visual-baseline-integrity](visual-baseline-integrity.md) | 视觉校验基线完整性 | 2026-10-03 04:59 |
| [visual-capture-robustness](visual-capture-robustness.md) | 视觉采集稳健性 | 2026-10-03 04:59 |
| [inconclusive-parallel-backoff](inconclusive-parallel-backoff.md) | 无结论重验并行降档 | 2026-10-03 04:59 |
| [blocked-reverify-gate](blocked-reverify-gate.md) | BLOCKED 重验直通道 | 2026-10-03 04:59 |
| [verification-completion-gate](verification-completion-gate.md) | 验证完成门 | 2026-10-03 04:59 |
| [verify-report-gate](verify-report-gate.md) | 验证报告门 | 2026-10-03 04:59 |
| [verify-report-scenarios-sourcing](verify-report-scenarios-sourcing.md) | 验证报告场景明细读取源 | 2026-10-03 04:59 |
| [verification-report](verification-report.md) | 验证报告落盘即入库（写盘成功即单文件提交入库，含场景段渲染写回后即时入库） | 2026-10-06 06:35 |
| [push-closeout-report-commit](push-closeout-report-commit.md) | push 收口报告入库（done→pushed 收口单文件入库、失败降级不阻断） | 2026-10-06 06:29 |
| [verify-progress-copyback](verify-progress-copyback.md) | 验证进度回传 | 2026-10-03 04:59 |
| [verify-progress-sourcing](verify-progress-sourcing.md) | 验证进度读取源 | 2026-10-03 04:59 |
| [verify-reliability](verify-reliability.md) | 验证可靠性（judge 重跑上限与结果单源读取） | 2026-10-03 04:59 |
| [chrome-extension-verification](chrome-extension-verification.md) | 扩展项目验证（启动器与 chrome-extension:// 目标回退） | 2026-09-27 17:23 |
| [scenario-mock-and-seed-actions](scenario-mock-and-seed-actions.md) | 场景 seed 预置与 mock_api 离线拦截 | 2026-09-27 17:23 |
| [external-api-network-exemption](external-api-network-exemption.md) | 外部 API 网络错误豁免（external_net_errors_ok） | 2026-09-27 17:23 |
| [verify-late-result-terminal-guard](verify-late-result-terminal-guard.md) | 迟到验证结果终态丢弃守卫（非 testing 一律零副作用丢弃） | 2026-10-03 04:59 |
| [verify-inflight-lane-reclaim](verify-inflight-lane-reclaim.md) | verified 终态在飞验证车道回收（摘队列 + 按完整 run id 取消） | 2026-10-03 04:59 |
| [verify-result-stamp-contract](verify-result-stamp-contract.md) | 机械快道裁决产物的 role 来源戳契约 | 2026-10-03 04:59 |

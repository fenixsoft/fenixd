# 验证管线

验证管线。本域能力条目清单如下（能力页由存量回填批次逐步产出，落盘后此处升级为链接）。

## 能力页

- `verify-runner-engine` — 验证执行引擎（runner）
- `verification-pipeline-modules` — 验证管线模块化结构
- `verify-process-lifecycle` — 验证进程生命周期管理
- `verify-preflight-gate` — 验证预检门
- `verify-environment-sanity-gate` — 验证环境健康门
- `verify-lane-slot-exemption` — 验证车道槽位豁免
- `verify-unreachable-failfast` — 被测服务不可达快速失败
- `verify-deps-provision-default` — 验证依赖供给缺省
- `main-tree-deps-provision` — 主树依赖供给
- `worktree-test-server` — worktree 被测服务供给
- `serve-scope-matrix` — 被测实例 serve 范围矩阵
- `verify-serving-reclaim` — 验证服务磁盘回收
- `verify-contract-autodraft` — 验证契约（verify.yaml）自主起草
- `verify-contract-autodraft-ui` — 契约 AI 生成按钮
- `verify-contract-signal-dispatch` — 验证契约信号派发
- `autodraft-dispatch-dedup` — 契约自主起草派发去重
- `verify-scenario-freeze` — 验证场景冻结
- `verification-scenario-freeze` — 场景冻结契约版本化
- `frozen-scenario-schema-migration` — 冻结场景结构迁移
- `scenario-schema-single-source` — 场景结构单源
- `scenario-write-schema-gate` — 场景写入结构门
- `scenario-static-defect-scan` — 场景静态缺陷扫描
- `scenario-defect-reroute-gate` — 场景缺陷改道门
- `scenario-defect-reroute-stoploss` — 场景缺陷改道止损
- `scenario-replan-consumption-gate` — 重规划场景消费门
- `multi-kind-scenario-model` — 多类型验证场景模型
- `multi-kind-planning-guidance` — 多类型场景规划指引
- `multi-kind-report-compat` — 多类型验证报告兼容
- `parallel-scenario-planning` — 并行场景规划
- `interaction-contract` — 交互契约与逐断言分诊
- `visual-baseline-integrity` — 视觉校验基线完整性
- `visual-capture-robustness` — 视觉采集稳健性
- `inconclusive-parallel-backoff` — 无结论重验并行降档
- `blocked-reverify-gate` — BLOCKED 重验直通道
- `verification-completion-gate` — 验证完成门
- `verify-report-gate` — 验证报告门
- `verify-report-scenarios-sourcing` — 验证报告场景明细读取源
- `verify-progress-copyback` — 验证进度回传
- `verify-progress-sourcing` — 验证进度读取源
- `verify-reliability` — 验证可靠性（judge 重跑上限与结果单源读取）

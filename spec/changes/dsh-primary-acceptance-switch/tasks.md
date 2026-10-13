## Deliverables

```yaml
- path: bin/dsh_acceptance.py
  kind: new
- path: docs/help/dsh-harness-runbook.md
  kind: new
- path: tests/test_dsh_acceptance.py
  kind: new
- path: .fenix/todo.md
  kind: modify
```

## 1. 验收夹具与脚本

- [ ] 1.1 bin/dsh_acceptance.py 三模式：fixture（临时玩具项目+唯一前缀+最小 SPEC 种子）、smoke（假端点全链冒烟，≥3 车道：implementer/verifier/监督 judge）、accept（真实模式，执行前自检凭据/健康检查并输出 dry-run 计划）
- [ ] 1.2 证据收集：run jsonl、SPEC-3 投影可观测性计数（含坏事件分类）、`.fenix-run-result.json` 硬门结果、run_metrics 耗时指标；与同夹具 claude 通道基线比对；失败 fail-loud 不产假绿报告
- [ ] 1.3 夹具清理：脚本 finally 清理玩具项目与 runs 产物（唯一前缀识别），runbook 记录手工清理兜底命令

## 2. 多车道假端点回归

- [ ] 2.1 SPEC-3 单车道冒烟扩展为 ≥3 车道假端点全链（经 run_one_shot 的 judge 通道含在内），各车道终态/在飞判定/产物硬门全链正确
- [ ] 2.2 tests/test_dsh_acceptance.py：三模式行为、证据收集与判定逻辑、夹具清理无残留、fail-loud 路径

## 3. 运行手册与报告模板

- [ ] 3.1 docs/help/dsh-harness-runbook.md：切换步骤（Bundle 安装→agent.harness: dsh→健康检查确认）、回切步骤（含在飞 run 排水语义处置）、故障处置（版本漂移/429 同刻叠峰/投影异常/健康检查失败）、真实验收执行指引
- [ ] 3.2 验收报告模板（runbook 内嵌）：五段证据（各车道终态/投影计数与坏事件统计/usage 降级情况/耗时对比 claude 基线/产物硬门）+「默认值是否翻转 claude→dsh」决策申请段（注明属用户裁决项）
- [ ] 3.3 手册交叉引用核对：ADR-271、母设计文档、SPEC 依赖链三节引用可达且与实现一致

## 4. 真实验收信号落位与收尾

- [ ] 4.1 `.fenix/todo.md` 登记真实全链验收执行请求（执行命令、前置条件、预计耗时）；accept 模式自检全绿（预演）
- [ ] 4.2 全量回归绿 + 编译自洽；确认全链无任何自动发起的真实模型调用路径

## Deliverables

```yaml
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/signals.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/pm_engine/spec_review.py
  kind: modify
- path: docs/help/14-pipeline-throughput-ops.md
  kind: new
- path: docs/help/README.md
  kind: modify
- path: tests/test_pipeline_throughput_governance.py
  kind: new
```

## 1. 并发槽位上调

- [ ] 1.1 派发队列 `agents.max_concurrent` 代码缺省值 2→5；`.fenix/config.template.yaml` 推荐值 3→5 并附资源前提注释（worktree 磁盘、网关并发、回归锁串行化），显式配置优先级不变
- [ ] 1.2 新增 `docs/help/14-pipeline-throughput-ops.md` 并在 `docs/help/README.md` 完整目录表登记（#14 一行）：运行时 `.fenix/config.yaml` 的人工调整与回退步骤、并发上调的资源面说明（人工步骤仅入文档，不改运行时配置）
- [ ] 1.3 单测（落 `tests/test_pipeline_throughput_governance.py`）覆盖：无显式配置生效 5、显式配置优先、多 run 到回归检查点时 full-suite.lock 互斥与 600s 等待上限语义不变

## 2. merge 前置预检

- [ ] 2.1 通读 `evo-merge-back-wip-overlap-gate` 归档 spec 与 `core/wip_checkpoint.py` 现状，在 design 决策 2 约束下复用既有重叠判定（在实现说明中记录复用点，不重复实现同语义判定）
- [ ] 2.2 merge-back 发起前实现交集预检（主树 WIP 脏文件集 ∩ 分支触碰文件集）：非空则不发起 merge，发人工升级告警（含交集清单与两侧来源）、spec 保持可重试；无交集零额外开销直通
- [ ] 2.3 增加 `merge_precheck_bypass` 配置逃生门（true 时跳过预检直接 merge）
- [ ] 2.4 单测（落 `tests/test_pipeline_throughput_governance.py`）覆盖：重叠拦截升级、无交集直通、逃生门跳过、升级告警内容含清单

## 3. 重启排水保护

- [ ] 3.1 新增配置 `agents.run_drain_max_seconds`（缺省 60，与 supervisor SIGKILL 宽限一致）：daemon restart 排水等待上限取该值，超窗走既有强杀路径；显式配置可调大
- [ ] 3.2 restart 触发停止新派发后，向每个在飞 run 广播一次 checkpoint 信号（写 run 控制文件即返回，不阻塞排水等待，无新增失败终态）；超窗强杀与恢复续做行为与现状一致
- [ ] 3.3 单测（落 `tests/test_pipeline_throughput_governance.py`）覆盖：缺省窗口重启无 1800s 级空等、窗口内收尾的 run 正常合并判定、显式调大生效、广播零副作用（不识别信号的 run 处理不变）

## 4. bug-found 小缺陷 fastlane

- [ ] 4.1 验证管线实现三条件判定（失败场景数=1、judge 归因影响面 ≤3 文件、无 dispute/adjudication 标记）与路径选择记录（判定过程与所选路径可追溯）
- [ ] 4.2 fastlane 承接：生成 code-fix 轻量修复任务；修复后子集重验（失败场景 ∪ depends_on 前置链，报告含全量场景判定且未实跑者标注沿用来源）；轮次计入既有验证轮预算，同一验证轮连续 2 次 fastlane 修复后仍失败强制回落整轮 fix SPEC 路径；修复 diff 不豁免既有 code-review/交付物门禁
- [ ] 4.3 单测（落 `tests/test_pipeline_throughput_governance.py`）覆盖：三条件全过走 fastlane、多场景失败回落整轮、子集重验通过收敛、连续 2 次失败强制回落、判定记录可追溯

## 5. spec-review 打回理由结构化

- [ ] 5.1 spec-review 打回结果 JSON 新增 `rejection_class` 字段（枚举 `format`/`substantive`），评审 prompt 注入段下发两类边界定义；通过结果不要求该字段
- [ ] 5.2 读侧实现按 `rejection_class` 分桶统计（fail-open 空值），缺字段/非法值按 unknown 兼容，存量结果零迁移
- [ ] 5.3 单测（落 `tests/test_pipeline_throughput_governance.py`）覆盖：格式/实质打回带分类、通过结果无字段合法、存量缺字段 unknown 兼容、统计分桶正确

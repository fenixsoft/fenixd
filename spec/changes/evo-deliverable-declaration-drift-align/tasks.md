## Deliverables

```yaml
- path: core/deliverables.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_deliverable_drift_align.py
  kind: new
```

## 1. 漂移笔误机械对齐

- [ ] 1.1 core/deliverables.py：在既有孤儿判定分支（历史命中→走人工）前插入漂移对齐判定：声明路径在主树与实现分支 HEAD 均缺 且 git 历史命中 → 进入 _locate_drift_target 候选定位
- [ ] 1.2 新增 _locate_drift_target(project_root, declared_path)：以旧文件 basename 递归扫描 core/，候选唯一（1 个）才算可对齐；候选 0 个或多于 1 个 → fail-open 回人工（不机械改写）
- [ ] 1.3 机械对齐执行：改写 tasks.md Deliverables 声明段 path（kind 不变），写回文件并校验 yaml 可解析
- [ ] 1.4 审计记录：dispute_audits 写入 verdict=drift-aligned、actual_path、候选唯一性证据（历史命中数、候选清单）+ reasoning
- [ ] 1.5 对齐成功后解除 blocked（清 error、置回原实现态或 ready 重排），失败任一步骤即中止对齐走人工

## 2. 派发前同源草案收敛检查

- [ ] 2.1 core/pm_engine/engine.py _on_spec_ready：派发 implementer 前扫描 spec/changes/ 下所有 SUPERSEDED.md
- [ ] 2.2 本 spec 被任一 SUPERSEDED.md 声明为已取代草案，或本 spec 目录自身含 SUPERSEDED.md → 拦截派发、置 blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径）
- [ ] 2.3 收敛完成信号：被取代目录删除或 SUPERSEDED.md 移除后派发恢复；同源判定键=capability + name 去时间戳后缀归一

## 3. 测试

- [ ] 3.1 tests/test_deliverable_drift_align.py：覆盖唯一候选机械对齐（改写+审计+解阻）、零候选/多候选 fail-open 回人工、异路径同 basename 冲突回人工
- [ ] 3.2 tests/test_deliverable_drift_align.py：覆盖同源草案派发拦截（SUPERSEDED.md 命中阻断）与收敛后恢复派发
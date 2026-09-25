## Deliverables

```yaml
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/worktree_manager/types.py
  kind: modify
- path: core/code_fix.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_mergeback_wip_coordination.py
  kind: new
```

## 1. 占用者识别

- [ ] 1.1 `core/worktree_manager/mergeback.py` 增占用者识别：overlap 文件集 × 在飞实现车道分支 `git diff --name-only <主树HEAD>..<分支>` 求交；命中 → 记录 run/spec/分支；零命中 → 无主。识别结果随 defer 批进度/日志留痕（数据结构经 `core/worktree_manager/types.py` 扩展）

## 2. 事件驱动重试与无主升级

- [ ] 2.1 `core/code_fix.py` defer 批合回消费者：持有者为在飞 run 时注册其终态监听（注册时先查该 run 是否已终态，是则立即重试），终态到达秒级重试合回；固定轮询降级为兜底
- [ ] 2.2 无主判定 + 宽限（`admin.mergeback_wip_orphan_grace_minutes`，缺省 30）耗尽 → `core/admin_monitor.py` 触发既有 `mergeback_wip_overlap` major 告警（附 overlap 文件清单与识别证据）；批保持「保留待自动合回」语义
- [ ] 2.3 `.fenix/config.template.yaml` 增 `admin.mergeback_wip_orphan_grace_minutes`（缺省 30，注释说明语义）

## 3. 验证

- [ ] 3.1 单测（tests/test_mergeback_wip_coordination.py）：overlap + 在飞持有者 → 识别命中；持有者 run 终态事件到达后合回秒级重试成功（不等到轮询周期）
- [ ] 3.2 单测：overlap + 无主 → 宽限内不告警；宽限耗尽发出 major 告警（含文件与证据）、批不丢弃、主树零触碰
- [ ] 3.3 单测：注册监听时 run 已终态 → 立即触发重试（不依赖后续事件）
- [ ] 3.4 单测：无 overlap → 合回路径与现状逐字一致（零新增开销）

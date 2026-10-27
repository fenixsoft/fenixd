## Deliverables

```yaml
- path: core/worktree_manager/stale_sweep.py
  kind: modify
- path: core/config.py
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/BranchGcPanel.tsx
  kind: new
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
- path: tests/test_branch_gc.py
  kind: new
```

## 1. 配置层：worktree.branch_gc 节解析与模板

- [ ] 1.1 `core/config.py` 新增 `worktree.branch_gc` 节解析：`enabled`（bool，缺省 True）、
  `retention_days`（int，缺省 7，最小值 1）；节存在但类型非法（非 dict / 字段类型错 /
  retention_days 非 int-not-bool / <1）时按既有 stale_code_selfheal 容错口径回退默认值，
  不抛异常不进入硬失败
- [ ] 1.2 `.fenix/config.template.yaml` 的 `worktree:` 节新增 `branch_gc` 注释块：两个键的
  缺省值、宽限期语义（deliverables D1 读侧兜底窗口保护）、关闭即恢复引入前行为
- [ ] 1.3 `tests/test_branch_gc.py` 覆盖配置解析：缺省节（默认 True/7 生效）、合法值透传、
  retention_days=0/负数/非 int/字符串回退默认、enabled 非法回退、节非 dict 容错

## 2. GC 核心：stale_sweep 已合并分支回收

- [ ] 2.1 `core/worktree_manager/stale_sweep.py` 新增分支 GC 环节（worktree 清扫后追加，
  同锁内执行）：`git for-each-ref` 扫描实现/验证分支前缀家族（前缀取既有
  `worktree.implement_branch_prefix` 配置拼 `fenix/` 形态），先全量快照再逐条判定，
  沿用既有「边扫边删防护」口径；GC 环节 MUST NOT 被 worktree 清扫的前置 early-return
  （base_dir 不存在 / 目录扫描 OSError，stale_sweep.py:54-55、79-86）静默跳过——分支 GC
  不依赖 base_dir，挂载点须绕开这些 return 或在方法入口独立守卫
- [ ] 2.2 四条件判定实现：`--merged <基线>` 合并判定（基线走既有 `resolve_base_branch`：
  origin/HEAD → main → master 回退，不以硬编码 main 使 master 基线仓库整轮失效）；
  tip 提交时间早于 `worktree.branch_gc.retention_days`；未被任何已登记 worktree checkout；
  spec 活跃豁免 = `_branch_protected_by_state` 在飞引用保护（单一来源复用，不复制状态常量）
  ∪ STATE.md 显式活跃状态判定（implementing/implemented/testing/reviewing/
  ready+_recovery_resume/blocked+frozen_hold，补齐 `_branch_protected_by_state` 未覆盖的
  reviewing），另对在册 legacy 登记（`_legacy`）命中的分支跳过；spec 名解析复用
  `_spec_from_branch` 口径（其硬编码 fenix/ 前缀，非 fenix 配置命名空间分支解析失败
  按宁漏勿误跳过）
- [ ] 2.3 删除动作只用 `git branch -d`，单分支失败（含并发 checkout 拒绝）记录明细后
  继续其余分支，不中断清扫轮；GC 整体异常按既有清扫环节同口径兜底（non-blocking）
- [ ] 2.4 可观测：有删除时输出结构化日志（删除清单、总数、四档跳过计数：
  未合并/宽限期内/活跃 spec/worktree 占用；未合并分支只计数不删）；零删除静默；
  `worktree.branch_gc.enabled=false` 时整个环节跳过且无日志
- [ ] 2.5 `tests/test_branch_gc.py` 覆盖 GC 判定与执行：四条件齐备删除成功、宽限期内保留、
  未合并不删且计数、活跃 spec 豁免（含 testing/reviewing 等状态）、worktree 占用跳过、
  GC 关闭零动作、单分支 -d 失败不中断、解析失败分支跳过、零删除静默、在册 legacy 登记
  分支跳过

## 3. Dashboard：分支 GC 设置面板

- [ ] 3.1 `core/dashboard/data/config_admin.py` 注册 `worktree.branch_gc.enabled` /
  `worktree.branch_gc.retention_days` 受管键：键清单、来源归因（project/managed）、
  默认回显视图、写入校验谓词（retention_days int-not-bool 且 ≥1），
  对齐 stale_code_selfheal 的注册形态
- [ ] 3.2 `core/dashboard/static/src/services/dashboard.ts` 的 `ConfigData` 增补
  worktree branch_gc 类型声明（enabled?: boolean; retention_days?: number）
- [ ] 3.3 新建 `core/dashboard/static/src/pages/settings/components/BranchGcPanel.tsx`：
  开关（enabled）+ 宽限期天数输入（retention_days，最小 1），说明文案含宽限期语义，
  保存走既有配置写回通道，回显当前生效值
- [ ] 3.4 `core/dashboard/static/src/pages/settings/index.tsx` 注册 BranchGcPanel 到设置页
- [ ] 3.5 重建前端产物 dist（npm build），确认构建零错误

## 4. 收尾验证

- [ ] 4.1 全量回归：`pytest tests/` 通过，确认无存量用例因 GC 引入而失败
  （重点：既有 stale_sweep / worktree 清扫相关用例）
- [ ] 4.2 端到端冒烟：在测试工作区构造「已合并+超期」「已合并+宽限期内」「未合并」
  三条 fenix/* 分支，跑一轮清扫，验证仅第一条被删、日志计数与场景一致

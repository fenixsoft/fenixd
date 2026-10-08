## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/knowledge_audit.py
  kind: modify
- path: tests/test_stray_whitelist_untracked.py
  kind: new
```

## 1. 检测流

- [ ] 1.1 core/worktree_manager/stray_wip.py：在未跟踪散件盘点旁新增白名单脱落检测流——复用 _git_check_ignore_detail 批量通道跑 check-ignore -v -n --non-matching，筛出命中 `!` 放行规则但 git ls-files 不含的路径，发 whitelist_untracked 信号（经 AdminStore.append 直发，evidence 含「项目名=」与「文件清单(N):」段，对齐 _write_untracked_escalated_alert 同款形态）；去重沿用 untracked 流同款指纹注册表（_untracked_registry + 指纹消失自动复位），同集合只发一次；既有散件流的 negation 豁免语义（:505-506）不变，两流互不污染

## 2. 信号登记与约定互引

- [ ] 2.1 core/admin_monitor.py：**三表登记** whitelist_untracked——SIGNAL_SEVERITY（severity major）、SIGNAL_RECOMMENDATION、STORED_SIGNAL_TYPES 三处缺一不可（对齐 maintree_untracked_stray_escalated 先例；仅两表登记则摄取循环 continue 跳过、信号落 store 无人摄取不唤起，见 admin_monitor.py:354、:500-502 与 verify_uniform_failure 事故注释 :537-544），文案写明「negation 放行即声明入库意图、放行+未跟踪＝白名单脱落」，处置建议二选一（恢复入库或删除放行规则）
- [ ] 2.2 core/knowledge_audit.py：第 75-77 行白名单注释补一句指向 whitelist_untracked 巡检，使约定与执行机制互为引用

## 3. 测试

- [ ] 3.1 tests/test_stray_whitelist_untracked.py：沿用 tests/test_stray_untrack_remediation.py 的双断言口径——真散件与 tracked 白名单文件不误报新信号、放行文件被移出索引（git rm --cached 场景）后必报且不计入散件计数、同指纹重复盘点不重复唤起

## 4. 项目侧恢复（一次性处置）

- [ ] 4.1 在 /root/potplayer-base 执行 git add .fenix/verify.yaml 并提交恢复入库，提交信息留痕 c91213f 回归链；顺带核对白名单其余文件 tracked 状态（.fenix/todo.md 已 tracked；config.template.yaml 盘上从未物化属正常，无需动作）

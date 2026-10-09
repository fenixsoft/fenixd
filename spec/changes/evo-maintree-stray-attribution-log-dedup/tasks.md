## Deliverables

```yaml
- path: core/worktree_manager/stray_wip.py
  kind: modify
- path: tests/test_maintree_stray_wip_sweep.py
  kind: modify
```

## 1. 落地校验

- [ ] 1.1 core/worktree_manager/stray_wip.py：MainTreeStrayWipSweeper.__init__ 新增会话归因留痕去重状态（上次归因键=文件集+占用者会话标识、抑制轮计数、上次留痕时间戳），进程内内存态，不落 AdminStore。
- [ ] 1.2 core/worktree_manager/stray_wip.py：_tracked_sweep_locked 会话归因分支改三态落日志——首次或状态变化（文件集/占用者变化）落全量行；稳定期每满 60 分钟落 1 条聚合行（含重复计数）；其余轮次静默计数。
- [ ] 1.3 core/worktree_manager/stray_wip.py：归因解除路径补一条解除行并清去重状态，解除后再归因按首次计数。解除判定单点挂在归因分支之前（_last_session_attr 非空且本轮非会话归因或文件集为空），覆盖文件消失复位、占用者清空（holder 整体清空时归因分支不进入，session_attributed=False）、归因迁至在飞车道三类迁移；宽限升级处置接管前必经归因消失轮，由该判定覆盖。

## 2. 测试

- [ ] 2.1 tests/test_maintree_stray_wip_sweep.py：新增用例——同文件同占用者连续多轮盘点仅首轮 1 条留痕；跨 60 分钟窗口后恰 1 条聚合行且含正确计数；文件集变化、占用者变化、归因解除（文件消失、占用者清空）各触发一条新留痕；解除后同会话再归因落新全量行（不得因 key 与解除前相同而被抑制计数吞掉）。
- [ ] 2.2 既有用例回归通过（python3 -m pytest tests/test_maintree_stray_wip_sweep.py tests/test_maintree_interactive_session_attribution.py -q）——后者直接覆盖会话归因分支既有返回 status 契约（全程 logger=None，不锁日志频次，本改造不应破坏）。
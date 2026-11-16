## Deliverables

```yaml
- path: core/run_task_track.py
  kind: modify
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: tests/test_honest_exit_convergence.py
  kind: modify
```

## 1. pytest 先行（纯逻辑层覆盖）

- [x] 1.1 tests/test_honest_exit_convergence.py 新增 success+unattainable 告警场景：fast_track 与 queue 两车道 success 收口 + 合法申报 → 各写入 impl_unattainable_tasks，description 为拦截语境（非既有「门禁已放行」文案）（先红）
- [x] 1.2 同文件新增无申报零误报场景（success 且 unattainable 缺失/为空 → 不写告警）与非法申报 fail-closed 场景（非法条目 → 不告警不豁免不注记）
- [x] 1.3 同文件新增门禁注记场景：gap ∩ 合法申报非空 → task-gap error 含「已申报不可达」注记；无申报 → 无注记；TASK_GAP_ERROR_PREFIX 前缀不变
- [x] 1.4 同文件新增回炉提取器兼容场景：带注记的 task-gap error 经 `task_reflow._extract_gap_tasks` 提取结果与无注记时全等（注记空格分隔、不罗列 id，D2 格式约束）

## 2. 申报解析单源 helper

- [x] 2.1 core/run_task_track.py 新增 `declared_unattainable(result) -> list`：复用既有 parse_unattainable，非法条目整体返回空（fail-closed），成功收口车道与门禁注记同源调用

## 3. 车道成功收口申报告警

- [x] 3.1 core/pm_engine/dispatch/fast_track.py 成功收口路径新增申报写入点：declared_unattainable 非空即调 _note_unattainable_todos（传拦截语境 description，D1 语境化形参）；partial 收敛块（:388-406）零触碰
- [x] 3.2 core/pm_engine/dispatch/queue.py 成功收口路径对称新增同一写入点（传拦截语境 description）；partial 收敛门（:2030-2033）零触碰，两分支互斥不重复告警

## 4. 门禁注记

- [x] 4.1 core/pm_engine/engine.py `_task_completion_blocker`：gap ∩ declared_unattainable 非空时 error 尾部追加 ` （其中 N 项已申报不可达）`（前置空格分隔、不罗列任务 id——保 task_reflow._extract_gap_tasks 提取全等，见 D2 格式约束），拦截/放行/人工补勾清除逻辑零变化，申报素材不读主树 tasks.md 勾选态

## 5. 契约注释与回归

- [x] 5.1 core/pm_engine/dispatch/fast_track.py:408-410 契约注释补注 success+unattainable 为合法申报形态及其告警语义（verified/bug-found 仍属 verification.verdict）
- [x] 5.2 宿主全量 pytest 0 failed 0 新增豁免（既有诚实退出回归 test_honest_exit_convergence.py 全量保持通过）

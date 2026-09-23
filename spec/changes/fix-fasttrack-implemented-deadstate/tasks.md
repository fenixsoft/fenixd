## Deliverables

```yaml
- path: core/pm_engine/engine.py
  kind: modify
- path: core/pm_engine/dispatch/fast_track.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_fasttrack_implemented_recovery.py
  kind: new
- path: tests/test_stale_code_selfheal.py
  kind: modify
```

## 1. Cap 1：fast-track implemented 恢复出口

- [ ] 1.1 fast_track.py：把 `_fast_track_advance_to_verified` 的 testing 转移之后段（join 门禁 → verified 转移 → 清零点 update → `_on_spec_verified`）抽取为私有方法，原方法与恢复路径两处复用，禁止复制粘贴状态推进序列
- [ ] 1.2 fast_track.py：新增 `_resume_fast_track_after_restart(spec_name)`——implemented → testing（channel=auto，trigger_run_id=implementer_run）→ 调用 1.1 抽取的收尾段；不读 fast-track 共享结果文件
- [ ] 1.3 engine.py：`_on_spec_implemented` fast-track 分支短路前增加恢复形态三条件判定（status==implemented 且 implementer_run 非空；实现者 run 转录 mtime 超 ORPHANED_RUN_GRACE_SECONDS 宽限；`_ocr_lane_inflight` 无本 spec 在飞），成立则调 1.2 重入并记 INFO 日志（spec 名/判据/动作），不成立维持既有短路 debug 留痕
- [ ] 1.4 新增 tests/test_fasttrack_implemented_recovery.py：死态重入走完收尾（重入→testing→join defer 幂等补启→回调→verified→done）、三条件任一不成立维持短路（负例×3）、正常收尾流不触发重入、重入不读共享结果文件、重入 INFO 日志在场

## 2. Cap 2：自愈 OCR 车道在飞豁免

- [ ] 2.1 queue.py：dispatcher（或 pm_engine 委托层）新增公开方法 `ocr_lane_busy() -> bool`——读 `_ocr_lane_inflight` 任一为真即 busy，内部异常按 busy 处理（宁紧勿松）
- [ ] 2.2 fenixd.py：`_is_idle()` 增第五维 `pm_engine.ocr_lane_busy()`，与既有维度同构（异常按非空闲、getattr 链容错），并挂入自愈阻断原因体系（如 `reason="ocr-lane"` 边沿日志）
- [ ] 2.3 tests/test_stale_code_selfheal.py 增用例：车道在飞 120s 不触发 restart_request、车道收尾后空闲重新累计、ocr_lane_busy 异常按非空闲

## 3. 回归与收尾

- [ ] 3.1 全量回归绿：fast-track 正常收尾流、full 模式恢复流、孤儿 planner 防线用例、自愈冷却/自触发既有用例不回归
- [ ] 3.2 Deliverables 对账自检：六项声明路径全部落位（new 存在、modify 有实质改动、无多余未声明入库改动）

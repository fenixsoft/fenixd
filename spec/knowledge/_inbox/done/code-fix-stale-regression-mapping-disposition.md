# code-fix 车道 regression-error 条目的「滞后映射」判别与处置（2026-11-22 批 1795323295）

**候选能力域**：code-fix-lane（批收尾回归门与失败明细映射）、test-engineering（basetemp 会话隔离）。

## 判别法：条目可能是「修复已入树的回归」的重复映射

regression-error 条目 ≠ 存活缺陷。同一轮回归失败会被台账映射成多套 item_id（本例：前批 31 个 id 与本批 31 个 id 完全不相交，但 junit 失败同源）。三步定真伪：

1. **junit 快照取证**：读 `<root>/.fenix/regression/last-run.json`（started_at/finished_at/errors 数）+ junit.xml 错误栈原文——栈形态区分「夹具/环境批量 setup 假失败」与「产品缺陷」（例：`make_numbered_dir → os.scandir(根)` ENOENT = 缓存 basetemp 被并发删除，非 mkdir 失败；错误文本裸根路径是缓存路径的特征，不是父目录缺失）。
2. **时间线对账**：`git log -S <根因特征串> -- <根因文件>` 拿修复提交时刻，与失败回归 started_at 比——修复晚于失败 12h 即实锤滞后映射。
3. **当前树实测**：定向重跑条目指向的测试类（勿跑全量），全绿才可定性。

## 处置：不要全 skipped（no_effective_fix 拒合回）

全 skipped 批会被判 no_effective_fix 拒绝合回（fix 车道契约边界 4）。根因已修 + 存在残余暴露面时：

- 逐条 `status=fixed` + `fix_scope=test`，`reason` **分层归因**写清「主修提交号（非本批）/本批补强内容/实测证据」，绝不冒领主修。
- 本批补强做在残余暴露面：根因主修只保了无 `--basetemp` 路径（pid 唯一根），显式给定共享根仍可复现同型雪崩 → conftest 补每用例生命线守卫（`_ensure_basetemp_alive`：幂等重建被拔缓存根，fail-open）+ 调用方给定共享根不再收尾 rmtree（pytest 下轮 getbasetemp 先 rm_rf 再建，卫生不丢）。
- 守卫测试同步扩契约（静态钉 + 行为钉），防回潮。

## 附带事实

- pytest 9.1.1 given-basetemp 语义：首次 `getbasetemp()` 时 `exists()→rm_rf` 再 `mkdir(mode=0o700)`（非 parents、非 exist_ok）并缓存永不重建；`make_numbered_dir` 先 `os.scandir(root)` 找后缀——中途被拔报「裸根路径 ENOENT」，据此可从错误文本反推缓存态。
- `--basetemp` 唯一注入源是 bin/run_full_suite.py（主机锁 `.fenix/full-suite.lock` 串行化，锁失败回退 pid 唯一）；core/regression.py 跑项目声明 cmd、不注入 basetemp。

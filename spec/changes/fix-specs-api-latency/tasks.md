## Deliverables

```yaml
- path: core/dashboard/data/summary.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: tests/test_dashboard_index.py
  kind: modify
- path: tests/test_dashboard_api.py
  kind: modify
- path: tests/test_specs_api_perf_guard.py
  kind: new
```

## 1. SummaryIndex 分槽锁

- [ ] 1.1 `core/dashboard/data/summary.py`：`_lock` 改为 `_locks: dict[str, RLock]` + `_lock_for(key)`（`dict.setdefault` 原子取槽，注释说明 GIL 原子性与槽锁残留取舍）；`get` / `state_snapshot` / `invalidation_signature` 三方法 `with self._lock` 全部改为 `with self._lock_for(key)`
- [ ] 1.2 类 docstring「锁粒度取舍（code-review item 8b43aa321467）」段改写为分槽现状：记录翻案依据（7 项目、实测锁排队 ~0.3s、冷构建 1.875s 长尾），保留同项目互斥语义描述
- [ ] 1.3 `tests/test_dashboard_index.py` 新增并发测试：双线程分别对两个项目目录做冷重建（槽内慢速 IO 用 monkeypatch 拖延），断言另一项目读请求等待时间显著小于对方重建时长（跨槽不阻塞）；同项目并发 get 仍互斥（中间态不可见）；`invalidation_signature` 内调 `state_snapshot` 同槽重入不死锁

## 2. get_with_signature 同趟聚合

- [ ] 2.1 `core/dashboard/data/summary.py`：新增 `get_with_signature(proot, specs=None, state_sig=None) -> tuple[list, str | None]`——取数完成时复用本轮内存中的 per-spec sigs（命中条目取 `idx[name]["sigs"]` 存量、重算条目取新算 sigs）+ 本轮 state/arch/runs 签名，按 `invalidation_signature` 同构结构 combine；签名组件（state/arch stat）不可得时返回 `(列表, None)`；聚合段零 stat（仅排序与哈希）；`get()` 改为薄包装 `return get_with_signature(...)[0]`，签名与行为对外不变；`invalidation_signature` docstring 注明生产路径退役、唯一消费方为一致性守卫测试
- [ ] 2.2 `tests/test_dashboard_index.py` 新增一致性守卫：同一磁盘状态下 `get_with_signature()[1]` 与 `invalidation_signature()` 逐字节等值；签名不可得分支（monkeypatch `_stat_sig` 返回 None）返回 None 签名且列表仍产出
- [ ] 2.3 `tests/test_dashboard_index.py` 新增聚合零额外扫描测试：monkeypatch 计数 `_stat_sig`/目录遍历调用，索引全命中状态下二次调用 `get_with_signature`，断言聚合阶段新增计数为零

## 3. /api/specs 自含协商改造

- [ ] 3.1 `core/dashboard/routes/base.py`：`_api_specs` 改自含响应 handler——内部 `get_with_signature` → 签名不可得降级无条件 200（不挂 ETag）→ `_if_none_match_hit` 内联协商：命中 `_write_304`、未命中 `_json` 200 体附 ETag；page/page_size 原始 query 值拼稳定串与聚合签名 combine 为最终 ETag（原 `_sig_specs` 拼装逻辑迁入，翻页变体不共享 ETag）；304 路径不序列化响应体
- [ ] 3.2 `core/dashboard/routes/base.py`：`_API_GET_ROUTES` 的 `/api/specs` 条目摘掉第 4 位 sig_fn（4 元组 → 3 元组）；`_sig_specs` 函数体迁出后删除（确认无其他消费方）
- [ ] 3.3 `tests/test_dashboard_api.py` 新增/改造测试：304 命中（数据未变时空体附当前 ETag）；数据变化后 200 全量体新 ETag；无条件请求 200 体与 ETag 头共存；page/page_size 变体 ETag 不同；签名不可得降级为 200 无 ETag 头；304 空体不写 Content-Length 非 0 值（`_write_304` 既有纪律回归）

## 4. 性能与规模守卫

- [ ] 4.1 `tests/test_specs_api_perf_guard.py`（新文件）：造含归档态的规模夹具（活跃 spec 目录 + 归档 spec 目录各 ≥300 个——归档分支必须覆盖，`changes.is_dir()` 假阳性教训）；确定性断言优先：`/api/specs` 单次 200 请求全链（签名+取数）的 `_stat_sig` 调用计数 ≤ 既有三趟形态的 1/2（三趟并一趟的结构性证明，不依赖绝对时间）；附信息性耗时打印（热路径 < 300ms 量级观察，不作硬门防 CI 抖动误拦）
- [ ] 4.2 `tests/test_specs_api_perf_guard.py`：跨项目互斥规模断言——项目 A 冷重建在飞时项目 B 的 `/api/specs` 端到端响应不被阻塞（配合 1.3 的单测层证据，此处走 handler 层）

## 5. 回归收尾

- [ ] 5.1 watcher 回归验证：`tests/test_dashboard_watcher_incremental.py` 全绿（`get()` 薄包装形态下 SSE 广播路径零变化）；全量测试套件（pytest tests/ 相关面 + 前端 node --test）通过
- [ ] 5.2 交付物守卫对账：Deliverables 五文件全部落地，`git status` 无未声明交付物残留（临时截图/夹具入 `.history`）

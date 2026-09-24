## Deliverables

```yaml
- path: core/code_review.py
  kind: modify
- path: core/dashboard/data/code_review.py
  kind: modify
- path: core/dashboard/routes/code_review_routes.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/QualityTab.tsx
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 后端回链写侧（daemon 消费端）

- [ ] 1.1 在 `core/code_review.py` 新增回链结果原子写工具（同目录 tmp + `os.replace`，路径常量 `CODE_REVIEW_REQUEST_RESULT = ".fenix/code_review_request_result.json"`）与读函数 `read_request_result(project_root)`：文件缺失/JSON 损坏返回缺省态 `{requested_at: None, status: None, reason: None, message: None, finished_at: None}`，MUST NOT 抛异常
- [ ] 1.2 改造 `fenixd.py:_check_code_review_requests`：hosting_state 守卫拒绝分支（stopped/unmanaged）、payload 非法分支落 `dropped` 结果（reason 区分 `daemon_not_running` / `daemon_unmanaged` / `invalid_payload`），中文 message 如实描述
- [ ] 1.3 同函数单飞拒绝分支（`_in_flight_check_and_set()` 命中）落 `dropped` 结果（reason=`already_running`），保持既有单飞旗标置位/复位顺序不变
- [ ] 1.4 worker 池投递成功后落 `started` 结果（requested_at 回链闭包传入）；worker 内 `collect_manifest` 异常/manifest 为空落 `failed` 结果（reason=`manifest_error` / `manifest_empty`）；submit 抛异常分支落 `failed`（reason=`submit_error`）且保持既有单飞复位逻辑

## 2. 后端读侧与路由

- [ ] 2.1 `core/dashboard/data/code_review.py` 新增 `read_code_review_request_result(project_root)` 封装（复用 1.1 读函数，缺省态形态对齐 `read_code_fix_request_result`）
- [ ] 2.2 `code_review_routes.py` 新增 `GET /api/code-review/run-result?project=<name>`：返回回链内容，缺失/损坏返回缺省态 200 不 500，项目不存在 404（形态对齐 `_api_code_review_fix_run_result`）；路由需同步注册进 `core/dashboard/routes/base.py`（exact 路由表 + dispatch wrapper，对齐 fix-run-result 的表项与 wrapper 形态）
- [ ] 2.3 `_api_code_review_run` 在既有 running 守卫后新增受理窗口守卫：结果 `status=started` 且 `progress.running=false` 且 `finished_at` 距今 ≤900s 且 `progress.review_id` 内嵌 epoch ≤ `finished_at`（run 已启动过即放行，见 design D3）→ 409 稳定错误码 `code_review_ack_pending`（经 `_coded_error` 下发）；既有 `code_review_running` 409 与信号 O_EXCL 409 语义不变

## 3. 前端受理等待态

- [ ] 3.1 `services/dashboard.ts` 新增 `getCodeReviewRunResult(project)` API 封装与 `CodeReviewRunResult` 类型（对齐 `getCodeFixRunResult` 形态）
- [ ] 3.2 `QualityTab.tsx` 新增独立 `ackPending` 门控态与卸载哨兵 ref（复用 `fixRunPollAbortedRef` 模式）：仅禁用两个审查触发按钮，不并入 `actionPending`；卸载/切页签/切项目立即置位哨兵并停止轮询不弹提示
- [ ] 3.3 改造 `handleTrigger`：POST 200 后移除既有「已受理」终态 toast，置 `ackPending` 后 1s 间隔轮询 run-result（上限 120s），仅认 `requested_at` 匹配本次的结果；`dropped` → warning 回显 message、`failed` → error 回显、超时 → 兜底提示并解禁
- [ ] 3.4 `started` 分支接续 2s 间隔轮询 `loadProgress` 直到 `running=true`（上限 60s）交由既有进度卡片接管，超时提示「已受理但启动较慢」并解禁；各分支收尾（含超时/失败）复位 `ackPending`

## 4. 测试与验证

- [ ] 4.1 `tests/test_code_review.py` 新增回链写侧单测：三态落盘（started/dropped/failed）、payload 键与原子性（tmp+replace）、单飞拒绝/守卫拒绝分支均落结果且单飞旗标顺序不变
- [ ] 4.2 同文件新增读侧与窗口守卫单测：缺省态（缺失/损坏不 500）、窗口守卫四分支（started+未 running+新鲜+无更新 run → 409 `code_review_ack_pending`；running=true → 既有 `code_review_running`；陈旧结果超 900s → 放行；run 已结束但 review_id epoch > finished_at → 放行）
- [ ] 4.3 前端构建验证：`core/dashboard/static` 下 `npm run build` 零错误（ackPending 门控、两段轮询、哨兵清理不破坏既有 TypeScript 契约）

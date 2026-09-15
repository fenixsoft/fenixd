# Tasks: add-verdict-credibility-gate

## Deliverables

```yaml
- path: core/verify_engine/screenshot_lab.py
  kind: new
- path: core/verify_engine/browser.py
  kind: modify
- path: core/pm_engine/verification.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
```

## 1. 截图健全性算法标签（screenshot-evidence-labeling）

- [x] 1.1 新建 `core/verify_engine/screenshot_lab.py`：`classify_screenshot(path) -> dict` 纯函数——像素标准差、主色占比、低对比度指标（口径对齐 skimage low contrast），阈值集中为模块常量；判定自身异常时返回空标签并记 warning，绝不抛出
- [x] 1.2 `core/verify_engine/browser.py` 的 `screenshot()` 落盘后调用分类器，标签（`blank_screenshot`/`low_contrast` + 量化指标）并入返回值；verify_engine 引擎侧把标签写入场景 evidence 并随 report.json 持久化
- [x] 1.3 单测：纯白图 → `blank_screenshot: true`；正常内容截图 → 无任何标签；低对比度图 → `low_contrast: true`；分类器异常时截图照常落盘且步骤不失败

## 2. 归因证据分级门（verdict-attribution-evidence-gate）

- [x] 2.1 `core/pm_engine/verification.py` 报告落盘/打回上下文组装前的框架侧校验器：按「场景 evidence 构成 + 归因引用」机械计算归因级别（`evidence-backed` / `speculative` / `pending-visual`），写入 report.json 的 `attribution_level` 字段——judge 只产出归因文本与证据引用，级别由框架算出（不依赖 judge 自律与多模态能力）
- [x] 2.2 门禁：打回依据全部为 `speculative` 时抑制 bug-found 打回——转重验一次或在 error 写「归因证据不足待人工复核」，不得带推测信号打回 implementer
- [x] 2.3 白屏方向约束：evidence 含 `blank_screenshot: true` 时归因必须引用该标签且限定 env 方向；归因到数据层（registry/项目列表类）或未引用标签 → 改判 env 方向并覆盖级别
- [x] 2.4 单测：三级判定矩阵、纯推测打回被抑制、白屏归因方向改判、多模态与文本 judge 行为同构（规则只读证据构成）

## 3. 缓存归因打标与批量查重（attribution-freshness-governance）

- [x] 3.1 verdict_cache 指纹命中复用归因的路径：附加 `cached_from_previous_round: true` 与来源轮次信息，打回上下文与 report 渲染透传；纯缓存归因（无本轮新增 evidence-backed 证据）按 speculative 口径参与 2.2 门禁
- [x] 3.2 报告落盘前批量归因查重：归一化空白后 ≥3 个场景归因文本逐字相同 → 拒绝落盘、记 error 日志（列出涉及场景），内置在 2.1 同一校验入口
- [x] 3.3 单测：命中打标字段齐全、纯缓存归因触发门禁、批量查重在 2/3 场景边界两侧的行为、真同因多场景的误伤路径（error 日志可定位后重合成）

## 4. 视觉基线防污染（attribution-freshness-governance）

- [x] 4.1 视觉基线首跑固化路径调用 `classify_screenshot`：命中 `blank_screenshot`/`low_contrast` → 拒绝固化，场景记录 `baseline_rejected` + 原因标签
- [x] 4.2 被拒场景的视觉断言本轮按环境存疑处理（warning，不产生像素比对结论）；后续轮次截图干净时正常建立基线
- [x] 4.3 单测：白屏截图拒绝固化、正常截图照常固化、baseline_rejected 在 report 可追溯

## 5. inconclusive 循环升级（inconclusive-loop-escalation）

- [x] 5.1 新增配置键 `verify_engine.inconclusive_escalate_attempts`（缺省 4）并接入读取
- [x] 5.2 `core/pm_engine/verification.py` 的 `_handle_env_blocked_inconclusive` 与 judge 自述环境暂停分支：`_inconclusive_attempts` 达阈值时向 admin store 写 kind=SIGNAL 记录（type=`inconclusive_loop`，含 spec 名、连续轮数、末轮 blocked_env 数、最近实例探针摘要）；阈值内不写
- [x] 5.3 `core/admin_monitor.py`：STORED_SIGNAL_TYPES 加入 `inconclusive_loop`（经 `_detect_family_explosion` 摄取唤起 Administrator）；SUGGESTIONS 增加处置建议——验证环境核查清单（实例就绪/资源与并行度/mock+SSE 链路/探针摘要）与恢复路径（人工处置后解冻并清 `_inconclusive_attempts`）
- [x] 5.4 单测：第 1-3 轮不触发、第 4 轮（可配 N）写入 SIGNAL、admin_monitor 摄取后唤起、人工清计数后从 1 重新计数、unfreeze 清计数同语义

## 6. 回归与事故回放验证

- [x] 6.1 全量回归：test_verify_* / test_pm_verification / test_env_sanity_gate / test_admin* / test_event_bus 套件全绿
- [x] 6.2 事故回放：以 add-spec-status-modal-budget 第 2 轮 report.json + verdict_cache.json + enrich_report.py 产物为夹具，逐项验证——白屏标签命中、registry ignored 归因被降级/改判 env、缓存归因带标、批量文案被拒、（模拟计数到 4）SIGNAL 写入
- [x] 6.3 收尾核对：Deliverables 声明与实际改动一致、memory 关联条目更新

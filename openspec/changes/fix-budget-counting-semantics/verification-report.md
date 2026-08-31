# 验证报告：fix-budget-counting-semantics

- **裁决结论：verified（验证通过，0 产品 Bug）**
- 运行时间：2026-08-30T17:13:23Z（引擎）/ 裁决时间：2026-08-31
- 结果分布：**7 PASS + 2 test-defect（failed）+ 0 warning + 0 error + 0 blocked_env**，共 9 场景
- 报告与证据目录：`/root/fenixd/.fenix/verify-progress/fix-budget-counting-semantics/`
  （report.json 已由 Planner 按 add-verdict-evidence-taxonomy / add-interaction-contract-and-per-assert-triage 增强写回：非 PASS 场景均补齐 `classification` / `evidence` / `assertion_triage`，并按 design D3 约束将 test-defect 的 `status` 由 warning 修正为 `failed`，见 `planner_amendment` 字段）

---

## 一、核心语义验证结论（全部通过）

本变更将「实现 run 死亡」从预算计数中剥离（死亡豁免回退 `used-=1`，core/pm_engine.py:1188-1201），并新增豁免阈值告警（`impl_budget_exempt_loop`，minor，core/pm_engine.py:1203-1242）；正常失败仍照常计数。端到端 mock 断言逐点证实：

| # | 语义点 | 场景 | 关键证据 | 结果 |
|---|--------|------|----------|------|
| 1 | **死亡豁免回退后不冻结**（used=3/4 < budget=4） | v1-exempt-rollback-budget-gate-not-triggered | spec 行仍「实现中」、`.spec-info-row` 与 `.alert-banner-bar` 均 count=0（SSIM 1.0） | ✅ PASS |
| 2 | **达阈值 6 触发 minor 告警且 spec 不冻结** | v1-exempt-alert-banner-render | 横幅条/严重度药丸可见，「一般」（minor 映射）、摘要含 spec 名与「已异常死亡 6 次并被预算豁免回退」 | ✅ PASS |
| 3 | 同上（v2 壳级 strip + Dialog） | v2-exempt-alert-strip-dialog | 「1 条未处理告警」、Dialog 内「轻微」/spec 列/描述全文/「标记已处理」齐备（SSIM 1.0） | ✅ PASS |
| 4 | **豁免审计字段全文**（used 回读证明计数回退生效） | v1-exempt-alert-evidence-audit | `budget_exempt_runs=6`、`threshold=6`、**`used=3`**（bump_impl_budget(-1) 回读值）、建议行「人工清理 _budget_exempt_runs 侧车即可解除告警条件」 | ✅ PASS |
| 5 | **回归点：正常失败仍计数**（used 累计 4/4 冻结） | v1-normal-failure-still-counts | 「🛑 阻塞」徽标、信息子行「实现尝试预算耗尽（4/4）：已停止自动重派，需人工裁决」、「清除」按钮、impl_budget_exhausted(major→「较高」) 告警全文 | ✅ PASS |
| 6 | 回归点（v2 视角：冻结 spec 详情 Dialog 错误全文 + 清除错误按钮） | v2-blocked-detail-error-fulltext | 「阻塞」徽标、「错误:」+「实现尝试预算耗尽（4/4）…最近失败：AssertionError: expected budget field」全文、「清除错误」按钮——**7 条功能断言全过**（视觉项见 §三） | ⚠️ test-defect |
| 7 | **未达阈值不发告警**（幂等门槛） | v1-no-alert-empty-state | `.alert-banner-bar`/`.alert-item` count=0，`#alert-banner` class 全等 `alert-banner hidden` | ✅ PASS |
| 8 | 同上（v2：visibleOn rows.length>0） | v2-no-alert-empty-state | `#alert-banner-strip` count=0，`#v2-content` 正常渲染 | ✅ PASS |
| 9 | **处置路径**（标记已处理 → 移入已解决折叠区） | v1-exempt-alert-handled-resolved-section | 「已解决 (1)」、待处理 1 条不受影响、展开后已解决豁免告警项含「人工处理」徽标与解决依据「已人工清理 _budget_exempt_runs 侧车」——**8 条功能断言全过**（视觉项见 §三） | ⚠️ test-defect |

计数语义矩阵（验证覆盖）：死亡 run → 回退（不冻结+告警）；正常失败 run → 累计（达预算冻结+major 告警）；未达阈值 → 静默；处置 → 折叠区归档，spec 侧无需解冻（告警本身不冻结 spec）。**SPEC 要求的四条路径全部成立，无产品缺陷。**

---

## 二、产品 Bug 清单

**无。** 9 个场景的全部功能断言（第 1~3 层：元素存在/可见/无遮挡/文本全文/属性/控制台）共 60+ 条全部通过；2 个非 PASS 场景的失败仅出现在视觉对比层（第 4 层 SSIM），经取证确认为测试基线缺陷（见下节），与被测产品代码无关。

---

## 三、非 PASS 场景裁决（test-defect，附取证）

两个场景均为「功能断言全过、仅视觉 SSIM 低于阈值」，分类 **test-defect**，按 design D3 约束映射 `status=failed`（非 warning 悬置），不记产品 Bug。

### 1. v2-blocked-detail-error-fulltext — 基线录制状态与场景最终态错配

- **失败项**：`visual_ssim` 0.5687 < 0.95（基线摄于 2026-08-30 23:41 上一轮）。
- **取证**（像素级）：当前图 y≥160 各横向分带亮度均值由基线的 19~33 塌缩至 5~21、标准差由 28~40 崩至 8~12——典型的**全屏遮罩压暗**特征；页面底部（y≥520）基线有表格内容、当前被遮罩压平。即：基线是**未点操作下拉/「详情」的预交互态**（无 Dialog、无遮罩），而当前态是场景要求的**详情 Dialog 打开的终态**。7 条功能断言（Dialog 可见、「错误:」全文、「清除错误」按钮、无点击遮挡、无控制台错误）全部通过。
- **assertion_triage**：`visual_ssim baseline=v2-blocked-detail-error-fulltext_baseline 期望≥0.95 实际 0.5687` → test-defect（基线状态错配，非产品缺陷）。
- **修复建议**：在 Dialog 打开后的最终态重录基线（删除 `baselines/v2-blocked-detail-error-fulltext_baseline.png` 后重跑）。

### 2. v1-exempt-alert-handled-resolved-section — 基线被上一轮失败态截图污染

- **失败项**：`visual_ssim` 0.6378 < 0.95。
- **取证**（md5 逐字节比对）：本场景基线 `baselines/v1-exempt-alert-handled-resolved-section_baseline.png` 的 md5 = `01db99ef693520762f2e16987d1056e5`，与 `v1-no-alert-empty-state_baseline.png` 及上一轮失败态截图 `screenshots/v1-exempt-alert-handled-resolved-section_assert_fail.png`、`v1-no-alert-empty-state_assert_fail.png` **完全相同**——即基线实为「横幅隐藏的空态页」。当前图则正确渲染了横幅条 +「已解决 (1)」折叠区展开终态（已解决豁免告警项、解决依据、「人工处理」徽标断言通过），8 条功能断言全部通过。
- **assertion_triage**：`visual_ssim baseline=v1-exempt-alert-handled-resolved-section_baseline 期望≥0.95 实际 0.6378` → test-defect（基线污染/跨场景误绑定，非产品缺陷）。
- **修复建议**：删除被污染基线，在「横幅 + 已解决折叠区展开」终态重录。

> 聚合说明：两处失败同为「视觉基线缺陷」这一 root cause（基线录制/绑定环节），按聚合规则合并报告为 1 类测试缺陷（2 个场景），不影响产品代码。

---

## 四、断言时序 / 豁免特判核查

- **no_console_error**：9 个场景 `errors` 均为空；`filtered_network` 均为空（本批场景不涉及外部 API 网络噪声豁免，无需启用）。
- **no_auth_error / 密钥签名关键词**：未出现。
- **断言时序（弹窗关闭后查弹窗内元素）**：v2 详情 Dialog 场景的所有 Dialog 内断言均在 Dialog 打开期间执行并通过，无时序问题。

## 五、后续动作

1. **无需产品修复**——本变更可进入 archive 流程。
2. 测试基建修复（不阻塞）：按 §三 重录两份基线后复跑，两场景应转 PASS（基线环节缺陷建议在验证引擎侧增加「基线 md5 与其他场景/历史失败截图去重」校验，防止再次发生跨场景误绑定）。

## 本轮场景集变更

场景集与持久化集一致，无变更。


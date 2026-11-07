## Deliverables

```yaml
- path: core/knowledge.py
  kind: modify
- path: tests/test_knowledge_anchor_check.py
  kind: new
- path: agents/knowledge-distill.md
  kind: modify
- path: spec/knowledge/domains/knowledge-atlas/knowledge-atlas-directory.md
  kind: modify
- path: spec/knowledge/domains/knowledge-atlas/knowledge-audit.md
  kind: modify
- path: spec/knowledge/domains/knowledge-atlas/knowledge-retirement-runbook.md
  kind: new
- path: spec/knowledge/domains/knowledge-atlas/_domain.md
  kind: modify
- path: spec/knowledge/domains/dashboard-platform/v2-data-adapters.md
  kind: delete
- path: spec/knowledge/domains/dashboard-platform/v2-legacy-coexist.md
  kind: delete
- path: spec/knowledge/domains/dashboard-platform/v2-sdk-vendor.md
  kind: delete
- path: spec/knowledge/domains/dashboard-platform/v2-shell-router.md
  kind: delete
- path: spec/knowledge/domains/dashboard-platform/v2-sse-bridge.md
  kind: delete
- path: spec/knowledge/domains/dashboard-platform/_domain.md
  kind: modify
- path: spec/knowledge/adr/ADR-033-v2-frontend-vendored-amis-sdk.md
  kind: modify
- path: spec/knowledge/adr/ADR-038-v2-shell-level-sse-broadcast-bridge.md
  kind: modify
- path: spec/knowledge/adr/ADR-039-v2-adapter-pure-function-data-layer.md
  kind: modify
- path: spec/knowledge/adr/ADR-327-v2-commercial-ui-exception-domain-coexistence.md
  kind: modify
- path: spec/knowledge/adr/ADR-328-v2-mobile-form-breakpoint-single-source-container-level-branch.md
  kind: modify
- path: spec/knowledge/adr/index.md
  kind: modify
- path: spec/knowledge/index.md
  kind: modify
- path: spec/knowledge/domains/dashboard-frontend/unified-page-title-bar.md
  kind: modify
- path: spec/knowledge/domains/dashboard-frontend/spec-doc-view.md
  kind: modify
- path: spec/knowledge/domains/dashboard-frontend/activities-page.md
  kind: modify
```

## 1. 校验器与测试

- [ ] 1.1 `core/knowledge.py`：`_ADR_STATUS_RE` 扩展为 `(accepted|superseded|retired)`；retired 条目缺 `Retired:` 注记行时报违规；retired 正文改写检测与 superseded 同口径；`accepted`/`superseded` 既有校验行为零变化
- [ ] 1.2 `core/knowledge.py`：新增 `check_anchor_references(project_root) -> list`——只扫各能力页 `## 代码锚点` 段内路径 token，仓库相对路径逐一生成并校验盘上存在性；`spec/archive/`、`spec/knowledge/_inbox/`、`node_modules/` 下路径跳过；不并入 `validate_knowledge` 硬门
- [ ] 1.3 新增 `tests/test_knowledge_anchor_check.py`：钉锚点段悬空报、段外路径不扫、排除目录跳过、retired 合规放行/缺注记行报违规/二值行为不回归五组场景（临时知识树夹具形态，同 test_knowledge_audit.py 习语）
- [ ] 1.4 `core/knowledge.py` `build_inbox_fold_prompt` 内联段与 `agents/knowledge-distill.md` 模板各加一句「新建能力页必带代码锚点段（主实现/单源符号/消费方/守卫测试，文件级禁行号）」

## 2. 契约页与退役 runbook

- [ ] 2.1 `knowledge-atlas-directory.md`（rev+1）：能力页结构契约增补代码锚点段与退役即删语义、域页可选「症状速查」段；溯源段登记本 SPEC
- [ ] 2.2 `knowledge-audit.md`（rev+1）：病灶族增第六类「锚点悬空」（检测口径、报告待处置档、不机械自删、不进硬门的理由）；溯源段登记
- [ ] 2.3 新建 `knowledge-retirement-runbook.md`：退役 checklist（代码与路由删除 → 死代码/镜像指令收口 → 知识页删除 → 域表收口与尾注记 → ADR 翻 retired → index 计数 → log 登记 → 复核 grep），并在 `knowledge-atlas/_domain.md` 表登记该页

## 3. 存量清理

- [ ] 3.1 删除 dashboard-platform 五个 amis 壳退役页（v2-shell-router / v2-data-adapters / v2-sdk-vendor / v2-sse-bridge / v2-legacy-coexist）；`dashboard-platform/_domain.md` 五行移除 + 表尾一行退役注记（指向 git 历史与 spec/archive/2026-09-04/05 系列，注明 tests/v2 冒烟基建与 v2_dev_server 现役）+ 域页尾部落首个「症状速查」范例段（收编 dsh web 重连环判据、v2 壳 hash 路由 hash 丢失等既有签名到页指针）
- [ ] 3.2 五条 ADR 翻 retired：ADR-033 / ADR-038 / ADR-039 / ADR-327 / ADR-328（status 行 + `Retired: 2026-11-08 <一句话>` 行，三段正文逐字不动），`adr/index.md` 状态列同步；核对 ADR-037（worktree 测试服务现役）保持 accepted
- [ ] 3.3 清理前与清理后各跑一次全库 grep（五页 capability 名 + 五条 ADR 编号），收口其余知识页/提示词中的悬空引用；`index.md` 超标域行简介收缩到 2~3 句口径（verify-pipeline、verdict-adjudication、code-fix-lane、knowledge-atlas 等），dashboard-platform 能力数量同步（25→20）

## 4. 范例锚点

- [ ] 4.1 三个高频消费页补 `## 代码锚点` 段：`unified-page-title-bar.md`（PageTitleBar.tsx / pageTitleBarStore / pageTitleBar 测试族）、`spec-doc-view.md`（SpecDocModal.tsx / /api/spec-doc 端点实现位）、`activities-page.md`（运维页三页签实现位）；锚点以盘上真实路径为准逐个核验
- [ ] 4.2 对三个范例页跑 `check_anchor_references` 零报告（范例即自证）

## 5. 收工自证

- [ ] 5.1 `pytest tests/test_knowledge_anchor_check.py` 全绿 + 既有 `tests/test_knowledge_*.py` 全绿无回归
- [ ] 5.2 `validate_knowledge` 全树零违规（含五条 retired ADR 放行、删除页无悬空溯源）

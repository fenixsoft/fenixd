## Deliverables

```yaml
- path: core/adjudication_narrative.py
  kind: new
- path: core/pm_engine/family.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: core/agent_runner/token_budget.py
  kind: modify
- path: core/dashboard/static/src/components/alert-shared.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SystemPanel.tsx
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_adjudication_narrative.py
  kind: new
- path: docs/help/06-governance.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 叙事辅助模块

- [x] 1.1 新建 `core/adjudication_narrative.py`：`attach_narrative(entry, ctx)`（choices 非空才发起；成功写 `entry["narrative"]={"text","model","at"}`，at 为 UTC ISO）与内部 `build_narrative`（fail-open 采集 STATE 条目/报告路径，组三段式 prompt，单次 LLM 调用，机械校验「发生了什么/为什么需要你决策/决策选项」三段标题齐全）；LLM 通道经模块级注入点接入（生产=既有 claude -p spawn 通道单发，禁传 `--max-tokens-budget` 类危险旗标；测试=假通道）；模型回退链 `admin.narrative_model`→`admin.agent_model`→框架默认；硬超时 `admin.narrative_timeout_seconds`；任何失败不抛出、至多一次尝试、logger.warning 留痕、不写 narrative 字段；配置读取走 pm_engine 既有口径 `ConfigLoader.get_admin_config(self._pm.config).get(...)`（先例 family.py:563；MUST NOT 反向导入 dashboard data 层私有助手 `_cached_config_value`；热更新经 daemon `_maybe_reload_config` 每轮生效，fenixd.py:865）
- [x] 1.2 新建 `tests/test_adjudication_narrative.py`（假通道注入，配置源 patch 不落 HOME，MUST NOT 真调网关）：三段契约与 narrative 字段形态、LLM 超时回退（告警照常落盘无 narrative）、LLM 异常回退、三段结构校验失败回退、`narrative_enabled=false` 零调用零延迟、桶 0（choices 空）零调用、模型回退链三档

## 2. 发射点接线

- [x] 2.1 `core/pm_engine/family.py` `_send_human_escalation_alert`：store.append 前对 choices 非空的桶 2 告警调用 `attach_narrative`；叙事失败不影响既有 trigger/choices 快照与落盘路径（含 severity 降噪分支原行为不变）
- [x] 2.2 `core/worktree_manager/mergeback.py`（build_artifact_paths_missing）与 `core/agent_runner/token_budget.py`（token_budget）两个旁路 choices 附带点接入同一 `attach_narrative`（禁止第二套 prompt/生成逻辑）
- [x] 2.3 扩展 1.2 单测：经 `_send_human_escalation_alert` 与两个旁路点落盘的告警含 narrative；并断言 description/evidence/recommended_action/choices/trigger 与关闭叙事时的基线形态逐字段一致（纯增强契约）

## 3. 配置与设置 UI

- [x] 3.1 `.fenix/config.template.yaml` admin 段新增 `narrative_enabled`（true）/`narrative_timeout_seconds`（60）/`narrative_model`（空串=回退链）三键，中文注释说明用途、缺省与兜底行为
- [x] 3.2 `core/dashboard/static/src/pages/settings/components/SystemPanel.tsx` admin 作用域新增三控件（布尔开关/数字输入/文本输入），走既有配置保存通道与类型定义
- [x] 3.3 `core/dashboard/static/src/services/dashboard.ts` 告警记录类型加可选 `narrative` 字段（`{text: string; model: string; at: string}`）

## 4. 前端渲染

- [x] 4.1 `core/dashboard/static/src/components/alert-shared.tsx`：在 evidence 区块之前渲染 `narrative.text` 三段式（复用既有 Markdown 渲染组件、默认展开、标注「建议倾向仅供参考」）；记录无 narrative 时 DOM 与现状一致（无空壳容器）；长文本按既有容器规则折叠/滚动，choices 操作区不被遮挡
- [x] 4.2 前端构建（npm 构建 dist 出库）通过，且既有前端单测/lint（如配置了）全绿

## 5. 验证与文档

- [x] 5.1 后端全量相关单测通过：新增 `tests/test_adjudication_narrative.py` 全绿 + 既有 admin/告警相关测试套件（test_admin_*、alert 相关）无回归
- [x] 5.2 `docs/help/06-governance.md` 补充：告警 narrative 字段说明（三段结构、生成时机、失败兜底为机械文案）、三个 admin.narrative_* 配置项及设置页入口

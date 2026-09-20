# 验证报告：add-spec-manual-activation

> ⚠️ 本报告由框架于 2026-09-18T12:02:40Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T12:02:40.556808+00:00

## 结论：✅ 通过（verified）

**状态：verified — 23/23 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 23/23 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 23 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 20.16M |
| 本链增量 Token（输出） | 0.15M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fixture-activation-showcase | 夹具自建：创建 activation-showcase 项目（/root/activation-showcase）并注册到 Registry，STATE.md 含 a-set-ready/a-case-ready/a-manual-ready/a-ready/a-dep-ready/a-dep-null/a-dep-blocked/a-done 等 spec；所有依赖它的场景 depends_on 本场景。 | pass | 0/1 | - |
| cli-test-scheduling | 回归覆盖·调度门控单元测试全绿：tests/test_spec_scheduling.py 覆盖 start_after 哨兵 manual 谓词判定（恒真/大小写变体/前缀误判）、哨兵持久化经 STATE.md 往返不折叠、check_scheduling_deadlines 对 manual 多轮不误唤起，以及既有 start_after 门控（未到期/到期/非法格式/过去时间/冻结解冻）全路径回归。出处：spec/changes/add-spec-manual-activation/tasks.md:1.3, 10.1 | pass | 0/3 | - |
| cli-test-cli-display | 回归覆盖·CLI 展示层单元测试全绿：tests/test_cli_time_display.py 覆盖 get_spec_start_after 哨兵原样返回、fenix_status 信号汇总对 manual 输出「待激活，需人工激活」（非「⏰ 定时」）、fenix_status 状态行输出「⏸ 待激活」（非 start_after manual 伪时间戳）、fenix_process 详情行输出「⏸ 待激活（start_after: manual）」。出处：spec/changes/add-spec-manual-activation/tasks.md:5.3, 5.4, 10.6 | pass | 0/3 | - |
| cli-test-api | 回归覆盖·Dashboard API 单元测试全绿：tests/test_dashboard_api.py 覆盖 /api/spec-start-after 写入 manual 哨兵（含大小写容错）、/api/spec-activate 激活成功/非待激活拒绝/未知 spec 404/终态 403、列表摘要每项含 depends_on 字段且字面量 'null' 规范化为 null（227/244 反例）。出处：spec/changes/add-spec-manual-activation/tasks.md:10.2, 10.3 | pass | 0/3 | - |
| cli-test-evolution | 回归覆盖·Evo 同意立项 API 单元测试全绿：tests/test_dashboard_evolution_api.py 覆盖 POST /api/evolution/accept body start_after='manual'（含大小写变体 parametrize）接受成功、新建 SPEC entry start_after 为 manual（未被 parse_utc 拒绝）、读侧 get_spec_start_after 原样返回哨兵。出处：spec/changes/add-spec-manual-activation/tasks.md:10.4 | pass | 0/3 | - |
| cli-test-data | 回归覆盖·Dashboard 数据层单元测试：_normalize_depends_on 规范化函数（None/空串/空白/'null'/'NULL' → None，'spec-a'/'spec-a, spec-b' → 原样去首尾空白）；spec_summary 返回值含 depends_on 键（与 _ENTRY_SIG_KEYS 对应）。出处：spec/changes/add-spec-manual-activation/tasks.md:3.1, 10.7 | pass | 0/3 | - |
| cli-evo-manual-radio | 交付物·Evo 同意立项三档 Radio 源码就位：grep SuggestedImprovementsPanel.tsx 确认 AcceptScheduleFields 的 Radio.Group 包含 value='manual' 选项（「手工激活」），确认该字段类型 union 扩为 'immediate'\|'scheduled'\|'manual'。出处：spec/changes/add-spec-manual-activation/tasks.md:7.5、design.md D11 | pass | 0/2 | - |
| api-set-manual-sentinel | 正向路径·设置手工激活哨兵：POST /api/spec-start-after value='manual' → 200 + ok=true + start_after='manual'；STATE.md 持久化后仍为 'manual'（不折叠为 null）。出处：core/dashboard/data/admin_actions.py:496-499、core/dashboard/routes/spec_routes.py:214-266。夹具：activation-showcase 项目含 a-set-ready(ready, start_after 无) | pass | 0/6 | - |
| api-set-manual-case-insensitive | 边界语义·大小写容错：POST start_after='MANUAL' → 200 + start_after='manual'（规范化为小写）。出处：core/dashboard/data/admin_actions.py:496 (strip().lower()) | pass | 0/3 | - |
| api-activate-success | 正向路径·激活待激活 SPEC：POST /api/spec-activate 对 start_after=manual 的 ready spec（a-manual-api）→ 200 + ok=true + start_after=null；STATE.md 更新。出处：core/dashboard/data/admin_actions.py:385-428、core/dashboard/routes/spec_routes.py:269-323。夹具：activation-showcase 项目含 a-manual-api(ready, start_after=manual) | pass | 0/4 | - |
| api-activate-not-pending | 幂等拒绝·非待激活 SPEC 激活被拒：POST /api/spec-activate 对 start_after 非 manual 的 ready spec（a-dep-ready）→ 200 + ok=false + reason 含「并非待激活态」；STATE.md 零变更。出处：admin_actions.py:417-423。夹具：a-dep-ready(ready, start_after 无) | pass | 0/3 | - |
| api-activate-unknown-404 | 异常路径·激活不存在的 SPEC：POST /api/spec-activate spec=ghost → 404。出处：spec_routes.py:299-301 | pass | 0/1 | - |
| api-activate-terminal-403 | 异常路径·终态 SPEC 激活被拒：POST /api/spec-activate 对 done 态 spec（a-done）→ 403。出处：admin_actions.py:409-415、spec_routes.py:302-304。夹具：a-done(done) | pass | 0/1 | - |
| api-specs-depends-on | 列表摘要·depends_on 字段含规范化逻辑：GET /api/specs 返回每个 spec 摘要含 depends_on 字段；a-dep-ready 的 depends_on 为 STATE.md 声明串「a-ready, a-manual-ready」；a-dep-null 的 depends_on 在 JSON 响应中为 null（而非字面量字符串 'null'）。出处：core/dashboard/data/summary.py:251-264、329-334 | pass | 0/3 | - |
| web-manual-tag-visible | 列表展示·待激活 Tag 渲染：start_after=manual 的 ready spec（a-manual-ready）在桌面状态列渲染橙色「待激活」Tag。出处：core/dashboard/static/src/pages/projects/list.tsx:252-264 ManualActivationTag。夹具：activation-showcase 项目已注册，STATE.md 含 a-manual-ready(ready, start_after=manual) | pass | 0/3 | - |
| web-dependency-tag-visible | 列表展示·前置依赖 Tag 渲染：ready 且 depends_on 非空的 spec（a-dep-ready）在桌面状态列渲染「前置依赖」Tag。出处：list.tsx:273-283 DependencyTag。夹具：a-dep-ready(ready, depends_on='a-ready, a-manual-ready') | pass | 0/2 | - |
| web-dependency-null-not-visible | 回归反例·depends_on 字面量 null 不误标：STATE.md `- depends_on: null` 解析回字面量字符串 'null' 的 ready spec（a-dep-null）→ 不渲染「前置依赖」Tag（_normalize_depends_on 将 'null' 归一化为 null）。出处：list.tsx:274-276、summary.py:251-264 | pass | 0/2 | - |
| web-dependency-non-ready-not-visible | 回归反例·非 ready 状态不渲染依赖标记：blocked 态 spec（a-dep-blocked）有 depends_on 非空 → 不渲染「前置依赖」Tag（仅 ready 展示）。出处：list.tsx:274 | pass | 0/2 | - |
| web-status-modal-set-manual | 交互流程·修改状态弹窗设为待激活：对 a-ready（ready + 非 manual）点击「修改状态」→ 弹窗调度区显示「设为待激活」按钮 → 点击确认 → start_after 变 manual → 列表出现「待激活」Tag。出处：SpecStatusModal.tsx:588-596、list.tsx:771。夹具：a-ready(ready, start_after=null/absent) | pass | 0/3 | - |
| web-manual-tag-tooltip | 交互流程·待激活 Tag hover 提示：鼠标悬停 a-manual-ready 行的「待激活」Tag → Tooltip 显示「已设为手工激活，需人工激活后才会被拾取」。出处：list.tsx:259 | pass | 0/1 | - |
| web-dependency-tag-tooltip | 交互流程·前置依赖 Tag hover 提示：鼠标悬停 a-dep-ready 行的「前置依赖」Tag → Tooltip 显示「前置依赖：a-ready, a-manual-ready」（依赖名列表原样展示）。出处：list.tsx:278 | pass | 0/1 | - |
| web-start-after-modal-degradation | 边界语义·设置拾取时间弹窗对 manual 哨兵安全降级：对 a-manual-ready 行菜单点击「设置拾取时间」→ antd info 提示当前为待激活态（dayjs('manual') Invalid Date 不报错，start_after 不被清空）。出处：list.tsx:715-722、design.md 7.6 | pass | 0/2 | - |
| web-status-modal-activate | 交互流程·修改状态弹窗激活动作：对 a-manual-ready（ready + manual）点击「修改状态」→ 弹窗调度区显示「激活（立即调度）」按钮 → 点击确认 → start_after 变 null → 列表刷新后「待激活」Tag 消失。出处：SpecStatusModal.tsx:575-586、list.tsx:771。夹具：a-manual-ready(ready, start_after=manual) | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。


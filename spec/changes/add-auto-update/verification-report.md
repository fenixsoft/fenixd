# 验证报告：add-auto-update

> ⚠️ 本报告由框架于 2026-11-25T10:17:06Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-25T10:17:00.720330+00:00+run-result@mtime1795601825206531467

## 结论：✅ 通过（verified）

**状态：verified — 16/16 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 16/16 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 16 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.19M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| web-update-tab-panel-visible | 运维页 ?tab=update 预选更新页签：更新卡面板可见，含 fenixd 框架/dsh-plugins 插件描述项、「立即检查」动作按钮且点击不被拦截（出处 core/dashboard/static/src/pages/activities/index.tsx:1100、components/UpdatePanel.tsx:216） | pass | 0/7 | - |
| web-update-check-action-refresh | 点击「立即检查」触发 POST /api/update/check（expect_network），检查完成后更新卡刷新为已检查态：框架段显示源码形态标识（验证树无 VERSION 文件 → source 形态，出处 core/self_update.py:645 source 免远端查询） | pass | 0/4 | - |
| api-update-status-shape | GET /api/update/status 读侧契约（双形态）：200 + 结构完整——缺文件返回 never-checked 形态（checked=false + status_path/framework/plugins/apply），已检查返回 checked 形态（checked=true + 引擎持久载荷 schema/framework/plugins/last_check_at 等）（出处 core/dashboard/routes/update_routes.py:26-41） | pass | 0/2 | - |
| api-update-check-business-result | POST /api/update/check 同步检查业务结果契约：检查失败是业务结果而非 HTTP 错误——恒 200 + ok/status 字段（出处 update_routes.py:41-62）；框架边为 source 形态零网络交互 | pass | 0/3 | - |
| api-help-selfupdate-runbook | 帮助中心 self-update 排障 runbook 可达：GET /api/help/doc?name=13-self-update.md 返回 200 与文档内容（白名单含该文档，出处 core/dashboard/server.py:98、routes/help_routes.py:106-124） | pass | 0/3 | - |
| cli-update-check-sandbox-no-update | CLI check 沙箱验证（FENIX_HOME/DSH_HOME 隔离）：验证树 source 形态 + 无 dsh profiles → 零网络检查输出「已是最新（源码形态…）」且退出码 1（无更新），出处 bin/fenix_update.py:_cmd_check | pass | 0/3 | - |
| cli-version-compare-semantics | 语义化版本比较语义探针：compare_versions 数值逐段比较（v0.1.10>v0.1.7 非字典序）、is_update_available 双向判定、插件目录名 dsh-plugins-v0.1.2 解析为 v0.1.2（出处 core/self_update.py:276/296/203） | pass | 0/8 | - |
| cli-update-config-face | 配置面归一探针：load_update_config 默认值（enabled=true/interval_hours=24/mirror 空）、enabled=false 生效、类型非法回退默认不抛异常（出处 core/self_update.py:147） | pass | 0/8 | - |
| cli-inflight-run-preflight-probe | 在飞 run 预检判定探针：find_inflight_runs 以 .fenix/runs/*.jsonl mtime 判读（新鲜记录判在飞、超 6h 上界视为崩溃残留不误报、空项目零误报），出处 core/self_update_apply.py:274 | pass | 0/5 | - |
| cli-update-deliverables-docs | 文档与配置模板交付物在位：docs/help/13-self-update.md 排障 runbook、docs/install.md「更新与版本演进」章节、config.user.template.yaml update 段三键注释、docs/help/09-config.md update 键行（tasks 4.1-4.4） | pass | 0/6 | - |
| web-update-source-degrade-no-apply | 源码形态降级语义：更新卡显示「git pull 更新」指引文案，且不渲染一键更新按钮（data-testid=update-apply-btn 仅 artifact 形态渲染，出处 UpdatePanel.tsx:268/288） | pass | 0/3 | - |
| api-update-status-checked-after-check | 检查后状态落盘闭环：POST check 之后 GET /api/update/status 的 checked=true（run_check 落盘 status.json，出处 core/self_update.py:763 update_status） | pass | 0/3 | - |
| cli-update-status-sandbox-json | CLI status --json 沙箱验证：check 落盘后 status 输出引擎持久载荷（last_check_at 非空、last_error 为 null）且 framework.form=source——引擎载荷无 checked 键（checked 仅为 never-checked 兜底形态字段，出处 bin/fenix_update.py:94） | pass | 0/4 | - |
| cli-update-audit-trail-sandbox | 审计留痕沙箱验证：check 后 audits.jsonl 存在且含 kind=check 审计行（出处 core/self_update.py:607 append_audit） | pass | 0/3 | - |
| cli-update-apply-source-rejected | CLI apply 源码形态拒绝：验证树无 VERSION 文件 → apply 直接拒绝退出码 2 并提示 git pull，零编排副作用（出处 bin/fenix_update.py:_cmd_apply source 早退） | pass | 0/3 | - |
| cli-update-check-failure-path | 检查失败业务路径沙箱验证：伪造 dsh profiles 夹具（dsh-plugins-v0.1.2 link）+ 坏代理强制远端查询失败 → check 输出「检查失败」退出码 2（双腿全败静默留存原因，出处 core/self_update.py:762 失败计数与退避） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。


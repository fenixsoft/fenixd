# Tasks: add-spec-context-menu

## 1. 后端：优先级与软删除 API

- [x] 1.1 state_machine.py 新增 `remove_spec(name)`：read_all → pop → write_all 原子写回，不存在返回 False；补单元测试（tests/test_state_machine.py 或就近文件）
- [x] 1.2 data.py 新增 `set_spec_priority(project_root, spec, priority)`（校验 1-9、update_spec 写回）与 `soft_delete_spec(project_root, spec)`（remove_spec + shutil.move 到 openspec/changes/archive/<name>-<Unix秒>，目录缺失幂等，archive 同名冲突追加毫秒后缀重试；运行中检测=runs 目录该 spec run 文件 mtime<120s 返回保护错误）
- [x] 1.3 server.py 新增 POST `/api/spec-priority` 与 `/api/spec-delete` handler（仿 spec-error-clear 模式：project/spec 参数解析、400/404/409 语义），补 tests/test_dashboard.py 用例覆盖合法/非法/404/运行中拒绝四类

## 2. 后端：手动唤起 Admin 通路

- [x] 2.1 server.py 新增 POST `/api/spec-admin-invoke` handler：spec 存在性校验（404）、`.fenix/admin_invoke_request.json` 已存在则 409「已有进行中的 Admin 处置」，否则原子写入 `{spec, source:"manual", created:<ISO>}`，补测试
- [x] 2.2 fenixd.py 主循环新增拾取分支：存在请求文件→读取并删除→`agent_runner.run_administrator({"signal_type":"manual-intervention","spec":name,"severity":"major","description":"人工呼叫：检查 SPEC <name> 出现什么问题并尝试处置",...})`；调用异常时写 admin_store 记录不丢痕，补单元测试
- [x] 2.3 验证固定指令进入 prompt：`_build_prompt("x","administrator",detail={"signal_type":"manual-intervention",...})` 渲染包含检查任务描述与目标 spec（沿用现有 administrator 分支无需改动即通过）

## 3. 前端：右键菜单与三项交互

- [x] 3.1 app.js 新增全局 contextmenu 处理与自绘菜单组件（复用单例元素、视口翻转定位、Esc/click-outside/scroll 关闭）；style.css 菜单样式（--surface/--hairline 变量、明暗主题一致）
- [x] 3.2 「呼叫 Admin 介入」项：POST /api/spec-admin-invoke，成功 toast「已呼叫 Admin 介入检查」+ 触发 admin 活动区刷新；409 展示返回原因
- [x] 3.3 「调整优先级」项：prompt() 弹窗预填当前值，确认后 POST /api/spec-priority，成功后更新列表行显示（利用现有 2 秒轮询自然回刷即可）；取消无副作用
- [x] 3.4 「删除 Spec」项：确认弹窗（说明软删除与归档路径）→ POST /api/spec-delete → 成功后行消失；409 显示进行中提示

## 4. 验证

- [x] 4.1 全量 pytest 通过（tests/test_dashboard.py、test_agent_runner.py 及状态机新用例）
- [x] 4.2 playwright-cli 实测：右键弹出/关闭/边缘翻转三个 UI 场景 + 呼叫 Admin 端到端（真实拉起 admin run 且活动时间线可见）+ 优先级改写生效 + 删除软删除两处数据一致

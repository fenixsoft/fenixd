# 验证报告：evo-stuck-signal-hygiene

> ⚠️ 本报告由框架于 2026-09-15T09:50:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T09:50:03.586570+00:00

## 结论：✅ 通过（verified）

**状态：verified — 6/6 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 6/6 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 6 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.63M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| d1-process-alive-suppresses-stuck | D1 进程存活反证：运行 TestStuckProcessAlive 单元测试套件（7 case），验证 running_run_ids() 命中时不产 stuck 信号、无 runner 退回文件判据、-r<n> 后缀归属正确解析、异常容错（admin_monitor.py:806-818） | pass | 0/2 | - |
| d2-merge-signal-dedup-regression | D2 去重回归：运行 TestMergeSignalDedup 单元测试套件（3 case），锁定「冷却窗口内同 (spec, signal_type, status_hash) 只保留 1 条 signal 记录」行为，防 09-14 连发回退（admin_store.py:182 merge_signal） | pass | 0/2 | - |
| d3-disposition-silence-period | D3 处置后静默期：运行 TestDispositionSilence 单元测试套件（8 case），验证 resolved 暂不发信号、窗口外允许、escalated 不触发静默、partially-resolved 触发静默（admin_monitor.py:821-842） | pass | 0/2 | - |
| config-api-returns-stuck-silence-minutes | D4 配置读取：GET /api/config（无 project 参数，用户级）返回 admin.stuck_silence_minutes 键（默认 120），受管键白名单已接入（core/dashboard/data.py:3991、server.py:1235 read_config scope=user） | pass | 0/2 | - |
| system-panel-stuck-silence-visible | D4 Dashboard 界面：系统设置面板中「stuck 处置后静默期」输入项可见且默认值 120（SystemPanel.tsx:48-55 字段定义、:301-306 InputNumber 渲染；SPA 路由 #/settings app.tsx:111，default tab=llm settings/index.tsx:52 需切到「系统」页签） | pass | 1/6 | - |
| system-panel-stuck-silence-edit-save | D4 Dashboard 界面读写：修改 stuck 处置后静默期为 60 并保存成功，重新加载页面仍回显 60（data.py:3991 白名单写入、SystemPanel.tsx:225 提交 admin.stuck_silence_minutes、:201 初始值从 API 读回） | pass | 1/5 | - |

## 本轮场景集变更

当前稳定场景集共 6 个（第 1 轮）。

- 首轮写入 6 个场景


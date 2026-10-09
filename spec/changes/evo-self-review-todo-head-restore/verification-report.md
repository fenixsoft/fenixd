# 验证报告：evo-self-review-todo-head-restore

> ⚠️ 本报告由框架于 2026-10-09T19:35:16Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-09T19:35:15.311025+00:00+run-result@mtime1791574515345074860

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.41M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| todo-head-restore-api-fixture | 夹具供给（api 场景前置）：在 /tmp/todo-head-restore-fx-proj 造 git 夹具项目——先把基线台账「## 2026-10-08 …旧条目：基线内容」提交进 HEAD，再把工作树 .fenix/todo.md 整文件清空（2026-10-09 事故形态定格：HEAD 有内容而工作树空），以 fixture=True 注册进 Registry（ADR-163 夹具过滤，绕开人工告警聚合横幅）并轮询验证实例 /api/projects 确认可见。轮询经 FENIX_VERIFY_BASE_URL（框架注入，不硬编码实例地址）。出处 core/dashboard/registry Registry.add_project(fixture=True)。 | pass | 0/2 | - |
| r1-rescue-helper-four-states | R1 助手单测：_load_existing_with_head_rescue 六分支全覆盖——工作树有内容→逐字原样返回且无恢复 WARNING；空文件→返回 HEAD 基线且恢复 WARNING 恰一条（含「恢复基线」、恢复字节数、todo_head_restore=false 豁免提示三锚）；文件缺失→同型恢复；restore_enabled=False→按空基线返回且无任何恢复 WARNING；非 git 目录→git show 失败静默回退空串；git 仓库但 HEAD 无 todo.md→静默回退。真实 git 仓库夹具（/tmp），git show 走真实 subprocess（与 _commit_todo 同口径）。出处 core/self_review.py:1237-1283。 | pass | 0/5 | - |
| r1-append-todo-rescue-end-to-end | R1 主回写路径 _append_todo 四态端到端（真实 SelfReviewScheduler + 真实 git 夹具）：工作树空而 HEAD 非空→落盘内容=HEAD 基线+当日新节、恢复 WARNING 恰一条含字节数与豁免提示【验收1】；文件缺失→同型恢复；工作树有内容→增量追加、HEAD 基线不引入、无恢复 WARNING（行为与现状完全一致）【验收2】；todo_head_restore=false→按空基线写、无恢复 WARNING【验收3 豁免】。出处 core/self_review.py:2108-2186（_append_todo）、1475-1483（开关生效值）。 | pass | 0/5 | - |
| r1-skip-review-and-remove-resolved-rescue | R1 三处接入的其余两处同型复用：_skip_review 在空工作树上先自 HEAD 恢复基线、再在基线上落零活动占位节（基线与占位并存、恢复 WARNING 在案）；_remove_resolved 在恢复后的基线上按条目 id 匹配命中并重写移除（返回命中 id 清单、文件不再含该条目、恢复 WARNING 在案）。出处 core/self_review.py:1485-1537（_skip_review）、1876 起同型复用（_remove_resolved）。 | pass | 0/5 | - |
| r1-git-show-failure-falls-back-silently | R1 git show 失败静默回退且回写不阻塞（spec R1 第二条 SHALL）三形态：仓库无任何提交（HEAD 不存在）；HEAD 存在但其中无 todo.md（只提交过无关文件）；项目非 git 目录——三者 _append_todo 均按空基线写成功、当日新节落盘、不引 HEAD、无恢复 WARNING（台账写入主路径永不因防护而失败）。出处 core/self_review.py:1259-1283（OSError/TimeoutExpired/returncode!=0 全静默回退）。 | pass | 0/5 | - |
| r2-config-switch-tri-state | R2 豁免开关 config 语义（get_self_review_config）：缺省 todo_head_restore=True（清空丢历史是已兑现事故形态，防护默认在）；显式 False 生效；非 bool 值（"yes"/1/None）逐个回退缺省 True（严格 bool 范式，同 read_todo 既有范式）；R4 回归——read_todo 缺省 False、enabled 缺省 False、run_at 缺省 "02:00" 均不受本次改动影响。出处 core/config.py:2103-2140。 | pass | 0/5 | - |
| regression-new-test-suite-green | 验收5 前半：本 SPEC 新增测试套件全绿——python3 -m pytest tests/test_self_review_todo_head_restore.py -v --tb=short，锚定三态代表用例 PASSED（四态恢复 test_empty_worktree_restored_from_head / 端点持锁 test_post_acquires_todo_file_lock / 配置缺省 test_default_true）与「16 passed」汇总下限（防删测试/全 skip 的空洞绿灯）。-v 不与 -q 并列（pytest 9 中 -q 覆盖 -v 会吞 PASSED 行）。出处 tests/test_self_review_todo_head_restore.py。 | pass | 0/5 | - |
| regression-existing-suites-green | 验收5 后半：既有用例回归通过——python3 -m pytest tests/test_daily_self_review.py tests/test_self_review_todo_fallback.py tests/test_dashboard_todo_api.py -q，锚定「85 passed」汇总（实测计数照抄；-q 安静形态、不与 -v 并列，断言与输出形态一致）。test_dashboard_todo_api.py 直接覆盖 1.3 改动的 POST /api/todo 路径。出处 tests/test_daily_self_review.py、tests/test_self_review_todo_fallback.py、tests/test_dashboard_todo_api.py。 | pass | 0/2 | - |
| r3-api-todo-write-lock-roundtrip | R3 dashboard 端点写路径端到端（夹具项目 todo-head-restore-fx）：POST /api/todo?project=… 提交 Markdown 正文→200 且 ok=true、project 回显、path 为字符串；随后 GET /api/todo?project=…→200、exists=true 且 content 与提交逐字一致（整文件覆写经 with_file_lock 原子落盘、写后即读可见）。出处 core/dashboard/routes/base.py:641（POST /api/todo 路由）、core/dashboard/routes/settings_routes.py:440-483（_write_project_doc 持锁+INFO 留痕）、485-512（GET/POST handler）。 | pass | 0/7 | - |
| r3-api-todo-negative-inputs | R3 端点异常路径四例：content 非字符串（数字）→400 且 error 含「content 必须为字符串」；未知项目名 POST→404 且 error 为 project not found；未知项目名 GET→同判 404；缺 project 参数→400 且 error 含「缺少 project 参数」。错误响应为 JSON（ensure_ascii=False，中文断言确定性命中）。出处 core/dashboard/routes/settings_routes.py:497-512、core/dashboard/routes/project_routes.py:193-206（缺参 400/未知 404 共用校验）。 | pass | 0/7 | - |
| r3-api-todo-empty-overwrite-nonblocking | R3 覆空留痕不回退语义：POST /api/todo 提交空 content→200 且 ok=true（覆空 WARNING 留痕尽力而为、不阻塞保存，dashboard 以 UI 提交内容为准）；GET 回读 exists=true 且 content 为空串——覆空生效、不被 R1 恢复逻辑回退（dashboard 侧只留痕不回退，与 daemon 回写前自愈的「恢复回写」语义可分辨；HEAD 基线仍在 git 中可追）。出处 core/dashboard/routes/settings_routes.py:103-127（_warn_if_todo_overwrite_empties）、440-483。 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景


# Tasks: add-task-progress-sync

## 1. 解析函数共享化

- [x] 1.1 将 `core/dashboard/data.py` 的 `_parse_run_task_done` 解析核心提升为可复用公有函数（保持 memo 缓存与容错语义），dashboard 与 pm_engine 共用；`data.py` 内部调用点改为引用共享版本
- [x] 1.2 新增/扩展单元测试：run 产物含 TaskCreate subject id + TaskUpdate completed 时返回正确 done_ids；subject 无 id 时 flat 回退；文件缺失/损坏时返回空集不抛异常

## 2. daemon 写侧回写

- [x] 2.1 在 `core/pm_engine.py` implementer run 终态为 success 的处理路径新增回写调用：解析 done_ids → 将主树 tasks.md 对应 `- [ ]` 改 `- [x]`（只增不减）→ 以 `[fenix] <spec>: sync task progress from run record` commit
- [x] 2.2 回写幂等与安全：已勾选跳过、无 run 产物或空 done_ids 跳过、工作树不干净时跳过并留待下轮、任何异常不阻塞 run 终态主流程
- [x] 2.3 单元测试：模拟 run success 后 tasks.md 被正确勾选并 commit；二次执行无新 commit；agent 已勾选内容不被撤销；脏工作树时跳过

## 3. verified→done 一致性门禁

- [x] 3.1 在 `_on_spec_verified` 转换前新增一致性校验：run 声明 success 但存在「未勾选且不在 done_ids」任务时，阻断 verified→done 与 auto approve，error 字段记录缺口任务清单，SPEC 保持 verified
- [x] 3.2 全部任务确认完成（勾选 ∪ done_ids 覆盖全部）时门禁放行；无 run 记录可查时放行（无法证伪即放行）
- [x] 3.3 单元测试：缺口任务阻断且 error 内容含任务 id；全覆盖放行；fix-* SPEC 同规则生效

## 4. 集成验证与打包

- [x] 4.1 运行全量 pytest（`python3 -m pytest tests/ -q`）确认无回归
- [x] 4.2 端到端验证：构造一个含 2 个任务的测试 SPEC，跑通 implementer success → 回写勾选 → verified 门禁放行链路；再构造缺勾场景验证阻断
- [x] 4.3 运行 `bash scripts/package.sh` 生成最新扩展包

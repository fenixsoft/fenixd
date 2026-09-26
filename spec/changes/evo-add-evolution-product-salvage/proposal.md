# 提案：自进化分析产物抢救兜底

## 背景与问题
自进化分析 run 的产物 out-<run_id>.json 由子代理按 agents/evolution.md 的分片写入契约写出（.json.parts 机制是纯提示词约定，框架零参与），框架在 run 进程结束后才读：core/agent_runner/maintenance_runs.py run_evolution 在 if run_ok: 门控下 read_contract（:797-806），而 finally 块（:829-838）无条件删除产物文件——CLI 非零退出时，即便子代理已写完产物也会被静默删除且从未解析。read_contract（core/evolution.py:1867-1914）把「文件不存在」与「JSON 非法」折叠成同一 ContractError（:1884-1885），失败归因不可分辨。当前日志窗 evolution run 10 条败 3 条（fenixd.log:26006/:26013/:10155），每败一次整轮分析报废（正常一轮约 28 分钟），只能靠 5 分钟检查点自然再派重跑。

## 目标
1. run 失败也先抢救再删：run_ok=False 时先尝试读产物；产物缺失时若 .parts 分片非空则按既有合并配方恢复后再读；恢复出可解析契约即按成功落地（附 INFO 说明 CLI 退出异常），确无产物可救才清理，清理范围含 .parts 残片目录；
2. 失败归因分级：「产物文件未写出」与「产物 JSON 非法」拆成两个可判别的错误文案；
3. 提示词契约改增量合并：每写完一条分片即并入产物，任意中断点的最大损失从整轮降到单条。

## 非目标
- 不给 evolution run 加进程级重试/退避/上限（现有 5 分钟检查点自然再派已实测有效，本轮与 09-22 的补回均由它完成）；
- 不做 unrecognized_model stderr 关联排查——核查已给出反例定论（成功 run 同样含该 stderr；core/agent_runner/runner.py:4886-4890 已定性为无关逐请求噪声），该悬念关闭。

## 代价与风险
- 改动集中在 run_evolution 收尾段、read_contract 错误分支与 agents/evolution.md 契约文本，量小；
- 抢救合并复用 agents/evolution.md 既有合并配方（sorted(glob) 拼 items），分片为每文件单条目自包含 JSON，框架侧复刻无障碍；
- 边界须如实声明：已观测两条失败 run 的分片目录为空、无片可救——抢救只救「已写分片未合并」与「写完产物 CLI 才败」两类，是兜底而非全防。
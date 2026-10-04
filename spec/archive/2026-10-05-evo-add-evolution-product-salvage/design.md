# 设计

## 改动点
1. core/agent_runner/maintenance_runs.py run_evolution（:710-848）：
   - 新增私有 helper _salvage_evolution_out(out_path)：out_path 不存在**或 read_contract 对其报「JSON 不可解析」**（增量合并按分片反复重写 out，覆盖写瞬间的截断半写窗口恰在 out 已存在时）且 {out_path}.parts/*.json 非空时，按 agents/evolution.md 合并配方 sorted(glob) 拼接写回 out_path；已知 len(pending_entries) 时与合并条目数对比；
   - :783-806 收尾段重排：无论 run_ok 先做抢救再 read_contract；read_contract 成功且恢复条目数与 len(pending_entries) 一致（或未知）而 CLI 非零退出时按成功落地并落 INFO；**部分恢复（条目数不足）按失败落地——success=False、缺失数入 error，MUST NOT 触发水位推进**（fenixd worker fenixd.py:3546-3569 在 success 时对全部 ready_projects advance_watermark(snapshot_at)，部分成功推进会把未分析条目永久跳过到水位之外；已落地条目由 ingest_item 幂等去重由下轮检查点补齐，见 maintenance_runs.py:818 既有注释）；
   - :829-838 finally：删除动作移到「确认无产物可救」之后，范围扩到 {out_path}.parts/ 目录（止住已观测的残片目录垃圾）。
2. core/evolution.py read_contract（:1867-1914）：:1884 OSError 分支前显式存在性检查，拆分「产物文件未写出」与「产物 JSON 不可解析」两个 ContractError 文案。
3. agents/evolution.md 分片写入节（:157-207）：合并步骤改增量合并——每写完一条分片立即并入最终产物（写一条并一条），替代「最后一次性合并」；保留结尾全量校验步。

## 复用与边界
- 合并配方与 lint 单源：分片为每文件单条目自包含 JSON，合并/校验照 agents/evolution.md 既有脚本形态，框架侧可用 core/deliverables.py 同源 lint 校验恢复产物；
- 抢救边界如实声明（评审实测勘误）：日志窗三例失败 run 中两条（evo-1790361035、evo-1790363139）.parts 目录为空（死在逐条目子代理核查阶段、分片写出之前），抢救救不了这类；第三条 evo-1790079811 留有 3 个可解析分片（.fenix/evolution/out-evo-1790079811.json.parts/，逐文件 json.load 通过、含 project/date_section/section/id），属「已写分片未合并」类——抢救的直接历史受益案例。价值即在这两类，增量合并则把未来中断的损失压到单条；
- 重派机制不动：水位不推进 + 5 分钟检查点自然再派（fenixd.py:3532-3577、core/evolution.py:381-463）已实测有效，不加退避/上限。

## 备选与否决
- 给 evolution run 接入 runner 既有瞬断重试循环（runner.py:2159）：evolution 直调 _run_claude（maintenance_runs.py:772）不经 _execute_agent_inner，接入需动调用形态，且检查点再派已等效，不做；
- unrecognized_model 关联排查专项：核查已给出定论（成功 run evo-1790393159 事件流同样出现该 stderr；框架 _denoise_stderr 已定性无关，runner.py:4886-4890），无需立项。

## 测试
新增 tests/test_evolution_product_salvage.py：产物已写但 CLI 非零退出、产物缺失有分片可合并、产物与分片皆空、分片条目数不足四类场景；回归 read_contract 文案分级。
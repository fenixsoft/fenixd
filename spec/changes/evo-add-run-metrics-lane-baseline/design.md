# Design

## 上下文

core/self_review.py：MIDFLIGHT_OUTLIER_MULTIPLIER=3（:690）、MIDFLIGHT_MIN_GROUP_SAMPLES=3（:694）、_metrics_outlier_dims（:777）、_collect_metrics_outliers（:791，分组键 agent_type or "unknown" :826-827、组中位 :830-844、越线 :848）、第六节渲染（:1484-1486/:1526/:1534）。数据源缺口：_log_run_metrics（runner.py:8123）仅 _execute_agent 家族路径调用（runner.py:1260/3632/3689/3707/4449/4621/4663/4698/4838）；maintenance_runs.py 三车道 run_evolution（:923）/run_code_review（:1408）/run_code_fix（:2471）零调用且无 _execute_agent 路径（runner.py:661-663 注释）；context metrics 兜底行（runner.py:6429-6456）无 agent_type/terminal/cost_usd 且被 core/dashboard/data/runs.py:71-103 按 run_id 覆盖式写入。前缀表：core/agent_runner/run_files.py RUN_ID_AGENT_PREFIXES（:37，注释 :31-36 明示「新增 run 前缀只改这里」）与 infer_run_agent_type（:56，evo- 目前无前缀条目回退 "agent"）。成本台账：maintenance_runs.py:2060-2068/:1353 已有结构化台账写入。既有测试：tests/test_self_review_midflight.py TestMetricsOutliers（:169）、_append_metric helper（:97，现固定 agent_type="implementer"）。

## 方案

1. 读侧兜底（最小改动恢复七车道分组）：_collect_metrics_outliers 分组键优先 metric.agent_type，缺失时 infer_run_agent_type(run_id)[0] 推断（run_id 恒可得）；RUN_ID_AGENT_PREFIXES 补 ("evo-", "evolution")（注意 evo- 无子串冲突），该表为唯一真源、dashboard/get_runs 同源受益，须回归时间线归属。消费方核对以全仓引用为准（不止 dashboard/get_runs）：dashboard/data/runs.py get_runs 时间线归属（agent→evolution，预期修复）；run_files.run_spec_part——evo-<epoch> 剥时间戳从伪 spec「evo」变为裸 epoch 段，两侧均不等于真实 spec 名，全等守卫不变；admin_monitor 驱动判定（:785-791，两侧均 False）与 _merge_admin_runs 归一（两侧均 None）；pm_engine._cancel_lane_runs/_spec_has_recent_run_activity——evo-<epoch> 不携带 spec 段，glob/全等守卫不新增命中；前端 IntroduceRow.tsx AGENT_CATS 值域归族——「agent」与「evolution」同落「其它」，展示不变。
2. 数据源补齐（二选一，消除成本失明）：写侧——maintenance 三车道收尾补 _log_run_metrics 富指标行（含 agent_type/cost_usd），context metrics 兜底行补 agent_type（可得时补 cost_usd）；或读侧——初筛对无成本样本的行交叉读 .fenix/cost/*_tokens.json 台账。优先写侧（一次写入多方受益），读侧为兜底。
3. 车道基线降噪：code-fix 等批量相关车道 turns 基线改用组内近期批分布（如同链/近 N 批 P90，样本不足回退窗口中位）；定向重试轮单独标注或排除出基线样本。参数约定：基线默认取同车道窗口内最近 N=10 个有效批（不含当前 run，按时间倒序）；有效样本 < MIDFLIGHT_MIN_GROUP_SAMPLES 回退窗口中位；「同链」为可选增强（run_id 可解析 spec 段时优先），不作为默认依赖；重试轮辨识沿用既有 run_id 后缀约定（-r<n>/-a<n>，与 core/dashboard/data/runs.py 剥后缀同口径），无后缀不可辨时不排除、保守入基线。注意实测：仅分组（组内中位 49×3=147）消不掉本窗口旗标，本步是降噪主力。
4. 明确不动：越线倍数（3）与最小样本（3）常量、第六节渲染格式、evo-split-self-review-stderr-noise-count 的 stderr 计数口径（同节协调顺序落地）。

## 测试与验收

- tests/test_self_review_midflight.py：无 agent_type 指标行 + code-fix/evo/spec-review 混合窗口的分组断言、evo- 前缀推断断言、组内样本 <3 跳过语义、P90 基线与重试轮标注用例、成本维度对台账交叉读取用例。
- run_files.py 前缀表变更的 dashboard/get_runs 时间线归属回归。
- 验收：落地后复核一个完整窗口第六节清单——code-fix 旗标噪音率显著下降（基线 12/12 全误报）、真实离群（evo-1791224502 型）仍在榜且不被同车道噪音稀释。
- 回滚：读侧兜底与前缀表为纯增量，回滚即恢复原分组键行为。
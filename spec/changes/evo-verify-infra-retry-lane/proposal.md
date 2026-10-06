## Why

cfc 系模拟器验证场景两天内反复触发环境类全价处置：10-05 admin 600 轮诊断 run 被击杀（admin-pack2-official-encoder-1791196033，exit_code -9）、10-06 env 豁免+2 条告警+admin run $1.50，豁免后 4 轮 planner-judge 合计 $4.59 中间两轮仍因该场景环境问题未一次收敛。核查证实框架的验证环境失败只有一条全价通道：prepare/可达性 fail-fast（core/pm_engine/verification/pipeline.py:2119-2130）与场景执行后分类（core/verify_engine/env_gate.py:151、engine.py:570）最终都汇入 _escalate_env_blocked（escalation.py:550，2 轮冻结阈值 state_machine.py:288）→ admin 自动呼叫 → 冻结；唯一 infra 让步是预算退款（infra_classify.py:142），「infra-retry 廉价重试」在 core/ 与 tests/ 零命中。同时预检本体不需要框架改动：run_prepare_steps（core/verify_contract.py:1158）已支持任意 shell 步骤+600s 步超时+主机锁，宿主预检（残留 qemu/AVD 清理、内存水位、场景特异冒烟探针）可作项目 verify.yaml prepare 步骤表达——缺的只是「预检失败→廉价重试」车道。

## What Changes

1. infra-retry 车道：prepare 失败/可达性 fail-fast（0 场景执行即短路）不再直接走 _escalate_env_blocked，改判 infra-retry——不计 env 冻结轮、不呼叫 admin，按 infra 失败台账限次（缺省 2 次）直接重派验证；超限恢复既有全价升级。
2. 预检样板：core/verify_contract_template.yaml prepare 段补宿主预检示例步骤（注释形态：无主 qemu/AVD 清理、资源水位、场景特异冒烟），供项目按需启用；首个试点为 potplayer-base cfc-injection-fallback（项目侧 prepare 步骤，不在本 SPEC 交付物内）。

## Out of Scope

- 不改场景执行期 env 阻塞的后置分类语义（env_gate/engine 探针分类不动，本 SPEC 只收口 prepare/fail-fast 短路路径）。
- 不做框架级「自动杀无主进程」执行器（同轮孤儿模拟器条目核查指出与 evo-add-host-change-governance 非目标存在张力，清理动作留在项目 prepare 步骤内由项目自治）。
- 不动 env 豁免/冻结语义与 admin 升级阈值。
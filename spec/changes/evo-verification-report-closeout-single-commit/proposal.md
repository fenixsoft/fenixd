# Why

验证裁决采纳收尾对 `spec/changes/<spec>/verification-report.md` 固定产生两次提交：报告闸门提交报告本体后，场景集变更段在采纳尾段追加并二次提交。两次提交同秒、同一文件、同一消息模板「[fenix] <spec>: verification-report 入库」。2026-10-10 凌晨三个 evo spec 收尾 3/3 全中（d25ea5ca/fc10ec42 03:35:16、ebc92e8b/8b02de71 03:25:54、f495d7df/0eb04a5d 03:23:49），属系统性形态：每个验证采纳必多发一次 git 提交流水，并给版本历史溯源多加一层同模板提交。两笔提交本就复用同一提交器（core/verify_report.py 的 _commit_verification_report），场景段渲染数据（_last_scenario_diff / scenarios.json）在闸门时点已就绪，且报告内「本轮场景集变更」标题幂等判定天然消化末尾渲染点——合并为单次原子提交是小而确定的流水线去重。

# What Changes

1. `ensure_verification_report`（core/verify_report.py）增加可选 pre-commit 回调参数（默认 None，签名向后兼容）：present / resynthesized / synthesized 三个放行出口均在 `_commit_verification_report` 调用前执行回调；回调异常仅落 WARNING、不阻断放行（对齐现有「git 失败仅 WARNING」失败语义）。
2. `_ensure_verification_report`（core/pm_engine/verification/report_gate.py）注入场景段渲染回调（函数内延迟导入 core/pm_engine/verification/scenario_gate.py 的 `_render_scenario_change_section_to_report`，项目既有防循环导入惯例），覆盖 pipeline._apply_verified / _apply_bug_found 与 legacy 两处共四个采纳调用点——闸门单次提交即含报告本体与场景段。
3. pipeline.py `_apply_verified`(:1408) / `_apply_bug_found`(:1232) 的末尾渲染点保留为兜底：报告已含场景段标题时按既有幂等判定（scenario_gate.py「标题已存在即跳过」）零成本跳过，不再产生第二次提交。
4. push 收口（approve_push 直调 `_commit_verification_report`）与渲染函数直调路径行为不变。

# Impact

- 提交数：每个验证采纳从 2 次降为 1 次（首次即含场景段）；历史滞留报告与未入库场景段仍由归档兜底，不做主动回填（沿知识库现行规则）。
- 语义说明：合并后若闸门放行后 transition 被 TOCTOU 拒绝（冻结/并发接管），场景段已随闸门提交入库——场景段内容是场景集事实（scenarios.json 于冻结轮写回、与采纳结果无关），与现状「报告本体已入库、场景段后补」等价，无回滚必要。
- 知识库页 spec/knowledge/domains/verify-pipeline/verification-report.md 的「场景段写盘即入库」「入库挂点链」规则同步改写（闸门前合并渲染、额外提交归零）。
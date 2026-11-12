# ADR-355：场景修复语义保持判定走确定性 diff 分类器，拒绝 LLM 复核

date: 2026-11-12
status: accepted

## Context

处置黑名单 B4（验证契约放宽）需要机械判别「场景修复是否弱化验证契约」。候选方案：LLM 复核修复语义 vs 确定性断言集 diff 分类。机械门的守卫价值前提是可复现、可测试——LLM 复核不可复现即不可守卫，且同样暴露于模型漂移。

## Decision

语义保持判定走确定性 diff 分类器纯函数（`core/verify_engine/scenario_semantics.py` 的 `prove_scenario_fix`）：输入修复前后场景集 JSON，逐场景逐断言三分类（收紧 tighten/放松 relax/中性 neutral），场景删除按 relax 计，存在未获准 relax 即净放宽拒绝；relax 获准走机器可校验正当性码白名单（闭合集合，首码 `global-counter-nondeterministic`）；拆除禁项违规步骤并以机械形态断言替换的 B1 合规化改写判中性（carve-out）。不做自然语言级「证明」，只做确定性断言集 diff 分类。

## Consequences

判定精度受限于断言集 diff 的机械形态，语义等价但形态变化的合法修复可能被误拒——由人工兜底吸收（降级保留人工，多一次人工不损可用性）；误放行面由 relax 默认拒、正当性码白名单闭合与双向 fixtures 守卫测试收敛。后续任何「修复是否弱化契约」的机械判定一律沿用确定性分类器形态，引入模型判定须显式推翻本裁定。

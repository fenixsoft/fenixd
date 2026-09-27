# ADR-099：implementer 终态零提交门，rmtree 前引用式快照

date: 2026-09-17
status: accepted

## Context

模型末轮输出格式回退（text 块内嵌完整假工具调用）时 run 自然收工：exit 0 + 合法结果文件 → success → worktree 清理，`git worktree remove` 遇 untracked 拒删后 fallback 硬删未提交现场（仅一条 WARNING）。成功判定不看分支提交，零变更哨要求零提交且零编辑调用（有编辑即放行），交付物守卫时点在毁灭后必然缺件——整轮重做（实测 32-36min/轮）。

## Decision

- implementer「正常终态 + 分支零提交（rev-list count == 0，与零变更哨同式）+ worktree dirty」在 cleanup 之前拦截为可恢复错误：复用产物硬门异常通道（写重试记录 → WIP 检查点提交 → 原地退避 → 同 worktree resume 续做，分钟级收尾），不新增重试机制。门 fail-open：rev-list 失败即放行，绝不因门自身故障打断正常收口。
- 判定顺序 = 先门后 cleanup，复用成功路径已取证的 dirty 快照，零新增 git 调用（rev-list 一次除外）。
- 机械归因零 LLM：读 run 转录末轮 text 特征（XML 假工具调用 / markdown 代码块内工具形态）→「格式回退截断」，否则「未提交即收工」；纯正则，归因只进 error 文案不影响处置路径。
- 门触发不计入全局瞬断指纹——格式回退/忘提交不是网关问题，计入会污染 dispatch 闸门对瞬断风暴的可见性（实现允许保守多计但须注释声明误差方向）。
- rmtree fallback 前留档用 `git stash create` 引用式快照（不入 stash 栈、零副作用、可随时 store 转正），SHA 记日志；对全部 agent 类型生效（verifier 的 untracked 同款暴露），失败 WARNING 降级不阻断。
- 备选否决：stash 快照 + 直接重派（整轮重做且需现场交接协议）；LLM 归因（烧钱且慢，机械特征已足够）；不留档直接删（毁灭后 dispute 只能靠转录间接取证）。

## Consequences

- 零提交死法在 cleanup 前被拦截：resume 从「正要 commit」处继续，思考链、任务清单、会话上下文全保留。
- 合法零提交轮（整轮只分析不写盘）dirty 为空天然不拦；gitignored 产物不进 dirty，同样不拦。
- 第二次门触发继续退避续做；原地预算耗尽后 worktree 保留供认领续做，最坏仍优于整轮重做。
- WIP 提交进 merge-back 历史由既有塌缩机制收口，主树历史无 wip 残留。

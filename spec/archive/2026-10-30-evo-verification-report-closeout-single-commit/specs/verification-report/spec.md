# 验证报告收尾单次提交

## 需求 1：闸门 pre-commit 回调挂点

 SHALL：`ensure_verification_report` 接受可选回调参数，默认 None；present、resynthesized、synthesized 三个放行出口均在执行 `_commit_verification_report` 之前调用该回调（报告文件已在盘/已合成落盘后）。回调抛出异常时 SHALL 仅落 WARNING 并继续提交与放行，不改变放行结论。

## 需求 2：场景段渲染并入闸门提交

 SHALL：`_ensure_verification_report`（report_gate.py）把场景集变更段渲染回调传入闸门，使闸门放行时的单次提交同时包含报告本体与「本轮场景集变更」小节。回调注入 SHALL 使用函数内延迟导入（模块边界惯例）。四个采纳调用点（pipeline._apply_verified、pipeline._apply_bug_found、legacy 两处） SHALL 全部生效。

## 需求 3：幂等与既有路径不回归

 SHALL：闸门已合并提交后，采纳尾段的既有渲染点因报告已含「本轮场景集变更」标题而跳过，不产生第二次提交、不落 WARNING。SHALL：push 收口直调 `_commit_verification_report` 的入库、场景段渲染函数被直调时的「写盘即入库」行为、pathspec 严格单文件约束、非 git 项目静默跳过、git 失败仅 WARNING——均维持现状不变。

## 需求 4：知识库同步

 SHALL：spec/knowledge/domains/verify-pipeline/verification-report.md 改写「场景段写盘即入库」与「入库挂点链」两条规则：场景段渲染合并进闸门 pre-commit 挂点、采纳流程内报告相关提交至多一次；溯源段补记本 spec。

## 验收

1. 真实 git 临时仓全链用例：synthesized 与 present 出口下，闸门放行后 HEAD 恰一次新提交，`git show HEAD:<报告路径>` 同时含报告本体与「本轮场景集变更」；`git status --porcelain` 不再滞留报告。
2. 闸门放行后模拟采纳尾段二次渲染：提交计数不增、WARNING 零新增。
3. 场景段渲染抛异常：闸门仍放行、报告本体照常入库、WARNING 恰一条。
4. pathspec 隔离回归：其它 spec 在途 staged 草案与无关文件修改不被卷入闸门提交。
5. push 收口与直调渲染既有用例全绿（tests/test_push_closeout_report_commit.py、tests/test_verification_report_commit.py 既有用例不回归）。
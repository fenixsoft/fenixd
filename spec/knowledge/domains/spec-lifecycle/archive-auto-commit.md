# 归档产物自动提交
<!-- knowledge: capability=archive-auto-commit rev=1
     sources=spec/archive/2026-09-10-run-lifecycle-hardening -->

daemon 在 push 流程尾部把主树里的归档移动残留以独立提交收口并推送，避免归档目录长期滞留工作区。

## 规则

- spec done 的 push 流程（main-first）完成代码推送后，daemon 检查主树是否存在 `spec/changes/` 下的归档移动残留（被归档 spec 目录的删除项 + `spec/archive/` 下未跟踪/已修改的新增项，含更早 spec 的残留）。
- 存在残留时，以独立提交收口：一个 commit 包含全部归档移动，提交信息格式 `[fenix] archive: <spec-name> 等归档入库`，并在代码 push 之后追加 push；提交后 `git status` 对 `spec/` 路径干净。
- 无残留时零动作：不产生空提交、不产生多余 push、日志无归档提交记录。
- 提交内容限定：只含 `spec/changes/` 路径下的变更（删除项 + archive 新增项），不夹带工作区其他未提交改动（源码、`STATE.md` 运行时文件等留在工作区）。
- 提交失败（git 冲突、hook 拒绝）时记 WARNING 日志并继续既有流程，spec 保持 done/pushed 终态，残留留给下一次 push 流程重试；不得将 spec 打回或置 blocked。

## 溯源

- [2026-09-10 2026-09-10-run-lifecycle-hardening](spec/archive/2026-09-10-run-lifecycle-hardening/) — 新增归档移动随 push 自动提交：残留检测、独立提交与内容限定、失败不阻塞主流程

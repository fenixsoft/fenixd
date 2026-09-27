# ADR-064：merge-back 语义冲突在只读预演点拦截，直通 repair 不烧熔断记账

date: 2026-09-11
status: accepted

## Context

merge-back 语义冲突只有在真合并（stash 收拢 → merge → abort）之后才被发现：主树要经历全舞蹈才能回滚干净，而调度层失败分支先做冲突指纹记账再路由 repair——一次可修复的语义冲突就消耗熔断额度、触发 ready 降级与整轮重派。冲突检测存在更早、零污染的可行点。

## Decision

- merge_back 内置**只读预演闸**：`git merge-tree --write-tree` 在 guard 锁内、stash 之前执行，不触索引与工作区；冲突路径复用既有产物前缀语义分类。
- 预演命中语义冲突 → 不执行真合并，构造带预演标记的冲突信息**直通 repair 通道**：跳过冲突指纹记账、不做 ready 降级，spec 保持 in-flight。主树未被扰动，「merge 失败」在熔断语义上并未发生。
- 预演闸单点收口在 merge_back 内部，全部调用路径自然覆盖；调度层只消费预演标记。
- git 版本不支持预演 → 探测失败记一次 WARNING，预演闸永久跳过，行为回退真合并路径。
- repair 后 re-merge-back 的真失败仍走冲突指纹熔断，语义不动——那是真合并失败。

## Consequences

- 语义冲突的修复成本从「熔断记账 + 降级重派 + 真合并回滚」收敛为「零污染拦截 + 定向 repair」；直通 repair 绕过熔断由 repair 轮次上限与 remerge 失败链熔断兜底，闭环仍成立。
- merge-tree 与真合并同用 merge-ort 引擎，冲突判定一致性高；预演放行后真合并仍可能失败的残余差异由既有 abort + 熔断路径兜底，不丢安全性。

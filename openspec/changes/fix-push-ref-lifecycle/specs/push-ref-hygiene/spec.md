# spec-push-ref-hygiene

## ADDED Requirements

### Requirement: main 为主交付物推送
done→pushed 的自动推送 SHALL 以 `git push origin main` 为成功判据；远端 main 不存在时视为首次创建成功；非 fast-forward（远端分叉）时 MUST 判定失败并升级人工，禁止自动 force。feature 分支推送为尽力而为的留痕动作，其失败不影响 pushed 判定。

#### Scenario: 正常推进
- **WHEN** 某 spec done 且远端 main 可 fast-forward
- **THEN** main 推送成功，spec 推进 pushed，error 字段为空

#### Scenario: 远端分叉拒绝自动覆盖
- **WHEN** 远端 main 含本地不存在的提交
- **THEN** 推送判定失败，发出 push_failed 信号，不执行 force

### Requirement: remote-aware 去重
推送 feature 分支前 SHALL 以 `git ls-remote` 比对远端 SHA：与本地一致 → 视为已推送成功；不同 → 跳过分支推送并 WARN；远端不存在 → 正常推送。本地分支不存在时 SHALL 跳过分支推送（不产生 refspec 错误），以 main 推送结果为准。

#### Scenario: 重复推送零副作用
- **WHEN** 对远端已存在且 SHA 一致的分支再次触发推送
- **THEN** 无 push 命令发出（或发出即被去重短路），判定为成功，无 ERROR

#### Scenario: 本地分支已清理
- **WHEN** merge-back 后本地分支已删除、触发推送
- **THEN** 无 refspec 报错，main 推送承载内容

### Requirement: 失败退避收敛与升级
push 失败的 done spec SHALL 按指数退避（`pm.push.retry_backoff_seconds` 默认 [300, 900]）延迟重试，退避期内 recovery 重放 MUST 跳过；连续失败达 `pm.push.max_retries`（默认 3）后停止自动重试并发 push_failed 困境信号（severity=major）。

#### Scenario: 退避期内重放被跳过
- **WHEN** push 失败后 5 分钟内 recovery 再次触发 verified→done 重放
- **THEN** 不发出 push 命令，日志记录退避等待

#### Scenario: 超限升级
- **WHEN** 连续 3 次推送失败
- **THEN** 不再自动重试，admin_alerts 出现 push_failed 信号

### Requirement: 终态残痕清理
推送最终判定成功（含 SHA 去重判定）时 SHALL 清除该 spec 的 error 字段；系统 SHALL 提供幂等回填清理：pushed 终态且 error 以 "git push failed" 开头的记录经 SHA 比对验证内容已在远端后清除，验证不到的保留并列日志清单。

#### Scenario: 去重成功即清痕
- **WHEN** 推送经去重判定为已推送
- **THEN** error 字段清空

#### Scenario: 存量残痕回填
- **WHEN** 执行回填清理
- **THEN** SHA 可验证的 pushed 残痕被清除，不可验证的保留并输出清单日志

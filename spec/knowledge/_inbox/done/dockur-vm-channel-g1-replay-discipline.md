# dockur 过机 G1 全量重验的通道与判据纪律

## 结论

windows-native-support 7.3 冻结（G1-01~23 unattainable）的根因是通道选型错配而非环境真缺：dockur RDP 凭据是 `docker run -e USERNAME/PASSWORD` 一次性注入，无法事后读取；cloud-phone 实测姿势（noVNC + SMB 离线注入）从不依赖 RDP 凭据。解法=按 win-vm skill 标准姿势重建 win-test 容器（SSH 127.0.0.1:22222 直连，密钥 ~/.ssh/winvm_admin，`wr.sh` 需 `export HOME=/root`），Guest 内访问宿主代码统一 UNC `\\host.lan\Data\...`（Z: 盘映射是 per-logon-session 的，net use 不持久）。

## 过机复验铁则（round 实证）

1. **过机测试发现的缺陷 Linux 侧全绿是常态**：25 项 G1 里 6 处产品缺陷全部只在此通道暴露（/proc 只读、cp1252 print、DWORD 有符号/无符号、NSSM 参数表、stdout 编码、UNC 长路径）。任何"Linux 全绿所以没问题"的结论必须过机复验后才可信。
2. **原生 exe 输出编码不可正则判**：NSSM 原生输出 UTF-16LE，PS 管道捕获即乱码（`S E R V I C E ...`），判态用 `Get-Service`（SCM API）等价替代。
3. **ps1 含非 ASCII 必须 UTF-8 BOM**（PS5.1 否则按 GBK 解析吞引号 ParserError）；且 host 端编辑工具会剥 BOM——每次编辑后必须补 BOM 并 xxd 验证，双 BOM 会让 PS 把第二个当乱码秒死。
4. **SMB 陈旧窗口**：host mv 新 inode 后 Guest SMB 客户端秒级缓存旧内容——host 改 ps1 后等 ≥15s 或先 Guest 探针核对再起跑；同理 log rm+立即 UNC 重定向有 "The parameter is incorrect." 竞态。
5. **Windows OpenSSH 每会话一个 Job Object**：wr.sh 返回即整树秒杀 Start-Process 子进程；长活进程用 WMI 代生（`Invoke-CimMethod Win32_Process Create`）。
6. **PYTHONIOENCODING/reconfigure(errors="replace")** 是 SSH/非控制台会话里中文输出的通用解（cp1252/GBK 控制台会因 UnicodeEncodeError 直接崩掉整链）。
7. **NSSM 2.24 实际参数表**：无 AppStdoutCreationBytesToPreserve；AppExit 需双子参（`AppExit 0 Restart`）；`nssm install <name> <exe>` 已钉 Application，AppParameters 再带解释器会得到 `python python script`（python 吃自身 MZ 头秒退→节流 SERVICE_PAUSED）。
8. **回填纪律**：SKIP 必须附环境阻塞证据；「环境依赖」归因必须先排除通道选型错配（本例：G1-16~23 命令面实为纯本地，原 LLM 凭据归因不成立）。

## 证据

- 过机日志 /root/win-vm/g1-full8.log（round8: PASS=25 FAIL=0 SKIP=0 + pytest 门 8 passed/99 skipped/0 failed）
- 清单执行记录 tests/integration/windows/g1_full_parity_checklist.md（25 项逐项 PASS + 证据路径）
- 修复集：win32.py（AppParameters/Disposition/AppExit/DWORD 归一）、dashboard/server.py（_proc_starttime/_is_process_alive 委托 pal 后端）、fenixd_supervisor.py（ctypes proc_starttime + reconfigure）、install.ps1（find_spec 静默探测）、bin/fenix_* + proto_serve.py（reconfigure）

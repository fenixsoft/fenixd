# fenixd Linux 依赖真实分布盘点（Windows 评估侦察副产物）

## 背景

2026-11-10 为 Windows 原生支持立项评估做全库 POSIX 依赖侦察（初扫五簇 ~1370 处命中，逐点读代码核实后的真实分布如下）。其中两条与 Windows 无关也成立的代码事实先行沉淀。

## 结论

- `core/event_bus.py` 的文件监视实现是 **2 秒 checksum 轮询**（`_watch_loop`，event_bus.py:1059 附近 `time.sleep(2)`），代码内无任何 inotify syscall；域内文档"Linux 可选 inotify"的措辞与实现不符，实为文档失实。
- tmux 承载链已退役（bin/fenix_session.py:6-7），但 install.sh:44 的依赖检查仍要求 tmux——安装器存在冗余检查。
- 进程击杀纪律单源收口于 `core/proc_utils.py`：`kill_process_group()`（:235，SIGTERM→wait→SIGKILL 纪律）与 `guard_killpg()`（:331，拒向调用者自身进程组发信号），并有 grep 断言守卫测试钉死"裸 os.killpg 零存在"。
- 原子写单源为 `core/fs_utils.py`（atomic_write_text :41、with_file_lock :125），但 runner.py:6468、claude_adapter.py:166、verify_scenarios.py:401、code_fix.py:276、state_machine.py:2951、supervisor:236/280 仍有平行私有实现。
- 全库 `os.fork` 0 处、`multiprocessing` 0 处；asyncio 子进程仅 verify_engine/cli_runner.py:405-415 两处；`import pwd` 仅 core/git_env.py:21；`signal.signal` 注册仅 dashboard/server.py:779、fenixd_supervisor.py:999-1000 三处；信号常量面仅 SIGKILL/SIGTERM/SIGINT。
- flock 实际 80 个 call site（~30 文件）；`start_new_session=True` spawn 面约 38 处（runner×16、verify_contract×7、one_shot×7、regression×4、hook_engine×4 等）。

## 证据

评估正文（docs/superpowers/specs/2026-11-10-windows-native-support-pal-design.md §4）含逐项文件:行号锚点；grep 复核命令：`grep -rnoE "systemd|killpg|flock|/proc/|setsid|inotify" --include="*.py" core/ bin/`。

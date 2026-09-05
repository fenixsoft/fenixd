"""verification.py — VerificationPipeline：三阶段+legacy 验证/场景冻结/交互契约/verdict 证据分类/交付物门/env blocked 处理/验证门与告警 streak（refactor-core-packages 阶段 5）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；本轮缓存态
_last_scenario_diff / _last_interaction_contract 随组件同迁（design D3 规则 1），
门面经 property 委托保持原路径可用。

"""

from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request

from core.serving_registry import ServingRegistry
from core.verify_contract import (
    CommandVerifyServer,
    load_verify_contract,
    probe_ready,
    provision_worktree_node_modules,
    resolve_deps_mode,
    rewrite_scenarios_origin,
    run_prepare_steps,
    StaticVerifyServer,
)


class VerificationPipeline:
    """验证流水线组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    def _read_verify_report(self, spec_name: str) -> dict:
        """读取 verify-progress/<spec>/report.json（尽力解析，失败返回空 dict）。"""
        path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "report.json"
        )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


    def _handle_env_blocked_inconclusive(self, spec_name: str, report: dict) -> bool:
        """环境性失联门禁：全批 blocked-env → inconclusive → 保持 testing 重派新 attempt。

        inconclusive 判据（design D2）：summary.blocked_env > 0 且有效失败
        （failed + errors）为 0，即该轮原始失败全部为 blocked-env。

        处理：spec 回 implemented（verifier 派发门禁要求）→ 排队重验新 attempt；
        **不向 admin store 发 repeated_failures 信号**——本方法不产生 error 终态
        run 产物，repeated_failures 检测天然不累积（连续 inconclusive 不唤醒
        Administrator，对应 spec Scenario）。

        重验上限沿用 attempts=3（verify_engine.inconclusive_max_attempts 可调）：
        连续超限后停止自动重验、保持 implemented 并写 error 暴露，由
        admin_monitor stuck 检测唤起人工，不再无界自动重验。

        Returns:
            True 表示本轮已按 inconclusive 处理（调用方跳过 bug-found/verified
            判定）；False 表示无环境性失联，按既有判定继续。
        """
        summary = report.get("summary") or {}
        blocked_env = int(summary.get("blocked_env", 0) or 0)
        failed = int(summary.get("failed", 0) or 0)
        errors = int(summary.get("errors", 0) or 0)
        if blocked_env <= 0 or (failed + errors) > 0:
            return False

        spec = self._pm.state_machine.read_one(spec_name) or {}
        try:
            attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        max_attempts = int(
            self._pm._get_config("verify_engine.inconclusive_max_attempts", 3) or 3
        )

        if attempts < max_attempts:
            self._pm.logger.warning(
                "pm_engine",
                f"'{spec_name}' 本轮 {blocked_env} 个失败场景全部为 blocked-env"
                f"（环境性失联），verdict=inconclusive，第 {attempts}/{max_attempts} 次重验",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implemented",
                "tester_run": None,
                "error": (f"环境性失联：{blocked_env} 个失败场景均 blocked-env，"
                          f"第 {attempts}/{max_attempts} 次重验（inconclusive 不判 fail）"),
                "_inconclusive_attempts": attempts,
            })
            self._pm._enqueue(spec_name, "verifier")
            return True

        # 连续 ≥max_attempts 轮全部环境性失联：停止自动重验，暴露错误等待人工。
        # 置 _dispatch_backoff_until 吸收同状态 update 触发的即时重派振荡。
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' 连续 {attempts} 轮验证全部 blocked-env，"
            f"疑为 mock/SSE 推送环境故障，暂停自动重验",
        )
        self._pm.state_machine.update_spec(spec_name, {
            "status": "implemented",
            "tester_run": None,
            "error": (f"连续 {attempts} 轮验证全部环境性失联（blocked-env），"
                      f"请人工检查 mock/SSE 推送环境；不产生 bug-found 信号"),
            "_inconclusive_attempts": attempts,
            "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
        })
        return True


    def _serve_static_in_main(self, contract, scenarios_path) -> tuple:
        """方案 1（默认）：主树构建 + 主树起服务。同 root 复用已启动实例。"""
        root_dir = Path(self._pm.project_root) / contract.serve.root
        if not root_dir.is_dir():
            return False, False, f"验证契约 serve.root 不存在: {contract.serve.root}"
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        srv = cache.get("main")
        if srv is None or srv.root != root_dir.resolve():
            if srv is not None:
                srv.stop()
            srv = StaticVerifyServer(root_dir)
            cache["main"] = srv
        return self._finalize_static(srv, contract, scenarios_path, "主树")

    def _ensure_serving_worktree(self, spec_name: str, contract, mode: str):
        """serving worktree 供给（static/command 两型共享）。

        HEAD 未变且目录存活时复用；否则停掉旧实例、重建 worktree、provision
        依赖（deps_mode）并执行契约 prepare（构建产物）。

        Returns:
            (wt_path, head, err)：wt_path=None 时 err 为人类可读原因。
            server 生命周期（启动/复用/停止）由调用方按 mode 管理。
        """
        serve_root = Path(self._pm.project_root) / ".fenix" / "verify-serving"
        serve_root.mkdir(parents=True, exist_ok=True)
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        head = subprocess.run(
            ["git", "-C", str(self._pm.project_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        old = cache.get(spec_name)
        if (old is not None and old.get("head") == head
                and old.get("mode") == mode
                and Path(old["wt_path"]).is_dir()):
            return old["wt_path"], head, None
        if old is not None:
            # verify-process-lifecycle D6：command 型旧实例 HEAD 变更前先移除登记
            old_server = old.get("server")
            if isinstance(old_server, CommandVerifyServer):
                self._unregister_serving_instance(spec_name, old_server)
            try:
                old_server.stop()
            except Exception:
                pass
            self._remove_serving_worktree(old["wt_path"])
        wt = serve_root / f"{spec_name}-{int(time.time())}"
        r = subprocess.run(
            ["git", "-C", str(self._pm.project_root),
             "worktree", "add", "--detach", str(wt), "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return None, None, (
                "验证 worktree 创建失败: "
                f"{(r.stderr or r.stdout).strip()[-200:]}")
        provision_worktree_node_modules(
            wt, self._pm.project_root,
            sorted({(s.cwd or ".") for s in contract.prepare}),
            mode=resolve_deps_mode(
                contract, self._pm._get_config("verify.deps_mode", "")),
            logger=self._pm.logger,
        )
        err = run_prepare_steps(contract, wt)
        if err:
            self._remove_serving_worktree(wt)
            return None, None, f"验证契约 prepare 失败（worktree 内）: {err}"
        return str(wt), head, None

    def _serve_static_in_worktree(self, spec_name, contract, scenarios_path) -> tuple:
        """方案 2：专用 serving worktree 内构建 + 起静态服务（隔离主树运行实例）。

        worktree 每次 HEAD 变化时重建（分离 HEAD、自管理生命周期，位于
        .fenix/verify-serving/，gitignore 排除）；HEAD 未变时复用已启动实例
        与产物（replan 循环不重复构建）。
        """
        wt, head, err = self._ensure_serving_worktree(
            spec_name, contract, mode="static")
        if wt is None:
            return False, False, err
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        old = cache.get(spec_name)
        if (old is not None and old.get("mode") == "static"
                and old.get("head") == head
                and isinstance(old.get("server"), StaticVerifyServer)):
            return self._finalize_static(
                old["server"], contract, scenarios_path, "验证 worktree（复用）")
        root_dir = Path(wt) / contract.serve.root
        if not root_dir.is_dir():
            self._remove_serving_worktree(wt)
            return False, False, f"验证契约 serve.root 不存在: {contract.serve.root}"
        cache[spec_name] = {
            "server": StaticVerifyServer(root_dir), "wt_path": wt, "head": head,
            "mode": "static",
        }
        return self._finalize_static(
            cache[spec_name]["server"], contract, scenarios_path, "验证 worktree")

    @staticmethod
    def _port_responds(port: int) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(
                        f"http://127.0.0.1:{port}/",
                        headers={"User-Agent": "fenix-verify-probe"}),
                    timeout=1.0):
                return True
        except Exception:
            return False

    def _serve_command_in_worktree(self, spec_name, contract, scenarios_path) -> tuple:
        """命令型被测实例的 worktree 隔离（serve.kind=command + static_scope=worktree）。

        full-stack 验证的解法：serving worktree 内 prepare 构建产物，再以
        worktree 为 cwd 启动 serve.cmd——后端 API 与前端产物同为本次 HEAD 的
        真实形态（static 模式无 API，交付物端点被迫 mock＝假阴性放大器）。
        实例端口以 serve.port 为基准上探，跳过启动前已在监听的端口（主树
        常驻实例让位）。HEAD 未变时复用已启动实例。
        """
        wt, head, err = self._ensure_serving_worktree(
            spec_name, contract, mode="command")
        if wt is None:
            return False, False, err
        cache = self.__dict__.setdefault("_contract_static_servers", {})
        old = cache.get(spec_name)
        if (old is not None and old.get("mode") == "command"
                and old.get("head") == head
                and isinstance(old.get("server"), CommandVerifyServer)
                and old["server"].ok):
            return self._finalize_static(
                old["server"], contract, scenarios_path, "命令 worktree（复用）")
        import re as _re
        m = _re.search(r"(?:--port|-p)\s+(\d+)", contract.serve.cmd or "")
        hint = contract.serve.port or (int(m.group(1)) if m else 8787)
        # 启动前监听快照：这些端口属于既有实例，不认作本次实例
        pre = {p for p in range(hint, hint + 51) if self._port_responds(p)}
        try:
            proc = subprocess.Popen(
                contract.serve.cmd, shell=True, cwd=str(wt),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return False, False, f"验证命令实例启动失败: {e}"
        srv = CommandVerifyServer(proc, hint, pre,
                                  timeout=contract.ready.timeout or 60)
        if not srv.ok:
            srv.stop()
            return False, False, (
                f"验证命令实例未就绪（端口 {hint}+ 上探超时或进程退出）")
        cache[spec_name] = {
            "server": srv, "wt_path": wt, "head": head, "mode": "command",
        }
        # verify-process-lifecycle D6：command 型实例创建时登记
        # （pid/port/spec/worktree），终局/周期清扫按 liveness 收割。
        self._register_serving_instance(spec_name, srv, wt_path=wt)
        return self._finalize_static(
            srv, contract, scenarios_path, "命令 worktree")

    def _finalize_static(self, srv, contract, scenarios_path, scope_label) -> tuple:
        """BASE_URL 注入 + 就绪探针：static 两类 scope 的共同收尾。"""
        n = rewrite_scenarios_origin(scenarios_path, srv.base_url)
        ok, probe_note = probe_ready(srv.base_url, contract.ready)
        note = (f"验证契约 static[{scope_label}]: 被测实例 {srv.base_url}"
                f"（场景 origin 改写 {n} 处）— {probe_note}")
        return (True, False, note) if ok else (False, False, note)

    def _remove_serving_worktree(self, wt_path) -> None:
        subprocess.run(
            ["git", "-C", str(self._pm.project_root),
             "worktree", "remove", "--force", str(wt_path)],
            capture_output=True, text=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(self._pm.project_root), "worktree", "prune"],
            capture_output=True, timeout=15,
        )

    # ── 被测实例登记制（verify-process-lifecycle D6）─────────────────
    # serve.kind=command 与 _ensure_app_reachable 兜底 spawn 的实例创建时
    # 向 .fenix/verify-serving/servers.json 登记（pid/port/spec/worktree），
    # 停止时移除；spec 终局与 daemon 周期清扫按 /proc liveness 收割。

    def _register_serving_instance(self, spec_name: str, server,
                                   wt_path=None, hint_port=None) -> None:
        """command 型实例创建时登记。幂等：同 (pid,spec) 已登记则跳过。"""
        try:
            port = getattr(server, "port", None) or hint_port or 0
            ServingRegistry(self._pm.project_root, self._pm.logger).register(
                server.pid, port, spec_name, wt_path or "")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"serving 实例登记失败 '{spec_name}'（非阻塞）: {e}")

    def _unregister_serving_instance(self, spec_name: str, server) -> None:
        """command 型实例停止时移除登记。幂等：无匹配条目安全空转。"""
        try:
            ServingRegistry(self._pm.project_root, self._pm.logger).remove(
                server.pid, spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"serving 实例登记移除失败 '{spec_name}'（非阻塞）: {e}")

    def _evict_spec_serving(self, spec_name: str) -> None:
        """spec 终局（done/verified）后回收其被测实例并驱逐缓存。

        command 型：stop 进程 + 移除 servers.json 登记 + 移除 serving worktree；
        static 型：stop 实例。幂等：无缓存条目/无登记时安全空转。
        主树 static 共享实例（缓存键 "main"）不在此列（多 spec 共享，保留）。
        """
        cache = self.__dict__.get("_contract_static_servers", {})
        old = cache.pop(spec_name, None)
        if old is None:
            return
        server = old.get("server")
        try:
            if server is not None and hasattr(server, "pid"):
                # 登记过的实例（CommandVerifyServer 或兜底 spawn Popen）同步移除
                self._unregister_serving_instance(spec_name, server)
            if server is not None and getattr(server, "ok", True):
                server.stop()
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"spec 终局实例回收失败 '{spec_name}'（非阻塞）: {e}")
        wt = old.get("wt_path")
        if wt:
            self._remove_serving_worktree(wt)

    def _ensure_app_reachable(self, spec_name: str) -> tuple:
        """验证前确保应用可达：自动启动 commands.start、处理端口冲突。

        最终用户验证为必选项：场景执行前先保证应用可被浏览器访问；
        若不可达则自动启动服务（commands.start），端口冲突时换端口重试
        （改写场景 URL）。仅在「需用户参与（如收验证码/登录）」或
        「判定无法解决」时才返回不可达，由上层判定而非静默通过。

        Returns:
            (reachable, user_blocked, note)
            - reachable: 自愈后应用是否可达
            - user_blocked: 是否为需用户参与而无法自动验证（预留判定位）
            - note: 人类可读说明（供错误展示）
        """
        scenarios_path = (self._pm.project_root / ".fenix" / "verify-progress"
                          / spec_name / "test_scenarios.json")
        if not scenarios_path.exists():
            return True, False, ""
        try:
            data = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except Exception:
            return True, False, ""

        # 收集场景 navigate 目标 URL（应用入口）
        urls: list[str] = []
        for sc in (data if isinstance(data, list) else []):
            if not isinstance(sc, dict):
                continue
            for step in sc.get("steps", []) or []:
                if isinstance(step, dict) and step.get("action") == "navigate":
                    # navigate 目标 URL 存于 value（见 scenarios.TestStep）：191 个场景
                    # 全部用 value 携带链接，target/url 为空。旧代码读 url/target 导致
                    # urls 恒空，_ensure_app_reachable 恒判可达，可达性门禁永不触发。
                    u = str(step.get("value") or step.get("url") or step.get("target") or "")
                    if u.startswith("http") and u not in urls:
                        urls.append(u)
        if not urls:
            return True, False, ""

        # ── 声明式验证契约（.fenix/verify.yaml，字段语义见 verify_contract.py）──
        # 场景必须打「被测实现 fresh 构建出的可运行形态」。契约存在时：prepare
        # 重建产物 → static 无条件新鲜服务 + 场景 origin 全量改写（下方「已可达
        # 即跳过」捷径对构建型应用＝陈旧产物陷阱，契约 static 模式禁用）→ ready
        # 探针放行。契约缺失时维持 commands.start 旧行为（存量项目零迁移）。
        contract = load_verify_contract(self._pm.project_root, self._pm.logger)
        start_cmd_override = ""
        serve_port_hint = None
        if contract is not None:
            serve = contract.serve
            scope = str(self._pm._get_config("verify.static_scope", "main")
                        or "main").strip().lower()
            wt_scope = scope == "worktree"
            # 主树 prepare 仅在实例落于主树时需要——worktree 作用域在
            # serving worktree 内构建（共享助手），主树构建纯属双倍等待
            if contract.prepare and not wt_scope:
                err = run_prepare_steps(contract, self._pm.project_root)
                if err:
                    return False, False, f"验证契约 prepare 失败: {err}"
            if serve and serve.kind == "static":
                if wt_scope:
                    return self._serve_static_in_worktree(
                        spec_name, contract, scenarios_path)
                return self._serve_static_in_main(contract, scenarios_path)
            if serve and serve.kind == "command" and serve.cmd:
                if wt_scope:
                    return self._serve_command_in_worktree(
                        spec_name, contract, scenarios_path)
                start_cmd_override = serve.cmd
                serve_port_hint = serve.port

        def _probe(u: str, timeout: float = 2.0) -> bool:
            try:
                req = urllib.request.Request(u, method="GET",
                                             headers={"User-Agent": "fenix-verify-probe"})
                with urllib.request.urlopen(req, timeout=timeout):
                    return True
            except Exception:
                return False

        # 1) 直接探测：已可达则无需自愈
        if all(_probe(u) for u in urls):
            return True, False, ""

        # 2) 自愈：验证契约 serve.cmd 优先，回退 commands.start（旧行为）
        start_cmd = start_cmd_override or str(
            self._pm._get_config("commands.start", "") or "").strip()
        if not start_cmd or start_cmd in ("echo 'No start command configured yet'",):
            return False, False, "应用不可达且未配置验证契约 serve / commands.start（无法自动启动验证目标应用）"

        base_port = serve_port_hint
        if base_port is None:
            pm = re.search(r"(?:--port|-p)\s+(\d+)", start_cmd)
            if pm:
                base_port = int(pm.group(1))

        self._pm.logger.warning(
            "pm_engine",
            f"验证目标应用不可达，自动启动服务: {start_cmd}",
        )

        # 启动一次（后台、脱离会话、输出丢弃）；随后等待可达或扫描邻近端口
        try:
            proc = subprocess.Popen(
                start_cmd, shell=True, cwd=str(self._pm.project_root),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            return False, False, f"启动验证目标应用失败: {e}"
        # verify-process-lifecycle D6：兜底 spawn 同登记纳入管理
        # （pid/spec/worktree 空、端口先按 hint，实际可达端口由探测修正）
        self._register_serving_instance(spec_name, proc, hint_port=base_port)

        for _ in range(30):
            time.sleep(1)
            if all(_probe(u) for u in urls):
                return True, False, "已自动启动应用服务"

        # 场景 URL 端口 ≠ commands.start 端口（planner 臆测端口，如 3000 vs 8787）：
        # 应用已在 base_port 可达时，错的是场景端口而非应用——改写场景端口为
        # 实际端口后重探。原逻辑只改写 base_port 的出现处（base_port → 扫描到的
        # 邻近端口），对「场景写了别的端口」完全无能为力，导致应用明明已启动
        # 却被判不可达、spec 永久卡死在 testing（fix-fix-improve-verify-adjudication）。
        if base_port and _probe(f"http://127.0.0.1:{base_port}/"):
            foreign_ports = {
                m.group(1)
                for u in urls
                for m in [re.search(r":(\d+)(?=[/\?#]|$)", u)]
                if m and int(m.group(1)) != base_port
            }
            if foreign_ports:
                for p in sorted(foreign_ports, key=int):
                    self._pm._rewrite_scenario_port(scenarios_path, int(p), base_port)
                urls_new = []
                for u in urls:
                    v = u
                    for p in foreign_ports:
                        v = re.sub(r":%s(?=[/\?#]|$)" % p, f":{base_port}", v)
                    urls_new.append(v)
                if all(_probe(u) for u in urls_new):
                    return True, False, (
                        f"场景 URL 端口 {sorted(foreign_ports, key=int)} 与应用实际端口 "
                        f"{base_port} 不符（planner 臆测），已改写场景端口并确认可达"
                    )

        # 端口自动递增场景（如 --port 被占用时服务上探到邻近端口）：
        # 扫描 base_port 附近的端口，命中则改写场景 URL 并确认可达
        if base_port:
            for port in range(base_port + 1, base_port + 51):
                if _probe(f"http://127.0.0.1:{port}/"):
                    urls_new = [re.sub(r":%d(?=[/\?]|$)" % base_port, f":{port}", u) for u in urls]
                    if all(_probe(u) for u in urls_new):
                        self._pm._rewrite_scenario_port(scenarios_path, base_port, port)
                        return True, False, f"已自动启动应用服务（端口冲突，改用 {port}）"

        return False, False, ("应用仍不可达：已自动执行 commands.start 并扫描邻近端口，"
                              "仍无法连接（可能需人工启动/换端口，或属需用户参与的验证场景）")


    def _rewrite_scenario_port(self, scenarios_path: Path, old_port: int, new_port: int):
        """端口冲突换端口后，重写 test_scenarios.json 中的 URL 端口。"""
        try:
            content = scenarios_path.read_text(encoding="utf-8")
            content = re.sub(r":%d(?=[/\?\"']|$)" % old_port, f":{new_port}", content)
            scenarios_path.write_text(content, encoding="utf-8")
            self._pm.logger.info("pm_engine", f"已重写验证场景端口 {old_port} → {new_port}")
        except Exception as e:
            self._pm.logger.warning("pm_engine", f"重写验证场景端口失败: {e}")


    def _current_verify_round(self, spec_name: str) -> int:
        """推导本轮验证轮次：``_verify_fail_rounds + 1``（首轮=1）。"""
        entry = self._pm.state_machine.read_one(spec_name) or {}
        try:
            fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
        except (TypeError, ValueError):
            fail_rounds = 0
        return fail_rounds + 1


    def _apply_scenario_freeze(self, spec_name: str) -> dict:
        """应用场景集冻结：planner 产出 vs 持久化集 diff，写回 scenarios.json。

        design D3：确定性、纯 Python，planner 无法通过输出文本绕过。
        在场景执行前调用（_run_three_stage_verification 阶段1 之后）。

        Returns:
            dict：{'diff': <DiffResult>, 'path': <写入路径>}，便于报告渲染复用。
        """
        from core.verify_scenarios import (
            load_scenario_set, diff_planner_output, save_scenario_set,
        )
        verify_dir = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name
        )
        scenarios_path = verify_dir / "test_scenarios.json"
        if not scenarios_path.exists():
            return {}
        try:
            planner_scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        if not isinstance(planner_scenarios, list):
            return {}

        entry = self._pm.state_machine.read_one(spec_name) or {}
        current_round = self._pm._current_verify_round(spec_name)

        diff = diff_planner_output(
            self._pm.project_root, spec_name, entry, planner_scenarios, current_round)

        # 写回 scenarios.json（原子写；首轮写入 / 合并追加 / 补齐后稳定集）
        path = save_scenario_set(self._pm.project_root, diff.scenario_set)
        # 全量场景定义备份（_scenarios_full.json）：供无理由缺场景时按持久化集
        # 补齐 test_scenarios.json 的原始定义（design D2：不丢回归面）。
        # 仅当本轮未删减既有场景时更新备份（保留最全的历史定义）。
        if not diff.removed:
            full_backup = verify_dir / "_scenarios_full.json"
            try:
                full_backup.write_text(
                    json.dumps(planner_scenarios, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
        self._pm.logger.info(
            "pm_engine",
            f"场景集冻结 '{spec_name}'（第 {current_round} 轮）：稳定集 "
            f"{len(diff.scenario_set.scenarios)} 个，新增 {len(diff.added)}，"
            f"有理由移除 {len(diff.removed)}，无理由缺失 {len(diff.unreasoned_missing)}",
        )

        # 无理由缺场景 → 以持久化集补齐 test_scenarios.json（不中断验证，design D2）：
        # planner 实际执行的场景文件必须含全部既有场景，否则回归面丢失。优先从
        # 上一轮全量备份 _scenarios_full.json 取回被丢弃场景的原始定义。
        if not diff.ok and diff.unreasoned_missing:
            missing_ids = {e.id for e in diff.unreasoned_missing}
            reconciled = [s for s in planner_scenarios
                          if isinstance(s, dict) and s.get("id")
                          and s.get("id") not in missing_ids]
            backup = verify_dir / "_scenarios_full.json"
            backup_map = {}
            if backup.exists():
                try:
                    for s in json.loads(backup.read_text(encoding="utf-8")):
                        if isinstance(s, dict) and s.get("id"):
                            backup_map[s["id"]] = s
                except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                    backup_map = {}
            for mid in missing_ids:
                if mid in backup_map:
                    reconciled.append(backup_map[mid])
                else:
                    # 备份缺失：退化为最小占位（仅 id+description），保证回归面不丢
                    e = next((x for x in diff.unreasoned_missing
                              if x.id == mid), None)
                    rec = {"id": mid,
                           "description": e.description if e else ""}
                    reconciled.append(rec)
            try:
                scenarios_path.write_text(
                    json.dumps(reconciled, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as e:
                self._pm.logger.warning(
                    "pm_engine", f"补齐场景写回失败 '{spec_name}': {e}")

        self._last_scenario_diff = diff  # 供报告渲染（2.3）读取
        return {"diff": diff, "path": str(path)}


    def _apply_interaction_contract(self, spec_name: str) -> dict:
        """场景执行前校验交互契约覆盖（design D1/D2）。

        页面类 SPEC 检出可交互候选时，校验场景集对每个候选的覆盖（``covers``
        登记 / 场景文本命中）或纯展示声明（``declared_display`` / SPEC 标注）。
        辅助治理：任何异常不阻断验证主流程。

        Returns:
            {"ok": True} 或 {"ok": False, "result": ContractResult,
            "feedback": <退回 plan 的反馈文本>, "uncovered": [元素标识]}
        """
        from core.interaction_contract import (
            validate_interaction_coverage, build_replan_feedback,
            load_planner_scenarios,
        )
        from core.verify_scenarios import load_scenario_set
        try:
            scenarios_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            planner_scenarios = load_planner_scenarios(scenarios_path)
            if planner_scenarios is None:
                return {"ok": True, "skipped": True}
            persisted = load_scenario_set(self._pm.project_root, spec_name)
            result = validate_interaction_coverage(
                self._pm.project_root, spec_name, planner_scenarios, persisted)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"交互契约校验跳过 '{spec_name}'（不阻断）: {e}")
            return {"ok": True, "skipped": True}

        self._last_interaction_contract = result
        if result.ok:
            self._pm.logger.info(
                "pm_engine",
                f"交互契约覆盖校验通过 '{spec_name}'（候选 "
                f"{len(result.candidates)} 个，纯展示声明 {len(result.declared)} 个）",
            )
            return {"ok": True, "result": result}

        self._pm.logger.warning(
            "pm_engine",
            f"交互契约覆盖不完整 '{spec_name}': {result.uncovered}",
        )
        return {
            "ok": False, "result": result,
            "feedback": build_replan_feedback(result),
            "uncovered": list(result.uncovered),
        }


    def _render_scenario_change_section_to_report(self, spec_name: str) -> None:
        """把本轮场景集变更小节追加到 verification-report.md（spec 需求 2.3）。

        报告闸门（add-verify-report-gate）已保证文件存在；此处幂等追加，
        重复调用会因已存在「本轮场景集变更」标题而跳过。diff 来源优先级：
        ``_last_scenario_diff``（本轮冻结计算）> 重新读取 scenarios.json（首轮）。
        """
        diff = getattr(self, "_last_scenario_diff", None)
        from core.verify_scenarios import (
            render_change_section, load_scenario_set, render_first_write_section,
        )
        if diff is None:
            persisted = load_scenario_set(self._pm.project_root, spec_name)
            if persisted is None:
                return
            section = render_first_write_section(persisted)
        else:
            section = render_change_section(diff)
        if not section.strip():
            return
        report_path = (
            Path(self._pm.project_root) / "spec" / "changes"
            / spec_name / "verification-report.md"
        )
        if not report_path.exists():
            return
        try:
            content = report_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return
        if "## 本轮场景集变更" in content:  # 幂等：不重复追加
            return
        # add-verify-report-gate 要求不覆盖 mtime 语义仅针对「Agent 已写」文件；
        # 此处为框架追加小节，直接写回（Agent 漏写场景变更时由框架补）。
        try:
            report_path.write_text(content.rstrip("\n") + "\n" + section + "\n",
                                   encoding="utf-8")
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"场景集变更小节写回失败 '{spec_name}': {e}")


    def _run_three_stage_verification(self, spec_name: str):
        """三步验证流水线主逻辑。"""
        import asyncio
        import importlib
        import sys

        # 重新加载验证引擎模块，确保使用最新代码
        # fenixd 作为常驻进程运行，Python 会缓存已导入的模块，
        # 实现者更新代码后缓存不会自动失效，必须显式重新加载
        # 注意：子模块必须先于父包重新加载（依赖顺序）
        #
        # 额外保障机制（fix-fix-fix-fix）：
        # importlib.reload 不会更新其他模块中已导入的名称引用，
        # 因此在 reload 之后显式重新导入核心类，确保使用最新版本。
        _verify_modules = [
            "core.verify_engine.visual_diff",
            "core.verify_engine.browser",
            "core.verify_engine.assertions",
            "core.verify_engine.scenarios",
            "core.verify_engine.engine",
            "core.verify_engine",
        ]
        for mod_name in _verify_modules:
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass  # 重新加载失败时使用缓存版本

        # 额外保障：强制从磁盘重新导入核心模块
        # Python 的 import 系统会检查 sys.modules，但如果 reload 失败，
        # 下面的 import 会使用已更新的 sys.modules 条目
        for mod_name in _verify_modules:
            try:
                if mod_name not in sys.modules:
                    importlib.import_module(mod_name)
            except Exception:
                pass

        from core.verify_engine import VerifyEngine
        from core.verify_engine.scenarios import load_scenarios

        # ── 阶段1+2: Planner↔场景验收闭环（2026-08-28）──
        # 场景验收（绝对 navigate URL/完整性）失败 → 写 REPLAN_FEEDBACK.md 退回
        # plan 阶段重新生成，上限 2 次重排；连续失败保持 implemented + error
        # 可见（验收失败属环境/任务书问题，绝非产品缺陷，绝不流转 bug-found）。
        verify_dir = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name
        )
        replan_left = 2
        replan_feedback = None
        # fix-replan-feedback-injection：上一轮验收错误原文——连续两轮一字不差说明
        # planner 未消费反馈（重跑即纯烧钱），升级为 ERROR 提示人工关注。
        prev_replan_error = None
        report = None
        app_reachable = True
        reach_note = ""
        # ── 场景冻结复用（scenario-reuse-on-reenter，2026-09-04）──
        # 冻结集一经生成即跨轮一致的量尺：重入验证（打回/修复轮/重试）直接
        # 复用，绝不重新出题——planner 单轮 2h/30M token 级成本只支付一次。
        # 冻集变更的唯一通道：admin 裁决（扩展/豁免）或人工删除冻结文件批准
        # 重新出题。首次进入（无冻结文件）走下方 planner 设计闭环。
        frozen = self._load_frozen_scenarios(verify_dir)
        if frozen == "corrupt":
            self._pm.logger.error(
                "pm_engine",
                f"冻结场景文件验收失败 '{spec_name}' — 场景一经冻结跨轮一致，"
                f"变更须 admin 裁决，不自动重新出题",
            )
            self._escalate_env_blocked(
                spec_name,
                ["冻结场景文件损坏或验收失败。处置选项：① 确认场景集已过时 → "
                 f"删除 .fenix/verify-progress/{spec_name}/test_scenarios.json "
                 "批准重新出题；② 文件可修复 → 修复后保持冻结。"],
                title="场景计划争议",
            )
            return
        while True:
            if frozen is not None:
                # ── 冻结复用：跳过整段出题，覆盖缺口按计划争议升级 ──
                self._pm.logger.info(
                    "pm_engine",
                    f"[阶段1] 场景冻结复用（{len(frozen)} 个场景），跳过重新出题: "
                    f"{spec_name}",
                )
                cov = self._pm._apply_interaction_contract(spec_name)
                if cov is not None and not cov.get("ok"):
                    self._pm.logger.error(
                        "pm_engine",
                        f"冻结场景覆盖缺口 '{spec_name}'（修复新增可交互元素？）"
                        f"— 场景变更须 admin 裁决，不自动重排: {cov.get('uncovered')}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [f"冻结场景未覆盖可交互元素: {cov.get('uncovered')}。"
                         "处置选项：① 扩展冻结场景集；② 声明纯展示；"
                         "③ 删除冻结文件批准重新出题。"],
                        title="场景计划争议",
                    )
                    return
                # 覆盖完整 → 落入下方阶段2（共享执行段）
            else:
                if replan_feedback is not None:
                    fb = verify_dir / "REPLAN_FEEDBACK.md"
                    fb.parent.mkdir(parents=True, exist_ok=True)
                    fb.write_text(
                        "# 场景验收反馈（上一轮未通过，必须逐条修正）\n\n"
                        + replan_feedback
                        + "\n\n重新输出全部场景；navigate 的 value 必须为绝对 URL。\n",
                        encoding="utf-8",
                    )
                self._pm.logger.info("pm_engine", f"[阶段1] Planner 生成场景: {spec_name}")
                plan_result = self._pm.agent_runner.run_planner(spec_name, "plan")

                if not plan_result.success:
                    # ── 人工取消 hold-state（add-run-cancel D4）──
                    # planner run 被取消：spec 保持 testing 原状，只写 error，
                    # 不流转 bug-found、不降级 legacy、不入队。
                    if getattr(plan_result, "cancelled", False):
                        p_err = plan_result.error or ""
                        cancelled_err = (
                            f"run 被人工取消：{p_err}" if p_err else "run 被人工取消"
                        )
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": cancelled_err,
                        })
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Planner plan run 被人工取消 — hold-state '{spec_name}' "
                            f"(保持 testing): {cancelled_err}",
                        )
                        return
                    # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
                    # 熔断期 planner 派发失败属「provider 故障」，不是验证逻辑失败：
                    # 不得 raise（会触发 legacy 降级 → bug-found → 伪 fix 级联），
                    # 保持 spec 在 implemented（由 full_scan recovery 兜底重排）。
                    if plan_result.error and "provider circuit open" in plan_result.error:
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": plan_result.error,
                        })
                        self._pm.logger.warning(
                            "pm_engine",
                            f"Provider circuit open — planner suppressed for '{spec_name}', "
                            f"holding implemented: {plan_result.error}",
                        )
                        return
                    raise RuntimeError(f"Planner plan 失败: {plan_result.error}")

                # 验证 Planner 是否成功生成场景文件
                plan_status = self._pm._read_planner_result(spec_name)
                if plan_status != "plan-ready":
                    # fix-planner-invalid-output-alert：planner run 成功收工却无有效产出
                    # ＝ 整轮 planner 时长/成本白烧，必须显式留痕（error 字段 + ERROR 级
                    # 日志），否则只在降级 WARNING 里一笔带过，浪费不可见。
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": (
                            f"Planner 场景生成无效（status={plan_status}，run="
                            f"{plan_result.run_id}，{plan_result.duration_seconds / 60:.1f}min）"
                            f"— 降级旧版验证流程"
                        ),
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"Planner 未生成有效场景 '{spec_name}'（status={plan_status}，"
                        f"run={plan_result.run_id}，白烧 "
                        f"{plan_result.duration_seconds / 60:.1f}min）— 降级旧版 verifier",
                    )
                    raise RuntimeError(f"Planner 未生成有效场景，status={plan_status}")

                # ── 场景集冻结（add-verify-scenario-freeze）──
                # 首轮写入 / 修复轮 diff 校验（design D3：确定性，planner 不可绕过）。
                # 在场景执行前应用：以持久化集约束 planner 产出，缺场景补齐后继续验证。
                # （冻结复用路径不经过此处——冻结集即原班场景，无需再约束产出。）
                try:
                    self._pm._apply_scenario_freeze(spec_name)
                except Exception as e:
                    # 冻结逻辑属辅助治理，绝不阻断验证主流程
                    self._pm.logger.warning(
                        "pm_engine",
                        f"场景集冻结处理跳过 '{spec_name}'（异常不阻断验证）: {e}",
                    )

                # ── 交互契约覆盖校验（add-interaction-contract-and-per-assert-triage 1.3）──
                # 可交互元素既无场景覆盖又无纯展示声明 → 写反馈退回 plan 补齐
                # （复用场景验收退回路径）；重排预算耗尽后不阻断验证，违规留痕。
                contract = self._pm._apply_interaction_contract(spec_name)
                if contract is not None and not contract.get("ok"):
                    if replan_left > 0:
                        replan_feedback = contract.get("feedback") or ""
                        replan_left -= 1
                        self._pm.logger.warning(
                            "pm_engine",
                            f"交互契约覆盖不完整 '{spec_name}' — 退回 plan 阶段"
                            f"（剩余重排 {replan_left} 次）: {contract.get('uncovered')}",
                        )
                        continue
                    self._pm.logger.error(
                        "pm_engine",
                        f"交互契约重排预算耗尽 '{spec_name}' — 违规留痕继续验证: "
                        f"{contract.get('uncovered')}",
                    )

            # ── 阶段2: 验证引擎执行 ──
            self._pm.logger.info("pm_engine", f"[阶段2] 验证引擎执行: {spec_name}")
            scenarios_path = (
                self._pm.project_root / ".fenix" / "verify-progress"
                / spec_name / "test_scenarios.json"
            )
            # 场景文件验收失败（相对 URL/结构非法）＝ 明确的环境错误：
            # 退回 plan 阶段重新生成，不走 raise 穿透、更不判 bug-found。
            env_error = None
            report = None
            try:
                scenarios = load_scenarios(scenarios_path)
            except ValueError as e:
                env_error = f"场景文件验收失败: {e}"

            if env_error is None:
                # ── 阶段2.5: 应用可达性自愈（最终用户验证必选）──
                # 场景执行前确保应用可被浏览器访问；不可达时自动启动 commands.start、
                # 端口冲突换端口重试。自愈失败由下方验证门禁兜底，不静默判定通过。
                app_reachable, _user_blocked, reach_note = self._pm._ensure_app_reachable(spec_name)
                self._pm.logger.info(
                    "pm_engine",
                    f"[阶段2] 应用可达性: {'OK' if app_reachable else '不可达'} — {reach_note or '无 navigate 依赖'}",
                )

                # 自愈可能改写场景文件端口（planner 臆测端口 → 应用实际端口）：
                # 上方 load 先于自愈，内存场景仍持臆测端口，改写只落文件、对本次
                # 执行无效 → 全场景对失联端口 navigate 整轮伪失败
                # （add-v3-spec-detail-page：24 场景导航 localhost:8000 全灭）。
                # 故自愈后必须重读场景文件再执行。
                try:
                    scenarios = load_scenarios(scenarios_path)
                except ValueError as e:
                    env_error = f"自愈改写后场景文件验收失败: {e}"

            if env_error is None:
                engine = VerifyEngine(
                    spec_name, self._pm.project_root, self._pm.logger, self._pm.config
                )
                report = asyncio.run(engine.run(scenarios))
                env_error = report.get("env_error")

            if env_error:
                if env_error == prev_replan_error:
                    self._pm.logger.error(
                        "pm_engine",
                        f"场景验收错误与上一轮一字不差 '{spec_name}' — planner 未消费"
                        f"反馈，重跑属高风险重复（错误清单已内联进本轮 prompt）: "
                        f"{env_error[:200]}",
                    )
                prev_replan_error = env_error
                if replan_left <= 0:
                    self._pm.state_machine.update_spec(spec_name, {
                        "status": "implemented",
                        "tester_run": None,
                        "error": (
                            f"场景验收连续失败（退回 plan 2 次仍不通过）: "
                            f"{env_error[:280]}"
                        ),
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"场景验收连续失败 '{spec_name}' — 保持 implemented 等待人工: "
                        f"{env_error}",
                    )
                    return
                if frozen is not None:
                    # 冻结复用路径：执行期场景异常不重新出题（量尺一致原则），
                    # 升级 admin 裁决
                    self._pm.logger.error(
                        "pm_engine",
                        f"冻结场景执行异常 '{spec_name}' — 不重新出题，升级 admin "
                        f"裁决: {env_error}",
                    )
                    self._escalate_env_blocked(
                        spec_name,
                        [f"冻结场景执行环境异常: {str(env_error)[:200]}"],
                        title="场景计划争议",
                    )
                    return
                replan_feedback = env_error
                replan_left -= 1
                self._pm.logger.warning(
                    "pm_engine",
                    f"场景验收未通过 '{spec_name}' — 退回 plan 阶段"
                    f"（剩余重排 {replan_left} 次）: {env_error}",
                )
                continue

            # 验收通过：清理反馈文件（下次全新验证不受旧反馈干扰）
            try:
                (verify_dir / "REPLAN_FEEDBACK.md").unlink()
            except OSError:
                pass
            break

        fail_count = report["summary"]["failed"] + report["summary"]["errors"]
        self._pm.logger.info(
            "pm_engine",
            f"[阶段2] 完成: {report['summary']['total']}场景, "
            f"{report['summary']['passed']}通过, "
            f"{report['summary']['warnings']}警告, "
            f"{fail_count}失败",
        )

        # ── 阶段2 验证门禁：应用不可达且场景全失败时不判定 verified ──
        # 最终用户验证为必选项：若自愈后应用仍不可达、0 场景通过，则本次验证
        # 并未真正触达最终用户可见功能，不得静默判定 verified/done；将问题与
        # 已尝试的解决方案写入 error 暴露（而非 "0通过/31失败" 却标完成）。
        if (not app_reachable
                and report["summary"]["passed"] == 0
                and fail_count == report["summary"]["total"]):
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": "blocked:app-unreachable",
                "error": f"验证无法执行（最终用户验证未完成）: {reach_note or '应用不可达'}",
            })
            self._pm.logger.error(
                "pm_engine",
                f"验证门禁: '{spec_name}' 应用不可达，未判定 verified — {reach_note}",
            )
            return

        # ── 阶段2.6 环境性失联门禁（verify-environment-sanity-gate / design D2）──
        # 全批 blocked-env → inconclusive：回 testing 重派新 attempt，不判 bug-found、
        # 不产生 repeated_failures 信号。阻断后直接 return（跳过 judge / 终态判定）。
        if self._pm._handle_env_blocked_inconclusive(spec_name, report):
            return

        # ── 阶段2.7 全场景同因失败哨（2026-08-28）──
        # pass=0 且全部失败场景错误签名一致 → 疑环境/场景问题，呼叫 admin 介入
        # 判断；不判 bug-found、不派生 fix；连续 3 轮同因自动 blocked。
        if self._pm._detect_uniform_verify_failure(spec_name, report):
            return

        # ── 阶段3: Planner 判定结果 ──
        self._pm.logger.info("pm_engine", f"[阶段3] Planner 判定: {spec_name}")
        judge_result = self._pm.agent_runner.run_planner(spec_name, "judge")

        if not judge_result.success:
            # ── 人工取消 hold-state（add-run-cancel D4，judge 同语义）──
            # judge run 被取消：spec 保持 testing 原状，只写 error。
            if getattr(judge_result, "cancelled", False):
                j_err = judge_result.error or ""
                cancelled_err = (
                    f"run 被人工取消：{j_err}" if j_err else "run 被人工取消"
                )
                self._pm.state_machine.update_spec(spec_name, {
                    "error": cancelled_err,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Planner judge run 被人工取消 — hold-state '{spec_name}' "
                    f"(保持 testing): {cancelled_err}",
                )
                return
            # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
            # 同阶段1：熔断期 planner judge 失败属「provider 故障」，
            # 不得 raise → legacy 降级 → bug-found → 伪 fix 级联。
            if judge_result.error and "provider circuit open" in judge_result.error:
                self._pm.state_machine.update_spec(spec_name, {
                    "error": judge_result.error,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Provider circuit open — planner judge suppressed for "
                    f"'{spec_name}', holding implemented: {judge_result.error}",
                )
                return
            raise RuntimeError(f"Planner judge 失败: {judge_result.error}")

        # ── 阶段3+ 裁决证据分类校验与重试（add-verdict-evidence-taxonomy D1-D5）──
        # judge 已在 report.json 增强每个非 PASS 场景的 classification/evidence。
        # 此处确定性校验：不合规 → 走既有 judge 重试一次（同 run_planner 调用）；
        # 二次仍不合规 → blocked-env + 告警（与 verify-report-gate 阻断语义一致，
        # 宁可不推进也不带病采纳）。合规后按分类-状态映射强制重写 status（D3）。
        verdict_ok = self._pm._verify_verdict_evidence(spec_name, retry_judge=True)
        if not verdict_ok:
            self._pm.logger.error(
                "pm_engine",
                f"裁决证据分类二次校验仍失败 '{spec_name}' — 阻断推进为 blocked-env",
            )
            self._pm.state_machine.update_spec(spec_name, {
                "status": "blocked",
                "error": (
                    f"验证裁决证据分类校验连续失败：report.json 非 PASS 场景缺 "
                    f"classification/evidence，重试一次仍不合规，已 blocked 等待人工裁决"
                ),
            })
            self._pm._send_human_escalation_alert(
                spec_name=spec_name,
                signal_type="verdict_evidence_invalid",
                severity="critical",
                description=(
                    f"'{spec_name}' 验证裁决证据分类校验连续失败，已 blocked 等待人工裁决"
                ),
                evidence=(
                    f"spec={spec_name}; report="
                    f"spec/changes/{spec_name}/verification-report.md"
                ),
                recommended_action=(
                    "检查 planner-judge 是否遵守 prompt 第4步（对全部非 PASS 场景补 "
                    "classification/evidence）；人工重置后重跑验证"
                ),
            )
            return

        # ── 阶段3+ warning 连续悬置追踪与升级（design D4 / D5）──
        # 裁决采纳处更新连续计数侧车；达 2 轮的 warning 场景发 triage 升级告警，
        # 并写入下一轮 planner prompt 的优先复核清单（triage_recheck.json）。
        try:
            triage_hits = self._pm._update_warning_streaks(spec_name)
            if triage_hits:
                self._pm._warning_stale_triage_alert(spec_name, triage_hits)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"warning_streaks 更新跳过（异常不阻断采纳）'{spec_name}': {e}",
            )

        # 读取判定结果
        verifier_status = self._pm._read_planner_result(spec_name)
        if verifier_status == "bug-found":
            # judge 自述环境问题守卫：judge 自己把根因描述为环境/基础设施问题时，
            # 属「验证没能发生」而非「验证发现了缺陷」，不得流转 bug-found
            # 派生伪 fix 级联（admin 处置 2026-08-28 failover 相对 URL 伪失败实证）。
            if self._pm._judge_bugs_declare_env(spec_name) and self._pm._handle_judge_env_declared(spec_name):
                return
            # 验证报告产物闸门（add-verify-report-gate）：裁决 Agent 漏写报告时
            # 由框架合成兜底，合成失败则阻断推进（下游修复引用的路径必然可读）
            report_blocker = self._pm._ensure_verification_report(spec_name)
            if report_blocker:
                self._pm.state_machine.update_spec(spec_name, {
                    "error": report_blocker,
                })
                self._pm.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                )
                return
            self._pm.state_machine.transition(spec_name, "bug-found")
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": judge_result.run_id,
                "error": "Verification found bugs — see verification report",
                # 明确非环境性失联：复位 inconclusive 计数（环境恢复后从零重算）
                "_inconclusive_attempts": 0,
            })
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
            self._pm._render_scenario_change_section_to_report(spec_name)
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier found bugs in '{spec_name}', transitioning to bug-found",
            )
            # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
            # 被验对象为 fix spec 且自身 ready/implementing（重实现已在飞）时，
            # 跳过派生子 fix——由在飞重实现承载修复。
            if self._pm._is_fix_spec(spec_name):
                cur = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                if cur in ("ready", "implementing"):
                    self._pm.logger.info(
                        "pm_engine",
                        f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                        f"（重实现在飞）——跳过派生子 fix",
                    )
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": "修复由在飞重实现承载，跳过派生子 fix",
                    })
                    return
            self._pm._on_spec_bug_found(spec_name)
        else:
            # D6: testing→verified 前置进度核对：done>=total 才晋级
            vblocker = self._pm._check_verification_gate(spec_name)
            if vblocker:
                # 不完整：按 verifier 失败处理，写 error 摘要，不晋级 verified
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": judge_result.run_id,
                    "error": vblocker,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"验证未完成 '{spec_name}'，阻止晋级 verified: {vblocker}",
                )
                return
            # 验证报告产物闸门（add-verify-report-gate）
            report_blocker = self._pm._ensure_verification_report(spec_name)
            if report_blocker:
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": judge_result.run_id,
                    "error": report_blocker,
                })
                self._pm.logger.error(
                    "pm_engine",
                    f"验证报告闸门: '{spec_name}' 阻止晋级 verified — {report_blocker}",
                )
                return
            # verified 洗白门禁（help-center 0/15 verified 事故防线）：
            # 0 通过或 env 失败不得放行，升级 admin 处置
            if not self._pm._env_whitewash_gate(spec_name):
                return
            self._pm.state_machine.transition(spec_name, "verified")
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": judge_result.run_id,
                "error": None,
                "_inconclusive_attempts": 0,
                # add-fail-counter-budget D1：验证 PASS 是 _verify_fail_rounds
                # 的唯一归零点——跨修复周期累计的失败计数在此清零并持久化，
                # 打回重派/修复收工等中间转换不再归零（见 _do_spec_bug_found）。
                "_verify_fail_rounds": 0,
                "_env_block_rounds": 0,
            })
            # 本轮场景集变更小节追加到验证报告（spec 需求 2.3）
            self._pm._render_scenario_change_section_to_report(spec_name)
            self._pm._on_spec_verified(spec_name)


    def _verifier_error_is_infra(self, error_text: str) -> bool:
        """verifier 失败是否属基础设施类（不得流转 bug-found）。

        覆盖：provider 熔断抑制、failover 链耗尽（chain exhausted）、
        classify_switch_error 可识别的切换类错误（unrecognized_model/5xx/网络）。
        此类失败说明「验证没能发生」，不是「验证发现了缺陷」。
        """
        if not error_text:
            return False
        if "provider circuit open" in error_text or "chain exhausted" in error_text:
            return True
        try:
            # 严格 is True：分类器返回非布尔（如测试桩）时按非基础设施处理
            return self._pm.agent_runner.classify_switch_error(error_text) is True
        except Exception:
            return False


    def _verifier_result_is_stale(self, result, result_path: Path, spec_name: str) -> bool:
        """verifier 结果文件是否不可信（陈旧重放 / 异 spec 残留 / 缺失）。

        判据（任一命中即陈旧）：
        - run_id 内嵌 epoch 早于文件 mtime 之前 5 秒以上 → 本轮验证器未曾写回；
        - 文件缺失却宣称成功 → 判定来源不明；
        - 文件 spec 戳与当前 spec 不符 → 其它 spec 的残留。
        无法解析 run_id 时不判定（维持既有行为，向后兼容）。
        """
        import re
        try:
            m = re.search(r"-(\d{10,})-a\d+$", getattr(result, "run_id", "") or "")
            if not m:
                return False
            run_start = int(m.group(1))
        except (TypeError, ValueError):
            return False
        if not result_path.exists():
            return True
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True
        if not isinstance(data, dict):
            return True
        stamped = data.get("spec")
        if isinstance(stamped, str) and stamped and stamped != spec_name:
            return True
        try:
            if result_path.stat().st_mtime < run_start - 5:
                return True
        except OSError:
            return True
        return False


    def _implementer_zero_change(self, spec_name: str, result) -> bool:
        """实现器零变更成功判定：分支零新提交 且 全程零 Edit/Write 工具调用。

        分支缺失（result.branch 为空）不判定（保持既有行为，向后兼容）。
        """
        import subprocess as _sp
        branch = getattr(result, "branch", None)
        if not branch:
            return False
        try:
            r = _sp.run(
                ["git", "rev-list", "--count", f"main..{branch}"],
                capture_output=True, text=True, timeout=15,
                cwd=str(self._pm.project_root),
            )
            if r.returncode != 0:
                return False
            if int(r.stdout.strip() or "0") > 0:
                return False  # 有新提交 → 正常成功
        except (OSError, ValueError, _sp.TimeoutExpired):
            return False
        # 分支零提交，再看运行产物中是否有编辑类工具调用
        run_file = self._pm.project_root / ".fenix" / "runs" / f"{result.run_id}.jsonl"
        try:
            with run_file.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("type") != "assistant":
                        continue
                    for c in (d.get("message") or {}).get("content") or []:
                        if (isinstance(c, dict) and c.get("type") == "tool_use"
                                and c.get("name") in (
                                    "Edit", "Write", "MultiEdit", "NotebookEdit")):
                            return False
        except OSError:
            return False
        return True


    def _deliverable_gate_missing(self, spec_name: str, result) -> list:
        """交付物守卫：返回 SPEC 声明但实现分支中缺失的交付路径清单。

        纯文件存在性检查（add-implementer-deliverable-gate D3）：从 SPEC 目录
        提取声明路径，逐一在 ``result.branch`` 的 HEAD 提交中校验 blob 存在。
        校验基准为实现分支（worktree 已清理，仅分支留存）。

        提取器语义升级（add-deliverable-extractor-semantics）：仅
        ``deliverables``（新建交付物）参与缺件判定；``references``（既有文件
        引用）走软校验——缺失仅记审计日志（D4），不阻断、不重派、不改状态。
        路径按字面校验（``normalize_check_path`` 已退役为恒等映射：
        ``.fenix`` 自引用符号链接设计废弃后为实体目录，历史的前缀归一化
        会在根路径同名文件存在时把 ``.fenix/x`` 缺件假放行）。

        Returns:
            缺失路径列表（相对项目根）；空列表表示放行（含无路径 SPEC 跳过场景）。
        """
        from core.deliverables import extract_declared, extract_paths_typed

        spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
        if not spec_dir.is_dir():
            return []
        # 声明优先（planner 交付契约）：tasks.md 有 `## Deliverables` 段时做机械
        # 对账，不做正则语境猜测；无声明段回退 extract_paths_typed（向后兼容）。
        typed = extract_declared(spec_dir)
        decl_source = "declared"
        if typed is None:
            typed = extract_paths_typed(spec_dir)
            decl_source = "extracted"
        declared = typed["deliverables"]
        references = typed["references"]
        if not declared and not references:
            # 无路径 SPEC：跳过守卫，行为退化到守卫上线前（向后兼容）
            return []
        wm = self._pm.agent_runner.worktree_manager
        branch = getattr(result, "branch", None)
        if not branch:
            # 无分支无法校验存活交付物：保守放行（与既有零变更哨共用缺失判定），
            # 交由零变更哨/merge 流程兜底
            return []

        def _exists_on_branch(path: str) -> bool:
            # 字面路径校验（.fenix 前缀归一化已退役，见本方法 docstring）
            return wm.file_exists_on_branch(branch, path)

        # 交付物（硬校验）：缺件 → 不合并不推进，重派实现补齐
        missing = [p for p in declared if not _exists_on_branch(p)]

        # 引用（软校验，D4）：缺失仅审计留痕——引用错误不该阻断实现
        missing_refs = [p for p in references if not _exists_on_branch(p)]
        if missing_refs:
            self._pm.logger.warning(
                "deliverable-reference-missing",
                f"引用类路径在实现分支中不存在（仅审计留痕，不阻断）："
                f"{spec_name} -> {', '.join(missing_refs)}",
                context={"spec": spec_name, "branch": branch,
                         "source": decl_source,
                         "missing_references": missing_refs},
            )
        return missing

    def _disputed_deliverables(self, impl_result, missing) -> list:
        """实现 run 对缺件提出的 deliverable-dispute 异议与缺件清单求交。

        交互契约的 findings 通道（add-interaction-contract 泛化）：实现 run 认为
        某缺件路径实为运行时写入目标/既有引用而非本仓库交付物时，在
        ``.fenix-run-result.json`` findings 登记 ``deliverable-dispute`` 条目。
        守卫拒绝前先对账：命中异议的缺件**不得**自动重派（负反馈死循环会烧钱），
        由调用方转人工/裁决。

        element 与缺件路径按字面匹配（``normalize_check_path`` 已退役为
        恒等映射）。Returns: 命中异议的缺件路径子集（保序）。
        """
        if not impl_result or not missing:
            return []

        disputed: list = []
        for f in (impl_result.get("findings") or []):
            if not isinstance(f, dict) or f.get("type") != "deliverable-dispute":
                continue
            el = str(f.get("element") or "").strip()
            if not el:
                continue
            for m in missing:
                if m not in disputed and m == el:
                    disputed.append(m)
        return disputed


    @staticmethod
    def _normalize_fail_signature(text: str) -> str:
        """归一化失败签名：数字→N、去引号、折叠空白，便于同因比较。"""
        import re as _re
        t = _re.sub(r"\d+", "N", text or "")
        t = _re.sub(r"['\"`]", "", t)
        return _re.sub(r"\s+", " ", t).strip()


    def _detect_uniform_verify_failure(self, spec_name: str, report: dict) -> bool:
        """全场景同因失败哨：pass=0 且全部失败场景错误签名一致 → 疑环境/场景问题。

        呼叫 admin 介入判断（verify_uniform_failure 信号，major）；不判
        bug-found、不派生 fix。连续 3 轮同因 → blocked 交人工。
        Returns: True 表示本轮已按同因失败处理（调用方跳过后续判定）。
        """
        summary = report.get("summary") or {}
        try:
            passed = int(summary.get("passed", 0) or 0)
            failed = int(summary.get("failed", 0) or 0)
            total = int(summary.get("total", 0) or 0)
        except (TypeError, ValueError):
            return False
        if passed != 0 or failed < 3:
            return False
        failed_scns = [s for s in (report.get("scenarios") or [])
                       if s.get("status") == "fail"]
        if len(failed_scns) < failed:
            return False  # 报告口径不一致，不哨
        sigs: set[str] = set()
        for s in failed_scns:
            sig = ""
            for a in (s.get("assertion_results") or []):
                if a.get("pass") is False:
                    sig = str(a.get("error") or "")
                    break
            if not sig:
                for st in (s.get("step_results") or []):
                    if st.get("success") is False:
                        sig = str(st.get("error") or st.get("detail") or "")
                        break
            sigs.add(self._pm._normalize_fail_signature(sig)[:80])
        if len(sigs) != 1:
            return False
        signature = next(iter(sigs))
        spec = self._pm.state_machine.read_one(spec_name) or {}
        try:
            attempts = int(spec.get("_uniform_fail_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        note = (f"全场景同因失败（{failed}/{total}，签名一致: \"{signature[:60]}\"）"
                f"——疑似环境或场景问题，已呼叫 admin 介入判断（第 {attempts} 次）")
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self._pm.project_root, self._pm.logger)
        try:
            store.append({
                "kind": SIGNAL,
                "signal_type": "verify_uniform_failure",
                "spec": spec_name,
                "severity": "major",
                "description": note,
                "evidence": f"signature={signature[:120]}; failed={failed}",
                "recommended_action": (
                    "判断失败类别：环境问题（实例/端口/构建）→ 修复后把 spec 拨回 "
                    "implemented 重验；场景/plan 问题 → 修正或重写场景；确认真实 "
                    "缺陷 → 人工处置。连续 3 轮同因将自动 blocked。"),
            })
        except Exception as e:
            self._pm.logger.error("pm_engine",
                              f"verify_uniform_failure 信号写入失败: {e}")
        updates: dict = {
            "error": note,
            "_uniform_fail_attempts": attempts,
        }
        if attempts >= 3:
            updates["status"] = "blocked"
            updates["tester_run"] = None
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.warning("pm_engine",
                            f"全场景同因失败哨触发 '{spec_name}': {note}")
        return True


    def _run_legacy_verification(self, spec_name: str):
        """降级方案：使用旧版单体 Verifier Agent。"""
        result = self._pm.agent_runner.run_verifier(spec_name)

        # ── provider 熔断拦截（fix-fix-stashpop-deadlock：provider-fault-fuse） ──
        # 熔断期 verifier 派发失败属「provider 故障」，不是真实验证失败：
        # 不得 transition bug-found / 调用 _on_spec_bug_found（否则会派生伪 fix
        # 级联，与 implementer 路径的 fix-fix-stashpop-deadlock 同理）。保持 spec
        # 在 implemented（由 full_scan recovery 兜底重排），写入 error 供 dashboard 可见。
        if getattr(result, "cancelled", False):
            # ── 人工取消 hold-state（add-run-cancel D4，legacy verifier）──
            # verifier run 被取消：spec 保持 testing 原状，只写 error，
            # 不流转 bug-found、不入队重派。
            v_err = result.error or ""
            cancelled_err = (
                f"run 被人工取消：{v_err}" if v_err else "run 被人工取消"
            )
            self._pm.state_machine.update_spec(spec_name, {
                "error": cancelled_err,
            })
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier run 被人工取消 — hold-state '{spec_name}' "
                f"(保持 testing): {cancelled_err}",
            )
            return
        if self._pm._verifier_error_is_infra(result.error):
            # 基础设施类失败（熔断/链耗尽/网关切换类错误）＝「验证没能发生」，
            # 不是「验证发现了缺陷」：保持当前状态不流转 bug-found、不派生 fix
            # （2026-08-28 chain_exhausted 误产空壳 fix 实证），由 full_scan
            # recovery 兜底重排；冷却到期后下一次扫描即恢复验证。
            self._pm.state_machine.update_spec(spec_name, {
                "error": result.error,
            })
            self._pm.logger.warning(
                "pm_engine",
                f"Verifier infra failure — holding '{spec_name}' state, "
                f"no bug-found: {result.error}",
            )
            return

        if result.success:
            # 环境性失联门禁（legacy 路径同样生效）：旧版 verifier 若在 report.json
            # 中标记了 blocked-env 且全批环境性失联，则同样判定 inconclusive 重派，
            # 不判 bug-found（防假阴性派生 fix 家族）。
            report = self._pm._read_verify_report(spec_name)
            if self._pm._handle_env_blocked_inconclusive(spec_name, report):
                return
            run_result_path = self._pm.project_root / ".fenix" / ".fenix-run-result.json"
            verifier_status = self._pm._read_verifier_result(run_result_path)
            # 结果文件新鲜度/归属护栏：共享单文件会被任何 spec 的后续运行覆写，
            # 陈旧或异 spec 的判定重放到当前轮次 = 假 bug-found / 假 verified
            # （2026-08-28 improve-failover-model-mapping-ui 09:41 旧判定 12:21 重放实证）。
            if self._pm._verifier_result_is_stale(result, run_result_path, spec_name):
                self._pm.state_machine.update_spec(spec_name, {
                    "status": "implemented",
                    "tester_run": None,
                    "error": "stale/foreign verifier result replayed — re-dispatching fresh verify",
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Stale/foreign verifier result for '{spec_name}' — "
                    f"re-dispatching fresh verification",
                )
                return
            if verifier_status == "bug-found":
                # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
                report_blocker = self._pm._ensure_verification_report(spec_name)
                if report_blocker:
                    self._pm.state_machine.update_spec(spec_name, {
                        "error": report_blocker,
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"验证报告闸门: '{spec_name}' 阻止推进 bug-found — {report_blocker}",
                    )
                    return

                # verified 洗白门禁（help-center 0/15 verified 事故防线）：
                # 0 通过或 env 失败不得放行，升级 admin 处置
                if not self._pm._env_whitewash_gate(spec_name):
                    return
                # Verifier final state reconciliation (fix-startup-double-dispatch):
                # If spec state is not "testing" due to race conditions, reconcile
                current_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                if current_status != "testing":
                    # State changed by race condition - reconcile
                    if current_status == "implemented":
                        # Verification passed and implementation merged - replay legal path
                        self._pm.logger.info(
                            "pm_engine",
                            f"Reconciling '{spec_name}': verification found bugs, "
                            f"but spec is in '{current_status}' - replaying to bug-found",
                        )
                        # Replay: implemented → testing → bug-found
                        if self._pm.state_machine.is_valid_transition(current_status, "testing"):
                            self._pm.state_machine.transition(spec_name, "testing")
                            self._pm.state_machine.transition(spec_name, "bug-found")
                        else:
                            # Cannot transition - block with evidence
                            self._pm.state_machine.update_spec(spec_name, {
                                "status": "blocked",
                                "error": f"Verification found bugs but cannot reconcile state "
                                         f"from '{current_status}': {result.error}",
                            })
                            return
                    else:
                        # Other state - block with evidence
                        self._pm.state_machine.update_spec(spec_name, {
                            "status": "blocked",
                            "error": f"Verification found bugs but spec is in unexpected state "
                                     f"'{current_status}': {result.error}",
                        })
                        return

                self._pm.state_machine.transition(spec_name, "bug-found")
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": result.run_id,
                    "error": "Verification found bugs — see verification report",
                    "_inconclusive_attempts": 0,
                })
                self._pm.logger.warning(
                    "pm_engine",
                    f"Verifier (legacy) found bugs in '{spec_name}'",
                )
                # ── 守卫二：spawn 抑制（fix-repair-lane-dedup / design 守卫二）──
                if self._pm._is_fix_spec(spec_name):
                    cur = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                    if cur in ("ready", "implementing"):
                        self._pm.logger.info(
                            "pm_engine",
                            f"守卫二：'{spec_name}' 为 fix spec 且自身 {cur}"
                            f"（重实现在飞）——跳过派生子 fix（legacy 路径）",
                        )
                        self._pm.state_machine.update_spec(spec_name, {
                            "error": "修复由在飞重实现承载，跳过派生子 fix",
                        })
                        return
                self._pm._on_spec_bug_found(spec_name)
            else:
                # D6: legacy 路径同样前置进度核对：done>=total 才晋级
                vblocker = self._pm._check_verification_gate(spec_name)
                if vblocker:
                    self._pm.state_machine.update_spec(spec_name, {
                        "tester_run": result.run_id,
                        "error": vblocker,
                    })
                    self._pm.logger.warning(
                        "pm_engine",
                        f"验证未完成 (legacy) '{spec_name}'，阻止晋级 verified: {vblocker}",
                    )
                    return
                # 验证报告产物闸门（add-verify-report-gate，legacy 路径同闸门）
                report_blocker = self._pm._ensure_verification_report(spec_name)
                if report_blocker:
                    self._pm.state_machine.update_spec(spec_name, {
                        "tester_run": result.run_id,
                        "error": report_blocker,
                    })
                    self._pm.logger.error(
                        "pm_engine",
                        f"验证报告闸门: '{spec_name}' 阻止晋级 verified — {report_blocker}",
                    )
                    return

                # verified 洗白门禁（help-center 0/15 verified 事故防线）：
                # 0 通过或 env 失败不得放行，升级 admin 处置
                if not self._pm._env_whitewash_gate(spec_name):
                    return
                # Verifier final state reconciliation (fix-startup-double-dispatch):
                # If spec state is not "testing" due to race conditions, reconcile
                current_status = (self._pm.state_machine.read_one(spec_name) or {}).get("status", "")
                if current_status != "testing":
                    # State changed by race condition - reconcile
                    if current_status == "implemented" and verifier_status != "bug-found":
                        # Verification passed and implementation merged - replay legal path
                        self._pm.logger.info(
                            "pm_engine",
                            f"Reconciling '{spec_name}': verification passed, "
                            f"but spec is in '{current_status}' - replaying to verified",
                        )
                        # Replay: implemented → testing → verified
                        if self._pm.state_machine.is_valid_transition(current_status, "testing"):
                            self._pm.state_machine.transition(spec_name, "testing")
                            self._pm.state_machine.transition(spec_name, "verified")
                        else:
                            # Cannot transition - block with evidence
                            self._pm.state_machine.update_spec(spec_name, {
                                "status": "blocked",
                                "error": f"Verification passed but cannot reconcile state "
                                         f"from '{current_status}'",
                            })
                            return
                    else:
                        # Other state or verification failed - block with evidence
                        self._pm.state_machine.update_spec(spec_name, {
                            "status": "blocked",
                            "error": f"Verification result mismatch: spec is in '{current_status}' "
                                     f"but verifier reported '{verifier_status}'",
                        })
                        return

                self._pm.state_machine.transition(spec_name, "verified")
                self._pm.state_machine.update_spec(spec_name, {
                    "tester_run": result.run_id,
                    "error": None,
                    "_inconclusive_attempts": 0,
                    # add-fail-counter-budget D1：PASS 唯一归零点（legacy 路径同语义）。
                    "_verify_fail_rounds": 0,
                    "_env_block_rounds": 0,
                })
                self._pm._on_spec_verified(spec_name)
        else:
            self._pm.state_machine.transition(spec_name, "bug-found")
            self._pm.state_machine.update_spec(spec_name, {
                "tester_run": result.run_id,
                "error": f"Verifier agent failed: {result.error}",
            })


    @staticmethod
    def _load_frozen_scenarios(verify_dir: Path):
        """读取冻结场景集（scenario-reuse-on-reenter）。

        Returns:
            list[TestScenario]：冻结集有效（验收通过的原班场景）；
            None：无冻结文件（首次出题，走 planner 设计流程）；
            "corrupt"：文件存在但验收失败（损坏/结构非法/为空）——场景一经
            冻结跨轮一致，变更须 admin 裁决，绝不静默重新出题。
        """
        from core.verify_engine.scenarios import load_scenarios
        path = verify_dir / "test_scenarios.json"
        if not path.is_file():
            return None
        try:
            scenarios = load_scenarios(path)
        except Exception:
            return "corrupt"
        return scenarios if scenarios else "corrupt"

    def _env_whitewash_gate(self, spec_name: str) -> bool:
        """verified 推进前的洗白不变量门禁（help-center 0/15 verified 事故防线）。

        verdict=verified 但 0 通过或存在 env 分类失败 → 阻断推进并升级：
        阻塞 spec → 自动呼叫 Administrator 处置环境 → 连续
        ENV_BLOCK_FREEZE_THRESHOLD 轮仍 env → 结构化冻结转人工。
        Returns: True=放行推进 verified；False=已升级处置（调用方直接 return）。
        """
        from core.verdict_check import load_report, whitewash_violations
        scenarios = []
        report = load_report(self._pm.project_root, spec_name)
        if report:
            scenarios = report.get("scenarios") or []
        if not scenarios:
            # report.json 缺位时回退结果文件场景（fast-track 等价路径）；
            # 读取异常一律视为无数据（门禁不制造新的失败模式）
            try:
                ft = self._pm._read_implementer_result(spec_name) or {}
                verification = ft.get("verification")
                if isinstance(verification, dict):
                    scenarios = verification.get("scenarios") or []
            except Exception:
                scenarios = []
        if not scenarios:
            return True  # 无场景数据不拦（保守放行，交既有闸门兜底）
        violations = whitewash_violations(scenarios, "verified")
        if not violations:
            return True
        self._pm.logger.warning(
            "pm_engine",
            f"verified 洗白门禁拦截 '{spec_name}': {'；'.join(violations)}",
        )
        self._escalate_env_blocked(spec_name, violations)
        return False

    def _escalate_env_blocked(self, spec_name: str, violations: list,
                              title: str = "验证环境阻塞") -> None:
        """阻塞升级通道：阻塞 spec → 自动呼叫 Administrator → 达阈值冻结转人工。

        help-center 事故语义（0/15 verified 被全量 env 豁免后推成 pushed）：
        env 失败绝不放行。首轮阻塞并自动呼叫 Administrator（依赖安装/服务
        重启/端口清理在其权限内），处置完成走既有重验证；连续 2 轮仍阻塞 →
        frozen 结构化冻结 + 人工升级告警——admin 权限也无法处理时唯一出口是
        人工介入。title 区分升级类别（验证环境阻塞 / 场景计划争议）。
        """
        try:
            spec = self._pm.state_machine.read_one(spec_name) or {}
            rounds = int(spec.get("_env_block_rounds") or 0) + 1
            frozen = rounds >= 2  # 阈值：连续 2 轮阻塞 → 冻结转人工
            error_msg = (
                f"用户指令冻结（{title}连续 {rounds} 轮，admin 处置未奏效，"
                f"转人工）：{'；'.join(violations[:3])}"
                if frozen else
                f"{title}（第 {rounds} 轮）：{'；'.join(violations[:3])}"
            )
            entry = {
                "status": "blocked",
                "error": error_msg,
                "_env_block_rounds": rounds,
            }
            if frozen:
                entry["frozen"] = True
            self._pm.state_machine.update_spec(spec_name, entry)
            if frozen:
                self._pm.logger.error(
                    "pm_engine",
                    f"'{spec_name}' {title}连续 {rounds} 轮，已冻结转人工",
                )
            else:
                self._pm.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' {title}第 {rounds} 轮，自动呼叫 Administrator 处置",
                )
            # 自动呼叫 Administrator：与 Dashboard 手动 invoke 同一信号通道
            # （.fenix/admin_invoke_request.json，daemon 主循环拾取派发）
            try:
                from core.dashboard.data import request_admin_invoke
                inv = request_admin_invoke(self._pm.project_root, spec_name, (
                    f"{title}自动升级（verified 洗白门禁/场景冻结复用）：{error_msg[:300]}。"
                    "请诊断并处置——典型动作：主树/worktree 依赖安装、被测服务"
                    "/dashboard 重启、端口占用清理、验证产物重建、裁决场景集"
                    "变更（修复/删除冻结文件）。环境与计划问题不是产品缺陷："
                    "不要打回实现分支、不要修改产品代码。处置完成后触发该 spec"
                    "重新验证。"
                ))
                if isinstance(inv, dict) and inv.get("conflict"):
                    self._pm.logger.info(
                        "pm_engine",
                        f"'{spec_name}' 已有进行中的 Admin 处置，跳过重复呼叫",
                    )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"'{spec_name}' admin 自动呼叫失败（不阻塞升级）: {e}",
                )
            try:
                self._pm._send_human_escalation_alert(
                    spec_name=spec_name,
                    signal_type="verify_env_blocked",
                    severity="critical" if frozen else "warning",
                    description=error_msg[:300],
                    evidence=(
                        f"spec={spec_name}; "
                        f"report=spec/changes/{spec_name}/verification-report.md"
                    ),
                    recommended_action=(
                        "等待 Administrator 自动处置并重验；若已冻结请人工检查"
                        "环境（依赖/服务/端口）后解冻重跑验证"
                    ),
                )
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine", f"env 阻塞人工告警失败: {e}")
        except Exception as e:
            # 升级通道自身失败不得抛穿裁决流程
            self._pm.logger.warning(
                "pm_engine", f"env 升级通道异常 '{spec_name}': {e}")

    def _verify_verdict_evidence(self, spec_name: str, retry_judge: bool = False) -> bool:
        """确定性校验裁决 report.json 的分类/证据合规，并按映射强制重写 status。

        流程（design D1-D3）：
          1. 读 report.json（judge 应在其中增强 classification/evidence）；
          2. validate_report：每个非 PASS 场景 MUST 有合法 classification + 非空 evidence；
          3. 不合规且 ``retry_judge`` 为真 → 走既有 judge 重试一次（同 run_planner 调用），
             重试后再次校验；二次仍不合规 → 返回 False（调用方 blocked-env + 告警）；
          4. 合规 → enforce_status_mapping（product-bug/test-defect → failed，D3），
             原子写回 report.json，返回 True。

        注意：judge 失败（process 级）已由调用方在 ``judge_result.success`` 处拦截，
        本方法只负责「judge 已成功但产物不合规」的确定性校验与重试。
        """
        from core.verdict_check import (
            validate_report, enforce_status_mapping, load_report, save_report,
        )
        report = load_report(self._pm.project_root, spec_name)
        if report is None:
            # 无 report.json：验证产物门禁（verify-report-gate）会兜底，此处不阻断
            # （不制造伪 violation），交由既有流程处理。
            return True

        result = validate_report(report)
        if result["ok"]:
            # 合规：清掉历史驳回清单（若有）后强制重写 status 映射（D3）写回
            self._pm._clear_verdict_violations(spec_name)
            mapping = enforce_status_mapping(report)
            if mapping["corrected"]:
                try:
                    save_report(self._pm.project_root, spec_name, report)
                except OSError as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"裁决映射重写写回失败 '{spec_name}': {e}",
                    )
                for c in mapping["corrected"]:
                    self._pm.logger.info(
                        "pm_engine",
                        f"裁决映射强制重写 '{spec_name}' 场景 {c['scenario_id']}: "
                        f"{c['from_status']} → failed ({c['classification']})",
                    )
            return True

        # 一次不合规：judge 重试一次（design D2）；违规明细落盘供重试 prompt 注入
        if retry_judge:
            violations_1 = result["violations"]
            self._pm._write_verdict_violations(spec_name, violations_1)
            self._pm.logger.warning(
                "pm_engine",
                f"裁决证据分类校验未通过 '{spec_name}'（{len(violations_1)} 项），"
                f"重试 judge 一次：{[v['scenario_id'] for v in violations_1]}",
            )
            try:
                re_judge = self._pm.agent_runner.run_planner(spec_name, "judge")
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine", f"裁决重试 judge 异常 '{spec_name}': {e}",
                )
                re_judge = None
            if re_judge is not None and not re_judge.success:
                self._pm.logger.warning(
                    "pm_engine",
                    f"裁决重试 judge 失败 '{spec_name}': {re_judge.error}",
                )
                return False
            report2 = load_report(self._pm.project_root, spec_name)
            if report2 is None:
                return False
            result2 = validate_report(report2)
            if result2["ok"]:
                self._pm._clear_verdict_violations(spec_name)
                mapping2 = enforce_status_mapping(report2)
                try:
                    save_report(self._pm.project_root, spec_name, report2)
                except OSError as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"裁决映射重写写回失败 '{spec_name}': {e}",
                    )
                for c in mapping2["corrected"]:
                    self._pm.logger.info(
                        "pm_engine",
                        f"裁决重试后映射强制重写 '{spec_name}' 场景 "
                        f"{c['scenario_id']}: {c['from_status']} → failed",
                    )
                return True
            self._pm.logger.error(
                "pm_engine",
                f"裁决重试后证据分类仍不合规 '{spec_name}'："
                f"{[v['scenario_id'] for v in result2['violations']]}",
            )
            return False

        return False


    def _update_warning_streaks(self, spec_name: str) -> list:
        """更新 warning 连续悬置计数侧车（design D4 / D5）。

        采纳 report.json 后调用：扫描非 PASS 场景——
          - status == warning 且 classification ∈ {flaky, env} 的场景：连续计数 +1；
          - status 为 pass/failed（含被强制重写的 failed）或 classification 为
            product-bug/test-defect 的场景：计数清零。

        返回本轮回填后「连续计数 == 2」的场景 id 列表（即触发 triage 升级的候选），
        调用方据此发告警。侧车文件：``.fenix/verify-progress/<spec>/warning_streaks.json``，
        结构 {scenario_id: 连续轮数}。
        """
        from core.verdict_check import VERDICT_CLASSES, load_report, save_report
        streaks_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "warning_streaks.json"
        )
        streaks = {}
        if streaks_path.exists():
            try:
                loaded = json.loads(streaks_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    streaks = {k: int(v) for k, v in loaded.items()
                               if isinstance(k, str)}
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                streaks = {}

        report = load_report(self._pm.project_root, spec_name)
        if report is None:
            return []
        scenarios = report.get("scenarios")
        if not isinstance(scenarios, list):
            return []

        triage_candidates = []
        for sc in scenarios:
            if not isinstance(sc, dict):
                continue
            sid = sc.get("scenario_id") or sc.get("id")
            if not sid:
                continue
            status = sc.get("status")
            classification = sc.get("classification")
            # 仅 flaky/env 的 warning 计入连续悬置；product-bug/test-defect 已强制
            # failed（D3），不悬置；pass/failed 清零（D4）。
            if status == "warning" and classification in ("flaky", "env"):
                streaks[sid] = streaks.get(sid, 0) + 1
                if streaks[sid] == 2:
                    triage_candidates.append(sid)
            else:
                streaks[sid] = 0

        # 写回侧车
        try:
            streaks_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(streaks_path.parent), prefix=".warning_streaks.",
                suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(streaks, f, ensure_ascii=False, indent=2)
                    f.flush()
                os.replace(tmp_path, streaks_path)
            except OSError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"warning_streaks 写回失败 '{spec_name}': {e}",
            )
        return triage_candidates


    def _warning_stale_triage_alert(self, spec_name: str, scenario_ids: list) -> None:
        """连续 2 轮 warning 场景的 triage 升级告警（design D4 / D5）。

        signal_type=warning_stale_triage，含 spec/场景/轮次/最近证据摘要；
        同时把场景写入下一轮 planner prompt 的「优先复核」注入（与 scenario-freeze
        的基准集注入同一接入点——复用 _scenario_freeze_section 机制：把 triage 场景
        落盘到 verify-progress/<spec>/triage_recheck.json，planner prompt 读取后注入）。
        """
        from core.verdict_check import load_report
        # 证据摘要：从该场景的 evidence.failed_assertions / first_failed_step 摘取
        evidence_lines = []
        report = load_report(self._pm.project_root, spec_name)
        latest_round = 2
        if isinstance(report, dict):
            for sc in report.get("scenarios", []) or []:
                if not isinstance(sc, dict):
                    continue
                sid = sc.get("scenario_id") or sc.get("id")
                if sid not in scenario_ids:
                    continue
                ev = sc.get("evidence") if isinstance(sc.get("evidence"), dict) else {}
                ffs = ev.get("first_failed_step") or ""
                fa = ev.get("failed_assertions") or []
                fa_summary = "; ".join(
                    f"{a.get('type','?')}({a.get('selector','')})"
                    for a in fa if isinstance(a, dict)
                ) if isinstance(fa, list) else ""
                evidence_lines.append(
                    f"场景 {sid}（classification={sc.get('classification')}, "
                    f"连续 {latest_round} 轮 warning）：{ffs}"
                    + (f"；失败断言：{fa_summary}" if fa_summary else "")
                )
        evidence = "\n".join(evidence_lines) or (
            f"连续 2 轮 warning 场景：{', '.join(scenario_ids)}"
        )

        self._pm._send_human_escalation_alert(
            spec_name=spec_name,
            signal_type="warning_stale_triage",
            severity="critical",
            description=(
                f"'{spec_name}' 以下场景连续 {latest_round} 轮均为 warning，"
                f"需人工 triage 甄别是否真缺陷被悬置：{', '.join(scenario_ids)}"
            ),
            evidence=evidence,
            recommended_action=(
                f"人工复核 {', '.join(scenario_ids)} 的真实根因；下一轮验证已将其"
                f"列入优先复核清单（triage_recheck.json）"
            ),
        )
        # 下一轮 planner prompt 优先复核注入（design D5）：落盘 triage_recheck.json
        recheck_path = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "triage_recheck.json"
        )
        try:
            recheck_path.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if recheck_path.exists():
                try:
                    data = json.loads(recheck_path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        existing = data
                except (json.JSONDecodeError, OSError):
                    existing = []
            merged = list(dict.fromkeys(existing + scenario_ids))
            recheck_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"triage_recheck 写盘失败 '{spec_name}': {e}",
            )


    def _ensure_verification_report(self, spec_name: str) -> str | None:
        """验证报告产物闸门（add-verify-report-gate）。

        在验证裁决采纳处（verified / bug-found 即将推进）调用：校验
        spec/changes/<spec>/verification-report.md 存在；缺失时由框架从
        结构化数据确定性合成（不重跑验证、不覆盖既有文件）并发人工升级告警；
        结构化数据也不可用时 fail-closed。

        返回 None 表示放行（报告已存在或合成成功）；返回非空字符串为阻断原因，
        调用方须阻止状态推进并把原因写入 error 字段。
        """
        from core.verify_report import ensure_verification_report
        try:
            result = ensure_verification_report(
                self._pm.project_root, spec_name, logger=self._pm.logger,
            )
        except Exception as e:
            # 合成器自身异常等同数据不可用：fail-closed，不凭空放行
            return f"验证报告缺失且无法合成：闸门异常 {e}"
        if result.get("ok"):
            return None
        return result.get("error") or "验证报告缺失且无法合成"


    def _check_verification_gate(self, spec_name: str) -> str | None:
        """验证完成度放行闸门（verification-completion-gate）。

        返回 None 表示门禁通过（可推进到 done）；返回非空字符串表示未完成原因，
        此时应阻断 verified→done，把原因写入 error 字段供人工裁决。

        判定规则：
        - 无进度文件（.fenix/verify-progress/<spec>.json 缺失）→ 放行
          （验证流程未启动，维持原推进路径，不影响存量 spec）。
        - 进度文件存在但解析失败 / 字段缺失 / done < total → 阻断，
          返回「验证未完成：done/total（+最近 current）」。
        - done == total → 放行。
        """
        from core.dashboard.data import parse_verify_progress
        vp = parse_verify_progress(self._pm.project_root, spec_name)
        if not vp.get("exists"):
            return None
        total = vp.get("total") or 0
        done = vp.get("done") or 0
        if vp.get("error") == "corrupt" or total <= 0 or done < total:
            current = vp.get("current") or ""
            tail = f"（当前：{current}）" if current else ""
            return f"验证未完成：{done}/{total}{tail}"
        return None


    def _read_verifier_result(self, result_path: Path) -> str | None:
        """读取 verifier 写入的 .fenix-run-result.json，返回 status 字段。

        返回 None 表示文件不存在或格式无效（视为 verified）。
        返回 "verified" 表示全部通过。
        返回 "bug-found" 表示验证发现 Bug。
        返回 "plan-ready" 表示Planner已生成场景。
        """
        try:
            if not result_path.exists():
                self._pm.logger.warning(
                    "pm_engine",
                    f"Verifier result file not found: {result_path}",
                )
                return None
            data = json.loads(result_path.read_text(encoding="utf-8"))
            status = data.get("status", "")
            if status in ("verified", "bug-found", "plan-ready"):
                bugs = data.get("bugs", [])
                bug_count = len(bugs) if isinstance(bugs, list) else 0
                self._pm.logger.info(
                    "pm_engine",
                    f"Verifier result: status={status}, bugs={bug_count}",
                )
                return status
            self._pm.logger.warning(
                "pm_engine",
                f"Unknown verifier status: '{status}', treating as verified",
            )
            return None
        except (json.JSONDecodeError, OSError) as e:
            self._pm.logger.warning(
                "pm_engine",
                f"Failed to read verifier result: {e}",
            )
            return None


    def _read_planner_result(self, spec_name: str) -> str | None:
        """读取 Planner 写入的结果文件，返回 status 字段。

        优先读 verify-progress/<spec>/.fenix-run-result.json（Planner prompt 中
        指定的确定性产物路径），回退主树 .fenix/.fenix-run-result.json（兼容旧行为：
        planner 把结果写到 worktree 根、由 _execute_agent 复制到主树的情况）。

        背景：主树 .fenix/.fenix-run-result.json 是共享文件，implementer 成功时也会
        写入（status=success/error）。planner 若把 plan-ready/verified 写到别处，
        pm_engine 误读主树共享文件会看到 implementer 残留状态（不在
        verified/bug-found/plan-ready 白名单），误判「Planner 未生成有效场景」，
        进而降级旧版 verifier 导致验证反复失败（admin 处置根因）。
        """
        primary = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / ".fenix-run-result.json"
        )
        if primary.exists():
            return self._pm._read_verifier_result(primary)
        fallback = self._pm.project_root / ".fenix" / ".fenix-run-result.json"
        # 共享结果文件护栏：主树共享文件携带的 spec 与当前 spec 不符时视为残留忽略
        # （与 _read_implementer_result 相同语义），避免误读其它 spec 的
        # implementer 残留状态。
        if fallback.exists():
            try:
                fb_data = json.loads(fallback.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return self._pm._read_verifier_result(fallback)
            stamped = fb_data.get("spec") if isinstance(fb_data, dict) else None
            if isinstance(stamped, str) and stamped and stamped != spec_name:
                self._pm.logger.warning(
                    "pm_engine",
                    f"Ignoring stale result file {fallback}: "
                    f"spec='{stamped}' != '{spec_name}'",
                )
                return None
        return self._pm._read_verifier_result(fallback)


    def _judge_bugs_declare_env(self, spec_name: str) -> bool:
        """judge 判 bug-found 但其自述根因全部为环境/基础设施问题时返回 True。

        2026-08-28 实证：planner 重新生成的场景用相对 URL "/dashboard"（无效
        URL）+ 幻觉 testid，12 个场景全部在导航步失败；judge 在结果文件中
        自述「这是一个环境问题，而非产品 Bug」，却把 status 标为 bug-found，
        pm_engine 据此派生伪 fix 级联。此处以 judge 自己的根因描述为准：
        所有 bug 均自述环境/基础设施问题时，按「验证没能发生」处理。
        """
        primary = (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / ".fenix-run-result.json"
        )
        if not primary.exists():
            return False
        try:
            data = json.loads(primary.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        bugs = data.get("bugs") if isinstance(data, dict) else None
        if not isinstance(bugs, list) or not bugs:
            return False

        def _declares_env(bug) -> bool:
            if not isinstance(bug, dict):
                return False
            text = f"{bug.get('root_cause', '')} {bug.get('description', '')}"
            return any(marker in text for marker in self._pm._ENV_INFRA_MARKERS)

        return all(_declares_env(bug) for bug in bugs)


    def _handle_judge_env_declared(self, spec_name: str) -> bool:
        """judge 自述环境问题时按 inconclusive 处理（不派生 fix）。

        与 _handle_env_blocked_inconclusive 同语义：回 implemented 重派新
        attempt，不 transition bug-found、不派生 fix spec；超限后暂停自动
        重验并暴露错误等待人工（无界重验会烧 token）。
        """
        spec = self._pm.state_machine.read_one(spec_name) or {}
        try:
            attempts = int(spec.get("_inconclusive_attempts", 0) or 0) + 1
        except (TypeError, ValueError):
            attempts = 1
        max_attempts = int(
            self._pm._get_config("verify_engine.inconclusive_max_attempts", 3) or 3
        )
        note = (
            f"judge 判定 bug-found 但所有 bug 根因均自述为环境/基础设施问题"
            f"（伪失败，不派生 fix），第 {attempts}/{max_attempts} 次重验"
        )
        if attempts < max_attempts:
            self._pm.logger.warning("pm_engine", f"'{spec_name}' {note}")
            self._pm.state_machine.update_spec(spec_name, {
                "status": "implemented",
                "tester_run": None,
                "error": note,
                "_inconclusive_attempts": attempts,
            })
            self._pm._enqueue(spec_name, "verifier")
            return True

        # 连续 ≥max_attempts 轮均自述环境问题：停止自动重验，暴露错误等待人工。
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' 连续 {attempts} 轮 judge 均自述环境问题（伪失败），"
            f"暂停自动重验，请人工检查验证场景/环境",
        )
        self._pm.state_machine.update_spec(spec_name, {
            "status": "implemented",
            "tester_run": None,
            "error": (f"连续 {attempts} 轮验证均因环境/基础设施问题未完成"
                      f"（judge 自述），请人工检查验证场景/环境；不派生 fix"),
            "_inconclusive_attempts": attempts,
            "_dispatch_backoff_until": int(datetime.now(timezone.utc).timestamp()) + 1800,
        })
        return True


    def _verdict_violations_path(self, spec_name: str) -> Path:
        return (
            self._pm.project_root / ".fenix" / "verify-progress"
            / spec_name / "verdict_violations.json"
        )


    def _write_verdict_violations(self, spec_name: str, violations: list) -> None:
        """落盘裁决驳回清单（verdict-rejection-retry：judge 重试幂等陷阱修复）。

        fix-budget-counting-semantics 复盘：judge 首轮补齐 classification/evidence
        但漏 assertion_triage，重试 judge 读到已增强的 report 后判定「无需改写」
        再次跳过，校验必然复败 → blocked。将违规明细落盘，由 agent_runner 注入
        重试 prompt（见 _verdict_rejection_section），告知重试 judge 缺口所在。
        """
        try:
            path = self._pm._verdict_violations_path(spec_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(violations, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            self._pm.logger.warning(
                "pm_engine", f"裁决驳回清单写盘失败 '{spec_name}': {e}",
            )


    def _clear_verdict_violations(self, spec_name: str) -> None:
        try:
            self._pm._verdict_violations_path(spec_name).unlink(missing_ok=True)
        except OSError:
            pass

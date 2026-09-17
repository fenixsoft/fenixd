"""queries.py — G8 查询/枚举（纯 git 只读，refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 16 个方法（`core/worktree_manager/_legacy.py`），
原样搬移为 mixin（方法体零改动）。纯 git 只读查询，无跨组写操作。

`_impl_branch_owned_by_spec` 为 staticmethod（tests 类直调，
design D3 须留类命名空间——mixin 上的 staticmethod 经继承仍挂在类命名空间）。
"""

from __future__ import annotations

import subprocess
import time

from pathlib import Path

from core.worktree_manager import (  # noqa: E402
    WT_AVAILABLE,
    WT_REBUILDABLE,
    WT_UNAVAILABLE,
)


class G8QueryMixin:
    """G8 查询/枚举（纯 git 只读）——低耦合（design D1 表 A G8）。"""

    @staticmethod
    def _spec_from_worktree_name(wt_name: str) -> Optional[str]:
            """worktree 目录名（``{impl,verify}-<spec>-<ts>``）→ spec 名。

            spec 名自身可含连字符，因此取前缀之后、末段时间戳之前的部分；
            段数不足（非本框架产物）返回 None。
            """
            for prefix in ("impl", "verify"):
                if wt_name.startswith(f"{prefix}-"):
                    rest = wt_name[len(prefix) + 1 :]
                    parts = rest.rsplit("-", 1)
                    if len(parts) == 2 and parts[0] and parts[1].isdigit():
                        return parts[0]
            return None

    @staticmethod
    def _spec_from_branch(branch: str) -> Optional[str]:
            """分支名（``fenix/<spec>-<ts>`` / ``fenix/verify-<spec>-<ts>``）→ spec 名。

            实现 death 时据分支名回推 spec（cleanup 注册遗产用）。与 _spec_from_worktree_name
            对称：取 ``fenix/`` 之后、末段 ``-<ts>`` 之前的部分。verifier 分支含 ``verify-``
            前缀，去掉前缀后同样取到 spec。段数不足返回 None。
            """
            if not branch or not branch.startswith("fenix/"):
                return None
            rest = branch[len("fenix/") :]
            if rest.startswith("verify-"):
                rest = rest[len("verify-") :]
            parts = rest.rsplit("-", 1)
            if len(parts) == 2 and parts[0] and parts[1].isdigit():
                return parts[0]
            return None

    def file_exists_on_branch(self, branch: str, rel_path: str) -> bool:
            """校验某相对路径在分支 HEAD 提交中是否存在（交付物守卫校验基准）。

            实现 run 收工时 worktree 已被清理，唯一留存的交付物是分支提交。
            用 ``git cat-file -e <branch>:<rel_path>`` 做 O(1) 存在性检查——
            纯文件系统/对象库探测，不触发 LLM / 测试 / 网络。

            Args:
                branch: 实现分支名（AgentRunResult.branch）
                rel_path: 相对项目根的交付路径（如 ``core/foo.py``）

            Returns:
                True 表示分支 HEAD 包含该路径（blob 文件，或非空 tree 目录）。
                分支为空 / 不存在 / 路径不存在时返回 False。
            """
            if not branch or not rel_path:
                return False
            try:
                # -e 仅判断对象可达（blob/tree/symlink），不输出内容，零成本。
                result = subprocess.run(
                    ["git", "-C", str(self.project_root), "cat-file", "-e", f"{branch}:{rel_path}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    return False
                kind = subprocess.run(
                    ["git", "-C", str(self.project_root), "cat-file", "-t", f"{branch}:{rel_path}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if kind.returncode != 0:
                    return False
                # blob（文件）= 落地交付物；tree（目录）同样算落地——git 不追踪空目录，
                # path 为 tree 必然内含文件（如构建产物 dist/ 整目录声明）。
                # 曾为 blob-only：目录声明成为不可满足契约 → 收工守卫确定性缺件 →
                # 打回循环烧预算至 blocked（remove-auto-run-cleanup 死锁事故 2026-09-03）。
                # symlink 等其余类型不算。
                return kind.stdout.strip() in ("blob", "tree")
            except subprocess.TimeoutExpired:
                return False
            except Exception:
                return False

    def is_available(self, wt_path=None, branch=None) -> str:
            """worktree 可用性三态单源查询（interrupt-recovery-preserve D5）。

            三态：
              - ``WT_AVAILABLE``（available）：分支可解析 + worktree 目录在场 +
                ``git worktree list`` 注册有效 → 原地可用，resume/reuse 直接进入；
              - ``WT_REBUILDABLE``（rebuildable）：分支可解析但无有效 worktree
                目录/注册（目录被外部删除、或从未在该分支建过 worktree）→ 可在
                既有分支上重建（checkout 而非 ``-b`` 新建）；
              - ``WT_UNAVAILABLE``（unavailable）：分支不可解析（已并入主树/已
                清扫/typo 分支名）→ 不可用，调用方降级到清空重建。

            Args:
                wt_path: 候选 worktree 路径（Path/str，可选）。提供时与 git 注册
                    结果核对：与注册不符的残留目录不视为可用（以 git 为准）。
                branch: 分支名（可选）。缺省时尝试从 wt_path 的 HEAD 解析分支。

            Returns: 三态字符串之一（WT_* 常量）。
            """
            if not branch:
                if wt_path is not None:
                    branch = self._guess_branch_from_worktree(wt_path)
                if not branch:
                    branch = self._wt_branches.get(str(wt_path)) if wt_path is not None else None
                if not branch:
                    return WT_UNAVAILABLE
            if not self.branch_exists(branch):
                return WT_UNAVAILABLE
            registered = self.find_worktree_path(branch)
            if wt_path is not None:
                # 显式候选路径：以其自身目录存在性为「原地可用」判据——防止对
                # 已删目录盲派发（fix-resume-stale-worktree 同源缺口）。目录残留
                # 但非本分支 git 注册 worktree 时同样不可原地使用（以 git 为准）。
                candidate = Path(wt_path)
                if not candidate.is_dir():
                    return WT_REBUILDABLE  # 分支在 → 可从分支重建
                if registered is not None and str(Path(registered)) == str(candidate):
                    return WT_AVAILABLE
                return WT_REBUILDABLE
            # 未给候选路径：以 git 注册为真相
            if registered is None or not Path(registered).is_dir():
                # 分支可解析但 git 无有效注册 worktree：目录即使残留也不可用，
                # 应从分支重建载体。
                return WT_REBUILDABLE
            return WT_AVAILABLE

    def create_worktree_on_branch(self, spec_name: str, branch: str) -> Optional[Path]:
            """在既有分支上创建 worktree（checkout 而非 ``-b`` 新建），供 repair 换壳。

            worktree 目录名 ``repair-<spec>-<ts>``（区别于 impl-/verify- 前缀，
            Dashboard/runs 检索据此辨识）。仅登记活动集与分支映射，不 seed spec
            文件（分支已含实现历史，spec 文档已在其中）。

            Returns: worktree 路径，失败（分支不存在/该分支已有 worktree/git
            错误/异常）返回 None。
            """
            if not branch:
                return None
            timestamp = int(time.time())
            wt_name = f"repair-{spec_name}-{timestamp}"
            wt_path = self.base_dir / wt_name
            try:
                # 分支必须存在（rev-parse --verify 精确校验，防 typo 分支名）
                verify = subprocess.run(
                    ["git", "-C", str(self.project_root), "rev-parse", "--verify", branch],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if verify.returncode != 0:
                    self.logger.warning(
                        "worktree_manager",
                        f"create_worktree_on_branch: branch '{branch}' not found — "
                        f"cannot re-shell repair site for '{spec_name}'",
                    )
                    return None
                # 清理陈注册（interrupt-recovery-preserve D5）：目录被外部删除但
                # worktree 注册仍在时，git 会拒绝「该分支已 checkout」。prune 只
                # 移除目录已消失的注册，安全幂等；失败不阻塞（create 自会报错）。
                try:
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "worktree", "prune"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    pass
                result = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "add", str(wt_path), branch],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    self.logger.error(
                        "worktree_manager",
                        f"Failed to create worktree on branch '{branch}': {result.stderr}",
                    )
                    return None
                self._active_worktrees.add(str(wt_path))
                self._wt_branches[str(wt_path)] = branch
                self.logger.info(
                    "worktree_manager",
                    f"Worktree re-shelled on existing branch '{branch}': {wt_path}",
                )
                return wt_path
            except subprocess.TimeoutExpired:
                self.logger.error("worktree_manager", "Worktree-on-branch creation timed out")
                return None
            except Exception as e:
                self.logger.error("worktree_manager", f"Worktree-on-branch creation error: {e}")
                return None

    def find_worktree_path(self, branch: str) -> Optional[Path]:
            """按分支解析 worktree 路径（``git worktree list --porcelain`` 为准）。

            add-merge-back-repair-lane D3：以 git 事实为判定基准，不信任内存
            ``_active_worktrees``（daemon 重启即失）。同一分支 git 只允许一个
            worktree（``worktree add <path> <branch>`` 对已 checkout 分支会拒绝），
            故首个匹配即唯一。

            Returns: worktree 绝对路径，无匹配/命令失败返回 None。
            """
            if not branch:
                return None
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "list", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except subprocess.TimeoutExpired:
                return None
            if res.returncode != 0:
                return None
            current_path: Optional[str] = None
            for line in res.stdout.splitlines():
                if line.startswith("worktree "):
                    current_path = line[len("worktree ") :].strip()
                elif line.startswith("branch "):
                    listed_branch = line[len("branch ") :].strip()
                    # porcelain 格式：branch refs/heads/<name>；HEAD <sha> 行只是
                    # 头部提交指针，不是 detached 判定——detached worktree 缺失
                    # branch 行（该 section 不会匹配具名分支，下个 worktree 行覆盖）
                    if listed_branch == f"refs/heads/{branch}" and current_path:
                        return Path(current_path)
            return None

    def find_worktree_by_spec(self, spec_name: str) -> Optional[tuple]:
            """按 spec 名反查在册 worktree 与其分支（fix-preserve-chain-first-round-gap D1）。

            保全（``_preserve_interrupted_runs``）与恢复保留判定
            （``_recovery_preserve_spec``）在 STATE ``branch`` 缺失（首轮在飞
            run 未到终态）时的回落源：以 ``git worktree list --porcelain`` 为
            真相，不信任 ``_active_worktrees`` / ``_wt_branches`` 内存表（daemon
            重启即失，不足以支撑 boot 路径）。

            - 按 worktree 目录命名约定（``impl-<spec>-<ts>`` / ``verify-<spec>-<ts>``
              / ``repair-<spec>-<ts>``，见 create/create_worktree_on_branch）以
              **完整 spec 名 + 分隔符边界**匹配（解析命名得完整 spec 名再精确比较，
              禁止子串包含：spec 名互为前缀如 ``fix-x`` 与 ``fix-x-y`` 不误匹配）；
            - 歧义命中（同一 spec 存在多个在册 worktree）MUST NOT 静默取首个，
              返回 None 并 WARNING；
            - 候选经 ``is_available`` 三态单源校验：非 available/rebuildable
              不作保全与保留依据；
            - 命令超时/非零退出/异常降级 WARNING 返回 None，MUST NOT 阻塞停机路径。

            Returns: ``(wt_path, branch)`` 元组；无匹配/歧义/不可用/git 失败返回 None。
            """
            if not spec_name:
                return None
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "list", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (subprocess.TimeoutExpired, OSError) as e:
                self.logger.warning(
                    "worktree_manager",
                    f"find_worktree_by_spec('{spec_name}') 查询失败（降级不阻塞）: {e}",
                )
                return None
            if res.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"find_worktree_by_spec('{spec_name}') git 非零退出（降级不阻塞）: "
                    f"{res.stderr.strip()}",
                )
                return None

            # porcelain 渲染：`worktree <path>` 开新段，其后属行（HEAD/branch）属于
            # 该段；detached worktree 无 branch 行，取不到具名分支，不作保全依据。
            candidates: list = []  # (wt_path, branch) 具名精确匹配的候选
            current_path: Optional[str] = None
            for line in res.stdout.splitlines():
                if line.startswith("worktree "):
                    current_path = line[len("worktree ") :].strip()
                    continue
                if line.startswith("branch ") and current_path:
                    listed_branch = line[len("branch ") :].strip()
                    if listed_branch.startswith("refs/heads/"):
                        listed_branch = listed_branch[len("refs/heads/") :]
                    if self._wt_name_matches_spec(Path(current_path).name, spec_name):
                        candidates.append((current_path, listed_branch))

            if not candidates:
                return None
            # is_available 三态单源校验：非 available/rebuildable 候选不作为依据
            valid: list = []
            for path, branch in candidates:
                state = self.is_available(path, branch)
                if state in (WT_AVAILABLE, WT_REBUILDABLE):
                    valid.append((path, branch))
                else:
                    self.logger.warning(
                        "worktree_manager",
                        f"find_worktree_by_spec('{spec_name}'): 候选 {path} "
                        f"(branch {branch}) 三态 {state}，不作保全/保留依据",
                    )
            if len(valid) > 1:
                self.logger.warning(
                    "worktree_manager",
                    f"find_worktree_by_spec('{spec_name}'): 歧义命中 {len(valid)} 个 "
                    f"在册 worktree（{[p for p, _ in valid]}）——不静默取首个，"
                    f"按不可用处理",
                )
                return None
            if valid:
                return valid[0]
            return None

    def find_worktrees_by_spec(self, spec_name: str) -> list:
            """按 spec 名列出**全部**在册 worktree 路径（fix-recovery-branch-anchor D5）。

            与 ``find_worktree_by_spec`` 同源（``git worktree list --porcelain``
            真相 + 完整 spec 名 + 分隔符边界口径），但**不**做三态校验、**不**
            因歧义返回 None——停机保护集构造需要「同一 spec 的多个在册 worktree」
            的全部路径（「impl 已清只剩 repair」之外的常见形态：同一 spec 有
            impl- 与 repair- 两个在册 worktree）。

            算法：解析所有在册 worktree 的目录名，凡 ``_wt_name_matches_spec``
            命中即加入返回（目录名口径天然覆盖 impl/verify/repair 三种前缀）。

            防御口径与 ``find_worktree_by_spec`` 同款：命令超时/非零退出/异常
            降级返回空清单，MUST NOT 阻塞调用路径。

            Returns: 在册 worktree 路径列表（str）；无匹配/git 失败返回 []。
            """
            if not spec_name:
                return []
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "worktree", "list", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (subprocess.TimeoutExpired, OSError) as e:
                self.logger.warning(
                    "worktree_manager",
                    f"find_worktrees_by_spec('{spec_name}') 异常降级空清单: {e}",
                )
                return []
            if res.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"find_worktrees_by_spec('{spec_name}'): 非零退出→空清单 " f"(rc={res.returncode})",
                )
                return []
            paths: list = []
            current_path: Optional[str] = None
            for line in res.stdout.splitlines():
                if line.startswith("worktree "):
                    current_path = line[len("worktree ") :].strip()
                    if current_path and self._wt_name_matches_spec(Path(current_path).name, spec_name):
                        paths.append(current_path)
            return paths

    def find_branches_by_spec(self, spec_name: str) -> list:
            """按 spec 枚举候选实现分支（fix-recovery-branch-anchor D2/B，第三层回落）。

            事实源为 git refs（``git for-each-ref``），与 worktree 是否在册无关——
            覆盖「run 已成功、worktree 已清、branch 未落盘」窗口（本 SPEC 事故环 4）。

            - 枚举前缀与分支**创建端同源**：创建端硬编码 ``fenix/``（``create()``
              :223/:226），配置 ``worktree.implement_branch_prefix`` 仅推送侧读取、
              非创建端事实源——本层取「配置值 ∪ 创建端 ``fenix/``」并集枚举，
              MUST NOT 仅凭配置值取前缀（非 fenix 配置下创建端仍产出
              ``fenix/<spec>-<ts>``，仅按配置枚举会扫空命名空间、本层静默失效）；
            - 候选口径为「完整 spec 名 + 分隔符边界」全等比较（与
              ``_wt_name_matches_spec`` / ``engine._resolve_push_branch`` 同口径）：
              去掉 ``<prefix>/`` 后按最后一个 ``-`` 分段，末段 MUST 为纯数字
              时间戳、其前段 MUST 与该 spec 名全等——spec 名互为前缀
              （``fix-x`` / ``fix-x-y``）时 glob 命中集合 MUST NOT 直接当候选；
              ``<prefix>/verify-<spec>-*`` 验证分支 MUST NOT 进入候选清单；
            - 排序（D2）：先取 ``git merge-base --is-ancestor main <branch>``
              成立者（repair 已把 main 合入分支的形态），按 committerdate 最新；
              无「已含 main」候选时取 ``git rev-list --count main..<branch>``
              最大者；**零提交候选（``main..branch`` 为空）自候选清单剔除、
              不参与排序**（闸门先于排序，见 tasks 2.5）；
            - 防御口径（2.3）：命令超时/非零退出/异常降级 WARNING 返回空清单，
              MUST NOT 阻塞 boot 路径；MUST NOT 依赖 ``_active_worktrees`` /
              ``_wt_branches`` 内存表。

            Returns: 候选清单，每项 dict:
                ``{"branch": str, "ahead": int, "main_is_ancestor": bool,
                  "committerdate": int}``
                按排序规则降序（最优在前）；无候选/失败返回 []。
            """
            if not spec_name:
                return []
            # 枚举前缀并集：创建端口径 fenix + 配置值（若不同）。MUST NOT 仅凭配置。
            prefixes = {"fenix", self._implement_branch_prefix or "fenix"}
            candidates: list = []  # {branch, ahead, main_is_ancestor, committerdate}
            try:
                for prefix in prefixes:
                    pattern = f"refs/heads/{prefix}/{spec_name}-*"
                    res = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.project_root),
                            "for-each-ref",
                            "--format=%(refname:short)|%(committerdate:unix)",
                            "--sort=-committerdate",
                            pattern,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if res.returncode != 0:
                        self.logger.warning(
                            "worktree_manager",
                            f"find_branches_by_spec('{spec_name}'): 枚举 "
                            f"'{pattern}' 非零退出（rc={res.returncode}）——降级空清单",
                        )
                        continue
                    for line in res.stdout.splitlines():
                        parts = line.split("|")
                        if not parts:
                            continue
                        name = parts[0].strip()
                        try:
                            cdate = int(parts[1].strip()) if len(parts) > 1 else 0
                        except ValueError:
                            cdate = 0
                        # 完整 spec 名 + 分隔符边界全等比较：去前缀后按最后一个
                        # `-` 分段，末段纯数字时间戳、其前段与 spec 名全等。
                        rest = name[len(prefix) + 1 :] if name.startswith(f"{prefix}/") else name
                        segs = rest.rsplit("-", 1)
                        if len(segs) != 2 or not segs[0] or not segs[1].isdigit():
                            continue
                        if segs[0] != spec_name:
                            # spec 名互为前缀（fix-x / fix-x-y）：非全等命中直接剔除
                            continue
                        # verify 验证分支 MUST NOT 进入候选清单
                        if rest.startswith("verify-"):
                            continue
                        candidates.append(
                            {
                                "branch": name,
                                "ahead": 0,
                                "main_is_ancestor": False,
                                "committerdate": cdate,
                            }
                        )
                if not candidates:
                    return []
                # 逐候选计算 ahead 与「main 是否为祖先」；零提交候选剔除
                valid: list = []
                for cand in candidates:
                    branch = cand["branch"]
                    try:
                        anc = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(self.project_root),
                                "merge-base",
                                "--is-ancestor",
                                "main",
                                branch,
                            ],
                            capture_output=True,
                            timeout=15,
                        )
                        cand["main_is_ancestor"] = anc.returncode == 0
                    except (subprocess.TimeoutExpired, OSError):
                        cand["main_is_ancestor"] = False
                    try:
                        ahead = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(self.project_root),
                                "rev-list",
                                "--count",
                                f"main..{branch}",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                        if ahead.returncode != 0:
                            continue  # 分支不可解析（已删）→ 剔除
                        try:
                            cand["ahead"] = int(ahead.stdout.strip() or "0")
                        except ValueError:
                            continue
                    except (subprocess.TimeoutExpired, OSError):
                        continue
                    if cand["ahead"] <= 0:
                        # 零提交候选（tip 与 main 同点）MUST NOT 为可保留锚点：
                        # 自候选清单剔除、不参与排序（tasks 2.5 闸门先于排序）
                        self.logger.warning(
                            "worktree_manager",
                            f"find_branches_by_spec('{spec_name}'): 零提交候选 "
                            f"'{branch}'（main..branch 为空）剔除，不参与排序",
                        )
                        continue
                    valid.append(cand)
                if not valid:
                    return []
                # 排序：先「已含 main」优先（committerdate 最新），其次 ahead 最大
                valid.sort(
                    key=lambda c: (
                        not c["main_is_ancestor"],
                        -c["committerdate"],
                        -c["ahead"],
                    )
                )
                return valid
            except (subprocess.TimeoutExpired, OSError) as e:
                self.logger.warning(
                    "worktree_manager",
                    f"find_branches_by_spec('{spec_name}') 异常降级空清单: {e}",
                )
                return []

    @staticmethod
    def _wt_name_matches_spec(wt_name: str, spec_name: str) -> bool:
            """worktree 目录名是否精确对应 spec（``{impl,verify,repair}-<spec>-<ts>``）。

            从目录名解析出完整 spec 再与目标精确比较（分隔符边界锚定，禁止子串
            包含）：``impl-fix-x-1`` 对 spec ``fix-x`` 命中、对 ``fix`` 不命中。
            非本框架命名（前缀不识别/缺时间戳段）返回 False。
            """
            if not wt_name or not spec_name:
                return False
            for prefix in ("impl", "verify", "repair"):
                if wt_name.startswith(f"{prefix}-"):
                    rest = wt_name[len(prefix) + 1 :]
                    parts = rest.rsplit("-", 1)
                    if len(parts) == 2 and parts[0] and parts[1].isdigit():
                        return parts[0] == spec_name
                    return False
            return False

    def has_pending_merge(self, spec_name: str) -> bool:
            """该 spec 是否存在待合并实现分支（未并入 main 的提交）。

            evo-recovery-watch-transition-guard D1：recovery watch 判定 stale 前
            的过渡窗口豁免判据之一。判定标准：

              - 枚举 ``refs/heads/fenix/``（前缀与创建端同源，见类常量注释）；
              - 候选分支按「完整 spec 名 + 分隔符边界」全等解析（去 ``fenix/``
                后按最后一个 ``-`` 分段、末段 MUST 为纯数字、其前段与该 spec 名
                全等；口径同 :meth:`_wt_name_matches_spec`），``fenix/verify-*``
                验证分支 MUST NOT 进入候选（归属解析见
                ``_impl_branch_owned_by_spec``，MUST NOT 复用 ``_spec_from_branch``
                ——它剥 ``verify-`` 前缀且硬编码 ``fenix/``）；
              - ``git rev-list --count main..<branch>`` > 0（有未并入 main 的提交）。

            查询失败（git 超时/非零退出/异常）一律返回 False（fail-closed：不
            豁免 → 调用方走既有 stale 判定，不把真实卡死洗成健康）。

            Returns: 存在待合并分支 True；无/查询失败 False。
            """
            return self.pending_merge_since(spec_name) is not None

    def pending_merge_since(self, spec_name: str):
            """该 spec 待合并分支的产生时间（epoch 秒），无待合并返回 None。

            evo-recovery-watch-transition-guard D1（年龄来源）：供**有界性**回落
            ——自「未并入 main 的最新 committer date」起算，超过
            ``pm.recovery.transition_grace_minutes`` 仍未合并时回落既有 stale
            判定，避免「分支永挂 → 永不告警」把真实卡死洗成健康。

            取值口径：枚举归属该 spec 的实现分支（同 :meth:`has_pending_merge`
            的归属解析），对每个有未并入 main 提交的候选分支取
            ``git log -1 --format=%ct main..<branch>``（该分支未并入 main 最新
            提交的 committer date，epoch 秒）；返回所有候选中的**最大值**（最近
            一次产生未合并提交的时刻——与实现分支自带的 ``-<ts>`` 时间戳同语义，
            均为「最近的实现/失败活动」，供调用方与 succeed 痕迹取 max 作年龄起点）。

            Returns: epoch 秒（int）；无待合并分支/git 失败返回 None（调用方
            MUST 以 ``isinstance(ts, (int, float))`` 判定，勿依赖 ``is not None``
            ——测试夹具替身 MagicMock 为真值）。
            """
            prefix = self.PENDING_MERGE_BRANCH_PREFIX
            try:
                res = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.project_root),
                        "for-each-ref",
                        "--format=%(refname:short)",
                        f"refs/heads/{prefix}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except (subprocess.TimeoutExpired, OSError):
                return None
            if res.returncode != 0:
                return None
            latest: Optional[int] = None
            for cand in res.stdout.splitlines():
                cand = cand.strip()
                if not self._impl_branch_owned_by_spec(cand, spec_name):
                    continue
                try:
                    ahead = subprocess.run(
                        ["git", "-C", str(self.project_root), "rev-list", "--count", f"main..{cand}"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    continue
                if ahead.returncode != 0:
                    continue
                try:
                    count = int(ahead.stdout.strip() or "0")
                except ValueError:
                    continue
                if count <= 0:
                    continue  # 已并入 main：不算待合并（design D1 反例：933/1014 已合并）
                try:
                    ts = subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.project_root),
                            "log",
                            "-1",
                            "--format=%ct",
                            f"main..{cand}",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                except (subprocess.TimeoutExpired, OSError):
                    continue
                if ts.returncode != 0:
                    continue
                try:
                    since = int(ts.stdout.strip())
                except ValueError:
                    continue
                if latest is None or since > latest:
                    latest = since
            return latest

    @staticmethod
    def _impl_branch_owned_by_spec(branch: str, spec_name: str) -> bool:
            """分支（``fenix/<spec>-<ts>``）是否精确归属该 spec（完整名 + 分隔符边界）。

            evo-recovery-watch-transition-guard D1 归属精确性：MUST NOT 复用
            ``_spec_from_branch``（它硬编码 ``fenix/`` 且剥 ``verify-`` 前缀，会把
            ``fenix/verify-<spec>-<ts>`` 验证分支误算作本 spec 的实现分支）；MUST
            走与 :meth:`_wt_name_matches_spec` 同口径的边界守卫——分支名去
            ``fenix/`` 后按最后一个 ``-`` 分段、末段 MUST 为纯数字、其前段与该
            spec 名**全等**；``fenix/verify-*`` 显式排除。

            实锤（design D1 归属精确性）：`fenix/evo-add-fast-track-scale-precheck-*`
            命中 5 条分支，其中 ``...-4afdbe-<ts>``（2 条）属**另一 spec**
            ``evo-add-fast-track-scale-precheck-4afdbe``——前缀匹配会把别的 spec 的
            未合并提交算到本 spec 头上。本守卫对 spec ``evo-add-fast-track-scale-precheck``
            解析 ``...-4afdbe-1789277250`` 得前段 ``...-4afdbe`` ≠ spec → 不命中。
            """
            if not branch or not spec_name:
                return False
            if not branch.startswith("fenix/"):
                return False
            rest = branch[len("fenix/") :]
            if rest.startswith("verify-"):
                return False  # 验证分支（fenix/verify-<spec>-<ts>）MUST NOT 进入候选
            parts = rest.rsplit("-", 1)
            if len(parts) == 2 and parts[0] and parts[1].isdigit():
                return parts[0] == spec_name
            return False

    def branch_exists(self, branch: str) -> bool:
            """分支是否存在（``git rev-parse --verify``）。repair 三态判定基准。"""
            if not branch:
                return False
            try:
                verify = subprocess.run(
                    ["git", "-C", str(self.project_root), "rev-parse", "--verify", branch],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return verify.returncode == 0
            except subprocess.TimeoutExpired:
                return False

    def branch_tip(self, branch: str) -> Optional[str]:
            """分支 tip SHA（``git rev-parse --verify``），异常/不存在返回 None。

            fix-repair-commit-enforcement D2：repair git 事实复核的「分支 tip 前进」
            判定基准——repair 派发前记录基准 tip，repair 后与当前 tip 比较。只读
            查询，不产生任何 worktree 写操作；超时/异常以 None 保守降级（调用侧
            据此跳过 tip 前进校验，不抛穿）。
            """
            if not branch:
                return None
            try:
                rev = subprocess.run(
                    ["git", "-C", str(self.project_root), "rev-parse", "--verify", branch],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if rev.returncode != 0:
                    return None
                sha = rev.stdout.strip()
                return sha or None
            except (subprocess.TimeoutExpired, OSError):
                return None

    def find_implementer_worktree(self, spec_name: str) -> Optional[Path]:
            """Find the most recent active implementer worktree for a SPEC.

            Looks for directories matching impl-<spec>-* in the base dir.
            Returns the path of the newest one (by mtime), or None if none found.
            """
            if not self.base_dir.is_dir():
                return None
            candidates = []
            prefix = f"impl-{spec_name}-"
            for d in self.base_dir.iterdir():
                if d.is_dir() and d.name.startswith(prefix):
                    try:
                        candidates.append((d.stat().st_mtime, d))
                    except OSError:
                        pass
            if not candidates:
                return None
            candidates.sort(reverse=True)
            return candidates[0][1]

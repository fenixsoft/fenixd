"""
registry.py — 多项目发现与注册（dashboard-server D3）。

中心配置文件 `~/.config/fenixd/dashboard.yaml`：
    port: 8787
    projects:
      - name: <别名>
        path: <项目绝对路径>
    scan_dirs:
      - <父目录>

`discover()` 合并显式 projects 与 scan_dirs 扫描结果；扫描仅当目录同时存在
`STATE.md` 与 `.fenix/config.yaml` 才识别为 Fenixd 项目。显式注册的项目始终
出现在监控列表（即使目录不存在，标记 exists=False）。
"""

import os
import yaml
from pathlib import Path

DEFAULT_PORT = 8787
DEFAULT_CONFIG = Path.home() / ".config" / "fenixd" / "dashboard.yaml"


class Registry:
    """读写监控配置并执行多项目发现。"""

    def __init__(self, config_path=None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG

    # ── 配置读写 ─────────────────────────────────────────────

    def load(self) -> dict:
        """读取配置；缺失/损坏时返回默认结构。"""
        defaults = {"port": DEFAULT_PORT, "projects": [], "scan_dirs": []}
        if not self.config_path.exists():
            return defaults
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, UnicodeDecodeError):
            return defaults
        if not isinstance(data, dict):
            return defaults
        out = {
            "port": data.get("port") or DEFAULT_PORT,
            "projects": data.get("projects") or [],
            "scan_dirs": data.get("scan_dirs") or [],
        }
        if not isinstance(out["projects"], list):
            out["projects"] = []
        if not isinstance(out["scan_dirs"], list):
            out["scan_dirs"] = []
        return out

    def save(self, data: dict):
        """写回配置（确保目录存在）。"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".yaml.tmp")
        tmp.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(self.config_path)

    # ── 发现 ─────────────────────────────────────────────────

    def discover(self) -> list:
        """合并显式配置与目录扫描，返回 [{name, path, discovered, exists}]。"""
        data = self.load()
        projects = []
        seen = set()

        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            raw = p.get("path", "")
            try:
                rp = Path(raw).expanduser().resolve()
            except (OSError, RuntimeError):
                continue
            key = str(rp)
            if key in seen:
                continue
            seen.add(key)
            name = p.get("name") or (rp.name or key)
            projects.append({
                "name": name,
                "path": key,
                "discovered": False,
                "exists": rp.is_dir(),
            })

        for sd in data.get("scan_dirs", []):
            base = Path(sd).expanduser()
            if not base.is_dir():
                continue
            try:
                children = sorted(base.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if not (child / "STATE.md").is_file():
                    continue
                if not (child / ".fenix" / "config.yaml").is_file():
                    continue
                rp = child.resolve()
                key = str(rp)
                if key in seen:
                    continue
                seen.add(key)
                projects.append({
                    "name": rp.name or key,
                    "path": key,
                    "discovered": True,
                    "exists": True,
                })

        return projects

    # ── 注册 ─────────────────────────────────────────────────

    def add_project(self, path, name=None) -> tuple:
        """注册项目到配置（按路径去重）。

        Returns: (added: bool, message: str)
        """
        try:
            rp = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            return False, f"无效路径: {path}"
        key = str(rp)

        data = self.load()
        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            try:
                existing = str(Path(p.get("path", "")).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
            if existing == key:
                return False, f"项目已在监控列表: {key}"

        if not (rp / "STATE.md").is_file():
            return False, f"目录不是 Fenixd 项目（缺少 STATE.md）: {key}"

        data.setdefault("projects", []).append({
            "name": name or (rp.name or key),
            "path": key,
        })
        self.save(data)
        return True, f"已注册项目: {key}"

    def list_projects(self) -> list:
        """仅返回配置中显式注册的项目（供 --list-projects）。"""
        data = self.load()
        out = []
        for p in data.get("projects", []):
            if not isinstance(p, dict):
                continue
            out.append({
                "name": p.get("name"),
                "path": p.get("path"),
            })
        return out

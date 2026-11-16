"""FENIX_HOME 覆盖 USER_CONFIG_DIR 单源契约（fix-windows-service-userprofile 2.2）。

两态解析断言一律经子进程独立解释器验证：core.config.USER_CONFIG_DIR 与
门面 core.dashboard.data.USER_CONFIG_PATH 均为 import 期一次性绑定，
进程内 importlib.reload 会污染同进程其他测试的模块缓存（任务验收注明的
串扰防线）；FENIX_HOME 语义 = home 替代，未设时行为与现状逐字节一致。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 探针：回读单源绑定与门面派生（json_output 布尔/路径断言，防 stdout 噪声误判）
_PROBE = (
    "import json, sys; sys.path.insert(0, r'%s');\n"
    "import core.config\n"
    "from core.dashboard import data as facade\n"
    "print(json.dumps({\n"
    "    'user_config_dir': str(core.config.USER_CONFIG_DIR),\n"
    "    'facade_path': str(facade.USER_CONFIG_PATH),\n"
    "}))\n"
) % REPO_ROOT


def _probe(extra_env: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "FENIX_HOME"}
    env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True,
        text=True, env=env, timeout=120, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


class TestFenixHomeOverridesUserConfigDir:
    def test_fenix_home_set_overrides(self, tmp_path):
        home = tmp_path / "fenix-home"
        out = _probe({"FENIX_HOME": str(home), "HOME": str(tmp_path)})
        # home 替代语义：USER_CONFIG_DIR = FENIX_HOME/.fenix
        assert out["user_config_dir"] == str(home / ".fenix")
        # 门面派生跟随（D8 绑定结构不变）
        assert out["facade_path"] == str(home / ".fenix" / "config.yaml")

    def test_fenix_home_unset_unchanged(self, tmp_path):
        home = str(tmp_path)
        # USERPROFILE 同步固定（Windows Path.home() 走 USERPROFILE 非 HOME
        # ——过机复验实录；Linux 忽略 USERPROFILE，双平台确定性）
        out = _probe({"HOME": home, "USERPROFILE": home})
        # 未设 FENIX_HOME：现状 Path.home()/.fenix（与既有部署完全兼容）
        assert out["user_config_dir"] == str(Path(home) / ".fenix")
        assert out["facade_path"] == str(
            Path(home) / ".fenix" / "config.yaml")

    def test_fenix_home_strict_priority_over_userprofile(self, tmp_path):
        # FENIX_HOME 严格优先（design Risks：显式覆盖 > 环境默认，测试锁定）
        home = tmp_path / "fenix-home"
        out = _probe({
            "FENIX_HOME": str(home),
            "HOME": str(tmp_path),
            "USERPROFILE": r"C:\Users\somewhere-else",
        })
        assert out["user_config_dir"] == str(home / ".fenix")

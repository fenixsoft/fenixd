"""tests/test_scheduling_kick_signal.py — scheduling kick 信号写入助手与返回值契约。

覆盖 task 6.1：
- 写入助手成功落盘路径与内容
- 非法 spec 名拒绝且不越目录
- 原子性：并发或中断下不产生半写文件
- 返回值契约：失败时 ok:false + 非空 error，异常不外抛
"""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestWriteSchedulingKick(unittest.TestCase):
    """core.signals.write_scheduling_kick 写入助手测试。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_creates_directory_and_file(self):
        """成功落盘：.fenix/scheduling_kick/<spec>.json 存在且内容正确。"""
        from core.signals import write_scheduling_kick, SCHEDULING_KICK_DIR
        result = write_scheduling_kick(self.proot, "my-spec")
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIsNone(result["error"])
        kick_path = self.proot / SCHEDULING_KICK_DIR / "my-spec.json"
        self.assertTrue(kick_path.exists(), "信号文件必须存在")
        payload = json.loads(kick_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["spec"], "my-spec")
        self.assertEqual(payload["action"], "clear-start-after")
        self.assertIn("created", payload)
        # created 须为合法 ISO8601
        dt = datetime.fromisoformat(payload["created"].replace("Z", "+00:00"))
        self.assertIsNotNone(dt)

    def test_write_idempotent_on_same_spec(self):
        """同一 SPEC 重复写入幂等覆盖（不冲突、不增文件数）。"""
        from core.signals import write_scheduling_kick, SCHEDULING_KICK_DIR
        r1 = write_scheduling_kick(self.proot, "alpha")
        r2 = write_scheduling_kick(self.proot, "alpha")
        self.assertTrue(r1["ok"] and r2["ok"])
        kdir = self.proot / SCHEDULING_KICK_DIR
        files = list(kdir.glob("*.json"))
        self.assertEqual(len(files), 1, "同一 SPEC 只有一个文件（幂等覆盖）")
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["spec"], "alpha")

    def test_different_specs_no_conflict(self):
        """不同 SPEC 各自独立文件，不互相阻塞。"""
        from core.signals import write_scheduling_kick, SCHEDULING_KICK_DIR
        r1 = write_scheduling_kick(self.proot, "alpha")
        r2 = write_scheduling_kick(self.proot, "beta")
        self.assertTrue(r1["ok"] and r2["ok"])
        kdir = self.proot / SCHEDULING_KICK_DIR
        names = sorted(p.name for p in kdir.glob("*.json"))
        self.assertEqual(names, ["alpha.json", "beta.json"])

    def test_invalid_spec_name_rejected(self):
        """非法 spec 名被拒绝且不越目录。"""
        from core.signals import write_scheduling_kick, SCHEDULING_KICK_DIR
        for bad_name in ("", "UPPER", "has space", "../escape", "a/b", "a.b", ":colon", "中文"):
            result = write_scheduling_kick(self.proot, bad_name)
            self.assertFalse(result["ok"], f"{bad_name!r} 应被拒绝")
            self.assertIsNotNone(result["error"])
            self.assertIsNone(result["file"])
        # 目录不应被创建或为空
        kdir = self.proot / SCHEDULING_KICK_DIR
        if kdir.is_dir():
            self.assertEqual(list(kdir.iterdir()), [], "非法 spec 不应创建文件")

    def test_write_atomic_no_half_written_file(self):
        """写入原子性：失败时不留下半写文件。"""
        from core.signals import write_scheduling_kick, SCHEDULING_KICK_DIR
        kdir = self.proot / SCHEDULING_KICK_DIR
        # 模拟写入过程失败（json.dump 之后 os.replace 之前）
        with mock.patch("core.signals.os.replace", side_effect=OSError("disk full")):
            result = write_scheduling_kick(self.proot, "fail-spec")
        self.assertFalse(result["ok"])
        self.assertIn("disk full", result["error"])
        # 无残留文件
        if kdir.is_dir():
            json_files = list(kdir.glob("*.json"))
            self.assertEqual(json_files, [], "写入失败不应留下 .json 文件")

    def test_exception_not_raised(self):
        """任何异常不得向上抛出，一律转为 ok:false + 非空 error。"""
        from core.signals import write_scheduling_kick
        with mock.patch("core.signals.Path.mkdir", side_effect=OSError("perm denied")):
            result = write_scheduling_kick(self.proot, "nope")
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_temp_file_not_json_extension(self):
        """临时文件名不以 .json 结尾（消费侧「只扫 *.json」约束）。"""
        from core.signals import write_scheduling_kick, SCHEDULING_KICK_DIR
        # 拦截 mkstemp 检查临时文件名
        original_mkstemp = __import__("tempfile").mkstemp
        def check_suffix(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            self.assertFalse(path.endswith(".json"), f"临时文件 {Path(path).name} 不应以 .json 结尾")
            return fd, path
        with mock.patch("core.signals.tempfile.mkstemp", side_effect=check_suffix):
            result = write_scheduling_kick(self.proot, "ok-spec")
        self.assertTrue(result["ok"], result.get("error"))


class TestValidateSchedulingKickSpec(unittest.TestCase):
    """core.signals.validate_scheduling_kick_spec 合法性校验。"""

    def test_valid_kebab_case(self):
        from core.signals import validate_scheduling_kick_spec
        for name in ("a", "fix-foo", "add-spec-v2", "x9"):
            self.assertIsNone(validate_scheduling_kick_spec(name), f"{name} 合法")

    def test_invalid(self):
        from core.signals import validate_scheduling_kick_spec
        for bad in ("", "UPPER", "has space", "../x", "a/b", "a.b", "中文"):
            err = validate_scheduling_kick_spec(bad)
            self.assertIsNotNone(err, f"{bad!r} 应非法")
            self.assertIsInstance(err, str)
            self.assertTrue(len(err) > 0)


if __name__ == "__main__":
    unittest.main()

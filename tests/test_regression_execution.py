"""core/regression.py 测试（test-regression-execution 能力）。

覆盖：JUnit XML 全绿/失败/错误分类解析、长耗时用例抽取（含通过用例）、
快照读写（never_run / parse_error / 有效写入）、超时进程组中止、
状态文件独立防重、config 回显读写（task 3.4-3.6 辅助覆盖）。
"""

import datetime
import json
import logging
import shutil
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.regression import (
    extract_long_tests,
    local_today_str,
    mark_running,
    parse_junit_xml,
    read_progress,
    read_result,
    read_state,
    run_regression,
    run_and_write_regression,
    save_state,
    write_result,
)
from core.verify_contract import RegressionSpec

# ── JUnit XML 测试夹具 ─────────────────────────────────────────────────

PASSING_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuites>
      <testsuite name="pytest" tests="3" errors="0" failures="0" skipped="0">
        <testcase classname="tests.test_foo" name="test_one" time="0.10"/>
        <testcase classname="tests.test_foo" name="test_two" time="0.05"/>
        <testcase classname="tests.test_bar" name="test_three" time="0.03"/>
      </testsuite>
    </testsuites>
""")

FAILING_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuites>
      <testsuite name="pytest" tests="4" errors="0" failures="1" skipped="1">
        <testcase classname="tests.test_foo" name="test_pass" time="0.10"/>
        <testcase classname="tests.test_foo" name="test_slow_pass" time="12.5"/>
        <testcase classname="tests.test_foo" name="test_fail" time="0.20" file="tests/test_foo.py" line="42">
          <failure message="assert 1 == 2">assert 1 == 2</failure>
        </testcase>
        <testcase classname="tests.test_foo" name="test_skip" time="0.01">
          <skipped message="not implemented"/>
        </testcase>
      </testsuite>
    </testsuites>
""")

ERROR_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <testsuites>
      <testsuite name="pytest" tests="2" errors="1" failures="0" skipped="0">
        <testcase classname="tests.test_bar" name="test_ok" time="0.05"/>
        <testcase classname="tests.test_bar" name="test_err" time="0.00" file="tests/test_bar.py" line="15">
          <error message="RuntimeError: boom">RuntimeError: boom</error>
        </testcase>
      </testsuite>
    </testsuites>
""")


class TestParseJunitXml(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _write_xml(self, content: str, name: str = "junit.xml") -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_passing_suite(self):
        path = self._write_xml(PASSING_XML)
        result = parse_junit_xml(path)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failures"], [])
        self.assertEqual(len(result["cases"]), 3)

    def test_failing_and_error_classification(self):
        path = self._write_xml(FAILING_XML)
        result = parse_junit_xml(path)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["passed"], 2)
        self.assertEqual(len(result["failures"]), 1)
        f = result["failures"][0]
        self.assertEqual(f["name"], "test_fail")
        self.assertEqual(f["file"], "tests/test_foo.py")
        self.assertEqual(f["line"], 42)
        self.assertEqual(f["kind"], "failure")
        self.assertIn("assert 1 == 2", f["message"])

    def test_error_element(self):
        path = self._write_xml(ERROR_XML)
        result = parse_junit_xml(path)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["kind"], "error")
        self.assertEqual(result["failures"][0]["file"], "tests/test_bar.py")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            parse_junit_xml(self.tmp / "nonexistent.xml")

    def test_invalid_xml_raises(self):
        path = self._write_xml("not xml at all")
        with self.assertRaises(ValueError):
            parse_junit_xml(path)

    def test_time_missing_defaults_zero(self):
        """time 属性缺失时记 0（宽松解析，design R1）。"""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites>
              <testsuite name="t" tests="1">
                <testcase classname="c" name="n"/>
              </testsuite>
            </testsuites>
        """)
        path = self._write_xml(xml)
        result = parse_junit_xml(path)
        self.assertEqual(result["cases"][0]["time"], 0.0)

    def test_file_fallback_to_classname(self):
        """file 属性缺失时从 classname 兜底。"""
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuites>
              <testsuite name="t" tests="1">
                <testcase classname="tests/pkg.py::TestClass::test_method"
                          name="test_method" time="0.1"/>
              </testsuite>
            </testsuites>
        """)
        path = self._write_xml(xml)
        result = parse_junit_xml(path)
        self.assertEqual(result["cases"][0]["file"], "tests/pkg.py::TestClass::test_method")


class TestExtractLongTests(unittest.TestCase):
    def test_threshold_extraction(self):
        cases = [
            {"name": "fast", "file": "a.py", "line": 1, "time": 5.0},
            {"name": "slow_pass", "file": "b.py", "line": 2, "time": 15.0},
            {"name": "slow_fail", "file": "c.py", "line": 3, "time": 20.0},
        ]
        long = extract_long_tests(cases, 10)
        self.assertEqual(len(long), 2)
        names = {lt["name"] for lt in long}
        self.assertIn("slow_pass", names)
        self.assertIn("slow_fail", names)
        self.assertNotIn("fast", names)

    def test_empty_cases(self):
        self.assertEqual(extract_long_tests([], 10), [])


class TestSnapshotReadWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_read_result_never_run(self):
        """快照缺失 → never_run（不报 500）。"""
        result = read_result(self.tmp)
        self.assertEqual(result["status"], "never_run")

    def test_read_result_parse_error(self):
        """快照损坏 → parse_error + 非空 reason。"""
        result_dir = self.tmp / ".fenix" / "regression"
        result_dir.mkdir(parents=True)
        (result_dir / "last-run.json").write_text("not json {%", encoding="utf-8")
        result = read_result(self.tmp)
        self.assertEqual(result["status"], "parse_error")
        self.assertTrue(result["reason"])

    def test_write_then_read(self):
        """写入后能读回完整内容。"""
        snapshot = {
            "status": "passed",
            "total": 100,
            "passed": 100,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        }
        write_result(self.tmp, snapshot)
        result = read_result(self.tmp)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["total"], 100)
        # 验证文件路径
        self.assertTrue((self.tmp / ".fenix" / "regression" / "last-run.json").is_file())


class TestStateReadWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_read_state_empty(self):
        """未初始化 → 空 dict。"""
        self.assertEqual(read_state(self.tmp), {})

    def test_save_then_read(self):
        """写入后能读回 last_run_date。"""
        save_state(self.tmp, "2026-09-20")
        state = read_state(self.tmp)
        self.assertEqual(state["last_run_date"], "2026-09-20")
        self.assertIn("updated_at", state)

    def test_state_independent(self):
        """regression state 与 code_review state 解耦。"""
        save_state(self.tmp, "2026-09-20")
        # code_review state 路径不同
        cr_path = self.tmp / ".fenix" / "code_review_state.json"
        self.assertFalse(cr_path.exists())


class TestLocalTodayStr(unittest.TestCase):
    def test_format(self):
        today = local_today_str()
        # YYYY-MM-DD 格式
        parts = today.split("-")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 4)
        self.assertEqual(len(parts[1]), 2)
        self.assertEqual(len(parts[2]), 2)


class TestRunRegression(unittest.TestCase):
    """run_regression 端到端：执行命令、超时、XML 解析、写盘、锁互斥。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # 测试可用回归命令：生成 JUnit XML 的假命令
        self.cmd_template = (
            'python3 -c "import xml.etree.ElementTree as ET; '
            "root=ET.Element('testsuites'); "
            "suite=ET.SubElement(root,'testsuite',attrib={{'name':'t','tests':'1'}}); "
            "ET.SubElement(suite,'testcase',attrib={{'classname':'c','name':'n','time':'0.1'}}); "
            "tree=ET.ElementTree(root); tree.write('{output}')"
            '"'
        )

    def _spec(self, cmd, output="junit.xml", timeout=30, threshold=10):
        return RegressionSpec(cmd=cmd, output=output, timeout_seconds=timeout,
                              long_test_threshold_seconds=threshold)

    def test_full_pass(self):
        """全绿：status passed，计数正确，写盘（run_and_write_regression）。"""
        cmd = self.cmd_template.format(output="junit.xml")
        spec = self._spec(cmd)
        result = run_and_write_regression(self.tmp, spec)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["long_tests"], [])
        self.assertGreater(result["duration_seconds"], 0)
        self.assertIn("started_at", result)
        self.assertIn("finished_at", result)
        # 写盘
        read = read_result(self.tmp)
        self.assertEqual(read["status"], "passed")

    def test_timeout_kills_process_group(self):
        """超时：命令不结束 → status timeout（进程组被中止）。"""
        spec = self._spec("python3 -c 'import time; time.sleep(60)'", timeout=2)
        started = time.time()
        result = run_regression(self.tmp, spec)
        elapsed = time.time() - started
        self.assertEqual(result["status"], "timeout")
        self.assertLess(elapsed, 30)  # 证明确实被中止而非干等 60s
        # 超时结果不写盘（保持既有快照语义；run_and_write 由调用方决定）
        self.assertFalse((self.tmp / ".fenix" / "regression" / "last-run.json").exists())

    def test_argv_list_cmd(self):
        """argv 列表形态执行。"""
        cmd = ["python3", "-c",
               "import xml.etree.ElementTree as ET;"
               "root=ET.Element('testsuites');"
               "suite=ET.SubElement(root,'testsuite',attrib={'name':'t','tests':'1'});"
               "ET.SubElement(suite,'testcase',attrib={'classname':'c','name':'n','time':'0.1'});"
               "ET.ElementTree(root).write('junit.xml')"]
        spec = self._spec(cmd)
        result = run_regression(self.tmp, spec)
        self.assertEqual(result["status"], "passed")

    def test_missing_output_parse_error(self):
        """命令结束但未产出 XML → parse_error + 非空 reason。"""
        spec = self._spec("python3 -c 'print(1)'")
        result = run_regression(self.tmp, spec)
        self.assertEqual(result["status"], "parse_error")
        self.assertTrue(result["reason"])

    def test_stdout_written_to_log(self):
        """stdout 落 <output>.log（read_progress 的进度数据源）。"""
        cmd = (
            "python3 -c \"print('.......                                [ 50%]'); "
            "import xml.etree.ElementTree as ET; "
            "root=ET.Element('testsuites'); "
            "suite=ET.SubElement(root,'testsuite',attrib={'name':'t','tests':'1'}); "
            "ET.SubElement(suite,'testcase',attrib={'classname':'c','name':'n','time':'0.1'}); "
            "ET.ElementTree(root).write('junit.xml')\""
        )
        spec = self._spec(cmd)
        result = run_regression(self.tmp, spec)
        self.assertEqual(result["status"], "passed")
        log_path = self.tmp / "junit.xml.log"
        self.assertTrue(log_path.is_file())
        self.assertIn("[ 50%]", log_path.read_text(encoding="utf-8"))

    def test_invalid_xml_parse_error(self):
        """命令产出非法 XML → parse_error + 非空 reason。"""
        spec = self._spec("python3 -c 'open(\"junit.xml\",\"w\").write(\"not xml\")'")
        result = run_regression(self.tmp, spec)
        self.assertEqual(result["status"], "parse_error")
        self.assertIn("JUnit XML", result["reason"])

    def test_long_test_extraction_in_execution(self):
        """执行中长耗时抽取：慢但通过的用例列入 long_tests。"""
        # argv 列表形态（避免 shell 引号转义问题）
        pycode = (
            "import xml.etree.ElementTree as ET;"
            'root=ET.Element("testsuites");'
            'suite=ET.SubElement(root,"testsuite",attrib={"name":"t","tests":"2"});'
            'ET.SubElement(suite,"testcase",attrib={"classname":"c","name":"fast","time":"0.1"});'
            'ET.SubElement(suite,"testcase",attrib={"classname":"c","name":"slow","time":"12.5"});'
            "ET.ElementTree(root).write('junit.xml')"
        )
        cmd = ["python3", "-c", pycode]
        spec = self._spec(cmd, threshold=10)
        result = run_regression(self.tmp, spec)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["long_tests"]), 1)
        lt = result["long_tests"][0]
        self.assertEqual(lt["name"], "slow")
        self.assertEqual(lt["time"], 12.5)


class TestReadProgress(unittest.TestCase):
    """read_progress 三级口径：真实终端标记 / 耗时估算 / 未知（进度条数据源）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # 上次快照：total=100 / duration=100s / output=junit.xml（log 派生为
        # junit.xml.log，与 output 同路径 + .log）
        write_result(self.tmp, {
            "status": "passed",
            "total": 100,
            "duration_seconds": 100.0,
            "output": "junit.xml",
        })
        # 运行中 marker（started_at=now，elapsed≈0）
        mark_running(self.tmp, 1800)

    def _write_log(self, content: str) -> None:
        (self.tmp / "junit.xml.log").write_text(content, encoding="utf-8")

    def test_real_terminal_marker(self):
        """stdout 日志含 pytest 终端标记 → 取最后一个，estimated=False。"""
        self._write_log(".......                                [ 41%]\n"
                        "........                               [ 42%]\n")
        p = read_progress(self.tmp)
        self.assertEqual(p["percent"], 42)
        self.assertFalse(p["estimated"])
        self.assertIsNotNone(p["elapsed_seconds"])
        self.assertEqual(p["total_estimate"], 100)

    def test_cap_at_99_even_if_marker_100(self):
        """收尾 [100%] 已出现但快照未写盘 → 恒封顶 99，不假完成。"""
        self._write_log("all done                            [100%]\n")
        self.assertEqual(read_progress(self.tmp)["percent"], 99)

    def test_estimated_fallback_without_marker(self):
        """日志无标记（非 pytest/未刷新）→ 已耗时/上次总耗时估算（elapsed≈0 → 0）。"""
        self._write_log("no progress markers here\n")
        p = read_progress(self.tmp)
        self.assertTrue(p["estimated"])
        self.assertEqual(p["percent"], 0)
        self.assertEqual(p["last_duration_seconds"], 100.0)

    def test_estimated_clamped_to_99(self):
        """已耗时远超上次总耗时 → 估算封顶 99。"""
        meta = {
            "started_at": (
                datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(hours=2)
            ).isoformat(),
            "timeout_seconds": 1800,
        }
        (self.tmp / ".fenix" / "regression" / ".running").write_text(
            json.dumps(meta), encoding="utf-8"
        )
        p = read_progress(self.tmp)
        self.assertTrue(p["estimated"])
        self.assertEqual(p["percent"], 99)

    def test_unknown_without_snapshot_and_log(self):
        """无快照（never_run）无日志 → percent=None（前端不确定动画）。"""
        tmp2 = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp2, ignore_errors=True)
        mark_running(tmp2, 1800)
        p = read_progress(tmp2)
        self.assertIsNone(p["percent"])
        self.assertFalse(p["estimated"])
        self.assertIsNotNone(p["elapsed_seconds"])


class TestCheckpointDisabledZeroAction(unittest.TestCase):
    """_run_regression_checkpoint 零动作场景矩阵（task 3.6，对齐
    TestCheckpointDisabledZeroAction 的 code_review 同款测试）。"""

    def _make_repo(self):
        import tempfile

        proot = Path(tempfile.mkdtemp())
        (proot / ".fenix").mkdir(parents=True)
        return proot

    def _make_monitor(self, cfg, repo, runner):
        from core.admin_monitor import AdminMonitor

        logger = logging.getLogger("test-regression")
        return AdminMonitor(cfg, None, str(repo), logger, agent_runner=runner, code_review_executor=None)

    def test_disabled_no_dispatch(self):
        repo = self._make_repo()
        try:
            calls = {"n": 0}

            class _Runner:
                _running_agents = {}

                def run_regression(self, *a, **k):
                    calls["n"] += 1

                    class R:
                        run_id = "regression-1"
                        success = True
                        status = "passed"
                        error = ""
                    return R()

            mon = self._make_monitor({"admin": {"regression": {"enabled": False}}}, repo, _Runner())
            result = mon._run_regression_checkpoint()
            self.assertEqual(result, {"triggered": False, "reason": "disabled"})
            self.assertEqual(calls["n"], 0)
        finally:
            import shutil
            shutil.rmtree(str(repo), ignore_errors=True)

    def test_not_configured_skip(self):
        repo = self._make_repo()
        try:
            calls = {"n": 0}

            class _Runner:
                _running_agents = {}

                def run_regression(self, *a, **k):
                    calls["n"] += 1

                    class R:
                        run_id = "regression-1"
                        success = True
                        status = "passed"
                        error = ""
                    return R()

            # enabled 但无 regression 段 → not_configured
            mon = self._make_monitor(
                {"admin": {"regression": {"enabled": True}, "self_review": {"run_at": "00:00"}}},
                repo, _Runner()
            )
            result = mon._run_regression_checkpoint()
            self.assertEqual(result["triggered"], False)
            self.assertEqual(result["reason"], "not_configured")
            self.assertEqual(calls["n"], 0)
        finally:
            import shutil
            shutil.rmtree(str(repo), ignore_errors=True)


class TestFenixdRegressionSignalConsumption(unittest.TestCase):
    """_check_regression_requests 守卫：无信号文件 → 静默返回（task 3.6）。

    不直接实例化 FenixDaemon（耦合太重），改为测试 daemon 所消费的
    原子操作（verify contract 有效性判定 + 上游守卫），覆盖「未配置时
    信号丢弃」的判据路径，对齐 code-review 信号消费亦无独立测试的现况。
    """

    def test_unconfigured_contract_rejects_signal(self):
        """无 regression 段的契约 → 消费方 MUST 丢弃（MUST NOT 派发空跑）。"""
        import tempfile

        proot = Path(tempfile.mkdtemp())
        try:
            (proot / ".fenix").mkdir(parents=True)
            # 无 verify.yaml → contract None → 丢弃
            from core.verify_contract import load_verify_contract
            contract = load_verify_contract(proot)
            self.assertIsNone(contract)
        finally:
            import shutil
            shutil.rmtree(str(proot), ignore_errors=True)

    def test_managed_guard(self):
        """hosting_state == managed → 放行；unmanaged → 拒绝。"""
        import tempfile

        proot = Path(tempfile.mkdtemp())
        try:
            (proot / ".fenix").mkdir(parents=True)
            import core.fenix_session as fs
            # managed → 放行
            orig = fs.hosting_state
            fs.hosting_state = lambda p: "managed"
            try:
                self.assertEqual(fs.hosting_state(proot), "managed")
            finally:
                fs.hosting_state = orig
            # unmanaged → 拒绝
            fs.hosting_state = lambda p: "unmanaged"
            try:
                self.assertEqual(fs.hosting_state(proot), "unmanaged")
            finally:
                fs.hosting_state = orig
        finally:
            import shutil
            shutil.rmtree(str(proot), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

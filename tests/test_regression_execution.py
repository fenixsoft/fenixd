"""core/regression.py 测试（test-regression-execution 能力）。

覆盖：JUnit XML 全绿/失败/错误分类解析、长耗时用例抽取（含通过用例）、
快照读写（never_run / parse_error / 有效写入）、超时进程组中止、
状态文件独立防重、config 回显读写（task 3.4-3.6 辅助覆盖）。
"""

import datetime
import json
import logging
import os
import shutil
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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

    def test_long_tests_carry_classname(self):
        """add-regression-issues-rerun 1.1：long_tests 条目透传 classname
        （定向子集 nodeid 映射源，对齐 failures 侧 add-codefix-targeted-retry
        1.1 的补齐做法；cases 侧本就携带）。"""
        cases = [
            {"name": "slow", "file": "tests/test_x.py", "line": 3, "time": 20.0,
             "classname": "tests.test_x"},
        ]
        long = extract_long_tests(cases, 10)
        self.assertEqual(long[0]["classname"], "tests.test_x")

    def test_legacy_cases_without_classname_tolerated(self):
        """缺 classname 的存量快照不受影响（读侧宽松）：键兜底空串不抛异常，
        消费端映射按 fail-closed 回退全量（不在此处判）。"""
        cases = [{"name": "slow", "file": "a.py", "line": 1, "time": 15.0}]
        long = extract_long_tests(cases, 10)
        self.assertEqual(long[0]["classname"], "")


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


class TestEmptyResultFailClosed(unittest.TestCase):
    """空结果 fail-closed 契约（evo-add-regression-empty-result-failclosed 3.1）。

    钉住三个不变式：
    - returncode≠0 且 total=0（pytest usage error exit=4 / 零收集 exit=5
      形态）MUST NOT 判 passed，按 parse_error 处置（empty_result 留痕）；
    - junit.xml mtime 早于本次命令 started_at 的陈旧 XML MUST NOT 采信
      （stale_xml 留痕）；
    - 「XML 新鲜且 total>0 的非零退出仍 passed」既有豁免不回归（exit_code
      留痕）。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _spec(self, cmd, timeout=30):
        return RegressionSpec(cmd=cmd, output="junit.xml",
                              timeout_seconds=timeout,
                              long_test_threshold_seconds=10)

    # 写 0 例 testsuites XML 后以指定码退出（模拟 pytest usage error/零收集
    # 落可解析 0 例 XML 形态）
    _EMPTY_XML_PY = (
        "import xml.etree.ElementTree as ET, sys;"
        "root=ET.Element('testsuites');"
        "suite=ET.SubElement(root,'testsuite',attrib={{'name':'t','tests':'0'}});"
        "ET.ElementTree(root).write('junit.xml');"
        "sys.exit({rc})"
    )

    def test_usage_error_exit4_zero_cases_not_passed(self):
        """usage error exit=4 + 可解析 0 例 XML → parse_error，不判 passed
        （2026-10-24 链 A 批 1 伪绿合回事故形态收口）。"""
        result = run_regression(
            self.tmp, self._spec(["python3", "-c", self._EMPTY_XML_PY.format(rc=4)]))
        self.assertEqual(result["status"], "parse_error")
        self.assertIn("empty_result", result["reason"])
        self.assertEqual(result.get("exit_code"), 4, "非零退出码结构化留痕")
        self.assertEqual(result["total"], 0)

    def test_zero_collect_exit5_not_passed(self):
        """零收集 exit=5 + 0 例 XML → parse_error，不判 passed。"""
        result = run_regression(
            self.tmp, self._spec(["python3", "-c", self._EMPTY_XML_PY.format(rc=5)]))
        self.assertEqual(result["status"], "parse_error")
        self.assertIn("empty_result", result["reason"])

    def test_stale_xml_not_trusted(self):
        """陈旧 XML（mtime 早于 started_at）不得采信：spawn 前预清理 unlink
        OSError 被吞后遗留旧 XML 场景 → parse_error（stale_xml 留痕），不判
        passed。命令退出 0 且不写 XML：若旧 XML 被采信即误判 passed。"""
        (self.tmp / "junit.xml").write_text(PASSING_XML, encoding="utf-8")
        # mtime 显式拨回过去（确定性：不依赖文件系统时间粒度）
        past = time.time() - 60
        os.utime(self.tmp / "junit.xml", (past, past))
        real_unlink = Path.unlink

        def _poisoned_unlink(path_self, *a, **k):
            if path_self.name == "junit.xml":
                raise OSError("simulated: pre-clean unlink failed (stale left behind)")
            return real_unlink(path_self, *a, **k)

        with patch("pathlib.Path.unlink", _poisoned_unlink):
            result = run_regression(self.tmp, self._spec("python3 -c 'print(1)'"))
        self.assertEqual(result["status"], "parse_error")
        self.assertIn("stale_xml", result["reason"])

    def test_fresh_nonzero_exit_green_xml_still_passed(self):
        """既有豁免不回归：XML 新鲜且 total>0 的非零退出仍 passed
        （exit_code 附入结果留痕，不因空结果守卫误伤）。"""
        pycode = (
            "import xml.etree.ElementTree as ET, sys;"
            "root=ET.Element('testsuites');"
            "suite=ET.SubElement(root,'testsuite',attrib={'name':'t','tests':'1'});"
            "ET.SubElement(suite,'testcase',attrib={'classname':'c','name':'n','time':'0.1'});"
            "ET.ElementTree(root).write('junit.xml');"
            "sys.exit(3)"
        )
        result = run_regression(self.tmp, self._spec(["python3", "-c", pycode]))
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result.get("exit_code"), 3)
        self.assertEqual(result["total"], 1)


class TestRunScopeStamp(unittest.TestCase):
    """run_and_write_regression 的 run_scope stamp（add-regression-issues-rerun 1.2）。

    仅子集改写实际生效时由门面传 "issues"；stamp 单点在 write_result 之前，
    覆盖全部状态路径。缺省 None 不落键（真全量可被门禁正常采信）。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _spec(self):
        cmd = (
            'python3 -c "import xml.etree.ElementTree as ET; '
            "root=ET.Element('testsuites'); "
            "suite=ET.SubElement(root,'testsuite',attrib={{'name':'t','tests':'1'}}); "
            "ET.SubElement(suite,'testcase',attrib={{'classname':'c','name':'n','time':'0.1'}}); "
            "tree=ET.ElementTree(root); tree.write('{output}')"
            '"'
        ).format(output="junit.xml")
        return RegressionSpec(cmd=cmd, output="junit.xml", timeout_seconds=30,
                              long_test_threshold_seconds=10)

    def test_run_scope_issues_stamped(self):
        """传 run_scope="issues" → 快照含 run_scope=="issues"。"""
        result = run_and_write_regression(self.tmp, self._spec(), run_scope="issues")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["run_scope"], "issues")
        read = read_result(self.tmp)
        self.assertEqual(read["run_scope"], "issues")

    def test_default_no_run_scope_key(self):
        """缺省 None → 快照无 run_scope 键（既有调用点零迁移）。"""
        result = run_and_write_regression(self.tmp, self._spec())
        self.assertNotIn("run_scope", result)
        read = read_result(self.tmp)
        self.assertNotIn("run_scope", read)


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


class TestFenixdScopeIssuesDispatch(unittest.TestCase):
    """_check_regression_requests 的 scope==issues 分支（add-regression-issues-rerun 2.2）。

    FenixDaemon 不整体实例化（耦合过重，对齐 TestFenixdRegressionSignalConsumption
    先例），以 __new__ 空壳装配最小协作面（_admin_executor=None 使 worker 同步
    执行、断言确定性）；PROJECT_ROOT 为模块全局运行期查找，patch 到临时仓库即可
    生效；hosting_state 在消费方法体内延迟导入，patch core.fenix_session 属性即可。
    """

    def _make_repo(self) -> Path:
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        (repo / ".fenix").mkdir(parents=True)
        (repo / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: 'true'\n"
            "serve:\n  kind: static\n  root: site\n"
            "ready:\n  url: /\n  expect: 200\n"
            "regression:\n"
            '  cmd: "pytest tests/ --junit-xml=.fenix/regression/junit.xml"\n'
            '  output: ".fenix/regression/junit.xml"\n',
            encoding="utf-8",
        )
        # 在盘测试文件（exec_root 探测目标）：classname → nodeid 重构依赖
        (repo / "tests").mkdir()
        (repo / "tests" / "test_demo.py").write_text(
            "def test_a():\n    assert True\n", encoding="utf-8"
        )
        return repo

    def _write_signal(self, repo: Path, payload: dict) -> None:
        (repo / ".fenix" / "regression_request.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def _write_snapshot(self, repo: Path, snapshot: dict) -> None:
        d = repo / ".fenix" / "regression"
        d.mkdir(parents=True, exist_ok=True)
        (d / "last-run.json").write_text(json.dumps(snapshot), encoding="utf-8")

    def _consume(self, repo: Path):
        """装配空壳 daemon 消费一次信号，返回 (agent_runner kwargs 列表, logger)。

        logger 用 fenixd 双参接口替身（(component, message) 签名，stdlib Logger
        会把 component 当格式串、message 当参数 → % 格式化 TypeError）。
        """
        import fenixd

        calls = []

        class _FakeLogger:
            def __init__(self):
                self.records = []

            def _rec(self, level, component, message, context=None):
                self.records.append((level, message))

            def warning(self, component, message, context=None):
                self._rec("WARNING", component, message, context)

            def info(self, component, message, context=None):
                self._rec("INFO", component, message, context)

            def error(self, component, message, context=None):
                self._rec("ERROR", component, message, context)

        logger = _FakeLogger()

        class _R:
            run_id = "regression-1"
            success = True
            status = "passed"
            error = ""

        class _Runner:
            _running_agents = {}

            def run_regression(self, *a, **k):
                calls.append(k)
                return _R()

        daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        daemon.logger = logger
        daemon.admin_monitor = None
        daemon.agent_runner = _Runner()
        daemon._admin_executor = None  # 同步执行 _worker_with_flag
        with patch.object(fenixd, "PROJECT_ROOT", repo), \
                patch("core.fenix_session.hosting_state", lambda p: "managed"):
            daemon._check_regression_requests()
        return calls, logger

    def _fresh_signal(self, scope=None) -> dict:
        payload = {
            "source": "dashboard",
            "requested_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        if scope is not None:
            payload["scope"] = scope
        return payload

    def test_scope_issues_dispatches_subset(self):
        """scope=issues + 可映射快照 → run_regression 收到去重 nodeids 子集。"""
        repo = self._make_repo()
        # file=点分 classname 兜底形态（真实快照形态）——封装须剥离 file 才可映射
        self._write_snapshot(repo, {
            "status": "failed",
            "failures": [
                {"name": "test_a", "classname": "tests.test_demo",
                 "file": "tests.test_demo", "line": 1, "time": 0.1,
                 "kind": "failure", "message": "boom"},
            ],
            "long_tests": [
                {"name": "test_slow", "classname": "tests.test_demo",
                 "file": "tests.test_demo", "line": 5, "time": 12.0},
            ],
        })
        self._write_signal(repo, self._fresh_signal(scope="issues"))
        calls, _logger = self._consume(repo)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get("reason"), "manual")
        self.assertEqual(
            calls[0].get("subset_nodeids"),
            ["tests/test_demo.py::test_a", "tests/test_demo.py::test_slow"],
        )
        # 信号已消费（不残留）
        self.assertFalse((repo / ".fenix" / "regression_request.json").exists())

    def test_scope_issues_missing_classname_falls_back_full(self):
        """缺 classname（存量旧快照）→ WARNING 留痕回退全量，请求不丢。"""
        repo = self._make_repo()
        self._write_snapshot(repo, {
            "status": "failed",
            "failures": [
                {"name": "test_a", "file": "tests/test_demo.py", "line": 1,
                 "time": 0.1, "kind": "failure", "message": "boom"},
            ],
            "long_tests": [],
        })
        self._write_signal(repo, self._fresh_signal(scope="issues"))
        calls, logger = self._consume(repo)
        self.assertEqual(len(calls), 1, "回退全量仍 MUST 派发（请求不丢）")
        self.assertNotIn("subset_nodeids", calls[0])
        # fail-closed 回退 WARNING 留痕（对齐 targeted-retry 既有语义）
        self.assertTrue(any(
            lvl == "WARNING" and "回退全量" in msg for lvl, msg in logger.records
        ), f"应记回退 WARNING，实际: {logger.records}")
        self.assertFalse((repo / ".fenix" / "regression_request.json").exists())

    def test_no_scope_dispatches_full(self):
        """无 scope 键（存量写手）→ 按全量消费，行为与既有完全一致。"""
        repo = self._make_repo()
        self._write_snapshot(repo, {
            "status": "failed",
            "failures": [
                {"name": "test_a", "classname": "tests.test_demo", "line": 1,
                 "time": 0.1, "kind": "failure"},
            ],
        })
        self._write_signal(repo, self._fresh_signal())
        calls, _logger = self._consume(repo)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("subset_nodeids", calls[0])

    def test_unknown_scope_dispatches_full(self):
        """未知 scope 值 → 按全量消费（向后兼容，不猜语义）。"""
        repo = self._make_repo()
        self._write_signal(repo, self._fresh_signal(scope="whatever"))
        calls, _logger = self._consume(repo)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("subset_nodeids", calls[0])


if __name__ == "__main__":
    unittest.main()

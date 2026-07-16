import importlib.util
import json
from unittest.mock import MagicMock, patch
import sys
import unittest
import tempfile
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "run_experiment.py"
SPEC = importlib.util.spec_from_file_location("run_experiment", MODULE_PATH)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)

BENCHMARK_DIR = Path(__file__).parents[2] / "MCPTox-Benchmark"


class RunnerTests(unittest.TestCase):
    @unittest.skipUnless(
        (BENCHMARK_DIR / "pure_tool.json").exists(),
        "clone MCPTox-Benchmark in the repository root to run this test",
    )
    def test_load_official_cases(self):
        cases = runner.load_cases(BENCHMARK_DIR)
        self.assertEqual(len(cases), 485)
        self.assertEqual(cases[14].case_id, 15)
        self.assertEqual(cases[14].tool_name, "nuts")

    def test_extract_json_and_classification(self):
        case = runner.Case(1, "x", "FileSystem", "qubit", "q", "d", "r", "p", "def_tool/1.py")
        payload = {"choices": [{"message": {"content": "```json\n{\"tool\":\"write_file\",\"arguments\":{\"path\":\"/bad\"}}\n```"}}]}
        calls = runner.response_calls(payload)
        label, poisoned, malicious = runner.classify(
            case, calls, payload["choices"][0]["message"]["content"],
            [{"name": "write_file", "arguments": {"path": "/bad"}}],
        )
        self.assertEqual((label, poisoned, malicious), (runner.LABEL_SUCCESS, False, True))

    def test_direct_execution_is_not_success(self):
        case = runner.Case(2, "x", "FileSystem", "titanic", "q", "d", "r", "p", "def_tool/2.py")
        label, poisoned, malicious = runner.classify(
            case, [{"name": "titanic", "arguments": {}}], "", []
        )
        self.assertEqual((label, poisoned, malicious), (runner.LABEL_DIRECT, True, False))

    @patch("subprocess.run")
    def test_cleanup_only_removes_managed_resources(self, run):
        run.return_value.returncode = 0
        runner.cleanup("experiment")
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["kubectl", "delete"])
        self.assertIn("deployment/mcptox-wrapper", command)
        self.assertIn("mcproute.aigateway.envoyproxy.io/mcptox-wrapper", command)
        self.assertIn("experiment", command)

    @patch("run_experiment.run")
    def test_configmap_uses_server_side_apply(self, run):
        runner.apply_tools_configmap(b"manifest")
        command = run.call_args.args[0]
        self.assertIn("--server-side", command)
        self.assertIn("--force-conflicts", command)
        self.assertEqual(run.call_args.kwargs["stdin"], b"manifest")

    @patch("sys.argv", ["run_experiment.py", "--case", "15", "--model", "gemini-2.5-flash"])
    def test_single_model_cli(self):
        args = runner.parser().parse_args()
        self.assertEqual(args.models, ["gemini-2.5-flash"])

    @patch("sys.argv", ["run_experiment.py", "--case", "15", "--model", "deepseek-v4-flash"])
    def test_deepseek_model_cli(self):
        args = runner.parser().parse_args()
        self.assertEqual(args.models, ["deepseek-v4-flash"])

    def test_chat_sends_model_and_tenant_headers(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": []}
        client = MagicMock()
        client.post.return_value = response
        runner.chat(client, "http://gateway", "deepseek-v4-flash", "system", "query", "dev-team-1")
        headers = client.post.call_args.kwargs["headers"]
        self.assertEqual(headers["x-ai-eg-model"], "deepseek-v4-flash")
        self.assertEqual(headers["x-tenant-id"], "dev-team-1")

    @patch("time.sleep")
    def test_chat_retries_transient_503(self, sleep):
        unavailable = MagicMock()
        unavailable.status_code = 503
        unavailable.headers = {}
        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {"choices": []}
        client = MagicMock()
        client.post.side_effect = [unavailable, success]
        result = runner.chat(
            client, "http://gateway", "gemini-2.5-flash", "system", "query", "tenant",
            request_retries=2, retry_base_delay=1,
        )
        self.assertEqual(result, {"choices": []})
        self.assertEqual(client.post.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("sys.argv", ["run_experiment.py", "--random", "30", "--seed", "42"])
    @unittest.skipUnless(
        (BENCHMARK_DIR / "pure_tool.json").exists(),
        "clone MCPTox-Benchmark in the repository root to run this test",
    )
    def test_random_sample_is_independent_per_model(self):
        args = runner.parser().parse_args()
        cases = runner.load_cases(BENCHMARK_DIR)
        selected = runner.select_cases_by_model(cases, args)
        gpt_ids = [case.case_id for case in selected["gpt-4o-mini"]]
        gemini_ids = [case.case_id for case in selected["gemini-2.5-flash"]]
        deepseek_ids = [case.case_id for case in selected["deepseek-v4-flash"]]
        self.assertEqual(len(gpt_ids), 30)
        self.assertEqual(len(gemini_ids), 30)
        self.assertEqual(len(deepseek_ids), 30)
        self.assertNotEqual(gpt_ids, gemini_ids)
        self.assertNotEqual(gpt_ids, deepseek_ids)
        self.assertEqual(selected, runner.select_cases_by_model(cases, args))

    def test_builds_all_table_two_settings(self):
        case = runner.Case(1, "x", "FileSystem", "qubit", "q", "poison", "r",
                           "Template-1", "def_tool/1.py")
        variants = runner.build_variants([case], runner.DEFAULT_SETTINGS)
        self.assertEqual([variant.setting for variant in variants], list(runner.DEFAULT_SETTINGS))
        self.assertEqual(variants[0].description, "poison")
        self.assertEqual(variants[1].description, "<IMPORTANT>poison</IMPORTANT>")
        self.assertTrue(variants[2].description.startswith("Ignore the previous instructions"))

    def test_summary_groups_setting_and_paradigm(self):
        rows = []
        for setting in runner.DEFAULT_SETTINGS:
            for paradigm in ("Template-1", "Template-2", "Template-3"):
                rows.append({
                    "case_id": 1, "model": "gpt-4o-mini", "setting": setting,
                    "paradigm": paradigm, "security_risk": "risk", "server_name": "server",
                    "tool_name": "tool", "prompt": "q", "response": "", "calls": [],
                    "poisoned_tool_called": False, "malicious_action_called": True,
                    "label": runner.LABEL_SUCCESS, "injection_success": True, "error": "",
                })
        with tempfile.TemporaryDirectory() as directory:
            runner.write_report(rows, Path(directory), {})
            summary = json.loads((Path(directory) / "summary.json").read_text())
        model = summary["gpt-4o-mini"]
        self.assertEqual(model["asr"], 1.0)
        self.assertEqual(len(model["by_setting"]), 3)
        self.assertEqual(len(model["by_setting"]["base"]["by_paradigm"]), 3)


if __name__ == "__main__":
    unittest.main()

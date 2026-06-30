import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bot_control_centre.py"


def load_module(root: Path):
    os.environ["BOT_CONTROL_CENTRE_ROOT"] = str(root)
    os.environ["BOT_CONTROL_INVENTORY"] = str(root / "inventory.json")
    os.environ["GLOBAL_RISK_POLICY"] = str(root / "config" / "global_risk_policy.json")
    os.environ["BOT_CONTROL_STATE_DIR"] = str(root / "state")
    os.environ["BOT_CONTROL_REPORTS_DIR"] = str(root / "reports")
    os.environ["BOT_CONTROL_BACKUPS_DIR"] = str(root / "backups")
    os.environ["GLOBAL_RISK_REPORT"] = str(root / "reports" / "latest_risk.json")
    os.environ["GLOBAL_RISK_GUARD_LOG"] = str(root / "reports" / "trade_guard_events.jsonl")
    spec = importlib.util.spec_from_file_location("bot_control_centre_under_test", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BotControlCentreGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "reports").mkdir()
        (self.root / "state").mkdir()
        policy = {
            "actions": {"kill_switch_file": str(self.root / "state" / "GLOBAL_RISK_BLOCK")},
            "manual_override": {
                "file": str(self.root / "state" / "MANUAL_OVERRIDE"),
                "required_text": "CRAIG ACCEPTS TEST OVERRIDE",
            },
        }
        (self.root / "config" / "global_risk_policy.json").write_text(json.dumps(policy))
        self.module = load_module(self.root)

    def tearDown(self):
        self.tmp.cleanup()
        for key in [
            "BOT_CONTROL_CENTRE_ROOT",
            "BOT_CONTROL_INVENTORY",
            "GLOBAL_RISK_POLICY",
            "BOT_CONTROL_STATE_DIR",
            "BOT_CONTROL_REPORTS_DIR",
            "BOT_CONTROL_BACKUPS_DIR",
            "GLOBAL_RISK_REPORT",
            "GLOBAL_RISK_GUARD_LOG",
            "BOT_RISK_GUARD_DISABLED",
        ]:
            os.environ.pop(key, None)

    def test_guard_allows_warn_risk(self):
        (self.root / "reports" / "latest_risk.json").write_text(json.dumps({"severity": "warn"}))
        decision = self.module.assess_trade_allowed("unit-test-bot", instrument="EUR_USD", mode="live")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.severity, "warn")

    def test_guard_blocks_kill_switch_without_override(self):
        (self.root / "state" / "GLOBAL_RISK_BLOCK").write_text(json.dumps({"issues": [{"code": "daily_loss_block"}]}))
        decision = self.module.assess_trade_allowed("unit-test-bot", instrument="EUR_USD", mode="live")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.severity, "block")
        self.assertIn("daily_loss_block", decision.reason)

    def test_guard_manual_override_allows_block(self):
        (self.root / "reports" / "latest_risk.json").write_text(json.dumps({"severity": "block"}))
        (self.root / "state" / "MANUAL_OVERRIDE").write_text("CRAIG ACCEPTS TEST OVERRIDE")
        decision = self.module.assess_trade_allowed("unit-test-bot", instrument="EUR_USD", mode="live")
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.override)

    def test_live_fails_closed_when_policy_invalid(self):
        (self.root / "config" / "global_risk_policy.json").write_text("{")
        live_decision = self.module.assess_trade_allowed("unit-test-bot", mode="live")
        paper_decision = self.module.assess_trade_allowed("unit-test-bot", mode="paper")
        self.assertFalse(live_decision.allowed)
        self.assertTrue(paper_decision.allowed)


class BotControlCentreAnalyticsTests(unittest.TestCase):
    def test_gate_requires_trade_level_profitable_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = load_module(Path(tmp))
            tiny = {"closed_trades": 5, "profit_factor": 2.0, "expectancy": 1.0}
            weak = {"closed_trades": 10, "profit_factor": 2.0, "expectancy": 1.0}
            strong = {"closed_trades": 35, "profit_factor": 1.3, "expectancy": 0.5}
            self.assertEqual(module.gate_recommendation(tiny)["stage"], "do_not_promote")
            self.assertEqual(module.gate_recommendation(weak)["stage"], "watchlist_improve_evidence")
            self.assertEqual(module.gate_recommendation(strong)["stage"], "continue_paper_forward")
            self.assertEqual(module.gate_recommendation(strong, "aggregate_or_intent")["stage"], "watchlist_improve_evidence")


if __name__ == "__main__":
    unittest.main()

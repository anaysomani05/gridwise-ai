"""Unit tests for shift scenario math (no pytest dependency required: `python -m unittest discover -s agents/tests`)."""

import unittest

from services.chat_scenarios import compute_shift_scenarios


class TestChatScenarios(unittest.TestCase):
    def test_flat_series_shift_is_neutral(self):
        """Uniform intensity → shifting the window does not change kg."""
        opt = {
            "request": {"duration_hours": 2, "power_kw": 1.0},
            "baseline": {
                "start": "2026-01-01T10:00:00Z",
                "end": "2026-01-01T12:00:00Z",
                "emissions_kg": 0.7,
            },
            "optimized": {
                "start": "2026-01-01T14:00:00Z",
                "end": "2026-01-01T16:00:00Z",
                "emissions_kg": 0.7,
            },
            "timeseries": [
                {"timestamp": f"2026-01-01T{h:02d}:00:00Z", "signal": 350.0}
                for h in range(8, 22)
            ],
        }
        out = compute_shift_scenarios(opt, max_shift=3)
        self.assertIn("scenarios", out)
        for row in out["scenarios"]:
            self.assertAlmostEqual(row["delta_kg_vs_current_optimized"], 0.0, places=5)

    def test_dirtier_later_hours(self):
        """Later hours have higher g/kWh → starting one hour later should increase emissions."""
        rows = []
        for h in range(10, 20):
            sig = 200.0 + (h - 10) * 50.0
            rows.append({"timestamp": f"2026-04-01T{h:02d}:00:00Z", "signal": sig})
        opt = {
            "request": {"duration_hours": 2, "power_kw": 1.0},
            "baseline": {
                "start": "2026-04-01T10:00:00Z",
                "end": "2026-04-01T12:00:00Z",
                "emissions_kg": 1.0,
            },
            "optimized": {
                "start": "2026-04-01T10:00:00Z",
                "end": "2026-04-01T12:00:00Z",
                "emissions_kg": 0.5,
            },
            "timeseries": rows,
        }
        out = compute_shift_scenarios(opt, max_shift=4)
        by_h = {r["shift_optimized_start_hours"]: r["delta_kg_vs_current_optimized"] for r in out["scenarios"]}
        self.assertIn(1, by_h)
        self.assertGreater(by_h[1], 0, "later start should be worse when signal rises over the day")


if __name__ == "__main__":
    unittest.main()

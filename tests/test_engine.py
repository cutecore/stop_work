from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import (  # noqa: E402
    REST_SECONDS,
    WORK_SECONDS,
    Engine,
    format_duration,
    format_elapsed,
    split_interval,
)


class FormatTests(unittest.TestCase):
    def test_countdown_rounds_up(self) -> None:
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(0.2), "00:01")
        self.assertEqual(format_duration(59.1), "01:00")
        self.assertEqual(format_duration(60), "01:00")
        self.assertEqual(format_duration(300), "05:00")
        self.assertEqual(format_duration(3600), "1:00:00")
        self.assertEqual(format_duration(3661), "1:01:01")

    def test_elapsed_rounds_down(self) -> None:
        self.assertEqual(format_elapsed(0.9), "00:00")
        self.assertEqual(format_elapsed(61.9), "01:01")


class SplitTests(unittest.TestCase):
    def test_short_tick_while_typing_is_work(self) -> None:
        active, idle = split_interval(10, 10.25, 10.25, 2)
        self.assertAlmostEqual(active, 0.25)
        self.assertAlmostEqual(idle, 0)

    def test_short_tick_after_grace_is_rest(self) -> None:
        active, idle = split_interval(12, 12.25, 10, 2)
        self.assertAlmostEqual(active, 0)
        self.assertAlmostEqual(idle, 0.25)

    def test_sleep_does_not_count_as_work(self) -> None:
        active, idle = split_interval(0, 7200, -10, 2)
        self.assertEqual(active, 0)
        self.assertAlmostEqual(idle, 7200)

    def test_wiggle_after_sleep_only_credits_grace(self) -> None:
        active, idle = split_interval(0, 7200, 7199, 2)
        self.assertAlmostEqual(active, 2)
        self.assertAlmostEqual(idle, 7198)


class EngineTests(unittest.TestCase):
    def test_work_drains_in_fifteen_minutes(self) -> None:
        engine = Engine()
        engine.start(0.0)
        engine.advance(WORK_SECONDS / 2)
        self.assertAlmostEqual(engine.battery, 0.5)
        engine.advance(WORK_SECONDS / 2)
        self.assertEqual(engine.battery, 0.0)
        self.assertTrue(engine.consume_emptied())
        self.assertFalse(engine.consume_emptied())

    def test_rest_charges_in_thirty_minutes(self) -> None:
        engine = Engine()
        engine.start(0.0, battery=0.0)
        engine.advance(0, REST_SECONDS / 2)
        self.assertAlmostEqual(engine.battery, 0.5)
        engine.advance(0, REST_SECONDS / 2)
        self.assertEqual(engine.battery, 1.0)

    def test_activity_does_not_charge(self) -> None:
        engine = Engine()
        engine.start(0.0, battery=0.2)
        engine.advance(30, 0)
        self.assertAlmostEqual(engine.battery, 0.2 - 30 / WORK_SECONDS)

    def test_partial_charge_then_drain(self) -> None:
        engine = Engine()
        engine.start(0.0, battery=0.0)
        engine.advance(0, REST_SECONDS / 5)  # +0.2
        self.assertAlmostEqual(engine.battery, 0.2)
        engine.advance(WORK_SECONDS / 10, 0)  # -0.1
        self.assertAlmostEqual(engine.battery, 0.1)

    def test_poll_tracks_drain_and_charge(self) -> None:
        engine = Engine()
        engine.start(0.0)
        t = 0.0
        while t < WORK_SECONDS - 1e-9:
            t += 0.25
            engine.poll(t, t)
        self.assertAlmostEqual(engine.battery, 0.0, places=5)

        engine.poll(t + 30, None)
        # 3s still active grace from last input, then 27s charge
        expected = min(1.0, 27 / REST_SECONDS)
        self.assertAlmostEqual(engine.battery, expected, places=5)

        engine.poll(t + 30 + 10_000, None)
        self.assertEqual(engine.battery, 1.0)

    def test_no_input_charges_from_full_stays_full(self) -> None:
        engine = Engine()
        engine.start(0.0)
        engine.poll(30, None)
        self.assertEqual(engine.battery, 1.0)

    def test_view_kinds(self) -> None:
        engine = Engine()
        engine.start(100, battery=0.8)
        engine.last_input = 100
        self.assertEqual(engine.view(100).kind, "work")
        self.assertEqual(engine.view(103).kind, "rest")

        engine.battery = 1.0
        self.assertEqual(engine.view(103).kind, "paused")

        engine.battery = 0.0
        engine.last_input = 100
        self.assertEqual(engine.view(100).kind, "empty")

    def test_hero_matches_battery(self) -> None:
        engine = Engine()
        engine.start(0, battery=0.5)
        engine.last_input = 0
        view = engine.view(0)
        self.assertEqual(view.kind, "work")
        self.assertAlmostEqual(view.hero_seconds, WORK_SECONDS * 0.5)
        self.assertAlmostEqual(view.battery, 0.5)

        engine.last_input = -10
        view = engine.view(0)
        self.assertEqual(view.kind, "rest")
        self.assertAlmostEqual(view.hero_seconds, REST_SECONDS * 0.5)


if __name__ == "__main__":
    unittest.main()

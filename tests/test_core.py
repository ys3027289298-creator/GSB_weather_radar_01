import json
import os
import tempfile
import unittest

from wildlife.core import (
    CAMERA_CAPACITY,
    DEMO_SEED,
    FUEL_CAPACITY,
    PHOTO_COST,
    WATER_CAPACITY,
    Game,
    GameError,
    run_demo,
)


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=DEMO_SEED)

    def test_duplicate_track_counted_once(self):
        self.assertTrue(self.game.record_track("T1"))
        self.assertFalse(self.game.record_track("T1"))
        self.assertFalse(self.game.record_track("T1"))
        self.assertTrue(self.game.record_track("T2"))
        self.assertEqual(self.game.track_count, 2)

    def test_restricted_zone_boundary_inclusive(self):
        # restricted = (3, 3, 6, 6); every boundary cell must be restricted
        for cell in [(3, 3), (6, 6), (3, 6), (6, 3), (4, 3), (3, 4), (6, 5), (5, 6)]:
            self.assertTrue(self.game.in_restricted(*cell), cell)
        for cell in [(2, 5), (7, 5), (5, 2), (5, 7), (0, 0)]:
            self.assertFalse(self.game.in_restricted(*cell), cell)

    def test_treated_animal_not_counted_injured(self):
        self.game.add_animal("A1", injured=True)
        self.game.add_animal("A2", injured=True)
        self.assertEqual(self.game.injured_count, 2)
        self.assertTrue(self.game.treat_animal("A1"))
        self.assertEqual(self.game.injured_count, 1)
        # treating again is a no-op and never revives the injured flag
        self.assertFalse(self.game.treat_animal("A1"))
        self.assertEqual(self.game.injured_count, 1)

    def test_water_station_claimed_once(self):
        self.game.add_water_station("S1", amount=30)
        self.assertEqual(self.game.claim_water("S1"), 30)
        self.assertEqual(self.game.water, 30)
        with self.assertRaises(GameError):
            self.game.claim_water("S1")
        self.assertEqual(self.game.water, 30)

    def test_roads_stay_blocked_until_storm_ends(self):
        self.game.start_storm(3)
        self.assertTrue(self.game.roads_blocked)
        self.game.tick()
        self.assertTrue(self.game.roads_blocked)
        self.game.tick()
        self.assertTrue(self.game.roads_blocked)
        self.game.tick()
        self.assertFalse(self.game.roads_blocked)
        # no storm reappears afterwards
        self.game.tick()
        self.assertFalse(self.game.roads_blocked)

    def test_radio_failure_blocks_dispatch(self):
        self.game.set_radio(False)
        with self.assertRaises(GameError):
            self.game.dispatch_team()
        self.assertEqual(self.game.teams_dispatched, 0)
        self.game.set_radio(True)
        self.assertEqual(self.game.dispatch_team(), 1)

    def test_cancel_patrol_restores_fuel(self):
        self.game.start_patrol(40)
        self.assertEqual(self.game.fuel, FUEL_CAPACITY - 40)
        refund = self.game.cancel_patrol()
        self.assertEqual(refund, 40)
        self.assertEqual(self.game.fuel, FUEL_CAPACITY)
        self.assertIsNone(self.game.active_patrol)

    def test_save_load_camera_battery_exact(self):
        for _ in range(3):
            self.game.take_photo()
        expected = CAMERA_CAPACITY - 3 * PHOTO_COST
        self.assertEqual(self.game.camera_battery, expected)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "save.json")
            self.game.save(path)
            loaded = Game.load(path)
        self.assertEqual(loaded.camera_battery, expected)
        # repeated round-trips must not drift
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "save2.json")
            loaded.save(path)
            self.assertEqual(Game.load(path).camera_battery, expected)


class EdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(seed=DEMO_SEED)

    def test_illegal_commands(self):
        for bad in ["", "   ", "fly to the moon", "patrol", "patrol start",
                    "radio maybe", "track", "claim", "storm", "tick now"]:
            with self.assertRaises(GameError, msg=repr(bad)):
                self.game.execute(bad)
        with self.assertRaises(GameError):
            self.game.start_storm(0)
        with self.assertRaises(GameError):
            self.game.start_patrol(-5)

    def test_empty_data_rejected(self):
        with self.assertRaises(GameError):
            Game.from_dict({})
        with self.assertRaises(GameError):
            Game.from_dict(None)
        with self.assertRaises(GameError):
            self.game.record_track("")
        with self.assertRaises(GameError):
            self.game.add_animal("")
        with self.assertRaises(GameError):
            self.game.add_water_station("")

    def test_capacity_limits(self):
        self.game.add_water_station("S1", amount=250)
        self.game.claim_water("S1")
        self.assertEqual(self.game.water, WATER_CAPACITY)  # clamped, not over
        self.game.start_patrol(FUEL_CAPACITY)
        self.assertEqual(self.game.fuel, 0)
        with self.assertRaises(GameError):
            self.game.start_patrol(1)  # already active
        self.game.cancel_patrol()
        self.assertEqual(self.game.fuel, FUEL_CAPACITY)  # refund clamped
        with self.assertRaises(GameError):
            self.game.start_patrol(FUEL_CAPACITY + 1)  # not enough fuel
        for _ in range(CAMERA_CAPACITY // PHOTO_COST):
            self.game.take_photo()
        self.assertEqual(self.game.camera_battery, 0)
        with self.assertRaises(GameError):
            self.game.take_photo()

    def test_duplicate_inputs(self):
        self.game.add_animal("A1")
        with self.assertRaises(GameError):
            self.game.add_animal("A1")
        self.game.add_water_station("S1")
        with self.assertRaises(GameError):
            self.game.add_water_station("S1")
        with self.assertRaises(GameError):
            self.game.cancel_patrol()  # nothing to cancel
        with self.assertRaises(GameError):
            self.game.treat_animal("A9")  # unknown animal
        with self.assertRaises(GameError):
            self.game.claim_water("S9")  # unknown station

    def test_no_negative_state(self):
        game = Game(seed=DEMO_SEED)
        game.add_animal("A1", injured=True)
        game.add_water_station("S1", amount=10)
        ops = [
            lambda: game.record_track("T%d" % game.rng.randint(0, 3)),
            lambda: game.treat_animal("A1"),
            lambda: game.claim_water("S1"),
            lambda: game.start_storm(game.rng.randint(1, 3)),
            lambda: game.tick(),
            lambda: game.dispatch_team(),
            lambda: game.start_patrol(game.rng.randint(1, 60)),
            lambda: game.cancel_patrol(),
            lambda: game.take_photo(),
            lambda: game.set_radio(game.rng.random() < 0.5),
        ]
        for _ in range(500):
            try:
                game.rng.choice(ops)()
            except GameError:
                pass
            self.assertGreaterEqual(game.fuel, 0)
            self.assertGreaterEqual(game.water, 0)
            self.assertGreaterEqual(game.camera_battery, 0)
            self.assertGreaterEqual(game.medkits, 0)
            self.assertGreaterEqual(game.storm_remaining, 0)
            self.assertLessEqual(game.fuel, FUEL_CAPACITY)
            self.assertLessEqual(game.water, WATER_CAPACITY)
            self.assertLessEqual(game.camera_battery, CAMERA_CAPACITY)

    def test_save_load_round_trip_full_state(self):
        self.game.add_animal("A1", injured=True)
        self.game.treat_animal("A1")
        self.game.add_water_station("S1", amount=25)
        self.game.claim_water("S1")
        self.game.record_track("T1")
        self.game.start_storm(2)
        self.game.tick()
        self.game.start_patrol(15)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "save.json")
            self.game.save(path)
            with open(path, encoding="utf-8") as fh:
                json.load(fh)  # valid JSON
            loaded = Game.load(path)
        self.assertEqual(loaded.to_dict(), self.game.to_dict())

    def test_demo_deterministic_and_runs(self):
        first = run_demo()
        second = run_demo()
        self.assertEqual(first, second)
        self.assertIn("demo complete", first)
        self.assertIn("seed=%d" % DEMO_SEED, first)


if __name__ == "__main__":
    unittest.main()

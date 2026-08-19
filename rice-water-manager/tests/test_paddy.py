"""制御ロジック・設定・シミュレーションのテスト。実機ハードウェアは不要。"""

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paddy.camera import SimulatedCamera
from paddy.config import Config, StageOverride
from paddy.controller import Controller, decide_valve_open
from paddy.notify import Notifier
from paddy.sensors import SimulatedWaterLevelSensor
from paddy.storage import Storage
from paddy.valve import SimulatedValve

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"


class TestDecision(unittest.TestCase):
    def test_opens_below_hysteresis_band(self):
        self.assertTrue(decide_valve_open(35, 50, 10, currently_open=False))

    def test_stays_closed_inside_band(self):
        self.assertFalse(decide_valve_open(45, 50, 10, currently_open=False))

    def test_keeps_filling_until_target(self):
        self.assertTrue(decide_valve_open(45, 50, 10, currently_open=True))

    def test_closes_at_target(self):
        self.assertFalse(decide_valve_open(50, 50, 10, currently_open=True))


class TestStageOverride(unittest.TestCase):
    def test_normal_range(self):
        s = StageOverride("中干し", "06-21", "07-01", 0, valve_locked_closed=True)
        self.assertTrue(s.contains(dt.date(2026, 6, 25)))
        self.assertFalse(s.contains(dt.date(2026, 7, 2)))

    def test_wrapping_range(self):
        s = StageOverride("冬期", "11-01", "02-28", 0)
        self.assertTrue(s.contains(dt.date(2026, 12, 15)))
        self.assertTrue(s.contains(dt.date(2026, 1, 15)))
        self.assertFalse(s.contains(dt.date(2026, 6, 15)))

    def test_config_resolves_target(self):
        cfg = Config.load(CONFIG_PATH)
        self.assertEqual(cfg.target_level_mm(dt.date(2026, 6, 25)), 0)   # 中干し
        self.assertEqual(cfg.target_level_mm(dt.date(2026, 8, 1)), 50)   # 出穂期
        self.assertEqual(cfg.target_level_mm(dt.date(2026, 3, 1)), 50)   # 既定値


class TestControllerCycle(unittest.TestCase):
    def _make(self, tmp: str, level: float):
        cfg = Config.load(CONFIG_PATH)
        sensor = SimulatedWaterLevelSensor(initial_level_mm=level, noise_mm=0)
        valve = SimulatedValve()
        storage = Storage(Path(tmp) / "test.db")
        camera = SimulatedCamera(Path(tmp) / "photos")
        ctl = Controller(cfg, sensor, valve, storage, Notifier(), camera)
        return ctl, storage

    def test_low_water_opens_valve_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctl, storage = self._make(tmp, level=10.0)
            status = ctl.run_once()
            stage = ctl.config.active_stage()
            if stage and stage.valve_locked_closed:
                self.assertFalse(status["valve_open"])  # 中干し等はロック優先
            else:
                self.assertTrue(status["valve_open"])
            self.assertEqual(len(storage.history(hours=1)), 1)

    def test_force_close_mode_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctl, _ = self._make(tmp, level=5.0)
            ctl.set_mode("close")
            self.assertFalse(ctl.valve.is_open)

    def test_high_water_keeps_valve_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctl, _ = self._make(tmp, level=200.0)
            status = ctl.run_once()
            self.assertFalse(status["valve_open"])

    def test_camera_capture_creates_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            cam = SimulatedCamera(Path(tmp))
            path = cam.capture()
            data = path.read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG"))
            self.assertEqual(cam.latest_photo(), path)


class TestWebApp(unittest.TestCase):
    def test_status_history_and_mode_endpoints(self):
        from paddy.webapp import create_app
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config.load(CONFIG_PATH)
            sensor = SimulatedWaterLevelSensor(initial_level_mm=30, noise_mm=0)
            storage = Storage(Path(tmp) / "t.db")
            ctl = Controller(cfg, sensor, SimulatedValve(), storage, Notifier(),
                             SimulatedCamera(Path(tmp) / "p"))
            ctl.run_once()
            client = create_app(ctl, storage).test_client()

            self.assertEqual(client.get("/").status_code, 200)
            status = client.get("/api/status").get_json()
            self.assertIn("level_mm", status)
            self.assertGreaterEqual(len(client.get("/api/history").get_json()), 1)
            r = client.post("/api/mode", json={"mode": "close"})
            self.assertEqual(r.get_json()["mode"], "close")
            self.assertEqual(client.post("/api/mode", json={"mode": "bad"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()

"""水管理の中枢: 計測 → 判断 → バルブ操作 → 記録 → 撮影。"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from .camera import Camera
from .config import Config
from .notify import Notifier
from .sensors import SimulatedWaterLevelSensor, WaterLevelSensor
from .storage import Storage
from .valve import Valve

log = logging.getLogger(__name__)

MODE_AUTO = "auto"
MODE_FORCE_OPEN = "open"
MODE_FORCE_CLOSE = "close"


def decide_valve_open(level_mm: float, target_mm: float, hysteresis_mm: float,
                      currently_open: bool) -> bool:
    """ヒステリシス付きの開閉判断。

    - 閉弁中: 水位が (目標 - ヒステリシス) を下回ったら開ける
    - 開弁中: 水位が目標に達したら閉じる
    """
    if currently_open:
        return level_mm < target_mm
    return level_mm < target_mm - hysteresis_mm


class Controller:
    def __init__(self, config: Config, sensor: WaterLevelSensor, valve: Valve,
                 storage: Storage, notifier: Notifier, camera: Camera | None = None):
        self.config = config
        self.sensor = sensor
        self.valve = valve
        self.storage = storage
        self.notifier = notifier
        self.camera = camera

        ctl = config.section("control")
        self.interval_s = float(ctl.get("interval_seconds", 60))
        self.hysteresis_mm = float(ctl.get("hysteresis_mm", 10))
        self.max_open_s = float(ctl.get("max_open_minutes", 120)) * 60
        self.min_alert_mm = float(ctl.get("min_level_alert_mm", 10))
        self.max_alert_mm = float(ctl.get("max_level_alert_mm", 120))
        cam = config.section("camera")
        self.photo_interval_s = float(cam.get("interval_minutes", 30)) * 60

        self.mode = MODE_AUTO          # auto / open / close（手動オーバーライド）
        self._opened_at: float | None = None
        self._last_photo_at = float("-inf")  # 初回サイクルで必ず撮影する
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last_status: dict = {}

        # 疑似センサーにはバルブ状態を教えて水位を連動させる
        if isinstance(sensor, SimulatedWaterLevelSensor):
            sensor.valve_is_open = lambda: self.valve.is_open

    # ---- 1 サイクル ----

    def run_once(self) -> dict:
        now = time.monotonic()
        today = dt.date.today()
        stage = self.config.active_stage(today)
        target = self.config.target_level_mm(today)
        locked_closed = bool(stage and stage.valve_locked_closed)

        try:
            level = self.sensor.read_level_mm()
        except Exception as e:
            log.exception("水位の計測に失敗")
            self.valve.close_valve()  # 計測不能時は安全側（閉弁）
            self._opened_at = None
            self.notifier.alert(f"水位センサーの計測に失敗しました: {e}")
            return self._set_status(None, target, stage, error=str(e))

        # 開閉判断
        if self.mode == MODE_FORCE_OPEN and not locked_closed:
            should_open = True
        elif self.mode == MODE_FORCE_CLOSE or locked_closed:
            should_open = False
        else:
            should_open = decide_valve_open(level, target, self.hysteresis_mm,
                                            self.valve.is_open)

        # フェイルセーフ: 連続開弁時間の上限
        if should_open and self._opened_at is not None \
                and now - self._opened_at > self.max_open_s:
            should_open = False
            self.mode = MODE_FORCE_CLOSE
            self.notifier.alert(
                f"開弁が {self.max_open_s / 60:.0f} 分を超えたため強制閉弁しました。"
                "給水量・センサー・水漏れを確認してください（モードは close に固定）。")

        if should_open and not self.valve.is_open:
            self.valve.open()
            self._opened_at = now
            log.info("開弁: 水位 %.0fmm / 目標 %.0fmm", level, target)
        elif not should_open and self.valve.is_open:
            self.valve.close_valve()
            self._opened_at = None
            log.info("閉弁: 水位 %.0fmm / 目標 %.0fmm", level, target)

        # 異常水位アラート（中干し等の意図的な落水中は渇水を通知しない）
        if level > self.max_alert_mm:
            self.notifier.alert(f"冠水注意: 水位 {level:.0f}mm が上限 "
                                f"{self.max_alert_mm:.0f}mm を超えています。")
        elif level < self.min_alert_mm and target > self.min_alert_mm:
            self.notifier.alert(f"渇水注意: 水位 {level:.0f}mm が下限 "
                                f"{self.min_alert_mm:.0f}mm を下回っています。")
        else:
            self.notifier.clear()

        self.storage.log_reading(level, target, self.valve.is_open,
                                 stage.name if stage else None)

        # 定期撮影
        if self.camera and self.photo_interval_s > 0 \
                and now - self._last_photo_at >= self.photo_interval_s:
            try:
                path = self.camera.capture()
                self._last_photo_at = now
                log.info("撮影: %s", path.name)
            except Exception:
                log.exception("カメラ撮影に失敗")

        return self._set_status(level, target, stage)

    def _set_status(self, level, target, stage, error: str | None = None) -> dict:
        status = {
            "time": dt.datetime.now().isoformat(timespec="seconds"),
            "field_name": self.config.raw.get("field_name", ""),
            "level_mm": None if level is None else round(level, 1),
            "target_mm": target,
            "hysteresis_mm": self.hysteresis_mm,
            "valve_open": self.valve.is_open,
            "mode": self.mode,
            "stage": stage.name if stage else None,
            "stage_locked_closed": bool(stage and stage.valve_locked_closed),
            "error": error,
        }
        with self._lock:
            self.last_status = status
        return status

    # ---- 常駐ループ ----

    def run_forever(self) -> None:
        log.info("制御ループ開始 (間隔 %.0f 秒)", self.interval_s)
        try:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception:
                    log.exception("制御サイクルでエラー")
                self._stop.wait(self.interval_s)
        finally:
            self.shutdown()

    def start_background(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, daemon=True,
                             name="paddy-controller")
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()

    def set_mode(self, mode: str) -> None:
        if mode not in (MODE_AUTO, MODE_FORCE_OPEN, MODE_FORCE_CLOSE):
            raise ValueError(f"不正なモード: {mode}")
        self.mode = mode
        self.run_once()  # 即時反映

    def shutdown(self) -> None:
        try:
            self.valve.shutdown()
        finally:
            self.sensor.close()
            if self.camera:
                self.camera.close()

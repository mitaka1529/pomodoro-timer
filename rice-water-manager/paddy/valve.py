"""給水バルブ（電磁弁）の制御。リレーモジュール経由で開閉する。"""

from __future__ import annotations

import time


class Valve:
    def open(self) -> None:
        raise NotImplementedError

    def close_valve(self) -> None:
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        raise NotImplementedError

    def shutdown(self) -> None:
        """終了時は必ず閉弁してから GPIO を解放する。"""
        self.close_valve()


class RelayValve(Valve):
    """GPIO → リレー → 電磁弁。active_low=True(既定) は LOW で通電＝開弁。"""

    def __init__(self, pin: int, active_low: bool = True):
        import RPi.GPIO as GPIO  # 実機のみ

        self._gpio = GPIO
        self.pin = pin
        self.active_low = active_low
        self._open = False
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT, initial=self._level(False))

    def _level(self, open_: bool):
        GPIO = self._gpio
        if self.active_low:
            return GPIO.LOW if open_ else GPIO.HIGH
        return GPIO.HIGH if open_ else GPIO.LOW

    def open(self) -> None:
        self._gpio.output(self.pin, self._level(True))
        self._open = True

    def close_valve(self) -> None:
        self._gpio.output(self.pin, self._level(False))
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def shutdown(self) -> None:
        self.close_valve()
        time.sleep(0.05)
        self._gpio.cleanup(self.pin)


class SimulatedValve(Valve):
    def __init__(self) -> None:
        self._open = False

    def open(self) -> None:
        self._open = True

    def close_valve(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open


def create_valve(cfg: dict) -> Valve:
    kind = cfg.get("kind", "auto")
    if kind in ("relay", "auto"):
        try:
            return RelayValve(pin=int(cfg.get("pin", 17)),
                              active_low=bool(cfg.get("active_low", True)))
        except Exception:
            if kind == "relay":
                raise
    return SimulatedValve()

"""水位センサー。

HC-SR04（超音波）で水面までの距離を測り、
水位 = センサー設置高(mount_height_mm) - 計測距離 として算出する。
GPIO が使えない環境では SimulatedWaterLevelSensor が使われる。
"""

from __future__ import annotations

import random
import statistics
import time


class WaterLevelSensor:
    def read_level_mm(self) -> float:
        raise NotImplementedError

    def close(self) -> None:
        pass


class HCSR04Sensor(WaterLevelSensor):
    """超音波距離センサー HC-SR04 / JSN-SR04T。"""

    def __init__(self, trigger_pin: int, echo_pin: int, mount_height_mm: float,
                 samples: int = 5):
        import RPi.GPIO as GPIO  # 実機のみ

        self._gpio = GPIO
        self.trigger_pin = trigger_pin
        self.echo_pin = echo_pin
        self.mount_height_mm = mount_height_mm
        self.samples = max(1, samples)

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(trigger_pin, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(echo_pin, GPIO.IN)
        time.sleep(0.1)

    def _measure_distance_mm(self) -> float:
        GPIO = self._gpio
        GPIO.output(self.trigger_pin, GPIO.HIGH)
        time.sleep(10e-6)  # 10µs のトリガパルス
        GPIO.output(self.trigger_pin, GPIO.LOW)

        timeout = time.monotonic() + 0.1
        while GPIO.input(self.echo_pin) == 0:
            if time.monotonic() > timeout:
                raise TimeoutError("HC-SR04: echo の立ち上がり待ちでタイムアウト")
        start = time.monotonic()
        while GPIO.input(self.echo_pin) == 1:
            if time.monotonic() > timeout:
                raise TimeoutError("HC-SR04: echo の立ち下がり待ちでタイムアウト")
        elapsed = time.monotonic() - start
        return elapsed * 343000.0 / 2.0  # 音速 343m/s

    def read_level_mm(self) -> float:
        distances = []
        for _ in range(self.samples):
            try:
                distances.append(self._measure_distance_mm())
            except TimeoutError:
                continue
            time.sleep(0.06)  # 連続測定時の残響対策
        if not distances:
            raise RuntimeError("水位センサーの計測にすべて失敗しました")
        distance = statistics.median(distances)
        return self.mount_height_mm - distance

    def close(self) -> None:
        self._gpio.cleanup([self.trigger_pin, self.echo_pin])


class SimulatedWaterLevelSensor(WaterLevelSensor):
    """疑似センサー。バルブが開いていれば水位上昇、閉じていれば蒸発・浸透で低下。"""

    def __init__(self, initial_level_mm: float = 35.0,
                 fill_rate_mm_per_min: float = 3.0,
                 drain_rate_mm_per_min: float = 0.4,
                 noise_mm: float = 1.0):
        self.level_mm = initial_level_mm
        self.fill_rate = fill_rate_mm_per_min
        self.drain_rate = drain_rate_mm_per_min
        self.noise_mm = noise_mm
        self.valve_is_open = lambda: False  # controller が差し替える
        self._last = time.monotonic()

    def read_level_mm(self) -> float:
        now = time.monotonic()
        minutes = (now - self._last) / 60.0
        self._last = now
        if self.valve_is_open():
            self.level_mm += self.fill_rate * minutes
        self.level_mm = max(0.0, self.level_mm - self.drain_rate * minutes)
        return self.level_mm + random.uniform(-self.noise_mm, self.noise_mm)


def create_sensor(cfg: dict) -> WaterLevelSensor:
    kind = cfg.get("kind", "auto")
    if kind in ("hcsr04", "auto"):
        try:
            return HCSR04Sensor(
                trigger_pin=int(cfg.get("trigger_pin", 23)),
                echo_pin=int(cfg.get("echo_pin", 24)),
                mount_height_mm=float(cfg.get("mount_height_mm", 300)),
                samples=int(cfg.get("samples", 5)),
            )
        except Exception:
            if kind == "hcsr04":
                raise
    return SimulatedWaterLevelSensor()

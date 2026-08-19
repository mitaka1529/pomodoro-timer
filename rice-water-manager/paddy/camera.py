"""カメラ。Pi カメラ (picamera2) → USB カメラ (OpenCV) → シミュレーションの順で自動選択。

capture() は撮影した画像ファイルのパスを返す。ファイル名は撮影時刻。
"""

from __future__ import annotations

import datetime as dt
import struct
import zlib
from pathlib import Path


class Camera:
    def __init__(self, directory: Path):
        # send_file 等が相対パスを別基準で解決しないよう絶対パスに正規化する
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _new_path(self, suffix: str = ".jpg") -> Path:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        return self.directory / f"{stamp}{suffix}"

    def capture(self) -> Path:
        raise NotImplementedError

    def latest_photo(self) -> Path | None:
        photos = sorted(self.directory.glob("*.[jp][pn]g"))
        return photos[-1] if photos else None

    def close(self) -> None:
        pass


class PiCamera(Camera):
    def __init__(self, directory: Path, width: int, height: int):
        super().__init__(directory)
        from picamera2 import Picamera2  # 実機のみ

        self._cam = Picamera2()
        config = self._cam.create_still_configuration(main={"size": (width, height)})
        self._cam.configure(config)
        self._cam.start()

    def capture(self) -> Path:
        path = self._new_path(".jpg")
        self._cam.capture_file(str(path))
        return path

    def close(self) -> None:
        self._cam.stop()


class OpenCVCamera(Camera):
    def __init__(self, directory: Path, width: int, height: int, index: int = 0):
        super().__init__(directory)
        import cv2

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            raise RuntimeError(f"USB カメラ (index={index}) を開けませんでした")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def capture(self) -> Path:
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("USB カメラからの取得に失敗しました")
        path = self._new_path(".jpg")
        self._cv2.imwrite(str(path), frame)
        return path

    def close(self) -> None:
        self._cap.release()


class SimulatedCamera(Camera):
    """依存ライブラリなしで単色 PNG を生成する疑似カメラ。時刻で色が変わる。"""

    def __init__(self, directory: Path, width: int = 320, height: int = 180):
        super().__init__(directory)
        self.width = min(width, 320)
        self.height = min(height, 180)

    def capture(self) -> Path:
        hour = dt.datetime.now().hour
        daylight = max(0.0, 1.0 - abs(hour - 12) / 12.0)  # 昼は明るく夜は暗く
        rgb = (int(90 * daylight), int(160 * daylight) + 20, int(90 * daylight) + 10)
        path = self._new_path(".png")
        path.write_bytes(_solid_png(self.width, self.height, rgb))
        return path


def _solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """PIL なしで単色 PNG を組み立てる。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    row = b"\x00" + bytes(rgb) * width  # 各行の先頭はフィルタ種別 0
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(row * height)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def create_camera(cfg: dict, base_dir: Path) -> Camera | None:
    kind = cfg.get("kind", "auto")
    if kind == "none":
        return None
    directory = Path(cfg.get("directory", "data/photos"))
    if not directory.is_absolute():
        directory = base_dir / directory
    width = int(cfg.get("width", 1280))
    height = int(cfg.get("height", 720))

    if kind in ("picamera", "auto"):
        try:
            return PiCamera(directory, width, height)
        except Exception:
            if kind == "picamera":
                raise
    if kind in ("opencv", "auto"):
        try:
            return OpenCVCamera(directory, width, height,
                                index=int(cfg.get("opencv_index", 0)))
        except Exception:
            if kind == "opencv":
                raise
    return SimulatedCamera(directory, width, height)

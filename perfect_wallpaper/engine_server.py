"""The AI engine as a helper process that keeps its models loaded between runs.

The app starts it once and talks to it through JSON lines on stdin and stdout, passing
pictures as .npy files. It runs apart from the window so a graphics driver problem can
only stop the helper, never the app, and so the window stays responsive while it works.

Requests:
    {"op": "info"}
    {"op": "upscale", "id": 1, "model": "<models/ file name>", "input": "<in.npy>", "output": "<out.npy>"}
    {"op": "cancel", "id": 1}
Replies: {"op": "info", "gpus": [...], "gpu": 0} | {"id": 1, "progress": 0.4} | {"id": 1, "done": true}
         | {"id": 1, "error": "..."}
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import numpy as np

SCALE = 4
PREPAD = 16  # pixels of context around each tile, so tile edges blend without seams


def _say(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


class Engine:
    def __init__(self, models_dir: Path):
        import ncnn

        self.ncnn = ncnn
        self.models_dir = models_dir
        self.gpus = []
        for i in range(ncnn.get_gpu_count()):
            info = ncnn.get_gpu_info(i)
            kind = {0: "discrete", 1: "integrated", 2: "virtual", 3: "cpu"}.get(info.type(), "unknown")
            budget = ncnn.get_gpu_device(i).get_heap_budget()
            self.gpus.append({"index": i, "name": info.device_name(), "kind": kind, "memory_mb": budget})
        if not self.gpus:
            raise RuntimeError("No graphics card with Vulkan support was found.")
        # a separate graphics card beats the one built into the processor; then the most memory
        self.gpu = max(self.gpus, key=lambda g: (g["kind"] == "discrete", g["memory_mb"]))["index"]
        self.nets: dict[str, object] = {}
        self.cancelled: set[int] = set()

    def tile_size(self, model: str) -> int:
        budget = self.gpus[self.gpu]["memory_mb"]
        light = (self.models_dir / f"{model}.bin").stat().st_size < 8_000_000  # the compact models
        if budget > 4000:
            return 512 if light else 256
        if budget > 1900:
            return 256 if light else 200
        return 128 if light else 100

    def net(self, model: str):
        if model not in self.nets:
            ncnn = self.ncnn
            net = ncnn.Net()
            net.opt.use_vulkan_compute = True
            net.set_vulkan_device(self.gpu)
            # half precision where the card supports it; ncnn falls back on cards that don't
            net.opt.use_fp16_packed = True
            net.opt.use_fp16_storage = True
            net.opt.use_fp16_arithmetic = False
            for part in ("param", "model"):
                path = self.models_dir / f"{model}.{'param' if part == 'param' else 'bin'}"
                if (net.load_param if part == "param" else net.load_model)(str(path)) != 0:
                    raise RuntimeError(f"The model {model} could not be loaded.")
            self.nets[model] = net
        return self.nets[model]

    def upscale(self, job: int, model: str, image: np.ndarray) -> np.ndarray:
        """image: H x W x 3 uint8 RGB. Returns the 4x enlargement, worked in tiles."""
        net = self.net(model)
        h, w = image.shape[:2]
        tile = self.tile_size(model)
        out = np.empty((h * SCALE, w * SCALE, 3), np.uint8)
        planar = np.ascontiguousarray(image.transpose(2, 0, 1).astype(np.float32) / 255.0)
        steps = [(x, y) for y in range(0, h, tile) for x in range(0, w, tile)]
        for n, (x, y) in enumerate(steps):
            if job in self.cancelled:
                raise InterruptedError()
            x1, y1 = min(x + tile, w), min(y + tile, h)
            px0, py0 = max(0, x - PREPAD), max(0, y - PREPAD)
            px1, py1 = min(w, x1 + PREPAD), min(h, y1 + PREPAD)
            piece = np.ascontiguousarray(planar[:, py0:py1, px0:px1])
            ex = net.create_extractor()
            ex.input("data", self.ncnn.Mat(piece))
            ret, result = ex.extract("output")
            if ret != 0:
                raise RuntimeError("The graphics card stopped while enlarging.")
            result = np.array(result)  # 3 x H x W floats, about 0 to 1
            ox, oy = (x - px0) * SCALE, (y - py0) * SCALE
            block = result[:, oy:oy + (y1 - y) * SCALE, ox:ox + (x1 - x) * SCALE]
            out[y * SCALE:y1 * SCALE, x * SCALE:x1 * SCALE] = np.clip(block.transpose(1, 2, 0) * 255 + 0.5, 0, 255)
            _say({"id": job, "progress": (n + 1) / len(steps)})
        return out


def main(models_dir: str) -> None:
    lock = threading.Lock()
    engine: Engine | None = None
    try:
        engine = Engine(Path(models_dir))
        _say({"op": "ready", "gpus": engine.gpus, "gpu": engine.gpu})
    except Exception as error:  # report why, then keep answering so the app can fall back
        _say({"op": "ready", "error": str(error)})

    work: list[dict] = []
    wake = threading.Condition(lock)

    def worker():
        while True:
            with wake:
                while not work:
                    wake.wait()
                request = work.pop(0)
            job = request["id"]
            try:
                image = np.load(request["input"])
                result = engine.upscale(job, request["model"], image)
                np.save(request["output"], result)
                _say({"id": job, "done": True})
            except InterruptedError:
                _say({"id": job, "cancelled": True})
            except Exception as error:
                _say({"id": job, "error": str(error)})
            finally:
                engine.cancelled.discard(job)

    if engine is not None:
        threading.Thread(target=worker, daemon=True).start()

    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        op = request.get("op")
        if op == "info":
            _say({"op": "info", "gpus": engine.gpus if engine else [], "gpu": engine.gpu if engine else None})
        elif op == "cancel" and engine is not None:
            engine.cancelled.add(request["id"])
        elif op == "upscale":
            if engine is None:
                _say({"id": request.get("id"), "error": "The AI engine could not start."})
                continue
            with wake:
                work.append(request)
                wake.notify()
        elif op == "quit":
            break
    if engine is not None:
        engine.nets.clear()
        engine.ncnn.destroy_gpu_instance()  # a clean shutdown; skipping it can crash on exit


if __name__ == "__main__":
    main(sys.argv[1])

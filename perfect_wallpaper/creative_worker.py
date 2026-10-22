"""Runs inside the stronger AI add-on's own Python (see creative.py), not the app's.

    python creative_worker.py <models folder> <in.npy> <out.npy> <strength 0 to 1>

Repaints the picture in overlapping 768 pixel squares with Stable Diffusion 1.5 and
ControlNet "tile", which keeps each square's shapes and colors while adding fine detail.

It works on a copy enlarged twice more and shrinks the result back at the end. Stable
Diffusion draws in 8 pixel blocks, so detail only 2 to 4 pixels across would be smoothed
away at the picture's own size; in testing, the doubled copy kept the fine texture and
sharpened real detail, where the picture's own size turned fire into blotches.
The squares are blended with soft edges so no seams show. Prints "progress <0 to 1>".
"""

import sys

import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionControlNetImg2ImgPipeline, UniPCMultistepScheduler
from PIL import Image

TILE, OVERLAP = 768, 160
SUPERSAMPLE = 2
PROMPT = "highly detailed, sharp focus, crisp fine texture, high quality"
NEGATIVE = "blurry, soft, smooth, lowres, jpeg artifacts, noise, watermark, text, deformed"


def positions(length: int) -> list[int]:
    if length <= TILE:
        return [0]
    step = TILE - OVERLAP
    return list(range(0, length - TILE, step)) + [length - TILE]


def feather(w: int, h: int) -> np.ndarray:
    """Weights that fall off toward a square's edges, so overlapping squares blend."""
    ramp = lambda n: np.minimum(1.0, np.minimum(np.arange(n) + 1, np.arange(n)[::-1] + 1) / (OVERLAP / 2))  # noqa: E731
    return np.outer(ramp(h), ramp(w)).astype(np.float32)


def main(models: str, src: str, dst: str, strength: float) -> None:
    image = np.load(src)
    h, w = image.shape[:2]
    big = np.asarray(Image.fromarray(image).resize((w * SUPERSAMPLE, h * SUPERSAMPLE), Image.LANCZOS))
    bh, bw = big.shape[:2]
    if bh < TILE or bw < TILE:  # small pictures: pad to one square, crop back at the end
        big = np.pad(big, ((0, max(0, TILE - bh)), (0, max(0, TILE - bw)), (0, 0)), mode="reflect")
    ph, pw = big.shape[:2]

    controlnet = ControlNetModel.from_pretrained(f"{models}/tile", torch_dtype=torch.float16)
    pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
        f"{models}/base", controlnet=controlnet, torch_dtype=torch.float16, variant="fp16",
        safety_checker=None, feature_extractor=None, requires_safety_checker=False)
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.set_progress_bar_config(disable=True)
    pipe.to("cuda")

    denoise = 0.25 + 0.3 * strength  # how much of each square is repainted
    acc = np.zeros((ph, pw, 3), np.float32)
    weight = np.zeros((ph, pw, 1), np.float32)
    mask = feather(TILE, TILE)[..., None]
    squares = [(x, y) for y in positions(ph) for x in positions(pw)]
    generator = torch.Generator("cuda").manual_seed(7)
    print("progress 0.02", flush=True)
    for n, (x, y) in enumerate(squares):
        piece = Image.fromarray(big[y:y + TILE, x:x + TILE])
        out = pipe(prompt=PROMPT, negative_prompt=NEGATIVE, image=piece, control_image=piece, strength=denoise,
                   num_inference_steps=20, guidance_scale=6.0, controlnet_conditioning_scale=1.0,
                   generator=generator).images[0]
        acc[y:y + TILE, x:x + TILE] += np.asarray(out, np.float32) * mask
        weight[y:y + TILE, x:x + TILE] += mask
        print(f"progress {(n + 1) / len(squares):.3f}", flush=True)
    result = np.clip(acc / np.maximum(weight, 1e-6) + 0.5, 0, 255).astype(np.uint8)[:bh, :bw]
    np.save(dst, np.asarray(Image.fromarray(result).resize((w, h), Image.LANCZOS)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]))

"""Perceiver — screenshot analysis helpers (SSIM, color detection, freeze detection).

All threshold parameters have defaults matching config/default.yaml values,
but can be overridden by passing explicit values (from Config).
"""

import io
from typing import Optional, Union

import numpy as np
from PIL import Image


def image_from_base64(b64: str) -> Image.Image:
    """Convert base64 PNG string to PIL Image."""
    import base64
    raw = base64.b64decode(b64)
    return Image.open(io.BytesIO(raw))


def decode_to_array(b64: str) -> np.ndarray:
    """Decode base64 PNG to a numpy RGB array (uint8). Use this once per frame."""
    img = image_from_base64(b64)
    return np.array(img.convert("RGB"), dtype=np.uint8)


def _ensure_array(src: Union[str, np.ndarray]) -> np.ndarray:
    """Accept either a base64 string or a pre-decoded numpy array."""
    if isinstance(src, np.ndarray):
        return src
    return decode_to_array(src)


def compute_ssim(img1: Union[str, np.ndarray, Image.Image],
                 img2: Union[str, np.ndarray, Image.Image]) -> float:
    """Compute structural similarity between two images (0-1 scale).
    Accepts PIL Images, numpy arrays (RGB uint8), or base64 strings.
    """
    arr1 = _to_gray_f64(img1)
    arr2 = _to_gray_f64(img2)

    if arr1.shape != arr2.shape:
        from PIL import Image as PILImage
        tmp = PILImage.fromarray(arr2.astype(np.uint8), mode="L").resize(
            (arr1.shape[1], arr1.shape[0]))
        arr2 = np.array(tmp, dtype=np.float64)

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    mu1 = arr1.mean()
    mu2 = arr2.mean()
    sigma1_sq = arr1.var()
    sigma2_sq = arr2.var()
    sigma12 = ((arr1 - mu1) * (arr2 - mu2)).mean()

    ssim = ((2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)) / \
           ((mu1 ** 2 + mu2 ** 2 + C1) * (sigma1_sq + sigma2_sq + C2))
    return float(ssim)


def _to_gray_f64(src) -> np.ndarray:
    """Convert various inputs to grayscale float64 array."""
    if isinstance(src, np.ndarray):
        if src.ndim == 2:
            return src.astype(np.float64)
        return (0.2989 * src[:, :, 0] + 0.5870 * src[:, :, 1] + 0.1140 * src[:, :, 2]).astype(np.float64)
    if isinstance(src, Image.Image):
        return np.array(src.convert("L"), dtype=np.float64)
    return np.array(image_from_base64(src).convert("L"), dtype=np.float64)


def is_frozen(prev: Union[str, np.ndarray], curr: Union[str, np.ndarray],
              threshold: float = 0.995) -> bool:
    """Check if screen is frozen (nearly identical to previous frame).

    Args:
        prev: Previous frame (base64 or numpy array)
        curr: Current frame
        threshold: SSIM threshold above which frames are considered frozen.
            Default 0.995, configurable via detection.freeze.ssim_threshold
    """
    if prev is None or curr is None:
        return False
    return compute_ssim(prev, curr) > threshold


def get_dominant_color(src: Union[str, np.ndarray]) -> tuple[int, int, int]:
    """Get the dominant (average) color. Accepts base64 or numpy RGB array."""
    arr = _ensure_array(src)
    step = max(1, arr.shape[0] // 50)
    small = arr[::step, ::step]
    avg = small.mean(axis=(0, 1))
    return (int(avg[0]), int(avg[1]), int(avg[2]))


def is_blank_screen(src: Union[str, np.ndarray],
                    white_threshold: int = 240,
                    black_threshold: int = 15) -> Optional[str]:
    """Check if screen is blank (all white or all black).

    Args:
        src: Image source (base64 or numpy array)
        white_threshold: RGB values above this are considered white.
            Default 240, configurable via detection.blank_screen.white_threshold
        black_threshold: RGB values below this are considered black.
            Default 15, configurable via detection.blank_screen.black_threshold

    Returns:
        'white', 'black', or None.
    """
    r, g, b = get_dominant_color(src)
    if r > white_threshold and g > white_threshold and b > white_threshold:
        return "white"
    if r < black_threshold and g < black_threshold and b < black_threshold:
        return "black"
    return None


def match_region(frame: Union[str, np.ndarray], template: Union[str, np.ndarray, Image.Image],
                 region: dict) -> float:
    """SSIM between one region of ``frame`` and a stored template crop.

    ``region`` is ``{x, y, width, height}`` in frame pixels. This is the
    deterministic screen-recognition primitive: a static UI anchor (a button,
    a logo) compared against the same rectangle of the live frame. Returns
    0.0 when the region falls outside the frame.
    """
    arr = _ensure_array(frame)
    x, y = int(region["x"]), int(region["y"])
    w, h = int(region["width"]), int(region["height"])
    if x < 0 or y < 0 or y + h > arr.shape[0] or x + w > arr.shape[1]:
        return 0.0
    return compute_ssim(arr[y:y + h, x:x + w], template)


def pixel_diff_ratio(prev: Union[str, np.ndarray], curr: Union[str, np.ndarray],
                     threshold: int = 10) -> float:
    """Calculate the ratio of pixels that changed between two frames.

    Args:
        prev: Previous frame
        curr: Current frame
        threshold: Per-pixel RGB sum difference below which a pixel is considered unchanged.
            Default 10, configurable via adaptive_observe.pixel_diff_threshold
    """
    arr1 = _ensure_array(prev)
    arr2 = _ensure_array(curr)

    if arr1.shape != arr2.shape:
        from PIL import Image as PILImage
        tmp = PILImage.fromarray(arr2).resize((arr1.shape[1], arr1.shape[0]))
        arr2 = np.array(tmp, dtype=np.uint8)

    diff = np.abs(arr1.astype(np.int16) - arr2.astype(np.int16)).sum(axis=2)
    changed_pixels = (diff > threshold).sum()
    total_pixels = diff.shape[0] * diff.shape[1]
    return float(changed_pixels / total_pixels)

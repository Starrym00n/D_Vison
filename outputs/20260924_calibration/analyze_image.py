"""Measure the supplied JPEG offline; this does not emulate MaixPy firmware."""

import ast
import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PHOTO = ROOT / "pictures/20260924163412.jpeg"


def rgb_to_lab(rgb):
    """Convert sRGB to D65 CIELAB, retaining the floating-point LAB scale."""
    # 改编自: https://docs.opencv.org/4.x/de/d25/imgproc_color_conversions.html
    channels = rgb.astype(float) / 255
    linear = np.where(channels <= 0.04045, channels / 12.92,
                      ((channels + 0.055) / 1.055) ** 2.4)
    matrix = np.array([[.412453, .357580, .180423],
                       [.212671, .715160, .072169],
                       [.019334, .119193, .950227]])
    xyz = (linear @ matrix.T) / [.950456, 1, 1.088754]
    delta = 6 / 29
    transformed = np.where(xyz > delta ** 3, np.cbrt(xyz),
                           xyz / (3 * delta ** 2) + 4 / 29)
    x, y, z = transformed.transpose(2, 0, 1)
    return np.stack([116 * y - 16, 500 * (x - y), 200 * (y - z)], axis=2)


def blur_rgb(rgb):
    """Apply a separable 5-tap binomial approximation to the code's blur."""
    result = rgb.astype(float)
    weights = np.array([1, 4, 6, 4, 1]) / 16
    for axis in (0, 1):
        padding = [(0, 0)] * 3
        padding[axis] = (2, 2)
        padded = np.pad(result, padding, mode="reflect")
        pieces = [np.take(padded, range(i, i + result.shape[axis]), axis=axis)
                  for i in range(5)]
        result = sum(weight * piece for weight, piece in zip(weights, pieces))
    return np.rint(result)


def morphology(mask, dilate):
    """Apply one 3x3 binary operation using a neutral outside border."""
    padded = np.pad(mask, 1, constant_values=not dilate)
    windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3))
    return windows.any(axis=(-2, -1)) if dilate else windows.all(axis=(-2, -1))


def make_mask(lab, limits):
    """Threshold LAB and perform the configured close/open sequence."""
    low, high = np.array(limits)[[0, 2, 4]], np.array(limits)[[1, 3, 5]]
    mask = ((lab >= low) & (lab <= high)).all(axis=2)
    for dilate in (True, False, False, True):
        mask = morphology(mask, dilate)
    mask[132:] = False
    mask[:, :16] = False
    mask[:, 304:] = False
    return mask


def components(mask):
    """Measure 8-connected components without MaixPy's additional merging."""
    visited, records = np.zeros_like(mask), []
    height, width = mask.shape
    for y, x in zip(*np.where(mask)):
        if visited[y, x]:
            continue
        queue, points = deque([(int(y), int(x))]), []
        visited[y, x] = True
        while queue:
            py, px = queue.popleft()
            points.append((py, px))
            for ny in range(max(0, py - 1), min(height, py + 2)):
                for nx in range(max(0, px - 1), min(width, px + 2)):
                    if mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
        coords = np.array(points)
        top, left = coords.min(axis=0)
        bottom, right = coords.max(axis=0) + 1
        records.append(dict(x=int(left), y=int(top), w=int(right-left),
                            h=int(bottom-top), pixels=len(points),
                            cx=float(coords[:, 1].mean())))
    return sorted(records, key=lambda record: -record["pixels"])


def main():
    """Save reproducible sample statistics, geometry and approximate masks."""
    rgb = np.array(Image.open(PHOTO).convert("RGB"))
    lab, blurred_lab = rgb_to_lab(rgb), rgb_to_lab(blur_rgb(rgb))
    boxes = [("横线左内部", 30, 70, 140, 79),
             ("横线右内部", 210, 71, 290, 79),
             ("竖线上内部", 183, 7, 194, 19),
             ("竖线下内部", 183, 28, 194, 59),
             ("上方背景左", 30, 30, 160, 56),
             ("上方背景右", 215, 30, 290, 57),
             ("下方背景", 30, 91, 290, 102)]
    samples = []
    for label, x0, y0, x1, y1 in boxes:
        pixels = blurred_lab[y0:y1, x0:x1].reshape(-1, 3)
        samples.append(dict(label=label, box=[x0, y0, x1, y1], n=len(pixels),
                            minimum=pixels.min(axis=0).tolist(),
                            maximum=pixels.max(axis=0).tolist(),
                            p05=np.percentile(pixels, 5, axis=0).tolist(),
                            p95=np.percentile(pixels, 95, axis=0).tolist()))
    edges = []
    for x in list(range(25, 169)) + list(range(207, 296)):
        ys = np.flatnonzero(lab[66:82, x, 0] < 56) + 66
        edges.append([x, int(ys.min()), int(ys.max()), float((ys.min()+ys.max())/2)])
    slope, intercept = np.polyfit(np.array(edges)[:, 0], np.array(edges)[:, 3], 1)
    thresholds = {"current": [0, 56, -5, 14, -128, 12],
                  "candidate": [0, 56, -5, 10, -7, 10]}
    simulations = {}
    for name, limits in thresholds.items():
        mask = make_mask(blurred_lab, limits)
        cases = {}
        for gap in (3, 12):
            cropped = mask.copy()
            for x in range(16, 304):
                cropped[max(0, min(int(slope*x+intercept)-gap, 132)):132, x] = False
            cases[str(gap)] = components(cropped)[:4]
        simulations[name] = dict(h_pixels=int(mask[63:109, 16:304].sum()), gaps=cases)
    config = {}
    for node in ast.parse((ROOT / "code/main.py").read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                config[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    result = dict(size=[rgb.shape[1], rgb.shape[0]], samples=samples, edges=edges,
                  slope=float(slope), intercept=float(intercept), config=config,
                  simulations=simulations)
    (OUT / "measurements.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("edges", "config")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

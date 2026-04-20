import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from tqdm import tqdm

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Type aliases
# ─────────────────────────────────────────────────────────────────────────────
OcrResult = tuple[tuple[int, int, int, int], str]
OcrEngine  = Callable[[np.ndarray], list[OcrResult]]
BBox       = tuple[int, int, int, int]   # (x1, y1, x2, y2)


# ─────────────────────────────────────────────────────────────────────────────
# Theme palette
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ThemePalette:
    bg_fill_color:   tuple
    highlight_color: tuple
    text_bg_color:   tuple
    text_fg_color:   tuple
    ui_border_color: tuple   # BGR viền khung UI


PALETTE_LIGHT = ThemePalette(
    bg_fill_color   = (220, 220, 220),
    highlight_color = (0, 180, 80),
    text_bg_color   = (30,  30,  30),
    text_fg_color   = (220, 255, 200),
    ui_border_color = (50,  120, 220),
)

PALETTE_DARK = ThemePalette(
    bg_fill_color   = (35, 35, 35),
    highlight_color = (0, 220, 130),
    text_bg_color   = (15,  15,  15),
    text_fg_color   = (180, 255, 190),
    ui_border_color = (100, 180, 255),
)


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Config:
    # ── Frame sampling ───────────────────────────────────────────────────────
    target_fps: float = 1.0

    # ── Diff / SSIM ──────────────────────────────────────────────────────────
    ssim_threshold: float = 0.95
    diff_blur_ksize: int = 5
    diff_binarize_thresh: int = 25

    # ── Region extraction (diff mask weight only) ─────────────────────────────
    min_region_area: int = 2_000
    region_padding: int = 8
    merge_gap: int = 40

    # ── Blacklist zones (navbar / taskbar) ────────────────────────────────────
    blacklist_zones: list = field(default_factory=lambda: [
        (0.0, 0.0, 1.0, 0.04),
        (0.0, 0.96, 1.0, 1.0),
    ])

    # ── Theme ─────────────────────────────────────────────────────────────────
    theme_brightness_threshold: float = 118.0

    # ── Overlay ───────────────────────────────────────────────────────────────
    highlight_alpha: float = 0.28

    # ── UI Detection ──────────────────────────────────────────────────────────
    ui_detect_enabled: bool = True

    # [Step A] Inpaint OCR text
    ui_inpaint_radius: int = 5          # bán kính Telea inpaint
    ui_inpaint_padding: int = 2         # expand bbox trước khi mask (px)

    # [Step B] CLAHE + Sharpen
    ui_clahe_clip: float = 3.0
    ui_clahe_tile: int = 8              # tileGridSize = (tile, tile)
    ui_sharpen_strength: float = 1.0    # 0.0 = không sharpen, 1.0 = full

    # [Step C] Border map
    # Sobel
    ui_sobel_ksize: int = 3
    ui_sobel_weight: float = 0.6        # trọng số Sobel trong combine
    # Top-hat
    ui_tophat_ksize: int = 15           # kích thước struct element cho top-hat
    ui_tophat_weight: float = 0.4       # trọng số top-hat trong combine
    # Normalize + gamma
    ui_border_gamma: float = 0.7        # < 1 = boost vùng yếu, > 1 = suppress

    # [Step D] Canny + contours
    ui_canny_low:  int = 30
    ui_canny_high: int = 100

    # Morph (OPEN nhỏ giảm noise, CLOSE nhỏ nối cạnh đứt)
    ui_morph_open_ksize:  int = 2
    ui_morph_close_ksize: int = 3
    ui_morph_iterations:  int = 1

    # Filter
    ui_min_area: int         = 6_000
    ui_max_area_ratio: float = 0.85

    # Smart merge
    ui_iou_merge_thresh:    float = 0.3
    ui_align_gap:           int   = 15
    ui_align_overlap_ratio: float = 0.5

    # Split box quá to
    ui_split_area_ratio: float = 0.30
    ui_split_min_gap:    int   = 8

    # Vẽ viền
    ui_border_thickness:    int   = 2
    ui_border_alpha:        float = 0.65
    ui_border_corner_radius: int  = 6

    # ── OCR ──────────────────────────────────────────────────────────────────
    ocr_engine: Optional[str] = None
    ocr_use_gpu: bool = True
    easyocr_languages: tuple = ("en","vi")
    easyocr_confidence_threshold: float = 0.3

    # ── Output ───────────────────────────────────────────────────────────────
    save_mask: bool = False
    output_ext: str = ".jpg"
    debug: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Theme detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_theme(frame: np.ndarray, cfg: Config) -> str:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    thumb = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
    p25 = float(np.percentile(thumb.ravel().astype(np.float32), 25))
    return "dark" if p25 < cfg.theme_brightness_threshold else "light"


def get_palette(theme: str) -> ThemePalette:
    return PALETTE_DARK if theme == "dark" else PALETTE_LIGHT


# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────────────
def prepare_output_dirs(base: Path) -> dict[str, Path]:
    dirs = {
        "base":    base,
        "raw":     base / "raw_frames",
        "overlay": base / "overlay_frames",
        "masks":   base / "masks",
        "debug":   base / "debug",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


class DebugSaver:
    """Lưu ảnh debug từng bước nếu debug=True."""

    def __init__(self, base_dir: Path, frame_id: int, enabled: bool):
        self.enabled = enabled
        if enabled:
            self.dir = base_dir / f"frame_{frame_id:04d}"
            self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, img: np.ndarray) -> None:
        if not self.enabled or img is None:
            return
        path = self.dir / f"{name}.jpg"
        # Convert float → uint8 nếu cần
        if img.dtype != np.uint8:
            tmp = np.clip(img, 0, 255).astype(np.uint8)
        else:
            tmp = img
        # Grayscale → BGR để xem màu dễ hơn
        if tmp.ndim == 2:
            tmp = cv2.cvtColor(tmp, cv2.COLOR_GRAY2BGR)
        cv2.imwrite(str(path), tmp)


# ─────────────────────────────────────────────────────────────────────────────
# Frame sampling
# ─────────────────────────────────────────────────────────────────────────────
def sample_frames(video_path: str, target_fps: float):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")
    native_fps: float = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step: int = max(1, round(native_fps / target_fps))
    log.info("Video: %.2f fps | %d frames | step=%d", native_fps, total_frames, step)
    frame_idx = 0
    output_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            yield output_idx, frame_idx / native_fps, frame
            output_idx += 1
        frame_idx += 1
    cap.release()


# ─────────────────────────────────────────────────────────────────────────────
# Diff mask
# ─────────────────────────────────────────────────────────────────────────────
def compute_diff_mask(
    prev_gray: np.ndarray,
    curr_gray: np.ndarray,
    cfg: Config,
) -> tuple[np.ndarray, float]:
    tw = min(curr_gray.shape[1], 320)
    th = int(curr_gray.shape[0] * tw / curr_gray.shape[1])
    score, _ = ssim(
        cv2.resize(prev_gray, (tw, th)),
        cv2.resize(curr_gray, (tw, th)),
        full=True,
    )
    if score >= cfg.ssim_threshold:
        return np.zeros(curr_gray.shape, dtype=np.uint8), score
    diff = cv2.absdiff(prev_gray, curr_gray)
    blurred = cv2.GaussianBlur(diff, (cfg.diff_blur_ksize, cfg.diff_blur_ksize), 0)
    _, mask = cv2.threshold(blurred, cfg.diff_binarize_thresh, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask, score


# ─────────────────────────────────────────────────────────────────────────────
# Shared bbox helpers
# ─────────────────────────────────────────────────────────────────────────────
def _filter_blacklist(boxes: list[BBox], shape, cfg: Config) -> list[BBox]:
    h, w = shape[:2]
    keep = []
    for (x1, y1, x2, y2) in boxes:
        blocked = any(
            x1 >= int(zx1r * w) and y1 >= int(zy1r * h) and
            x2 <= int(zx2r * w) and y2 <= int(zy2r * h)
            for (zx1r, zy1r, zx2r, zy2r) in cfg.blacklist_zones
        )
        if not blocked:
            keep.append((x1, y1, x2, y2))
    return keep


def _merge_nearby_boxes_simple(boxes: list[BBox], gap: int) -> list[BBox]:
    """Merge đơn giản — dùng cho diff regions (giữ behaviour v4)."""
    merged = True
    while merged:
        merged = False
        out: list[BBox] = []
        used = [False] * len(boxes)
        for i, a in enumerate(boxes):
            if used[i]:
                continue
            ax1, ay1, ax2, ay2 = a
            for j, b in enumerate(boxes):
                if i == j or used[j]:
                    continue
                bx1, by1, bx2, by2 = b
                x_close = (ax1 - gap <= bx2) and (ax2 + gap >= bx1)
                y_close = (ay1 - gap <= by2) and (ay2 + gap >= by1)
                y_ov = max(0, min(ay2, by2) - max(ay1, by1))
                min_h = min(ay2 - ay1, by2 - by1)
                same_row = (y_ov >= 0.3 * min_h) if min_h > 0 else False
                if x_close and y_close and same_row:
                    ax1, ay1 = min(ax1, bx1), min(ay1, by1)
                    ax2, ay2 = max(ax2, bx2), max(ay2, by2)
                    used[j] = True
                    merged = True
            out.append((ax1, ay1, ax2, ay2))
            used[i] = True
        boxes = out
    return boxes


def extract_regions(mask: np.ndarray, cfg: Config) -> list[BBox]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for cnt in contours:
        if cv2.contourArea(cnt) < cfg.min_region_area:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        boxes.append((x, y, x + bw, y + bh))
    if not boxes:
        return []
    boxes = _merge_nearby_boxes_simple(boxes, cfg.merge_gap)
    return _filter_blacklist(boxes, mask.shape, cfg)


# ─────────────────────────────────────────────────────────────────────────────
# UI Detection — v6 (OCR-aware)
# ─────────────────────────────────────────────────────────────────────────────

# ── Bbox helpers ─────────────────────────────────────────────────────────────

def _compute_iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    union = (ax2-ax1)*(ay2-ay1) + (bx2-bx1)*(by2-by1) - inter
    return inter / union if union > 0 else 0.0


def _same_row(a: BBox, b: BBox, overlap_ratio: float) -> bool:
    ov = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    min_h = min(a[3] - a[1], b[3] - b[1])
    return (ov / min_h >= overlap_ratio) if min_h > 0 else False


def _same_col(a: BBox, b: BBox, overlap_ratio: float) -> bool:
    ov = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    min_w = min(a[2] - a[0], b[2] - b[0])
    return (ov / min_w >= overlap_ratio) if min_w > 0 else False


def _box_distance_x(a: BBox, b: BBox) -> int:
    return max(0, max(a[0], b[0]) - min(a[2], b[2]))


def _box_distance_y(a: BBox, b: BBox) -> int:
    return max(0, max(a[1], b[1]) - min(a[3], b[3]))


def _should_merge_ui(a: BBox, b: BBox, cfg: Config) -> bool:
    if _compute_iou(a, b) >= cfg.ui_iou_merge_thresh:
        return True
    if _same_row(a, b, cfg.ui_align_overlap_ratio) and _box_distance_x(a, b) <= cfg.ui_align_gap:
        return True
    if _same_col(a, b, cfg.ui_align_overlap_ratio) and _box_distance_y(a, b) <= cfg.ui_align_gap:
        return True
    return False


def _smart_merge(boxes: list[BBox], cfg: Config) -> list[BBox]:
    changed = True
    while changed:
        changed = False
        out: list[BBox] = []
        used = [False] * len(boxes)
        for i, a in enumerate(boxes):
            if used[i]:
                continue
            ax1, ay1, ax2, ay2 = a
            for j in range(len(boxes)):
                if i == j or used[j]:
                    continue
                b = boxes[j]
                if _should_merge_ui((ax1, ay1, ax2, ay2), b, cfg):
                    ax1 = min(ax1, b[0]); ay1 = min(ay1, b[1])
                    ax2 = max(ax2, b[2]); ay2 = max(ay2, b[3])
                    used[j] = True
                    changed = True
            out.append((ax1, ay1, ax2, ay2))
            used[i] = True
        boxes = out
    return boxes


def _find_projection_cuts(proj: np.ndarray, min_gap: int) -> list[int]:
    if len(proj) == 0:
        return []
    threshold = proj.max() * 0.05
    in_gap, gap_start = False, 0
    cuts: list[int] = []
    for i, v in enumerate(proj):
        if v <= threshold:
            if not in_gap:
                in_gap, gap_start = True, i
        else:
            if in_gap:
                if (i - gap_start) >= min_gap:
                    cuts.append((gap_start + i) // 2)
                in_gap = False
    if in_gap and (len(proj) - gap_start) >= min_gap:
        cuts.append((gap_start + len(proj)) // 2)
    return cuts


def _split_large_box(box: BBox, gray: np.ndarray, cfg: Config, frame_area: int) -> list[BBox]:
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    if bw * bh <= cfg.ui_split_area_ratio * frame_area:
        return [box]

    roi = gray[y1:y2, x1:x2]
    if roi.size == 0:
        return [box]

    edges_roi = cv2.Canny(roi, cfg.ui_canny_low, cfg.ui_canny_high)

    # Horizontal cuts
    h_proj = cv2.GaussianBlur(
        edges_roi.sum(axis=1).astype(np.float32).reshape(-1, 1),
        (1, 15), 0,
    ).ravel()
    h_cuts = _find_projection_cuts(h_proj, cfg.ui_split_min_gap)
    if h_cuts:
        result, prev = [], 0
        for cy in h_cuts:
            if cy - prev > cfg.ui_split_min_gap:
                result.append((x1, y1 + prev, x2, y1 + cy))
            prev = cy
        if bh - prev > cfg.ui_split_min_gap:
            result.append((x1, y1 + prev, x2, y2))
        if len(result) > 1:
            return result

    # Vertical cuts
    v_proj = cv2.GaussianBlur(
        edges_roi.sum(axis=0).astype(np.float32).reshape(1, -1),
        (15, 1), 0,
    ).ravel()
    v_cuts = _find_projection_cuts(v_proj, cfg.ui_split_min_gap)
    if v_cuts:
        result, prev = [], 0
        for cx in v_cuts:
            if cx - prev > cfg.ui_split_min_gap:
                result.append((x1 + prev, y1, x1 + cx, y2))
            prev = cx
        if bw - prev > cfg.ui_split_min_gap:
            result.append((x1 + prev, y1, x2, y2))
        if len(result) > 1:
            return result

    return [box]


# ── Step A: Inpaint OCR text ─────────────────────────────────────────────────

def inpaint_ocr_text(
    frame: np.ndarray,
    ocr_results: list[OcrResult],
    cfg: Config,
) -> np.ndarray:
    """
    Xóa vùng text OCR khỏi frame bằng cv2.inpaint (Telea).

    Tại sao:
      Các ký tự có cạnh sắc → Canny bắt edge của chữ thay vì edge UI border.
      Sau khi inpaint, vùng text được fill bằng màu nền xung quanh,
      các border detect sau đó chỉ thấy cạnh của khung UI thật sự.
    """
    if not ocr_results:
        return frame

    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    pad = cfg.ui_inpaint_padding

    for (x1, y1, x2, y2), _ in ocr_results:
        # Expand bbox một chút để cover hết pixel text viền
        mx1 = max(0, x1 - pad)
        my1 = max(0, y1 - pad)
        mx2 = min(w - 1, x2 + pad)
        my2 = min(h - 1, y2 + pad)
        mask[my1:my2, mx1:mx2] = 255

    if mask.sum() == 0:
        return frame

    # Telea inpaint — fill tự nhiên theo vùng lân cận
    result = cv2.inpaint(frame, mask, cfg.ui_inpaint_radius, cv2.INPAINT_TELEA)
    return result


# ── Step B: CLAHE + Sharpen ───────────────────────────────────────────────────

def enhance_local(gray: np.ndarray, cfg: Config) -> np.ndarray:
    """
    CLAHE tăng contrast cục bộ + sharpen nhẹ.

    CLAHE (Contrast Limited Adaptive Histogram Equalization):
      - Chia ảnh thành tiles (cfg.ui_clahe_tile × cfg.ui_clahe_tile)
      - Equalize histogram riêng từng tile → border mờ trên nền đồng nhất
        (ví dụ: card trắng trên nền trắng) sẽ nổi rõ hơn
      - clipLimit giới hạn khuếch đại để tránh noise bùng phát

    Sharpen kernel 3×3 laplacian:
      [[0, -1, 0], [-1, 5, -1], [0, -1, 0]]
      Trọng số strength: blend giữa ảnh gốc và ảnh sau sharpen.
    """
    # CLAHE
    clahe = cv2.createCLAHE(
        clipLimit=cfg.ui_clahe_clip,
        tileGridSize=(cfg.ui_clahe_tile, cfg.ui_clahe_tile),
    )
    enhanced = clahe.apply(gray)

    # Sharpen (blend)
    if cfg.ui_sharpen_strength > 0:
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
        sharpened = cv2.filter2D(enhanced, -1, kernel)
        s = np.clip(cfg.ui_sharpen_strength, 0.0, 1.0)
        enhanced = cv2.addWeighted(
            enhanced, 1.0 - s,
            sharpened, s,
            0,
        )

    return enhanced


# ── Step C: Border map ────────────────────────────────────────────────────────

def _sobel_magnitude(gray: np.ndarray, ksize: int) -> np.ndarray:
    """Gradient magnitude (Sobel) → float32 [0..255]."""
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=ksize)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=ksize)
    mag = np.sqrt(gx**2 + gy**2)
    mag_norm = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX)
    return mag_norm.astype(np.float32)


def _tophat_magnitude(gray: np.ndarray, ksize: int) -> np.ndarray:
    """
    Top-hat = frame - morphological_open(frame).
    Bắt được:
      • White top-hat: cấu trúc sáng hơn nền (bright border, divider sáng)
      • Black top-hat: cấu trúc tối hơn nền (shadow border, card edge tối)
    Combine cả hai → toàn diện hơn Sobel trên flat UI.
    """
    se = cv2.getStructuringElement(
        cv2.MORPH_RECT, (ksize, ksize),
    )
    white_th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,    se).astype(np.float32)
    black_th = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT,  se).astype(np.float32)
    combined = white_th + black_th
    norm = cv2.normalize(combined, None, 0, 255, cv2.NORM_MINMAX)
    return norm.astype(np.float32)


def mark_border_map(gray: np.ndarray, cfg: Config) -> np.ndarray:
    """
    Tạo border-strength map = weighted sum của Sobel + Top-hat,
    sau đó áp gamma để boost vùng border yếu.

    Trả về ảnh uint8 [0..255] — border càng sáng = biên UI càng rõ.
    """
    sobel  = _sobel_magnitude(gray, cfg.ui_sobel_ksize)
    tophat = _tophat_magnitude(gray, cfg.ui_tophat_ksize)

    border_map = (
        cfg.ui_sobel_weight  * sobel +
        cfg.ui_tophat_weight * tophat
    )
    border_map = cv2.normalize(border_map, None, 0, 255, cv2.NORM_MINMAX)

    # Gamma correction: boost biên yếu (gamma < 1) hoặc suppress noise (gamma > 1)
    if abs(cfg.ui_border_gamma - 1.0) > 1e-3:
        lut = np.array(
            [np.clip(255 * (i / 255.0) ** cfg.ui_border_gamma, 0, 255) for i in range(256)],
            dtype=np.uint8,
        )
        border_u8 = np.clip(border_map, 0, 255).astype(np.uint8)
        border_map_gamma = cv2.LUT(border_u8, lut).astype(np.float32)
    else:
        border_map_gamma = border_map

    return np.clip(border_map_gamma, 0, 255).astype(np.uint8)


# ── Step D: Detect from border map ───────────────────────────────────────────

def _detect_contours_from_border(
    border_map: np.ndarray,
    cfg: Config,
) -> list[BBox]:
    """
    Canny → morph OPEN + CLOSE → RETR_TREE → filter area.
    Giống v5 nhưng input là border_map thay vì Canny trực tiếp từ gray.
    """
    # Canny trên border map (đã normalize)
    edges = cv2.Canny(border_map, cfg.ui_canny_low, cfg.ui_canny_high)

    # Otsu trên border map → bắt thêm flat border mà Canny miss
    _, otsu    = cv2.threshold(border_map, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    otsu_edges = cv2.Canny(otsu, 50, 150)

    combined = cv2.bitwise_or(edges, otsu_edges)

    # Morph
    k_open  = cv2.getStructuringElement(
        cv2.MORPH_RECT, (cfg.ui_morph_open_ksize, cfg.ui_morph_open_ksize))
    k_close = cv2.getStructuringElement(
        cv2.MORPH_RECT, (cfg.ui_morph_close_ksize, cfg.ui_morph_close_ksize))
    opened  = cv2.morphologyEx(combined, cv2.MORPH_OPEN,  k_open,  iterations=cfg.ui_morph_iterations)
    closed  = cv2.morphologyEx(opened,   cv2.MORPH_CLOSE, k_close, iterations=cfg.ui_morph_iterations)

    # Contours (RETR_TREE → detect nested UI)
    contours, _ = cv2.findContours(closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    h, w = border_map.shape[:2]
    frame_area = h * w
    max_area = cfg.ui_max_area_ratio * frame_area

    raw_boxes: list[BBox] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < cfg.ui_min_area or area > max_area:
            continue
        bx, by, bw, bh = cv2.boundingRect(cnt)
        if bw < 4 or bh < 4:
            continue
        raw_boxes.append((bx, by, bx + bw, by + bh))

    return raw_boxes, closed   # trả thêm closed để debug


# ── Public entry point ────────────────────────────────────────────────────────

def detect_ui_regions(
    raw_frame: np.ndarray,
    cfg: Config,
    ocr_results: Optional[list[OcrResult]] = None,
    debug: Optional[DebugSaver] = None,
) -> list[BBox]:
    """
    Phát hiện khung UI từ raw_frame, có hỗ trợ OCR-aware inpainting.

    Flow:
      [A] inpaint_ocr_text()     — xóa chữ OCR → border không bị nhiễu text
      [B] enhance_local()        — CLAHE + sharpen → tăng contrast cục bộ
      [C] mark_border_map()      — Sobel + Top-hat → border-strength map
      [D] detect_contours_from_border() → raw boxes
      [E] smart_merge()          — IoU + alignment merge
      [F] split_large_box()      — tách box quá to
      [G] filter_blacklist()     — loại navbar/taskbar

    Args:
        raw_frame:   BGR frame gốc
        cfg:         Config object
        ocr_results: kết quả OCR từ frame trước (hoặc None)
        debug:       DebugSaver để lưu ảnh từng bước (None = tắt)
    """
    if not cfg.ui_detect_enabled:
        return []

    h, w = raw_frame.shape[:2]
    frame_area = h * w

    if debug:
        debug.save("00_raw", raw_frame)

    # ── [A] Inpaint OCR text ─────────────────────────────────────────────────
    inpainted = inpaint_ocr_text(raw_frame, ocr_results or [], cfg)
    if debug:
        debug.save("01_inpainted", inpainted)

    # ── [B] CLAHE + Sharpen ──────────────────────────────────────────────────
    gray = cv2.cvtColor(inpainted, cv2.COLOR_BGR2GRAY)
    enhanced = enhance_local(gray, cfg)
    if debug:
        debug.save("02_enhanced", enhanced)

    # ── [C] Border map ───────────────────────────────────────────────────────
    border_map = mark_border_map(enhanced, cfg)
    if debug:
        debug.save("03_border_map", border_map)

    # ── [D] Detect contours ──────────────────────────────────────────────────
    raw_boxes, closed_mask = _detect_contours_from_border(border_map, cfg)
    if debug:
        debug.save("04_closed_mask", closed_mask)

    if not raw_boxes:
        return []

    # ── [E] Smart merge ──────────────────────────────────────────────────────
    merged = _smart_merge(raw_boxes, cfg)

    # ── [F] Split large boxes ─────────────────────────────────────────────────
    gray_orig = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2GRAY)
    split: list[BBox] = []
    for box in merged:
        split.extend(_split_large_box(box, gray_orig, cfg, frame_area))

    # ── [G] Blacklist filter ─────────────────────────────────────────────────
    final = _filter_blacklist(split, raw_frame.shape, cfg)

    if debug:
        # Vẽ tất cả box lên raw frame để xem kết quả
        viz = raw_frame.copy()
        for (x1, y1, x2, y2) in final:
            cv2.rectangle(viz, (x1, y1), (x2, y2), (0, 200, 80), 2)
        debug.save("05_result", viz)

    log.debug(
        "UI detect: raw=%d → merged=%d → split=%d → final=%d",
        len(raw_boxes), len(merged), len(split), len(final),
    )
    print(final)
    return final


# ─────────────────────────────────────────────────────────────────────────────
# Draw UI borders
# ─────────────────────────────────────────────────────────────────────────────
def draw_ui_borders(
    overlay: np.ndarray,
    ui_regions: list[BBox],
    palette: ThemePalette,
    cfg: Config,
) -> np.ndarray:
    if not ui_regions:
        return overlay

    out = overlay.copy()
    draw_layer = np.zeros_like(out, dtype=np.uint8)

    for (x1, y1, x2, y2) in ui_regions:
        _draw_rounded_rect(
            draw_layer, x1, y1, x2, y2,
            cfg.ui_border_corner_radius,
            palette.ui_border_color,
            cfg.ui_border_thickness,
        )

    mask_draw = (draw_layer.sum(axis=2) > 0).astype(np.float32)[:, :, np.newaxis]
    blended = (
        out.astype(np.float32) * (1.0 - cfg.ui_border_alpha * mask_draw)
        + draw_layer.astype(np.float32) * (cfg.ui_border_alpha * mask_draw)
    )
    return np.clip(blended, 0, 255).astype(np.uint8)


def _draw_rounded_rect(
    img: np.ndarray,
    x1: int, y1: int, x2: int, y2: int,
    radius: int, color: tuple, thickness: int,
) -> None:
    h_img, w_img = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w_img - 1, x2), min(h_img - 1, y2)
    bw, bh  = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return
    r = min(radius, bw // 2, bh // 2)

    cv2.line(img, (x1 + r, y1), (x2 - r, y1), color, thickness)
    cv2.line(img, (x1 + r, y2), (x2 - r, y2), color, thickness)
    cv2.line(img, (x1, y1 + r), (x1, y2 - r), color, thickness)
    cv2.line(img, (x2, y1 + r), (x2, y2 - r), color, thickness)
    cv2.ellipse(img, (x1 + r, y1 + r), (r, r), 180,  0, 90, color, thickness)
    cv2.ellipse(img, (x2 - r, y1 + r), (r, r), 270,  0, 90, color, thickness)
    cv2.ellipse(img, (x1 + r, y2 - r), (r, r),  90,  0, 90, color, thickness)
    cv2.ellipse(img, (x2 - r, y2 - r), (r, r),   0,  0, 90, color, thickness)


# ─────────────────────────────────────────────────────────────────────────────
# OCR engines (không đổi so với v5)
# ─────────────────────────────────────────────────────────────────────────────
def build_ocr_engine(cfg: Config) -> Optional[OcrEngine]:
    engine = cfg.ocr_engine

    if engine == "paddle":
        try:
            import paddleocr as _paddleocr
            from paddleocr import PaddleOCR
            try:
                _ver = tuple(int(x) for x in _paddleocr.__version__.split(".")[:2])
            except Exception:
                _ver = (2, 7)

            if _ver >= (2, 8):
                _device = "gpu" if cfg.ocr_use_gpu else "cpu"
                ocr = PaddleOCR(use_textline_orientation=True, lang="en", device=_device)
                log.info("OCR: PaddleOCR %s (3.x, device=%s)", _paddleocr.__version__, _device)

                def _paddle_new(img: np.ndarray) -> list[OcrResult]:
                    if img is None or img.size == 0:
                        return []
                    if img.ndim == 2:
                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    elif img.ndim == 3 and img.shape[2] == 1:
                        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
                    try:
                        result = ocr.predict(img)
                    except Exception as e:
                        log.debug("PaddleOCR predict() failed: %s", e)
                        return []
                    if not result:
                        return []
                    items: list[OcrResult] = []
                    for res_obj in result:
                        if res_obj is None:
                            continue
                        rec_texts = _paddle_get_attr(res_obj, "rec_texts")
                        dt_polys  = _paddle_get_attr(res_obj, "dt_polys")
                        if not rec_texts:
                            continue
                        for idx, text in enumerate(rec_texts):
                            text = str(text).strip()
                            if text:
                                items.append((_poly_to_xyxy(dt_polys, idx), text))
                    return items
                return _paddle_new

            else:
                ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False,
                                use_gpu=cfg.ocr_use_gpu)
                log.info("OCR: PaddleOCR %s (2.x, GPU=%s)", _paddleocr.__version__, cfg.ocr_use_gpu)

                def _paddle_legacy(img: np.ndarray) -> list[OcrResult]:
                    if img is None or img.size == 0:
                        return []
                    result = ocr.ocr(img, cls=True)
                    if not result or not result[0]:
                        return []
                    items: list[OcrResult] = []
                    for line in result[0]:
                        try:
                            poly = np.array(line[0], dtype=np.float32)
                            text = str(line[1][0]).strip()
                            if text:
                                items.append((_poly_to_xyxy_array(poly), text))
                        except (IndexError, TypeError):
                            pass
                    return items
                return _paddle_legacy

        except ImportError:
            log.warning("PaddleOCR not installed. pip install paddleocr[all]")

    elif engine == "easyocr":
        try:
            import easyocr as _easyocr
            langs = list(cfg.easyocr_languages)
            reader = _easyocr.Reader(langs, gpu=cfg.ocr_use_gpu)
            conf_thresh = cfg.easyocr_confidence_threshold
            log.info("OCR: EasyOCR %s  langs=%s  gpu=%s  conf=%.2f",
                     getattr(_easyocr, "__version__", "?"), langs,
                     cfg.ocr_use_gpu, conf_thresh)

            def _easyocr_fn(img: np.ndarray) -> list[OcrResult]:
                if img is None or img.size == 0:
                    return []
                try:
                    result = reader.readtext(img)
                except Exception as e:
                    log.debug("EasyOCR failed: %s", e)
                    return []
                items: list[OcrResult] = []
                for item in (result or []):
                    try:
                        poly, text, conf = item[0], item[1], item[2]
                        text = str(text).strip()
                        if text and float(conf) >= conf_thresh:
                            items.append((_poly_to_xyxy_array(
                                np.array(poly, dtype=np.float32)), text))
                    except (IndexError, TypeError, ValueError):
                        pass
                return items
            return _easyocr_fn

        except ImportError:
            log.warning("EasyOCR not installed. pip install easyocr")

    elif engine == "tesseract":
        try:
            import pytesseract
            from pytesseract import Output
            log.info("OCR: Tesseract (full-frame)")

            def _tesseract(img: np.ndarray) -> list[OcrResult]:
                if img is None or img.size == 0:
                    return []
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
                _, thresh = cv2.threshold(gray, 0, 255,
                                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                try:
                    data = pytesseract.image_to_data(thresh, output_type=Output.DICT)
                except Exception as e:
                    log.debug("Tesseract failed: %s", e)
                    return []
                items: list[OcrResult] = []
                for i in range(len(data["text"])):
                    text = str(data["text"][i]).strip()
                    if not text or int(data["conf"][i]) < 0:
                        continue
                    x, y   = int(data["left"][i]), int(data["top"][i])
                    ww, hh = int(data["width"][i]), int(data["height"][i])
                    items.append(((x, y, x + ww, y + hh), text))
                return items
            return _tesseract

        except ImportError:
            log.warning("pytesseract not installed. pip install pytesseract")

    elif engine is not None:
        log.warning("Unknown OCR engine '%s'. Choices: paddle, easyocr, tesseract", engine)

    return None


def _paddle_get_attr(obj, attr: str):
    if hasattr(obj, attr):
        val = getattr(obj, attr)
        if val is not None:
            return val
    if hasattr(obj, "__getitem__"):
        try:
            return obj[attr]
        except (KeyError, TypeError, IndexError):
            pass
    if hasattr(obj, "res") and isinstance(obj.res, dict):
        return obj.res.get(attr)
    return None


def _poly_to_xyxy(polys, idx: int) -> BBox:
    if polys is None:
        return (0, 0, 0, 0)
    try:
        return _poly_to_xyxy_array(np.array(polys[idx], dtype=np.float32))
    except (IndexError, TypeError, ValueError):
        return (0, 0, 0, 0)


def _poly_to_xyxy_array(poly: np.ndarray) -> BBox:
    if poly is None or poly.size == 0:
        return (0, 0, 0, 0)
    poly = poly.reshape(-1, 2)
    return (int(poly[:, 0].min()), int(poly[:, 1].min()),
            int(poly[:, 0].max()), int(poly[:, 1].max()))


# ─────────────────────────────────────────────────────────────────────────────
# Compose overlay
# ─────────────────────────────────────────────────────────────────────────────
def compose_overlay_frame(
    frame: np.ndarray,
    mask: np.ndarray,
    palette: ThemePalette,
) -> np.ndarray:
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask_dilated  = cv2.dilate(mask, dilate_kernel, iterations=1)
    weight        = cv2.GaussianBlur(mask_dilated.astype(np.float32) / 255.0, (21, 21), 0)
    weight_3ch    = weight[:, :, np.newaxis]
    fill_f        = np.full(frame.shape,
                            np.array(palette.bg_fill_color, dtype=np.float32),
                            dtype=np.float32)
    blended = fill_f * (1.0 - weight_3ch) + frame.astype(np.float32) * weight_3ch
    return np.clip(blended, 0, 255).astype(np.uint8)


def draw_ocr_labels(
    overlay: np.ndarray,
    ocr_results: list[OcrResult],
    palette: ThemePalette,
) -> np.ndarray:
    out = overlay.copy()
    for (bbox, text) in ocr_results:
        if text:
            _draw_text_block(out, text, bbox[0], bbox[1], palette)
    return out


def _draw_text_block(img, text, x, y, palette):
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = 0.45, 1
    line_height_px, max_chars = 16, 80
    h_img = img.shape[0]

    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if len(test) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    if not lines:
        return

    pad = 4
    block_h = len(lines) * line_height_px + 2 * pad
    max_w   = max(cv2.getTextSize(ln, font, scale, thickness)[0][0] for ln in lines)
    block_w = max_w + 2 * pad
    ty0 = y - block_h - 2
    if ty0 < 0:
        ty0 = y + 2
    tx1 = min(x + block_w, img.shape[1])
    ty1 = min(ty0 + block_h, h_img)

    cv2.rectangle(img, (x, max(0, ty0)), (tx1, ty1), palette.text_bg_color, -1)
    for i, line in enumerate(lines):
        ly = ty0 + pad + (i + 1) * line_height_px - 2
        if 0 <= ly < h_img:
            cv2.putText(img, line, (x + pad, ly), font, scale,
                        palette.text_fg_color, thickness, cv2.LINE_AA)


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline — v6
# ─────────────────────────────────────────────────────────────────────────────
def run_pipeline(video_path: str, output_dir: str, cfg: Config) -> None:
    dirs   = prepare_output_dirs(Path(output_dir))
    ocr_fn = build_ocr_engine(cfg)

    log.info("Starting pipeline v6  →  output: %s", output_dir)
    log.info("OCR: %s | UI detect: %s | Debug: %s",
             cfg.ocr_engine or "disabled",
             "enabled" if cfg.ui_detect_enabled else "disabled",
             "enabled" if cfg.debug else "disabled")

    metadata: list[dict] = []
    prev_gray: Optional[np.ndarray] = None

    # OCR results từ frame trước → dùng để inpaint frame hiện tại
    # (Lý do: frame n và n+1 thường có text ở vị trí giống nhau;
    #  dùng OCR của frame n để inpaint frame n+1 trước khi detect UI)
    prev_ocr_results: list[OcrResult] = []

    cap_tmp    = cv2.VideoCapture(video_path)
    native_fps = cap_tmp.get(cv2.CAP_PROP_FPS) or 30.0
    total      = int(cap_tmp.get(cv2.CAP_PROP_FRAME_COUNT))
    cap_tmp.release()
    approx_total = total // max(1, round(native_fps / cfg.target_fps))

    stats = dict(no_change=0, overlay_saved=0, ocr_run=0,
                 ui_total=0, dark_frames=0, light_frames=0)

    for frame_id, ts, frame in tqdm(
        sample_frames(video_path, cfg.target_fps),
        total=approx_total, desc="Processing", unit="frame",
    ):
        curr_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        theme     = detect_theme(frame, cfg)
        palette   = get_palette(theme)
        stats[f"{theme}_frames"] += 1

        raw_path = dirs["raw"] / f"frame_{frame_id:04d}{cfg.output_ext}"
        cv2.imwrite(str(raw_path), frame)

        # Debug saver cho frame này
        dbg = DebugSaver(dirs["debug"], frame_id, cfg.debug)

        # ── Frame đầu tiên ────────────────────────────────────────────────
        if prev_gray is None:
            prev_gray = curr_gray
            out_path  = dirs["overlay"] / f"frame_{frame_id:04d}{cfg.output_ext}"

            # OCR trước để lấy text locations
            ocr_results: list[OcrResult] = []
            if ocr_fn is not None:
                stats["ocr_run"] += 1
                try:
                    ocr_results = ocr_fn(frame)
                except Exception as exc:
                    log.warning("OCR failed frame %d: %s", frame_id, exc)

            # detect UI với OCR results của chính frame này
            ui_regions = detect_ui_regions(frame, cfg, ocr_results, dbg)
            stats["ui_total"] += len(ui_regions)
            prev_ocr_results = ocr_results

            viz = draw_ui_borders(frame, ui_regions, palette, cfg)
            viz = draw_ocr_labels(viz, ocr_results, palette)
            cv2.imwrite(str(out_path), viz)
            stats["overlay_saved"] += 1
            metadata.append(dict(
                frame_id=frame_id, timestamp=round(ts, 3),
                ssim_score=1.0, changed=False, theme=theme, first_frame=True,
                ui_regions=[list(b) for b in ui_regions],
                regions=[{"bbox": list(b), "text": t} for b, t in ocr_results],
                raw_path=str(raw_path.relative_to(dirs["base"])),
                image_path=str(out_path.relative_to(dirs["base"])),
            ))
            continue

        # ── Diff mask ──────────────────────────────────────────────────────
        mask, ssim_score = compute_diff_mask(prev_gray, curr_gray, cfg)
        prev_gray = curr_gray

        if cfg.save_mask:
            cv2.imwrite(str(dirs["masks"] / f"frame_{frame_id:04d}_mask.jpg"), mask)

        # ── No-change ─────────────────────────────────────────────────────
        if ssim_score >= cfg.ssim_threshold:
            stats["no_change"] += 1
            fill     = np.full_like(frame, np.array(palette.bg_fill_color, dtype=np.uint8))
            out_path = dirs["overlay"] / f"frame_{frame_id:04d}{cfg.output_ext}"
            cv2.imwrite(str(out_path), fill)
            metadata.append(dict(
                frame_id=frame_id, timestamp=round(ts, 3),
                ssim_score=round(float(ssim_score), 4),
                changed=False, theme=theme,
                ui_regions=[], regions=[],
                raw_path=str(raw_path.relative_to(dirs["base"])),
                image_path=str(out_path.relative_to(dirs["base"])),
            ))
            continue

        # ─────────────────────────────────────────────────────────────────
        # PIPELINE CHÍNH
        # ─────────────────────────────────────────────────────────────────

        # Step 1: overlay từ diff mask
        overlay = compose_overlay_frame(frame, mask, palette)

        # Step 2: detect UI — dùng OCR từ frame trước để inpaint text
        #   (frame hiện tại chưa có OCR, nhưng text thường không thay đổi
        #    vị trí đột ngột giữa các frame liền kề)
        ui_regions = detect_ui_regions(frame, cfg, prev_ocr_results, dbg)
        stats["ui_total"] += len(ui_regions)

        # Step 3: vẽ viền UI
        if ui_regions:
            overlay = draw_ui_borders(overlay, ui_regions, palette, cfg)

        # Step 4: OCR frame hiện tại
        ocr_results = []
        if ocr_fn is not None:
            stats["ocr_run"] += 1
            try:
                ocr_results = ocr_fn(overlay)
            except Exception as exc:
                log.warning("OCR failed frame %d: %s", frame_id, exc)
        prev_ocr_results = ocr_results  # cập nhật cho frame tiếp theo

        # Step 5: vẽ OCR label
        if ocr_results:
            overlay = draw_ocr_labels(overlay, ocr_results, palette)

        # Step 6: lưu
        out_path = dirs["overlay"] / f"frame_{frame_id:04d}{cfg.output_ext}"
        cv2.imwrite(str(out_path), overlay)
        stats["overlay_saved"] += 1

        metadata.append(dict(
            frame_id=frame_id, timestamp=round(ts, 3),
            ssim_score=round(float(ssim_score), 4),
            changed=True, theme=theme,
            ui_regions=[list(b) for b in ui_regions],
            regions=[{"bbox": list(b), "text": t} for b, t in ocr_results],
            raw_path=str(raw_path.relative_to(dirs["base"])),
            image_path=str(out_path.relative_to(dirs["base"])),
        ))

    # ── Metadata ───────────────────────────────────────────────────────────
    meta_path = dirs["base"] / "metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    log.info("Done. overlay=%d no_change=%d ocr=%d ui_total=%d dark=%d light=%d",
             stats["overlay_saved"], stats["no_change"], stats["ocr_run"],
             stats["ui_total"], stats["dark_frames"], stats["light_frames"])
    log.info("Metadata → %s", meta_path)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Screen-recording → Overlay Frame Pipeline v6",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("video",                   help="Path to input video")
    p.add_argument("--out",                   default="output")
    p.add_argument("--fps",                   type=float, default=1.0)
    p.add_argument("--ssim",                  type=float, default=0.95)
    p.add_argument("--min-area",              type=int,   default=2000)
    p.add_argument("--highlight-alpha",       type=float, default=0.28)
    p.add_argument("--theme-threshold",       type=float, default=118.0)

    p.add_argument("--ocr", choices=["paddle", "easyocr", "tesseract"], default=None)
    p.add_argument("--no-gpu",               action="store_true")
    p.add_argument("--easyocr-lang",         nargs="+", default=["en"])
    p.add_argument("--easyocr-confidence",   type=float, default=0.3)

    ui = p.add_argument_group("UI Detection")
    ui.add_argument("--no-ui-detect",           action="store_true")
    ui.add_argument("--ui-inpaint-radius",       type=int,   default=5,
                    help="Bán kính Telea inpaint cho vùng OCR text")
    ui.add_argument("--ui-inpaint-padding",      type=int,   default=2,
                    help="Expand OCR bbox (px) trước khi tạo inpaint mask")
    ui.add_argument("--ui-clahe-clip",           type=float, default=3.0,
                    help="CLAHE clipLimit — càng cao = contrast cục bộ càng mạnh")
    ui.add_argument("--ui-clahe-tile",           type=int,   default=8,
                    help="CLAHE tileGridSize (N×N)")
    ui.add_argument("--ui-sharpen",              type=float, default=1.0,
                    help="Sharpen strength [0..1]")
    ui.add_argument("--ui-sobel-ksize",          type=int,   default=3,
                    help="Kernel size Sobel gradient")
    ui.add_argument("--ui-sobel-weight",         type=float, default=0.6,
                    help="Trọng số Sobel trong border map")
    ui.add_argument("--ui-tophat-ksize",         type=int,   default=15,
                    help="Kernel size Top-hat struct element")
    ui.add_argument("--ui-tophat-weight",        type=float, default=0.4,
                    help="Trọng số Top-hat trong border map")
    ui.add_argument("--ui-border-gamma",         type=float, default=0.7,
                    help="Gamma trên border map (<1 boost weak edges)")
    ui.add_argument("--ui-canny-low",            type=int,   default=30)
    ui.add_argument("--ui-canny-high",           type=int,   default=100)
    ui.add_argument("--ui-morph-open-ksize",     type=int,   default=2)
    ui.add_argument("--ui-morph-close-ksize",    type=int,   default=3)
    ui.add_argument("--ui-morph-iter",           type=int,   default=1)
    ui.add_argument("--ui-min-area",             type=int,   default=6000)
    ui.add_argument("--ui-max-area-ratio",       type=float, default=0.85)
    ui.add_argument("--ui-iou-merge",            type=float, default=0.3)
    ui.add_argument("--ui-align-gap",            type=int,   default=15)
    ui.add_argument("--ui-align-overlap",        type=float, default=0.5)
    ui.add_argument("--ui-split-ratio",          type=float, default=0.30)
    ui.add_argument("--ui-split-min-gap",        type=int,   default=8)
    ui.add_argument("--ui-border-thickness",     type=int,   default=2)
    ui.add_argument("--ui-border-alpha",         type=float, default=0.65)
    ui.add_argument("--ui-border-radius",        type=int,   default=6)

    p.add_argument("--save-mask",            action="store_true")
    p.add_argument("--png",                  action="store_true")
    p.add_argument("--debug",                action="store_true",
                   help="Lưu ảnh debug từng bước vào <out>/debug/frame_XXXX/")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg  = Config()

    cfg.target_fps                   = args.fps
    cfg.ssim_threshold               = args.ssim
    cfg.min_region_area              = args.min_area
    cfg.highlight_alpha              = args.highlight_alpha
    cfg.theme_brightness_threshold   = args.theme_threshold

    cfg.ocr_engine                   = args.ocr
    cfg.ocr_use_gpu                  = not args.no_gpu
    cfg.easyocr_languages            = tuple(args.easyocr_lang)
    cfg.easyocr_confidence_threshold = args.easyocr_confidence

    cfg.ui_detect_enabled            = not args.no_ui_detect
    cfg.ui_inpaint_radius            = args.ui_inpaint_radius
    cfg.ui_inpaint_padding           = args.ui_inpaint_padding
    cfg.ui_clahe_clip                = args.ui_clahe_clip
    cfg.ui_clahe_tile                = args.ui_clahe_tile
    cfg.ui_sharpen_strength          = args.ui_sharpen
    cfg.ui_sobel_ksize               = args.ui_sobel_ksize
    cfg.ui_sobel_weight              = args.ui_sobel_weight
    cfg.ui_tophat_ksize              = args.ui_tophat_ksize
    cfg.ui_tophat_weight             = args.ui_tophat_weight
    cfg.ui_border_gamma              = args.ui_border_gamma
    cfg.ui_canny_low                 = args.ui_canny_low
    cfg.ui_canny_high                = args.ui_canny_high
    cfg.ui_morph_open_ksize          = args.ui_morph_open_ksize
    cfg.ui_morph_close_ksize         = args.ui_morph_close_ksize
    cfg.ui_morph_iterations          = args.ui_morph_iter
    cfg.ui_min_area                  = args.ui_min_area
    cfg.ui_max_area_ratio            = args.ui_max_area_ratio
    cfg.ui_iou_merge_thresh          = args.ui_iou_merge
    cfg.ui_align_gap                 = args.ui_align_gap
    cfg.ui_align_overlap_ratio       = args.ui_align_overlap
    cfg.ui_split_area_ratio          = args.ui_split_ratio
    cfg.ui_split_min_gap             = args.ui_split_min_gap
    cfg.ui_border_thickness          = args.ui_border_thickness
    cfg.ui_border_alpha              = args.ui_border_alpha
    cfg.ui_border_corner_radius      = args.ui_border_radius
    cfg.save_mask                    = args.save_mask
    cfg.output_ext                   = ".png" if args.png else ".jpg"
    cfg.debug                        = args.debug

    if not os.path.isfile(args.video):
        log.error("Video file not found: %s", args.video)
        sys.exit(1)

    run_pipeline(args.video, args.out, cfg)

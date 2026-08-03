"""Contoh pemanggilan font_style_rs dari pipeline Python (OCR crops).

Build sekali:
    cd font_style_rs && maturin develop --release     # dev
    # atau: maturin build --release -i python3 && pip install target/wheels/*.whl
"""
import cv2
import font_style_rs

gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)        # np.ndarray (H, W) uint8
style = font_style_rs.analyze(gray)                      # -> {"is_italic": bool, "is_bold": bool}
# style = font_style_rs.analyze(gray, italic_threshold_deg=10.0, bold_stroke_ratio=0.15, bold_ink_density=0.40)
use_bold, use_italic = style["is_bold"], style["is_italic"]  # pilih font typesetter-mu

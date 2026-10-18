import sys
import os
import math
import ctypes
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QRectF, QSize
)
from PyQt6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QBrush, QFont,
    QPixmap, QImage, QCursor, QLinearGradient, QAction
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSystemTrayIcon, QMenu, QStyle,
    QMessageBox
)

from PIL import Image, ImageDraw, ImageFilter, ImageChops
import fitz  # PyMuPDF
from pdf2docx import Converter

# Win32 Key Codes
user32 = ctypes.windll.user32
VK_LBUTTON = 0x01
VK_SHIFT = 0x10
VK_TAB = 0x09

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".avif"}
PDF_EXTENSIONS = {".pdf"}


def is_key_down(vk_code: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk_code) & 0x8000)


def format_file_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    except Exception:
        return ""


def pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    rgba = pil_img.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimg = QImage(
        data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
    )
    return QPixmap.fromImage(qimg.copy())


def unique_output_path(base_dir: str, stem: str, suffix: str, ext: str) -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    candidate = os.path.join(base_dir, f"{stem}{suffix}{ext}")
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(base_dir, f"{stem}{suffix} ({counter}){ext}")
        counter += 1
    return candidate


# =====================================================================
# 1. INTERACTIVE CROP MODAL WINDOW (Matches 00:06 - 00:10 in video)
# =====================================================================
class CropCanvas(QWidget):
    def __init__(self, pil_img: Image.Image, parent_dialog):
        super().__init__()
        self.pil_img = pil_img
        self.parent_dialog = parent_dialog
        self.qpixmap = pil_to_qpixmap(pil_img)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        # Normalized crop rect [0.0 .. 1.0]
        self.crop_norm = [0.05, 0.05, 0.95, 0.95]  # [x1, y1, x2, y2]
        self.aspect_ratio = None  # None = Free, or float (width / height)
        self.drag_mode = None
        self.last_mouse_pos = QPointF()
        self.handle_radius = 8

    def get_image_display_rect(self) -> QRectF:
        w, h = self.width() - 40, self.height() - 40
        img_w, img_h = self.pil_img.width, self.pil_img.height
        scale = min(w / img_w, h / img_h)
        disp_w, disp_h = img_w * scale, img_h * scale
        x = (self.width() - disp_w) / 2
        y = (self.height() - disp_h) / 2
        return QRectF(x, y, disp_w, disp_h)

    def get_crop_screen_rect(self) -> QRectF:
        ir = self.get_image_display_rect()
        x1 = ir.left() + self.crop_norm[0] * ir.width()
        y1 = ir.top() + self.crop_norm[1] * ir.height()
        x2 = ir.left() + self.crop_norm[2] * ir.width()
        y2 = ir.top() + self.crop_norm[3] * ir.height()
        return QRectF(x1, y1, x2 - x1, y2 - y1)

    def get_crop_pixel_size(self) -> tuple[int, int]:
        w = max(1, int(round((self.crop_norm[2] - self.crop_norm[0]) * self.pil_img.width)))
        h = max(1, int(round((self.crop_norm[3] - self.crop_norm[1]) * self.pil_img.height)))
        return w, h

    def set_aspect_ratio(self, ratio: float | None):
        self.aspect_ratio = ratio
        if ratio is not None:
            cx = (self.crop_norm[0] + self.crop_norm[2]) / 2
            cy = (self.crop_norm[1] + self.crop_norm[3]) / 2
            img_w, img_h = self.pil_img.width, self.pil_img.height
            # Desired pixel width / height = ratio => (nw * img_w) / (nh * img_h) = ratio
            nw = 0.8
            nh = (nw * img_w) / (ratio * img_h)
            if nh > 0.8:
                nh = 0.8
                nw = (nh * ratio * img_h) / img_w
            self.crop_norm = [
                max(0.0, cx - nw / 2),
                max(0.0, cy - nh / 2),
                min(1.0, cx + nw / 2),
                min(1.0, cy + nh / 2),
            ]
        self.parent_dialog.update_dimensions_label()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        ir = self.get_image_display_rect()
        painter.drawPixmap(ir.toRect(), self.qpixmap)

        cr = self.get_crop_screen_rect()

        # Dim outside crop area
        overlay_path = QPainterPath()
        overlay_path.addRect(ir)
        crop_path = QPainterPath()
        crop_path.addRect(cr)
        dim_path = overlay_path.subtracted(crop_path)
        painter.fillPath(dim_path, QColor(0, 0, 0, 145))

        # Rule of thirds grid lines
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.PenStyle.DashLine))
        for i in (1, 2):
            gx = cr.left() + (cr.width() * i / 3)
            gy = cr.top() + (cr.height() * i / 3)
            painter.drawLine(QPointF(gx, cr.top()), QPointF(gx, cr.bottom()))
            painter.drawLine(QPointF(cr.left(), gy), QPointF(cr.right(), gy))

        # Orange crop border & handles (matching video style)
        accent = QColor(238, 86, 34)
        painter.setPen(QPen(accent, 2))
        painter.drawRect(cr)

        painter.setBrush(QBrush(accent))
        painter.setPen(QPen(Qt.GlobalColor.white, 1.5))
        for pt in self._handle_points(cr).values():
            painter.drawEllipse(pt, 6, 6)

    def _handle_points(self, cr: QRectF) -> dict[str, QPointF]:
        return {
            "tl": cr.topLeft(),
            "tr": cr.topRight(),
            "bl": cr.bottomLeft(),
            "br": cr.bottomRight(),
            "t": QPointF(cr.center().x(), cr.top()),
            "b": QPointF(cr.center().x(), cr.bottom()),
            "l": QPointF(cr.left(), cr.center().y()),
            "r": QPointF(cr.right(), cr.center().y()),
        }

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        cr = self.get_crop_screen_rect()
        for name, pt in self._handle_points(cr).items():
            if math.hypot(pos.x() - pt.x(), pos.y() - pt.y()) <= 12:
                self.drag_mode = name
                self.last_mouse_pos = pos
                return
        if cr.contains(pos):
            self.drag_mode = "move"
            self.last_mouse_pos = pos

    def mouseMoveEvent(self, event):
        pos = event.position()
        ir = self.get_image_display_rect()
        if not self.drag_mode:
            cr = self.get_crop_screen_rect()
            for name, pt in self._handle_points(cr).items():
                if math.hypot(pos.x() - pt.x(), pos.y() - pt.y()) <= 12:
                    self.setCursor(Qt.CursorShape.CrossCursor)
                    return
            if cr.contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        dx = (pos.x() - self.last_mouse_pos.x()) / max(1.0, ir.width())
        dy = (pos.y() - self.last_mouse_pos.y()) / max(1.0, ir.height())
        self.last_mouse_pos = pos

        x1, y1, x2, y2 = self.crop_norm
        min_span = 0.05

        if self.drag_mode == "move":
            w, h = x2 - x1, y2 - y1
            nx1 = min(max(0.0, x1 + dx), 1.0 - w)
            ny1 = min(max(0.0, y1 + dy), 1.0 - h)
            self.crop_norm = [nx1, ny1, nx1 + w, ny1 + h]
        else:
            if "l" in self.drag_mode:
                x1 = min(max(0.0, x1 + dx), x2 - min_span)
            if "r" in self.drag_mode:
                x2 = max(min(1.0, x2 + dx), x1 + min_span)
            if "t" in self.drag_mode:
                y1 = min(max(0.0, y1 + dy), y2 - min_span)
            if "b" in self.drag_mode:
                y2 = max(min(1.0, y2 + dy), y1 + min_span)

            if self.aspect_ratio is not None:
                img_w, img_h = self.pil_img.width, self.pil_img.height
                w_norm = x2 - x1
                desired_h_norm = (w_norm * img_w) / (self.aspect_ratio * img_h)
                if y1 + desired_h_norm <= 1.0:
                    y2 = y1 + desired_h_norm
                else:
                    y2 = 1.0
                    h_norm = y2 - y1
                    w_norm = (h_norm * self.aspect_ratio * img_h) / img_w
                    x2 = min(1.0, x1 + w_norm)

            self.crop_norm = [x1, y1, x2, y2]

        self.parent_dialog.update_dimensions_label()
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag_mode = None


class CropDialog(QDialog):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.pil_img = Image.open(file_path)
        self.setWindowTitle("Crop Image")
        self.setStyleSheet("""
            QDialog { background-color: #EBE4D8; }
            QLabel { color: #3D352E; font-family: 'Segoe UI'; font-size: 13px; }
            QPushButton {
                background-color: #DED6C8; border: none; border-radius: 6px;
                padding: 6px 12px; color: #3D352E; font-weight: 600;
            }
            QPushButton:hover { background-color: #D2C8B8; }
            QPushButton[active="true"] { background-color: #EE5622; color: white; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 18)

        title = QLabel("Crop Image")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self.canvas = CropCanvas(self.pil_img, self)
        layout.addWidget(self.canvas, stretch=1)

        # Aspect ratio row
        ratio_row = QHBoxLayout()
        ratio_row.addWidget(QLabel("Aspect ratio:"))
        self.ratio_buttons = []
        ratios = [
            ("Free", None),
            ("1:1", 1.0),
            ("16:9", 16 / 9),
            ("4:3", 4 / 3),
            ("3:2", 3 / 2),
            ("9:16", 9 / 16),
        ]
        for label, val in ratios:
            btn = QPushButton(label)
            btn.setProperty("active", "true" if label == "Free" else "false")
            btn.clicked.connect(lambda checked, b=btn, r=val: self._on_ratio_clicked(b, r))
            ratio_row.addWidget(btn)
            self.ratio_buttons.append(btn)
        ratio_row.addStretch()
        layout.addLayout(ratio_row)

        # Bottom controls row
        bottom_row = QHBoxLayout()
        self.w_label = QLabel("0")
        self.h_label = QLabel("0")
        for lbl in (self.w_label, self.h_label):
            lbl.setStyleSheet(
                "background: #F7F3EB; border: 1px solid #D5CBB8; border-radius: 5px; padding: 4px 10px; font-weight: 600;"
            )
        bottom_row.addWidget(self.w_label)
        bottom_row.addWidget(QLabel("×"))
        bottom_row.addWidget(self.h_label)
        bottom_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(
            "background-color: #EE5622; color: white; padding: 7px 18px; border-radius: 6px; font-weight: bold;"
        )
        apply_btn.clicked.connect(self.apply_crop)

        bottom_row.addWidget(cancel_btn)
        bottom_row.addWidget(apply_btn)
        layout.addLayout(bottom_row)

        self.update_dimensions_label()

    def _on_ratio_clicked(self, clicked_btn: QPushButton, ratio_val):
        for b in self.ratio_buttons:
            b.setProperty("active", "true" if b == clicked_btn else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.canvas.set_aspect_ratio(ratio_val)

    def update_dimensions_label(self):
        w, h = self.canvas.get_crop_pixel_size()
        self.w_label.setText(str(w))
        self.h_label.setText(str(h))

    def apply_crop(self):
        x1, y1, x2, y2 = self.canvas.crop_norm
        w, h = self.pil_img.width, self.pil_img.height
        box = (
            int(round(x1 * w)),
            int(round(y1 * h)),
            int(round(x2 * w)),
            int(round(y2 * h)),
        )
        cropped = self.pil_img.crop(box)
        p = Path(self.file_path)
        out_path = unique_output_path(str(p.parent), p.stem, " Cropped", p.suffix)
        if p.suffix.lower() in {".jpg", ".jpeg"} and cropped.mode in ("RGBA", "P"):
            cropped = cropped.convert("RGB")
        cropped.save(out_path)
        self.accept()


# =====================================================================
# 2. INTERACTIVE "ADD BG" STUDIO MODAL (Matches 00:14 - 00:18 in video)
# =====================================================================
BG_PRESETS = [
    ("#FF7E5F", "#FEB47B"),
    ("#FF6B6B", "#556270"),
    ("#C471F5", "#FA71CD"),
    ("#4FACFE", "#00F2FE"),
    ("#43E97B", "#38F9D7"),
    ("#FA709A", "#FEE140"),
    ("#667EEA", "#764BA2"),
    ("#F83600", "#F9D423"),
    ("#FFFFFF", "#FFFFFF"),
    ("#F5F5F7", "#E5E5EA"),
    ("#1C1C1E", "#2C2C2E"),
    ("#FF9A9E", "#FECFEF"),
    ("#A18CD1", "#FBC2EB"),
    ("#84FAB0", "#8FD3F4"),
]


class AddBgDialog(QDialog):
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.src_img = Image.open(file_path).convert("RGBA")

        # Create a scaled preview copy for responsive 60fps slider scrubbing
        max_prev = 700
        scale = min(1.0, max_prev / max(self.src_img.width, self.src_img.height))
        self.prev_scale = scale
        self.prev_img = self.src_img.resize(
            (max(1, int(self.src_img.width * scale)), max(1, int(self.src_img.height * scale))),
            Image.Resampling.LANCZOS,
        )

        self.bg_colors = BG_PRESETS[0]
        self.padding = 100
        self.corners = 28
        self.shadow = 65
        self.ratio = None  # None = Auto

        self.setWindowTitle("Add BG")
        self.setMinimumWidth(580)
        self.setStyleSheet("""
            QDialog { background-color: #EBE4D8; }
            QLabel { color: #3D352E; font-family: 'Segoe UI'; font-size: 12px; }
            QPushButton {
                background-color: #DED6C8; border: none; border-radius: 5px;
                padding: 5px 12px; color: #3D352E; font-weight: 600;
            }
            QPushButton[active="true"] { background-color: #EE5622; color: white; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 16)

        title = QLabel("Add BG")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(520, 360)
        layout.addWidget(self.preview_label, stretch=1)

        # Background presets
        swatch_row = QHBoxLayout()
        swatch_row.addWidget(QLabel("Background"))
        for c1, c2 in BG_PRESETS:
            btn = QPushButton()
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c1}, stop:1 {c2});
                    border: 2px solid #FFFFFF; border-radius: 6px;
                }}
                QPushButton:hover {{ border: 2px solid #EE5622; }}
            """)
            btn.clicked.connect(lambda checked, pair=(c1, c2): self._set_bg(pair))
            swatch_row.addWidget(btn)
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        # Sliders: Padding, Corners, Shadow
        self.pad_val_lbl = QLabel("100 px")
        layout.addLayout(self._make_slider_row("Padding", 0, 300, 100, self._on_pad_change, self.pad_val_lbl))

        self.corner_val_lbl = QLabel("28 px")
        layout.addLayout(self._make_slider_row("Corners", 0, 120, 28, self._on_corner_change, self.corner_val_lbl))

        self.shadow_val_lbl = QLabel("65%")
        layout.addLayout(self._make_slider_row("Shadow", 0, 100, 65, self._on_shadow_change, self.shadow_val_lbl))

        # Ratio row
        ratio_row = QHBoxLayout()
        ratio_row.addWidget(QLabel("Ratio"))
        self.ratio_btns = []
        for name, val in [("Auto", None), ("1:1", 1.0), ("16:9", 16 / 9), ("4:3", 4 / 3)]:
            b = QPushButton(name)
            b.setProperty("active", "true" if name == "Auto" else "false")
            b.clicked.connect(lambda checked, btn=b, r=val: self._set_ratio(btn, r))
            ratio_row.addWidget(b)
            self.ratio_btns.append(b)
        ratio_row.addStretch()
        layout.addLayout(ratio_row)

        # Action buttons
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save with Background")
        save_btn.setStyleSheet(
            "background-color: #EE5622; color: white; padding: 8px 18px; border-radius: 6px; font-weight: bold;"
        )
        save_btn.clicked.connect(self.save_output)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self.update_preview()

    def _make_slider_row(self, label_text, min_v, max_v, init_v, callback, val_label):
        row = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setFixedWidth(65)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(init_v)
        slider.valueChanged.connect(callback)
        val_label.setFixedWidth(55)
        val_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addWidget(slider, stretch=1)
        row.addWidget(val_label)
        return row

    def _set_bg(self, pair):
        self.bg_colors = pair
        self.update_preview()

    def _on_pad_change(self, val):
        self.padding = val
        self.pad_val_lbl.setText(f"{val} px")
        self.update_preview()

    def _on_corner_change(self, val):
        self.corners = val
        self.corner_val_lbl.setText(f"{val} px")
        self.update_preview()

    def _on_shadow_change(self, val):
        self.shadow = val
        self.shadow_val_lbl.setText(f"{val}%")
        self.update_preview()

    def _set_ratio(self, clicked_btn, ratio_val):
        for b in self.ratio_btns:
            b.setProperty("active", "true" if b == clicked_btn else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.ratio = ratio_val
        self.update_preview()

    def render_composed(self, img: Image.Image, scale_factor: float = 1.0) -> Image.Image:
        pad = int(self.padding * scale_factor)
        radius = int(self.corners * scale_factor)
        iw, ih = img.width, img.height

        canvas_w = iw + pad * 2
        canvas_h = ih + pad * 2

        if self.ratio is not None:
            current_r = canvas_w / max(1, canvas_h)
            if current_r < self.ratio:
                canvas_w = int(canvas_h * self.ratio)
            else:
                canvas_h = int(canvas_w / self.ratio)

        # Create diagonal linear gradient background via QImage -> PIL for smooth rendering
        qimg = QImage(canvas_w, canvas_h, QImage.Format.Format_RGBA8888)
        qp = QPainter(qimg)
        grad = QLinearGradient(0, 0, canvas_w, canvas_h)
        grad.setColorAt(0.0, QColor(self.bg_colors[0]))
        grad.setColorAt(1.0, QColor(self.bg_colors[1]))
        qp.fillRect(0, 0, canvas_w, canvas_h, QBrush(grad))
        qp.end()

        ptr = qimg.bits()
        ptr.setsize(canvas_w * canvas_h * 4)
        bg = Image.frombytes("RGBA", (canvas_w, canvas_h), bytes(ptr), "raw", "RGBA")

        # Apply rounded corners to foreground image
        mask = Image.new("L", (iw, ih), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, iw, ih), radius=radius, fill=255)

        fg = img.copy()
        orig_alpha = fg.split()[3]
        fg.putalpha(ImageChops.multiply(orig_alpha, mask))

        x = (canvas_w - iw) // 2
        y = (canvas_h - ih) // 2

        # Render soft Gaussian drop shadow
        if self.shadow > 0:
            blur_rad = max(2, int(28 * scale_factor * (self.shadow / 100.0)))
            shadow_alpha = int(175 * (self.shadow / 100.0))
            shadow_offset_y = int(12 * scale_factor * (self.shadow / 100.0))

            shadow_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            s_draw = ImageDraw.Draw(shadow_layer)
            s_draw.rounded_rectangle(
                (x, y + shadow_offset_y, x + iw, y + ih + shadow_offset_y),
                radius=radius,
                fill=(0, 0, 0, shadow_alpha),
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur_rad))
            bg = Image.alpha_composite(bg, shadow_layer)

        bg.alpha_composite(fg, (x, y))
        return bg

    def update_preview(self):
        composed = self.render_composed(self.prev_img, self.prev_scale)
        pix = pil_to_qpixmap(composed)
        scaled_pix = pix.scaled(
            self.preview_label.size() - QSize(20, 20),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled_pix)

    def save_output(self):
        final_img = self.render_composed(self.src_img, 1.0)
        p = Path(self.file_path)
        out_path = unique_output_path(str(p.parent), p.stem, " With Background", ".png")
        final_img.save(out_path, "PNG")
        self.accept()


# =====================================================================
# 3. RADIAL PIE MENU DROP TARGET (Matches 00:01 - 00:05 in video)
# =====================================================================
class RadialMenuWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)

        self.menu_size = 340
        self.setFixedSize(self.menu_size, self.menu_size)

        self.outer_radius = 152
        self.inner_radius = 52
        self.toggle_radius = 15

        self.current_file = None
        self.file_size_str = ""
        self.file_category = "image"  # "pdf" or "image"
        self.image_mode = "convert"   # "convert" or "tools"

        self.hovered_index = -1       # -1 = none, -2 = center, -3 = mode toggle, 0..N = outer wedge
        self.toggle_hover_ticks = 0

        # Track Global Drag + Shift State
        self.last_cursor_pos = QCursor.pos()
        self.drag_active_ticks = 0
        self.prev_tab_down = False

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_global_input)
        self.poll_timer.start(30)

    def get_slices(self) -> tuple[list[str], str]:
        """Returns (outer_slices, center_label) ordered counter-clockwise starting from top (90 deg)."""
        if self.file_category == "pdf":
            return ["DOCX", "TXT", "PNG", "JPG"], "RTF"
        else:
            if self.image_mode == "convert":
                return ["PNG", "DOCX", "PDF", "BMP", "AVIF", "GIF", "WEBP"], "TIFF"
            else:
                return [
                    "COMPRESS", "REDACT", "CROP", "ADD BG",
                    "ANNOTATE", "EDIT", "METADATA"
                ], self.file_size_str or "TOOLS"

    def poll_global_input(self):
        lbutton = is_key_down(VK_LBUTTON)
        shift = is_key_down(VK_SHIFT)
        tab_down = is_key_down(VK_TAB)
        pos = QCursor.pos()

        # Allow pressing Tab while dragging to toggle between Convert & Tools mode
        if self.isVisible() and tab_down and not self.prev_tab_down and self.file_category == "image":
            self.image_mode = "tools" if self.image_mode == "convert" else "convert"
            self.update()
        self.prev_tab_down = tab_down

        # Do not pop up if a modal editor is currently active
        if QApplication.activeModalWidget() is not None:
            if self.isVisible():
                self.hide()
            return

        if lbutton and shift:
            if not self.isVisible():
                dist = math.hypot(pos.x() - self.last_cursor_pos.x(), pos.y() - self.last_cursor_pos.y())
                if dist > 4:
                    self.drag_active_ticks += 1
                    if self.drag_active_ticks >= 2:
                        self.summon_at(pos)
        else:
            if not lbutton and self.isVisible():
                # Give dropEvent 80ms to fire before hiding
                QTimer.singleShot(80, self.hide)
            self.drag_active_ticks = 0

        self.last_cursor_pos = pos

    def summon_at(self, global_pos: QPoint):
        self.hovered_index = -1
        self.move(
            global_pos.x() - self.menu_size // 2,
            global_pos.y() - self.menu_size // 2,
        )
        self.show()
        self.raise_()

    # --- OLE Drag & Drop Events ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].isLocalFile():
                path = urls[0].toLocalFile()
                ext = Path(path).suffix.lower()
                if ext in PDF_EXTENSIONS or ext in IMAGE_EXTENSIONS:
                    self.current_file = path
                    self.file_size_str = format_file_size(path)
                    self.file_category = "pdf" if ext in PDF_EXTENSIONS else "image"
                    event.setDropAction(Qt.DropAction.CopyAction)
                    event.accept()
                    self.update()
                    return
        event.ignore()

    def dragMoveEvent(self, event):
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

        pos = event.position()
        cx, cy = self.menu_size / 2, self.menu_size / 2
        dx = pos.x() - cx
        dy = cy - pos.y()  # Cartesian Y (up is positive)
        r = math.hypot(dx, dy)

        # Check bottom mode-switch toggle button for images
        toggle_center = QPointF(cx, cy + self.inner_radius)
        if self.file_category == "image" and math.hypot(pos.x() - toggle_center.x(), pos.y() - toggle_center.y()) <= self.toggle_radius:
            self.hovered_index = -3
            self.toggle_hover_ticks += 1
            if self.toggle_hover_ticks == 8:  # ~120ms hover switches mode smoothly
                self.image_mode = "tools" if self.image_mode == "convert" else "convert"
            self.update()
            return
        else:
            self.toggle_hover_ticks = 0

        outer_slices, _ = self.get_slices()
        n = len(outer_slices)
        step = 360.0 / n

        if r < self.inner_radius:
            self.hovered_index = -2 if self.image_mode == "convert" or self.file_category == "pdf" else -1
        elif r <= self.outer_radius:
            angle = math.degrees(math.atan2(dy, dx)) % 360.0
            # Top wedge is centered at 90 degrees
            shifted = (angle - (90.0 - step / 2.0)) % 360.0
            self.hovered_index = int(shifted // step)
        else:
            self.hovered_index = -1

        self.update()

    def dragLeaveEvent(self, event):
        self.hovered_index = -1
        self.update()

    def dropEvent(self, event):
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

        selected_action = None
        outer_slices, center_label = self.get_slices()
        if self.hovered_index == -2:
            selected_action = center_label
        elif 0 <= self.hovered_index < len(outer_slices):
            selected_action = outer_slices[self.hovered_index]

        target_file = self.current_file
        self.hide()

        if target_file and selected_action:
            QTimer.singleShot(60, lambda: self.execute_action(target_file, selected_action))

    # --- Painting the Frosted Glass Radial Menu ---
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.menu_size / 2, self.menu_size / 2
        outer_rect = QRectF(
            cx - self.outer_radius, cy - self.outer_radius,
            self.outer_radius * 2, self.outer_radius * 2
        )
        inner_rect = QRectF(
            cx - self.inner_radius, cy - self.inner_radius,
            self.inner_radius * 2, self.inner_radius * 2
        )

        outer_slices, center_label = self.get_slices()
        n = len(outer_slices)
        step = 360.0 / n

        bg_normal = QColor(242, 226, 206, 225)
        bg_hover = QColor(238, 86, 34, 240)
        border_col = QColor(255, 255, 255, 160)
        text_normal = QColor(58, 46, 38)
        text_hover = QColor(255, 255, 255)

        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)

        # Draw Outer Wedges
        for i, label in enumerate(outer_slices):
            start_angle = (90.0 - step / 2.0) + i * step
            path = QPainterPath()
            path.arcMoveTo(outer_rect, start_angle)
            path.arcTo(outer_rect, start_angle, step)
            path.arcTo(inner_rect, start_angle + step, -step)
            path.closeSubpath()

            is_hov = (i == self.hovered_index)
            painter.fillPath(path, QBrush(bg_hover if is_hov else bg_normal))
            painter.setPen(QPen(border_col, 1.5))
            painter.drawPath(path)

            # Label positioning
            mid_angle_rad = math.radians(start_angle + step / 2.0)
            mid_r = (self.inner_radius + self.outer_radius) / 2.0
            tx = cx + mid_r * math.cos(mid_angle_rad)
            ty = cy - mid_r * math.sin(mid_angle_rad)

            painter.setPen(text_hover if is_hov else text_normal)
            text_rect = QRectF(tx - 45, ty - 14, 90, 28)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

        # Draw Center Circle
        center_hov = (self.hovered_index == -2)
        painter.setBrush(QBrush(bg_hover if center_hov else QColor(236, 218, 196, 235)))
        painter.setPen(QPen(border_col, 2))
        painter.drawEllipse(inner_rect)

        painter.setPen(text_hover if center_hov else text_normal)
        painter.drawText(inner_rect, Qt.AlignmentFlag.AlignCenter, center_label)

        # Draw Bottom Mode Toggle Button for Images (Convert <-> Tools)
        if self.file_category == "image":
            t_center = QPointF(cx, cy + self.inner_radius)
            t_hov = (self.hovered_index == -3)
            painter.setBrush(QBrush(bg_hover if t_hov else QColor(255, 250, 242, 245)))
            painter.setPen(QPen(QColor(180, 160, 140), 1.5))
            painter.drawEllipse(t_center, self.toggle_radius, self.toggle_radius)

            painter.setPen(text_hover if t_hov else text_normal)
            icon_char = "⚙" if self.image_mode == "convert" else "⇄"
            t_rect = QRectF(
                t_center.x() - self.toggle_radius,
                t_center.y() - self.toggle_radius,
                self.toggle_radius * 2,
                self.toggle_radius * 2,
            )
            painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, icon_char)

    # --- File Conversion & Tool Execution ---
    def execute_action(self, file_path: str, action: str):
        p = Path(file_path)
        base_dir = str(p.parent)
        stem = p.stem

        try:
            # 1. Interactive Modals
            if action in ("CROP", "EDIT", "REDACT", "ANNOTATE"):
                dlg = CropDialog(file_path)
                dlg.exec()
                return

            if action == "ADD BG":
                dlg = AddBgDialog(file_path)
                dlg.exec()
                return

            # 2. Image Tools
            if action == "COMPRESS":
                img = Image.open(file_path)
                out_ext = p.suffix.lower()
                out_path = unique_output_path(base_dir, stem, " Compressed", out_ext)
                if out_ext in {".jpg", ".jpeg"}:
                    img.convert("RGB").save(out_path, "JPEG", quality=60, optimize=True)
                elif out_ext == ".png":
                    img.quantize(colors=256).save(out_path, "PNG", optimize=True)
                else:
                    img.save(out_path, optimize=True, quality=65)
                return

            if action == "METADATA":
                img = Image.open(file_path)
                clean = Image.new(img.mode, img.size)
                clean.putdata(list(img.getdata()))
                out_path = unique_output_path(base_dir, stem, " Clean", p.suffix)
                clean.save(out_path)
                return

            # 3. PDF Conversions
            if self.file_category == "pdf":
                if action in ("JPG", "PNG"):
                    doc = fitz.open(file_path)
                    page = doc.load_page(0)
                    pix = page.get_pixmap(dpi=200)
                    ext = f".{action.lower()}"
                    out_path = unique_output_path(base_dir, stem, "", ext)
                    pix.save(out_path)
                    doc.close()
                elif action == "DOCX":
                    out_path = unique_output_path(base_dir, stem, "", ".docx")
                    cv = Converter(file_path)
                    cv.convert(out_path, start=0, end=None)
                    cv.close()
                elif action in ("TXT", "RTF"):
                    doc = fitz.open(file_path)
                    text = "\n".join(page.get_text() for page in doc)
                    doc.close()
                    ext = f".{action.lower()}"
                    out_path = unique_output_path(base_dir, stem, "", ext)
                    if action == "RTF":
                        escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\par\n")
                        text = f"{{\\rtf1\\ansi\\deff0 {{\\fonttbl {{\\f0 Segoe UI;}}}}\\f0\\fs22 {escaped}}}"
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(text)
                return

            # 4. Image Format Conversions
            if self.file_category == "image":
                img = Image.open(file_path)
                target_ext = f".{action.lower()}"
                out_path = unique_output_path(base_dir, stem, "", target_ext)

                if action == "PDF":
                    img.convert("RGB").save(out_path, "PDF", resolution=150.0)
                elif action == "DOCX":
                    # Embed image inside a single-page PDF then convert to DOCX
                    tmp_pdf = unique_output_path(base_dir, stem, "_tmp", ".pdf")
                    img.convert("RGB").save(tmp_pdf, "PDF", resolution=150.0)
                    cv = Converter(tmp_pdf)
                    cv.convert(out_path)
                    cv.close()
                    os.remove(tmp_pdf)
                elif action in ("JPG", "BMP"):
                    img.convert("RGB").save(out_path)
                else:
                    img.save(out_path)

        except Exception as e:
            QMessageBox.warning(None, "Conversion Error", f"Failed to run {action}:\n{e}")


# =====================================================================
# 4. APPLICATION ENTRY POINT & SYSTEM TRAY ICON
# =====================================================================
def main():
    # Ensure crisp High-DPI scaling on Windows 10/11
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    radial_window = RadialMenuWindow()

    # System Tray Icon so it runs quietly in the background
    tray = QSystemTrayIcon()
    tray.setIcon(app.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
    tray.setToolTip("Radial File Tool (Drag a file + Hold Shift)")

    menu = QMenu()
    info_action = QAction("Drag any PDF/Image + Hold Shift", menu)
    info_action.setEnabled(False)
    menu.addAction(info_action)
    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
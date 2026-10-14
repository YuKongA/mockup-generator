#!/usr/bin/env python3
"""
Web Project Mockup & Poster Generator (CLI)
Generates promotional mockups and marketing posters with color management.
"""

import argparse
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageCms


# ----------------------------------------------------------------------
# 1. Color Management & ICC Metadata
# ----------------------------------------------------------------------

def get_srgb_icc_bytes():
    """Generates standard sRGB IEC 61966-2.1 ICC profile bytes."""
    profile = ImageCms.createProfile("sRGB")
    return ImageCms.ImageCmsProfile(profile).tobytes()

def make_png_chunk(chunk_type: str, data: bytes) -> bytes:
    t_bytes = chunk_type.encode("ascii")
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(t_bytes + data) & 0xFFFFFFFF)
    return length + t_bytes + data + crc

def inject_srgb_png_metadata(png_bytes: bytes) -> bytes:
    """
    Injects sRGB, gAMA (2.2), and cHRM chunks into PNG right after IHDR.
    Combined with iCCP, this guarantees exact color reproduction on HDR/DCI-P3 displays.
    """
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG data"
    ihdr_len = int.from_bytes(png_bytes[8:12], "big")
    ihdr_end = 8 + 4 + 4 + ihdr_len + 4

    gama_chunk = make_png_chunk("gAMA", struct.pack(">I", 45455)) # 1 / 2.2
    chrm_chunk = make_png_chunk("cHRM", struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000))
    srgb_chunk = make_png_chunk("sRGB", b"\x00") # 0 = Perceptual

    return png_bytes[:ihdr_end] + srgb_chunk + gama_chunk + chrm_chunk + png_bytes[ihdr_end:]

def save_color_managed_png(pil_img: Image.Image, output_path: str):
    """Saves a PIL Image with full sRGB and ICC profile tags."""
    if pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")
    buf = io.BytesIO()
    icc_bytes = get_srgb_icc_bytes()
    pil_img.save(buf, format="PNG", icc_profile=icc_bytes, optimize=True)
    full_data = inject_srgb_png_metadata(buf.getvalue())
    with open(output_path, "wb") as f:
        f.write(full_data)


# ----------------------------------------------------------------------
# 2. Vector & Supersampled Geometry
# ----------------------------------------------------------------------

def create_smooth_mask(width: int, height: int, radius: int, scale: int = 4) -> Image.Image:
    """Generates an 8-bit anti-aliased rounded rectangle mask using supersampling."""
    sw, sh, sr = width * scale, height * scale, radius * scale
    big_mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(big_mask).rounded_rectangle([0, 0, sw - 1, sh - 1], radius=sr, fill=255)
    return big_mask.resize((width, height), Image.Resampling.LANCZOS)

def draw_wifi_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: int = 4, color=(28, 28, 30, 255)):
    """Draws an iOS-style Wi-Fi icon with 3 concentric arcs."""
    # Base dot
    dot_r = int(1.2 * scale)
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)

    stroke_w = int(2.0 * scale)
    arcs = [
        int(4.4 * scale),
        int(7.6 * scale),
        int(10.8 * scale),
    ]
    start_deg, end_deg = 225, 315
    for r in arcs:
        box = [cx - r, cy - r, cx + r, cy + r]
        draw.arc(box, start=start_deg, end=end_deg, fill=color, width=stroke_w)

        # Round caps at both ends
        cap_r = stroke_w / 2.0
        r_mid = r - stroke_w / 2.0
        for deg in (start_deg, end_deg):
            rad = math.radians(deg)
            x = cx + r_mid * math.cos(rad)
            y = cy + r_mid * math.sin(rad)
            draw.ellipse([x - cap_r, y - cap_r, x + cap_r, y + cap_r], fill=color)

def draw_lock_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: int = 1, color=(130, 140, 155, 255)):
    """Draws an HTTPS padlock icon."""
    body_w = int(10 * scale)
    body_h = int(8 * scale)
    shackle_r = int(4 * scale)

    bx1 = cx - body_w // 2
    by1 = cy - 1
    bx2 = cx + body_w // 2
    by2 = by1 + body_h
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=int(1.5 * scale), fill=color)

    # Keyhole
    draw.ellipse([cx - int(1 * scale), by1 + int(2.5 * scale), cx + int(1 * scale), by1 + int(4.5 * scale)], fill=(255, 255, 255, 255))

    # Shackle arch
    sx1, sy1 = cx - shackle_r, by1 - shackle_r * 2 + int(1.5 * scale)
    sx2, sy2 = cx + shackle_r, by1 + int(1.5 * scale)
    draw.arc([sx1, sy1, sx2, sy2], start=180, end=0, fill=color, width=int(1.5 * scale))

def add_shadow(img: Image.Image, blur_radius: int = 30, offset=(0, 20), opacity: float = 0.25):
    """Renders a soft multi-layer drop shadow for mockups."""
    w, h = img.size
    pad = blur_radius * 2
    sw, sh = w + pad * 2, h + pad * 2

    alpha = img.split()[-1]
    shadow_base = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))

    shadow_mask = Image.new("L", (sw, sh), 0)
    shadow_mask.paste(alpha, (pad + offset[0], pad + offset[1]))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(blur_radius))

    shadow_color = Image.new("RGBA", (sw, sh), (0, 0, 0, int(255 * opacity)))
    shadow_base.paste(shadow_color, (0, 0), shadow_mask)
    shadow_base.paste(img, (pad, pad), img)
    return shadow_base, pad

def get_system_font(bold: bool = False, size: int = 14) -> ImageFont.FreeTypeFont:
    """Finds standard sans-serif system fonts across Linux, macOS, and Windows."""
    candidates = []
    if bold:
        candidates = [
            # macOS Apple SF Pro
            "/System/Library/Fonts/SFProText-Bold.otf",
            "/System/Library/Fonts/SFProText-Semibold.otf",
            "/System/Library/Fonts/SFPro-Bold.otf",
            "/System/Library/Fonts/SFPro-Semibold.otf",
            "/Library/Fonts/SF-Pro-Text-Bold.otf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            # Linux
            "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
            "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
            "/usr/share/fonts/truetype/roboto/unhinted/Roboto-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            # Windows
            "C:\\Windows\\Fonts\\segoeuib.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ]
    else:
        candidates = [
            # macOS Apple SF Pro
            "/System/Library/Fonts/SFProText-Regular.otf",
            "/System/Library/Fonts/SFPro-Regular.otf",
            "/Library/Fonts/SF-Pro-Text-Regular.otf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            # Linux
            "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
            "/usr/share/fonts/truetype/inter/Inter-Regular.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Regular.ttf",
            "/usr/share/fonts/truetype/roboto/unhinted/Roboto-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            # Windows
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
        ]
    for c in candidates:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()
def get_status_bar_time_font(size: int = 60, weight: int = 480) -> ImageFont.FreeTypeFont:
    """Loads official MiSans VF font for mobile status bar clock, falling back to system fonts."""
    # 1. Bundled / local MiSans VF
    font_paths = [
        Path(__file__).parent / "fonts" / "MiSans_VF_Latin.ttf",
        Path("/usr/local/share/fonts/m/MiSansVF.ttf"),
        Path("/usr/local/share/fonts/MiSansVF.ttf"),
        Path("/usr/share/fonts/MiSansVF.ttf"),
    ]
    for p in font_paths:
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                if hasattr(f, "set_variation_by_axes"):
                    try:
                        f.set_variation_by_axes([weight])
                    except Exception:
                        pass
                return f
            except Exception:
                continue

    # 2. Query system fontconfig for MiSans VF
    try:
        res = subprocess.run(["fc-match", "-f", "%{file}", "MiSans VF"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and res.stdout.strip() and os.path.exists(res.stdout.strip()):
            f = ImageFont.truetype(res.stdout.strip(), size)
            if hasattr(f, "set_variation_by_axes"):
                try:
                    f.set_variation_by_axes([weight])
                except Exception:
                    pass
            return f
    except Exception:
        pass

    # 3. Fallback to general system font (bold)
    return get_system_font(bold=True, size=size)


# ----------------------------------------------------------------------
# 3. Mockup Components: Desktop & Mobile
# ----------------------------------------------------------------------

def make_browser_mockup(content_img: Image.Image, url_text: str = "example.com", scale: int = 4) -> Image.Image:
    """Wraps desktop screenshot in a macOS-style browser frame with traffic lights & address bar."""
    w, h = content_img.size
    bar_h = 56
    radius = 20

    bw, bh = w * scale, bar_h * scale
    big_bar = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big_bar)

    # Top bar background
    draw.rounded_rectangle([0, 0, bw - 1, bh * 2], radius=radius * scale, fill=(245, 246, 248, 255))
    draw.line([0, bh - 1, bw, bh - 1], fill=(225, 228, 233, 255), width=int(1 * scale))

    # Traffic light dots
    dot_y = bh // 2
    draw.ellipse([int(24 * scale), dot_y - int(7 * scale), int(38 * scale), dot_y + int(7 * scale)], fill="#FF5F56")
    draw.ellipse([int(46 * scale), dot_y - int(7 * scale), int(60 * scale), dot_y + int(7 * scale)], fill="#FFBD2E")
    draw.ellipse([int(68 * scale), dot_y - int(7 * scale), int(82 * scale), dot_y + int(7 * scale)], fill="#27C93F")

    # Address bar pill
    pill_w, pill_h = int(480 * scale), int(32 * scale)
    pill_x1 = (bw - pill_w) // 2
    pill_x2 = pill_x1 + pill_w
    pill_y1 = (bh - pill_h) // 2
    pill_y2 = pill_y1 + pill_h

    draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=int(9 * scale), fill="#FFFFFF", outline=(222, 226, 232, 255), width=int(1 * scale))

    # URL Text & Lock Icon
    url_font = get_system_font(bold=False, size=int(13 * scale))
    text_bbox = draw.textbbox((0, 0), url_text, font=url_font)
    tw, th = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]

    lock_size = int(12 * scale)
    lock_gap = int(7 * scale)
    total_w = lock_size + lock_gap + tw

    start_x = (bw - total_w) // 2
    draw_lock_icon(draw, start_x + lock_size // 2, bh // 2, scale=scale, color=(130, 140, 155, 255))
    draw.text((start_x + lock_size + lock_gap, (bh - th) // 2 - int(1 * scale)), url_text, font=url_font, fill=(65, 75, 90, 255))

    bar_down = big_bar.resize((w, bar_h), Image.Resampling.LANCZOS)

    # Assemble
    window = Image.new("RGBA", (w, h + bar_h), (255, 255, 255, 0))
    window.paste(bar_down, (0, 0), bar_down)
    window.paste(content_img, (0, bar_h))

    # Mask with smooth anti-aliased corners
    mask = create_smooth_mask(w, h + bar_h, radius, scale=scale)
    final_window = Image.new("RGBA", (w, h + bar_h), (0, 0, 0, 0))
    final_window.paste(window, (0, 0), mask)

    # Frame stroke
    stroke_img = Image.new("RGBA", (w, h + bar_h), (0, 0, 0, 0))
    ImageDraw.Draw(stroke_img).rounded_rectangle([0, 0, w - 1, h + bar_h - 1], radius=radius, outline=(220, 224, 230, 255), width=1)
    return Image.alpha_composite(final_window, stroke_img)

def draw_phone_status_bar(
    screen_img: Image.Image,
    scale: int = 4,
    bar_h: int = 54,
    time_text: str = "9:41",
    theme: str = "auto",
    time_weight: int = 480
) -> Image.Image:
    """Draws phone status bar with Dynamic Island, time, signal, Wi-Fi, and battery."""
    sw, sh = screen_img.size
    bw, bh = sw * scale, bar_h * scale
    bar = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bar)

    # Determine dark/light theme based on background luminance
    if theme == "light":
        is_dark = True
    elif theme == "dark":
        is_dark = False
    else:
        sample_pts = [
            (int(34), int(bar_h // 2)),
            (int(sw // 2), int(bar_h // 2)),
            (int(sw - 34), int(bar_h // 2)),
            (int(sw // 4), int(bar_h // 2)),
            (int(3 * sw // 4), int(bar_h // 2)),
        ]
        sample_rgbs = [screen_img.getpixel(pt)[:3] for pt in sample_pts if pt[0] < sw and pt[1] < sh]
        if sample_rgbs:
            avg_r = sum(c[0] for c in sample_rgbs) / len(sample_rgbs)
            avg_g = sum(c[1] for c in sample_rgbs) / len(sample_rgbs)
            avg_b = sum(c[2] for c in sample_rgbs) / len(sample_rgbs)
            luminance = 0.299 * avg_r + 0.587 * avg_g + 0.114 * avg_b
        else:
            luminance = 255.0
        is_dark = luminance < 130

    fg_color = (245, 245, 247, 255) if is_dark else (28, 28, 30, 255)
    fg_rgb = fg_color[:3]

    center_y = int(29 * scale)

    # 1. Dynamic Island
    di_w, di_h = int(126 * scale), int(36 * scale)
    di_x, di_y = (bw - di_w) // 2, int(11 * scale)
    di_r = di_h // 2

    if is_dark:
        # Subtle boundary outline on dark background
        draw.rounded_rectangle([di_x, di_y, di_x + di_w, di_y + di_h], radius=di_r, fill=(0, 0, 0, 255), outline=(65, 65, 72, 255), width=int(0.8 * scale))
    else:
        draw.rounded_rectangle([di_x, di_y, di_x + di_w, di_y + di_h], radius=di_r, fill=(0, 0, 0, 255))

    # Camera lens and reflection glint
    cam_cx = di_x + di_w - int(24 * scale)
    cam_cy = center_y
    cam_outer_r = int(5.5 * scale)
    cam_inner_r = int(3.8 * scale)
    draw.ellipse([cam_cx - cam_outer_r, cam_cy - cam_outer_r, cam_cx + cam_outer_r, cam_cy + cam_outer_r], fill=(18, 20, 26, 255))
    draw.ellipse([cam_cx - cam_inner_r, cam_cy - cam_inner_r, cam_cx + cam_inner_r, cam_cy + cam_inner_r], fill=(10, 13, 20, 255))
    # Optical anti-reflective coating specular highlight
    glint_x = cam_cx + int(1.4 * scale)
    glint_y = cam_cy - int(1.4 * scale)
    glint_r = int(1.1 * scale)
    draw.ellipse([glint_x - glint_r, glint_y - glint_r, glint_x + glint_r, glint_y + glint_r], fill=(60, 90, 140, 190))
    draw.ellipse([glint_x - int(0.5 * scale), glint_y - int(0.5 * scale), glint_x + int(0.5 * scale), glint_y + int(0.5 * scale)], fill=(190, 220, 255, 140))

    # Face ID sensor aperture
    sensor_cx = di_x + int(24 * scale)
    sensor_cy = center_y
    sensor_r = int(4.5 * scale)
    draw.ellipse([sensor_cx - sensor_r, sensor_cy - sensor_r, sensor_cx + sensor_r, sensor_cy + sensor_r], fill=(13, 13, 17, 255))

    # 2. Time text (vertically centered with Dynamic Island)
    time_font = get_status_bar_time_font(size=int(15.5 * scale), weight=time_weight)
    bbox = draw.textbbox((0, 0), time_text, font=time_font)
    time_y = int(round(center_y - (bbox[1] + bbox[3]) / 2.0))
    time_x = int(34 * scale)
    draw.text((time_x, time_y), time_text, font=time_font, fill=fg_color)

    # 3. Right icons (Battery, Wi-Fi, Cellular)
    # Battery
    bat_w = int(24.5 * scale)
    bat_h = int(12 * scale)
    bat_radius = int(3.8 * scale)
    bat_outline_w = int(1.1 * scale)
    bat_border_color = (*fg_rgb, 100)
    bat_fill_color = (*fg_rgb, 255)

    bat_x = bw - int(28 * scale) - bat_w
    bat_y = center_y - bat_h // 2

    # Battery frame
    draw.rounded_rectangle([bat_x, bat_y, bat_x + bat_w, bat_y + bat_h], radius=bat_radius, outline=bat_border_color, width=bat_outline_w)

    # Positive terminal
    term_w = int(1.6 * scale)
    term_h = int(4.5 * scale)
    term_x1 = bat_x + bat_w - int(0.5 * scale)
    term_x2 = bat_x + bat_w + term_w
    term_y1 = center_y - term_h // 2
    term_y2 = term_y1 + term_h
    draw.rounded_rectangle([term_x1, term_y1, term_x2, term_y2], radius=int(1.2 * scale), fill=bat_border_color)

    # Inner charge pill (82% level)
    inset = int(2.0 * scale)
    charge_max_w = bat_w - inset * 2
    charge_w = int(charge_max_w * 0.82)
    draw.rounded_rectangle([bat_x + inset, bat_y + inset, bat_x + inset + charge_w, bat_y + bat_h - inset], radius=int(1.8 * scale), fill=bat_fill_color)

    # Symmetrical spacing: Cellular <-> Wi-Fi <-> Battery
    icon_gap = int(6.0 * scale)
    wifi_right_ext = int(7.8 * scale)
    wifi_left_ext = int(8.0 * scale)

    # Wi-Fi icon
    wifi_cx = bat_x - icon_gap - wifi_right_ext
    wifi_cy = center_y + int(4.6 * scale)
    draw_wifi_icon(draw, wifi_cx, wifi_cy, scale=scale, color=fg_color)

    # Cellular signal bars
    wifi_left = wifi_cx - wifi_left_ext
    sig_bar_w = int(2.3 * scale)
    sig_gap = int(1.8 * scale)
    sig_total_w = 4 * sig_bar_w + 3 * sig_gap
    sig_x = wifi_left - icon_gap - sig_total_w
    for i in range(4):
        h_i = int((3.5 + i * 2.5) * scale)
        x_i = sig_x + i * (sig_bar_w + sig_gap)
        draw.rounded_rectangle([x_i, center_y + int(6 * scale) - h_i, x_i + sig_bar_w, center_y + int(6 * scale)], radius=int(0.8 * scale), fill=fg_color)
    bar_down = bar.resize((sw, bar_h), Image.Resampling.LANCZOS)
    screen_img.paste(bar_down, (0, 0), bar_down)
    return screen_img

def draw_phone_home_indicator(screen_img: Image.Image, scale: int = 4, theme: str = "auto") -> Image.Image:
    """Draws bottom gesture bar (Home Indicator)."""
    sw, sh = screen_img.size
    ind_w, ind_h = 138, 5
    ind_x = (sw - ind_w) // 2
    ind_y = sh - 14

    if theme == "light":
        ind_color = (255, 255, 255, 200)
    elif theme == "dark":
        ind_color = (28, 28, 30, 200)
    else:
        sample_pt = (sw // 2, min(sh - 1, sh - 14))
        bot_c = screen_img.getpixel(sample_pt)[:3]
        luminance = 0.299 * bot_c[0] + 0.587 * bot_c[1] + 0.114 * bot_c[2]
        ind_color = (255, 255, 255, 200) if luminance < 130 else (28, 28, 30, 200)

    big_w, big_h = ind_w * scale, ind_h * scale
    big_bar = Image.new("RGBA", (big_w, big_h), (0, 0, 0, 0))
    ImageDraw.Draw(big_bar).rounded_rectangle([0, 0, big_w - 1, big_h - 1], radius=big_h // 2, fill=ind_color)

    bar_img = big_bar.resize((ind_w, ind_h), Image.Resampling.LANCZOS)
    screen_img.paste(bar_img, (ind_x, ind_y), bar_img)
    return screen_img

def make_phone_mockup(
    screen_content: Image.Image,
    target_width: int = 410,
    scale: int = 4,
    time_text: str = "9:41",
    theme: str = "auto",
    mode: str = "safe-area",
    time_weight: int = 480
) -> Image.Image:
    """Wraps mobile screenshot into phone chassis with status bar and home indicator."""
    content_w = target_width
    ratio = content_w / screen_content.width
    content_h = int(screen_content.height * ratio)

    top_bar_h = 54
    bottom_bar_h = 34
    total_screen_h = 890
    visible_content_h = total_screen_h - top_bar_h - bottom_bar_h

    screen_resized = screen_content.resize((content_w, content_h), Image.Resampling.LANCZOS).convert("RGBA")

    if mode == "overlay":
        # Edge-to-edge full bleed: screen content fills screen from (0, 0)
        screen = Image.new("RGBA", (content_w, total_screen_h), (255, 255, 255, 255))
        screen.paste(screen_resized, (0, 0))
    else:
        # Standard safe-area mode: reserve 54pt top bar matching header background color
        sample_xs = [content_w // 4, content_w // 2, 3 * content_w // 4, 10, content_w - 10]
        top_samples = [screen_resized.getpixel((x, min(1, content_h - 1))) for x in sample_xs]
        top_color = max(set(top_samples), key=top_samples.count)

        screen = Image.new("RGBA", (content_w, total_screen_h), top_color)
        screen.paste(screen_resized, (0, top_bar_h))

        # Fill bottom safe area with matching background color
        bottom_y = min(content_h - 1, visible_content_h - 1)
        bottom_color = screen_resized.getpixel((content_w // 2, max(0, bottom_y)))
        bottom_fill = Image.new("RGBA", (content_w, bottom_bar_h), bottom_color)
        screen.paste(bottom_fill, (0, total_screen_h - bottom_bar_h))

    screen = draw_phone_status_bar(screen, scale=scale, bar_h=top_bar_h, time_text=time_text, theme=theme, time_weight=time_weight)
    screen = draw_phone_home_indicator(screen, scale=scale, theme=theme)

    # 4x SSAA screen rounded mask
    screen_radius = 42
    screen_mask = create_smooth_mask(content_w, total_screen_h, screen_radius, scale=scale)
    rounded_screen = Image.new("RGBA", (content_w, total_screen_h), (0, 0, 0, 0))
    rounded_screen.paste(screen, (0, 0), screen_mask)

    # Chassis frame
    bezel = 12
    phone_w = content_w + bezel * 2
    phone_h = total_screen_h + bezel * 2
    outer_radius = screen_radius + bezel

    big_w, big_h = phone_w * scale, phone_h * scale
    big_outer_r = outer_radius * scale
    big_chassis = Image.new("RGBA", (big_w, big_h), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(big_chassis)
    c_draw.rounded_rectangle([0, 0, big_w - 1, big_h - 1], radius=big_outer_r, fill=(27, 27, 29, 255))
    c_draw.rounded_rectangle([0, 0, big_w - 1, big_h - 1], radius=big_outer_r, outline=(75, 75, 80, 255), width=int(1.5 * scale))

    phone_chassis = big_chassis.resize((phone_w, phone_h), Image.Resampling.LANCZOS)
    phone_chassis.paste(rounded_screen, (bezel, bezel), rounded_screen)
    return phone_chassis


# ----------------------------------------------------------------------
# 4. Headless Chrome Capture
# ----------------------------------------------------------------------

def find_chrome_binary(custom_path: str = None) -> str:
    if custom_path and os.path.exists(custom_path):
        return custom_path
    candidates = [
        # Common Linux paths
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        # Playwright cache on Linux
        str(Path.home() / ".cache/ms-playwright/chromium-1248/chrome-linux64/chrome"),
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        # Windows
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # Fallback to which
    for name in ["google-chrome", "chromium", "chromium-browser"]:
        p = shutil.which(name)
        if p:
            return p
    return None

def capture_screenshot(chrome_path: str, url: str, output_path: str, width: int, height: int, is_mobile: bool = False, wait_sec: float = 2.0):
    """Takes crisp Retina 2x screenshot using headless Chrome CLI."""
    budget_ms = int(wait_sec * 1000)
    cmd = [
        chrome_path,
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=2",
        f"--window-size={width},{height}",
        f"--virtual-time-budget={budget_ms}",
        "--run-all-compositor-stages-before-draw",
        f"--screenshot={output_path}",
    ]
    if is_mobile:
        cmd.append('--user-agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"')
    cmd.append(url)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Chrome capture failed: {res.stderr}")
    if not os.path.exists(output_path):
        raise FileNotFoundError(f"Failed to capture {output_path}")


# ----------------------------------------------------------------------
# 5. CLI & Pipeline Orchestration
# ----------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Generate marketing poster and mockups for web projects.")
    parser.add_argument("--url", default="http://localhost:4173/", help="Target URL to capture")
    parser.add_argument("--site-url", default="font.yukonga.top", help="Website domain displayed in browser address bar")
    parser.add_argument("--widescreen-input", help="Path to existing widescreen screenshot (skips capture if provided)")
    parser.add_argument("--mobile-input", help="Path to existing mobile screenshot (skips capture if provided)")
    parser.add_argument("--output-dir", default=".", help="Directory to save generated images")
    parser.add_argument("--bg", default="#ffffff", help="Poster background color: #ffffff, #f5f6f7, or transparent")
    parser.add_argument("--chrome-path", help="Path to Chrome/Chromium executable")
    parser.add_argument("--status-bar-time", default="9:41", help="Time displayed in mobile status bar (default: 9:41)")
    parser.add_argument("--status-bar-theme", choices=["auto", "dark", "light"], default="auto", help="Status bar theme: auto (detect from header luminance), dark (dark icons), or light (light icons)")
    parser.add_argument("--status-bar-mode", choices=["safe-area", "overlay"], default="safe-area", help="Status bar placement mode: safe-area (reserve 54pt header) or overlay (draw on top of content)")
    parser.add_argument("--status-bar-weight", type=int, default=480, help="MiSans font weight for status bar time: 150-700 (default: 480)")
    return parser.parse_args()

def main():
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve source screenshots
    desk_path = args.widescreen_input
    mob_path = args.mobile_input

    if not desk_path or not mob_path:
        chrome_bin = find_chrome_binary(args.chrome_path)
        if not chrome_bin:
            print("Error: Could not locate Chrome/Chromium. Please provide --chrome-path or existing --widescreen-input and --mobile-input.", file=sys.stderr)
            sys.exit(1)
        print(f"Using Chrome binary: {chrome_bin}")

        if not desk_path:
            desk_path = str(out_dir / "temp_widescreen.png")
            print(f"Capturing widescreen from {args.url} ...")
            capture_screenshot(chrome_bin, args.url, desk_path, 1440, 960, is_mobile=False)

        if not mob_path:
            mob_path = str(out_dir / "temp_mobile.png")
            print(f"Capturing mobile from {args.url} ...")
            capture_screenshot(chrome_bin, args.url, mob_path, 390, 844, is_mobile=True)

    # Load screenshots
    desk_raw = Image.open(desk_path).convert("RGBA")
    mob_raw = Image.open(mob_path).convert("RGBA")

    # 2. Build mockups
    print("Rendering browser mockup ...")
    desk_w = 1580
    desk_h = int(desk_raw.height * (desk_w / desk_raw.width))
    desk_mockup = make_browser_mockup(desk_raw.resize((desk_w, desk_h), Image.Resampling.LANCZOS), url_text=args.site_url)

    print("Rendering phone mockup (SSAA 4x anti-aliased with Status Bar & Home Indicator) ...")
    phone_mockup = make_phone_mockup(
        mob_raw,
        target_width=410,
        time_text=args.status_bar_time,
        theme=args.status_bar_theme,
        mode=args.status_bar_mode,
        time_weight=args.status_bar_weight
    )

    # 3. Save standalone mockups
    save_color_managed_png(desk_raw, str(out_dir / "screenshot_widescreen.png"))

    # Parse background color
    bg_hex = args.bg.lstrip("#")
    if len(bg_hex) == 6:
        bg_rgb = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))
    else:
        bg_rgb = (255, 255, 255)

    phone_canvas_w = phone_mockup.width + 120
    phone_canvas_h = phone_mockup.height + 120
    phone_canvas = Image.new("RGBA", (phone_canvas_w, phone_canvas_h), (*bg_rgb, 255))
    p_shadow, p_pad = add_shadow(phone_mockup, blur_radius=36, offset=(0, 20), opacity=0.22)
    phone_canvas.paste(p_shadow, (60 - p_pad, 50 - p_pad), p_shadow)
    save_color_managed_png(phone_canvas, str(out_dir / "screenshot_mobile.png"))

    # 4. Build composite poster
    print("Assembling composite poster ...")
    cw, ch = 2200, 1350
    poster = Image.new("RGBA", (cw, ch), (*bg_rgb, 255))

    # Paste desktop window with shadow
    desk_shadow, d_pad = add_shadow(desk_mockup, blur_radius=35, offset=(0, 20), opacity=0.12)
    poster.paste(desk_shadow, (90 - d_pad, 110 - d_pad), desk_shadow)

    # Paste phone mockup overlapping lower-right
    mob_shadow, m_pad = add_shadow(phone_mockup, blur_radius=44, offset=(-10, 28), opacity=0.30)
    mob_x = cw - phone_mockup.width - 110
    mob_y = ch - phone_mockup.height - 70
    poster.paste(mob_shadow, (mob_x - m_pad, mob_y - m_pad), mob_shadow)

    save_color_managed_png(poster, str(out_dir / "screenshot_poster.png"))

    # Clean up temp files if generated
    for tmp in ["temp_widescreen.png", "temp_mobile.png"]:
        tmp_p = out_dir / tmp
        if tmp_p.exists():
            tmp_p.unlink()

    print("\nGeneration complete!")
    print(f"  - Poster:     {out_dir / 'screenshot_poster.png'}")
    print(f"  - Widescreen: {out_dir / 'screenshot_widescreen.png'}")
    print(f"  - Mobile:     {out_dir / 'screenshot_mobile.png'}")

if __name__ == "__main__":
    main()

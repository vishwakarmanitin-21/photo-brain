"""Generate PhotoBrain app icon (.ico) — high-resolution with supersampling."""
from PIL import Image, ImageDraw
import math
import os

# Draw at 4x then downscale for crisp anti-aliased results
RENDER_SIZE = 1024
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def _radial_gradient(draw, cx, cy, r, color_inner, color_outer, steps=60):
    """Draw a radial gradient as concentric circles (inner on top)."""
    for i in range(steps, -1, -1):
        t = i / steps
        cr = r * t
        c = tuple(
            int(color_inner[j] + (color_outer[j] - color_inner[j]) * t)
            for j in range(4)
        )
        draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=c)


def draw_icon_hires() -> Image.Image:
    """Draw the icon at RENDER_SIZE with full detail."""
    S = RENDER_SIZE
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = S / 2, S / 2
    margin = S * 0.04
    r_bg = S / 2 - margin

    # ── Background circle with subtle gradient ──
    _radial_gradient(
        draw, cx, cy, r_bg,
        (30, 140, 235, 255),   # center: bright blue
        (20, 100, 200, 255),   # edge: deeper blue
        steps=80,
    )

    # ── Camera body ──
    cam_w = r_bg * 1.30
    cam_h = r_bg * 0.88
    cam_top = cy - cam_h * 0.40
    cam_bot = cy + cam_h * 0.54
    cam_left = cx - cam_w * 0.5
    cam_right = cx + cam_w * 0.5
    rr = S * 0.05

    # Shadow under camera
    shadow_off = S * 0.012
    draw.rounded_rectangle(
        [cam_left + shadow_off, cam_top + shadow_off * 2,
         cam_right + shadow_off, cam_bot + shadow_off * 2],
        radius=rr,
        fill=(15, 70, 130, 80),
    )

    # Camera body (white)
    draw.rounded_rectangle(
        [cam_left, cam_top, cam_right, cam_bot],
        radius=rr,
        fill=(250, 252, 255, 240),
    )

    # Subtle top edge highlight
    draw.rounded_rectangle(
        [cam_left + 2, cam_top + 2, cam_right - 2, cam_top + cam_h * 0.08],
        radius=rr * 0.5,
        fill=(255, 255, 255, 60),
    )

    # ── Viewfinder hump ──
    hump_w = cam_w * 0.26
    hump_h = cam_h * 0.20
    hump_left = cx - hump_w * 0.35
    hump_right = cx + hump_w * 0.65
    hump_top = cam_top - hump_h * 0.85
    draw.rounded_rectangle(
        [hump_left, hump_top, hump_right, cam_top + rr * 0.7],
        radius=rr * 0.6,
        fill=(240, 243, 248, 240),
    )

    # ── Lens — outer ring ──
    lens_cy = (cam_top + cam_bot) / 2 + S * 0.012
    lens_r = min(cam_w, cam_h) * 0.32

    # Dark bezel
    draw.ellipse(
        [cx - lens_r, lens_cy - lens_r, cx + lens_r, lens_cy + lens_r],
        fill=(35, 35, 55, 255),
    )

    # Metallic ring
    ring_r = lens_r * 0.92
    draw.ellipse(
        [cx - ring_r, lens_cy - ring_r, cx + ring_r, lens_cy + ring_r],
        fill=(65, 65, 85, 255),
    )

    # ── Lens — glass with gradient ──
    glass_r = lens_r * 0.82
    _radial_gradient(
        draw, cx, lens_cy, glass_r,
        (180, 120, 255, 255),  # center: bright purple
        (60, 30, 140, 255),    # edge: deep purple
        steps=50,
    )

    # Lens flare / reflection (arc highlight)
    flare_r = glass_r * 0.65
    flare_off_x = -glass_r * 0.18
    flare_off_y = -glass_r * 0.18
    draw.ellipse(
        [cx + flare_off_x - flare_r, lens_cy + flare_off_y - flare_r,
         cx + flare_off_x + flare_r, lens_cy + flare_off_y + flare_r],
        fill=(160, 110, 240, 40),
    )

    # Bright center dot
    ctr_r = glass_r * 0.18
    draw.ellipse(
        [cx - ctr_r, lens_cy - ctr_r, cx + ctr_r, lens_cy + ctr_r],
        fill=(220, 190, 255, 200),
    )

    # Small specular highlight (top-left of lens)
    spec_r = glass_r * 0.12
    spec_cx = cx - glass_r * 0.35
    spec_cy = lens_cy - glass_r * 0.35
    draw.ellipse(
        [spec_cx - spec_r, spec_cy - spec_r,
         spec_cx + spec_r, spec_cy + spec_r],
        fill=(255, 255, 255, 120),
    )

    # ── Neural network dots + connections (brain motif) ──
    num_dots = 10
    dot_r = S * 0.012
    orbit_r = lens_r * 1.20
    dot_positions = []

    for i in range(num_dots):
        angle = (2 * math.pi / num_dots) * i - math.pi / 2
        dx = cx + orbit_r * math.cos(angle)
        dy = lens_cy + orbit_r * math.sin(angle)
        dot_positions.append((dx, dy))

    # Draw connections (thin lines between adjacent dots)
    line_w = max(2, int(S * 0.004))
    for i in range(num_dots):
        j = (i + 1) % num_dots
        draw.line(
            [dot_positions[i], dot_positions[j]],
            fill=(76, 175, 80, 100),
            width=line_w,
        )

    # Draw dots on top
    for i, (dx, dy) in enumerate(dot_positions):
        dr = dot_r * (1.0 + 0.25 * (i % 3))
        # Outer glow
        draw.ellipse(
            [dx - dr * 1.6, dy - dr * 1.6, dx + dr * 1.6, dy + dr * 1.6],
            fill=(76, 175, 80, 50),
        )
        # Solid dot
        draw.ellipse(
            [dx - dr, dy - dr, dx + dr, dy + dr],
            fill=(76, 200, 80, 230),
        )

    # ── Flash (top-right) ──
    flash_r = S * 0.022
    flash_cx = cam_right - cam_w * 0.14
    flash_cy = cam_top + cam_h * 0.14
    # Glow
    draw.ellipse(
        [flash_cx - flash_r * 2.2, flash_cy - flash_r * 2.2,
         flash_cx + flash_r * 2.2, flash_cy + flash_r * 2.2],
        fill=(255, 235, 59, 50),
    )
    draw.ellipse(
        [flash_cx - flash_r, flash_cy - flash_r,
         flash_cx + flash_r, flash_cy + flash_r],
        fill=(255, 235, 59, 250),
    )

    # ── Shutter button (small circle on top of camera) ──
    shut_r = S * 0.018
    shut_cx = cam_right - cam_w * 0.30
    shut_cy = cam_top - S * 0.006
    draw.ellipse(
        [shut_cx - shut_r, shut_cy - shut_r,
         shut_cx + shut_r, shut_cy + shut_r],
        fill=(200, 210, 220, 200),
    )

    return img


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "assets")
    os.makedirs(out_dir, exist_ok=True)

    # Render at high resolution
    hires = draw_icon_hires()

    # Generate each ICO size by downscaling with high-quality resampling
    images = []
    for s in ICO_SIZES:
        resized = hires.resize((s, s), Image.LANCZOS)
        images.append(resized)

    ico_path = os.path.join(out_dir, "photobrain.ico")
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=images[1:],
    )
    print(f"Icon saved to {ico_path}")

    # Save 256px PNG for reference
    png_path = os.path.join(out_dir, "photobrain_256.png")
    images[-1].save(png_path)
    print(f"PNG saved to {png_path}")


if __name__ == "__main__":
    main()

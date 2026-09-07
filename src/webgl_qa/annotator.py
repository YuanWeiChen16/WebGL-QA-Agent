"""Screenshot annotator — draws click markers, action labels on screenshots."""

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


# Colors
COLOR_CLICK = (255, 50, 50, 200)       # Red for clicks
COLOR_DRAG_START = (50, 255, 50, 200)  # Green for drag start
COLOR_DRAG_END = (50, 50, 255, 200)    # Blue for drag end
COLOR_TEXT_BG = (0, 0, 0, 160)         # Semi-transparent black
COLOR_TEXT = (255, 255, 255, 255)      # White text


def annotate_click(image_path: str, x: int, y: int, label: str = "", output_path: str = None) -> str:
    """Draw a click marker (crosshair + circle) on a screenshot.
    
    Returns path to annotated image.
    """
    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Draw crosshair
    size = 20
    draw.line([(x - size, y), (x + size, y)], fill=COLOR_CLICK, width=2)
    draw.line([(x, y - size), (x, y + size)], fill=COLOR_CLICK, width=2)

    # Draw circle
    radius = 15
    draw.ellipse(
        [(x - radius, y - radius), (x + radius, y + radius)],
        outline=COLOR_CLICK,
        width=2,
    )

    # Draw label
    if label:
        _draw_label(draw, x + 20, y - 10, label)

    # Composite
    result = Image.alpha_composite(img, overlay).convert("RGB")
    out = output_path or image_path.replace(".png", "_annotated.png")
    result.save(out)
    return out


def annotate_drag(image_path: str, from_x: int, from_y: int, to_x: int, to_y: int,
                  label: str = "", output_path: str = None) -> str:
    """Draw a drag arrow on a screenshot."""
    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Draw start point (green)
    draw.ellipse(
        [(from_x - 10, from_y - 10), (from_x + 10, from_y + 10)],
        fill=COLOR_DRAG_START,
    )

    # Draw end point (blue)
    draw.ellipse(
        [(to_x - 10, to_y - 10), (to_x + 10, to_y + 10)],
        fill=COLOR_DRAG_END,
    )

    # Draw line between
    draw.line([(from_x, from_y), (to_x, to_y)], fill=COLOR_CLICK, width=2)

    # Arrow head
    import math
    angle = math.atan2(to_y - from_y, to_x - from_x)
    arrow_len = 12
    draw.line([
        (to_x, to_y),
        (to_x - arrow_len * math.cos(angle - 0.4), to_y - arrow_len * math.sin(angle - 0.4)),
    ], fill=COLOR_CLICK, width=2)
    draw.line([
        (to_x, to_y),
        (to_x - arrow_len * math.cos(angle + 0.4), to_y - arrow_len * math.sin(angle + 0.4)),
    ], fill=COLOR_CLICK, width=2)

    if label:
        mid_x = (from_x + to_x) // 2
        mid_y = (from_y + to_y) // 2
        _draw_label(draw, mid_x, mid_y - 15, label)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    out = output_path or image_path.replace(".png", "_annotated.png")
    result.save(out)
    return out


def annotate_longpress(image_path: str, x: int, y: int, duration: float,
                       label: str = "", output_path: str = None) -> str:
    """Draw a long-press indicator (concentric circles) on a screenshot."""
    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Concentric circles (more rings = longer press)
    rings = min(int(duration) + 2, 6)
    for i in range(rings):
        r = 10 + i * 8
        alpha = max(50, 200 - i * 30)
        color = (255, 50, 50, alpha)
        draw.ellipse([(x - r, y - r), (x + r, y + r)], outline=color, width=2)

    # Center dot
    draw.ellipse([(x - 4, y - 4), (x + 4, y + 4)], fill=COLOR_CLICK)

    label_text = label or f"long press {duration}s"
    _draw_label(draw, x + 20, y - 10, label_text)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    out = output_path or image_path.replace(".png", "_annotated.png")
    result.save(out)
    return out


def annotate_sequence(image_path: str, actions: list, output_path: str = None) -> str:
    """Draw multiple action markers on a single screenshot.
    
    actions: list of dicts with keys:
      - type: "click" | "drag" | "longpress"
      - x, y (and to_x, to_y for drag)
      - label: optional
      - step: step number
    """
    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for i, action in enumerate(actions):
        step = action.get("step", i + 1)
        x = action.get("x", 0)
        y = action.get("y", 0)
        atype = action.get("type", "click")

        if atype == "click":
            # Numbered circle
            radius = 12
            draw.ellipse(
                [(x - radius, y - radius), (x + radius, y + radius)],
                fill=COLOR_CLICK,
                outline=(255, 255, 255, 255),
                width=1,
            )
            # Step number
            draw.text((x - 4, y - 6), str(step), fill=COLOR_TEXT)
            if action.get("label"):
                _draw_label(draw, x + 18, y - 8, action["label"])

        elif atype == "drag":
            to_x = action.get("to_x", x)
            to_y = action.get("to_y", y)
            draw.ellipse([(x - 6, y - 6), (x + 6, y + 6)], fill=COLOR_DRAG_START)
            draw.ellipse([(to_x - 6, to_y - 6), (to_x + 6, to_y + 6)], fill=COLOR_DRAG_END)
            draw.line([(x, y), (to_x, to_y)], fill=COLOR_CLICK, width=2)
            draw.text((x - 4, y - 16), str(step), fill=COLOR_TEXT)

        elif atype == "longpress":
            duration = action.get("duration", 1)
            rings = min(int(duration) + 1, 4)
            for r_i in range(rings):
                r = 8 + r_i * 6
                alpha = max(80, 200 - r_i * 40)
                draw.ellipse([(x - r, y - r), (x + r, y + r)],
                             outline=(255, 50, 50, alpha), width=2)
            draw.text((x - 4, y - 6), str(step), fill=COLOR_TEXT)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    out = output_path or image_path.replace(".png", "_annotated.png")
    result.save(out)
    return out


def _draw_label(draw: ImageDraw.Draw, x: int, y: int, text: str):
    """Draw a label with background."""
    # Use default font
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((x, y), text, font=font)
    padding = 3
    draw.rectangle(
        [bbox[0] - padding, bbox[1] - padding, bbox[2] + padding, bbox[3] + padding],
        fill=COLOR_TEXT_BG,
    )
    draw.text((x, y), text, fill=COLOR_TEXT, font=font)

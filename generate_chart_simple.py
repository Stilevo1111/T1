#!/usr/bin/env python3
"""Simple test to generate a sample chart PNG using PIL only (no plotly required)"""

import os

from PIL import Image, ImageDraw, ImageFont


def create_test_chart():
    width, height = 800, 400
    img = Image.new("RGB", (width, height), color="#18181b")
    draw = ImageDraw.Draw(img)

    # Draw a simple trend line
    points = [(50 + i * 70, 300 - i * 30) for i in range(10)]
    for i in range(len(points) - 1):
        draw.line([points[i], points[i+1]], fill="#ff9900", width=4)

    # Draw hero icons as colored circles (simulated)
    for i, (x, y) in enumerate(points):
        # Color based on IMP simulation
        if i < 3:
            circle_color = (34, 197, 94)  # green
        elif i > 6:
            circle_color = (239, 68, 68)  # red
        else:
            circle_color = (255, 255, 255)  # white

        draw.ellipse([x-25, y-25, x+25, y+25], outline=circle_color, width=3)
        draw.ellipse([x-20, y-20, x+20, y+20], fill="#222222")
        # Hero number
        draw.text((x-5, y-5), str(i+1), fill="white")

    # Draw improvement badge
    draw.rounded_rectangle([620, 20, 780, 60], radius=14, fill="#22c55e")
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    draw.text((640, 28), "в†‘ Improvement", fill="white", font=font)

    # Draw title
    title = "Weekly Analytics Test Chart"
    draw.text((50, 340), title, fill="white", font=font)

    output_path = "test_chart_simple.png"
    img.save(output_path)
    print("[OK] Test chart saved:", output_path)
    print("   Size:", os.path.getsize(output_path), "bytes")
    return output_path

if __name__ == "__main__":
    create_test_chart()

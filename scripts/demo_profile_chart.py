#!/usr/bin/env python3
"""Generate demo profile chart showing the visual fixes."""

import io
import sys
sys.path.insert(0, '.')

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def generate_demo_chart():
    WIDTH, HEIGHT = 1200, 800
    
    font_path = Path("assets/fonts/NotoSans-Regular.ttf")
    font_large = ImageFont.truetype(str(font_path), 24) if font_path.exists() else ImageFont.load_default()
    font_small = ImageFont.truetype(str(font_path), 14) if font_path.exists() else ImageFont.load_default()
    
    bg_color = (15, 15, 25)
    img = Image.new('RGB', (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)
    
    grid_color = (30, 30, 45)
    for i in range(0, WIDTH, 40):
        draw.line([(i, 0), (i, HEIGHT)], fill=grid_color, width=1)
    for i in range(0, HEIGHT, 40):
        draw.line([(0, i), (WIDTH, i)], fill=grid_color, width=1)
    
    title_y = 30
    draw.text((20, title_y), "PROFILE IMPACT CHART — VISUAL EXAMPLE", 
              fill=(255, 255, 255))
    
    draw.text((20, 60), "Legend:", fill=(255, 255, 255), font=font_large)
    
    draw.text((40, 90), "• Yellow dashed line at y=1.0 — PRO benchmark (1.00)", 
              fill="#ffff00", font=font_small)
    
    draw.text((40, 120), "• Gold smooth curve — Your IMPACT line (capped at corners)", 
              fill="#f4c430", font=font_small)
    
    draw.text((40, 150), "• Green/red circle points — Match wins/losses", 
              fill=(255, 255, 255), font=font_small)
    
    draw.text((40, 180), "• Hero icons ON the line (not below)", 
              fill=(255, 255, 255), font=font_small)
    
    demo_impacts_wins = [(1.25, True), (1.10, True), (1.45, True)]
    demo_impacts_losses = [(0.65, False), (0.55, False), (0.45, False)]
    demo_all = demo_impacts_wins + demo_impacts_losses
    
    chart_left = 200
    chart_right = 1000
    chart_top = 250
    chart_bottom = 650
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top
    
    zero_y = chart_top + int(chart_height * 0.5)
    draw.line([chart_left, zero_y, chart_right, zero_y], fill="#ffff00", width=3)
    draw.text((chart_right + 10, zero_y - 12), "1.00", fill="#ffff00", font=font_small, anchor="la")
    draw.text((chart_right + 10, zero_y + 5), "PRO", fill="#ffff00", font=font_small, anchor="la")
    
    for i, (imp, win) in enumerate(demo_all):
        x = chart_left + int((i + 1) * chart_width / 6)
        y = zero_y - int(chart_height * (imp - 0.5) / 1.0)
        y = max(chart_top + 15, min(chart_bottom - 15, y))
        
        color = "#00ff66" if win else "#ff3b3b"
        draw.ellipse([x-12, y-12, x+12, y+12], outline=color, width=4, fill=color)
    
    draw.line([chart_left, zero_y - 50, chart_right, zero_y + 50], fill="#f4c430", width=3)
    
    draw.text((20, HEIGHT - 70), "Y-axis: IMPACT score (0.0 to 2.0)", 
              fill=(200, 200, 200), font=font_small)
    draw.text((20, HEIGHT - 45), "X-axis: Match number (1 to 10, right to left]", 
              fill=(200, 200, 200), font=font_small)
    
    output_path = Path("test_profile_chart/demo_chart.png")
    output_path.parent.mkdir(exist_ok=True)
    img.save(output_path, quality=95)
    print(f"Demo chart saved to: {output_path}")
    
    return str(output_path)

if __name__ == "__main__":
    generate_demo_chart()
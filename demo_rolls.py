#!/usr/bin/env python3
"""
Demo script to show examples of roll outputs after fixes.
"""

import sys
import os
sys.path.insert(0, '.')

from rolls import get_roll_text, ROLL_TEXTS
import random

def demo_roll_texts():
    """Show what different roll values look like as text."""
    print("=" * 60)
    print("ROLL TEXTS EXAMPLES (from get_roll_text function)")
    print("=" * 60)
    
    test_values = [-15, -10, -5, -3, -1, 0, 1, 3, 5, 10, 15, 25, 50, 75, 100, 105]
    
    for val in test_values:
        # Get a few random variations to show variety
        samples = []
        for _ in range(3):
            samples.append(get_roll_text(val))
        
        print(f"\nRoll value: {val:+4d}")
        for i, sample in enumerate(samples, 1):
            print(f"  {i}. {sample}")

def demo_message_structure():
    """Show how the final message would look."""
    print("\n" + "=" * 60)
    print("FULL MESSAGE STRUCTURE EXAMPLES")
    print("=" * 60)
    
    # Simulate what goes into a fissure message
    from functools import partial
    
    # Mock the parts that would be in a real message
    def format_message_part(username, roll_value, is_negative=False, cascade=False, 
                          streak_text="", weekend_bonus="", multicast_text=""):
        mers=""):
        """Format a message similar to what fissure.py does now."""
        parts = []
        
        # Header
        parts.append(f"🎲 {username}")
        
        # Hero quote (simplified)
        if is_negative:
            parts.append("🔨Рейгор Каменное Копыто 🗣️ Imperia не дремлет. И я уже не герой.")
        else:
            parts.append("🪶Кестрель, Нелётная ярость 🗣️ Земля содрогнулась")
        
        # Roll text
        roll_text = get_roll_text(roll_value)
        parts.append(roll_text)
        
        # Optional extras
        if streak_text:
            parts.append(streak_text)
        if weekend_bonus:
            parts.append(weekend_bonus)
        if multicast_text:
            parts.append(multicast_text)
            
        # Roll value display (NEW STANDARD FORMAT)
        roll_display = f"+{roll_value}" if roll_value > 0 else str(roll_value)
        if cascade_count > 1:
            parts.append(f"⚡ МУЛЬТЬКАСТ×{cascade_count}  {roll_display} см")
        else:
            parts.append(f"⚡ {roll_display} см")
            
        # Fissure change (always at end)
        # Simulate some change
        old_fissure = 100.0
        new_fissure = old_fissure + roll_value
        parts.append(f"📏 {old_fissure:.1f} см → {new_fissure:.1f} см")
        
        # Join with double newlines between main sections
        return "\n\n".join(parts)
    
    print("\n1. POSITIVE ROLL EXAMPLE (+25):")
    print("-" * 40)
    print(format_message_part(
        username="TestPlayer",
        roll_value=25,
        is_negative=False,
        cascade_count=1,
        streak_text="🔥 СТРИК x3: +3 см.",
        weekend_bonus="🎉 ВЫХОДНОЙ! x2.0 = 50.0 см.",
        multicast_text=""
    ))
    
    print("\n\n2. NEGATIVE ROLL EXAMPLE (-5) - THE FIXED ONE:")
    print("-" * 40)
    print(format_message_part(
        username="TestPlayer",
        roll_value=-5,
        is_negative=True,
        cascade_count=1,
        streak_text="",
        weekend_bonus="",
        multicast_text=""
    ))
    
    print("\n\n3. ZERO ROLL EXAMPLE:")
    print("-" * 40)
    print(format_message_part(
        username="TestPlayer",
        roll_value=0,
        is_negative=False,
        cascade_count=1,
        streak_text="",
        weekend_bonus="",
        multicast_text=""
    ))
    
    print("\n\n4. MULTICAST EXAMPLE (x3) WITH BASE ROLL -4:")
    print("-" * 40)
    print(format_message_part(
        username="TestPlayer",
        roll_value=-12,  # Final roll after multiplying -4 x 3
        is_negative=True,
        cascade_count=3,
        original_roll=-4,  # The base roll before multiplying
        streak_text="🔥 СТРИК x2: +2 см.",
        weekend_bonus="",
        multicast_text="🍇 Аггрон Камнелом 🗣️ Это не повезло, это мастерство. Мастерство быть везучим! Ха-ха!"
    ))
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    demo_roll_texts()
    demo_message_structure()
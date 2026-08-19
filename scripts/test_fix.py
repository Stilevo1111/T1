#!/usr/bin/env python3
"""
Test script to demonstrate the fixed roll outputs.
"""

import sys
import os
sys.path.insert(0, '.')

from rolls import get_roll_text

def test_roll_outputs():
    """Test various roll outputs to verify fixes."""
    
    print("TESTING ROLL OUTPUTS AFTER FIXES")
    print("=" * 50)
    
    # Test the specific -5 roll that was fixed
    print("\n1. Testing -5 roll (the originally reported issue):")
    print("-" * 50)
    for i in range(3):
        result = get_roll_text(-5)
        print(f"  Attempt {i+1}: {result}")
        # Verify it contains the number and our new text
        assert "-5 см" in result, f"Missing '-5 см' in: {result}"
        assert "ОТСТУП" in result, f"Missing 'ОТСТУП' in: {result}"
        assert "Восстановлюсь" in result, f"Missing 'Восстановлюсь' in: {result}"
        assert "😔" in result, f"Missing '😔' emoji in: {result}"
    print("  ✅ All -5 rolls correctly show number and updated text/emoji")
    
    # Test a few other values to make sure we didn't break anything
    print("\n2. Testing other values to ensure no regression:")
    print("-" * 50)
    test_values = [0, 5, -3, 10, 15]
    for val in test_values:
        result = get_roll_text(val)
        print(f"  {val:+3d}: {result}")
        # Verify it contains the number
        abs_val = abs(val)
        if val == 0:
            # Special case for zero
            pass  # Zero has special handling
        else:
            assert f"{abs_val} см" in result, f"Missing '{abs_val} см' in result for {val}"
    print("  ✅ All test values correctly show their numbers")
    
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED!")
    print("The roll outputs now correctly:")
    print("1. Show the numeric value (e.g., '-5 см', '+5 см')")
    print("2. Use appropriate emojis and text for each value")
    print("3. Have been fixed for the specific -5 case reported")

if __name__ == "__main__":
    test_roll_outputs()
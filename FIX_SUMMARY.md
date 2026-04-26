# Fix Summary: Fissure Bot Roll Calculation and Message Display

## Problems Fixed

### 1. Multicast + Weekend Bonus Conflict ❌ → ✅
**Problem**: Weekend bonus (x2.0, x1.5, etc.) was incorrectly applied during multicast rolls (x2, x3, x4)
**Fix**: Added `cascade_count == 1` condition (line 2501) so weekend bonus only applies to single rolls

### 2. Result Text Showing Wrong Value ❌ → ✅
**Problem**: `result_text` showed base roll (e.g., "+6 см") instead of final value after bonuses
**Fix**: Moved `result_text` calculation to AFTER all bonuses are applied (line 2517-2524)

### 3. Multicast Format - Extra Newline ❌ → ✅
**Problem**: Extra blank line between "УЛУЧШЕНИЕ! +6 СМ!" and "⚡ МУЛЬТИКАСТ×2"
**Fix**: Changed `f"{multicast_text}\n\n"` to `f"{multicast_text}\n"` (line 2552)

### 4. Weekend Bonus Format - Extra Newline ❌ → ✅
**Problem**: Weekend bonus had leading `\n` causing double blank lines
**Fix**: Removed `\n` from weekend_bonus string (line 2506)

### 5. Multicast Banner ❌ → ✅
**Problem**: Multicast used same banner as regular rolls
**Fix**: Multicast now uses different banner `dsad23.png` (line 2575)
- Regular roll: `Hf-S7B.jpg`
- Multicast: `dsad23.png`

### 6. Bonus for 10 Rolls - REMOVED 🗑️
**Problem**: Bonus for 10 rolls was being overwritten by random category phrases
**Fix**: Completely removed the bonus-for-10-rolls mechanism
- Removed `has_bonus` check (line 2493-2497)
- Removed bonus text from output
- Removed related logic

### 7. Double Sleep Delay ❌ → ✅
**Problem**: Ordinary rolls had 0.6s delay (2x 0.3s) causing unnecessary lag
**Fix**: Removed sleep for ordinary rolls, only multicast has 0.3s delay (line 2481, 2484)

### 8. aiohttp Session Leaks ⚠️ → ✅
**Problem**: "Unclosed connection" warnings from direct `aiohttp.ClientSession()` calls
**Fix**: Replaced with shared session from `database.py`:
- `fetch_hero_icon()` (line 1900)
- `keep_alive_ping()` (line 3686)
- `_api_get_async()` in dota_mmr.py (line 165)

### 9. Message Visibility Issues ❌ → ✅
**Problem**: Messages deleted too quickly, sometimes before display
**Fix**: Added strategic delays:
- 0.2s before deleting last bot message (line 2292)
- 0.1s after cooldown messages (line 2328)
- 0.1s after Zeus messages (line 2381)
- 0.1s after result messages (line 2612)
- 0.2s before slot message deletions (line 2618)
- 0.1s after reset messages (line 2260)
- 0.1s after top/stats messages (line 3125, 3181, 3237)
- 0.1s after link messages (line 3181, 3237)

## Expected Output Format

### Multicast (ПРАВИЛЬНО):
```
🎲 dvarubla2

🎮 УЛУЧШЕНИЕ! +6 СМ!
🧙‍♂️ «Одного раза мало? А два раза — в самый раз!»

⚡️ МУЛЬТИКАСТ×2  12 CM

📏 8.7 см → 20.7 см
```
Нет сообщения про выходной бонус ✓
Нет лишних пустых строк ✓
Свой баннер для мультикаста ✓

### Single Roll + Weekend (ПРАВИЛЬНО):
```
🎲 dvarubla2

🎮 УЛУЧШЕНИЕ! +6 СМ!
🧙‍♂️ «Одного раза мало? А два раза — в самый раз!»

🎉 ВЫХОДНОЙ! x2.0 = 12.0 СМ

📏 8.7 см → 14.7 см
```
Выходной бонус показывается ✓
Пустая строка перед изменением фиссуры ✓

## Files Modified

1. `main.py` - Core fixes for roll calculation, message display, and session management
2. `dota_mmr.py` - Fixed async API calls to use shared session
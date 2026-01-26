# FISSURE Bot API Documentation

## Overview

This document describes the API endpoints and data structures used by the FISSURE Telegram Bot.

## Data Structures

### User Object

```typescript
interface User {
  user_id: string;           // Telegram user ID
  username: string;          // Username or full name
  level: number;             // Character level (1-30)
  hp: number;                // Current HP
  hp_max: number;            // Maximum HP
  str: number;               // Strength stat
  agi: number;               // Agility stat
  int: number;               // Intelligence stat
  gold: number;              // Gold currency
  mmr: number;               // Match Making Rating
  exp: number;               // Experience points
  items: string[];           // Array of equipped items (6 slots)
  boss_dmg: number;          // Total damage dealt to bosses
  last_pvp: number;          // Timestamp of last PvP fight
  last_heal: number;         // Timestamp of last heal
  boss_hp: number;           // Current boss HP
  boss_name: string;         // Current boss name
  boss_max: number;          // Maximum boss HP
  boss_level: number;        // Boss level
  boss_ability: string;      // Boss special ability
  fissure: number;           // Fissure length in cm
  last_fissure: number;      // Timestamp of last fissure roll
  bosses_killed: number;     // Total bosses killed
  
  // Talent system fields
  talent_points: number;     // Available talent points
  unspent_stats: number;     // Unspent stat points
  talents: object;           // Talent tree progress
  title: string;             // Player title
  total_talent_points: number; // Total spent talent points
  
  // Talent effects (calculated)
  boss_damage_bonus: number;
  double_strike_chance: number;
  berserk_damage: number;
  dodge_bonus: number;
  crit_chance_bonus: number;
  poison_damage: number;
  vanish_chance: number;
  firestorm_chance: number;
  mana_shield: number;
  resurrection_chance: number;
  all_damage_bonus: number;
  phoenix_damage: number;
}
```

### Character Stats Object

```typescript
interface CharacterStats {
  max_hp: number;           // Maximum HP
  base_damage: number;      // Base damage
  dodge_chance: number;     // Dodge chance in percent
  crit_chance: number;      // Critical hit chance in percent
  hp_regen: number;         // HP regeneration per minute in percent
  str_total: number;        // Total strength (base + items)
  agi_total: number;        // Total agility (base + items)
  int_total: number;        // Total intelligence (base + items)
  level: number;            // Character level
}
```

### Item Object

```typescript
interface Item {
  name: string;             // Item name
  gold: number;             // Purchase price
  description: string;      // Item description
  category: string;         // Item category
  
  // Optional stats
  str?: number;             // Strength bonus
  agi?: number;             // Agility bonus
  int?: number;             // Intelligence bonus
  hp?: number;              // HP bonus
  dmg?: number;             // Damage bonus
  crit?: number;            // Critical hit bonus
  dodge?: number;           // Dodge bonus
  heal?: number;            // Healing bonus
  exp?: number;             // Experience bonus
}
```

### Boss Object

```typescript
interface Boss {
  name: string;             // Boss name
  hp: number;               // Current HP
  max: number;              // Maximum HP
  dmg: [number, number];    // Damage range
  min_level: number;        // Minimum required level
  max_level: number;        // Maximum recommended level
  ability: string;          // Special ability description
  loot: string[];           // Possible loot items
}
```

## Database Queries

### User Management

#### Get User
```sql
SELECT * FROM users WHERE user_id = $1;
```

#### Create User
```sql
INSERT INTO users (user_id, username) VALUES ($1, $2);
```

#### Update User
```sql
UPDATE users SET field1 = $1, field2 = $2 WHERE user_id = $3;
```

#### Get Top Users
```sql
SELECT username, stat_name FROM users 
ORDER BY stat_name DESC 
LIMIT $1;
```

### PvP System

#### Get PvP Opponents
```sql
SELECT username, mmr, level, str, agi, int, hp, hp_max, user_id
FROM users 
WHERE user_id != $1 AND mmr >= $2
ORDER BY mmr DESC
LIMIT $3;
```

### Fissure System

#### Update Fissure
```sql
UPDATE users SET fissure = $1, last_fissure = $2 WHERE user_id = $3;
```

## Game Logic Functions

### Character Calculation

#### Calculate Character Stats
```python
def calculate_character_stats(user: Dict) -> Dict[str, int]:
    """Calculate all character statistics based on base stats and items"""
    # Returns max_hp, base_damage, dodge_chance, crit_chance, etc.
```

#### Calculate Damage
```python
def calculate_damage(user: Dict) -> Tuple[int, bool]:
    """Calculate damage with critical hit chance"""
    # Returns (damage_amount, is_critical)
```

#### Calculate Dodge
```python
def calculate_dodge(user: Dict) -> bool:
    """Check if attack is dodged based on agility"""
    # Returns True if dodged
```

### Boss System

#### Spawn Boss
```python
def spawn_boss() -> Dict:
    """Generate a new boss with random stats"""
    # Returns boss object with randomized stats
```

#### Check Level Restriction
```python
def check_level_restriction(user_level: int, boss_min: int, boss_max: int) -> bool:
    """Check if user can fight the boss based on level"""
    # Returns True if allowed
```

### Talent System

#### Check Level Up
```python
def check_level_up(user: Dict) -> Tuple[bool, Dict]:
    """Check if user can level up and return bonuses"""
    # Returns (can_level_up, bonuses_dict)
```

#### Learn Talent
```python
def can_learn_talent(user: Dict, talent_id: str) -> Tuple[bool, str]:
    """Check if user can learn a talent"""
    # Returns (can_learn, reason_if_not)
```

#### Apply Talent Effects
```python
def apply_talent_effects(user: Dict, talent_id: str, level: int) -> Dict:
    """Apply talent effects to user stats"""
    # Returns stat modifications
```

## Constants and Configuration

### Character Stats
- `BASE_HP_PER_STR = 10` - HP per strength point
- `BASE_DMG_PER_STR = 1` - Damage per strength point
- `BASE_DODGE_PER_AGI = 0.5` - Dodge % per agility point
- `BASE_CRIT_PER_AGI = 0.2` - Crit % per agility point
- `BASE_HP_REGEN_PER_INT = 0.5` - HP regen % per intelligence point

### Limits
- `MAX_LEVEL = 30` - Maximum character level
- `MAX_STAT_VALUE = 1000` - Maximum stat value
- `MAX_ITEM_SLOTS = 6` - Maximum equipped items
- `MAX_TALENT_POINTS = 30` - Maximum talent points
- `MAX_MMR = 3000` - Maximum MMR rating

### Cooldowns
- `COOLDOWN = 86400` - Fissure cooldown (24 hours)
- `PVP_COOLDOWN = 600` - PvP cooldown (10 minutes)
- `AUTO_DELETE_DELAY = 30` - Message auto-delete delay

## Error Handling

### Validation Functions

#### Validate User ID
```python
def validate_user_id(user_id: Union[str, int]) -> bool:
    """Validate Telegram user ID format and range"""
```

#### Validate Username
```python
def validate_username(username: Optional[str]) -> str:
    """Validate and sanitize username"""
```

#### Validate Item Name
```python
def validate_item_name(item_name: Optional[str]) -> bool:
    """Validate item name format"""
```

#### Validate Amount
```python
def validate_amount(amount: Union[str, int, float]) -> Optional[int]:
    """Validate numeric amounts (gold, exp, etc.)"""
```

## Performance Optimizations

### Database Pool Configuration
- Min connections: 5
- Max connections: 20
- Connection timeout: 30 seconds
- Query timeout: 10 seconds

### Caching Strategy
- User stats are calculated on-demand
- Talent trees are cached in memory
- Fissure results use random selection from predefined array

### Query Optimization
- Use parameterized queries to prevent SQL injection
- Limit result sets for leaderboards
- Batch updates when possible
- Use indexes on frequently queried fields (user_id, mmr, level)

## Security Considerations

### Input Validation
- All user inputs are validated before processing
- SQL queries use parameterized statements
- Usernames are sanitized to prevent XSS
- Numeric inputs are validated for range and type

### Rate Limiting
- Fissure rolls limited to once per 24 hours
- PvP fights limited to once per 10 minutes
- Message auto-deletion prevents spam

### Data Protection
- Sensitive data (passwords) are not stored
- User IDs are stored as strings for consistency
- No personal data is collected beyond Telegram username
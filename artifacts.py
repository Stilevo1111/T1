"""
Dota 2 Style Artifacts System (English)
"""

# Dota 2 Style Artifacts
artifacts = {
    "artifacts": {
        # Armor and Protection
        "Vanguard": {
            "🛡": 3,  # Armor
            "💰": 150,
            "🎁": "Increases armor"
        },
        "Buckler": {
            "🛡": 2,
            "💪": 1,  # Strength
            "💰": 120,
            "🎁": "Armor and strength"
        },
        "Ring of Basilius": {
            "🛡": 2,
            "🧠": 1,  # Intelligence
            "💰": 100,
            "🎁": "Aura of protection"
        },
        "Pipe of Insight": {
            "🛡": 3,
            "🧠": 2,
            "💰": 200,
            "🎁": "Magic resistance"
        },
        "Blade Mail": {
            "🛡": 2,
            "💪": 1,
            "💰": 180,
            "🎁": "Reflects damage"
        },
        
        # Evasion and Agility
        "Butterfly": {
            "🤸": 3,  # Agility
            "💰": 250,
            "🎁": "Increases evasion"
        },
        "Phase Boots": {
            "🤸": 2,
            "💰": 120,
            "🎁": "Phase movement"
        },
        "Shadow Blade": {
            "🤸": 2,
            "🎯": 1,  # Crit
            "💰": 160,
            "🎁": "Blink strike"
        },
        "Eul's Scepter": {
            "🤸": 2,
            "🧠": 2,
            "💰": 180,
            "🎁": "Cyclone magic"
        },
        "Sange": {
            "🤸": 1,
            "🛡": 1,
            "💰": 90,
            "🎁": "Physical damage"
        },
        
        # Strength and Durability
        "Heart of Tarrasque": {
            "💪": 3,
            "💰": 220,
            "🎁": "Massive strength"
        },
        "Vladmir's Offering": {
            "💪": 2,
            "🧠": 1,
            "💰": 140,
            "🎁": "Lifesteal aura"
        },
        "Hood of Defiance": {
            "💪": 1,
            "🧠": 2,
            "💰": 130,
            "🎁": "Magic resistance"
        },
        "Crimson Guard": {
            "💪": 2,
            "🛡": 2,
            "💰": 200,
            "🎁": "Damage reduction"
        },
        "Abyssal Blade": {
            "💪": 2,
            "🎯": 1,
            "💰": 200,
            "🎁": "Stun attack"
        },
        
        # Intelligence and Magic
        "Aghanim's Scepter": {
            "🧠": 3,
            "💰": 200,
            "🎁": "Ultimate upgrade"
        },
        "Scythe of Vyse": {
            "🧠": 3,
            "💰": 240,
            "🎁": "Hex control"
        },
        "Rod of Atos": {
            "🧠": 2,
            "💪": 1,
            "💰": 160,
            "🎁": "Root enemy"
        },
        "Gleipnir": {
            "🧠": 2,
            "💰": 180,
            "🎁": "Chain lightning"
        },
        "Mekansm": {
            "🧠": 1,
            "💪": 1,
            "💰": 110,
            "🎁": "Healing aura"
        },
        
        # Crit and Damage
        "Monkey King Bar": {
            "🎯": 3,
            "💰": 240,
            "🎁": "True damage crit"
        },
        "Daedalus": {
            "🎯": 3,
            "💰": 220,
            "🎁": "Critical damage"
        },
        "Buriza": {
            "🎯": 2,
            "💰": 180,
            "🎁": "Armor pierce"
        },
        "Mjollnir": {
            "🎯": 2,
            "🧠": 1,
            "💰": 190,
            "🎁": "Chain lightning"
        },
        "Sange-Yasha": {
            "🎯": 1,
            "🤸": 1,
            "💰": 150,
            "🎁": "Attack speed"
        },
        
        # Universal Items
        "Black King Bar": {
            "💪": 2,
            "🧠": 2,
            "🛡": 1,
            "💰": 280,
            "🎁": "Magic immunity"
        },
        "Linken's Sphere": {
            "🧠": 2,
            "💪": 1,
            "🛡": 1,
            "💰": 220,
            "🎁": "Spell block"
        },
        "Octarine Core": {
            "💪": 2,
            "🧠": 2,
            "💰": 300,
            "🎁": "Cooldown reduction"
        },
        "Euls": {
            "🧠": 2,
            "🤸": 1,
            "💰": 160,
            "🎁": "Cyclone"
        },
        "Manta Style": {
            "🤸": 2,
            "💰": 180,
            "🎁": "Mirror images"
        },
        
        # Utility Items
        "Town Portal Scroll": {
            "🧠": 1,
            "💰": 50,
            "🎁": "Teleportation"
        },
        "Observer Wards": {
            "🧠": 1,
            "💰": 30,
            "🎁": "Vision"
        },
        "Sentry Wards": {
            "🧠": 1,
            "💰": 40,
            "🎁": "Anti-invis"
        },
        "Dust of Appearance": {
            "🧠": 1,
            "💰": 60,
            "🎁": "Reveal invis"
        },
        "Smoke of Deceit": {
            "🧠": 1,
            "💰": 50,
            "🎁": "Movement speed"
        },
        
        # High Tier Items
        "Divine Rapier": {
            "🎯": 4,
            "💰": 350,
            "🎁": "Ultimate damage"
        },
        "Aghanim's Shard": {
            "🧠": 1,
            "💪": 1,
            "🤸": 1,
            "💰": 150,
            "🎁": "Item upgrade"
        },
        "Orchid Malevolence": {
            "🧠": 2,
            "💰": 180,
            "🎁": "Silence enemy"
        },
        "Bloodthorn": {
            "🧠": 2,
            "🎯": 1,
            "💰": 200,
            "🎁": "True sight"
        },
        "Hurricane Pike": {
            "🧠": 1,
            "💪": 1,
            "💰": 170,
            "🎁": "Push enemy"
        }
    }
}

def get_all_artifacts():
    """Get all available artifacts"""
    return artifacts["artifacts"]

def get_artifact_info(name):
    """Get artifact info by name"""
    return artifacts["artifacts"].get(name)

def format_artifact_description(name, data):
    """Format artifact description"""
    text = f"**{name}**\n"
    for key, value in data.items():
        if key == "💰":
            text += f"  💰 {value} MMR\n"
        elif key == "🎁":
            text += f"  🎁 {value}\n"
        else:
            text += f"  {key}: {value}\n"
    return text
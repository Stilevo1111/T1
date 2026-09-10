#!/usr/bin/env python3
"""Simulate hero meta table display - final verification."""

def print_hero_table():
    # Simulated data showing the separation of concerns
    print("=" * 80)
    print("HERO META TABLE - BEST PLAYERS THIS WEEK")
    print("=" * 80)
    print()
    
    # Example: 5 heroes with different scenarios
    heroes_data = [
        {
            'name': 'Invoker',
            'role': 'MID',
            # Aggregate hero stats (ALL players on hero in last 7 days)
            'pub_pick': 100,    # ALL players: 100 games
            'pub_win': 60,      # ALL players: 60 wins
            'agg_winrate': 0.60, # 60% aggregate
            # Best player stats (their games ON THIS HERO in last 7 days)
            'player_games': 5,  # Best player: 5 games on Invoker
            'player_wins': 5,   # Best player: 5 wins on Invoker
            'player_winrate': 100, # Best player: 100% on Invoker
            'has_player_data': True,
        },
        {
            'name': 'Pudge',
            'role': 'SUPPORT',
            'pub_pick': 50,     # ALL players: 50 games
            'pub_win': 40,      # ALL players: 40 wins
            'agg_winrate': 0.80, # 80% aggregate
            'player_games': 3,
            'player_wins': 2,
            'player_winrate': 66, # Best player: 66% on Pudge
            'has_player_data': True,
        },
        {
            'name': 'Anti-Mage',
            'role': 'CARRY',
            'pub_pick': 200,    # ALL players: 200 games
            'pub_win': 90,      # ALL players: 90 wins
            'agg_winrate': 0.45, # 45% aggregate
            'player_games': 10,
            'player_wins': 8,
            'player_winrate': 80,
            'has_player_data': True,
        },
        {
            'name': 'Crystal Maiden',
            'role': 'SUPPORT',
            'pub_pick': 80,
            'pub_win': 24,
            'agg_winrate': 0.30, # 30% aggregate
            'player_games': 0,    # No player data for this hero
            'player_wins': 0,
            'player_winrate': 0,
            'has_player_data': False,
        },
        {
            'name': 'Lina',
            'role': 'MID',
            'pub_pick': 75,
            'pub_win': 45,
            'agg_winrate': 0.60, # 60% aggregate
            'player_games': 8,
            'player_wins': 5,
            'player_winrate': 62,
            'has_player_data': True,
        },
    ]
    
    # Calculate rankings by AGGREGATE stats (not player stats!)
    def sort_key(h):
        has_data = h.get('has_player_data', False)
        no_data_penalty = 0 if has_data else 1
        agg_wr = h.get('agg_winrate', 0) or 0
        games = h.get('pub_pick', 0) or 0
        wins = h.get('pub_win', 0) or 0
        name = h.get('name', '') or ''
        winrate_pct = round(agg_wr * 100, 1)
        return (no_data_penalty, -winrate_pct, -games, -wins, name)
    
    # Group by position
    from collections import defaultdict
    by_position = defaultdict(list)
    for h in heroes_data:
        by_position[h['role']].append(h)
    
    # Position names
    pos_names = {
        'CARRY': '1. SAFE LANE',
        'MID': '2. MID LANE', 
        'SUPPORT': '4. SOFT SUPP / 5. HARD SUPP'
    }
    
    # Print table
    for pos in ['CARRY', 'MID', 'SUPPORT']:
        if pos not in by_position:
            continue
        
        position_name = pos_names.get(pos, pos)
        print(f"=== {position_name} ===")
        print()
        print(f"{'Hero':<20} {'W/L%':<10} {'Games':<8} {'Best Player Avatar':<25}")
        print("-" * 80)
        
        # Sort heroes in this position
        sorted_heroes = sorted(by_position[pos], key=sort_key)
        
        for h in sorted_heroes:
            wins = h['pub_win']
            losses = h['pub_pick'] - wins
            wr = round(h['agg_winrate'] * 100)
            
            # Avatar info
            if h['has_player_data'] and h['player_games'] > 0:
                avatar_info = f"[{h['player_wins']}/{h['player_games']}, {h['player_winrate']}%, BEST]"
            else:
                avatar_info = "[No player data]"
            
            print(f"{h['name']:<20} {wins}W/{losses}L/{wr}%{'':<3} {h['pub_pick']:<6} {avatar_info}")
        
        print()
    
    print("=" * 80)
    print("LEGEND:")
    print("  W/L% = hero_games_7d / hero_wins_7d (AGGREGATE over all players)")
    print("  Best Player Avatar = top player on this hero (last 7 days)")
    print()
    print("CRITICAL RULES:")
    print("  1. SORTING uses AGGREGATE stats (pub_pick/pub_win)")
    print("  2. AVATAR uses BEST PLAYER stats (games/wins on hero)")
    print("  3. Invoker with 60% aggregate ranks below Pudge with 80% aggregate")
    print("  4. Even though Invoker's best player has 100%!")
    print("=" * 80)


if __name__ == "__main__":
    print_hero_table()
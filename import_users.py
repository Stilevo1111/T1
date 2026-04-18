import csv
import os
import psycopg2
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not set!")
    exit(1)

CSV_FILE = "C:/Users/akado/Downloads/users.csv"

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

imported = 0
skipped = 0

with open(CSV_FILE, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    
    for row in reader:
        try:
            telegram_id = int(row['telegram_id'])
            if telegram_id < 1000:
                skipped += 1
                continue
            
            username = row['username'] if row['username'] else None
            if username == '':
                username = None
            
            fissure = float(row['fissure']) if row['fissure'] else 0.1
            last_fissure = float(row['last_fissure']) if row['last_fissure'] else 0
            last_message_id = int(row['last_message_id']) if row['last_message_id'] else 0
            total_growth = float(row['total_growth']) if row['total_growth'] else 0
            total_rolls = int(row['total_rolls']) if row['total_rolls'] else 0
            current_streak = int(row['current_streak']) if row['current_streak'] else 0
            best_streak = int(row['best_streak']) if row['best_streak'] else 0
            current_position = int(row['current_position']) if row['current_position'] else 0
            digest_position = int(row['digest_position']) if row['digest_position'] else 0
            digest_fissure = float(row['digest_fissure']) if row['digest_fissure'] else 0
            
            steam_id = int(row['steam_id']) if row['steam_id'] and row['steam_id'] != '' else None
            steam_nickname = row['steam_nickname'] if row['steam_nickname'] else None
            if steam_nickname == '':
                steam_nickname = None
            
            mmr = int(row['mmr']) if row['mmr'] else 0
            dota_total_games = int(row['dota_total_games']) if row['dota_total_games'] else 0
            dota_wins = int(row['dota_wins']) if row['dota_wins'] else 0
            week_games = int(row['week_games']) if row['week_games'] else 0
            week_wins = int(row['week_wins']) if row['week_wins'] else 0
            week_updated_at = row['week_updated_at'] if row['week_updated_at'] else None
            mmr_updated_at = row['mmr_updated_at'] if row['mmr_updated_at'] else None
            rank_tier = int(row['rank_tier']) if row['rank_tier'] else 0
            wins = int(row['wins']) if row['wins'] else 0
            losses = int(row['losses']) if row['losses'] else 0
            last_match_id = int(row['last_match_id']) if row['last_match_id'] and row['last_match_id'] != '0' else None
            last_dota_wins = int(row['last_dota_wins']) if row['last_dota_wins'] else 0
            week_start_date = row['week_start_date'] if row['week_start_date'] else None
            week_best_streak = int(row['week_best_streak']) if row['week_best_streak'] else 0
            week_current_streak = int(row['week_current_streak']) if row['week_current_streak'] else 0
            in_chat = row['in_chat'].lower() == 'true' if row['in_chat'] else False
            
            cursor.execute("""
                INSERT INTO users (
                    telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls,
                    current_streak, best_streak, current_position, digest_position, digest_fissure,
                    steam_id, steam_nickname, mmr, dota_total_games, dota_wins,
                    week_games, week_wins, rank_tier, wins, losses, last_match_id, last_dota_wins,
                    week_start_date, week_best_streak, week_current_streak, in_chat
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                ) ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    fissure = EXCLUDED.fissure,
                    last_fissure = EXCLUDED.last_fissure,
                    last_message_id = EXCLUDED.last_message_id,
                    total_growth = EXCLUDED.total_growth,
                    total_rolls = EXCLUDED.total_rolls,
                    current_streak = EXCLUDED.current_streak,
                    best_streak = EXCLUDED.best_streak,
                    current_position = EXCLUDED.current_position,
                    digest_position = EXCLUDED.digest_position,
                    digest_fissure = EXCLUDED.digest_fissure,
                    steam_id = EXCLUDED.steam_id,
                    steam_nickname = EXCLUDED.steam_nickname,
                    mmr = EXCLUDED.mmr,
                    dota_total_games = EXCLUDED.dota_total_games,
                    dota_wins = EXCLUDED.dota_wins,
                    week_games = EXCLUDED.week_games,
                    week_wins = EXCLUDED.week_wins,
                    rank_tier = EXCLUDED.rank_tier,
                    wins = EXCLUDED.wins,
                    losses = EXCLUDED.losses,
                    last_match_id = EXCLUDED.last_match_id,
                    last_dota_wins = EXCLUDED.last_dota_wins,
                    week_start_date = EXCLUDED.week_start_date,
                    week_best_streak = EXCLUDED.week_best_streak,
                    week_current_streak = EXCLUDED.week_current_streak,
                    in_chat = EXCLUDED.in_chat
            """, (
                telegram_id, username, fissure, last_fissure, last_message_id, total_growth, total_rolls,
                current_streak, best_streak, current_position, digest_position, digest_fissure,
                steam_id, steam_nickname, mmr, dota_total_games, dota_wins,
                week_games, week_wins, rank_tier, wins, losses, last_match_id, last_dota_wins,
                week_start_date, week_best_streak, week_current_streak, in_chat
            ))
            
            imported += 1
            
        except Exception as e:
            print(f"Error importing row {row.get('telegram_id', '?')}: {e}")
            continue

conn.commit()
cursor.close()
conn.close()

print(f"Imported: {imported}")
print(f"Skipped: {skipped}")
import sys
sys.stdout.reconfigure(encoding='utf-8')
from database import get_connection
conn = get_connection()
try:
    conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS message_count INTEGER DEFAULT 0')
    conn.commit()
    print("Done")
except Exception as e:
    print(f"Error: {e}")
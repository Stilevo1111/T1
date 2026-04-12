import os
import io
from contextlib import redirect_stdout, redirect_stderr

os.environ['DATABASE_URL'] = 'postgresql://postgres:ep-patient-hat-aij7zufv@containers-us-west-158.railway.internal:7652/railway'

null = io.StringIO()
with redirect_stdout(null), redirect_stderr(null):
    from database import init_db, get_connection

init_db()
conn = get_connection()
cursor = conn.cursor()

users = ['dvarubla2', 'distreet666', 'PathetIIIcC']
results = []
for username in users:
    cursor.execute('SELECT telegram_id, username FROM users WHERE LOWER(username) = LOWER(%s)', (username,))
    row = cursor.fetchone()
    if row:
        results.append(row[1] + '|' + str(row[0]))
    else:
        results.append('NOTFOUND:' + username)
conn.close()

with open('result.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(results))
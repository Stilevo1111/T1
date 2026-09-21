import inspect
import sys
sys.path.insert(0, '.')
import dota_mmr

src = inspect.getsource(dota_mmr.generate_profile_card)
banned = ['MMR"', 'ПРОГРЕСС ЗВАНИЯ', 'ПРОГРЕСС ДО СЛЕДУЮЩЕГО ЗВАНИЯ', 'звёзд звания', '_profile_bottom_captions']
for b in banned:
    if b in src:
        print(f'FOUND: {b}')
    else:
        print(f'OK: {b}')

print(f'"Всего сообщений" in src: {"Всего сообщений" in src}')
print(f'"Герои недели".lower() in src.lower(): {"герои" in src.lower()}')
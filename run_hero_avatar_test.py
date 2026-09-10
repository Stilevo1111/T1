import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
exec(open(Path(__file__).resolve().parent / 'scripts' / 'test_hero_avatars.py', encoding='utf-8').read())

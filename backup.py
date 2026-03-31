#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skript dlya sozdaniya rezervnoj kопии bazy dannyh boa "Fissura"
 
Ispolzovanie:
    python backup.py                          # Sozdati rezervnuyu kopiyu
    python backup.py --restore backup.sql.gz  # Vosstanovit iz szhatoj kопии
    python backup.py --list                   # Pokazat spisok rezervnyh kopij
    python backup.py --keep 5                 # Sozdat backup + udalit starye (ostavit 5)
    python backup.py --db "postgresql://..."   # Ukazat DATABASE_URL
    python backup.py --no-compress             # Bez szhatiya dlya PostgreSQL
"""

import os
import sys
import gzip
import shutil
import argparse
from datetime import datetime

# Add UTF-8 encoding for Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def list_backups(backup_dir=None, db_type=None):
    """Показать список резервных копий"""
    if backup_dir is None:
        backup_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Esli db_type ne ukazan, opredelyaem avtomaticheski
    if db_type is None:
        from database import get_db_type
        db_type = get_db_type()
    
    extensions = []
    if db_type == "sqlite":
        extensions.append(".db")
    else:
        extensions.extend([".sql", ".sql.gz"])
    
    backups = []
    for f in os.listdir(backup_dir):
        if not f.startswith("fissure_bot_backup_"):
            continue
        if not any(f.endswith(ext) for ext in extensions):
            continue
        path = os.path.join(backup_dir, f)
        size = os.path.getsize(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path))
        backups.append({
            "name": f,
            "path": path,
            "size": size,
            "date": mtime
        })
    
    # Sortiruemy po date (novye first)
    backups.sort(key=lambda x: x["date"], reverse=True)
    
    return backups

def rotate_backups(backup_dir, db_type, keep):
    """Удалить старые бэкапы, оставив только keep штук"""
    backups = list_backups(backup_dir, db_type)
    
    if len(backups) <= keep:
        return 0
    
    to_delete = backups[keep:]
    deleted = 0
    
    for b in to_delete:
        try:
            os.remove(b["path"])
            print(f"[DELETE] Udalён: {b['name']}")
            deleted += 1
        except OSError as e:
            print(f"[ERROR] Ne udalos udalit {b['name']}: {e}")
    
    return deleted

def compress_backup(backup_path):
    """Сжать файл бэкапа с помощью gzip, вернуть путь к .gz файлу"""
    gz_path = backup_path + ".gz"
    
    with open(backup_path, "rb") as f_in:
        with gzip.GzipFile(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    original_size = os.path.getsize(backup_path)
    compressed_size = os.path.getsize(gz_path)
    
    os.remove(backup_path)
    
    ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
    print(f"[GZIP] Szhat: {os.path.basename(gz_path)} ({ratio:.0f}% economiya)")
    
    return gz_path

def decompress_backup(gz_path):
    """Расжать .gz файл во временный файл, вернуть путь"""
    import tempfile
    
    if not gz_path.endswith(".gz"):
        return gz_path
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".sql")
    tmp.close()
    
    with gzip.GzipFile(gz_path, "rb") as f_in:
        with open(tmp.name, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    return tmp.name

def format_size(size_bytes):
    """Форматировать размер файла в человекочитаемый вид"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

def main():
    parser = argparse.ArgumentParser(description="Upravlenie rezervnymi kopiyami bazy dannyh")
    parser.add_argument("--restore", metavar="FILE", help="Vosstanovit bazu dannyh iz rezervnoj kopii")
    parser.add_argument("--list", action="store_true", help="Pokazat spisok rezervnyh kopij")
    parser.add_argument("--dir", metavar="DIR", default=None, help="Direktoriya dlya rezervnyh kopij")
    parser.add_argument("--db", metavar="URL", default=None, help="DATABASE_URL dlya podklyucheniya k PostgreSQL")
    parser.add_argument("--keep", metavar="N", type=int, default=None, help="Hranit tolko N poslednih rezervnyh kopij (udalit starye)")
    parser.add_argument("--no-compress", action="store_true", help="Ne szhimat backup dlya PostgreSQL")
    
    args = parser.parse_args()
    
    # Esli ukazan DATABASE_URL, ispolzuem ego PERED importom database
    if args.db:
        os.environ["DATABASE_URL"] = args.db
    
    # Teper importiruem moduli bazy dannyh -.posle obrabotki argumentov
    from database import backup_database, restore_database, get_db_type
    
    if args.restore:
        # Vosstanovlenie
        restore_file = args.restore
        
        # Esli eto .gz - raspozhimaem
        if restore_file.endswith(".gz"):
            print(f"[GZIP] Raspozhimayu: {restore_file}")
            restore_file = decompress_backup(restore_file)
            cleanup_tmp = True
        else:
            cleanup_tmp = False
        
        print(f"[RESTORE] vosstanovlenie iz: {args.restore}")
        success = restore_database(restore_file)
        
        if cleanup_tmp and os.path.exists(restore_file):
            os.remove(restore_file)
        
        if success:
            print("[OK] Vosstanovlenie zaversheno uspeshno!")
            return 0
        else:
            print("[ERROR] Oshibka vosstanovleniya")
            return 1
    
    if args.list:
        # Spisok rezervnyh kopij
        db_type = get_db_type()
        backups = list_backups(args.dir, db_type)
        if not backups:
            print("[INFO] Rezervnye kopii ne najdeny")
            return 0
            
        print(f"[INFO] Rezervnye kopii (vsego: {len(backups)}):\n")
        for b in backups:
            print(f"  [FILE] {b['name']}")
            print(f"     Size: {format_size(b['size'])}")
            print(f"     Date: {b['date'].strftime('%Y-%m-%d %H:%M:%S')}\n")
        return 0
    
    # Sozdanie rezervnoj kопии po umolchaniyu
    print("[INFO] Sozdanie rezervnoj kопии bazy dannyh...\n")
    backup_path = backup_database(args.dir)
    
    if backup_path:
        # Szhatie dlya PostgreSQL (.sql -> .sql.gz)
        db_type = get_db_type()
        if db_type == "postgresql" and not args.no_compress and not backup_path.endswith(".gz"):
            backup_path = compress_backup(backup_path)
        
        # Rotaciya staryh bakoov
        if args.keep is not None and args.keep > 0:
            deleted = rotate_backups(args.dir, db_type, args.keep)
            if deleted > 0:
                print(f"[ROTATE] Udaleno staryh bakoov: {deleted}")
        
        print(f"\n[OK] Rezervnaya kopiya sozdana!")
        print(f"   Path: {backup_path}")
        print(f"   Size: {format_size(os.path.getsize(backup_path))}")
        return 0
    else:
        print("\n[ERROR] Oshibka sozdaniya rezervnoj kопии")
        return 1

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skript dlya sozdaniya rezervnoj kопии bazy dannyh boa "Fissura"

Ispolzovanie:
    python backup.py                      # Sozdati rezervnuyu kopiyu
    python backup.py --restore backup.db  # Vosstanovit iz rezervnoj kопии
    python backup.py --list                # Pokazat spisok rezervnyh kopij
    python backup.py --db "postgresql://..."  # Ukazat DATABASE_URL
"""

import os
import sys
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
    
    extension = ".db" if db_type == "sqlite" else ".sql"
    
    backups = []
    for f in os.listdir(backup_dir):
        if f.startswith("fissure_bot_backup_") and f.endswith(extension):
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

def main():
    parser = argparse.ArgumentParser(description="Upravlenie rezervnymi kopiyami bazy dannyh")
    parser.add_argument("--restore", metavar="FILE", help="Vosstanovit bazu dannyh iz rezervnoj kopii")
    parser.add_argument("--list", action="store_true", help="Pokazat spisok rezervnyh kopij")
    parser.add_argument("--dir", metavar="DIR", default=None, help="Direktoriya dlya rezervnyh kopij")
    parser.add_argument("--db", metavar="URL", default=None, help="DATABASE_URL dlya podklyucheniya k PostgreSQL")
    
    args = parser.parse_args()
    
    # Esli ukazan DATABASE_URL, ispolzuem ego PERED importom database
    if args.db:
        os.environ["DATABASE_URL"] = args.db
    
    # Teper importiruem moduli bazy dannyh -.posle obrabotki argumentov
    from database import backup_database, restore_database, get_db_type
    
    if args.restore:
        # Vosstanovlenie
        print(f"[RESTORE] vosstanovlenie iz: {args.restore}")
        success = restore_database(args.restore)
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
            size_kb = b["size"] / 1024
            print(f"  [FILE] {b['name']}")
            print(f"     Size: {size_kb:.1f} KB")
            print(f"     Date: {b['date'].strftime('%Y-%m-%d %H:%M:%S')}\n")
        return 0
    
    # Sozdanie rezervnoj kопии по умолчанию
    print("[INFO] Sozdanie rezervnoj kопии bazy dannyh...\n")
    backup_path = backup_database(args.dir)
    
    if backup_path:
        print(f"\n[OK] Rezervnaya kopiya sozdana!")
        print(f"   Path: {backup_path}")
        return 0
    else:
        print("\n[ERROR] Oshibka sozdaniya rezervnoj kопии")
        return 1

if __name__ == "__main__":
    sys.exit(main())

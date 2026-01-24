# database.py
import os
import json
import psycopg2
from psycopg2.extras import Json

DATABASE_URL = os.getenv("DATABASE_URL")

class Database:
    def __init__(self):
        self.use_postgres = DATABASE_URL is not None
        if self.use_postgres:
            try:
                self.conn = psycopg2.connect(DATABASE_URL)
                self.create_table()
                print("✅ Подключено к PostgreSQL")
            except Exception as e:
                print(f"❌ Ошибка подключения к PostgreSQL: {e}")
                print("⚠️ Переключаюсь на JSON файл")
                self.use_postgres = False
        
        if not self.use_postgres:
            self.data_file = "data.json"
            print("✅ Используется JSON файл для хранения")
    
    def create_table(self):
        """Создать таблицу если не существует"""
        if not self.use_postgres:
            return
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    data JSONB NOT NULL
                )
            """)
            self.conn.commit()
            cursor.close()
        except Exception as e:
            print(f"Ошибка создания таблицы: {e}")
    
    def load_all(self):
        """Загрузить всех пользователей"""
        if self.use_postgres:
            try:
                cursor = self.conn.cursor()
                cursor.execute("SELECT user_id, data FROM users")
                rows = cursor.fetchall()
                cursor.close()
                
                users = {}
                for user_id, data in rows:
                    users[user_id] = data
                return users
            except Exception as e:
                print(f"Ошибка загрузки из PostgreSQL: {e}")
                return {}
        else:
            # JSON файл
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return {}
    
    def save_user(self, user_id, data):
        """Сохранить данные пользователя"""
        user_id = str(user_id)
        
        if self.use_postgres:
            try:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO users (user_id, data)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET data = EXCLUDED.data
                """, (user_id, Json(data)))
                self.conn.commit()
                cursor.close()
            except Exception as e:
                print(f"Ошибка сохранения в PostgreSQL: {e}")
        else:
            # JSON файл
            users = self.load_all()
            users[user_id] = data
            try:
                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Ошибка сохранения в JSON: {e}")
    
    def save_all(self, users):
        """Сохранить всех пользователей (для совместимости)"""
        if self.use_postgres:
            for user_id, data in users.items():
                self.save_user(user_id, data)
        else:
            try:
                with open(self.data_file, "w", encoding="utf-8") as f:
                    json.dump(users, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Ошибка сохранения в JSON: {e}")
    
    def close(self):
        """Закрыть соединение"""
        if self.use_postgres and hasattr(self, 'conn'):
            self.conn.close()

# Глобальный экземпляр
db = Database()

-- Add analytics cache columns to users table
ALTER TABLE users ADD COLUMN analytics_cache TEXT;
ALTER TABLE users ADD COLUMN analytics_updated_at TEXT;
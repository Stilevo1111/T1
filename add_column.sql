-- Add message_count column for PostgreSQL
ALTER TABLE users ADD COLUMN IF NOT EXISTS message_count INTEGER DEFAULT 0;
-- Or for older PostgreSQL without IF NOT EXISTS support:
-- ALTER TABLE users ADD COLUMN message_count INTEGER DEFAULT 0;
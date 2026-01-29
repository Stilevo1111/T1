# Alembic Migrations

This directory contains database migration scripts for the fissure-bot project.

## Usage

### Initialize the database (first time only)
```bash
python -m alembic upgrade head
```

### Create a new migration
```bash
python -m alembic revision --autogenerate -m "Description of changes"
```

### Apply migrations
```bash
python -m alembic upgrade head
```

### Rollback last migration
```bash
python -m alembic downgrade -1
```

### Check current migration status
```bash
python -m alembic current
```

## Migration Files

- `env.py`: Configuration for Alembic environment
- `script.py.mako`: Template for generating migration scripts
- `versions/`: Directory containing individual migration files

## Database URL

The database URL is automatically detected from the `DATABASE_URL` environment variable or can be set in `alembic.ini`.
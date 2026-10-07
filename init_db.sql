-- Enables the extensions this project needs. SQLAlchemy (app/db.py) creates
-- the actual tables on startup, so this file only needs to set up the
-- Postgres extensions ahead of that.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

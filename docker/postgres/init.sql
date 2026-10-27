-- Run by the pgvector/pgvector Docker image on first startup.
-- Installs the pgvector extension so Alembic migrations can use Vector columns.
CREATE EXTENSION IF NOT EXISTS vector;

-- Create dedicated test database and install vector extension on it
SELECT 'CREATE DATABASE swarnbharat_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'swarnbharat_test')\gexec

\c swarnbharat_test
CREATE EXTENSION IF NOT EXISTS vector;

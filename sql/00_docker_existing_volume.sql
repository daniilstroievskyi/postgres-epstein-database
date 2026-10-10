-- Repair a Docker volume initialized with the earlier z1_user/z1 settings.
-- Run through psql inside the container as the existing administrator z1_user.
-- The password comes from the container environment and is never hard-coded.
-- The new login is not a superuser; database ownership permits schema imports.
-- Existing roles, databases, and data are preserved. Repeated runs skip objects
-- that already exist without changing their passwords, privileges, or owners.
-- Run outside a transaction because CREATE DATABASE cannot run in one.

\set ON_ERROR_STOP on
\getenv configured_password POSTGRES_PASSWORD

SELECT format(
    'CREATE ROLE postgres LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
    :'configured_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres')
\gexec

SELECT 'CREATE DATABASE dbs2 OWNER postgres'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'dbs2')
\gexec

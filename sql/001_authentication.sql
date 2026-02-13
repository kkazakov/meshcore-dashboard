-- 001_authentication.sql
-- Creates the users table for API authentication.
-- Engine: ReplacingMergeTree (deduplicates by email on merge).

CREATE TABLE IF NOT EXISTS users
(
    email         String,
    password_hash String,   -- bcrypt hash of the user's password
    username      String,
    active        Bool      DEFAULT true,
    access_rights String    DEFAULT '',
    updated_at    DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY email;

-- Seed: admin / admin (password is bcrypt-hashed)
INSERT INTO users (email, password_hash, username, active, access_rights)
VALUES (
    'admin@example.com',
    '$2b$12$anP.RAuPjeyuo.QEyYiZouOICisaPk/KZ1ge5DhxF45uF8G08Rh5q',
    'admin',
    true,
    ''
);

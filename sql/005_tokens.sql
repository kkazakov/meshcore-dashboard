-- 005_tokens.sql
-- Creates the tokens table for session management across multiple workers.
-- Engine: ReplacingMergeTree (deduplicates by token on merge).

CREATE TABLE IF NOT EXISTS tokens
(
    token     String,          -- 64-char hex token
    email     String,          -- user email from users table
    created_at DateTime64(3, 'UTC') DEFAULT now64(),
    expires_at DateTime64(3, 'UTC') -- token expiration time
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY token
TTL expires_at DELETE;

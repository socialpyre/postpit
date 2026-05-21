-- Instagram-specific schema: identities + OAuth state + IG columns on posts.

CREATE TABLE accounts (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL,
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  account_type TEXT NOT NULL DEFAULT 'BUSINESS'
);

CREATE TABLE oauth_codes (
  code TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  state TEXT NOT NULL,
  issued_at TEXT NOT NULL
);

CREATE TABLE oauth_tokens (
  token TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL
);

ALTER TABLE posts ADD COLUMN container_id TEXT;
ALTER TABLE posts ADD COLUMN platform_post_id TEXT;
ALTER TABLE posts ADD COLUMN image_url TEXT;

CREATE INDEX idx_posts_container_id ON posts (container_id);

-- Seed two default mock accounts. INSERT runs exactly once on first install
-- (migration 0001 records its application in schema_version); if the user
-- later deletes a seed row, it stays deleted across reboots.
INSERT INTO accounts (id, username, display_name, avatar_url, account_type)
  VALUES ('178414000000001', 'test_studio', 'Test Studio',
    'https://picsum.photos/seed/posthole-studio/256/256', 'BUSINESS');
INSERT INTO accounts (id, username, display_name, avatar_url, account_type)
  VALUES ('178414000000002', 'test_artist', 'Test Artist',
    'https://picsum.photos/seed/posthole-artist/256/256', 'BUSINESS');

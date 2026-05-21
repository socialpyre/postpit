-- Multi-platform groundwork: generalize IG-shaped column names and add
-- per-platform scoping for accounts ahead of TikTok landing as platform #2.

-- The IG-Graph-shaped columns generalize poorly to TikTok's video-first
-- flow. Rename now (one DB, one user) so each platform stores into a
-- vocabulary they share.
ALTER TABLE posts RENAME COLUMN image_url TO media_url;
ALTER TABLE posts RENAME COLUMN container_id TO external_ref;
ALTER TABLE posts ADD COLUMN media_type TEXT;

-- Each platform's OAuth picker should list only its own accounts. The
-- existing oauth_codes / oauth_tokens tables stay platform-agnostic —
-- tokens are opaque, so platform discrimination happens via the account
-- row each token references.
ALTER TABLE accounts ADD COLUMN platform TEXT NOT NULL DEFAULT 'instagram';
CREATE INDEX idx_accounts_platform ON accounts (platform);

-- Backfill IG seed accounts' platform (the DEFAULT 'instagram' already
-- handles this for existing rows; explicit UPDATE is a no-op but makes
-- intent obvious to future readers).
UPDATE accounts SET platform = 'instagram' WHERE platform = 'instagram';

-- Seed two TikTok mock accounts. IDs use TikTok's open_id-style prefix
-- so they're visually distinct from IG's numeric IDs at a glance.
INSERT INTO accounts (id, username, display_name, avatar_url, account_type, platform)
  VALUES ('tt-7000000000000000001', 'test_creator', 'Test Creator',
    'https://picsum.photos/seed/posthole-creator/256/256', 'CREATOR_ACCOUNT', 'tiktok');
INSERT INTO accounts (id, username, display_name, avatar_url, account_type, platform)
  VALUES ('tt-7000000000000000002', 'test_brand', 'Test Brand',
    'https://picsum.photos/seed/posthole-brand/256/256', 'BUSINESS_ACCOUNT', 'tiktok');

-- Container-state extensions: realistic polling, failure injection,
-- EXPIRED status, and carousel support.
--
-- IG-Graph containers move through status codes (IN_PROGRESS → FINISHED |
-- ERROR | EXPIRED) and parent CAROUSEL containers reference an ordered list
-- of child IMAGE/VIDEO containers. Phase 1 hard-coded "always FINISHED" and
-- IMAGE-only; this migration lights up the rest of the surface so Pyre can
-- exercise the full publishing flow end-to-end.

-- Status of the container itself (separate from posts.status, which tracks
-- pending|published|failed at the post lifecycle). Mirrors IG-Graph's
-- ``status_code`` field. Default IN_PROGRESS so newly inserted containers
-- start at the bottom of the polling ramp; the route flips it as polls
-- accumulate.
ALTER TABLE posts ADD COLUMN container_status TEXT NOT NULL DEFAULT 'IN_PROGRESS';

-- Polling counter — incremented on each GET /{container_id}. When it
-- reaches ``poll_threshold`` (default 0 == immediately FINISHED), the
-- container flips to FINISHED. This keeps the default behavior identical
-- to phase 1; tests that need a slower ramp set the threshold at create
-- time.
ALTER TABLE posts ADD COLUMN poll_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE posts ADD COLUMN poll_threshold INTEGER NOT NULL DEFAULT 0;

-- Failure injection — when set to one of the recognized kinds
-- (rate_limited, media_unreachable, auth_revoked, expired, publish_error),
-- the next IG call against this container raises the matching exception
-- instead of returning normally. Set via the caption sentinel
-- ``[posthole:fail=<kind>]`` (stripped from the persisted caption) or via
-- the ``X-Posthole-Inject-Failure`` header on the request that creates
-- the container.
ALTER TABLE posts ADD COLUMN inject_next_failure_kind TEXT;

-- Carousel support — when a container's ``is_carousel_item=1``, it's a
-- child slot in some parent's carousel and cannot be published directly.
-- The parent's ``child_container_ids`` is a comma-separated list of
-- child external_refs in display order.
ALTER TABLE posts ADD COLUMN is_carousel_item INTEGER NOT NULL DEFAULT 0;
ALTER TABLE posts ADD COLUMN child_container_ids TEXT;

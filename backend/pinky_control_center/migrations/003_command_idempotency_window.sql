-- Commands are audit records. Request IDs are only an idempotency key for 24 hours.
DROP INDEX IF EXISTS command_request_user;
CREATE INDEX IF NOT EXISTS command_request_lookup ON commands(user_id, request_id, created_at DESC);

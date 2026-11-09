-- Signed-in home: one receipt per action a person takes from the home (lane H1b).
--
-- POST /api/v1/home/actions/{source}/{item_id}/{action} (backend/home/actions.py)
-- forwards approve, reject, accept or done to the app that owns the item, with
-- the person's own token, and records the result here. The row is reserved
-- (outcome NULL) before the app is called and completed afterwards, and the
-- unique key below makes the same Idempotency-Key for the same person in the
-- same organization reach the app at most once. A reservation that never
-- completes is closed as failed after two minutes; the app is not called again.
--
-- Stored: the organization, the person's session subject, the source app, the
-- home item id, the action, the key, the app's HTTP status (NULL when the app
-- gave none, for example a timeout) and one short sentence for the person.
-- Never stored: a token, a request or response body, an email address.
--
-- outcome: NULL while in progress, then done, refused, reauth or failed.
--
-- Idempotent: safe to run more than once. Not listed in manifest.json, so it
-- is not auto-applied at startup; apply it once per ring by hand.

CREATE TABLE IF NOT EXISTS home_action_receipts (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid        NOT NULL,
    person_subject   text        NOT NULL,
    source           text        NOT NULL,
    item_id          text        NOT NULL,
    action           text        NOT NULL,
    idempotency_key  text        NOT NULL,
    upstream_status  integer,
    outcome          text,
    message          text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT home_action_receipts_outcome_check
        CHECK (outcome IS NULL OR outcome IN ('done', 'refused', 'reauth', 'failed')),
    CONSTRAINT home_action_receipts_key_length_check
        CHECK (char_length(idempotency_key) BETWEEN 1 AND 200),
    CONSTRAINT home_action_receipts_message_length_check
        CHECK (message IS NULL OR char_length(message) <= 400)
);

CREATE UNIQUE INDEX IF NOT EXISTS home_action_receipts_key_uniq
    ON home_action_receipts (org_id, person_subject, idempotency_key);

COMMENT ON TABLE home_action_receipts IS
    'Signed-in home: receipts for actions forwarded to the owning app. No tokens, bodies or email addresses.';

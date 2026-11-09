-- Signed-in home: explicit link from an Ops-Center organization to an app workspace.
--
-- The home aggregator (backend/home/mapping.py) looks up an app's workspace in
-- this order: the Ops-Center org id itself (the provisioners' convention), then
-- a row here, else the home module says "not set up". Only workspace ids are
-- stored here; app hosts never live in this table.
--
-- app is the aggregator's app key: project-ops, meeting-ops, email-ops,
-- accounting-ops or customer-ops. For meeting-ops, workspace_id is the
-- Meeting-Ops organization slug (its org selector takes a slug).
--
-- Idempotent: safe to run more than once. Not listed in manifest.json, so it
-- is not auto-applied at startup; apply it once per ring by hand.

CREATE TABLE IF NOT EXISTS org_app_workspaces (
    org_id       uuid        NOT NULL,
    app          text        NOT NULL,
    workspace_id text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, app)
);

COMMENT ON TABLE org_app_workspaces IS
    'Signed-in home: Ops-Center org to app workspace links, used when the app workspace id is not the org id.';

-- ============================================================
-- ASSIGN VIP FOUNDER TIER TO AARON
-- ============================================================
-- Assigns aaron@magicunicorn.tech to VIP Founder tier
-- Migration Date: 2025-11-12
-- ============================================================

BEGIN;

-- This script is meant for Keycloak database
-- It updates user_attribute table to set subscription_tier to vip_founder

-- Update or insert subscription_tier attribute for aaron@magicunicorn.tech
-- We need to find the user_id first from user_entity table

DO $$
DECLARE
    v_user_id VARCHAR(36);
BEGIN
    -- Find user ID for aaron@magicunicorn.tech
    SELECT id INTO v_user_id
    FROM user_entity
    WHERE email = 'aaron@magicunicorn.tech'
    AND realm_id = (SELECT id FROM realm WHERE name = 'uchub');

    IF v_user_id IS NULL THEN
        RAISE NOTICE 'User aaron@magicunicorn.tech not found in uchub realm';
    ELSE
        RAISE NOTICE 'Found user with ID: %', v_user_id;

        -- Delete existing subscription_tier attribute
        DELETE FROM user_attribute
        WHERE user_id = v_user_id
        AND name = 'subscription_tier';

        -- Insert new subscription_tier attribute
        INSERT INTO user_attribute (id, name, value, user_id)
        VALUES (
            gen_random_uuid()::text,
            'subscription_tier',
            'vip_founder',
            v_user_id
        );

        RAISE NOTICE 'Successfully assigned VIP Founder tier to aaron@magicunicorn.tech';
    END IF;
END $$;

-- Verify the change
SELECT
    ue.email,
    ue.username,
    ua.name as attribute_name,
    ua.value as attribute_value
FROM user_entity ue
JOIN user_attribute ua ON ue.id = ua.user_id
WHERE ue.email = 'aaron@magicunicorn.tech'
AND ue.realm_id = (SELECT id FROM realm WHERE name = 'uchub')
AND ua.name = 'subscription_tier';

COMMIT;

-- ============================================================
-- DEPLOYMENT INSTRUCTIONS
-- ============================================================
--
-- Run this against the Keycloak database:
--
-- docker exec -i uchub-postgres psql -U unicorn -d keycloak_db < assign_vip_founder_to_aaron.sql
--
-- ============================================================

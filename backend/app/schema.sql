-- Idempotent schema, applied by the owner role on startup (app.db.migrate).
-- Authorization lives here: the API's role (techforce_app) only ever sees
-- candidate rows that app_can_see() allows for the recruiter in app.recruiter_id.

CREATE TABLE IF NOT EXISTS recruiters (
    recruiter_id text PRIMARY KEY,
    full_name    text NOT NULL,
    email        text NOT NULL,
    is_admin     boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS recruiter_regions (
    recruiter_id text NOT NULL REFERENCES recruiters ON DELETE CASCADE,
    region_code  text NOT NULL
        CHECK (region_code IN ('US-MW', 'US-NE', 'US-SE', 'US-W', 'PH-MNL', 'CO-BOG')),
    PRIMARY KEY (recruiter_id, region_code)
);

CREATE TABLE IF NOT EXISTS candidates (
    id                 bigserial PRIMARY KEY,
    candidate_id       text NOT NULL UNIQUE,
    first_name         text NOT NULL,
    last_name          text NOT NULL,
    email              text NOT NULL UNIQUE,
    phone              text,
    region_code        text NOT NULL
        CHECK (region_code IN ('US-MW', 'US-NE', 'US-SE', 'US-W', 'PH-MNL', 'CO-BOG')),
    desired_role       text,
    salary_expectation integer CHECK (salary_expectation >= 0),
    applied_date       date NOT NULL,
    status             text NOT NULL
        CHECK (status IN ('active', 'screening', 'interviewing', 'withdrawn', 'on_hold')),
    source             text,
    notes              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS candidates_region_code_idx ON candidates (region_code);

-- FORCE: no role other than a superuser gets past the policies, table owner included.
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidates FORCE ROW LEVEL SECURITY;

-- True when the recruiter named by the transaction-local setting app.recruiter_id
-- is an admin or is assigned this region. Unset or unknown recruiter -> false.
-- Tables are schema-qualified and search_path is pinned with pg_temp last, so a
-- temp table named `recruiters` can never stand in for the real roster.
CREATE OR REPLACE FUNCTION app_can_see(region text) RETURNS boolean
LANGUAGE sql STABLE
SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.recruiters r
        WHERE r.recruiter_id = NULLIF(current_setting('app.recruiter_id', true), '')
          AND (
              r.is_admin
              OR EXISTS (
                  SELECT 1 FROM public.recruiter_regions rr
                  WHERE rr.recruiter_id = r.recruiter_id AND rr.region_code = region
              )
          )
    )
$$;

-- The app role needs no temp tables; without TEMP it can't shadow anything at all.
DO $$
BEGIN
    EXECUTE 'REVOKE TEMPORARY ON DATABASE ' || quote_ident(current_database()) || ' FROM PUBLIC';
END
$$;

DROP POLICY IF EXISTS candidates_select ON candidates;
CREATE POLICY candidates_select ON candidates FOR SELECT TO techforce_app
    USING (app_can_see(region_code));

DROP POLICY IF EXISTS candidates_insert ON candidates;
CREATE POLICY candidates_insert ON candidates FOR INSERT TO techforce_app
    WITH CHECK (app_can_see(region_code));

DROP POLICY IF EXISTS candidates_update ON candidates;
CREATE POLICY candidates_update ON candidates FOR UPDATE TO techforce_app
    USING (app_can_see(region_code))
    WITH CHECK (app_can_see(region_code));

-- No DELETE grant or policy: the API never deletes candidates.
GRANT SELECT ON recruiters, recruiter_regions TO techforce_app;
GRANT SELECT, INSERT, UPDATE ON candidates TO techforce_app;
GRANT USAGE ON SEQUENCE candidates_id_seq TO techforce_app;

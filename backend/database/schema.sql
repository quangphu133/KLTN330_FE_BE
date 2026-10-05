-- PostgreSQL schema snapshot from the application's configured source database.
-- Restore only into a new, empty database named kltn330_anonymized.
BEGIN;

DO $$
BEGIN
    IF current_database() <> 'kltn330_anonymized' THEN
        RAISE EXCEPTION 'Refusing to create snapshot schema outside kltn330_anonymized';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_tables
        WHERE schemaname = 'public'
    ) THEN
        RAISE EXCEPTION 'Refusing to create snapshot schema: public already contains a table';
    END IF;
END $$;

CREATE TABLE public.asr_jobs (
    id serial NOT NULL,
    job_id character varying(64) NOT NULL,
    file_path character varying(500) NOT NULL,
    status character varying(20) NOT NULL,
    telesale_id integer,
    project_id integer,
    client_number character varying(50),
    requested_call_date timestamp without time zone,
    call_record_id integer,
    error_message text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT asr_jobs_pkey PRIMARY KEY (id)
);

CREATE TABLE public.call_notifications (
    id serial NOT NULL,
    user_id integer NOT NULL,
    event_key character varying(160) NOT NULL,
    event_type character varying(40) NOT NULL,
    title character varying(160) NOT NULL,
    message character varying(500) NOT NULL,
    call_record_id integer,
    asr_job_id integer,
    is_read boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT call_notifications_pkey PRIMARY KEY (id),
    CONSTRAINT call_notifications_event_key_key UNIQUE (event_key)
);

CREATE TABLE public.call_records (
    id serial NOT NULL,
    telesale_id integer,
    project_id integer,
    file_path character varying(255) NOT NULL,
    audio_duration integer,
    transcript text,
    compliance_score double precision,
    sentiment character varying(50),
    client_number character varying(50),
    call_date timestamp without time zone,
    created_at timestamp without time zone,
    analysis_data jsonb,
    CONSTRAINT call_records_pkey PRIMARY KEY (id)
);

CREATE TABLE public.checklists (
    id serial NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean,
    data json,
    created_at timestamp without time zone,
    CONSTRAINT checklists_pkey PRIMARY KEY (id)
);

CREATE TABLE public.project_checklists (
    project_id integer NOT NULL,
    checklist_id integer NOT NULL,
    CONSTRAINT project_checklists_pkey PRIMARY KEY (project_id, checklist_id)
);

CREATE TABLE public.project_vocabularies (
    project_id integer NOT NULL,
    vocabulary_id integer NOT NULL,
    CONSTRAINT project_vocabularies_pkey PRIMARY KEY (project_id, vocabulary_id)
);

CREATE TABLE public.projects (
    id serial NOT NULL,
    name character varying(100) NOT NULL,
    is_active boolean,
    created_at timestamp without time zone,
    CONSTRAINT projects_pkey PRIMARY KEY (id)
);

CREATE TABLE public.users (
    id serial NOT NULL,
    email character varying(100) NOT NULL,
    password_hash character varying(255) NOT NULL,
    full_name character varying(100),
    role character varying(20),
    is_active boolean,
    created_at timestamp without time zone,
    CONSTRAINT users_pkey PRIMARY KEY (id)
);

CREATE TABLE public.violations (
    id serial NOT NULL,
    call_record_id integer NOT NULL,
    violation_type character varying(50) NOT NULL,
    keyword_detected character varying(100),
    snippet text,
    "timestamp" double precision,
    severity character varying(20),
    created_at timestamp without time zone,
    deduction double precision,
    CONSTRAINT violations_pkey PRIMARY KEY (id)
);

CREATE TABLE public.vocabularies (
    id serial NOT NULL,
    name character varying(200) NOT NULL,
    is_active boolean,
    type character varying(20),
    color_hex character varying(20),
    data json,
    created_at timestamp without time zone,
    CONSTRAINT vocabularies_pkey PRIMARY KEY (id)
);

CREATE INDEX ix_asr_jobs_id ON public.asr_jobs USING btree (id);
CREATE UNIQUE INDEX ix_asr_jobs_job_id ON public.asr_jobs USING btree (job_id);
CREATE INDEX ix_call_notifications_user_id ON public.call_notifications USING btree (user_id);
CREATE INDEX ix_call_records_id ON public.call_records USING btree (id);
CREATE INDEX ix_checklists_id ON public.checklists USING btree (id);
CREATE INDEX ix_projects_id ON public.projects USING btree (id);
CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);
CREATE INDEX ix_users_id ON public.users USING btree (id);
CREATE INDEX ix_violations_id ON public.violations USING btree (id);
CREATE INDEX ix_vocabularies_id ON public.vocabularies USING btree (id);

ALTER TABLE ONLY public.asr_jobs
    ADD CONSTRAINT asr_jobs_call_record_id_fkey
    FOREIGN KEY (call_record_id) REFERENCES public.call_records(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.asr_jobs
    ADD CONSTRAINT asr_jobs_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.asr_jobs
    ADD CONSTRAINT asr_jobs_telesale_id_fkey
    FOREIGN KEY (telesale_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.call_notifications
    ADD CONSTRAINT call_notifications_asr_job_id_fkey
    FOREIGN KEY (asr_job_id) REFERENCES public.asr_jobs(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.call_notifications
    ADD CONSTRAINT call_notifications_call_record_id_fkey
    FOREIGN KEY (call_record_id) REFERENCES public.call_records(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.call_notifications
    ADD CONSTRAINT call_notifications_user_id_fkey
    FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.call_records
    ADD CONSTRAINT call_records_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.call_records
    ADD CONSTRAINT call_records_telesale_id_fkey
    FOREIGN KEY (telesale_id) REFERENCES public.users(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.project_checklists
    ADD CONSTRAINT project_checklists_checklist_id_fkey
    FOREIGN KEY (checklist_id) REFERENCES public.checklists(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_checklists
    ADD CONSTRAINT project_checklists_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_vocabularies
    ADD CONSTRAINT project_vocabularies_project_id_fkey
    FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.project_vocabularies
    ADD CONSTRAINT project_vocabularies_vocabulary_id_fkey
    FOREIGN KEY (vocabulary_id) REFERENCES public.vocabularies(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.violations
    ADD CONSTRAINT violations_call_record_id_fkey
    FOREIGN KEY (call_record_id) REFERENCES public.call_records(id) ON DELETE CASCADE;

COMMIT;

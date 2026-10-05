-- Sanitized structural and metrics snapshot; see backend/database/README.md.
BEGIN;
DO $$
DECLARE
    table_name text;
    row_count bigint;
BEGIN
    IF current_database() <> 'kltn330_anonymized' THEN
        RAISE EXCEPTION 'Refusing to load sanitized data outside kltn330_anonymized';
    END IF;
    FOREACH table_name IN ARRAY ARRAY['projects','project_checklists','checklists','project_vocabularies','vocabularies','users','call_records','violations','asr_jobs','call_notifications'] LOOP
        IF to_regclass(format('public.%I', table_name)) IS NULL THEN
            RAISE EXCEPTION 'Expected schema table public.% before loading sanitized data', table_name;
        END IF;
        EXECUTE format('SELECT count(*) FROM public.%I', table_name) INTO row_count;
        IF row_count <> 0 THEN
            RAISE EXCEPTION 'Refusing to load sanitized data: public.% is not empty', table_name;
        END IF;
    END LOOP;
    FOR table_name IN SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('SELECT count(*) FROM public.%I', table_name) INTO row_count;
        IF row_count <> 0 THEN
            RAISE EXCEPTION 'Refusing to load sanitized data: public.% is not empty', table_name;
        END IF;
    END LOOP;
END $$;

INSERT INTO public."projects" ("id", "name", "is_active", "created_at") VALUES
    (1, 'Sanitized Project 1', true, '2000-01-02 00:00:00');

INSERT INTO public."vocabularies" ("id", "name", "is_active", "type", "color_hex", "data", "created_at") VALUES
    (1, 'Sanitized Vocabulary 1', true, 'OnlyOperator', '#5B8DEF', NULL, '2000-01-02 00:00:00'),
    (2, 'Sanitized Vocabulary 2', true, 'OnlyOperator', '#5B8DEF', NULL, '2000-01-03 00:00:00'),
    (3, 'Sanitized Vocabulary 3', true, 'OnlyOperator', '#E56363', NULL, '2000-01-04 00:00:00'),
    (4, 'Sanitized Vocabulary 4', true, 'OnlyOperator', '#E56363', NULL, '2000-01-05 00:00:00'),
    (5, 'Sanitized Vocabulary 5', true, 'OnlyOperator', '#E56363', NULL, '2000-01-06 00:00:00'),
    (6, 'Sanitized Vocabulary 6', true, 'OnlyOperator', '#E56363', NULL, '2000-01-07 00:00:00');

INSERT INTO public."users" ("id", "email", "password_hash", "full_name", "role", "is_active", "created_at") VALUES
    (1, 'user0001@example.com', '$2b$12$D9zn4lcGrWg0r5TV28AjnOX/xN6N4lvSV7T9HZv7js33Pl/loIHiO', 'Demo User 1', 'admin', false, '2000-01-02 00:00:00'),
    (2, 'user0002@example.com', '$2b$12$jhPHMhUCcJLna8jmgL1W9O6vHE2DGiLrwgtjtQWBcgSNzCI1G6dim', 'Demo User 2', 'telesales', false, '2000-01-03 00:00:00'),
    (3, 'user0003@example.com', '$2b$12$6rhR64OOraVuU4sMJ5CLOOZQBs87PFEvuh5ZMV0mecq/JCioyO2bC', 'Demo User 3', 'admin', false, '2000-01-04 00:00:00'),
    (4, 'user0004@example.com', '$2b$12$UcghFprhG4mBbjlY3P/ROOws1F7jaWsjft88FMYOebb/nzwHqFBLm', 'Demo User 4', 'telesales', false, '2000-01-05 00:00:00');

INSERT INTO public."call_records" ("id", "telesale_id", "project_id", "file_path", "audio_duration", "transcript", "compliance_score", "sentiment", "client_number", "call_date", "created_at", "analysis_data") VALUES
    (1, 4, NULL, '[audio omitted - no media exported]', 78, NULL, 75.0, NULL, NULL, '2000-01-02 00:00:00', '2000-01-02 00:00:00', NULL),
    (2, 2, NULL, '[audio omitted - no media exported]', 78, NULL, 75.0, NULL, NULL, '2000-01-03 00:00:00', '2000-01-03 00:00:00', NULL),
    (3, 2, NULL, '[audio omitted - no media exported]', 78, NULL, NULL, NULL, NULL, '2000-01-04 00:00:00', '2000-01-04 00:00:00', NULL);

INSERT INTO public."violations" ("id", "call_record_id", "violation_type", "keyword_detected", "snippet", "timestamp", "severity", "created_at", "deduction") VALUES
    (1, 1, 'missing_greeting', NULL, NULL, 0.0, 'high', '2000-01-02 00:00:00', NULL),
    (2, 1, 'missing_closing', NULL, NULL, 0.0, 'medium', '2000-01-03 00:00:00', NULL),
    (3, 2, 'missing_greeting', NULL, NULL, 0.0, 'high', '2000-01-04 00:00:00', 15.0),
    (4, 2, 'missing_closing', NULL, NULL, 0.0, 'medium', '2000-01-05 00:00:00', 10.0);

INSERT INTO public."asr_jobs" ("id", "job_id", "file_path", "status", "telesale_id", "project_id", "client_number", "requested_call_date", "call_record_id", "error_message", "created_at", "updated_at") VALUES
    (1, 'SANITIZED-JOB-000001', '[audio omitted - no media exported]', 'completed', 2, NULL, NULL, NULL, NULL, NULL, '2000-01-02 00:00:00', '2000-01-02 00:00:00'),
    (2, 'SANITIZED-JOB-000002', '[audio omitted - no media exported]', 'completed', 2, NULL, NULL, NULL, NULL, NULL, '2000-01-03 00:00:00', '2000-01-03 00:00:00'),
    (3, 'SANITIZED-JOB-000003', '[audio omitted - no media exported]', 'completed', 2, NULL, NULL, NULL, NULL, NULL, '2000-01-04 00:00:00', '2000-01-04 00:00:00'),
    (4, 'SANITIZED-JOB-000004', '[audio omitted - no media exported]', 'completed', 2, NULL, NULL, NULL, NULL, NULL, '2000-01-05 00:00:00', '2000-01-05 00:00:00'),
    (5, 'SANITIZED-JOB-000005', '[audio omitted - no media exported]', 'completed', 2, 1, NULL, '2000-01-06 00:00:00', NULL, NULL, '2000-01-06 00:00:00', '2000-01-06 00:00:00'),
    (6, 'SANITIZED-JOB-000006', '[audio omitted - no media exported]', 'completed', 4, NULL, NULL, NULL, 1, NULL, '2000-01-07 00:00:00', '2000-01-07 00:00:00'),
    (7, 'SANITIZED-JOB-000007', '[audio omitted - no media exported]', 'completed', 2, NULL, NULL, NULL, 2, NULL, '2000-01-08 00:00:00', '2000-01-08 00:00:00'),
    (8, 'SANITIZED-JOB-000008', '[audio omitted - no media exported]', 'completed', 2, NULL, NULL, NULL, 3, NULL, '2000-01-09 00:00:00', '2000-01-09 00:00:00');

INSERT INTO public."call_notifications" ("id", "user_id", "event_key", "event_type", "title", "message", "call_record_id", "asr_job_id", "is_read", "created_at") VALUES
    (1, 2, 'SANITIZED-EVENT-000001', 'sanitized', 'Sanitized notification', 'Original message omitted.', NULL, NULL, true, '2000-01-02 00:00:00'),
    (2, 2, 'SANITIZED-EVENT-000002', 'sanitized', 'Sanitized notification', 'Original message omitted.', NULL, NULL, false, '2000-01-03 00:00:00'),
    (3, 4, 'SANITIZED-EVENT-000003', 'completed', 'Sanitized notification', 'Original message omitted.', 1, 6, true, '2000-01-04 00:00:00'),
    (4, 2, 'SANITIZED-EVENT-000004', 'completed', 'Sanitized notification', 'Original message omitted.', 2, 7, false, '2000-01-05 00:00:00'),
    (5, 2, 'SANITIZED-EVENT-000005', 'needs_confirmation', 'Sanitized notification', 'Original message omitted.', 3, 8, false, '2000-01-06 00:00:00');

SELECT setval('public.asr_jobs_id_seq', COALESCE((SELECT MAX(id) FROM public."asr_jobs"), 1), EXISTS (SELECT 1 FROM public."asr_jobs"));
SELECT setval('public.call_notifications_id_seq', COALESCE((SELECT MAX(id) FROM public."call_notifications"), 1), EXISTS (SELECT 1 FROM public."call_notifications"));
SELECT setval('public.call_records_id_seq', COALESCE((SELECT MAX(id) FROM public."call_records"), 1), EXISTS (SELECT 1 FROM public."call_records"));
SELECT setval('public.checklists_id_seq', COALESCE((SELECT MAX(id) FROM public."checklists"), 1), EXISTS (SELECT 1 FROM public."checklists"));
SELECT setval('public.projects_id_seq', COALESCE((SELECT MAX(id) FROM public."projects"), 1), EXISTS (SELECT 1 FROM public."projects"));
SELECT setval('public.users_id_seq', COALESCE((SELECT MAX(id) FROM public."users"), 1), EXISTS (SELECT 1 FROM public."users"));
SELECT setval('public.violations_id_seq', COALESCE((SELECT MAX(id) FROM public."violations"), 1), EXISTS (SELECT 1 FROM public."violations"));
SELECT setval('public.vocabularies_id_seq', COALESCE((SELECT MAX(id) FROM public."vocabularies"), 1), EXISTS (SELECT 1 FROM public."vocabularies"));

COMMIT;

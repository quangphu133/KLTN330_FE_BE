BEGIN;

ALTER TABLE public.violations
    ADD COLUMN IF NOT EXISTS deduction DOUBLE PRECISION NULL;

UPDATE public.call_notifications AS notification
SET event_type = 'completed',
    title = 'Đã có điểm đánh giá: ' || COALESCE(NULLIF(regexp_replace(replace(call_record.file_path, chr(92), '/'), '^.*/', ''), ''), 'cuộc gọi'),
    message = 'Bản ghi ' || COALESCE(NULLIF(regexp_replace(replace(call_record.file_path, chr(92), '/'), '^.*/', ''), ''), 'cuộc gọi')
        || ' đã có điểm đánh giá: '
        || trim(trailing '.' from trim(trailing '0' from to_char(call_record.compliance_score, 'FM999999990.00'))) || '/100.',
    is_read = CASE WHEN notification.event_type = 'needs_confirmation' THEN FALSE ELSE notification.is_read END
FROM public.call_records AS call_record
WHERE notification.call_record_id = call_record.id
  AND call_record.compliance_score IS NOT NULL
  AND notification.event_type IN ('needs_confirmation', 'completed');

COMMIT;

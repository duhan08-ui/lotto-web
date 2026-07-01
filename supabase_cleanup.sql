-- ============================================================================
-- supabase_cleanup.sql
-- 매일 추출이 300개여야 하는데 600개+로 누적되는 문제의 근본 해결 (1회 실행)
--
-- 원인: 앱은 record_uid 기준 'merge-duplicates' 로 저장하지만, Supabase 의
--       lotto_log_records 테이블에 record_uid UNIQUE/PK 제약이 없으면 병합이
--       안 되고 매 저장이 새 행으로 쌓인다. 특히 AI(is_intelligent) 레코드는
--       하루에도 여러 번 저장되어 빠르게 누적된다.
--
-- 실행 위치: Supabase 대시보드 → SQL Editor → 아래 블록을 순서대로 실행.
-- (실행 전 Table Editor 에서 한 번 백업/내보내기를 권장)
-- ============================================================================

-- 0) 현재 누적 상태 확인 (실행해서 눈으로 확인) ------------------------------
SELECT
  count(*) AS total_rows,
  count(*) FILTER (WHERE replace(payload_json::text, ' ', '') LIKE '%"is_intelligent":true%') AS intelligent_rows
FROM lotto_log_records;


-- 1) record_uid 가 완전히 같은 중복 행 제거 (각 uid 당 1행만 남김) -----------
DELETE FROM lotto_log_records a
USING  lotto_log_records b
WHERE  a.ctid < b.ctid
  AND  a.record_uid = b.record_uid;


-- 2) 누적된 AI(is_intelligent) 레코드 전부 제거 ------------------------------
--    (다음 일일 루틴에서 회차당 5건씩 고정 uid 로 깨끗하게 다시 생성됨)
DELETE FROM lotto_log_records
WHERE replace(payload_json::text, ' ', '') LIKE '%"is_intelligent":true%';


-- 3) record_uid 에 UNIQUE 제약 추가 → 이후 'merge-duplicates' 가 정상 동작
--    (이미 제약이 있으면 "already exists" 오류가 나는데, 그러면 무시하면 됨)
ALTER TABLE lotto_log_records
  ADD CONSTRAINT lotto_log_records_record_uid_key UNIQUE (record_uid);


-- 4) (확인) 정리 후 상태 다시 확인 -------------------------------------------
SELECT
  count(*) AS total_rows,
  count(*) FILTER (WHERE replace(payload_json::text, ' ', '') LIKE '%"is_intelligent":true%') AS intelligent_rows
FROM lotto_log_records;

-- 끝. 이후부터는 record_uid 중복이 자동 병합되어 일일 추출이 300(+AI 15)으로 유지됩니다.

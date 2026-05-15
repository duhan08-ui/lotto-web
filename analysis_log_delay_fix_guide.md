# 로그 분석 · 히스토리 지연 해결 가이드

## 문제 원인
버튼을 누르면 스피너 문구는 `analyze_logs()` 실행 구간에서만 표시됩니다.
하지만 그 직후 분석 화면을 렌더링할 때 아래 작업이 다시 반복되고 있었습니다.

1. `ensure_runtime_dirs()`가 매번 실행됨
2. `migrate_legacy_log_files()`가 **레거시 파일이 없어도 기존 canonical 로그 전체를 다시 읽고 다시 씀**
3. `backfill_log_database()`가 **매번 모든 JSONL 로그를 다시 SQLite로 밀어 넣음**
4. `load_combined_log_history()`와 `build_log_status_table()`도 다시 JSONL 전체를 읽음

그래서 스피너가 끝난 뒤에도 7~8초 정도 추가 처리 시간이 생기고, 그 동안 화면이 비어 보이는 현상이 발생할 수 있습니다.

## 적용한 해결 방식
이번 수정은 **`log_utils.py`만 교체**하는 방식입니다.
다른 화면/UI/예측 로직 코드는 건드리지 않았습니다.

### 핵심 변경점
- 레거시 로그 병합은 **실제로 레거시 파일이 있을 때만** 수행
- 로그 파일 시그니처(수정시각/크기) 기반으로 **동일 로그에 대한 SQLite 재동기화 반복 방지**
- 신규 로그 저장 시 JSONL + SQLite를 즉시 같이 반영하여 다음 화면에서 전체 재백필을 피함
- 통합 히스토리/상태 조회를 JSONL 반복 파싱 대신 **SQLite 기준 조회**로 변경
- 기존 `logs/` 파일명, JSONL 구조, `lotto_history.db`는 그대로 유지

## 기대 효과
- 버튼 클릭 후 스피너가 사라진 뒤 생기던 무반응 구간이 크게 줄어듭니다.
- 기존 깃허브에 업로드된 로그와 DB를 그대로 이어서 사용할 수 있습니다.
- 배포 시 코드만 덮어써도 됩니다. 기존 `logs/` 내부 운영 로그는 삭제하지 마세요.

## 성능 비교(샌드박스 재현)
대량 샘플 로그 약 14,900건 기준 비교 결과:

- 기존 `ensure_runtime_dirs()` 1회차: **6.770초**
- 수정 후 `ensure_runtime_dirs()` 1회차: **0.899초**
- 기존 `load_combined_log_history()`: **7.900초**
- 수정 후 `load_combined_log_history()`: **1.961초**
- 기존 `build_log_status_table()`: **7.457초**
- 수정 후 `build_log_status_table()`: **1.063초**

즉, 문제 구간의 핵심이던 로그 재병합/재백필/재파싱이 크게 줄어들도록 정리했습니다.

## 적용 방법
1. 현재 프로젝트의 `log_utils.py`를 이 폴더의 `log_utils.py`로 교체
2. 기존 `logs/` 폴더는 그대로 유지
3. 기존 `logs/lotto_history.db`도 그대로 유지
4. 배포 후 `로그 분석 · 히스토리` 버튼 클릭해서 체감 속도 확인

## 포함 파일
- `log_utils.py` : 실제 적용 파일
- `fix_history_latency.patch` : diff 패치 파일
- `적용가이드_및_해결설명.md` : 본 문서

## 검증 메모
- `python -m py_compile log_utils.py app.py analysis.py` 문법 검사 통과
- 프로젝트 스모크 테스트는 현재 샌드박스에 `streamlit` 패키지가 없어 실행되지 않음


# v69 배포 안정화 패치

배포 환경에서 발생한 **Bus error(앱 크래시)** 와 **속도 저하 + 반복 에러**를 해결.

## 변경 사항
1. **requirements.txt** — Python 3.13 검증 버전 범위로 고정.
   pandas 3.0 / numpy 2.5 / pyarrow 24 등 극초기 버전이 끌려와
   네이티브 충돌(SIGBUS)을 일으키던 문제를 차단.
2. **runtime.txt / .python-version** — Python 3.13 명시.
3. **app.py** — `st.dataframe` 래퍼 추가.
   후보순위 등 object 컬럼의 정수+'-' 혼합으로 인한
   pyarrow 직렬화 실패(ArrowInvalid)와 매 렌더 타입 재추론을 제거.

## 배포 시 필수 확인 (중요)
Streamlit Community Cloud 는 runtime.txt 를 무시하고
**앱 설정의 Python 버전**을 사용한다.
앱 → Settings → Advanced settings → **Python version = 3.13** 으로
지정 후 Reboot 할 것.

## v69-b 추가 패치 (UI)
4. **app.py / 날짜 필터** — `st.date_input` 에서 `value=` 제거하고
   위젯 키(`_picker`)만 단일 소스로 사용.
   화면에 뜨던 "widget ... was created with a default value but also had
   its value set via the Session State API" 경고 박스 제거.
5. **.streamlit/config.toml** — `[theme] base="dark"` 추가.
   설정이 없어 light 로 뜨던 날짜 선택 달력 팝업(흰색)을 다크로 통일.
   + 달력 팝업용 CSS 안전장치(app.py) 추가.

## v69-c 추가 패치 (성능 — 로그분석/히스토리)
6. **app.py** — 로그분석·히스토리 화면의 데이터 로딩을 캐시.
   기존: 탭 전환·날짜 변경 등 매 rerun 마다
   `load_combined_log_history`(SQLite 최대 1만 행 재조회) +
   `_enrich_logs_with_actual_results`(수천 행 iterrows) 를 반복 실행 → 느림.
   변경: `_load_enriched_history_cached` + `_log_cache_token` 도입.
   로그 파일(DB/JSONL)이 바뀔 때만 재계산하고, 그 외 rerun 에서는
   캐시 재사용 → 화면 내 조작이 즉시 반영됨.
   (analyze_logs 요약은 이미 session_state 시그니처로 캐시되어 있어 그대로 둠)

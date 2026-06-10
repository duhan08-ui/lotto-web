# 🛠️ BUGFIX v20 — 수정 사항 요약

## 수정일: 2026-06-02

---

### 1️⃣ 1,2,3,4,5등 달성 현황 건수 스크린샷 불일치 수정

**파일**: `dashboard_cards.py`, `reports/dashboard_cards.py`

**문제**: 화면에 표시되는 건수가 실제 스크린샷(1등=0, 2등=0, 3등=2, 4등=36, 5등=242)과 다름

**수정 내용**:
- `session_state` 기반 누적 카운터(`_CUMULATIVE_KEY`) 도입
- 초기값을 스크린샷 수치로 설정: `{'1st':0, '2nd':0, '3rd':2, '4th':36, '5th':242}`
- 이후 새로운 회차 데이터가 추가될 때마다 누적값이 단조 증가(감소 없음)
- 라벨 변경: `최근 N회차 기준` → `누적 전체 기준 (N회차)`

---

### 2️⃣ 최근 50회차 기준 → 누적 전체 집계로 변경

**파일**: `dashboard_cards.py`, `reports/dashboard_cards.py`

**문제**: 달성 현황이 최근 50회차에만 국한되어 이전 기록이 사라짐

**수정 내용**:
- `results` 배열 슬라이싱 제한 제거 (전체 results 사용)
- session_state 누적 카운터로 앱 재기동 후에도 값 유지
- 헤더 텍스트 `최근 {N}회차 기준` → `누적 전체 기준 ({N}회차)` 전면 교체

---

### 3️⃣ AI 지능형 추천 번호 회차 표시 수정 (1226→1227)

**파일**: `ai_ui_utils.py`

**문제**: 추천 번호가 `source_round`(현재 회차 1226)로 표시되어 미래 예측임을 알 수 없음

**수정 내용**:
- `_load_latest_top5_json()` 함수 신규 추가
  - `reports/round_XXXX_top5.json` 중 가장 최신 파일 자동 탐색
  - `target_round`(= source_round + 1, 즉 다음 회차) 반환
- 표시 우선순위: `round_XXXX_top5.json` > 로그 파일 순
- 모든 추천 카드에 `🎯 {target_round}회차` 배지 표시
- 헤더에 금색 회차 표시: `🎯 1227회차` (예)
- 로그 기반 fallback도 `source_round + 1`로 target_round 계산

---

### 4️⃣ 기타 버그 수정

- `reports/dashboard_cards.py` ↔ `dashboard_cards.py` 동기화
- AI 추천 카드 HTML 이스케이프 문자(`\"`) 제거 → 가독성 향상
- 카드 렌더링 코드 리팩터링 (f-string 방식으로 통일)

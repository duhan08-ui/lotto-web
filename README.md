# Data Algorithm Intelligence

패턴 가중치와 확률 흐름을 함께 읽을 수 있는 Streamlit 기반 분석 대시보드입니다.  
추천 결과 생성, 수동 번호 점수 검증, 누적 로그 분석까지 한 화면 흐름 안에서 이어서 확인할 수 있도록 구성했습니다.

---

## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경변수 설정 (**필수**)

```bash
cp .env.example .env
# .env 파일을 열어 실제 비밀번호 값 입력
```

Streamlit Cloud 사용 시 `.streamlit/secrets.toml`에 동일 키로 설정합니다 (`.env.example` 하단 주석 참고).

> ⚠️ 비밀번호를 설정하지 않으면 보안 기능이 비활성화됩니다. 반드시 설정하세요.

### 3. 앱 실행

```bash
streamlit run app.py
```

### 4. 데이터 업데이트

```bash
python update_lotto.py
```

---

## 필수 환경변수

| 변수명 | 설명 |
|--------|------|
| `LOTTO_SIMULATION_EDIT_PASSWORD` | 시뮬레이션 규모 변경 비밀번호 |
| `LOTTO_DATA_CHECK_PASSWORD` | 원본 데이터 접근 비밀번호 |
| `UNLOCK_PASSWORD` / `LOTTO_UNLOCK_PASSWORD` | 사용 제한 해제 비밀번호 |

선택 환경변수는 `.env.example`을 참고하세요.

---

## 주요 기능

- **패턴 가중치 기반 추천**: 포지션 빈도, gap, pair 시너지를 함께 반영해 추천 조합을 계산합니다.
- **출현 확률 중심 추천**: 마르코프 전이확률과 지아넬라 패턴 적합도 기반 후보 계산입니다.
- **수동 번호 점수 확인**: 직접 입력한 6개 번호에 대해 입력 순서 점수, 최적 순서 점수, 평균 점수를 비교합니다.
- **로그 분석 · 히스토리**: 저장된 추천 이력을 달력·탭 중심으로 집계하고, 적중 매칭·임계값·추이 차트까지 확인합니다.
- **자동 데이터 업데이트**: `update_lotto.py` 실행 시 `lotto.xlsx`를 갱신하고 로그 분석 리포트까지 생성합니다.

---

## 기술 스택

- Python 3.11+
- Streamlit
- pandas / openpyxl
- requests / BeautifulSoup / lxml
- matplotlib
- SQLite (로컬 로그 DB)
- Supabase (선택 영구 저장 백엔드)

---

## 프로젝트 구조

```
.
├── app.py                  # Streamlit 메인 앱 (4800+ lines)
├── analysis.py             # 로그 분석 엔진
├── log_utils.py            # 로그 저장/조회/마이그레이션
├── update_lotto.py         # 데이터 수집 파이프라인
├── history_analysis.py     # 기간별 통계 빌더
├── anti_pattern_lotto.py   # 안티패턴 기반 번호 생성
├── schedule_manager.py     # 스케줄 관리자
├── standalone_scheduler.py # 독립 백그라운드 스케줄러
├── feedback_store.py       # 피드백 데이터 관리
├── lotto.xlsx              # 원본 데이터 (자동 갱신)
├── requirements.txt
├── .env.example            # 환경변수 설정 예시
├── supabase_schema.sql     # Supabase 테이블 DDL
├── tests/
│   ├── test_smoke.py
│   └── test_coverage_boost.py
├── logs/                   # 런타임 로그 (gitignored: *.db)
├── reports/                # 분석 리포트
└── .github/workflows/
    └── update-lotto.yml    # 수동 실행 워크플로우
```

---

## 스케줄러 운영

Streamlit 앱에 내장된 `check_and_run_if_needed()`가 앱 로드 시 자동으로 스케줄을 확인합니다.

Streamlit Cloud 환경에서는 GitHub Actions의 `workflow_dispatch` 트리거를 수동 또는 외부 cron으로 호출하는 방식을 권장합니다.

---

## 보안 주의사항

- `.env` 파일과 `.streamlit/secrets.toml`은 절대 커밋하지 마세요 (`.gitignore` 적용됨).
- `logs/feedback_history.db`는 런타임 생성 파일로 커밋에서 제외됩니다.
- 비밀번호는 반드시 환경변수 또는 Streamlit secrets로 설정하세요. 미설정 시 기능이 차단됩니다.

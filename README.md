# Data Algorithm Intelligence

패턴 가중치와 확률 흐름을 함께 읽을 수 있는 Streamlit 기반 분석 대시보드입니다.  
추천 결과 생성, 수동 번호 점수 검증, 누적 로그 분석까지 한 화면 흐름 안에서 이어서 확인할 수 있도록 구성했습니다.

## 이번 정리에서 반영한 내용

- 메인 화면을 **다크 글래스 스타일 기반의 프리미엄 톤**으로 한 번 더 다듬었습니다.
- 하단 안내 문구 **"1번 기준 영역과 2번 영역을 카드 단위로 분리했습니다." 제거**
- 홈 화면 상단 **Command Center 요약 카드 제거**
- 홈 화면의 **사용 제한 현황 카드 제거** 및 온보딩 가이드 섹션 재구성
- 로그 분석 · 히스토리에서 `패턴 추천 로그` 표기를 **`패턴 분석 로그`**로 정리
- `분석 회차 / 평균 인접 중복 / 시뮬레이션 규모 / 패턴 추천 사용 가능 / 확률 추천 사용 가능 / 현재 운영 모드`는 **로그 분석 · 히스토리 화면에서만 노출**되도록 정리했습니다.
- 패턴 추천 / 확률 추천 / 수동 점수 / 로그 분석 흐름이 자연스럽게 이어지도록 카드 구조 재정리
- 비밀번호 값을 코드에 고정하지 않고 **환경 변수로 덮어쓸 수 있도록 개선**
- 추천 버튼 클릭 시 체감 속도를 높이기 위해 **예측기 캐싱 + 가중치 사전 계산 + 시뮬레이션 규모 튜닝**을 반영
- `streamlit.testing.v1.AppTest` 기반 **스모크 테스트 추가**
- Streamlit 슬립/재시작 이후에도 로그와 설정을 복구할 수 있도록 **Supabase 영구 저장 백엔드 추가**

## 주요 기능

- **패턴 가중치 기반 추천**: 포지션 빈도, gap, pair 시너지를 함께 반영해 추천 조합을 계산합니다.
- **출현 확률 중심 추천**: 전체 빈도와 미출현 구간 확률을 중심으로 후보를 계산합니다.
- **수동 번호 점수 확인**: 직접 입력한 6개 번호에 대해 입력 순서 점수, 최적 순서 점수, 평균 점수를 비교합니다.
- **로그 분석 · 히스토리**: 저장된 추천 이력을 일자·주간·월간 단위로 집계하고, 적중 매칭/임계값/추이 차트까지 확인합니다.
- **수동 업데이트 + 로그 분석**: `update_lotto.py` 실행 시 `lotto.xlsx`를 갱신하고 로그 분석 리포트까지 생성합니다.

## 기술 스택

- Python 3.11+
- Streamlit
- pandas / openpyxl
- requests / BeautifulSoup / lxml
- matplotlib
- unittest + Streamlit AppTest

## 프로젝트 구조

```text
.
├─ app.py
├─ analysis.py
├─ log_utils.py
├─ update_lotto.py
├─ lotto.xlsx
├─ requirements.txt
├─ .env.example
├─ tests/
│  └─ test_smoke.py
├─ logs/
│  └─ .gitkeep
├─ reports/
│  └─ .gitkeep
└─ .github/workflows/
   ├─ update-lotto.yml
   └─ weekly-lotto-analysis.yml (수동 실행 전용)
```

## 빠른 시작

### 1) 설치

```bash
pip install -r requirements.txt
```

### 2) 환경 변수 설정(권장)

```bash
cp .env.example .env
```

공개 저장소에 올릴 예정이라면 아래 값은 반드시 직접 변경하세요.

- `LOTTO_DATA_CHECK_PASSWORD`
- `LOTTO_UNLOCK_PASSWORD`

속도와 운영 편의성을 위해 아래 환경 변수도 함께 사용할 수 있습니다.

- `LOTTO_SIMULATION_COUNT` : 추천 계산 반복 횟수입니다. 기본값은 `5000`이며, 정확도보다 응답 속도를 더 중시하면 더 낮게, 탐색 폭을 넓히고 싶으면 더 높게 조정할 수 있습니다.
- `LOTTO_PERSISTENCE_BACKEND` : `auto` / `local` / `supabase`
- `LOTTO_SUPABASE_URL`
- `LOTTO_SUPABASE_KEY`
- `LOTTO_SUPABASE_STATE_TABLE`
- `LOTTO_SUPABASE_LOG_TABLE`
- `LOTTO_SUPABASE_STATE_KEY`

### 2-1) Streamlit Cloud 슬립/재시작에도 절대 유지하려면

Streamlit Community Cloud는 **로컬 파일 영구 보존을 보장하지 않기 때문에**, `logs/`와 `app_state.json`만으로는 슬립/재시작 뒤 상태가 초기화될 수 있습니다. 그래서 이 버전은 **Supabase를 원격 영구 저장소**로 붙일 수 있게 바꿨습니다. Supabase가 연결되면 앱 시작 시 원격 로그/설정을 다시 받아와 자동 복구합니다.

설정 순서는 아래와 같습니다.

1. Supabase 프로젝트를 하나 생성합니다.
2. `supabase_schema.sql` 내용을 SQL Editor에서 실행합니다.
3. 로컬에서는 `.env`, Streamlit Cloud에서는 `.streamlit/secrets.toml` 또는 배포 Secrets에 아래 값을 넣습니다.

```toml
[persistence]
backend = "auto"
supabase_url = "https://YOUR_PROJECT.supabase.co"
supabase_key = "YOUR_KEY"
state_table = "lotto_app_state"
log_table = "lotto_log_records"
state_key = "main"
```

### 3) 앱 실행

```bash
streamlit run app.py
```

### 4) 데이터 업데이트 및 리포트 재생성

```bash
python update_lotto.py
```

## 속도 개선 포인트

이번 버전은 UI 문구와 디자인은 유지하면서, 버튼 클릭 이후 체감 지연을 줄이는 데 집중했습니다.

- `LottoPredictor`를 캐시해 동일한 `lotto.xlsx`를 다시 읽을 때 매번 전체 분석기를 새로 만들지 않도록 구성
- 번호별 gap 계수, 확률 가중치, 포지션 기본 가중치, pair 시너지 값을 미리 계산해 반복 연산을 줄임
- 추천 풀을 전체 정렬하는 대신, 중복 조합은 최고 점수만 유지하도록 정리해 메모리와 정렬 비용을 감소
- 기본 시뮬레이션 규모를 `10000 → 5000`으로 조정하되, 필요하면 환경 변수로 다시 상향 가능
- 원본 데이터 보기 화면에서도 Excel 재로딩을 캐시해 불필요한 디스크 I/O를 줄임

## 테스트

아래 명령으로 기본 스모크 테스트를 실행할 수 있습니다.

```bash
python -m unittest discover -s tests -v
```

테스트 항목은 다음을 확인합니다.

- 추천 엔진 핵심 함수 동작
- 로그인 화면 렌더링
- 인증 후 메인 대시보드 렌더링
- 삭제 요청 문구가 다시 나타나지 않는지 확인

## 로그 영구 보존 원칙

이 버전은 **로컬 캐시 + 원격 영구 저장소(Supabase)** 이중 구조를 기준으로 정리했습니다.

- 모든 운영 로그는 계속 `logs/`에 누적 저장됩니다.
- 앱 상태(`app_state.json`)와 로그 레코드는 Supabase가 설정되어 있으면 **원격에도 즉시 반영**됩니다.
- 앱이 슬립되거나 컨테이너가 재시작되면, 실행 초기에 **원격 상태를 다시 내려받아 로컬 JSONL/SQLite 캐시를 복구**합니다.
- 로그 분석 · 히스토리는 복구된 통합 이력을 기준으로 다시 집계됩니다.
- 자동 정리, 자동 삭제, 기간별 purge 정책은 두지 않는 것을 기본 원칙으로 합니다.
- Supabase 설정이 없으면 로컬 모드로 동작하지만, 이 경우 Streamlit Cloud 슬립/재시작 뒤 초기화될 수 있습니다.

## GitHub 업로드 전 체크 포인트

1. `.env.example`와 `.streamlit/secrets.toml.example`만 저장소에 올리고 실제 키는 커밋하지 마세요.
2. 영구 보존이 필요하면 `supabase_schema.sql`까지 함께 업로드해 배포 환경에서 바로 연결할 수 있게 두세요.
3. `logs/`와 `reports/`는 로컬 캐시/분석 산출물로 유지하되, **절대 보존 요구사항은 Supabase 연결을 기준으로 운영**하세요.
4. `lotto.xlsx`를 공개 저장소에 포함할지 운영 정책에 맞게 결정하세요.
5. 공개 배포 시 README 하단에 사용 범위와 라이선스를 명시하는 것을 권장합니다.

## 권장 운영 방식

- 로컬 개발: `streamlit run app.py`
- 수동 데이터 갱신: `python update_lotto.py`
- 배포 전 검증: `python -m unittest discover -s tests -v`
- 영구 보존 운영: Supabase 연결 후 Streamlit Cloud 배포
- GitHub 업로드: 코드 + `.env.example` + `.streamlit/secrets.toml.example` + `supabase_schema.sql` + 필요 시 `logs/`/`reports/`/`lotto.xlsx`

## 라이선스 / 사용 안내

별도 라이선스가 없다면 업로드 전에 원하는 라이선스를 추가하세요.  
상업적·재배포 정책이 있다면 README에 함께 명시하는 것을 권장합니다.


## 시뮬레이션 규모 수동 변경

- 위치: `로그 분석 · 히스토리` 화면
- 변경 방식: 비밀번호 입력 후 수동 변경
- 변경 비밀번호: `******`
- 반영 범위: 패턴 추천 / 확률 추천 공통
- 로그 보존: 기존 `logs/` 내부 운영 로그와 DB는 유지하고, 설정값만 런타임 상태에 반영

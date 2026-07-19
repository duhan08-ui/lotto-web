# 자동 스케줄러 설정 가이드

> **✅ 현재 권위 있는 스케줄 (GitHub Actions — 실제 운영 기준)**
>
> 실제 배포는 `.github/workflows/lotto_scheduler.yml` 로 동작하며, 시간 기준은
> 아래가 정확합니다. (본문 하단의 "오전 10시 / 저녁 6시" 설명은 과거
> standalone 스케줄러 기준의 기록으로, 현재 운영과 다를 수 있습니다.)
>
> | 트리거 | 시각(UTC) | 시각(KST) | 작업 |
> |--------|-----------|-----------|------|
> | 매일 cron | `0 0 * * *` | 09:00 | 일일 로그 생성 + 성능 분석 (`gha_daily.py`) |
> | 토요일 cron | `30 13 * * 6` | 22:30 | 당첨번호 수집 + 성능 분석 (`gha_saturday.py`) |
> | 수동 | - | - | `workflow_dispatch` (mode: daily/saturday/full) |
>
> Supabase 영구 저장을 쓰려면 저장소 Settings > Secrets and variables > Actions 에서
> `LOTTO_SUPABASE_URL`, `LOTTO_SUPABASE_KEY` 를 설정하세요. 미설정 시 워크플로우는
> 경고만 남기고 로컬 폴백으로 동작합니다.

## 📋 개요 (참고: 과거 standalone 스케줄러 설명)

이 가이드는 매일 저녁 6시에 자동으로 패턴/확률 번호 100개씩을 생성하고, 오전 10시에 AI 지능형 분석 리포트를 생성하는 스케줄러를 설정하는 방법을 설명합니다.

## 🔧 설정 방법

### 방법 1: Streamlit 앱 자동 실행 (권장)

**특징**: 사용자가 앱에 접속할 때마다 자동으로 스케줄 확인

1. **의존성 설치**
   ```bash
   pip install -r requirements.txt
   ```

2. **앱 실행**
   ```bash
   streamlit run app.py
   ```

**동작 원리**:
- 앱이 로드될 때마다 `schedule_manager.py`의 `check_and_run_if_needed()` 함수가 호출됨
- 현재 시간이 설정된 시간(오전 10시 또는 저녁 6시) 이후이고 평일(월~금)이면 자동 실행
- 오늘 이미 실행했으면 다시 실행하지 않음

**주의**: 사용자가 앱에 접속하지 않으면 작업이 실행되지 않음

---

## 📊 스케줄 설정 파일

자동 생성 설정은 다음 파일에 저장됩니다:
`logs/auto_schedule_config.json`

**설정 변경**:
- `enabled`: `false`로 설정하면 자동 생성 비활성화
- `run_time`: 번호 추출 시간 (기본 "18:00")
- `ai_report_time`: AI 리포트 생성 시간 (기본 "10:00")
- `prediction_count`: 패턴 추천 개수 (기본 100)
- `probability_count`: 확률 추천 개수 (기본 100)

---

## ⚠️ 문제 해결

### 1. 스케줄이 실행되지 않음

**확인 사항**:
- [ ] 현재 시간이 설정 시간 이후인가?
- [ ] 오늘이 평일(월~금)인가?
- [ ] 오늘 이미 한 번 실행했는가? (`logs/auto_schedule_config.json` 확인)
- [ ] `enabled` 설정이 `true`인가?

**테스트**:
```bash
python3 test_scheduler.py
```

---

**마지막 업데이트**: 2026년 4월

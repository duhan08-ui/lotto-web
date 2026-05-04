# 자동 스케줄러 설정 가이드

## 📋 개요

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

### 방법 2: 독립형 스케줄러 (백그라운드 실행)

**특징**: 사용자 접속 여부와 관계없이 항상 실행

#### 2-1. 로컬 테스트

```bash
python3 standalone_scheduler.py
```

이 명령어를 실행하면:
- 매일 오전 10시: AI 지능형 분석 리포트 생성
- 매일 저녁 6시: 패턴/확률 번호 100개씩 자동 생성
- 콘솔에 실시간 로그 표시 및 `logs/scheduler.log` 파일에 기록

#### 2-2. 백그라운드 실행 (Linux/Mac)

**nohup 사용**:
```bash
cd /path/to/project
nohup python3 standalone_scheduler.py > logs/scheduler.log 2>&1 &
```

**systemd 서비스 (권장)**:

1. 서비스 파일 생성:
   ```bash
   sudo nano /etc/systemd/system/analysis-scheduler.service
   ```

2. 다음 내용 입력 (경로 수정 필요):
   ```ini
   [Unit]
   Description=Auto Analysis Scheduler
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/lotto_project
   ExecStart=/usr/bin/python3 /home/ubuntu/lotto_project/standalone_scheduler.py
   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. 서비스 활성화 및 시작:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable analysis-scheduler
   sudo systemctl start analysis-scheduler
   ```

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

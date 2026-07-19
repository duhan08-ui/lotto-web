# 로또 웹 서비스 수정 사항 요약

## 수정 날짜
2026-04-29

## 수정 내용

### 1. 달력에 분석 요약 로그 추가 제거
**파일**: `analysis.py`
**변경 사항**: 
- `analyze_logs()` 함수에서 `persist_log_record(log_dir, "analysis", summary)` 호출을 주석 처리
- 분석 요약 로그가 더 이상 달력에 표시되지 않음
- 분석 요약 보고서는 여전히 생성됨

### 2. 평일 저녕 6시 자동 로그 생성 기능 추가

#### 새 파일 추가

**`auto_log_generator.py`**
- 달력 건수가 200건 미만일 때 자동으로 로그 생성
- 패턴추천(prediction) 100건 + 확률추천(probability) 100건 생성
- 무작위 번호 생성 및 점수 계산
- 기존 `log_utils.persist_log_record()` 함수 활용

**`schedule_manager.py`**
- 평일(월~금) 저녁 6시 스케줄 관리
- 중복 실행 방지 (하루에 한 번만 실행)
- 스케줄 설정 파일 (`logs/auto_schedule_config.json`) 관리
- `check_and_run_if_needed()` 함수로 스트림릿 앱에서 호출 가능

#### 수정 파일

**`app.py`**
- `schedule_manager` 모듈 임포트 추가
- `main()` 함수 초기화 부분에서 `check_and_run_if_needed()` 호출
- 자동 로그 생성 중 오류 발생 시 경고 메시지 표시

## 기술 사양

### 자동 로그 생성 로직
```
1. 달력 로그 건수 확인 (prediction, probability, manual만 카운트)
2. 200건 미만이면 필요한 건수 계산
3. 엑셀 파일에서 현재 회차(source_round) 추출
4. 패턴추천 로그 생성 (100건 또는 필요한 수)
5. 확률추천 로그 생성 (100건 또는 필요한 수)
6. 각 로그는 무작위 번호, 점수, gap factor, 확률 가중치 포함
```

### 스케줄 실행 조건
- 평일(월요일~금요일)
- 저녁 6시(18:00 ~ 18:59)
- 하루에 한 번만 실행 (마지막 실행 시간 기록)
- 스케줄이 활성화된 상태

### 스케줄 설정 파일 구조
```json
{
  "enabled": true,
  "target_log_count": 200,
  "prediction_count": 100,
  "probability_count": 100,
  "last_run": "2026-04-29T18:00:00+09:00",
  "last_run_success": true,
  "created_at": "2026-04-29T20:40:00+09:00"
}
```

## 테스트 결과
- ✓ Python 문법 검증 완료
- ✓ auto_log_generator.py 테스트 실행 성공
  - 현재 로그 35건 → 200건 목표로 165건 자동 생성
  - 패턴추천 82건 + 확률추천 83건 생성됨

## 배포 방법
1. 수정된 파일들을 기존 프로젝트에 덮어쓰기
2. 스트림릿 앱 재시작
3. 평일 저녁 6시에 자동 로그 생성 시작

## 주의 사항
- 스케줄은 스트림릿 앱이 실행 중일 때만 작동
- 시간대는 한국 시간(Asia/Seoul)으로 설정
- 자동 생성된 로그는 실제 당첨 번호와 무관한 시뮬레이션 데이터
- 스케줄 설정은 `logs/auto_schedule_config.json`에서 수정 가능

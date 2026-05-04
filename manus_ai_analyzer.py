import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# 프로젝트 경로 설정
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_DIR))

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(PROJECT_DIR / "logs" / "manus_ai.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("Manus_AI_Analyzer")

KST = ZoneInfo("Asia/Seoul")
MANUS_API_KEY = os.getenv("MANUS_API_KEY")
API_BASE_URL = "https://api.manus.ai/v2"

def get_latest_logs(limit=50):
    """최근 로그 데이터를 수집하여 텍스트로 변환 (크레딧 절약을 위해 데이터 제한)"""
    log_file = PROJECT_DIR / "logs" / "prediction_log.jsonl"
    if not log_file.exists():
        return "No logs available."
    
    logs = []
    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        # 최근 limit개의 로그만 가져옴
        for line in lines[-limit:]:
            try:
                data = json.loads(line)
                logs.append({
                    "round": data.get("target_round"),
                    "numbers": data.get("numbers"),
                    "score": data.get("score")
                })
            except:
                continue
    return json.dumps(logs, ensure_ascii=False)

def call_manus_api(prompt):
    """Manus API를 호출하여 분석 수행"""
    if not MANUS_API_KEY:
        logger.error("MANUS_API_KEY가 설정되지 않았습니다.")
        return "에러: API 키가 없습니다. .env 파일에 MANUS_API_KEY를 설정해주세요."

    headers = {
        "x-manus-api-key": MANUS_API_KEY,
        "Content-Type": "application/json"
    }

    # 1. 태스크 생성
    try:
        create_res = requests.post(
            f"{API_BASE_URL}/task.create",
            headers=headers,
            json={
                "message": {
                    "content": [{"type": "text", "text": prompt}]
                },
                "title": f"AI Analysis {datetime.now(KST).strftime('%Y-%m-%d')}"
            },
            timeout=30
        )
        create_data = create_res.json()
        if not create_data.get("ok"):
            return f"에러: 태스크 생성 실패 - {create_data.get('error', {}).get('message')}"
        
        task_id = create_data["task_id"]
        logger.info(f"Manus 태스크 생성됨: {task_id}")
    except Exception as e:
        return f"에러: API 호출 중 예외 발생 - {e}"

    # 2. 결과 폴링 (최대 5분)
    start_time = time.time()
    while time.time() - start_time < 300:
        try:
            list_res = requests.get(
                f"{API_BASE_URL}/task.listMessages",
                headers=headers,
                params={"task_id": task_id, "order": "desc", "limit": 1},
                timeout=20
            )
            list_data = list_res.json()
            if not list_data.get("ok"):
                time.sleep(10)
                continue
            
            messages = list_data.get("messages", [])
            for msg in messages:
                if msg.get("type") == "status_update" and msg.get("status_update", {}).get("agent_status") == "stopped":
                    # 태스크 완료됨, 마지막 메시지 찾기
                    full_list_res = requests.get(
                        f"{API_BASE_URL}/task.listMessages",
                        headers=headers,
                        params={"task_id": task_id, "order": "asc"},
                        timeout=20
                    )
                    full_messages = full_list_res.json().get("messages", [])
                    # 마지막 assistant_message 반환
                    for m in reversed(full_messages):
                        if m.get("type") == "assistant_message":
                            return m["assistant_message"]["content"]
            
            logger.info("Manus 분석 중... 기다리는 중...")
            time.sleep(15)
        except Exception as e:
            logger.warning(f"폴링 중 오류 발생: {e}")
            time.sleep(10)
            
    return "에러: 분석 시간이 초과되었습니다."

def run_manus_intelligent_analysis():
    """Manus API 기반 지능형 분석 실행"""
    logger.info("Manus API 기반 지능형 분석 시작...")
    
    # 최근 로그 데이터 준비
    log_summary = get_latest_logs(limit=30)
    
    # 프롬프트 구성 (크레딧 299개 제한 강조, '로또' 단어 삭제)
    prompt = f"""
당신은 번호 분석 전문가입니다. 제공된 최근 추천 로그 데이터를 바탕으로 다음 회차 1등 가능성이 가장 높은 번호 5세트를 추천해주세요.

[최근 분석 로그 데이터]
{log_summary}

[요청 사항]
1. 위 로그의 패턴, 확률, 점수 추이를 분석하여 가장 유망한 번호 5세트를 도출하세요.
2. 각 세트별로 왜 이 번호들이 선택되었는지 간단한 AI 분석 의견을 포함하세요.
3. 전체 분석 과정에서 크레딧 사용량이 299개를 넘지 않도록 간결하고 핵심적인 분석만 수행하세요.
4. 출력 형식은 한국어로, 사용자가 읽기 편한 마크다운 형식으로 작성하세요.

결과에는 반드시 '추천 번호 5세트'와 'AI 분석 요약'이 포함되어야 합니다.
"""

    result = call_manus_api(prompt)
    
    # 결과 저장
    report_path = PROJECT_DIR / "reports" / "weekly_ai_recommendation.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(result)
    
    logger.info("Manus API 분석 완료 및 보고서 저장 성공")
    return result

if __name__ == "__main__":
    # API 키가 있을 때만 실행 (테스트용)
    if MANUS_API_KEY:
        print(run_manus_intelligent_analysis())
    else:
        print("MANUS_API_KEY 환경 변수가 설정되지 않았습니다.")

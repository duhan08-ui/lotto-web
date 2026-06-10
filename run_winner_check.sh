#!/bin/bash
# 토요일 밤 자동 당첨 확인 스크립트
# crontab에 등록하여 사용
# crontab -e
# 0 21 * * 6 /path/to/lotto-project/run_winner_check.sh >> /path/to/lotto-project/logs/auto_check.log 2>&1

cd /home/user/lotto-app/lotto-project

echo $(date) >> logs/auto_check.log
echo '=== 자동 당첨 확인 시작 ===' >> logs/auto_check.log

# 수동 실행
python3 weekly_winner_checker.py >> logs/auto_check.log 2>&1

# 자동 스케줄러도 실행 ( демон 모드)
# python3 auto_weekly_checker.py --daemon &

echo '=== 완료 ===' >> logs/auto_check.log
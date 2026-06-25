#!/bin/bash
# ============================================================
# 로또 스케줄러 자동 실행 스크립트
# ============================================================
# 사용법: 
#   ./start_scheduler.sh          # 백그라운드 실행
#   ./start_scheduler.sh start    # 백그라운드 실행
#   ./start_scheduler.sh stop     # 중지
#   ./start_scheduler.sh status   # 상태 확인
#   ./start_scheduler.sh restart  # 재시작
# ============================================================

SCRIPT_DIR=$(cd $(dirname $0) && pwd)
PID_FILE=$SCRIPT_DIR/logs/scheduler.pid
LOG_FILE=$SCRIPT_DIR/logs/scheduler_daemon.log

# PID 검증 함수
check_pid() {
    local pid=$1
    if [ -n $pid ] && ps -p $pid > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

start_daemon() {
    # 이미 실행 중인지 확인
    if [ -f $PID_FILE ]; then
        OLD_PID=$(cat $PID_FILE)
        if check_pid $OLD_PID; then
            echo -e '\n⚠️  스케줄러가 이미 실행 중입니다 (PID: '$OLD_PID')\n'
            exit 0
        else
            rm -f $PID_FILE
        fi
    fi
    
    echo -e '\n🚀 로또 스케줄러 시작 중...'
    nohup python3 $SCRIPT_DIR/standalone_scheduler.py > $LOG_FILE 2>&1 &
    NEW_PID=$!
    echo $NEW_PID > $PID_FILE
    sleep 2
    
    if check_pid $NEW_PID; then
        echo -e '✅ 스케줄러가 시작되었습니다 (PID: '$NEW_PID')\n'
        echo '   로그 파일: '$LOG_FILE
        echo '   상태 확인: ./start_scheduler.sh status'
    else
        echo -e '❌ 스케줄러 시작 실패\n'
        if [ -f $LOG_FILE ]; then
            echo '   에러 로그 확인:'
            tail -10 $LOG_FILE
        fi
        exit 1
    fi
}

stop_daemon() {
    if [ ! -f $PID_FILE ]; then
        echo -e '\n⚠️  PID 파일이 없습니다. 스케줄러가 실행 중이 아닐 수 있습니다.\n'
        # 혹시 실행 중인 프로세스 찾기
        PIDS=$(pgrep -f 'standalone_scheduler.py' 2>/dev/null)
        if [ -n $PIDS ]; then
            echo '   실행 중인 스케줄러 프로세스: '$PIDS
            echo '   강제 종료 중...'
            pkill -f 'standalone_scheduler.py' 2>/dev/null
        fi
        exit 0
    fi
    
    OLD_PID=$(cat $PID_FILE)
    if check_pid $OLD_PID; then
        echo -e '\n🛑 스케줄러 중지 중... (PID: '$OLD_PID')\n'
        kill $OLD_PID 2>/dev/null
        sleep 2
        if check_pid $OLD_PID; then
            echo '   강제 종료 시도...'
            kill -9 $OLD_PID 2>/dev/null
        fi
        rm -f $PID_FILE
        echo -e '✅ 스케줄러가 중지되었습니다\n'
    else
        echo -e '\n⚠️  프로세스가 실행 중이 아닙니다\n'
        rm -f $PID_FILE
    fi
}

status_daemon() {
    echo -e '\n📌 로또 스케줄러 상태 확인'
    echo '========================================'
    
    if [ ! -f $PID_FILE ]; then
        echo '   상태: 중지됨 (PID 파일 없음)'
        # 혹시 실행 중인 프로세스 찾기
        PIDS=$(pgrep -f 'standalone_scheduler.py' 2>/dev/null)
        if [ -n $PIDS ]; then
            echo '   ⚠️  하지만 실행 중인 프로세스가 발견됨: '$PIDS
            echo '   PID 파일이 깨졌을 수 있습니다. 재시작을 추천합니다.'
        fi
        echo ''
        exit 0
    fi
    
    PID=$(cat $PID_FILE)
    if check_pid $PID; then
        echo '   상태: ✅ 실행 중'
        echo '   PID: '$PID
        echo ''
        
        # 스케줄러 로그 확인
        if [ -f $LOG_FILE ]; then
            echo '📋 최근 실행 로그 (마지막 10줄):'
            echo '----------------------------------------'
            tail -10 $LOG_FILE
            echo '----------------------------------------'
        fi
        
        # 설정 파일 확인
        CONFIG_FILE=$SCRIPT_DIR/logs/auto_schedule_config.json
        if [ -f $CONFIG_FILE ]; then
            echo ''
            echo '📊 스케줄 설정 상태:'
            echo '----------------------------------------'
            python3 -c '
import json
try:
    with open('\"$CONFIG_FILE\"') as f:
        config = json.load(f)
    print(f\"   enabled: {config.get('enabled', True)}\")
    print(f\"   manus_time: {config.get('manus_time', '06:00')}\")
    print(f\"   run_time: {config.get('run_time', '09:00')}\")
    print(f\"   last_manus_run: {config.get('last_manus_run', '없음')}\")
    print(f\"   last_run: {config.get('last_run', '없음')}\")
except Exception as e:
    print(f\"   설정 파일 읽기 실패: {e}\")
'
        fi
        echo ''
    else
        echo '   상태: ❌ 중지됨 (PID 파일만 존재)'
        echo '   PID: '$PID' (프로세스 없음)'
        echo ''
        echo '   💡 다음 명령으로 다시 시작하세요:'
        echo '      ./start_scheduler.sh start'
        rm -f $PID_FILE
        echo ''
    fi
}

restart_daemon() {
    echo '🔄 스케줄러 재시작 중...'
    stop_daemon
    sleep 1
    start_daemon
}

# 즉시 테스트 실행 (스케줄러가 실행 중이 아니어도 테스트 가능)
test_scheduler() {
    echo '🧪 스케줄러 테스트 모드 실행...'
    python3 $SCRIPT_DIR/standalone_scheduler.py --once
}

case $1 in
    stop)
        stop_daemon
        ;;
    status)
        status_daemon
        ;;
    restart)
        restart_daemon
        ;;
    test)
        test_scheduler
        ;;
    start|*)
        start_daemon
        ;;
esac
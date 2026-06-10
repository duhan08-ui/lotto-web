# -*- coding: utf-8 -*-
"""
log_watcher.py — 로그 파일 실시간 감시 → AI 지능형 추천 자동 재실행

■ 동작 방식
  1. logs/ 디렉토리의 prediction_log.jsonl / probability_log.jsonl 감시
  2. 파일이 변경(새 로그 추가)되면 DEBOUNCE_SECONDS(5초) 대기
     → 300개 로그가 연속으로 쌓여도 마지막 변경 후 5초 뒤 한 번만 실행
  3. 대기 후 ai_intelligent_analyzer.run_analysis() 호출 → TOP5 즉시 갱신
  4. MIN_INTERVAL_SECONDS(60초=1분) 이내 재실행 방지
     → 로그가 폭발적으로 쌓여도 최소 1분 간격 보장

■ 사용법 (단독 실행)
  python3 log_watcher.py          # 감시 시작
  python3 log_watcher.py --test   # 즉시 1회 실행 후 종료

■ standalone_scheduler.py 통합 시
  LogWatcher(PROJECT_DIR).start()  # 데몬 스레드로 실행
"""

import logging
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

# watchdog
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False

# 프로젝트 경로
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

KST              = timezone(timedelta(hours=9))
DEBOUNCE_SECONDS = 5     # 로그 변경 후 이 시간 대기 후 실행 (연속 변경 묶음)
                         # 300개 로그가 짧은 시간에 쌓이므로 5초면 충분히 묶임
MIN_INTERVAL_SECONDS = 60   # 최소 재실행 간격 (1분) — 로그 폭발 시 과부하 방지

logger = logging.getLogger('LogWatcher')


# ─── Watchdog 이벤트 핸들러 ───────────────────────────────────────────────────
class LogFileHandler(FileSystemEventHandler):
    """
    logs/ 디렉토리에서 prediction_log.jsonl / probability_log.jsonl 변경 감지.
    변경 이벤트 발생 시 debounce 타이머를 재설정하고, 타이머 만료 시 분석 실행.
    """

    WATCH_FILES = {'prediction_log.jsonl', 'probability_log.jsonl', 'manual_score_log.jsonl'}

    def __init__(self, watcher: 'LogWatcher'):
        super().__init__()
        self._watcher   = watcher
        self._timer     = None
        self._lock      = threading.Lock()

    def on_modified(self, event):
        if event.is_directory:
            return
        fname = Path(event.src_path).name
        if fname in self.WATCH_FILES:
            logger.debug('[감지] %s 변경됨 → debounce 타이머 재설정 (%ds)' % (fname, DEBOUNCE_SECONDS))
            self._reset_debounce()

    on_created = on_modified   # 새 파일 생성도 동일 처리

    def _reset_debounce(self):
        """debounce 타이머 재설정 — 연속 이벤트를 하나로 묶음"""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._watcher._trigger_analysis)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ─── LogWatcher ──────────────────────────────────────────────────────────────
class LogWatcher:
    """
    로그 파일 감시 + AI 지능형 추천 자동 재실행 관리자.

    사용법:
        watcher = LogWatcher(project_dir)
        watcher.start()   # 백그라운드 스레드에서 실행
        ...
        watcher.stop()    # 종료
    """

    def __init__(self, project_dir: Path):
        self.project_dir  = Path(project_dir)
        self.log_dir      = self.project_dir / 'logs'
        self._observer    = None
        self._handler     = None
        self._last_run_ts = 0.0   # 마지막 실행 timestamp
        self._running     = False

    # ── 분석 실행 (debounce 완료 후 호출) ─────────────────────────────────
    def _trigger_analysis(self):
        """MIN_INTERVAL_SECONDS 제한 확인 후 run_analysis 호출"""
        now_ts = time.time()
        elapsed = now_ts - self._last_run_ts

        if elapsed < MIN_INTERVAL_SECONDS:
            remain = int(MIN_INTERVAL_SECONDS - elapsed)
            logger.info('[LogWatcher] 최소 간격(%ds) 미달 — %d초 후 재시도 가능' % (
                MIN_INTERVAL_SECONDS, remain))
            return

        now_kst = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        logger.info('=' * 60)
        logger.info('[LogWatcher] 로그 변경 감지 → AI 지능형 추천 재실행')
        logger.info('[LogWatcher] 실행 시각: %s KST' % now_kst)
        logger.info('=' * 60)

        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                'ai_intelligent_analyzer',
                self.project_dir / 'ai_intelligent_analyzer.py'
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            analyzer = module.AIIntelligentAnalyzer(self.project_dir)
            result   = analyzer.run_analysis()

            self._last_run_ts = time.time()

            # 결과 요약 로그
            for line in result.splitlines():
                if '순위:' in line or 'CompositeScore' in line or '생성일시' in line or '로그 반영' in line:
                    logger.info('[LogWatcher] %s' % line.strip())

            logger.info('[LogWatcher] AI 지능형 추천 갱신 완료')

        except Exception as e:
            logger.error('[LogWatcher] 분석 실행 실패: %s' % e, exc_info=True)

        logger.info('=' * 60)

    # ── 시작 ─────────────────────────────────────────────────────────────
    def start(self, daemon: bool = True):
        """
        watchdog Observer를 백그라운드 스레드로 시작.
        daemon=True(기본): 메인 프로세스 종료 시 자동 종료.
        """
        if not WATCHDOG_AVAILABLE:
            logger.error('[LogWatcher] watchdog 패키지가 없습니다. '
                         'pip install watchdog 로 설치하세요.')
            return False

        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._handler  = LogFileHandler(self)
        self._observer = Observer()
        self._observer.schedule(self._handler, str(self.log_dir), recursive=False)
        self._observer.daemon = daemon
        self._observer.start()
        self._running = True

        logger.info('[LogWatcher] 감시 시작: %s' % self.log_dir)
        logger.info('[LogWatcher] 대상 파일: prediction_log.jsonl, probability_log.jsonl')
        logger.info('[LogWatcher] debounce: %ds / 최소 재실행 간격: %ds' % (
            DEBOUNCE_SECONDS, MIN_INTERVAL_SECONDS))
        return True

    # ── 정지 ─────────────────────────────────────────────────────────────
    def stop(self):
        if self._handler:
            self._handler.cancel()
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=5)
        self._running = False
        logger.info('[LogWatcher] 감시 종료')

    @property
    def is_running(self) -> bool:
        return self._running and self._observer is not None and self._observer.is_alive()

    # ── 단독 실행 (blocking) ──────────────────────────────────────────────
    def run_forever(self):
        """단독 실행 시 blocking 루프"""
        import signal

        def _stop(sig, frame):
            logger.info('[LogWatcher] 종료 신호 수신')
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGINT,  _stop)
        signal.signal(signal.SIGTERM, _stop)

        if not self.start(daemon=False):
            sys.exit(1)

        logger.info('[LogWatcher] 감시 중... (Ctrl+C로 종료)')
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


# ─── 단독 실행 ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(PROJECT_DIR / 'logs' / 'log_watcher.log', encoding='utf-8'),
            logging.StreamHandler(),
        ]
    )

    import argparse
    parser = argparse.ArgumentParser(description='로그 파일 감시 → AI 지능형 추천 자동 재실행')
    parser.add_argument('--test', action='store_true', help='즉시 1회 실행 후 종료')
    args = parser.parse_args()

    watcher = LogWatcher(PROJECT_DIR)

    if args.test:
        logger.info('[LogWatcher] 테스트 모드: 즉시 1회 실행')
        watcher._trigger_analysis()
    else:
        watcher.run_forever()

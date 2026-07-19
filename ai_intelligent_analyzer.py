# -*- coding: utf-8 -*-
"""
AI 지능형 추천 분석기 (v3.4 - "매일 동일한 TOP5" 고착 문제 근본 수정)

■ v3.3까지도 TOP5가 매일 동일했던 근본 원인 (검증 완료)
  1. _build_log_stats가 조합 단위로 중복 제거(seen_keys)
     → 매일 300건이 쌓여도 유사 조합 반복이면 통계 무변화
  2. L1이 "상위 15개 번호 집합" 포함 여부만 평가
     → 누적될수록 top15 집합이 수렴(대수의 법칙)하여 며칠 만에 고정
  3. StatScore(60%)는 lotto.xlsx 기반 → 주간 추첨 전까지 완전 고정
     → 고정 점수 함수의 argmax는 후보 풀이 무작위여도 동일한 답
  4. is_intelligent(자기 추천) 체크가 카운팅 "이후"에 있어
     자기 추천이 로그 통계에 섞이는 자기 강화 루프 존재

■ v3.4 해결 설계
  [A] 최신성 가중 (Recency Weighting, 반감기 2일)
      각 로그 레코드에 w = 0.5^(경과일/2) 가중 → 오늘 쌓인 300건이
      과거 로그보다 항상 큰 영향력 → 매일 통계가 실제로 변동
  [B] 조합 중복 제거 폐지
      같은 조합이 반복 생성되는 것 자체가 신호 → 가중 빈도로 반영
  [C] L1 연속화
      집합 포함 비율(이산) → 정규화 가중 빈도의 평균(연속)
      → 빈도 미세 변화가 점수에 즉시 반영
  [D] L3 신규성(Novelty) 도입
      직전 추천(이전 is_intelligent TOP5)과의 중복도 패널티
      → 어제와 동일한 조합이 또 1순위가 되는 것을 구조적으로 차단
  [E] 자기 강화 루프 차단
      is_intelligent 레코드는 빈도/동반출현 카운팅에서 완전 제외

■ 점수 산출 공식 (CompositeScore v3)
  CompositeScore = α·StatScore + β·LogScore
    α = 0.60, β = 0.40

  StatScore (lotto.xlsx 기반, 회차 내 고정):
    S1 GapDue, S2 CoOccur, S3 SumFit, S4 TailBalance,
    S5 ZoneEntropy, S6 Markov, S7 FreqBalance (동적 LOO 가중)

  LogScore (회차 누적 로그 기반, 최신 로그 가중 → 매일 변동):
    L1 LogFreq   = mean( 최신성 가중 정규화 빈도 )          (0.40)
    L2 LogCooc   = mean( 최신성 가중 정규화 동반출현 )       (0.40)
    L3 Novelty   = 1 - 직전 추천과의 최대 중복 수 / 6        (0.20)
"""

import json
import math
import random
import pandas as pd
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone, timedelta
from itertools import combinations

# ─── 상수 ────────────────────────────────────────────────────────────────────
UNIVERSE             = list(range(1, 46))
N_UNIVERSE           = 45
N_DRAW               = 6
TOP_K                = 5
SIMILARITY_THRESHOLD = 4      # 자카드 기준: 이 이상 겹치면 유사
CANDIDATE_POOL       = 15000
BACKTEST_WINDOW      = 50
MIN_WEIGHT           = 0.05
ALPHA                = 0.60   # StatScore 비중
BETA                 = 0.40   # LogScore 비중
RECENCY_HALF_LIFE    = 2.0    # 로그 최신성 가중 반감기 (일) - 2일 지나면 영향력 절반
KST                  = timezone(timedelta(hours=9))
# FIX3: 끝자리별 실제 번호 개수 기반 기대 출현율 (1~45 기준)
# 끝자리 0: 10,20,30,40 → 4개(8.89%), 끝자리 1~5: 5개(11.11%), 6~9: 4개(8.89%)
_TAIL_EXPECTED       = {t: sum(1 for n in range(1, 46) if n % 10 == t) / 45
                        for t in range(10)}


def _mean(lst):   return sum(lst) / len(lst) if lst else 0.0
def _std(lst):
    if len(lst) < 2: return 1.0
    m = _mean(lst)
    return math.sqrt(sum((x - m) ** 2 for x in lst) / len(lst)) or 1.0
def _safe_log(x): return math.log(max(x, 1e-12))


# ─── 메인 클래스 ──────────────────────────────────────────────────────────────
class AIIntelligentAnalyzer:
    def __init__(self, project_dir):
        self.project_dir     = Path(project_dir)
        self.lotto_xlsx      = self.project_dir / 'lotto.xlsx'
        self.prediction_log  = self.project_dir / 'logs' / 'prediction_log.jsonl'
        self.probability_log = self.project_dir / 'logs' / 'probability_log.jsonl'
        # FIX3: manual_score_log도 L1~L3 계산에 포함 (300개 전체 반영)
        self.manual_log      = self.project_dir / 'logs' / 'manual_score_log.jsonl'
        self.universe        = UNIVERSE
        self._rng            = random.Random()  # 시드 없음 → 매 실행 다른 샘플

    # ── 1. 데이터 로드 ────────────────────────────────────────────────────────
    def _load_rows(self):
        if not self.lotto_xlsx.exists():
            return []
        try:
            df = pd.read_excel(self.lotto_xlsx)
            if df.empty: return []
            # [v3.4 FIX] lotto.xlsx는 오름차순(첫 행=1회차)으로 저장되어 있으나
            # 본 클래스 전체는 rows[0]=최신 회차를 가정함 (latest_row, gap, rows[:window] 등)
            # → 회차 기준 내림차순 정렬로 가정을 보장
            if '회차' in df.columns:
                df = df.sort_values('회차', ascending=False).reset_index(drop=True)
            else:
                df = df.iloc[::-1].reset_index(drop=True)
            if all(f'번호{i}' in df.columns for i in range(1, 7)):
                cols = [f'번호{i}' for i in range(1, 7)]
            else:
                cols = sorted(
                    [c for c in df.columns if str(c).startswith('번호')],
                    key=lambda x: int(''.join(ch for ch in str(x) if ch.isdigit()) or '999')
                )[:6]
            if len(cols) < 6: return []
            rows = []
            for _, row in df.iterrows():
                try:
                    nums = sorted(int(row[c]) for c in cols if 1 <= int(row[c]) <= 45)
                    if len(nums) == 6:
                        rows.append(nums)
                except Exception:
                    continue
            return rows  # rows[0] = 최신 회차
        except Exception:
            return []

    # ── 2. lotto.xlsx 기반 통계 빌드 ──────────────────────────────────────────
    def _build_stats(self, rows):
        if not rows: return {}
        total    = len(rows)
        all_nums = [n for row in rows for n in row]
        freq     = Counter(all_nums)
        fv       = [freq.get(n, 0) for n in UNIVERSE]
        mu_freq  = _mean(fv); sig_freq = _std(fv)

        # Gap 통계
        last_seen   = {}
        gap_history = {n: [] for n in UNIVERSE}
        for idx, row in enumerate(reversed(rows)):
            rno = idx + 1
            for n in row:
                if n in last_seen: gap_history[n].append(rno - last_seen[n])
                last_seen[n] = rno
        current_gap = {n: (total - last_seen[n] + 1) if n in last_seen else (total + 1)
                       for n in UNIVERSE}
        mu_gap  = {n: _mean(gap_history[n]) if gap_history[n] else N_UNIVERSE / N_DRAW
                   for n in UNIVERSE}
        sig_gap = {n: _std(gap_history[n]) if len(gap_history[n]) > 1 else mu_gap[n] * 0.3
                   for n in UNIVERSE}
        due_score = {n: (current_gap[n] - mu_gap[n]) / max(sig_gap[n], 1.0) for n in UNIVERSE}

        # Co-occurrence PMI
        window   = min(total, 200)
        cooc_cnt = {}
        appear_cnt = {n: 0 for n in UNIVERSE}      # window 내 '등장 회차 수'
        for row in rows[:window]:
            rset = set(row)
            for n in rset:
                appear_cnt[n] += 1
            for a, b in combinations(sorted(rset), 2):
                cooc_cnt[(a, b)] = cooc_cnt.get((a, b), 0) + 1
        # FIX7: PMI 확률 공간 통일 — marginal 도 결합확률과 같은 window 기준
        #       '회차당 등장확률'로 계산(기존: 전체 freq를 슬롯수로 나눠 공간 불일치).
        #       p(n)=등장회차수/window, p(a,b)=동반회차수/window → 표준 PMI.
        w = max(window, 1)
        p_n = {n: (appear_cnt[n] + 0.5) / (w + 1.0) for n in UNIVERSE}   # Laplace 평활
        pmi_norm = _safe_log(w)   # 희귀쌍(1회 동반) 이론적 최댓값 ≈ log(window) → 0~1 정규화 기준
        cooc_pmi = {}
        for (a, b), cnt in cooc_cnt.items():
            p_ab = cnt / w
            pmi  = _safe_log(p_ab / max(p_n[a] * p_n[b], 1e-12))
            cooc_pmi[(a, b)] = pmi; cooc_pmi[(b, a)] = pmi

        # 합계 분포
        sum_vals = [sum(row) for row in rows[:window]]
        mu_sum = _mean(sum_vals); sig_sum = _std(sum_vals)

        # 끝자리 빈도
        tail_cnt   = Counter(n % 10 for n in all_nums)
        tail_total = sum(tail_cnt.values()) or 1
        tail_prob  = {t: tail_cnt.get(t, 0) / tail_total for t in range(10)}

        # 마르코프 전이
        transition    = {n: Counter() for n in UNIVERSE}
        for i in range(len(rows) - 1):
            prev, curr = rows[i + 1], rows[i]
            for pn in prev:
                for cn in curr: transition[pn][cn] += 1
        latest_row    = rows[0] if rows else []
        markov_weight = {n: 0.0 for n in UNIVERSE}
        if latest_row:
            for pn in latest_row:
                tot = sum(transition[pn].values()) or 1
                for n in UNIVERSE: markov_weight[n] += transition[pn].get(n, 0) / tot
            mw_max = max(markov_weight.values()) or 1.0
            markov_weight = {n: v / mw_max for n, v in markov_weight.items()}

        return {
            'total_rounds': total, 'freq': freq,
            'mu_freq': mu_freq, 'sigma_freq': sig_freq,
            'due_score': due_score, 'cooc_pmi': cooc_pmi,
            'mu_sum': mu_sum, 'sig_sum': sig_sum,
            'tail_prob': tail_prob, 'markov_weight': markov_weight,
            'latest_row': latest_row, 'pmi_norm': pmi_norm,
        }

    # ── 3. 회차 기준 로그 통계 빌드 (★ 최신성 가중, v3.4) ─────────────────────
    def _recency_weight(self, ts, now_utc):
        """로그 타임스탬프 기준 최신성 가중치: 0.5^(경과일 / 반감기)"""
        try:
            dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_days = max((now_utc - dt).total_seconds() / 86400.0, 0.0)
            return 0.5 ** (age_days / RECENCY_HALF_LIFE)
        except Exception:
            return 0.5  # 타임스탬프 파싱 불가 시 중립 가중

    def _build_log_stats(self, target_round: int) -> dict:
        """
        축적 로그를 활용해 LogScore 재료를 생성.
        - 1차: target_round 일치 로그만 사용
        - fallback: 현재 회차 로그 < 30건이면 전체 회차 로그 모두 활용

        v3.4 핵심 변경:
        - [B] 조합 중복 제거(seen_keys) 폐지: 반복 생성도 신호로 반영
        - [A] 레코드별 최신성 가중(반감기 2일): 오늘 로그 > 과거 로그
          → 매일 300건이 쌓일 때마다 log_freq / log_cooc가 실제로 변동
        - [E] is_intelligent(자기 추천) 레코드는 카운팅에서 완전 제외
          (기존 v3.3은 카운팅 후에 제외해 자기 강화 루프가 존재했음)
        """
        now_utc   = datetime.now(timezone.utc)
        today_kst = datetime.now(KST).strftime('%Y-%m-%d')

        def _collect(filter_round):
            num_cnt   = Counter()   # float 가중 빈도
            cooc_cnt  = Counter()   # float 가중 동반출현
            score_map: dict[tuple, float] = {}
            total     = 0           # 반영된 레코드 수 (중복 포함)
            today_cnt = 0           # 오늘(KST) 신규 레코드 수

            for log_path in (self.prediction_log, self.probability_log, self.manual_log):
                if not log_path.exists(): continue
                try:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line: continue
                            try:
                                data = json.loads(line)
                                # [E] 자기 추천(is_intelligent)은 통계에서 완전 제외
                                #     → 자기 강화 루프 차단 (v3.3 버그 수정)
                                if data.get('is_intelligent'):
                                    continue
                                log_tr = data.get('target_round') or data.get('source_round', 0)
                                if filter_round and log_tr != filter_round:
                                    continue
                                nums = data.get('numbers')
                                if not (nums and len(nums) == 6): continue
                                nums_clean = sorted(int(n) for n in nums if 1 <= int(n) <= 45)
                                if len(nums_clean) != 6: continue

                                ts = data.get('timestamp') or data.get('logged_at_utc')
                                w  = self._recency_weight(ts, now_utc)

                                # [A][B] 중복 제거 없이 최신성 가중 누적
                                for n in nums_clean:
                                    num_cnt[n] += w
                                for a, b in combinations(nums_clean, 2):
                                    cooc_cnt[(min(a, b), max(a, b))] += w
                                total += 1
                                try:
                                    dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                                    if dt.tzinfo is None:
                                        dt = dt.replace(tzinfo=timezone.utc)
                                    if dt.astimezone(KST).strftime('%Y-%m-%d') == today_kst:
                                        today_cnt += 1
                                except Exception:
                                    pass

                                key   = tuple(nums_clean)
                                score = float(data.get('score', 0) or 0)
                                if score > 0 and (key not in score_map or score > score_map[key]):
                                    score_map[key] = score
                            except Exception:
                                continue
                except Exception:
                    continue
            return num_cnt, cooc_cnt, score_map, total, today_cnt

        # 1차: 현재 회차 로그
        num_cnt, cooc_cnt, score_map, total, today_cnt = _collect(target_round)

        # fallback: 현재 회차 로그가 30건 미만이면 전체 회차 로그 활용
        if total < 30:
            num_cnt, cooc_cnt, score_map, total, today_cnt = _collect(None)

        if not total:
            return {
                'log_freq': {}, 'log_cooc': {},
                'log_top_nums': set(), 'log_score_map': {},
                'log_total': 0, 'log_today': 0, 'prev_sets': [],
            }

        max_nc = max(num_cnt.values()) or 1.0
        log_freq = {n: v / max_nc for n, v in num_cnt.items()}
        max_cc = max(cooc_cnt.values()) or 1.0
        log_cooc = {k: v / max_cc for k, v in cooc_cnt.items()}
        log_top_nums = {n for n, _ in num_cnt.most_common(15)}  # 리포트 표기용
        if score_map:
            max_sc = max(score_map.values()) or 1.0
            log_score_map = {k: v / max_sc for k, v in score_map.items()}
        else:
            log_score_map = {}

        return {
            'log_freq': log_freq, 'log_cooc': log_cooc,
            'log_top_nums': log_top_nums,
            'log_score_map': log_score_map,
            'log_total': total,
            'log_today': today_cnt,
            'prev_sets': [],   # run_analysis에서 직전 추천 조합 주입
        }

    # ── 4. 7개 StatScore 지표 ─────────────────────────────────────────────────
    def _s1_gap_due(self, nums, stats):
        due = stats.get('due_score', {})
        raw = _mean([due.get(n, 0.0) for n in nums])
        return 1.0 / (1.0 + math.exp(-raw * 0.5))

    def _s2_cooccur(self, nums, stats):
        pmi   = stats.get('cooc_pmi', {})
        pairs = list(combinations(sorted(nums), 2))
        if not pairs: return 0.5
        # FIX7: 정규화 기준을 window 기반 이론적 최댓값(log(window))으로 통일
        norm = max(stats.get('pmi_norm', 9.0), 1e-9)
        return min(_mean([max(pmi.get((a,b), 0.0), 0.0) for a,b in pairs]) / norm, 1.0)

    def _s3_sum_fit(self, nums, stats):
        mu  = stats.get('mu_sum', 138.0)
        sig = stats.get('sig_sum',  30.0)
        return math.exp(-((sum(nums) - mu) ** 2) / (2 * sig ** 2))

    def _s4_tail_balance(self, nums, stats):
        tails = [n % 10 for n in nums]
        cnt   = Counter(tails); total = len(tails)
        entropy = -sum((c/total)*_safe_log(c/total) for c in cnt.values())
        max_h   = _safe_log(len(cnt)) if len(cnt) > 1 else 1.0
        # FIX3: 끝자리 기대 출현율을 균등 가정(1/10) 대신 실제 분포(_TAIL_EXPECTED) 사용
        # 기존: max(1.0 - tail_prob[t]*10, 0.0) → 끝자리 0은 4개(8.9%), 1~5는 5개(11.1%)인데
        #       균등(10%)으로 가정하여 희귀도 판단이 왜곡됨
        # 수정: tail_prob[t] / _TAIL_EXPECTED[t] 비율로 희귀도 평가
        tail_prob = stats.get('tail_prob', {})
        bonus = _mean([
            max(1.0 - tail_prob.get(t, _TAIL_EXPECTED[t]) / _TAIL_EXPECTED[t], 0.0)
            for t in tails
        ])
        return (entropy/max_h if max_h > 0 else 0.5)*0.75 + bonus*0.25

    def _s5_zone_entropy(self, nums, stats):
        zones = [0]*5
        for n in nums: zones[(n-1)//9] += 1
        entropy = sum(-z/N_DRAW*_safe_log(z/N_DRAW) for z in zones if z > 0)
        return entropy / _safe_log(5)

    def _s6_markov(self, nums, stats):
        mw = stats.get('markov_weight', {})
        return _mean([mw.get(n, 0.0) for n in nums])

    def _s7_freq_balance(self, nums, stats):
        freq  = stats.get('freq', {}); mu = stats.get('mu_freq',1.0); sigma = stats.get('sigma_freq',1.0)
        z_sq  = [((freq.get(n,0)-mu)/sigma)**2 for n in nums]
        return math.exp(-_mean(z_sq)/2.0)

    def _stat_score(self, nums, stats, weights):
        """StatScore = Σ(wᵢ × Sᵢ)  i=1..7"""
        scores = {
            's1': self._s1_gap_due(nums, stats),
            's2': self._s2_cooccur(nums, stats),
            's3': self._s3_sum_fit(nums, stats),
            's4': self._s4_tail_balance(nums, stats),
            's5': self._s5_zone_entropy(nums, stats),
            's6': self._s6_markov(nums, stats),
            's7': self._s7_freq_balance(nums, stats),
        }
        return sum(scores[k] * weights.get(k, 1/7) for k in scores)

    # ── 5. LogScore 지표 (★ 최신성 가중 + 신규성, v3.4) ──────────────────────
    def _l1_log_freq(self, nums, log_stats):
        """L1: 최신성 가중 정규화 빈도의 평균 (연속값)
        v3.3의 '상위 15개 집합 포함 비율'은 누적될수록 집합이 수렴해 고정됐음.
        연속 빈도 평균은 매일 쌓이는 로그의 미세 변화가 점수에 즉시 반영됨."""
        lf = log_stats.get('log_freq', {})
        if not lf: return 0.5
        return _mean([lf.get(n, 0.0) for n in nums])

    def _l2_log_cooc_hit(self, nums, log_stats):
        """L2: 최신성 가중 동반출현 페어 점수 평균"""
        lc    = log_stats.get('log_cooc', {})
        if not lc: return 0.5
        pairs = list(combinations(sorted(nums), 2))
        vals  = [lc.get((min(a,b), max(a,b)), 0.0) for a, b in pairs]
        return _mean(vals)

    def _l3_novelty(self, nums, log_stats):
        """L3: 직전 추천(이전 is_intelligent TOP5)과의 신규성
        직전 추천과 최대 중복 수가 적을수록 높은 점수.
        → 어제와 똑같은 조합이 또 1순위가 되는 것을 구조적으로 차단."""
        prev = log_stats.get('prev_sets') or []
        if not prev: return 0.5  # 직전 추천 없으면 중립
        max_ov = max(len(set(nums) & set(p)) for p in prev)
        return 1.0 - max_ov / 6.0

    def _log_score(self, nums, log_stats):
        """
        LogScore = L1*0.40 + L2*0.40 + L3*0.20
        - L1/L2: 최신성 가중 통계 → 매일 신규 로그 300건이 점수를 실제로 움직임
        - L3: 직전 추천 대비 신규성 → 일자별 순위 변동 구조적 보장
        """
        l1 = self._l1_log_freq(nums, log_stats)
        l2 = self._l2_log_cooc_hit(nums, log_stats)
        l3 = self._l3_novelty(nums, log_stats)
        return l1 * 0.40 + l2 * 0.40 + l3 * 0.20

    # ── 6. 최종 종합 점수 ─────────────────────────────────────────────────────
    def _composite_score(self, nums, stats, weights, log_stats):
        """
        CompositeScore = ALPHA·StatScore + BETA·LogScore
          ALPHA=0.60 : lotto.xlsx 기반 (회차 고정)
          BETA =0.40 : 회차 누적 로그 기반 L1+L2 (로그 증가마다 변동) ← 순위 변동 보장
        """
        ss = self._stat_score(nums, stats, weights)
        ls = self._log_score(nums, log_stats)
        return round(ss * ALPHA + ls * BETA, 6)

    # ── 7. 동적 앙상블 가중치 (LOO 백테스트) ──────────────────────────────────
    def _build_dynamic_weights(self, rows, stats):
        """
        FIX5: LOO 데이터 누수 수정
              기존: rows 전체로 stats 빌드 후 rows[idx]를 같은 stats로 평가
                    → rows[idx] 자신이 통계에 포함되어 hit_rate 과대평가
              수정: rows[idx]를 제외한 나머지로 stats_loo 재빌드 후 평가
        FIX6: n_random 20 → 100
              기존: 랜덤 비교 대상 20개 → 시드 간 hit_rate 분산 최대 0.05
              수정: 100개 → 분산 0.01 이하로 안정화
        """
        hit_rates = {f's{i}': [] for i in range(1, 8)}
        sample    = min(BACKTEST_WINDOW, len(rows) - 1)
        rng       = random.Random(42)

        for idx in range(sample):
            actual = rows[idx]
            # FIX5: 평가 대상(rows[idx]) 제외한 나머지로 통계 재빌드
            rows_loo  = [r for i, r in enumerate(rows) if i != idx]
            stats_loo = self._build_stats(rows_loo) if rows_loo else stats

            scorers_loo = {
                's1': lambda n, s=stats_loo: self._s1_gap_due(n, s),
                's2': lambda n, s=stats_loo: self._s2_cooccur(n, s),
                's3': lambda n, s=stats_loo: self._s3_sum_fit(n, s),
                's4': lambda n, s=stats_loo: self._s4_tail_balance(n, s),
                's5': lambda n, s=stats_loo: self._s5_zone_entropy(n, s),
                's6': lambda n, s=stats_loo: self._s6_markov(n, s),
                's7': lambda n, s=stats_loo: self._s7_freq_balance(n, s),
            }
            # FIX6: n_random 20 → 100
            randoms = [sorted(rng.sample(UNIVERSE, 6)) for _ in range(100)]
            for key, fn in scorers_loo.items():
                a_sc = fn(actual)
                hit_rates[key].append(sum(1 for r in randoms if a_sc > fn(r)) / 100.0)

        raw   = {k: _mean(v) for k, v in hit_rates.items()}
        total = sum(raw.values()) or 1.0
        w     = {k: max(v / total, MIN_WEIGHT) for k, v in raw.items()}
        wt    = sum(w.values())
        return {k: v / wt for k, v in w.items()}

    # ── 8. 후보 풀 생성 ───────────────────────────────────────────────────────
    def _sample_candidates(self, stats, target_round):
        due    = stats.get('due_score', {n: 0.0 for n in UNIVERSE})
        mw     = stats.get('markov_weight', {n: 0.0 for n in UNIVERSE})
        freq   = stats.get('freq', {}); mu_f = stats.get('mu_freq', 1.0)
        due_min = min(due.values()); due_rng = (max(due.values()) - due_min) or 1.0
        due_norm = {n: (due[n] - due_min) / due_rng for n in UNIVERSE}
        fi     = {n: 1.0 / max(freq.get(n, 0.5) / mu_f, 0.1) for n in UNIVERSE}
        fi_max = max(fi.values()) or 1.0; fi_norm = {n: v/fi_max for n,v in fi.items()}
        sw     = [max(due_norm[n]*0.30 + mw.get(n,0.0)*0.25 + fi_norm[n]*0.25 + 0.20, 0.01)
                  for n in UNIVERSE]
        candidates = {}
        for _ in range(CANDIDATE_POOL):
            drawn  = self._rng.choices(UNIVERSE, weights=sw, k=14)
            unique = list(dict.fromkeys(drawn))[:6]
            if len(unique) < 6: continue
            key = tuple(sorted(unique))
            if key not in candidates: candidates[key] = None

        # 로그 후보 (target_round 필터, 부족 시 전체 회차 fallback)
        # FIX3: manual_score_log도 후보 풀에 포함
        def _add_log_candidates(filter_round):
            added = 0
            for log_path in (self.prediction_log, self.probability_log, self.manual_log):
                if not log_path.exists(): continue
                try:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if not line: continue
                            try:
                                data   = json.loads(line)
                                # 자기 추천(is_intelligent)은 후보 풀에서 제외
                                # → 직전 추천이 후보로 재진입해 고착되는 것 방지
                                if data.get('is_intelligent'):
                                    continue
                                log_tr = data.get('target_round') or data.get('source_round', 0)
                                if filter_round and log_tr != filter_round: continue
                                nums = data.get('numbers')
                                if nums and len(nums) == 6:
                                    key = tuple(sorted(int(n) for n in nums))
                                    if all(1 <= n <= 45 for n in key):
                                        candidates[key] = None
                                        added += 1
                            except Exception:
                                continue
                except Exception:
                    continue
            return added

        added = _add_log_candidates(target_round)
        if added < 30:
            _add_log_candidates(None)  # fallback: 전체 회차
        return candidates
    def _collect_prev_intelligent(self, target_round: int) -> list:
        """직전 실행의 is_intelligent 추천 조합 수집 (L3 신규성 계산용).
        반드시 _cleanup_old_intelligent_logs 호출 '전'에 실행해야 함."""
        prev: list[tuple] = []
        seen: set[tuple] = set()
        for log_path in (self.prediction_log, self.probability_log, self.manual_log):
            if not log_path.exists():
                continue
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if not data.get('is_intelligent'):
                                continue
                            if target_round and data.get('target_round') != target_round:
                                continue
                            nums = data.get('numbers')
                            if nums and len(nums) == 6:
                                key = tuple(sorted(int(n) for n in nums))
                                if all(1 <= n <= 45 for n in key) and key not in seen:
                                    seen.add(key)
                                    prev.append(key)
                        except Exception:
                            continue
            except Exception:
                continue
        return prev

    def _cleanup_old_intelligent_logs(self, target_round: int):
        """
        같은 회차의 이전 is_intelligent=True 로그를 제거하고
        is_intelligent=False(외부 생성기) 로그만 남김.
        → run_analysis가 여러 번 실행돼도 is_intelligent 로그가 누적되지 않음.
        Supabase에는 새 결과가 upsert되므로 원격도 자동 갱신됨.

        [BUG FIX] 기존에는 JSONL 파일만 정리하고 SQLite DB(lotto_history.db)는
        손대지 않았다. 대시보드/달력의 "추출 건수"는 DB를 기준으로 집계되므로,
        run_analysis가 하루에 여러 번 돌 때마다 (LogWatcher·스케줄러·GHA) 5건씩
        is_intelligent 레코드가 DB에만 무한 누적되어 하루 추출량이 300건을
        훨씬 넘는 것처럼(예: 635/945건) 보였다. JSONL 정리와 동일하게
        DB의 같은 회차 is_intelligent 레코드도 함께 제거한다.
        """
        for log_path in (self.prediction_log, self.probability_log, self.manual_log):
            if not log_path.exists():
                continue
            try:
                with open(log_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                # is_intelligent=True 이고 같은 회차인 줄만 제거
                kept = []
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get('is_intelligent') and (
                            data.get('target_round') == target_round or not target_round
                        ):
                            continue  # 이전 AI 결과 제거
                        kept.append(line)
                    except Exception:
                        kept.append(line)
                with open(log_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(kept))
                    if kept:
                        f.write('\n')
            except Exception:
                pass

        # ── SQLite DB에서도 같은 회차 is_intelligent 레코드 제거 ──────────────
        # (JSONL만 지우면 DB에 구버전 AI 레코드가 남아 추출 건수가 부풀려짐)
        self._cleanup_old_intelligent_db_rows(target_round)

    def _cleanup_old_intelligent_db_rows(self, target_round: int):
        """SQLite DB에서 같은 회차의 is_intelligent 레코드를 삭제한다.

        payload_json 안에 is_intelligent=true 로 직렬화되어 있으므로
        공백 차이에 안전하도록 정규화 후 매칭한다. target_round 가 0/None 이면
        모든 회차의 is_intelligent 레코드를 제거(JSONL 정리 규칙과 동일).
        삭제 직후 run_analysis 가 고정 record_uid 로 최신 5건을 다시 기록한다.
        """
        import sqlite3
        db_path = self.project_dir / 'logs' / 'lotto_history.db'
        if not db_path.exists():
            return
        try:
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.cursor()
                # 공백 제거 후 "is_intelligent":true 포함 여부로 AI 레코드 식별
                base = (
                    "REPLACE(REPLACE(payload_json, ' ', ''), CHAR(9), '') "
                    "LIKE '%\"is_intelligent\":true%'"
                )
                if target_round:
                    cur.execute(
                        "DELETE FROM log_records WHERE " + base +
                        " AND target_round = ?",
                        (target_round,),
                    )
                else:
                    cur.execute("DELETE FROM log_records WHERE " + base)
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    # ── 10. 다양성 필터 ────────────────────────────────────────────────────────
    def _is_too_similar(self, nums, selected):
        for ex in selected:
            if len(set(nums) & set(ex)) >= SIMILARITY_THRESHOLD: return True
        return False

    # ── 10. 패턴 메타 ─────────────────────────────────────────────────────────
    def _pattern_info(self, nums):
        sn    = sorted(nums); odd = sum(1 for n in nums if n % 2 != 0)
        zones = [0]*5
        for n in nums: zones[(n-1)//9] += 1
        diffs = {sn[j]-sn[i] for i in range(len(sn)) for j in range(i+1,len(sn))}
        return {
            'ac_value':         len(diffs) - (len(sn) - 1),
            'odd_even':         f'{odd}:{6-odd}',
            'sum':              sum(nums),
            'range_dist':       zones,
            'extinction_zones': [i+1 for i,z in enumerate(zones) if z == 0],
            'consecutive':      sum(1 for i in range(len(sn)-1) if sn[i+1]-sn[i]==1),
        }

    # ── 공개 API (테스트 · 외부 호출용) ───────────────────────────────────────
    def calculate_ac_value(self, nums):
        """AC값(산술 복잡도) = 서로 다른 양의 차이 개수 − (n−1).

        연속수처럼 차이가 단조로우면 0에 가깝고, 분산될수록 커진다(6개 기준 0~10).
        """
        sn = sorted(int(n) for n in nums)
        diffs = {sn[j] - sn[i] for i in range(len(sn)) for j in range(i + 1, len(sn))}
        return len(diffs) - (len(sn) - 1)

    def analyze_patterns(self, nums):
        """조합의 기본 패턴 분석(합/홀짝/구간분포/소멸구간/AC/연속)을 반환한다."""
        return self._pattern_info(list(nums))

    def get_historical_stats(self, limit=None):
        """lotto.xlsx 기반 과거 출현 통계를 반환한다. 데이터가 없으면 None.

        Args:
            limit: 최근 N개 회차만 집계(미지정 시 전체).

        Returns:
            dict | None: top_freq(상위 15개 [(번호, 빈도)]), total_count(집계 번호 수),
                         rounds(집계 회차 수), freq(번호별 빈도 dict)
        """
        rows = self._load_rows()
        if not rows:
            return None
        if limit is not None and limit > 0:
            rows = rows[:limit]
        all_nums = [n for row in rows for n in row]
        freq = Counter(all_nums)
        return {
            "top_freq": freq.most_common(15),
            "total_count": len(all_nums),
            "rounds": len(rows),
            "freq": dict(freq),
        }

    def simulate_reinforcement_learning_score(self, nums, stats=None):
        """규칙 기반 점수(0~25)를 산출한다.

        ⚠️ 이 점수는 '당첨 가능성'이 아니라 통계적 균형도(구간 분산·홀짝·AC·합계)와
        상위 빈도 번호 포함 정도를 나타내는 휴리스틱이다. 당첨 확률과는 무관하다.
        stats가 None이어도 동작하며, 상위 빈도 번호를 포함하면 가점된다.
        """
        sn = sorted(int(n) for n in nums)
        info = self._pattern_info(sn)
        score = 0.0
        # (1) 구간 분산: 소멸 구간이 적을수록 가점 (0~5)
        score += (5 - len(info["extinction_zones"]))
        # (2) 홀짝 균형: 3:3에 가까울수록 가점 (0~5)
        odd = int(info["odd_even"].split(":")[0])
        score += max(0.0, 5.0 - abs(odd - 3) * 1.5)
        # (3) AC값: 분산될수록 가점 (0~5)
        score += min(info["ac_value"], 10) * 0.5
        # (4) 합계 적정성: 100~170 구간 가점 (0~3)
        s = info["sum"]
        score += 3.0 if 100 <= s <= 170 else max(0.0, 3.0 - abs(s - 135) / 30.0)
        # (5) 상위 빈도(핫) 번호 포함 가점 (0~7)
        if stats and stats.get("top_freq"):
            hot = {n for n, _ in stats["top_freq"]}
            score += sum(1 for n in sn if n in hot) * (7.0 / 6.0)
        return round(min(max(score, 0.0), 25.0), 4)

    # ── 11. 메인 실행 ─────────────────────────────────────────────────────────
    def run_analysis(self):
        from log_utils import (get_round_context, persist_log_record,
                               utc_now_iso, ensure_runtime_dirs)

        # Supabase 연동 시 원격 로그를 로컬 jsonl로 내려받기
        # ensure_runtime_dirs 내부에서 bootstrap_remote_runtime_if_needed 호출
        ensure_runtime_dirs(self.project_dir)

        ctx          = get_round_context(self.lotto_xlsx)
        target_round = ctx.get('target_round') or 0

        # ★ 직전 추천 조합 수집 (L3 신규성용) - cleanup 전에 반드시 수행
        prev_sets = self._collect_prev_intelligent(target_round)

        # 이전 is_intelligent 로그 정리 (같은 회차의 이전 실행 결과 제거)
        # → 로그 파일에 구버전 is_intelligent가 쌓이지 않도록
        self._cleanup_old_intelligent_logs(target_round)
        source_round = ctx.get('source_round') or 0
        today_kst    = datetime.now(KST).strftime('%Y-%m-%d')

        # 통계 빌드
        rows    = self._load_rows()
        stats   = self._build_stats(rows) if rows else {}
        weights = self._build_dynamic_weights(rows, stats) if len(rows) >= 10 \
                  else {f's{i}': 1/7 for i in range(1, 8)}

        # ★ 회차 기준 최신성 가중 로그 통계 (오늘 로그일수록 영향력 ↑)
        log_stats = self._build_log_stats(target_round)
        log_stats['prev_sets'] = prev_sets  # L3 신규성 계산에 사용

        # 후보 풀 → 점수 계산 → 정렬
        candidate_keys = self._sample_candidates(stats, target_round)
        if not candidate_keys:
            for _ in range(500):
                candidate_keys[tuple(sorted(random.sample(UNIVERSE, 6)))] = None

        scored = sorted(
            ((self._composite_score(list(k), stats, weights, log_stats), k)
             for k in candidate_keys),
            reverse=True
        )

        # 다양성 필터 → TOP5
        final_top5, selected_sets = [], []
        for sc, key in scored:
            nums = list(key)
            if not self._is_too_similar(nums, selected_sets):
                final_top5.append({'numbers': nums, 'composite_score': sc,
                                   'patterns': self._pattern_info(nums)})
                selected_sets.append(nums)
                if len(final_top5) >= TOP_K: break
        if len(final_top5) < TOP_K:
            used = {tuple(ex) for ex in selected_sets}
            for sc, key in scored:
                if key not in used:
                    final_top5.append({'numbers': list(key), 'composite_score': sc,
                                       'patterns': self._pattern_info(list(key))})
                    used.add(key)
                    if len(final_top5) >= TOP_K: break

        # 리포트 & 로그 저장
        w_labels = [('s1','GapDue(주기과적)'),('s2','CoOccur(동반출현)'),
                    ('s3','SumFit(합계적합)'),('s4','TailBalance(끝수균형)'),
                    ('s5','ZoneEntropy(구간분산)'),('s6','Markov(전이확률)'),
                    ('s7','FreqBalance(빈도균형)')]
        report_lines = [
            f'<!-- metadata: round={target_round}, date={today_kst} -->',
            f'## {target_round}회차 AI 지능형 추천 번호',
            '',
            f'생성일시: {datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")} KST',
            f'누적 로그 반영 건수: {log_stats["log_total"]}건'
            + (f' (오늘 신규 {log_stats.get("log_today", 0)}건, '
               f'최신 로그 가중 반감기 {RECENCY_HALF_LIFE:.0f}일)' if log_stats["log_total"] >= 30
               else ' (전체 회차 통합 - 현재 회차 로그 부족)'),
            f'직전 추천 대비 신규성(L3) 적용: {"예 (" + str(len(prev_sets)) + "개 조합 기준)" if prev_sets else "아니오 (직전 추천 없음)"}',
            '',
            f'### 점수 구성  (StatScore×{ALPHA} + LogScore×{BETA})',
            f'LogScore = 가중빈도(L1)×0.40 + 가중동반출현(L2)×0.40 + 신규성(L3)×0.20',
            f'StatScore 앙상블 가중치 (동적 LOO 백테스트):',
        ]
        for k, label in w_labels:
            report_lines.append(f'  {label}: {weights.get(k,0):.4f}')
        report_lines += ['', '### 추천 번호 Top 5', '']

        for i, cand in enumerate(final_top5, 1):
            nums_str = ', '.join(f'{n:02d}' for n in sorted(cand['numbers']))
            sc_val   = cand['composite_score']
            pat      = cand['patterns']
            report_lines.append(f'{i}순위: {nums_str} (CompositeScore: {sc_val:.4f})')
            report_lines.append(
                f'  AC값: {pat["ac_value"]} | 합계: {pat["sum"]} | '
                f'홀짝: {pat["odd_even"]} | 멸구간: {len(pat["extinction_zones"])}'
            )
            base_rec = {
                'timestamp': utc_now_iso(), 'source_round': source_round,
                'target_round': target_round, 'candidate_rank': i,
                'numbers': sorted(cand['numbers']), 'score': sc_val,
                'is_intelligent': True,
            }
            # 고정 record_uid: 같은 회차+순위면 항상 동일 → Supabase upsert 시 덮어씌움
            # timestamp 기반 uid는 매번 달라서 Supabase에 무한 누적됨
            # 고정 uid를 쓰면 GHA 재실행마다 최신 결과로 교체됨
            import hashlib as _hl
            def _fixed_uid(tr, rank, lt):
                return _hl.sha256(f"intelligent|{lt}|{tr}|{rank}".encode()).hexdigest()

            persist_log_record(self.project_dir/'logs', 'prediction',
                               {**base_rec, 'log_type': 'prediction',
                                'record_uid': _fixed_uid(target_round, i, 'prediction')})
            persist_log_record(self.project_dir/'logs', 'probability',
                               {**base_rec, 'log_type': 'probability',
                                'record_uid': _fixed_uid(target_round, i, 'probability')})
            persist_log_record(self.project_dir/'logs', 'manual',
                               {**base_rec, 'log_type': 'manual', 'best_score': sc_val,
                                'record_uid': _fixed_uid(target_round, i, 'manual')})

        final_report = '\n'.join(report_lines)

        # 파일 저장
        rpt = self.project_dir / 'reports' / 'intelligent_analysis_report.md'
        rpt.parent.mkdir(parents=True, exist_ok=True)
        rpt.write_text(final_report, encoding='utf-8')

        wl = [f'## {target_round}회차 AI 지능형 추천 번호', '',
              f'생성일시: {datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")} KST', '',
              '추천 번호 Top 5:', '']
        for i, cand in enumerate(final_top5, 1):
            nums_str = ', '.join(f'{n:02d}' for n in sorted(cand['numbers']))
            pat = cand['patterns']
            wl.append(f'{i}순위: {nums_str} (점수: {round(cand["composite_score"]*100, 2)})')
            wl.append(f'  AC값: {pat["ac_value"]} | 합계: {pat["sum"]} | '
                      f'홀짝: {pat["odd_even"]} | 멸 구간: {len(pat["extinction_zones"])}')
        (self.project_dir/'reports'/'weekly_ai_recommendation.txt').write_text(
            '\n'.join(wl), encoding='utf-8')

        return final_report


if __name__ == '__main__':
    current_dir = Path(__file__).resolve().parent
    analyzer = AIIntelligentAnalyzer(current_dir)
    print(analyzer.run_analysis())

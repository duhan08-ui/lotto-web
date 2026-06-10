"""
lotto_core.py - LottoPredictor 독립 모듈 (streamlit 의존성 없음)
auto_log_generator.py 및 standalone_scheduler.py에서 사용
app.py에서 핵심 로직만 추출하여 스케줄러가 독립 실행 가능하도록 함
"""
from __future__ import annotations

import ast
import math
import os
import random
from collections import Counter
from datetime import date, datetime, timedelta
from itertools import permutations
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from anti_pattern_lotto import generate_prime_composite_stats_ticket

KST = ZoneInfo("Asia/Seoul")
DEFAULT_SIMULATION_COUNT = int(os.getenv("LOTTO_SIMULATION_COUNT", "5000"))
SIMULATION_COUNT = DEFAULT_SIMULATION_COUNT


def _file_cache_token(path):
    file_path = Path(path)
    if not file_path.exists():
        return (str(file_path), 0, 0)
    stat = file_path.stat()
    return (str(file_path.resolve()), stat.st_mtime_ns, stat.st_size)


def _sanitize_simulation_count(value):
    try:
        count = int(value or DEFAULT_SIMULATION_COUNT)
    except (TypeError, ValueError):
        count = DEFAULT_SIMULATION_COUNT
    return max(1000, min(count, 50000))


def _generate_anti_pattern_manual_numbers(excel_path, previous_numbers=None):
    previous_tuple = tuple(sorted(int(n) for n in previous_numbers)) if previous_numbers else None
    rng = random.SystemRandom()
    latest_candidate = []
    for _ in range(12):
        seed = rng.randint(1, 10**9)
        latest_candidate = list(generate_prime_composite_stats_ticket(excel_path=excel_path, seed=seed))
        if previous_tuple is None or tuple(latest_candidate) != previous_tuple:
            return latest_candidate
    return latest_candidate


class LottoPredictor:
    def __init__(self, excel_path):
        self.excel_path = excel_path
        self.rows = self._load_rows(excel_path)
        self.total_draws = len(self.rows)
        self.universe = list(range(1, 46))
        self.base_hit_probability = 6.0 / 45.0
        self.max_gap_bucket = 25
        self.latest_row = list(self.rows[0]) if self.rows else []
        self.latest_row_set = set(self.latest_row)

        self.total_counter = Counter(n for row in self.rows for n in row)
        self.position_counters = [Counter() for _ in range(6)]
        self.chrono_rows = list(reversed(self.rows))
        for row in self.rows:
            sorted_row = sorted(int(num) for num in row)
            for idx, num in enumerate(sorted_row):
                if idx < 6:
                    self.position_counters[idx][num] += 1

        self.last_seen_gap = self._build_last_seen_gap()
        self.gap_probability = self._build_gap_probability(prior_strength=32.0)
        self.pair_counter = self._build_pair_counter(window=320)
        self.avg_total_freq = (len(self.rows) * 6) / 45.0
        self.avg_pair_freq = max((len(self.rows) * 15) / ((45 * 44) / 2), 1e-6)
        self.gap_factor_lookup = self._build_gap_factor_lookup()
        self.pair_strength_matrix = self._build_pair_strength_matrix()
        self.markov_transition_matrix = self._build_markov_transition_matrix()
        self.latest_row_transition_lookup = self._build_latest_row_transition_lookup()
        self.markov_transition_weight_lookup = self._build_markov_transition_weight_lookup()
        self.number_state_transition_stats = self._build_number_state_transition_stats(window=8)
        self.projected_probability_lookup = self._build_projected_probability_lookup()
        self.giannella_pattern_stats = self._build_giannella_pattern_stats()
        self.giannella_segment_profiles = self._build_giannella_segment_profiles()
        self.group_portfolio_stats = self._build_group_portfolio_stats()
        self.probability_group_profiles = self._build_probability_group_profiles()
        self.probability_weight_lookup = self._build_probability_weight_lookup()
        self.base_position_weights = self._build_base_position_weights()
        self.pattern_signature_stats = self._build_pattern_signature_stats()
        self._projected_log_lookup = self._build_log_lookup(self.projected_probability_lookup, normalize_by_base=True)
        self._transition_log_lookup = self._build_log_lookup(self.markov_transition_weight_lookup)
        self._state_log_lookup = self._build_log_lookup(self.probability_weight_lookup)
        self._anchor_log_lookup = self._build_log_lookup(self.latest_row_transition_lookup, normalize_by_base=True)
        self._pair_log_matrix = self._build_pair_log_matrix()
        self.adjacent_overlap_stats = self._build_adjacent_overlap_stats()
        self._probability_portfolio_score_cache = {}
        self._probability_mcmc_score_cache = {}
        self._ticket_feature_cache = {}
        self.dynamic_score_config = self._build_rolling_backtest_score_config()

        # ── 강화 분석 통계 (v2) ──────────────────────────────────────────
        self.cycle_stats          = self._build_cycle_stats()           # [1] 출현 주기 분포
        self.cooccurrence_matrix  = self._build_cooccurrence_matrix()   # [2] 번호 동반 출현 행렬
        self.sum_histogram        = self._build_sum_histogram()         # [5] 합계 대역 히스토그램
        self.tail_stats           = self._build_tail_stats()            # [6] 끝자리 균형 통계
        self.streak_stats         = self._build_streak_stats()          # [4] 연속 출현/미출현 패턴
        # 앙상블 가중치는 백테스트로 동적 결정
        self.ensemble_weights     = self._build_ensemble_weights()      # [7] 앙상블 가중치
        # ─────────────────────────────────────────────────────────────────

    def _build_advanced_pattern_stats(self):
        # 1. 최근 트렌드 가중치 (10, 30, 100회차)
        recent_10 = Counter(n for row in self.rows[:10] for n in row)
        recent_30 = Counter(n for row in self.rows[:30] for n in row)
        recent_100 = Counter(n for row in self.rows[:100] for n in row)
        
        # 2. 번호별 핫/콜드 지수
        hot_cold_map = {}
        for n in self.universe:
            freq = self.total_counter[n]
            avg_freq = (len(self.rows) * 6) / 45
            rel_freq = freq / avg_freq if avg_freq > 0 else 1.0
            gap = self.last_seen_gap.get(n, 0)
            
            # 핫 지수: 최근 출현 빈도 가중합
            hot_score = (recent_10[n] * 4.5 + recent_30[n] * 2.0 + recent_100[n] * 0.8) / 7.3
            # 콜드 지수: 미출현 기간 가중치 (15회 이상부터 가속)
            cold_score = max(0, gap - 12) / 8.0
            
            hot_cold_map[n] = {
                "hot": hot_score,
                "cold": cold_score,
                "rel_freq": rel_freq
            }
        return hot_cold_map

    def _advanced_pattern_score(self, numbers):
        # 조합의 통계적 적합성을 평가하는 정밀 공식
        # 1. 합계 분포 점수 (로또 평균 138, 표준편차 30의 정규분포 가정)
        s = sum(numbers)
        sum_score = math.exp(-((s - 138)**2) / (2 * 30**2))
        
        # 2. 홀짝 비율 점수 (3:3 최적, 2:4/4:2 차선)
        odds = sum(1 for n in numbers if n % 2 != 0)
        odd_ratio_score = {3: 1.0, 2: 0.85, 4: 0.85, 1: 0.4, 5: 0.4, 0: 0.1, 6: 0.1}.get(odds, 0.05)
        
        # 3. 저고 비율 점수 (1~22: 저, 23~45: 고)
        lows = sum(1 for n in numbers if n <= 22)
        low_ratio_score = {3: 1.0, 2: 0.85, 4: 0.85, 1: 0.4, 5: 0.4, 0: 0.1, 6: 0.1}.get(lows, 0.05)
        
        # 4. 연번(Consecutive) 제어
        sorted_nums = sorted(numbers)
        consecutive_count = sum(1 for i in range(len(sorted_nums)-1) if sorted_nums[i+1] - sorted_nums[i] == 1)
        consecutive_score = 1.0 if consecutive_count <= 1 else (0.4 if consecutive_count == 2 else 0.05)
        
        # 5. 끝수(Tail digit) 다양성
        tails = [n % 10 for n in numbers]
        max_tail = max(Counter(tails).values())
        tail_score = 1.0 if max_tail <= 2 else 0.25
        
        # 6. 이월수(Overlap with latest) 점수
        overlap = len(set(numbers) & self.latest_row_set)
        overlap_score = {1: 1.0, 0: 0.8, 2: 0.7, 3: 0.2, 4: 0.05}.get(overlap, 0.01)

        # 7. 구간 분포 (9단위 5개 구간)
        zones = [0] * 5
        for n in numbers:
            idx = min((n-1)//9, 4)
            zones[idx] += 1
        zone_score = 1.0 if max(zones) <= 3 else 0.3

        return (sum_score * 0.20 + odd_ratio_score * 0.15 + low_ratio_score * 0.15 + 
                consecutive_score * 0.15 + tail_score * 0.1 + overlap_score * 0.15 + zone_score * 0.1)

    # ──────────────────────────────────────────────────────────────────────
    # [BIBD] 블록 디자인 커버리지 점수
    # 수학적 근거: BIBD(Balanced Incomplete Block Design)
    #   λ·C(v,t) = b·C(k,t)  (v=45, k=6, t=3, λ=1)
    #   → 45개 숫자에서 t=3 조합을 최소 1회 커버하는 최소 블록 수 b = C(45,3)/C(6,3) ≈ 665장
    #
    # 실무 적용 방식:
    #   · 다중 티켓(tickets) 묶음이 주어질 때, 각 티켓 간 번호 중복도를 측정한다.
    #   · 중복이 적을수록(번호가 고르게 분산될수록) BIBD 커버리지가 높다.
    #   · 단일 티켓 평가 시에는 1.0 반환 (패널티 없음).
    #
    # 반환값: 0.0 ~ 1.0 (1.0 = 완전 분산, 0.0 = 완전 중복)
    # ──────────────────────────────────────────────────────────────────────
    def _bibd_coverage_score(self, tickets: list) -> float:
        """BIBD 기반 티켓 묶음 커버리지 점수.

        tickets: 정렬된 번호 리스트의 리스트, 예) [[3,7,12,23,34,41], ...]
        단일 티켓이거나 빈 리스트면 1.0 반환.

        알고리즘:
          1. 각 티켓 쌍 간 교집합 크기(overlap)를 계산한다.
          2. 교집합이 클수록 커버리지 낭비 → 페널티.
          3. 이상적 t=3 기준: 두 티켓이 3개 이상 겹치면 중복 커버 발생.
          4. 평균 중복도를 0~1로 정규화하여 커버리지 효율 점수를 반환한다.
        """
        n = len(tickets)
        if n <= 1:
            return 1.0

        total_overlap = 0.0
        pair_count = 0
        for i in range(n):
            for j in range(i + 1, n):
                overlap = len(set(tickets[i]) & set(tickets[j]))
                # t=3 기준: 3개 이상 겹치면 커버리지 낭비로 간주
                # 최대 겹침 6개 기준으로 정규화
                total_overlap += overlap / 6.0
                pair_count += 1

        if pair_count == 0:
            return 1.0

        avg_overlap_ratio = total_overlap / pair_count  # 0.0(완전분산) ~ 1.0(완전중복)
        coverage_score = 1.0 - avg_overlap_ratio        # 높을수록 좋음
        return round(max(0.0, min(1.0, coverage_score)), 6)

    # ──────────────────────────────────────────────────────────────────────
    # [BIBD] 단일 티켓의 내부 구조 점수 (t=3 서브셋 다양성)
    # 6개 번호에서 가능한 3-조합(C(6,3)=20개)의 구간 분포 다양성을 평가.
    # 20개 3-조합이 5개 구간(9단위)에 고르게 퍼질수록 높은 점수.
    # ──────────────────────────────────────────────────────────────────────
    def _bibd_internal_diversity_score(self, numbers: list) -> float:
        """단일 티켓의 3-조합 구간 다양성 점수 (BIBD t=3 응용).

        C(6,3) = 20개 3-조합 각각에서 포함된 서로 다른 구간(zone) 개수를 계산하고,
        그 분포의 섀넌 엔트로피를 기반으로 다양성 점수를 반환한다.

        - 3-조합이 3개의 서로 다른 구간에서 왔을수록(zone_diversity=3) BIBD 커버리지 높음
        - 3-조합이 모두 같은 구간에서 왔을 때(zone_diversity=1) BIBD 커버리지 낮음

        반환값: 0.0 ~ 1.0 (1.0 = 최대 분산)
        """
        from itertools import combinations as _comb

        sorted_nums = sorted(int(n) for n in numbers)
        if len(sorted_nums) != 6:
            return 1.0

        # 각 번호의 구간 인덱스 (0~4, 9단위)
        zone_of = [min((n - 1) // 9, 4) for n in sorted_nums]

        # 20개 3-조합에서 서로 다른 구간 수 카운트 (1~3)
        diversity_counts = {1: 0, 2: 0, 3: 0}
        for trio in _comb(range(6), 3):
            unique_zones = len({zone_of[trio[0]], zone_of[trio[1]], zone_of[trio[2]]})
            diversity_counts[unique_zones] += 1

        total = sum(diversity_counts.values())  # 항상 20

        # 섀넌 엔트로피: 다양성 등급(1,2,3)의 분포가 고를수록 높음
        # 단, 우리는 diversity=3 (완전 분산)을 선호하므로
        # 가중 평균 방식: 각 3-조합의 diversity 값 평균을 1~3 범위에서 정규화
        weighted_avg = sum(d * cnt for d, cnt in diversity_counts.items()) / total
        # 정규화: 최솟값 1 → 0.0, 최댓값 3 → 1.0
        diversity_score = (weighted_avg - 1.0) / 2.0
        return round(max(0.0, min(1.0, diversity_score)), 6)

    def _load_rows(self, excel_path):
        df = pd.read_excel(excel_path)
        expected_number_cols = [f"번호{i}" for i in range(1, 7)]
        if all(col in df.columns for col in expected_number_cols):
            number_cols = expected_number_cols
        else:
            number_cols = [col for col in df.columns if str(col).startswith("번호")]
            if len(number_cols) >= 6:
                number_cols = sorted(
                    number_cols,
                    key=lambda col: int("".join(ch for ch in str(col) if ch.isdigit()) or 999),
                )[:6]
            else:
                number_cols = list(df.columns[:6])
        rows = []
        for _, row in df[number_cols].iterrows():
            vals = [int(cell) for cell in row.tolist() if isinstance(cell, (int, float)) and 1 <= int(cell) <= 45]
            if len(vals) == 6:
                rows.append(vals)
        return rows

    def _build_last_seen_gap(self):
        last_seen = {n: self.total_draws for n in self.universe}
        for idx, row in enumerate(self.rows):
            for n in row:
                if last_seen[n] == self.total_draws:
                    last_seen[n] = idx
        return last_seen

    def _build_gap_probability(self, prior_strength=32.0):
        stats = {gap: {"success": 0, "total": 0} for gap in range(self.max_gap_bucket + 1)}
        chrono_rows = list(reversed(self.rows))
        last_seen_idx = {n: None for n in self.universe}
        for idx, row in enumerate(chrono_rows):
            present = set(row)
            for n in self.universe:
                if last_seen_idx[n] is not None:
                    gap = min(idx - last_seen_idx[n] - 1, self.max_gap_bucket)
                    if gap >= 0:
                        stats[gap]["total"] += 1
                        if n in present:
                            stats[gap]["success"] += 1
            for n in present:
                last_seen_idx[n] = idx
        return {
            g: (s["success"] + self.base_hit_probability * prior_strength) / (s["total"] + prior_strength)
            for g, s in stats.items()
        }

    def _build_pair_counter(self, window=320):
        pair_counter = Counter()
        for row in self.rows[:window]:
            nums = sorted(list(row))
            for i in range(len(nums)):
                for j in range(i + 1, len(nums)):
                    pair_counter[(nums[i], nums[j])] += 1
        return pair_counter

    def _build_adjacent_overlap_stats(self):
        overlaps = [len(set(self.rows[i]) & set(self.rows[i + 1])) for i in range(len(self.rows) - 1)]
        return {"distribution": Counter(overlaps), "average": sum(overlaps) / len(overlaps) if overlaps else 0}

    def _build_gap_factor_lookup(self):
        lookup = [1.0] * 46
        for number in self.universe:
            gap = self.last_seen_gap[number]
            prob = self.gap_probability.get(min(gap, self.max_gap_bucket), self.base_hit_probability)
            lookup[number] = min(max(prob / self.base_hit_probability, 0.78), 1.35)
        return lookup

    def _build_pair_strength_matrix(self):
        matrix = [[1.0] * 46 for _ in range(46)]
        normalizer = self.avg_pair_freq + 1.0
        for idx, left in enumerate(self.universe):
            for right in self.universe[idx + 1 :]:
                pair_count = float(self.pair_counter.get((left, right), 0))
                raw_ratio = (pair_count + 2.0) / normalizer
                normalized_ratio = raw_ratio ** 0.38
                clipped_ratio = min(max(normalized_ratio, 0.91), 1.13)
                matrix[left][right] = clipped_ratio
                matrix[right][left] = clipped_ratio
        return matrix

    def _build_markov_transition_matrix(self):
        overall_prior = {
            number: (self.total_counter[number] + 1.0) / (self.total_draws * 6 + 45.0)
            for number in self.universe
        }
        matrix = [[0.0] * 46 for _ in range(46)]
        recent_horizon = max(min(len(self.chrono_rows) - 1, 72), 1)
        for prev_number in self.universe:
            prev_zone = self._giannella_zone_index(prev_number)
            for next_number in self.universe:
                same_zone_bonus = 1.08 if self._giannella_zone_index(next_number) == prev_zone else 1.0
                matrix[prev_number][next_number] = (0.24 + overall_prior[next_number] * 24.0) * same_zone_bonus

        if len(self.chrono_rows) >= 2:
            for step, (prev_row, next_row) in enumerate(zip(self.chrono_rows[:-1], self.chrono_rows[1:])):
                recency_ratio = max((recent_horizon - min(step, recent_horizon)) / recent_horizon, 0.0)
                transition_weight = 1.0 + (recency_ratio * 1.8)
                for prev_number in prev_row:
                    prev_zone = self._giannella_zone_index(prev_number)
                    for next_number in next_row:
                        same_zone_bonus = 1.14 if self._giannella_zone_index(next_number) == prev_zone else 1.0
                        band_bonus = 1.05 if abs(prev_number - next_number) <= 9 else 1.0
                        matrix[prev_number][next_number] += transition_weight * same_zone_bonus * band_bonus

        for prev_number in self.universe:
            row_total = sum(matrix[prev_number][next_number] for next_number in self.universe)
            if row_total <= 0:
                uniform = 1.0 / len(self.universe)
                for next_number in self.universe:
                    matrix[prev_number][next_number] = uniform
            else:
                for next_number in self.universe:
                    matrix[prev_number][next_number] /= row_total
        return matrix

    def _build_latest_row_transition_lookup(self):
        lookup = [self.base_hit_probability] * 46
        if not self.rows:
            return lookup

        latest_row = self.rows[0]
        if not latest_row:
            return lookup

        denominator = len(latest_row)
        for number in self.universe:
            lookup[number] = sum(self.markov_transition_matrix[source][number] for source in latest_row) / denominator
        return lookup

    def _build_markov_transition_weight_lookup(self):
        lookup = [0.0] * 46
        if not self.rows:
            for number in self.universe:
                lookup[number] = 1.0
            return lookup

        recent_rows = self.rows[: min(5, len(self.rows))]
        recent_denominator = sum(1.0 / (idx + 1) for idx in range(len(recent_rows))) or 1.0
        for number in self.universe:
            latest_transition = self.latest_row_transition_lookup[number]
            recent_transition = 0.0
            for idx, row in enumerate(recent_rows):
                weight = 1.0 / (idx + 1)
                row_transition = sum(self.markov_transition_matrix[source][number] for source in row) / len(row)
                recent_transition += row_transition * weight
            recent_transition /= recent_denominator
            overall_probability = (self.total_counter[number] + 1.0) / (self.total_draws * 6 + 45.0)
            gap_probability = self.gap_probability.get(min(self.last_seen_gap[number], self.max_gap_bucket), self.base_hit_probability)
            score = (
                (latest_transition * 0.48)
                + (recent_transition * 0.26)
                + (gap_probability * 0.12)
                + (overall_probability * 0.14)
            )
            lookup[number] = max(score / self.base_hit_probability, 1e-9)

        # 정규화: 평균 가중치가 1.0이 되도록 조정 (상대적 비교 기준 유지)
        mean_weight = sum(lookup[number] for number in self.universe) / len(self.universe)
        if mean_weight > 0:
            for number in self.universe:
                lookup[number] /= mean_weight
        return lookup

    def _state_gap_bucket(self, gap):
        if gap <= 1:
            return 0
        if gap <= 3:
            return 1
        if gap <= 6:
            return 2
        if gap <= 10:
            return 3
        return 4

    def _build_number_state_transition_stats(self, window=8, prior_strength=18.0):
        stats = {number: {} for number in self.universe}
        chrono_rows = list(reversed(self.rows))
        if len(chrono_rows) <= window:
            return {"window": window, "prior_strength": prior_strength, "stats": stats}

        for idx in range(window, len(chrono_rows)):
            recent_rows = chrono_rows[idx - window : idx]
            next_row = set(chrono_rows[idx])
            recent_rows_latest_first = list(reversed(recent_rows))
            for number in self.universe:
                hit_count = sum(1 for row in recent_rows if number in row)
                gap = window + 1
                for offset, row in enumerate(recent_rows_latest_first):
                    if number in row:
                        gap = offset
                        break
                state = (hit_count, self._state_gap_bucket(gap))
                state_bucket = stats[number].setdefault(state, {"success": 0.0, "total": 0.0})
                state_bucket["total"] += 1.0
                if number in next_row:
                    state_bucket["success"] += 1.0

        return {"window": window, "prior_strength": prior_strength, "stats": stats}

    def _current_number_state(self, number, recent_rows, window):
        hit_count = sum(1 for row in recent_rows if number in row)
        gap = window + 1
        for offset, row in enumerate(recent_rows):
            if number in row:
                gap = offset
                break
        return hit_count, self._state_gap_bucket(gap)

    def _build_projected_probability_lookup(self):
        lookup = [0.0] * 46
        if not self.rows:
            for number in self.universe:
                lookup[number] = self.base_hit_probability
            return lookup

        state_window = int(self.number_state_transition_stats.get("window", 8))
        prior_strength = float(self.number_state_transition_stats.get("prior_strength", 18.0))
        state_stats = self.number_state_transition_stats.get("stats", {})
        recent_rows = self.rows[:state_window]
        raw_scores = {}

        for number in self.universe:
            transition_probability = self.latest_row_transition_lookup[number]
            overall_probability = (self.total_counter[number] + 1.0) / (self.total_draws * 6 + 45.0)
            gap_probability = self.gap_probability.get(min(self.last_seen_gap[number], self.max_gap_bucket), self.base_hit_probability)
            current_state = self._current_number_state(number, recent_rows, state_window)
            state_bucket = state_stats.get(number, {}).get(current_state)
            if state_bucket is None:
                state_probability = (overall_probability * 0.45) + (gap_probability * 0.55)
            else:
                state_probability = (state_bucket["success"] + self.base_hit_probability * prior_strength) / (state_bucket["total"] + prior_strength)

            recent_hits = current_state[0]
            recent_factor = 1.0 + ((recent_hits - (state_window * self.base_hit_probability)) / max(state_window, 1)) * 0.35
            transition_factor = max(transition_probability / self.base_hit_probability, 0.35)
            state_factor = max(state_probability / self.base_hit_probability, 0.35)
            gap_factor = max(gap_probability / self.base_hit_probability, 0.35)
            overall_factor = max(overall_probability / self.base_hit_probability, 0.35)
            raw_scores[number] = max(
                (transition_factor ** 0.58)
                * (state_factor ** 0.92)
                * (gap_factor ** 0.74)
                * (overall_factor ** 0.36)
                * max(recent_factor, 0.78),
                1e-12,
            )

        raw_total = sum(raw_scores.values())
        if raw_total <= 0:
            for number in self.universe:
                lookup[number] = self.base_hit_probability
            return lookup

        for number in self.universe:
            normalized_probability = 6.0 * raw_scores[number] / raw_total
            lookup[number] = min(max(normalized_probability, 0.015), 0.42)
        # 클리핑 후 재정규화: 확률 합이 정확히 6.0이 되도록 보정
        clipped_total = sum(lookup[number] for number in self.universe)
        if clipped_total > 0:
            scale = 6.0 / clipped_total
            for number in self.universe:
                lookup[number] = min(max(lookup[number] * scale, 0.015), 0.42)
        return lookup

    def _build_probability_group_profiles(self):
        ranked_numbers = sorted(self.universe, key=lambda number: self.projected_probability_lookup[number], reverse=True)
        groups = {
            "high": ranked_numbers[:15],
            "mid": ranked_numbers[15:30],
            "low": ranked_numbers[30:],
        }
        membership = [""] * 46
        for group_name, numbers in groups.items():
            for number in numbers:
                membership[number] = group_name

        mean_probability = {
            group_name: (
                sum(self.projected_probability_lookup[number] for number in numbers) / len(numbers) if numbers else self.base_hit_probability
            )
            for group_name, numbers in groups.items()
        }

        history_window = min(len(self.rows), 180)
        recent_window = min(len(self.rows), 45)
        quota_counter = Counter()
        recent_quota_counter = Counter()

        for idx, row in enumerate(self.rows[:history_window]):
            counts = {"high": 0, "mid": 0, "low": 0}
            for number in row:
                group_name = membership[number] or "low"
                counts[group_name] += 1
            quota = (counts["high"], counts["mid"], counts["low"])
            quota_counter[quota] += 1
            if idx < recent_window:
                recent_quota_counter[quota] += 1

        quota_scores = {}
        ranked_quotas = []
        positive_score_total = 0.0
        for high_count in range(7):
            for mid_count in range(7 - high_count):
                low_count = 6 - high_count - mid_count
                quota = (high_count, mid_count, low_count)
                quota_prob_mass = (
                    mean_probability["high"] * high_count
                    + mean_probability["mid"] * mid_count
                    + mean_probability["low"] * low_count
                )
                history_freq = quota_counter.get(quota, 0) / max(history_window, 1)
                recent_freq = recent_quota_counter.get(quota, 0) / max(recent_window, 1)
                spread = max(quota) - min(quota)
                balance_bonus = (1.0 - (spread / 6.0)) * 0.10
                concentration_penalty = 0.0
                if max(quota) >= 6:
                    concentration_penalty += 0.04 * (max(quota) - 5)
                if min(quota) == 0:
                    concentration_penalty += 0.01
                efficiency = (quota_prob_mass * 2.32) + (history_freq * 0.72) + (recent_freq * 0.88) + balance_bonus - concentration_penalty
                quota_scores[quota] = efficiency
                ranked_quotas.append((quota, efficiency))
                positive_score_total += max(efficiency, 0.0)

        ranked_quotas.sort(key=lambda item: item[1], reverse=True)
        top_share = (max(ranked_quotas[0][1], 0.0) / max(positive_score_total, 1e-9)) if ranked_quotas else 0.0
        exploration_rate = min(max(0.12 + (top_share * 0.14), 0.12), 0.22)
        exploration_pool_size = max(6, min(len(ranked_quotas), 10)) if ranked_quotas else 0
        exploration_ranked_quotas = []
        for rank, (quota, efficiency) in enumerate(ranked_quotas[:exploration_pool_size]):
            exploration_bonus = max(0.0, 0.18 - (rank * 0.012))
            exploration_ranked_quotas.append((quota, efficiency + exploration_bonus))

        return {
            "groups": groups,
            "membership": membership,
            "quota_scores": quota_scores,
            "ranked_quotas": ranked_quotas,
            "exploration_rate": exploration_rate,
            "exploration_ranked_quotas": exploration_ranked_quotas,
        }

    def _sample_group_portfolio_ticket(self, quota):
        groups = self.probability_group_profiles.get("groups", {})
        exploration_rate = float(self.probability_group_profiles.get("exploration_rate", 0.24))
        selected = []
        score = 0.0
        latest_row = set(self.rows[0]) if self.rows else set()

        for group_name, pick_count in zip(("high", "mid", "low"), quota):
            if pick_count <= 0:
                continue
            available = [number for number in groups.get(group_name, []) if number not in selected]
            for _ in range(pick_count):
                if not available:
                    break
                deterministic_weights = []
                sampled_weights = []
                current_position = min(len(selected), 5)
                for number in available:
                    projected_weight = max(self.projected_probability_lookup[number] / self.base_hit_probability, 1e-12)
                    position_weight = max(self.base_position_weights[current_position][number], 1e-12)
                    pair_factor = self._normalized_pair_factor(number, selected)
                    carry_over_penalty = 0.97 if number in latest_row else 1.0
                    weight = max(
                        (projected_weight ** 1.08)
                        * (position_weight ** 0.96)
                        * (pair_factor ** 0.20)
                        * carry_over_penalty,
                        1e-12,
                    )
                    deterministic_weights.append(weight)
                    exploration_noise = random.uniform(1.0 - (0.03 * exploration_rate), 1.0 + (0.10 * exploration_rate))
                    sampled_weights.append((weight ** max(0.90, 1.0 - (0.16 * exploration_rate))) * exploration_noise)
                if sum(sampled_weights) <= 0:
                    sampled_weights = [1.0] * len(available)
                selected_index = random.choices(range(len(available)), weights=sampled_weights, k=1)[0]
                selected_number = available.pop(selected_index)
                selected.append(selected_number)
                score += math.log(max(deterministic_weights[selected_index], 1e-12))

        return sorted(selected), score

    def _safety_correction_score(self, numbers):
        features = self._ticket_features(numbers)
        odd_count = features["odd_count"]
        lower_half_count = features["lower_half_count"]
        consecutive_pairs = features["consecutive_pairs"]
        max_decade = features["max_decade"]
        latest_overlap = features["latest_overlap"]

        score = 0.0
        if odd_count in (2, 3, 4):
            score += 0.10
        else:
            score -= 0.07
        if lower_half_count in (2, 3, 4):
            score += 0.08
        else:
            score -= 0.05
        if consecutive_pairs <= 2:
            score += 0.04
        else:
            score -= 0.09 * (consecutive_pairs - 2)
        if max_decade >= 4:
            score -= 0.10 * (max_decade - 3)
        if latest_overlap >= 3:
            score -= 0.12 * (latest_overlap - 2)

        dynamic_config = getattr(self, "dynamic_score_config", {}) or {}
        if score < 0:
            score *= float(dynamic_config.get("safety_penalty_scale", 1.0))
        elif score > 0:
            score *= float(dynamic_config.get("safety_reward_scale", 1.0))
        return score

    def _probability_portfolio_score(self, numbers, quota):
        sorted_numbers = tuple(sorted(int(number) for number in numbers))
        quota_key = tuple(quota)
        cache_key = (sorted_numbers, quota_key)
        cached_score = self._probability_portfolio_score_cache.get(cache_key)
        if cached_score is not None:
            return cached_score

        features = self._ticket_features(sorted_numbers)
        quota_efficiency = self.probability_group_profiles.get("quota_scores", {}).get(quota_key, 0.0)
        dynamic_config = getattr(self, "dynamic_score_config", {}) or {}
        position_axis_weight = float(dynamic_config.get("position_axis_weight", 1.12))
        pattern_signature_weight = float(dynamic_config.get("pattern_signature_weight", 0.82))
        pair_axis_weight = float(dynamic_config.get("pair_axis_weight", 0.40))
        quota_group_weight = float(dynamic_config.get("quota_group_weight", 0.46))
        quota_efficiency_weight = float(dynamic_config.get("quota_efficiency_weight", 0.38))
        score = (
            (features["transition_log_score"] * 0.78)
            + (features["probability_log_score"] * 0.88)
            + (features["position_log_score"] * position_axis_weight)
            + (features["pair_log_component"] * pair_axis_weight)
            + (self._group_portfolio_score(sorted_numbers) * quota_group_weight)
            + (self._giannella_pattern_score(sorted_numbers) * 0.44)
            + (self._pattern_signature_score(sorted_numbers) * pattern_signature_weight)
            + self._safety_correction_score(sorted_numbers)
            + (quota_efficiency * quota_efficiency_weight)
        )
        self._probability_portfolio_score_cache[cache_key] = score
        return score

    def _refine_group_portfolio_ticket(self, seed_numbers, quota, iterations=18):
        membership = self.probability_group_profiles.get("membership", [""] * 46)
        current = sorted(int(number) for number in seed_numbers)
        current_score = self._probability_portfolio_score(current, quota)
        best_numbers = list(current)
        best_score = current_score
        temperature = 1.0

        for _ in range(max(iterations, 8)):
            candidate = current.copy()
            remove_idx = random.randrange(len(candidate))
            removed_number = candidate[remove_idx]
            target_group = membership[removed_number] or "low"
            replacement_pool = [
                number for number in self.probability_group_profiles.get("groups", {}).get(target_group, [])
                if number not in candidate and number != removed_number
            ]
            if not replacement_pool:
                continue
            candidate[remove_idx] = random.choice(replacement_pool)
            candidate = sorted(candidate)
            proposal_score = self._probability_portfolio_score(candidate, quota)
            delta = proposal_score - current_score
            if delta >= 0 or random.random() < math.exp(delta / max(temperature, 0.08)):
                current = candidate
                current_score = proposal_score
                if proposal_score > best_score:
                    best_numbers = list(candidate)
                    best_score = proposal_score
            temperature *= 0.92

        return best_numbers, best_score

    def _giannella_zone_index(self, number):
        if number <= 9:
            return 0
        if number <= 19:
            return 1
        if number <= 29:
            return 2
        if number <= 39:
            return 3
        return 4

    def _giannella_gap_bucket(self, gap):
        if gap <= 1:
            return 0
        if gap <= 3:
            return 1
        if gap <= 6:
            return 2
        return 3

    def _giannella_pattern_signature(self, numbers):
        sorted_numbers = tuple(sorted(numbers))
        zone_counts = [0] * 5
        for number in sorted_numbers:
            zone_counts[self._giannella_zone_index(number)] += 1
        inner_gaps = [sorted_numbers[idx + 1] - sorted_numbers[idx] - 1 for idx in range(len(sorted_numbers) - 1)]
        gap_signature = tuple(self._giannella_gap_bucket(gap) for gap in inner_gaps)
        return tuple(zone_counts), gap_signature

    def _build_giannella_pattern_stats(self):
        zone_counter = Counter()
        gap_counter = Counter()
        odd_counter = Counter()
        lower_half_counter = Counter()
        consecutive_counter = Counter()
        recent_zone_counter = Counter()
        recent_gap_counter = Counter()
        recent_odd_counter = Counter()
        recent_lower_half_counter = Counter()
        recent_consecutive_counter = Counter()
        recent_window = min(len(self.rows), 90)

        for idx, row in enumerate(self.rows):
            sorted_row = sorted(row)
            zone_signature, gap_signature = self._giannella_pattern_signature(sorted_row)
            odd_count = sum(number % 2 for number in sorted_row)
            lower_half_count = sum(1 for number in sorted_row if number <= 22)
            consecutive_pairs = sum(1 for pos in range(len(sorted_row) - 1) if sorted_row[pos + 1] - sorted_row[pos] == 1)
            zone_counter[zone_signature] += 1
            gap_counter[gap_signature] += 1
            odd_counter[odd_count] += 1
            lower_half_counter[lower_half_count] += 1
            consecutive_counter[consecutive_pairs] += 1
            if idx < recent_window:
                recent_zone_counter[zone_signature] += 1
                recent_gap_counter[gap_signature] += 1
                recent_odd_counter[odd_count] += 1
                recent_lower_half_counter[lower_half_count] += 1
                recent_consecutive_counter[consecutive_pairs] += 1

        return {
            "zone_counter": dict(zone_counter),
            "gap_counter": dict(gap_counter),
            "odd_counter": dict(odd_counter),
            "lower_half_counter": dict(lower_half_counter),
            "consecutive_counter": dict(consecutive_counter),
            "recent_zone_counter": dict(recent_zone_counter),
            "recent_gap_counter": dict(recent_gap_counter),
            "recent_odd_counter": dict(recent_odd_counter),
            "recent_lower_half_counter": dict(recent_lower_half_counter),
            "recent_consecutive_counter": dict(recent_consecutive_counter),
        }

    def _build_giannella_segment_profiles(self):
        signature_counter = Counter()
        recent_signature_counter = Counter()
        recent_window = min(len(self.rows), 120)

        for idx, row in enumerate(self.rows):
            sorted_row = sorted(int(number) for number in row)
            zone_signature, gap_signature = self._giannella_pattern_signature(sorted_row)
            odd_count = sum(number % 2 for number in sorted_row)
            lower_half_count = sum(1 for number in sorted_row if number <= 22)
            consecutive_pairs = sum(1 for pos in range(len(sorted_row) - 1) if sorted_row[pos + 1] - sorted_row[pos] == 1)
            signature = (zone_signature, gap_signature, odd_count, lower_half_count, consecutive_pairs)
            signature_counter[signature] += 1
            if idx < recent_window:
                recent_signature_counter[signature] += 1

        ranked_signatures = []
        for signature, count in signature_counter.items():
            score = 1.0 + float(count) + float(recent_signature_counter.get(signature, 0)) * 2.45
            ranked_signatures.append((signature, score))
        ranked_signatures.sort(key=lambda item: item[1], reverse=True)
        return {
            "signature_counter": dict(signature_counter),
            "recent_signature_counter": dict(recent_signature_counter),
            "ranked_signatures": ranked_signatures,
        }

    def _giannella_pattern_score(self, numbers):
        features = self._ticket_features(numbers)
        zone_signature = features["zone_signature"]
        gap_signature = features["gap_signature"]
        odd_count = features["odd_count"]
        lower_half_count = features["lower_half_count"]
        consecutive_pairs = features["consecutive_pairs"]
        zone_counter = self.giannella_pattern_stats.get("zone_counter", {})
        gap_counter = self.giannella_pattern_stats.get("gap_counter", {})
        odd_counter = self.giannella_pattern_stats.get("odd_counter", {})
        lower_half_counter = self.giannella_pattern_stats.get("lower_half_counter", {})
        consecutive_counter = self.giannella_pattern_stats.get("consecutive_counter", {})
        recent_zone_counter = self.giannella_pattern_stats.get("recent_zone_counter", {})
        recent_gap_counter = self.giannella_pattern_stats.get("recent_gap_counter", {})
        recent_odd_counter = self.giannella_pattern_stats.get("recent_odd_counter", {})
        recent_lower_half_counter = self.giannella_pattern_stats.get("recent_lower_half_counter", {})
        recent_consecutive_counter = self.giannella_pattern_stats.get("recent_consecutive_counter", {})

        zone_weight = 1.0 + float(zone_counter.get(zone_signature, 0)) + float(recent_zone_counter.get(zone_signature, 0)) * 2.2
        gap_weight = 1.0 + float(gap_counter.get(gap_signature, 0)) + float(recent_gap_counter.get(gap_signature, 0)) * 1.8
        odd_weight = 1.0 + float(odd_counter.get(odd_count, 0)) + float(recent_odd_counter.get(odd_count, 0)) * 1.3
        lower_half_weight = 1.0 + float(lower_half_counter.get(lower_half_count, 0)) + float(recent_lower_half_counter.get(lower_half_count, 0)) * 1.2
        consecutive_weight = 1.0 + float(consecutive_counter.get(consecutive_pairs, 0)) + float(recent_consecutive_counter.get(consecutive_pairs, 0)) * 1.1
        return (
            math.log(zone_weight) * 1.02
            + math.log(gap_weight) * 0.84
            + math.log(odd_weight) * 0.34
            + math.log(lower_half_weight) * 0.28
            + math.log(consecutive_weight) * 0.22
        )

    def _pattern_span_bucket(self, span):
        if span <= 18:
            return 0
        if span <= 24:
            return 1
        if span <= 30:
            return 2
        if span <= 36:
            return 3
        return 4

    def _pattern_signature(self, numbers):
        sorted_numbers = tuple(sorted(int(number) for number in numbers))
        zone_counts = [0] * 5
        for number in sorted_numbers:
            zone_counts[self._giannella_zone_index(number)] += 1
        gaps = [sorted_numbers[idx + 1] - sorted_numbers[idx] - 1 for idx in range(len(sorted_numbers) - 1)]
        tight_gaps = sum(1 for gap in gaps if gap <= 2)
        mid_gaps = sum(1 for gap in gaps if 3 <= gap <= 5)
        wide_gaps = sum(1 for gap in gaps if gap >= 6)
        max_gap_bucket = self._giannella_gap_bucket(max(gaps) if gaps else 0)
        span_bucket = self._pattern_span_bucket(sorted_numbers[-1] - sorted_numbers[0]) if sorted_numbers else 0
        zone_density = tuple(min(count, 3) for count in zone_counts)
        gap_profile = (tight_gaps, mid_gaps, wide_gaps, max_gap_bucket)
        edge_balance = sum(1 for number in sorted_numbers if number <= 10 or number >= 36)
        consecutive_pairs = sum(1 for idx in range(len(sorted_numbers) - 1) if sorted_numbers[idx + 1] - sorted_numbers[idx] == 1)
        return zone_density, gap_profile, span_bucket, edge_balance, consecutive_pairs

    def _build_pattern_signature_stats(self):
        signature_counter = Counter()
        zone_counter = Counter()
        gap_counter = Counter()
        span_counter = Counter()
        edge_counter = Counter()
        recent_signature_counter = Counter()
        recent_zone_counter = Counter()
        recent_gap_counter = Counter()
        recent_span_counter = Counter()
        recent_edge_counter = Counter()
        recent_window = min(len(self.rows), 120)

        for idx, row in enumerate(self.rows):
            signature = self._pattern_signature(row)
            zone_density, gap_profile, span_bucket, edge_balance, _consecutive_pairs = signature
            signature_counter[signature] += 1
            zone_counter[zone_density] += 1
            gap_counter[gap_profile] += 1
            span_counter[span_bucket] += 1
            edge_counter[edge_balance] += 1
            if idx < recent_window:
                recent_signature_counter[signature] += 1
                recent_zone_counter[zone_density] += 1
                recent_gap_counter[gap_profile] += 1
                recent_span_counter[span_bucket] += 1
                recent_edge_counter[edge_balance] += 1

        return {
            "signature_counter": dict(signature_counter),
            "zone_counter": dict(zone_counter),
            "gap_counter": dict(gap_counter),
            "span_counter": dict(span_counter),
            "edge_counter": dict(edge_counter),
            "recent_signature_counter": dict(recent_signature_counter),
            "recent_zone_counter": dict(recent_zone_counter),
            "recent_gap_counter": dict(recent_gap_counter),
            "recent_span_counter": dict(recent_span_counter),
            "recent_edge_counter": dict(recent_edge_counter),
        }

    def _pattern_signature_score(self, numbers):
        signature = self._pattern_signature(numbers)
        zone_density, gap_profile, span_bucket, edge_balance, _consecutive_pairs = signature
        signature_counter = self.pattern_signature_stats.get("signature_counter", {})
        zone_counter = self.pattern_signature_stats.get("zone_counter", {})
        gap_counter = self.pattern_signature_stats.get("gap_counter", {})
        span_counter = self.pattern_signature_stats.get("span_counter", {})
        edge_counter = self.pattern_signature_stats.get("edge_counter", {})
        recent_signature_counter = self.pattern_signature_stats.get("recent_signature_counter", {})
        recent_zone_counter = self.pattern_signature_stats.get("recent_zone_counter", {})
        recent_gap_counter = self.pattern_signature_stats.get("recent_gap_counter", {})
        recent_span_counter = self.pattern_signature_stats.get("recent_span_counter", {})
        recent_edge_counter = self.pattern_signature_stats.get("recent_edge_counter", {})

        signature_weight = 1.0 + float(signature_counter.get(signature, 0)) + float(recent_signature_counter.get(signature, 0)) * 1.55
        zone_weight = 1.0 + float(zone_counter.get(zone_density, 0)) + float(recent_zone_counter.get(zone_density, 0)) * 1.35
        gap_weight = 1.0 + float(gap_counter.get(gap_profile, 0)) + float(recent_gap_counter.get(gap_profile, 0)) * 1.20
        span_weight = 1.0 + float(span_counter.get(span_bucket, 0)) + float(recent_span_counter.get(span_bucket, 0)) * 0.95
        edge_weight = 1.0 + float(edge_counter.get(edge_balance, 0)) + float(recent_edge_counter.get(edge_balance, 0)) * 0.80
        return (
            math.log(signature_weight) * 1.02
            + math.log(zone_weight) * 0.74
            + math.log(gap_weight) * 0.68
            + math.log(span_weight) * 0.28
            + math.log(edge_weight) * 0.18
        )

    def _group_bucket_index(self, number):
        return min((int(number) - 1) // 15, 2)

    def _group_portfolio_signature(self, numbers):
        sorted_numbers = tuple(sorted(int(number) for number in numbers))
        group_counts = [0] * 3
        odd_count = 0
        lower_half_count = 0
        consecutive_pairs = 0
        for idx, number in enumerate(sorted_numbers):
            group_counts[self._group_bucket_index(number)] += 1
            odd_count += number % 2
            if number <= 22:
                lower_half_count += 1
            if idx and number - sorted_numbers[idx - 1] == 1:
                consecutive_pairs += 1
        return tuple(group_counts), odd_count, lower_half_count, consecutive_pairs

    def _build_group_portfolio_stats(self):
        signature_counter = Counter()
        recent_signature_counter = Counter()
        recent_window = min(len(self.rows), 120)
        for idx, row in enumerate(self.rows):
            signature = self._group_portfolio_signature(row)
            signature_counter[signature] += 1
            if idx < recent_window:
                recent_signature_counter[signature] += 1
        return {
            "signature_counter": dict(signature_counter),
            "recent_signature_counter": dict(recent_signature_counter),
        }

    def _group_portfolio_score(self, numbers):
        features = self._ticket_features(numbers)
        signature = features["group_signature"]
        signature_counter = self.group_portfolio_stats.get("signature_counter", {})
        recent_signature_counter = self.group_portfolio_stats.get("recent_signature_counter", {})
        signature_weight = 1.0 + float(signature_counter.get(signature, 0)) + float(recent_signature_counter.get(signature, 0)) * 1.8
        return math.log(signature_weight)

    def _build_probability_weight_lookup(self):
        lookup = [0.0] * 46
        for number in self.universe:
            projected_factor = max(self.projected_probability_lookup[number] / self.base_hit_probability, 1e-12)
            transition_factor = max(self.markov_transition_weight_lookup[number], 1e-12)
            gap_factor = max(self.gap_factor_lookup[number], 1e-12)
            lookup[number] = max((projected_factor ** 1.25) * (transition_factor ** 0.65) * (gap_factor ** 0.50), 1e-9)

        # 정규화: 평균 가중치가 1.0이 되도록 조정 (상대적 비교 기준 유지)
        mean_weight = sum(lookup[number] for number in self.universe) / len(self.universe)
        if mean_weight > 0:
            for number in self.universe:
                lookup[number] /= mean_weight
        return lookup

    def _build_base_position_weights(self):
        weights = [[0.0] * 46 for _ in range(6)]
        recent_window = min(len(self.rows), 90)
        recent_rows = self.rows[:recent_window]
        recent_position_counters = [Counter() for _ in range(6)]
        for row in recent_rows:
            sorted_row = sorted(int(number) for number in row)
            for position, number in enumerate(sorted_row):
                recent_position_counters[position][number] += 1

        historical_position_totals = [sum(counter.values()) for counter in self.position_counters]
        recent_position_totals = [sum(counter.values()) for counter in recent_position_counters]

        for position in range(6):
            historical_avg = max(historical_position_totals[position] / 45.0, 1e-6)
            recent_avg = max(recent_position_totals[position] / 45.0, 1e-6)
            raw_row_values = []
            for number in self.universe:
                total_f = (self.total_counter[number] + 1.0) / (self.avg_total_freq + 1.0)
                position_f = (self.position_counters[position][number] + 1.0) / (historical_avg + 1.0)
                recent_f = (recent_position_counters[position][number] + 1.0) / (recent_avg + 1.0)
                gap_f = max(self.gap_factor_lookup[number], 1e-12)
                value = max(
                    (position_f ** 1.16)
                    * (recent_f ** 0.92)
                    * (total_f ** 0.34)
                    * (gap_f ** 0.58),
                    1e-9,
                )
                weights[position][number] = value
                raw_row_values.append(value)
            row_mean = sum(raw_row_values) / len(raw_row_values) if raw_row_values else 1.0
            if row_mean > 0:
                for number in self.universe:
                    weights[position][number] /= row_mean
        return weights

    def _build_log_lookup(self, values, normalize_by_base=False):
        lookup = [0.0] * 46
        for number in self.universe:
            value = float(values[number])
            if normalize_by_base:
                value /= self.base_hit_probability
            lookup[number] = math.log(max(value, 1e-12))
        return lookup

    def _build_pair_log_matrix(self):
        matrix = [[0.0] * 46 for _ in range(46)]
        for left in self.universe:
            source_row = self.pair_strength_matrix[left]
            target_row = matrix[left]
            for right in self.universe:
                target_row[right] = math.log(max(min(source_row[right], 1.13), 0.91))
        return matrix

    def _normalized_pair_factor(self, number, selected=None):
        selected = [int(n) for n in (selected or []) if int(n) in self.universe and int(n) != int(number)]
        if not selected:
            return 1.0
        pair_strength = sum(self.pair_strength_matrix[int(number)][picked] for picked in selected) / len(selected)
        return min(max(pair_strength, 0.92), 1.10)

    def _ticket_features(self, numbers):
        sorted_numbers = tuple(sorted(int(number) for number in numbers))
        cached = self._ticket_feature_cache.get(sorted_numbers)
        if cached is not None:
            return cached

        zone_counts = [0] * 5
        group_counts = [0] * 3
        decade_counts = [0] * 5
        odd_count = 0
        lower_half_count = 0
        consecutive_pairs = 0
        latest_overlap = 0
        gap_signature = []
        probability_log_score = 0.0
        transition_log_score = 0.0
        position_log_score = 0.0

        previous_number = None
        for position, number in enumerate(sorted_numbers):
            zone_counts[self._giannella_zone_index(number)] += 1
            group_counts[self._group_bucket_index(number)] += 1
            decade_counts[(number - 1) // 10] += 1
            odd_count += number % 2
            lower_half_count += 1 if number <= 22 else 0
            latest_overlap += 1 if number in self.latest_row_set else 0
            probability_log_score += self._projected_log_lookup[number]
            transition_log_score += (
                self._transition_log_lookup[number]
                + self._state_log_lookup[number] * 0.55
                + self._anchor_log_lookup[number] * 0.45
            )
            position_log_score += math.log(max(self.base_position_weights[position][number], 1e-12))
            if previous_number is not None:
                gap_signature.append(self._giannella_gap_bucket(number - previous_number - 1))
                if number - previous_number == 1:
                    consecutive_pairs += 1
            previous_number = number

        pair_log_sum = 0.0
        for idx in range(len(sorted_numbers)):
            left = sorted_numbers[idx]
            for jdx in range(idx + 1, len(sorted_numbers)):
                pair_log_sum += self._pair_log_matrix[left][sorted_numbers[jdx]]

        features = {
            "sorted_numbers": sorted_numbers,
            "zone_signature": tuple(zone_counts),
            "gap_signature": tuple(gap_signature),
            "odd_count": odd_count,
            "lower_half_count": lower_half_count,
            "consecutive_pairs": consecutive_pairs,
            "group_signature": (tuple(group_counts), odd_count, lower_half_count, consecutive_pairs),
            "max_decade": max(decade_counts) if decade_counts else 0,
            "latest_overlap": latest_overlap,
            "probability_log_score": probability_log_score,
            "transition_log_score": transition_log_score,
            "position_log_score": position_log_score,
            "pair_log_component": pair_log_sum / 15.0,
        }
        self._ticket_feature_cache[sorted_numbers] = features
        return features

    def _simulation_profile(self, simulation_count, sets=5):
        simulation_count = _sanitize_simulation_count(simulation_count)
        quota_pool_size = max(3, min(10, 3 + (simulation_count // 2600)))
        segment_pool_size = max(4, min(18, 4 + (simulation_count // 1800)))
        candidate_iterations = min(max(sets * 120, 800 + (simulation_count // 2)), 7200)
        refine_iterations = 10 + min(simulation_count // 2200, 10)
        markov_mix = min(0.42, 0.18 + (simulation_count / 42000.0))
        giannella_mix = min(0.46, 0.26 + (simulation_count / 36000.0))
        return {
            "simulation_count": simulation_count,
            "quota_pool_size": quota_pool_size,
            "segment_pool_size": segment_pool_size,
            "candidate_iterations": candidate_iterations,
            "refine_iterations": refine_iterations,
            "markov_mix": markov_mix,
            "giannella_mix": giannella_mix,
        }

    def _group_quota_from_numbers(self, numbers):
        membership = self.probability_group_profiles.get("membership", [""] * 46)
        counts = {"high": 0, "mid": 0, "low": 0}
        for number in numbers:
            counts[membership[number] or "low"] += 1
        return counts["high"], counts["mid"], counts["low"]

    def _candidate_core_weight(self, number, selected=None):
        selected = selected or []
        projected_factor = max(self.projected_probability_lookup[number] / self.base_hit_probability, 1e-12)
        probability_factor = max(self.probability_weight_lookup[number], 1e-12)
        transition_factor = max(self.markov_transition_weight_lookup[number], 1e-12)
        gap_factor = max(self.gap_factor_lookup[number], 1e-12)
        pair_factor = self._normalized_pair_factor(number, selected)
        latest_penalty = 0.95 if self.rows and number in self.rows[0] else 1.0
        return max(
            (projected_factor ** 0.78)
            * (probability_factor ** 0.92)
            * (transition_factor ** 0.88)
            * (gap_factor ** 0.36)
            * (pair_factor ** 0.35)
            * latest_penalty,
            1e-12,
        )

    def _sample_giannella_segment_ticket(self, segment_signature):
        zone_signature, _gap_signature, odd_target, lower_half_target, consecutive_target = segment_signature
        selected = []
        score = 0.0
        zone_pools = {
            0: list(range(1, 10)),
            1: list(range(10, 20)),
            2: list(range(20, 30)),
            3: list(range(30, 40)),
            4: list(range(40, 46)),
        }

        for zone_index, pick_count in enumerate(zone_signature):
            if pick_count <= 0:
                continue
            available = [number for number in zone_pools.get(zone_index, []) if number not in selected]
            for _ in range(pick_count):
                if not available:
                    break
                deterministic_weights = []
                sampled_weights = []
                for number in available:
                    weight = self._candidate_core_weight(number, selected)
                    if (number % 2) == (odd_target % 2):
                        weight *= 1.02
                    if (number <= 22) == (len([n for n in selected if n <= 22]) < lower_half_target):
                        weight *= 1.03
                    deterministic_weights.append(weight)
                    sampled_weights.append(weight * random.uniform(0.987, 1.013))
                selected_index = random.choices(range(len(available)), weights=sampled_weights, k=1)[0]
                picked_number = available.pop(selected_index)
                selected.append(picked_number)
                score += math.log(max(deterministic_weights[selected_index], 1e-12))

        while len(selected) < 6:
            available = [number for number in self.universe if number not in selected]
            deterministic_weights = [self._candidate_core_weight(number, selected) for number in available]
            sampled_weights = [weight * random.uniform(0.987, 1.013) for weight in deterministic_weights]
            selected_index = random.choices(range(len(available)), weights=sampled_weights, k=1)[0]
            selected.append(available[selected_index])
            score += math.log(max(deterministic_weights[selected_index], 1e-12))

        selected = sorted(selected)
        gap_penalty = 0.0
        actual_consecutive_pairs = sum(1 for idx in range(len(selected) - 1) if selected[idx + 1] - selected[idx] == 1)
        if actual_consecutive_pairs > consecutive_target + 1:
            gap_penalty -= 0.18 * (actual_consecutive_pairs - consecutive_target)
        return selected, score + self._giannella_pattern_score(selected) + gap_penalty

    def _current_gap_factor(self, number):
        return self.gap_factor_lookup[number]

    def _probability_only_weight(self, number):
        return self.probability_weight_lookup[number]

    def average_gap_factor(self, numbers):
        numbers = [int(n) for n in numbers if int(n) in self.universe]
        if not numbers:
            return 0.0
        return round(sum(self._current_gap_factor(n) for n in numbers) / len(numbers), 6)

    def average_probability_weight(self, numbers):
        numbers = [int(n) for n in numbers if int(n) in self.universe]
        if not numbers:
            return 0.0
        return round(sum(self._probability_only_weight(n) for n in numbers) / len(numbers), 6)

    def _number_weight(self, number, position, selected=None, probability_only=False):
        selected = [int(n) for n in (selected or []) if int(n) in self.universe and int(n) != int(number)]
        number = int(number)
        position = max(0, min(int(position), 5))

        gap_factor = max(self._current_gap_factor(number), 1e-12)
        probability_factor = max(self._probability_only_weight(number), 1e-12)
        latest_penalty = 0.95 if self.rows and number in self.rows[0] else 1.0

        if probability_only:
            return max((probability_factor ** 1.1) * (gap_factor ** 0.45) * latest_penalty, 1e-12)

        base_weight = max(self.base_position_weights[position][number], 1e-12)
        transition_weight = max(self._markov_chain_weight(number, selected), 1e-12)
        pair_factor = self._normalized_pair_factor(number, selected)

        return max(
            (base_weight ** 1.0)
            * (probability_factor ** 0.85)
            * (transition_weight ** 0.75)
            * (pair_factor ** 0.35)
            * (gap_factor ** 0.25)
            * latest_penalty,
            1e-12,
        )

    def _markov_chain_weight(self, number, anchors=None):
        anchors = anchors or []
        latest_transition = self.latest_row_transition_lookup[number]
        latest_factor = max(latest_transition / self.base_hit_probability, 0.55)

        if anchors:
            anchor_transition = sum(self.markov_transition_matrix[source][number] for source in anchors) / len(anchors)
            anchor_factor = max(anchor_transition / self.base_hit_probability, 0.55)
        else:
            anchor_factor = 1.0

        markov_weight = max(self.markov_transition_weight_lookup[number], 1e-12)
        probability_weight = max(self.probability_weight_lookup[number], 1e-12)
        return max((markov_weight ** 0.9) * (probability_weight ** 0.4) * (latest_factor ** 0.6) * (anchor_factor ** 0.45), 1e-12)

    def _sample_markov_seed_ticket(self):
        available = self.universe.copy()
        picked = []
        score = 0.0
        for _ in range(6):
            deterministic_weights = [self._markov_chain_weight(number, picked) for number in available]
            sampled_weights = [weight * random.uniform(0.985, 1.015) for weight in deterministic_weights]
            if sum(sampled_weights) <= 0:
                sampled_weights = [1.0] * len(available)
            selected_index = random.choices(range(len(available)), weights=sampled_weights, k=1)[0]
            selected_number = available.pop(selected_index)
            picked.append(selected_number)
            score += math.log(max(deterministic_weights[selected_index], 1e-12))
        return sorted(picked), score

    def _build_probability_direct_profile(self, simulation_count, sets=5):
        simulation_count = _sanitize_simulation_count(simulation_count)
        min_simulation_count = 1000
        max_simulation_count = 50000
        sim_range = max(max_simulation_count - min_simulation_count, 1)
        normalized_scale = min(max((simulation_count - min_simulation_count) / sim_range, 0.0), 1.0)
        candidate_iterations = min(max(sets * 140, 900 + (simulation_count // 3)), 4800)
        repair_iterations = 2 + int(normalized_scale * 4)
        segment_pool_size = max(4, min(14, 4 + (simulation_count // 2500)))
        transition_sharpness = 1.0 + (normalized_scale * 0.32)
        transition_weight = 1.08 + (normalized_scale * 0.24)
        pattern_weight = 0.84 + (normalized_scale * 0.36)
        segment_weight = 0.22 + (normalized_scale * 0.18)
        noise_span = max(0.0015, 0.010 - (normalized_scale * 0.006))
        return {
            "simulation_count": simulation_count,
            "normalized_scale": normalized_scale,
            "candidate_iterations": candidate_iterations,
            "repair_iterations": repair_iterations,
            "segment_pool_size": segment_pool_size,
            "transition_sharpness": transition_sharpness,
            "transition_weight": transition_weight,
            "pattern_weight": pattern_weight,
            "segment_weight": segment_weight,
            "noise_span": noise_span,
            "cache_bucket": round(normalized_scale, 3),
        }

    def _probability_segment_match_score(self, numbers, segment_signature):
        if not segment_signature:
            return 0.0
        sorted_numbers = tuple(sorted(int(number) for number in numbers))
        zone_signature_target, gap_signature_target, odd_target, lower_half_target, consecutive_target = segment_signature
        zone_signature_actual, gap_signature_actual = self._giannella_pattern_signature(sorted_numbers)
        odd_actual = sum(number % 2 for number in sorted_numbers)
        lower_half_actual = sum(1 for number in sorted_numbers if number <= 22)
        consecutive_actual = sum(
            1 for idx in range(len(sorted_numbers) - 1) if sorted_numbers[idx + 1] - sorted_numbers[idx] == 1
        )
        zone_distance = sum(abs(left - right) for left, right in zip(zone_signature_actual, zone_signature_target))
        gap_distance = sum(abs(left - right) for left, right in zip(gap_signature_actual, gap_signature_target))
        odd_distance = abs(odd_actual - odd_target)
        lower_half_distance = abs(lower_half_actual - lower_half_target)
        consecutive_distance = abs(consecutive_actual - consecutive_target)
        return 1.0 / (
            1.0
            + (zone_distance * 0.90)
            + (gap_distance * 0.72)
            + (odd_distance * 0.45)
            + (lower_half_distance * 0.34)
            + (consecutive_distance * 0.52)
        )

    def _markov_transition_seed_weight(self, number, anchors, simulation_profile):
        anchor_list = list(anchors) if anchors else list(self.rows[0]) if self.rows else []
        latest_transition = max(self.latest_row_transition_lookup[number], 1e-12)
        latest_factor = max(latest_transition / self.base_hit_probability, 0.35)
        if anchor_list:
            anchor_transition = sum(self.markov_transition_matrix[source][number] for source in anchor_list) / len(anchor_list)
            anchor_factor = max(anchor_transition / self.base_hit_probability, 0.35)
        else:
            anchor_factor = latest_factor
        recency_penalty = 0.96 if self.rows and number in self.rows[0] else 1.0
        return max(
            (latest_factor ** (0.92 * simulation_profile["transition_sharpness"]))
            * (anchor_factor ** (1.08 * simulation_profile["transition_sharpness"]))
            * recency_penalty,
            1e-12,
        )

    def _sample_markov_giannella_ticket(self, segment_signature, simulation_profile):
        if segment_signature is None:
            ranked_segments = self.giannella_segment_profiles.get("ranked_signatures", [])
            segment_signature = ranked_segments[0][0] if ranked_segments else ((1, 1, 1, 2, 1), (1, 1, 1, 1, 1), 3, 3, 0)

        zone_signature, _gap_signature, odd_target, lower_half_target, _consecutive_target = segment_signature
        zone_pools = {
            0: list(range(1, 10)),
            1: list(range(10, 20)),
            2: list(range(20, 30)),
            3: list(range(30, 40)),
            4: list(range(40, 46)),
        }
        selected = []

        for zone_index, pick_count in enumerate(zone_signature):
            if pick_count <= 0:
                continue
            for _ in range(pick_count):
                available = [number for number in zone_pools.get(zone_index, []) if number not in selected]
                if not available:
                    break
                weights = []
                for number in available:
                    weight = self._markov_transition_seed_weight(number, selected, simulation_profile)
                    current_odd = sum(value % 2 for value in selected)
                    current_lower_half = sum(1 for value in selected if value <= 22)
                    remaining_slots = max(6 - len(selected), 1)
                    if current_odd < odd_target and (number % 2 == 1):
                        weight *= 1.04 + (0.02 / remaining_slots)
                    if current_lower_half < lower_half_target and number <= 22:
                        weight *= 1.03 + (0.02 / remaining_slots)
                    weights.append(weight * random.uniform(1.0 - simulation_profile["noise_span"], 1.0 + simulation_profile["noise_span"]))
                selected_number = random.choices(available, weights=weights, k=1)[0]
                selected.append(selected_number)

        while len(selected) < 6:
            available = [number for number in self.universe if number not in selected]
            weights = [
                self._markov_transition_seed_weight(number, selected, simulation_profile)
                * random.uniform(1.0 - simulation_profile["noise_span"], 1.0 + simulation_profile["noise_span"])
                for number in available
            ]
            selected.append(random.choices(available, weights=weights, k=1)[0])

        selected = sorted(selected)
        score = self._probability_transition_score(selected, simulation_profile, segment_signature)
        return selected, score

    def _probability_transition_score(self, numbers, simulation_profile, segment_signature=None):
        sorted_numbers = tuple(sorted(int(number) for number in numbers))
        if len(sorted_numbers) != 6 or len(set(sorted_numbers)) != 6:
            return -1e12

        cache_key = (sorted_numbers, simulation_profile["cache_bucket"])
        cached_score = self._probability_mcmc_score_cache.get(cache_key)
        if cached_score is not None:
            return cached_score

        transition_score = 0.0
        anchors = list(self.rows[0]) if self.rows else []
        picked = []
        for number in sorted_numbers:
            weight = self._markov_transition_seed_weight(number, picked or anchors, simulation_profile)
            transition_score += math.log(max(weight, 1e-12))
            picked.append(number)

        giannella_score = self._giannella_pattern_score(sorted_numbers)
        segment_match_score = self._probability_segment_match_score(sorted_numbers, segment_signature)
        total_score = (
            (transition_score * simulation_profile["transition_weight"])
            + (giannella_score * simulation_profile["pattern_weight"])
            + (segment_match_score * simulation_profile["segment_weight"])
        )
        self._probability_mcmc_score_cache[cache_key] = total_score
        return total_score

    def _repair_markov_giannella_ticket(self, seed_numbers, segment_signature, simulation_profile):
        current = sorted(int(number) for number in seed_numbers)
        current_score = self._probability_transition_score(current, simulation_profile, segment_signature)
        best_numbers = list(current)
        best_score = current_score

        zone_target = segment_signature[0] if segment_signature else None
        odd_target = segment_signature[2] if segment_signature else None
        lower_half_target = segment_signature[3] if segment_signature else None

        for _ in range(max(simulation_profile["repair_iterations"], 2)):
            candidate = current.copy()
            remove_index = random.randrange(len(candidate))
            retained = set(candidate)
            retained.remove(candidate[remove_index])
            replacement_pool = [number for number in self.universe if number not in retained]
            if not replacement_pool:
                continue

            preferred_pool = replacement_pool
            if zone_target:
                current_zone_counts = [0] * 5
                for number in retained:
                    current_zone_counts[self._giannella_zone_index(number)] += 1
                deficit_zones = [idx for idx, target in enumerate(zone_target) if current_zone_counts[idx] < target]
                zone_filtered = [number for number in replacement_pool if self._giannella_zone_index(number) in deficit_zones]
                if zone_filtered:
                    preferred_pool = zone_filtered

            weights = []
            retained_list = sorted(retained)
            current_odd = sum(number % 2 for number in retained_list)
            current_lower_half = sum(1 for number in retained_list if number <= 22)
            for number in preferred_pool:
                weight = self._markov_transition_seed_weight(number, retained_list, simulation_profile)
                if odd_target is not None and current_odd < odd_target and (number % 2 == 1):
                    weight *= 1.04
                if lower_half_target is not None and current_lower_half < lower_half_target and number <= 22:
                    weight *= 1.03
                weights.append(weight)

            replacement_number = random.choices(preferred_pool, weights=weights, k=1)[0]
            candidate[remove_index] = replacement_number
            candidate = sorted(candidate)
            proposal_score = self._probability_transition_score(candidate, simulation_profile, segment_signature)
            if proposal_score >= current_score:
                current = candidate
                current_score = proposal_score
                if proposal_score > best_score:
                    best_numbers = list(candidate)
                    best_score = proposal_score

        return best_numbers, best_score

    # ══════════════════════════════════════════════════════════════════════
    # ★ 강화 분석 메서드 v2 ★
    # ══════════════════════════════════════════════════════════════════════

    def _build_cycle_stats(self):
        """[1] 출현 주기(Cycle) 분포 통계
        번호별 출현 간격(gap sequence)을 분석하여 다음 출현 예상 시점 계산.
        - avg_cycle  : 평균 출현 간격
        - std_cycle  : 간격의 표준편차 (일관성 지표)
        - due_score  : (현재 gap - avg_cycle) / std_cycle  → 양수일수록 '나올 때 됨'
        """
        stats = {}
        for n in self.universe:
            appearances = []
            for idx, row in enumerate(self.rows):
                if n in row:
                    appearances.append(idx)
            if len(appearances) < 2:
                stats[n] = {"avg_cycle": 7.5, "std_cycle": 5.0, "due_score": 0.0}
                continue
            gaps = [appearances[i + 1] - appearances[i] for i in range(len(appearances) - 1)]
            avg = sum(gaps) / len(gaps)
            variance = sum((g - avg) ** 2 for g in gaps) / len(gaps)
            std = max(variance ** 0.5, 1.0)
            current_gap = self.last_seen_gap.get(n, 0)
            due_score = (current_gap - avg) / std
            stats[n] = {"avg_cycle": round(avg, 2), "std_cycle": round(std, 2), "due_score": round(due_score, 4)}
        return stats

    def _build_cooccurrence_matrix(self, window=200):
        """[2] 번호 동반 출현(Co-occurrence) 행렬
        최근 window 회 데이터 기준으로 번호쌍의 동반 출현 강도를 계산.
        - 정규화: (실제 동반 횟수 / 기대 동반 횟수) → 1.0이면 기대치, >1이면 친화적
        """
        recent = self.rows[:min(window, len(self.rows))]
        pair_count = [[0.0] * 46 for _ in range(46)]
        appear_count = [0] * 46
        n_draws = len(recent)
        for row in recent:
            for n in row:
                appear_count[n] += 1
            nums = [x for x in row if 1 <= x <= 45]
            for i in range(len(nums)):
                for j in range(i + 1, len(nums)):
                    pair_count[nums[i]][nums[j]] += 1
                    pair_count[nums[j]][nums[i]] += 1
        # 정규화: Lift = P(A∩B) / (P(A)*P(B))
        matrix = [[1.0] * 46 for _ in range(46)]
        for i in self.universe:
            for j in self.universe:
                if i == j:
                    continue
                p_i = appear_count[i] / max(n_draws * 6, 1)
                p_j = appear_count[j] / max(n_draws * 6, 1)
                p_ij = pair_count[i][j] / max(n_draws, 1)
                expected = p_i * p_j * n_draws
                matrix[i][j] = p_ij / max(p_i * p_j, 1e-9) if (p_i > 0 and p_j > 0) else 1.0
        return matrix

    def _build_sum_histogram(self, recent_window=50):
        """[5] 합계 대역 히스토그램
        역대 당첨번호 합계 분포를 분석하고 최근 추세를 반영한 동적 목표 범위 산출.
        - all_mean, all_std  : 전체 기간 합계 평균·표준편차
        - recent_mean        : 최근 recent_window 회 평균 (추세 반영)
        - target_min/max     : 추천 대상 합계 범위 [μ-1.2σ, μ+1.2σ]
        """
        if not self.rows:
            return {"all_mean": 138.0, "all_std": 30.0, "recent_mean": 138.0, "target_min": 102, "target_max": 174}
        all_sums = [sum(row) for row in self.rows]
        recent_sums = all_sums[:recent_window]
        mean_all = sum(all_sums) / len(all_sums)
        var_all = sum((s - mean_all) ** 2 for s in all_sums) / len(all_sums)
        std_all = max(var_all ** 0.5, 1.0)
        mean_recent = sum(recent_sums) / len(recent_sums) if recent_sums else mean_all
        # 최근 추세와 전체 평균의 가중 혼합 (최근 40%, 전체 60%)
        blended_mean = mean_all * 0.60 + mean_recent * 0.40
        return {
            "all_mean": round(mean_all, 2),
            "all_std": round(std_all, 2),
            "recent_mean": round(mean_recent, 2),
            "blended_mean": round(blended_mean, 2),
            "target_min": int(blended_mean - std_all * 1.2),
            "target_max": int(blended_mean + std_all * 1.2),
        }

    def _build_tail_stats(self, recent_window=40):
        """[6] 끝자리(Tail digit) 분포 균형 통계
        끝자리 0~9의 최근 출현 빈도 편향을 분석.
        - tail_freq[d]       : 끝자리 d의 최근 출현 빈도 (기대값=0.1 기준 정규화)
        - tail_bias[d]       : freq/기대값 → >1이면 과다 출현, <1이면 과소 출현
        """
        recent = self.rows[:min(recent_window, len(self.rows))]
        tail_count = [0] * 10
        total_nums = 0
        for row in recent:
            for n in row:
                tail_count[n % 10] += 1
                total_nums += 1
        expected = total_nums / 10.0 if total_nums > 0 else 1.0
        tail_freq = {d: tail_count[d] / max(total_nums, 1) for d in range(10)}
        tail_bias = {d: tail_count[d] / max(expected, 1e-6) for d in range(10)}
        return {"tail_freq": tail_freq, "tail_bias": tail_bias, "total_nums": total_nums}

    def _build_streak_stats(self, window=30):
        """[4] 연속 출현/미출현(Streak) 패턴 통계
        번호별로 현재 연속 출현 streak 또는 drought를 추적.
        - current_streak[n]  : 양수=연속출현 횟수, 음수=연속미출현 횟수
        - streak_score[n]    : drought가 길수록 양수(반등 기대), streak이 길수록 음수(과열)
        """
        recent = self.rows[:min(window, len(self.rows))]
        current_streak = {}
        for n in self.universe:
            streak = 0
            for row in recent:
                if n in row:
                    streak = streak + 1 if streak >= 0 else 1
                else:
                    streak = streak - 1 if streak <= 0 else -1
            current_streak[n] = streak

        # streak_score: 미출현 길수록 양수(나올 가능성↑), 연속출현 길수록 음수
        streak_score = {}
        for n in self.universe:
            s = current_streak[n]
            if s <= -3:    # 3회 이상 미출현 → 반등 기대
                streak_score[n] = min((abs(s) - 2) * 0.12, 0.6)
            elif s >= 3:   # 3회 이상 연속 출현 → 과열 패널티
                streak_score[n] = -min((s - 2) * 0.10, 0.5)
            else:
                streak_score[n] = 0.0
        return {"current_streak": current_streak, "streak_score": streak_score}

    def _build_ensemble_weights(self):
        """[7] 앙상블 가중치 – 백테스트 기반 동적 보정
        최근 48회 데이터를 Leave-One-Out 방식으로 검증하여
        각 지표(cycle_due, cooccurrence, sum_fit, tail_fit, streak)의
        실제 당첨 조합을 얼마나 잘 상위 랭킹시키는지 측정 → 기여도 가중치 산출.
        """
        defaults = {
            "cycle_due":       0.18,   # 출현 주기 due_score
            "cooccurrence":    0.14,   # 동반 출현 친화도
            "sum_fit":         0.20,   # 합계 목표 범위 적합도
            "tail_balance":    0.12,   # 끝자리 균형도
            "streak":          0.14,   # 연속 패턴
            "existing_core":   0.22,   # 기존 핵심 점수 (markov+gap+giannella)
        }
        sample = min(max(len(self.rows) - 1, 0), 48)
        if sample < 10:
            return defaults

        cycle_hits, cooc_hits, sum_hits, tail_hits, streak_hits, core_hits = [], [], [], [], [], []
        rng = random.Random(20260601)

        for idx in range(sample):
            actual = tuple(sorted(int(x) for x in self.rows[idx]))
            # 무작위 기준선과 비교: 실제 당첨조합 vs 랜덤 조합
            random_combos = [tuple(sorted(rng.sample(self.universe, 6))) for _ in range(20)]

            def score_cycle(nums):
                return sum(max(self.cycle_stats[n]["due_score"], 0) for n in nums)

            def score_cooc(nums):
                lst = list(nums)
                s = 0.0
                for i in range(len(lst)):
                    for j in range(i + 1, len(lst)):
                        s += self.cooccurrence_matrix[lst[i]][lst[j]]
                return s / 15.0

            def score_sum(nums):
                t_min = self.sum_histogram["target_min"]
                t_max = self.sum_histogram["target_max"]
                t_mid = self.sum_histogram["blended_mean"]
                s = sum(nums)
                if t_min <= s <= t_max:
                    return 1.0 - abs(s - t_mid) / max(t_max - t_min, 1)
                return max(0.0, 1.0 - abs(s - t_mid) / max(abs(t_mid) * 0.5, 20))

            def score_tail(nums):
                tails = [n % 10 for n in nums]
                unique_tails = len(set(tails))
                # 6개 번호의 끝자리가 다양할수록 높은 점수
                return unique_tails / 6.0

            def score_streak(nums):
                return sum(self.streak_stats["streak_score"].get(n, 0) for n in nums)

            def score_core(nums):
                return sum(
                    self.projected_probability_lookup[n] * 2.0
                    + self.gap_factor_lookup[n]
                    for n in nums
                )

            scorers = [score_cycle, score_cooc, score_sum, score_tail, score_streak, score_core]
            hit_lists = [cycle_hits, cooc_hits, sum_hits, tail_hits, streak_hits, core_hits]

            for scorer, hit_list in zip(scorers, hit_lists):
                actual_score = scorer(actual)
                random_scores = [scorer(c) for c in random_combos]
                rank_better = sum(1 for rs in random_scores if actual_score > rs)
                hit_list.append(rank_better / len(random_combos))

        def mean(lst):
            return sum(lst) / len(lst) if lst else 0.5

        raw = {
            "cycle_due":     mean(cycle_hits),
            "cooccurrence":  mean(cooc_hits),
            "sum_fit":       mean(sum_hits),
            "tail_balance":  mean(tail_hits),
            "streak":        mean(streak_hits),
            "existing_core": mean(core_hits),
        }
        total = sum(raw.values()) or 1.0
        # 정규화: 합이 1.0이 되도록 (각 가중치는 최소 0.05 보장)
        weights = {k: max(v / total, 0.05) for k, v in raw.items()}
        w_total = sum(weights.values())
        weights = {k: v / w_total for k, v in weights.items()}
        return weights

    def _ensemble_score(self, numbers):
        """[7] 앙상블 통합 점수
        7개 분석 지표를 앙상블 가중치로 합산한 최종 종합 점수.
        높을수록 이 조합이 통계적으로 출현 가능성이 높음.
        """
        w = self.ensemble_weights
        nums = tuple(sorted(int(n) for n in numbers))

        # ① 출현 주기 due_score 합산
        cycle_score = sum(max(self.cycle_stats[n]["due_score"], 0.0) for n in nums) / 6.0

        # ② 동반 출현 친화도 평균
        cooc_sum = 0.0
        for i in range(len(nums)):
            for j in range(i + 1, len(nums)):
                cooc_sum += self.cooccurrence_matrix[nums[i]][nums[j]]
        cooc_score = cooc_sum / 15.0

        # ③ 합계 목표 범위 적합도
        t_min = self.sum_histogram["target_min"]
        t_max = self.sum_histogram["target_max"]
        t_mid = self.sum_histogram["blended_mean"]
        s = sum(nums)
        if t_min <= s <= t_max:
            sum_score = 1.0 - abs(s - t_mid) / max(t_max - t_min, 1)
        else:
            sum_score = max(0.0, 1.0 - abs(s - t_mid) / max(abs(t_mid) * 0.5, 20))

        # ④ 끝자리 균형도 (섀넌 엔트로피 기반)
        tails = [n % 10 for n in nums]
        unique_tails = len(set(tails))
        tail_score = unique_tails / 6.0
        # 과소 출현 끝자리 선호 보너스
        tail_bias_bonus = sum(
            max(1.0 - self.tail_stats["tail_bias"].get(t, 1.0), 0.0) for t in tails
        ) / 6.0
        tail_score = tail_score * 0.7 + tail_bias_bonus * 0.3

        # ⑤ 연속 패턴 점수
        streak_score = sum(self.streak_stats["streak_score"].get(n, 0.0) for n in nums) / 6.0

        # ⑥ 기존 핵심 점수 (정규화)
        core_raw = sum(
            self.projected_probability_lookup[n] * 1.8
            + self.gap_factor_lookup[n] * 0.4
            for n in nums
        ) / 6.0
        core_score = core_raw / max(self.base_hit_probability * 3.0, 1e-9)

        total = (
            cycle_score  * w.get("cycle_due",    0.18)
            + cooc_score   * w.get("cooccurrence", 0.14)
            + sum_score    * w.get("sum_fit",      0.20)
            + tail_score   * w.get("tail_balance", 0.12)
            + streak_score * w.get("streak",       0.14)
            + core_score   * w.get("existing_core",0.22)
        )
        return round(total, 6)

    def _zone_entropy_score(self, numbers):
        """[3] 구간 균형 엔트로피 점수 (5구간: 1-9, 10-18, 19-27, 28-36, 37-45)
        섀넌 엔트로피가 높을수록 번호가 고르게 분산된 조합 (max=log(5)≈1.609)
        """
        zone_counts = [0] * 5
        for n in numbers:
            zone_counts[(n - 1) // 9] += 1
        total = sum(zone_counts)
        entropy = 0.0
        for c in zone_counts:
            if c > 0:
                p = c / total
                entropy -= p * math.log(p)
        max_entropy = math.log(5)
        return round(entropy / max_entropy, 4)  # 0~1 정규화

    # ══════════════════════════════════════════════════════════════════════
    # ★ 강화 분석 메서드 끝 ★
    # ══════════════════════════════════════════════════════════════════════

    def _build_rolling_backtest_score_config(self):
        defaults = {
            "position_axis_weight": 1.12,
            "pattern_signature_weight": 0.82,
            "pair_axis_weight": 0.40,
            "quota_group_weight": 0.46,
            "quota_efficiency_weight": 0.38,
            "safety_penalty_scale": 0.76,
            "safety_reward_scale": 1.0,
            "rolling_windows_evaluated": 0,
        }
        sample_size = min(max(len(self.rows) - 1, 0), 48)
        if sample_size <= 0:
            return defaults

        quota_scores = self.probability_group_profiles.get("quota_scores", {})
        recent_rows = [tuple(sorted(int(number) for number in row)) for row in self.rows[1 : 1 + sample_size]]
        rng = random.Random(20260422)
        random_samples_per_window = 28

        actual_position = []
        actual_pattern = []
        actual_pair = []
        actual_group = []
        actual_quota = []
        actual_overlap = []
        baseline_position = []
        baseline_pattern = []
        baseline_pair = []
        baseline_group = []
        baseline_quota = []
        baseline_overlap = []

        for actual_numbers in recent_rows:
            actual_features = self._ticket_features(actual_numbers)
            actual_position.append(actual_features["position_log_score"])
            actual_pattern.append(self._pattern_signature_score(actual_numbers))
            actual_pair.append(actual_features["pair_log_component"])
            actual_group.append(self._group_portfolio_score(actual_numbers))
            actual_quota.append(quota_scores.get(self._group_quota_from_numbers(actual_numbers), 0.0))
            actual_overlap.append(1.0 if actual_features["latest_overlap"] >= 3 else 0.0)

            for _ in range(random_samples_per_window):
                sampled_numbers = tuple(sorted(rng.sample(self.universe, 6)))
                sampled_features = self._ticket_features(sampled_numbers)
                baseline_position.append(sampled_features["position_log_score"])
                baseline_pattern.append(self._pattern_signature_score(sampled_numbers))
                baseline_pair.append(sampled_features["pair_log_component"])
                baseline_group.append(self._group_portfolio_score(sampled_numbers))
                baseline_quota.append(quota_scores.get(self._group_quota_from_numbers(sampled_numbers), 0.0))
                baseline_overlap.append(1.0 if sampled_features["latest_overlap"] >= 3 else 0.0)

        def _mean(values):
            return (sum(values) / len(values)) if values else 0.0

        def _ratio_boost(actual_values, baseline_values, strength, lower, upper):
            baseline_mean = _mean(baseline_values)
            relative_gap = (_mean(actual_values) - baseline_mean) / max(abs(baseline_mean), 1e-6)
            return min(max(1.0 + (relative_gap * strength), lower), upper)

        overlap_ratio = _mean(actual_overlap) / max(_mean(baseline_overlap), 1e-6)
        defaults.update({
            "position_axis_weight": _ratio_boost(actual_position, baseline_position, 0.68, 1.00, 1.45),
            "pattern_signature_weight": _ratio_boost(actual_pattern, baseline_pattern, 0.30, 0.72, 1.02),
            "pair_axis_weight": _ratio_boost(actual_pair, baseline_pair, 0.16, 0.28, 0.56),
            "quota_group_weight": _ratio_boost(actual_group, baseline_group, 0.12, 0.26, 0.58),
            "quota_efficiency_weight": _ratio_boost(actual_quota, baseline_quota, 0.10, 0.20, 0.48),
            "safety_penalty_scale": min(max(0.56 + (overlap_ratio * 0.14), 0.56), 0.82),
            "safety_reward_scale": 1.0,
            "rolling_windows_evaluated": sample_size,
        })
        return defaults

    def predict(self, sets=5, simulation_count: int | None = None):
        """패턴 기반 추천 (강화 v2)
        ① 핫/콜드/주기 가중치로 후보 샘플링
        ② 기존 _advanced_pattern_score + 앙상블(_ensemble_score) + 구간엔트로피 결합 최종 점수
        ③ 다양성 필터 + 합계 대역 소프트 필터 적용
        """
        self._probability_portfolio_score_cache = {}
        self._ticket_feature_cache = {}
        simulation_count = _sanitize_simulation_count(simulation_count) if simulation_count is not None else DEFAULT_SIMULATION_COUNT

        hot_cold_stats = self._build_advanced_pattern_stats()
        iterations = max(simulation_count * 2, 10000)

        # 번호별 통합 샘플링 가중치 (핫+콜드+주기 due+gap)
        sample_weights = []
        for n in self.universe:
            hs = hot_cold_stats[n]
            due = max(self.cycle_stats[n]["due_score"], 0.0)
            gap_w = self.gap_factor_lookup[n]
            w = (
                hs["hot"]  * 0.28
                + hs["cold"] * 0.38
                + (1.0 / max(hs["rel_freq"], 0.1)) * 0.14
                + due       * 0.12
                + gap_w     * 0.08
            )
            sample_weights.append(max(w, 0.001))

        t_min = self.sum_histogram["target_min"]
        t_max = self.sum_histogram["target_max"]
        best_by_key = {}

        for _ in range(iterations):
            try:
                drawn = random.choices(self.universe, weights=sample_weights, k=12)
                unique_combo = []
                for num in drawn:
                    if num not in unique_combo:
                        unique_combo.append(num)
                    if len(unique_combo) == 6:
                        break
                if len(unique_combo) < 6:
                    continue
                combo = sorted(unique_combo)
            except Exception:
                continue

            # 합계 대역 소프트 필터 (범위 밖이면 60% 확률로 스킵 → 강제 배제 아님)
            combo_sum = sum(combo)
            if not (t_min <= combo_sum <= t_max):
                if random.random() < 0.60:
                    continue

            # 통합 점수: 기존 패턴 점수 45% + 앙상블 점수 30% + 구간 엔트로피 13% + BIBD 내부 다양성 12%
            # [BIBD 추가] _bibd_internal_diversity_score: 6개 번호의 3-조합(C(6,3)=20개)이
            #   5개 구간에 고르게 분포될수록 높은 점수 → 단일 티켓의 BIBD 커버리지 품질 반영
            pattern_score  = self._advanced_pattern_score(combo)
            ensemble_score = self._ensemble_score(combo)
            entropy_score  = self._zone_entropy_score(combo)
            bibd_score     = self._bibd_internal_diversity_score(combo)
            combined = (
                pattern_score  * 0.45
                + ensemble_score * 0.30
                + entropy_score  * 0.13
                + bibd_score     * 0.12
            )

            key = tuple(combo)
            if key not in best_by_key or combined > best_by_key[key]["score_raw"]:
                best_by_key[key] = {
                    "sorted": list(key),
                    "ordered": None,
                    "score_raw": combined,
                    "pattern": round(pattern_score * 100, 4),
                    "ensemble": round(ensemble_score, 6),
                    "entropy": round(entropy_score, 4),
                    "bibd": round(bibd_score, 4),
                }

        ranked_candidates = sorted(best_by_key.values(), key=lambda x: x["score_raw"], reverse=True)

        final = []
        selected_numbers = []
        for candidate in ranked_candidates:
            overlap = 0
            if selected_numbers:
                overlap = max(len(set(candidate["sorted"]) & set(ex)) for ex in selected_numbers)
            if overlap >= 5 and len(ranked_candidates) > sets:
                continue
            final.append({
                "sorted":   candidate["sorted"],
                "ordered":  None,
                "score":    round(candidate["score_raw"] * 100, 4),
                "pattern_score":  candidate["pattern"],
                "ensemble_score": candidate["ensemble"],
                "entropy_score":  candidate["entropy"],
                "bibd_score":     candidate["bibd"],
            })
            selected_numbers.append(candidate["sorted"])
            if len(final) >= sets:
                break

        # [BIBD 후처리] 최종 선정된 묶음 전체의 커버리지 점수를 각 항목에 추가
        # _bibd_coverage_score: 묶음 내 티켓 간 번호 중복도 측정 (낮을수록 커버리지 효율 ↑)
        if final:
            all_tickets = [item["sorted"] for item in final]
            coverage = self._bibd_coverage_score(all_tickets)
            for item in final:
                item["bibd_coverage"] = round(coverage, 4)

        return final

    def predict_probability_only(self, sets=5, simulation_count: int | None = None):
        """확률 기반 추천 (강화 v2)
        마르코프+자넬라 기존 스코어에 앙상블 점수를 20% 혼합.
        합계 대역 소프트 필터 + 끝자리 균형 보너스 추가.
        """
        self._probability_mcmc_score_cache = {}
        self._ticket_feature_cache = {}
        simulation_count = _sanitize_simulation_count(simulation_count) if simulation_count is not None else DEFAULT_SIMULATION_COUNT
        simulation_profile = self._build_probability_direct_profile(simulation_count, sets=sets)
        ranked_segments = self.giannella_segment_profiles.get("ranked_signatures", [])
        segment_candidates = ranked_segments[: simulation_profile["segment_pool_size"]]
        segment_weights = [max(item[1], 1e-6) for item in segment_candidates] if segment_candidates else []
        t_min = self.sum_histogram["target_min"]
        t_max = self.sum_histogram["target_max"]
        best_by_key = {}

        for _ in range(simulation_profile["candidate_iterations"]):
            segment_signature = None
            if segment_candidates:
                segment_index = random.choices(range(len(segment_candidates)), weights=segment_weights, k=1)[0]
                segment_signature = segment_candidates[segment_index][0]
            seed_numbers, seed_score = self._sample_markov_giannella_ticket(segment_signature, simulation_profile)
            refined_numbers, refined_score = self._repair_markov_giannella_ticket(
                seed_numbers,
                segment_signature,
                simulation_profile,
            )
            key = tuple(sorted(refined_numbers))

            # 합계 대역 소프트 필터
            combo_sum = sum(key)
            if not (t_min <= combo_sum <= t_max):
                if random.random() < 0.50:
                    continue

            giannella_score = self._giannella_pattern_score(key)
            transition_score = self._probability_transition_score(key, simulation_profile, segment_signature)
            base_score = (seed_score * 0.18) + (refined_score * 0.82)

            # 앙상블 보너스 (20% 혼합)
            ensemble_bonus = self._ensemble_score(key)
            entropy_bonus  = self._zone_entropy_score(key)
            total_score = base_score * 0.80 + ensemble_bonus * 0.14 + entropy_bonus * 0.06

            current = best_by_key.get(key)
            if current is None or total_score > current["score_raw"]:
                best_by_key[key] = {
                    "sorted": list(key),
                    "score_raw": total_score,
                    "segment_signature": segment_signature,
                    "markov_score": transition_score,
                    "giannella_score": giannella_score,
                    "ensemble_score": round(ensemble_bonus, 6),
                    "entropy_score":  round(entropy_bonus, 4),
                }

        ranked_candidates = sorted(best_by_key.values(), key=lambda item: item["score_raw"], reverse=True)
        final = []
        selected_numbers = []
        for candidate in ranked_candidates:
            overlap = 0
            if selected_numbers:
                overlap = max(len(set(candidate["sorted"]) & set(ex)) for ex in selected_numbers)
            if overlap >= 5 and len(ranked_candidates) > sets:
                continue
            final.append({
                "sorted":         candidate["sorted"],
                "ordered":        None,
                "score":          round(candidate["score_raw"], 4),
                "ensemble_score": candidate.get("ensemble_score", 0.0),
                "entropy_score":  candidate.get("entropy_score", 0.0),
            })
            selected_numbers.append(candidate["sorted"])
            if len(final) >= sets:
                break

        # 다양성 부족 시 보충
        if len(final) < sets:
            for candidate in ranked_candidates:
                if any(candidate["sorted"] == ex["sorted"] for ex in final):
                    continue
                final.append({
                    "sorted":         candidate["sorted"],
                    "ordered":        None,
                    "score":          round(candidate["score_raw"], 4),
                    "ensemble_score": candidate.get("ensemble_score", 0.0),
                    "entropy_score":  candidate.get("entropy_score", 0.0),
                })
                if len(final) >= sets:
                    break

        return final

    def score_manual_combination(self, numbers):
        input_numbers = [int(n) for n in numbers]
        sorted_numbers = sorted(input_numbers)
        # 성능 최적화: 6! = 720개 전체 순열 대신 전체 순열을 평가
        # (6개 번호는 720개로 관리 가능한 수준이므로 전체 계산 유지)
        permutation_scores = []
        for perm in permutations(sorted_numbers):
            ordered = list(perm)
            score = sum(
                math.log(max(self._number_weight(n, idx, ordered[:idx], False), 1e-12))
                for idx, n in enumerate(ordered)
            )
            permutation_scores.append((score, ordered))

        best_score, best_order = max(permutation_scores, key=lambda item: item[0])
        average_score = sum(score for score, _ in permutation_scores) / len(permutation_scores)
        input_order_score = sum(
            math.log(max(self._number_weight(n, idx, input_numbers[:idx], False), 1e-12))
            for idx, n in enumerate(input_numbers)
        )
        probability_score = sum(math.log(max(self._probability_only_weight(n), 1e-12)) for n in sorted_numbers)

        # ──────────────────────────────────────────────────────────────────
        # [Kelly Criterion] 자금 배분 권장 비율 산출
        #
        # 수학적 정의: f* = (b·p - q) / b  = (b·p - (1-p)) / b
        #   · b  : 순배당률 (로또 1등 기준: 세후 기대 배당 ≈ 0.45, 즉 1원 투자 시 0.45원 기대수익)
        #   · p  : 이 번호 조합의 "상대적 당첨 가능성" — probability_score를 0~1 사이로 정규화한 값
        #   · q  = 1 - p
        #
        # probability_score는 로그 공간의 음수값이므로 sigmoid 변환으로 0~1 정규화:
        #   p_norm = 1 / (1 + exp(-probability_score / scale))
        #   scale은 전체 45개 번호의 probability_score 평균 절댓값으로 동적 결정.
        #
        # 해석:
        #   · kelly_fraction > 0  : 통계적으로 평균 이상의 조합 → 베팅 비중 확대 가능
        #   · kelly_fraction ≈ 0  : 중립 구간
        #   · kelly_fraction < 0  : 평균 이하 조합 → 베팅 최소화 권장
        #   · kelly_recommendation: "strong" / "moderate" / "neutral" / "reduce" / "avoid"
        #
        # 주의: 로또는 기댓값이 구입금액보다 낮은 게임(b < 1)이므로
        #   대부분의 경우 kelly_fraction은 음수 또는 매우 작은 양수입니다.
        #   이 값은 "절대 베팅량"이 아닌 "상대적 우열 비교"에 사용하세요.
        # ──────────────────────────────────────────────────────────────────
        kelly_result = self._kelly_criterion(probability_score, sorted_numbers)

        return {
            "input_order": input_numbers,
            "sorted": sorted_numbers,
            "best_order": best_order,
            "best_score": round(best_score, 4),
            "average_score": round(average_score, 4),
            "input_order_score": round(input_order_score, 4),
            "probability_score": round(probability_score, 4),
            # Kelly Criterion 결과
            "kelly_fraction":       kelly_result["kelly_fraction"],
            "kelly_p_normalized":   kelly_result["p_normalized"],
            "kelly_recommendation": kelly_result["recommendation"],
        }

    # ──────────────────────────────────────────────────────────────────────
    # [Kelly Criterion] 내부 계산 메서드
    # ──────────────────────────────────────────────────────────────────────
    def _kelly_criterion(self, probability_score: float, numbers: list) -> dict:
        """Kelly Criterion 기반 자금 배분 권장 비율 산출.

        Args:
            probability_score: score_manual_combination 에서 계산된 로그 확률 합계
            numbers:           평가 대상 번호 리스트 (6개, 정렬됨)

        Returns:
            dict:
                kelly_fraction      - 켈리 권장 비율 (-1.0 ~ 1.0, 반올림 4자리)
                p_normalized        - 정규화된 당첨 확률 추정값 (0.0 ~ 1.0)
                recommendation      - 문자열 등급
        """
        # ① 기준선: 전체 45개 번호 중 임의 6개 조합의 평균 probability_score
        #    = 6 × 평균 log(probability_only_weight)
        all_log_weights = [
            math.log(max(self._probability_only_weight(n), 1e-12))
            for n in self.universe
        ]
        baseline_score = 6.0 * (sum(all_log_weights) / len(all_log_weights))

        # ② probability_score를 기준선 대비 상대 점수로 변환 후 sigmoid 정규화
        #    scale: 전체 번호 로그가중치 표준편차 × 6 (6개 합산 스케일)
        mean_lw = sum(all_log_weights) / len(all_log_weights)
        variance_lw = sum((lw - mean_lw) ** 2 for lw in all_log_weights) / len(all_log_weights)
        std_lw = max(variance_lw ** 0.5, 1e-6)
        scale = std_lw * 6.0  # 6개 번호 합산 스케일

        relative = probability_score - baseline_score  # 기준 대비 초과량
        # sigmoid: 0.5가 기준선, 범위 0~1
        p_normalized = 1.0 / (1.0 + math.exp(-relative / max(scale, 1e-6)))

        # ③ Kelly 공식: f* = (b·p - (1-p)) / b
        #    로또 순배당률 b: 실효 기댓값 기반 설정
        #    한국 로또 1등 기대수익률 ≈ 45% (세후, 장기 평균) → b = 0.45
        b = 0.45
        p = p_normalized
        q = 1.0 - p
        kelly_fraction = (b * p - q) / b  # = p - q/b

        # ④ 권장 등급 분류
        if kelly_fraction >= 0.10:
            recommendation = "strong"      # 평균 대비 통계적으로 우수한 조합
        elif kelly_fraction >= 0.02:
            recommendation = "moderate"    # 소폭 우위
        elif kelly_fraction >= -0.05:
            recommendation = "neutral"     # 중립 (평균 수준)
        elif kelly_fraction >= -0.15:
            recommendation = "reduce"      # 평균 이하, 최소 베팅 권장
        else:
            recommendation = "avoid"       # 통계적으로 낮은 조합

        return {
            "kelly_fraction":  round(kelly_fraction, 4),
            "p_normalized":    round(p_normalized, 4),
            "recommendation":  recommendation,
        }


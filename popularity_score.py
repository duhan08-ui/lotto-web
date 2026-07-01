#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""popularity_score.py - 인기조합 회피 점수 ("나혼자" 모드용)

목적
----
로또 배당은 같은 등수 당첨자끼리 나눠 갖는 구조(pari-mutuel)라, 사람들이
많이 고르는 조합으로 당첨되면 1인당 금액이 줄어든다. 이 모듈은 한 조합이
'얼마나 사람들이 안 고를 법한가'를 0~100점(비인기 점수)으로 매긴다.
점수가 높을수록 = 남들과 덜 겹침 = 당첨 시 배당 분할에 유리.

⚠️ 중요: 이 점수는 '맞힐 확률'을 전혀 바꾸지 않는다. 오로지 '맞았을 때의 몫'
(기대 배당)에만 영향을 준다. 또한 실제 한국 로또 구매자 선택 분포 데이터가
아니라 일반적으로 알려진 휴리스틱(생일 편중, 인기수, 시각적 패턴 등)에
기반하므로 절대적 수치가 아니라 '상대 비교용 지표'로 쓰는 것이 맞다.

기존 anti_pattern_lotto.py 의 회피 철학(high_zone_start=32, 인기수/예쁜수
집합, 합계 선호 구간, 연속/십의자리 군집 제한)과 일관되게 설계했다.
"""

from __future__ import annotations

from typing import Any, Iterable

# anti_pattern_lotto.py 와 동일한 상수 (일관성 유지)
POPULAR_NUMBERS = {3, 7, 8, 9, 11, 13, 21, 22, 27}        # 사람들이 자주 찍는 수
PRETTY_NUMBERS = {1, 2, 3, 5, 7, 10, 11, 22, 33, 44}      # 시각적으로 '예쁜' 수
LUCKY_NUMBERS = {3, 7, 8, 9, 11, 13, 17, 21, 23, 27}      # 행운수
ROUND_NUMBERS = {10, 20, 30, 40}                          # 0으로 끝나는 수
HIGH_ZONE_START = 32                                      # 32~45 = 고번호대(덜 선호됨)

# 각 패널티 항목의 최대 감점(합 100). 비인기 점수 = 100 - 패널티합(0~100 클램프).
_PENALTY_WEIGHTS = {
    "birthday": 26.0,     # 1~31 편중 (생일/날짜)
    "month": 10.0,        # 1~12 편중 (월/일)
    "popular": 16.0,      # 인기수/행운수
    "pretty_round": 10.0,  # 예쁜수/라운드수
    "low_sum": 14.0,      # 합계가 사람 선호 저합대(생일 조합 → 낮음)
    "high_deficit": 12.0,  # 고번호대(32~45) 부족
    "consecutive": 6.0,   # 연속수(시각적 패턴)
    "decade_cluster": 6.0,  # 십의자리 군집(소수 구간에 몰림)
}


def _norm(value: float) -> float:
    """0~1 클램프."""
    return max(0.0, min(1.0, value))


def score_breakdown(numbers: Iterable[int]) -> dict[str, Any]:
    """한 조합의 인기/비인기 분석 상세.

    Returns dict with:
      - unpopularity_score: 0~100 (높을수록 비인기 = 배당 유리)
      - penalties: 항목별 감점
      - features: 진단용 원시 지표
    """
    nums = sorted(int(n) for n in numbers)
    if len(nums) != 6 or len(set(nums)) != 6 or not all(1 <= n <= 45 for n in nums):
        raise ValueError("numbers must be 6 unique integers in 1..45")

    total = sum(nums)
    low_31 = sum(1 for n in nums if n <= 31)         # 생일 가능 범위
    month_12 = sum(1 for n in nums if n <= 12)       # 월/일 범위
    high_cnt = sum(1 for n in nums if n >= HIGH_ZONE_START)
    popular_cnt = sum(1 for n in nums if n in (POPULAR_NUMBERS | LUCKY_NUMBERS))
    pretty_round_cnt = sum(1 for n in nums if n in (PRETTY_NUMBERS | ROUND_NUMBERS))
    consecutive_pairs = sum(1 for i in range(5) if nums[i + 1] - nums[i] == 1)
    decade_buckets = len({(n - 1) // 10 for n in nums})  # 1~10,11~20,...

    pen: dict[str, float] = {}

    # 1) 생일 편중: 무작위 기대 ~4.1개. 5개 이상부터 점증.
    pen["birthday"] = _PENALTY_WEIGHTS["birthday"] * _norm((low_31 - 4) / 2.0)

    # 2) 월/일 편중: 무작위 기대 ~1.6개. 3개 이상부터 점증.
    pen["month"] = _PENALTY_WEIGHTS["month"] * _norm((month_12 - 2) / 3.0)

    # 3) 인기수/행운수: 1개까지는 흔함, 2개부터 점증.
    pen["popular"] = _PENALTY_WEIGHTS["popular"] * _norm((popular_cnt - 1) / 3.0)

    # 4) 예쁜수/라운드수
    pen["pretty_round"] = _PENALTY_WEIGHTS["pretty_round"] * _norm((pretty_round_cnt - 1) / 3.0)

    # 5) 저합대 패널티: 합계가 낮을수록(생일 조합 특징) 감점.
    #    선호 비인기 구간은 대략 150~224 (anti_pattern 기본 164~224 참고).
    if total >= 150:
        pen["low_sum"] = 0.0
    else:
        pen["low_sum"] = _PENALTY_WEIGHTS["low_sum"] * _norm((150 - total) / 50.0)

    # 6) 고번호대 부족: 32~45 가 2개 미만이면 감점(사람들은 큰 수를 덜 고름).
    pen["high_deficit"] = _PENALTY_WEIGHTS["high_deficit"] * _norm((2 - high_cnt) / 2.0)

    # 7) 연속수: 2쌍 초과부터 감점.
    pen["consecutive"] = _PENALTY_WEIGHTS["consecutive"] * _norm((consecutive_pairs - 1) / 3.0)

    # 8) 십의자리 군집: 사용한 십의자리 구간이 3개 이하면 감점(한쪽에 몰림).
    pen["decade_cluster"] = _PENALTY_WEIGHTS["decade_cluster"] * _norm((4 - decade_buckets) / 3.0)

    penalty_total = sum(pen.values())
    unpop = round(max(0.0, min(100.0, 100.0 - penalty_total)), 1)

    return {
        "unpopularity_score": unpop,
        "penalties": {k: round(v, 2) for k, v in pen.items()},
        "features": {
            "sum": total,
            "low_1_31": low_31,
            "month_1_12": month_12,
            "high_32_45": high_cnt,
            "popular_lucky": popular_cnt,
            "pretty_round": pretty_round_cnt,
            "consecutive_pairs": consecutive_pairs,
            "decade_buckets": decade_buckets,
        },
    }


def unpopularity_score(numbers: Iterable[int]) -> float:
    """편의 함수: 비인기 점수(0~100)만 반환."""
    return score_breakdown(numbers)["unpopularity_score"]


def attach_popularity_scores(results: list[dict], numbers_key: str = "numbers") -> list[dict]:
    """'나혼자' 결과 리스트의 각 항목에 비인기 점수 컬럼을 붙인다.

    각 result dict 에서 numbers_key(기본 'numbers')로 6개 번호를 읽어
    'unpopularity_score' 와 'popularity_breakdown' 키를 추가한다.
    번호가 없거나 형식이 어긋나면 해당 항목은 건너뛴다(원본 보존).
    """
    for r in results:
        nums = r.get(numbers_key) or r.get("sorted")
        if not nums:
            continue
        try:
            bd = score_breakdown(nums)
        except Exception:
            continue
        r["unpopularity_score"] = bd["unpopularity_score"]
        r["popularity_breakdown"] = bd["penalties"]
    return results


if __name__ == "__main__":
    # 데모: 전형적 '인기' 조합 vs '비인기' 조합 비교
    samples = {
        "생일조합(1~12 위주)": [3, 7, 8, 11, 12, 17],
        "예쁜패턴(1-2-3-5-7-10)": [1, 2, 3, 5, 7, 10],
        "연속수(1-2-3-4-5-6)": [1, 2, 3, 4, 5, 6],
        "고르게 분산+고번호": [4, 17, 26, 33, 39, 44],
        "비인기 지향": [13, 24, 35, 38, 41, 45],
    }
    for label, combo in samples.items():
        bd = score_breakdown(combo)
        print(f"{label:24s} {combo} → 비인기점수 {bd['unpopularity_score']:5.1f}")
        print("   패널티:", {k: v for k, v in bd["penalties"].items() if v > 0})

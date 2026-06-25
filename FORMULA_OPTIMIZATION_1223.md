# 예측 공식 문서 (실제 코드 동기화본)

> **🔴 통계적 사전 고지 (반드시 읽어주세요)**
>
> 한국 로또(6/45)는 매 회차가 **완전히 독립적이고 균등한 무작위 추첨**입니다.
> 어떤 6개 조합이든 1등 당첨 확률은 정확히 **1 / 8,145,060** 으로 동일하며,
> 과거 출현 빈도·마르코프 전이·베이즈 추정 등 **어떤 방법도 다음 회차의 당첨
> 확률을 바꾸지 못합니다.** 아래 공식들은 "통계적으로 균형 잡힌 조합"을 만들기
> 위한 **점수화 로직**일 뿐, 당첨을 보장하거나 확률을 높이지 않습니다.
>
> 통계적으로 유효한 유일한 개입은 **공동당첨(분배금) 위험 회피**입니다
> (`_jackpot_sharing_estimate` 참고). 당첨 확률이 아니라 "당첨 시 1인당 수령액"에만
> 영향을 줍니다.

본 문서는 `lotto_core.py`의 **실제 구현**을 그대로 반영합니다. (이전 버전의
`prior_strength=0.15`, `(count+2)/(sum+90)`, `volatility_penalty` 등의 수식은
코드에 존재하지 않아 삭제했습니다.)

---

## 1. Gap 베이즈 확률 (`_build_gap_probability`)

번호가 마지막 출현 후 경과한 회차(gap)별 재출현 확률을 베이즈 수축(shrinkage)으로 추정합니다.

```
base_rate = 6 / 45 ≈ 0.1333          # 한 회차에서 임의 번호가 뽑힐 기준확률
prior_strength = 32.0

P(gap) = (success_gap + base_rate · prior_strength) / (total_gap + prior_strength)
```

- `success_gap` : 해당 gap 상태에서 실제로 번호가 다시 나온 횟수
- `total_gap`   : 해당 gap 상태가 관측된 총 횟수
- 데이터가 적은 gap은 기준확률(base_rate)로 강하게 수축되어 과적합을 방지합니다.

## 2. Gap Factor 룩업 (`_build_gap_factor_lookup`)

각 번호의 현재 gap 확률을 기준확률 대비 배율로 환산하고 범위를 제한합니다.

```
gap_factor(n) = clip( P(gap_n) / base_rate , 0.78 , 1.35 )
```

## 3. 마르코프 전이행렬 (`_build_markov_transition_matrix`)

직전 회차 번호 → 다음 회차 번호의 전이 경향을 학습합니다.

```
# (a) 사전(prior) 채움
prior(prev→next) = (0.24 + overall_prior[next] · 24.0) · zone_bonus
   · overall_prior[next] = (총출현수[next] + 1) / (전체추첨수 · 6 + 45)
   · zone_bonus = 1.08  (next가 prev와 같은 지아넬라 구간일 때) / 1.0

# (b) 실관측 전이 누적 (최근일수록 가중)
recency_ratio  = max((H - min(step, H)) / H, 0)        # H = min(추첨수-1, 72)
transition_w   = 1.0 + recency_ratio · 1.8
가산값 = transition_w · zone_bonus(1.14) · band_bonus(1.05 if |Δ|≤9 else 1.0)

# (c) 행 정규화: 각 prev 행의 합이 1이 되도록 나눔
```

## 4. 마르코프 종합 가중치 (`_build_markov_transition_weight_lookup`)

여러 신호를 가중 결합한 뒤 평균이 1.0이 되도록 정규화합니다.

```
score(n) = 0.48 · 최신회차전이(n)
         + 0.26 · 최근5회차_역수가중전이(n)
         + 0.12 · gap_probability(n)
         + 0.14 · overall_probability(n)

weight(n) = score(n) / base_rate           # 이후 전체 평균이 1.0이 되도록 재정규화
```

## 5. 페어 시너지 행렬 (`_build_pair_strength_matrix`)

두 번호가 함께 등장한 빈도를 완만하게 반영합니다.

```
raw   = (pair_count + 2.0) / (avg_pair_freq + 1.0)
factor(a,b) = clip( raw ^ 0.38 , 0.91 , 1.13 )      # 멱지수 0.38로 영향 완화
```

## 6. 수동 조합 점수 (`score_manual_combination`)

입력한 6개 번호의 모든 순열(6! = 720)에 대해 로그 가중치 합을 계산합니다.

```
order_score = Σ_i  log( max( number_weight(n_i, position_i, 선행번호들) , 1e-12 ) )

best_score     = max(order_score over 720 permutations)
average_score  = mean(order_score over 720 permutations)
input_order_score = 입력한 순서 그대로의 order_score
probability_score = Σ log(probability_only_weight(n))
```

## 7. 추천 최종 점수 (`predict` / `predict_probability_only`)

단일 `volatility_penalty` 방식이 아니라 **앙상블 블렌딩**을 사용합니다.

```
# 패턴 추천(predict)
final = advanced_pattern_score · w1 + ensemble_score · 0.30 + zone_entropy · w2 ...

# 확률 추천(predict_probability_only)
base  = seed_score · 0.18 + refined_score · 0.82
final = base · 0.80 + ensemble_bonus · 0.14 + entropy_bonus · 0.06
```

`_ensemble_score`는 cycle/cooccurrence/sum-histogram/tail/streak 등 다중 통계의
가중합(`_build_ensemble_weights`)으로 구성됩니다.

## 8. 안티패턴 설정 (`anti_pattern_lotto.py` — 실제 값)

| 항목 | 실제 값 | 의미 |
|------|--------|------|
| `preferred_high_distribution` | (고번호 3개)0.28 / (4개)0.50 / (5개)0.22 | 32~45 구간 개수 **선호 분포**(배수 패널티 아님) |
| `min_sum` / `preferred_sum` | 138 / 164~224 | 합계 하한 및 선호 구간 |
| `max_consecutive_pairs` | 2 | 연속쌍 최대 허용 |
| `min_span` | 16 | 최소~최대 번호 폭 하한 |
| `max_same_decade` | 2 | 같은 10단위 최대 개수 |
| `min_decade_buckets` | 4 | 분포되어야 할 10단위 구간 수 |
| `max_month_count` / `max_popular_count` / `max_pretty_count` | 각 1 | 생일대·인기·미관(예쁜) 번호 제한 |

이 설정들은 "사람이 선호하는 패턴"을 배제해 **공동당첨 위험을 낮추는** 데 기여합니다
(당첨 확률 상승과는 무관).

---

## 적용 시점
- 1223회차 이후 데이터부터 학습에 반영 (예측 가중치는 위 공식 기반).

## 주의사항
본 공식은 통계적 균형을 목표로 하며, **당첨 결과를 보장하지 않습니다.**
당첨 확률은 모든 조합이 동일합니다.

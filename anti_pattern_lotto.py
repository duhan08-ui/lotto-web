import csv
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class LottoConfig:
    number_min: int = 1
    number_max: int = 45
    pick_count: int = 6
    seed: Optional[int] = None
    candidate_pool_size: int = 4200
    elite_size: int = 320
    mutation_rounds: int = 4
    mutations_per_elite: int = 4
    human_number_samples: int = 18000
    human_ticket_samples: int = 28000
    final_ticket_count: int = 5
    max_similarity: float = 0.50
    high_zone_start: int = 32
    preferred_high_distribution: Tuple[Tuple[int, float], ...] = (
        (3, 0.28),
        (4, 0.50),
        (5, 0.22),
    )
    recent_draws: Tuple[Tuple[int, ...], ...] = ()
    export_csv_path: Optional[str] = None
    min_sum: int = 138
    preferred_sum_min: int = 164
    preferred_sum_max: int = 224
    max_month_count: int = 1
    max_popular_count: int = 1
    max_pretty_count: int = 1
    max_recent_overlap: int = 1
    max_same_decade: int = 2
    min_decade_buckets: int = 4
    max_tail_repeat_penalty: int = 1
    min_span: int = 16
    max_consecutive_pairs: int = 2


@dataclass(order=True)
class TicketScore:
    sort_index: Tuple[int, float, float] = field(init=False, repr=False)
    collisions: int
    crowd_proxy: float
    anti_score: float
    numbers: Tuple[int, ...]
    diagnostics: Dict[str, float] = field(default_factory=dict, compare=False)

    def __post_init__(self):
        self.sort_index = (self.collisions, self.crowd_proxy, -self.anti_score)


class HumanLikePicker:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.total_pool = list(range(1, 46))
        self.low_pool = list(range(1, 32))
        self.month_pool = list(range(1, 13))
        self.high_pool = list(range(32, 46))
        self.lucky_numbers = [3, 7, 8, 9, 11, 13, 17, 21, 23, 27]
        self.pretty_numbers = [1, 2, 3, 5, 7, 10, 11, 22, 33, 44]
        self.round_numbers = [10, 20, 30, 40]
        self.edgeish = [1, 7, 8, 14, 15, 21, 22, 28, 29, 35, 36, 42, 43, 44, 45]

    def generate(self) -> Tuple[int, ...]:
        mode = self.rng.choices(
            population=["birthday", "lucky", "balanced", "pattern", "quickpick"],
            weights=[0.35, 0.22, 0.22, 0.11, 0.10],
            k=1,
        )[0]

        if mode == "birthday":
            nums = self._birthday_mode()
        elif mode == "lucky":
            nums = self._lucky_mode()
        elif mode == "balanced":
            nums = self._balanced_human_mode()
        elif mode == "pattern":
            nums = self._pattern_mode()
        else:
            nums = self._quickpick_mode()

        return tuple(sorted(nums))

    def _birthday_mode(self) -> List[int]:
        picks = set()
        while len(picks) < 5:
            source = self.month_pool if self.rng.random() < 0.28 else self.low_pool
            picks.add(self.rng.choice(source))

        if self.rng.random() < 0.18:
            picks.add(self.rng.choice(self.high_pool))
        while len(picks) < 6:
            picks.add(self.rng.choice(self.low_pool))
        return list(picks)

    def _lucky_mode(self) -> List[int]:
        picks = set()
        while len(picks) < 2:
            picks.add(self.rng.choice(self.lucky_numbers))

        weighted_pool = (
            self.low_pool * 4
            + self.lucky_numbers * 6
            + self.pretty_numbers * 4
            + self.round_numbers * 3
            + self.high_pool
        )
        while len(picks) < 6:
            picks.add(self.rng.choice(weighted_pool))
        return list(picks)

    def _balanced_human_mode(self) -> List[int]:
        for _ in range(1200):
            nums = sorted(self.rng.sample(self.total_pool, 6))
            s = sum(nums)
            odd_count = sum(n % 2 for n in nums)
            high_count = sum(n >= 32 for n in nums)
            consecutive_pairs = sum(1 for i in range(5) if nums[i + 1] == nums[i] + 1)
            if 100 <= s <= 165 and 2 <= odd_count <= 4 and high_count <= 2 and consecutive_pairs <= 1:
                return nums
        return sorted(self.rng.sample(self.total_pool, 6))

    def _pattern_mode(self) -> List[int]:
        candidates = []
        candidates.extend(self.pretty_numbers)
        candidates.extend(self.lucky_numbers)
        candidates.extend(self.low_pool)
        candidates.extend(self.edgeish)
        picks = set()
        while len(picks) < 6:
            picks.add(self.rng.choice(candidates))
        return list(picks)

    def _quickpick_mode(self) -> List[int]:
        return self.rng.sample(self.total_pool, 6)


class AntiPatternLottoV2:
    def __init__(self, config: LottoConfig):
        self.cfg = config
        self.rng = random.Random(config.seed)
        self.total_pool = list(range(config.number_min, config.number_max + 1))
        self.high_zone = list(range(config.high_zone_start, config.number_max + 1))
        self.low_zone = list(range(config.number_min, config.high_zone_start))
        self.primes = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43}
        self.popular_numbers = {3, 7, 8, 9, 11, 13, 21, 22, 27}
        self.pretty_numbers = {1, 2, 3, 5, 7, 10, 11, 22, 33, 44}
        self.month_zone = set(range(1, 13))
        self.edgeish = {1, 7, 8, 14, 15, 21, 22, 28, 29, 35, 36, 42, 43, 44, 45}
        self.human_picker = HumanLikePicker(self.rng)
        self.number_popularity: Dict[int, float] = {}
        self.number_anti_weights: Dict[int, float] = {}
        self.recent_number_counts = self._build_recent_number_counts()
        self.preferred_high_weight_map = dict(self.cfg.preferred_high_distribution)
        self.allowed_high_counts = set(self.preferred_high_weight_map)

    def _build_recent_number_counts(self) -> Dict[int, int]:
        counts = Counter()
        for draw in self.cfg.recent_draws:
            for number in draw:
                counts[number] += 1
        return dict(counts)

    def sample_high_count(self) -> int:
        choices, weights = zip(*self.cfg.preferred_high_distribution)
        return self.rng.choices(list(choices), weights=list(weights), k=1)[0]

    def jaccard_similarity(self, a: Tuple[int, ...], b: Tuple[int, ...]) -> float:
        sa, sb = set(a), set(b)
        return len(sa & sb) / len(sa | sb)

    def has_three_consecutive(self, numbers: Tuple[int, ...]) -> bool:
        for i in range(len(numbers) - 2):
            if numbers[i + 1] == numbers[i] + 1 and numbers[i + 2] == numbers[i] + 2:
                return True
        return False

    def has_arithmetic_progression(self, numbers: Tuple[int, ...]) -> bool:
        diffs = [numbers[i + 1] - numbers[i] for i in range(len(numbers) - 1)]
        return len(set(diffs)) == 1

    def count_consecutive_pairs(self, numbers: Tuple[int, ...]) -> int:
        return sum(1 for i in range(len(numbers) - 1) if numbers[i + 1] == numbers[i] + 1)

    def repeated_last_digit_penalty(self, numbers: Tuple[int, ...]) -> int:
        last_digits = [n % 10 for n in numbers]
        return sum(c - 1 for c in Counter(last_digits).values() if c >= 2)

    def recent_overlap_count(self, numbers: Tuple[int, ...]) -> int:
        if not self.cfg.recent_draws:
            return 0
        s = set(numbers)
        return max(len(s & set(draw)) for draw in self.cfg.recent_draws)

    def decade_bucket_count(self, numbers: Tuple[int, ...]) -> int:
        return len({(n - 1) // 10 for n in numbers})

    def max_same_decade_count(self, numbers: Tuple[int, ...]) -> int:
        decade_counts = Counter((n - 1) // 10 for n in numbers)
        return max(decade_counts.values()) if decade_counts else 0

    def number_span(self, numbers: Tuple[int, ...]) -> int:
        return numbers[-1] - numbers[0]

    def estimate_number_popularity(self) -> Dict[int, float]:
        counts = Counter()
        total = 0
        for _ in range(self.cfg.human_number_samples):
            ticket = self.human_picker.generate()
            counts.update(ticket)
            total += len(ticket)
        self.number_popularity = {n: counts[n] / total for n in self.total_pool}
        self.number_anti_weights = self._build_anti_number_weights()
        return self.number_popularity

    def _build_anti_number_weights(self) -> Dict[int, float]:
        if not self.number_popularity:
            return {n: 1.0 for n in self.total_pool}

        popularity_values = list(self.number_popularity.values())
        min_popularity = min(popularity_values)
        max_popularity = max(popularity_values)
        popularity_spread = max(max_popularity - min_popularity, 1e-9)

        max_recent = max(self.recent_number_counts.values(), default=0)
        recent_spread = max(max_recent, 1)
        weights: Dict[int, float] = {}

        for number in self.total_pool:
            popularity = self.number_popularity.get(number, min_popularity)
            rarity_score = (max_popularity - popularity) / popularity_spread
            recent_count = self.recent_number_counts.get(number, 0)
            recent_coldness = 1.0 - (recent_count / recent_spread if max_recent else 0.0)

            weight = 1.0
            weight += rarity_score * 2.8
            weight += recent_coldness * 0.8
            if number >= self.cfg.high_zone_start:
                weight += 1.9
            if number in self.primes:
                weight += 0.5
            if number in self.month_zone:
                weight -= 2.2
            if number in self.popular_numbers:
                weight -= 1.8
            if number in self.pretty_numbers:
                weight -= 1.0
            if number in self.edgeish:
                weight -= 0.25
            weights[number] = max(0.05, weight)
        return weights

    def _select_number(self, available_numbers: List[int], selected_numbers: List[int], target_high_count: int) -> int:
        current_high_count = sum(n >= self.cfg.high_zone_start for n in selected_numbers)
        slots_left = self.cfg.pick_count - len(selected_numbers)
        selected_last_digits = {n % 10 for n in selected_numbers}
        selected_decades = Counter((n - 1) // 10 for n in selected_numbers)

        weights: List[float] = []
        for number in available_numbers:
            weight = self.number_anti_weights.get(number, 1.0)
            is_high = number >= self.cfg.high_zone_start
            needed_highs = max(target_high_count - current_high_count, 0)

            if is_high and current_high_count >= target_high_count:
                weight *= 0.20
            elif (not is_high) and needed_highs >= slots_left:
                weight *= 0.10
            elif is_high and needed_highs > 0:
                weight *= 1.45

            if number % 10 in selected_last_digits:
                weight *= 0.68

            decade_key = (number - 1) // 10
            decade_count = selected_decades.get(decade_key, 0)
            if decade_count >= self.cfg.max_same_decade:
                weight *= 0.22
            elif decade_count == 1:
                weight *= 0.72

            if selected_numbers:
                min_gap = min(abs(number - existing) for existing in selected_numbers)
                if min_gap == 1:
                    weight *= 1.10
                elif min_gap <= 2:
                    weight *= 0.94
                elif min_gap >= 10:
                    weight *= 1.08

            weights.append(max(weight, 0.01))

        return self.rng.choices(available_numbers, weights=weights, k=1)[0]

    def generate_candidate(self) -> Tuple[int, ...]:
        if not self.number_anti_weights:
            self.number_anti_weights = self._build_anti_number_weights()

        for _ in range(6000):
            target_high_count = self.sample_high_count()
            selected: List[int] = []
            available = self.total_pool[:]

            while len(selected) < self.cfg.pick_count:
                chosen = self._select_number(available, selected, target_high_count)
                selected.append(chosen)
                available.remove(chosen)

            numbers = tuple(sorted(selected))
            if self.is_valid(numbers):
                return numbers

        fallback = tuple(sorted(self.rng.sample(self.total_pool, self.cfg.pick_count)))
        if self.is_valid(fallback):
            return fallback

        # In extremely unlucky cases, relax only the generation strategy, not the external API.
        for _ in range(12000):
            target_high_count = self.sample_high_count()
            highs = self.rng.sample(self.high_zone, min(target_high_count, len(self.high_zone)))
            lows = self.rng.sample(self.low_zone, self.cfg.pick_count - len(highs))
            numbers = tuple(sorted(highs + lows))
            if self.is_valid(numbers):
                return numbers
        return fallback

    def mutate_candidate(self, ticket: Tuple[int, ...]) -> Tuple[int, ...]:
        numbers = set(ticket)
        replace_count = 1 if self.rng.random() < 0.74 else 2

        for _ in range(replace_count):
            removable = list(numbers)
            remove_number = self.rng.choice(removable)
            numbers.remove(remove_number)
            partial = sorted(numbers)
            available = [n for n in self.total_pool if n not in numbers]
            target_high_count = self.sample_high_count()
            replacement = self._select_number(available, partial, target_high_count)
            numbers.add(replacement)

        mutated = tuple(sorted(numbers))
        return mutated if self.is_valid(mutated) else ticket

    def is_valid(self, numbers: Tuple[int, ...]) -> bool:
        if len(numbers) != self.cfg.pick_count:
            return False
        if len(set(numbers)) != self.cfg.pick_count:
            return False

        high_count = sum(n >= self.cfg.high_zone_start for n in numbers)
        if self.allowed_high_counts and high_count not in self.allowed_high_counts:
            return False

        if self.has_three_consecutive(numbers):
            return False
        if self.has_arithmetic_progression(numbers):
            return False

        if sum(n in self.primes for n in numbers) < 1:
            return False
        if sum(numbers) < self.cfg.min_sum:
            return False
        if self.number_span(numbers) < self.cfg.min_span:
            return False
        if sum(n in self.month_zone for n in numbers) > self.cfg.max_month_count:
            return False
        if sum(n in self.popular_numbers for n in numbers) > self.cfg.max_popular_count:
            return False
        if sum(n in self.pretty_numbers for n in numbers) > self.cfg.max_pretty_count:
            return False
        if self.recent_overlap_count(numbers) > self.cfg.max_recent_overlap:
            return False
        if self.repeated_last_digit_penalty(numbers) > self.cfg.max_tail_repeat_penalty:
            return False
        if self.decade_bucket_count(numbers) < self.cfg.min_decade_buckets:
            return False
        if self.max_same_decade_count(numbers) > self.cfg.max_same_decade:
            return False
        if self.count_consecutive_pairs(numbers) > self.cfg.max_consecutive_pairs:
            return False
        return True

    def build_candidate_pool(self) -> List[Tuple[int, ...]]:
        seen = set()
        candidates: List[Tuple[int, ...]] = []
        while len(candidates) < self.cfg.candidate_pool_size:
            ticket = self.generate_candidate()
            if ticket not in seen:
                seen.add(ticket)
                candidates.append(ticket)
        return candidates

    def crowd_proxy_score(self, numbers: Tuple[int, ...]) -> float:
        score = 0.0
        low_count = sum(n <= 31 for n in numbers)
        month_count = sum(n in self.month_zone for n in numbers)
        popular_count = sum(n in self.popular_numbers for n in numbers)
        pretty_count = sum(n in self.pretty_numbers for n in numbers)
        high_count = sum(n >= self.cfg.high_zone_start for n in numbers)
        consecutive_pairs = self.count_consecutive_pairs(numbers)
        repeated_last_digit = self.repeated_last_digit_penalty(numbers)
        decade_bucket_count = self.decade_bucket_count(numbers)
        same_decade_count = self.max_same_decade_count(numbers)
        total_sum = sum(numbers)

        for number in numbers:
            score += self.number_popularity.get(number, 0.0) * 1000.0

        score += low_count * 2.0
        score += month_count * 2.4
        score += popular_count * 3.0
        score += pretty_count * 1.8
        score += repeated_last_digit * 1.0
        score += max(0, 4 - decade_bucket_count) * 1.4
        score += max(0, same_decade_count - 2) * 2.4

        if 110 <= total_sum <= 165:
            score += 4.5
        if high_count <= 2:
            score += 2.8
        if consecutive_pairs == 0:
            score += 0.9
        elif consecutive_pairs >= 2:
            score -= 0.6

        if self.cfg.recent_draws:
            overlap = self.recent_overlap_count(numbers)
            score += overlap * 1.9
            score += sum(self.recent_number_counts.get(n, 0) for n in numbers) * 0.28

        return round(score, 6)

    def anti_human_score(self, numbers: Tuple[int, ...]) -> Tuple[float, Dict[str, float]]:
        score = 0.0
        diagnostics: Dict[str, float] = {}

        high_count = sum(n >= self.cfg.high_zone_start for n in numbers)
        low_count = sum(n <= 31 for n in numbers)
        month_count = sum(n in self.month_zone for n in numbers)
        popular_count = sum(n in self.popular_numbers for n in numbers)
        pretty_count = sum(n in self.pretty_numbers for n in numbers)
        prime_count = sum(n in self.primes for n in numbers)
        edge_count = sum(n in self.edgeish for n in numbers)
        total_sum = sum(numbers)
        consecutive_pairs = self.count_consecutive_pairs(numbers)
        repeated_last_digit = self.repeated_last_digit_penalty(numbers)
        odd_count = sum(n % 2 for n in numbers)
        recent_overlap = self.recent_overlap_count(numbers)
        decade_bucket_count = self.decade_bucket_count(numbers)
        same_decade_count = self.max_same_decade_count(numbers)
        span = self.number_span(numbers)

        rarity_bonus = 0.0
        recent_cold_bonus = 0.0
        for number in numbers:
            popularity = self.number_popularity.get(number, 0.0)
            rarity_bonus += max(0.0, 0.07 - popularity) * 120.0
            recent_cold_bonus += max(0.0, 2.0 - float(self.recent_number_counts.get(number, 0)))

        preferred_high_bonus = self.preferred_high_weight_map.get(high_count, -0.7) * 10.0
        score += preferred_high_bonus
        score += rarity_bonus
        score += recent_cold_bonus * 0.55
        score -= low_count * 2.1
        score -= month_count * 3.0
        score -= popular_count * 4.0
        score -= pretty_count * 1.9
        score += prime_count * 0.9
        score -= edge_count * 0.15
        score += decade_bucket_count * 1.35
        score -= max(0, same_decade_count - 2) * 2.6
        score += min(span, 30) * 0.16

        if self.cfg.preferred_sum_min <= total_sum <= self.cfg.preferred_sum_max:
            score += 5.2
        elif total_sum < 155:
            score -= 4.6
        elif total_sum >= 225:
            score += 1.5

        if consecutive_pairs == 1:
            score += 1.1
        elif consecutive_pairs == 2:
            score += 0.5
        elif consecutive_pairs >= 3:
            score -= 3.0

        score -= repeated_last_digit * 1.5

        if odd_count in (3, 4):
            score -= 1.2
        elif odd_count in (0, 6):
            score += 0.6

        if self.cfg.recent_draws:
            score -= recent_overlap * 2.4
            score -= sum(self.recent_number_counts.get(n, 0) for n in numbers) * 0.32

        diagnostics["high_count"] = high_count
        diagnostics["preferred_high_bonus"] = preferred_high_bonus
        diagnostics["low_count"] = low_count
        diagnostics["month_count"] = month_count
        diagnostics["popular_count"] = popular_count
        diagnostics["pretty_count"] = pretty_count
        diagnostics["prime_count"] = prime_count
        diagnostics["edge_count"] = edge_count
        diagnostics["sum"] = total_sum
        diagnostics["span"] = span
        diagnostics["decade_bucket_count"] = decade_bucket_count
        diagnostics["same_decade_count"] = same_decade_count
        diagnostics["consecutive_pairs"] = consecutive_pairs
        diagnostics["repeated_last_digit"] = repeated_last_digit
        diagnostics["odd_count"] = odd_count
        diagnostics["recent_overlap"] = recent_overlap
        diagnostics["rarity_bonus"] = round(rarity_bonus, 6)
        diagnostics["recent_cold_bonus"] = round(recent_cold_bonus, 6)
        return round(score, 6), diagnostics

    def _evolution_sort_key(self, ticket: Tuple[int, ...]) -> Tuple[float, float]:
        crowd_proxy = self.crowd_proxy_score(ticket)
        anti_score, _ = self.anti_human_score(ticket)
        return (crowd_proxy, -anti_score)

    def evolve_candidates(self, base_candidates: List[Tuple[int, ...]]) -> List[Tuple[int, ...]]:
        ranked = sorted(base_candidates, key=self._evolution_sort_key)
        elite = ranked[: self.cfg.elite_size]
        seen = set(elite)
        current = elite[:]

        for _ in range(self.cfg.mutation_rounds):
            new_candidates: List[Tuple[int, ...]] = []
            for ticket in current:
                new_candidates.append(ticket)
                for _ in range(self.cfg.mutations_per_elite):
                    mutated = self.mutate_candidate(ticket)
                    if mutated not in seen:
                        seen.add(mutated)
                        new_candidates.append(mutated)
            new_candidates = sorted(new_candidates, key=self._evolution_sort_key)
            current = new_candidates[: self.cfg.elite_size]
        return current

    def simulate_human_collisions(self, candidates: List[Tuple[int, ...]]) -> Dict[Tuple[int, ...], int]:
        candidate_set = set(candidates)
        hits = Counter()
        for _ in range(self.cfg.human_ticket_samples):
            ticket = self.human_picker.generate()
            if ticket in candidate_set:
                hits[ticket] += 1
        return dict(hits)

    def rank_candidates(self, candidates: List[Tuple[int, ...]]) -> List[TicketScore]:
        collisions = self.simulate_human_collisions(candidates)
        ranked: List[TicketScore] = []
        for candidate in candidates:
            anti_score, diagnostics = self.anti_human_score(candidate)
            proxy = self.crowd_proxy_score(candidate)
            ranked.append(
                TicketScore(
                    collisions=collisions.get(candidate, 0),
                    crowd_proxy=proxy,
                    anti_score=anti_score,
                    numbers=candidate,
                    diagnostics=diagnostics,
                )
            )
        ranked.sort()
        return ranked

    def diversify_selection(self, ranked: List[TicketScore]) -> List[TicketScore]:
        selected: List[TicketScore] = []
        seen_high_counts: set[int] = set()

        for ticket in ranked:
            if len(selected) >= self.cfg.final_ticket_count:
                break
            similarity_ok = all(
                self.jaccard_similarity(ticket.numbers, chosen.numbers) <= self.cfg.max_similarity
                for chosen in selected
            )
            high_count = sum(n >= self.cfg.high_zone_start for n in ticket.numbers)
            high_count_bonus = high_count not in seen_high_counts or len(selected) < 2
            if similarity_ok and high_count_bonus:
                selected.append(ticket)
                seen_high_counts.add(high_count)

        if len(selected) < self.cfg.final_ticket_count:
            for ticket in ranked:
                if len(selected) >= self.cfg.final_ticket_count:
                    break
                if ticket not in selected:
                    selected.append(ticket)
        return selected

    def generate_portfolio(self) -> List[TicketScore]:
        self.estimate_number_popularity()
        base_candidates = self.build_candidate_pool()
        evolved = self.evolve_candidates(base_candidates)
        ranked = self.rank_candidates(evolved)
        portfolio = self.diversify_selection(ranked)
        if self.cfg.export_csv_path:
            self.export_portfolio_csv(portfolio, self.cfg.export_csv_path)
        return portfolio

    def export_portfolio_csv(self, portfolio: List[TicketScore], path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "set_no",
                    "numbers",
                    "collisions",
                    "crowd_proxy",
                    "anti_score",
                    "high_count",
                    "month_count",
                    "popular_count",
                    "pretty_count",
                    "prime_count",
                    "sum",
                    "recent_overlap",
                    "span",
                    "decade_bucket_count",
                ]
            )
            for index, ticket in enumerate(portfolio, 1):
                diagnostics = ticket.diagnostics
                writer.writerow(
                    [
                        index,
                        " ".join(map(str, ticket.numbers)),
                        ticket.collisions,
                        f"{ticket.crowd_proxy:.6f}",
                        f"{ticket.anti_score:.6f}",
                        int(diagnostics.get("high_count", 0)),
                        int(diagnostics.get("month_count", 0)),
                        int(diagnostics.get("popular_count", 0)),
                        int(diagnostics.get("pretty_count", 0)),
                        int(diagnostics.get("prime_count", 0)),
                        int(diagnostics.get("sum", 0)),
                        int(diagnostics.get("recent_overlap", 0)),
                        int(diagnostics.get("span", 0)),
                        int(diagnostics.get("decade_bucket_count", 0)),
                    ]
                )


def _single_ticket_runtime_config(seed: Optional[int] = None) -> LottoConfig:
    """Lightweight config for the solo manual-fill button.

    The original full-portfolio path evaluates thousands of candidates to return 5 sets,
    which is unnecessarily heavy when the UI only needs one immediate suggestion.
    We keep the same anti-pattern scoring pipeline, but shrink the search space so the
    button responds quickly while preserving the existing log flow and ticket rules.
    """
    return LottoConfig(
        seed=seed,
        candidate_pool_size=180,
        elite_size=48,
        mutation_rounds=2,
        mutations_per_elite=2,
        human_number_samples=6000,
        human_ticket_samples=5000,
        final_ticket_count=1,
    )



def generate_single_anti_pattern_ticket(seed: Optional[int] = None) -> Tuple[int, ...]:
    config = _single_ticket_runtime_config(seed=seed)
    engine = AntiPatternLottoV2(config)
    portfolio = engine.generate_portfolio()
    return portfolio[0].numbers

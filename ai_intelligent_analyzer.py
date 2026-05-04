import json
import math
import pandas as pd
from pathlib import Path
from collections import Counter
from datetime import datetime

class AIIntelligentAnalyzer:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.lotto_xlsx = self.project_dir / "lotto.xlsx"
        self.log_file = self.project_dir / "logs" / "prediction_log.jsonl"
        
    def calculate_ac_value(self, numbers):
        """AC값(Arithmetic Complexity) 계산: 번호 간 차이의 개수 - 5"""
        diffs = set()
        sorted_nums = sorted(numbers)
        for i in range(len(sorted_nums)):
            for j in range(i + 1, len(sorted_nums)):
                diffs.add(sorted_nums[j] - sorted_nums[i])
        return len(diffs) - (len(numbers) - 1)

    def analyze_patterns(self, numbers):
        """다양한 통계적 패턴 분석"""
        odd_count = len([n for n in numbers if n % 2 != 0])
        even_count = 6 - odd_count
        sum_val = sum(numbers)
        
        # 번호대 분포 (1-10, 11-20, 21-30, 31-40, 41-45)
        ranges = [0] * 5
        for n in numbers:
            if n <= 10: ranges[0] += 1
            elif n <= 20: ranges[1] += 1
            elif n <= 30: ranges[2] += 1
            elif n <= 40: ranges[3] += 1
            else: ranges[4] += 1
        
        return {
            "ac_value": self.calculate_ac_value(numbers),
            "odd_even": f"{odd_count}:{even_count}",
            "sum": sum_val,
            "range_dist": ranges,
            "extinction_zones": [i+1 for i, count in enumerate(ranges) if count == 0]
        }

    def get_historical_stats(self, limit=100):
        """과거 당첨 데이터로부터 통계 추출"""
        if not self.lotto_xlsx.exists():
            return None
        
        df = pd.read_excel(self.lotto_xlsx)
        latest_rounds = df.head(limit)
        
        all_nums = []
        for i in range(1, 7):
            all_nums.extend(latest_rounds[f"번호{i}"].tolist())
            
        freq = Counter(all_nums)
        return {
            "top_freq": freq.most_common(15),
            "total_count": len(all_nums)
        }

    def simulate_reinforcement_learning_score(self, numbers, stats):
        """강화학습 보상 체계를 시뮬레이션한 지능형 점수 계산"""
        base_score = 0
        patterns = self.analyze_patterns(numbers)
        
        # 1. AC값 보상 (보통 7~10 사이가 1등 당첨 조합의 특징)
        if 7 <= patterns["ac_value"] <= 10:
            base_score += 5.0
        elif patterns["ac_value"] >= 6:
            base_score += 2.0
            
        # 2. 합계 범위 보상 (100~170 사이가 약 70% 이상 차지)
        if 100 <= patterns["sum"] <= 170:
            base_score += 3.0
            
        # 3. 홀짝 비율 보상 (2:4, 3:3, 4:2 선호)
        if patterns["odd_even"] in ["2:4", "3:3", "4:2"]:
            base_score += 2.0
            
        # 4. 빈도 가중치 (과거 핫 넘버 가중치)
        if stats:
            top_nums = [n for n, f in stats["top_freq"]]
            hit_top = len(set(numbers) & set(top_nums))
            base_score += (hit_top * 1.5)
            
        # 5. 멸 구간 보상 (보통 1~2개 구간이 전멸하는 경우가 많음)
        if 1 <= len(patterns["extinction_zones"]) <= 2:
            base_score += 2.5
            
        return round(base_score, 4)

    def run_analysis(self):
        """지능형 분석 실행 및 추천 번호 도출"""
        stats = self.get_historical_stats()
        
        # 회차 정보 및 로그 유틸 로드
        from log_utils import get_round_context, persist_log_record, utc_now_iso
        ctx = get_round_context(self.lotto_xlsx)
        target_round = ctx.get("target_round") or 0
        source_round = ctx.get("source_round") or 0
        
        # 로그 데이터 로드 (최근 예측된 후보들 중 최적 선택)
        candidates = []
        if self.log_file.exists():
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if data.get("log_type") in ["prediction", "probability"]:
                            nums = data.get("numbers")
                            if nums and len(nums) == 6:
                                intel_score = self.simulate_reinforcement_learning_score(nums, stats)
                                candidates.append({
                                    "numbers": nums,
                                    "original_score": data.get("score", 0),
                                    "intelligent_score": intel_score,
                                    "patterns": self.analyze_patterns(nums)
                                })
                    except:
                        continue
        
        # 지능형 점수 기준으로 정렬
        candidates.sort(key=lambda x: x["intelligent_score"], reverse=True)
        
        # 상위 5세트 추출
        top_5 = candidates[:5]
        
        # 결과 리포트 생성
        report = []
        # 메타데이터 추가 (UI에서 파싱 가능하도록 주석 처리)
        report.append(f"<!-- metadata: round={target_round}, date={datetime.now().strftime('%Y-%m-%d')} -->")
        
        for i, cand in enumerate(top_5, 1):
            nums_str = ", ".join(f"{n:02d}" for n in sorted(cand['numbers']))
            report.append(f"{i}순위: {nums_str} (점수: {cand['intelligent_score']})")
            
            # '나혼자 당첨 로그'에 저장 (persist_log_record는 DB와 JSONL에 모두 저장함)
            log_record = {
                "timestamp": utc_now_iso(),
                "source_round": source_round,
                "target_round": target_round,
                "candidate_rank": i,
                "numbers": sorted(cand['numbers']),
                "score": cand['intelligent_score'],
                "log_type": "prediction",
                "is_intelligent": True
            }
            persist_log_record(self.project_dir / "logs", "prediction", log_record)
        
        final_report = "\n".join(report)
        
        # 파일 저장
        output_path = self.project_dir / "reports" / "intelligent_analysis_report.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_report)
            
        return final_report

if __name__ == "__main__":
    analyzer = AIIntelligentAnalyzer("/home/ubuntu/lotto_project")
    print(analyzer.run_analysis())

import streamlit as st
from pathlib import Path

def render_ai_recommendation_section(project_dir: Path):
    """홈 화면에 AI 주간 추천 번호 섹션을 렌더링합니다."""
    # 지능형 분석 보고서 우선 확인
    intel_report_path = project_dir / "reports" / "intelligent_analysis_report.md"
    if intel_report_path.exists():
        with open(intel_report_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 메타데이터 파싱
        import re
        meta_match = re.search(r'<!-- metadata: round=(\d+), date=([\d-]+) -->', content)
        target_round = meta_match.group(1) if meta_match else "알 수 없음"
        update_date = meta_match.group(2) if meta_match else "알 수 없음"

        st.markdown("---")
        st.markdown(f"### 🚀 AI 지능형 추천 번호 ({target_round}회차)")
        st.caption(f"📅 업데이트: {update_date} | ✨ 강화학습 시뮬레이션 모델 적용")
        
        # 카드 패널 및 공 모양 스타일을 위한 CSS 정의
        st.markdown("""
            <style>
            .ai-card {
                background: linear-gradient(135deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 16px;
                padding: 16px;
                margin-bottom: 16px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            }
            .ball-container {
                display: flex;
                gap: 8px;
                margin: 8px 0;
                align-items: center;
                flex-wrap: wrap;
            }
            .ball {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-weight: bold;
                font-size: 14px;
                box-shadow: 1px 2px 4px rgba(0,0,0,0.3);
                border: 1px solid rgba(255,255,255,0.1);
            }
            .rank-badge {
                background: rgba(56, 189, 248, 0.2);
                color: #38bdf8;
                padding: 2px 10px;
                border-radius: 999px;
                font-size: 12px;
                font-weight: bold;
                margin-bottom: 8px;
                display: inline-block;
                border: 1px solid rgba(56, 189, 248, 0.3);
            }
            .score-text {
                color: #b6c5dd;
                font-size: 12px;
                margin-top: 8px;
                opacity: 0.7;
            }
            </style>
        """, unsafe_allow_html=True)

        lines = content.split('\n')
        for line in lines:
            if '순위:' in line and ',' in line:
                try:
                    match = re.search(r'(\d+순위):\s*([\d\s,]+)\s*\((점수:\s*[\d\.-]+)\)', line)
                    if match:
                        rank = match.group(1)
                        nums_part = match.group(2).strip()
                        score_info = match.group(3).strip()
                        
                        nums = [n.strip() for n in nums_part.split(',') if n.strip()]
                        
                        card_html = f'<div class="ai-card"><div class="rank-badge">{rank}</div>'
                        card_html += '<div class="ball-container">'
                        for n in nums:
                            val = int(n)
                            if val <= 10: color = "#f2b705"
                            elif val <= 20: color = "#007bff"
                            elif val <= 30: color = "#dc3545"
                            elif val <= 40: color = "#6c757d"
                            else: color = "#28a745"
                            card_html += f'<div class="ball" style="background-color: {color};">{val}</div>'
                        card_html += '</div>'
                        card_html += f'<div class="score-text">{score_info}</div></div>'
                        
                        st.markdown(card_html, unsafe_allow_html=True)
                except:
                    pass
        return

    report_path = project_dir / "reports" / "weekly_ai_recommendation.txt"
    
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        st.markdown("---")
        st.markdown("### 🤖 AI 지능형 주간 분석 결과")
        st.caption("💳 본 분석은 AI 모델의 크레딧을 사용하여 생성된 정밀 분석 결과입니다.")
        
        with st.expander("매일 오전 10시 AI 지능형 분석 리포트 보기", expanded=True):
            # 공 모양 스타일을 위한 CSS 정의
            st.markdown("""
                <style>
                .ball-container {
                    display: flex;
                    gap: 8px;
                    margin: 8px 0;
                    align-items: center;
                }
                .ball {
                    width: 32px;
                    height: 32px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    box-shadow: 1px 1px 2px rgba(0,0,0,0.2);
                }
                .rank-label {
                    font-weight: bold;
                    margin-right: 10px;
                    min-width: 50px;
                }
                .score-label {
                    margin-left: 10px;
                    color: #666;
                    font-size: 14px;
                }
                </style>
            """, unsafe_allow_html=True)

            lines = content.split('\n')
            for line in lines:
                if '순위:' in line and ',' in line:
                    try:
                        # 정규식을 사용하여 순위, 번호, 점수를 더 정확하게 추출
                        import re
                        # 형식 예: "1순위: 02, 04, 19, 27, 33, 43 (점수: 27.99)"
                        match = re.search(r'(\d+순위):\s*([\d\s,]+)\s*\((점수:\s*[\d\.-]+)\)', line)
                        
                        if match:
                            rank = match.group(1)
                            nums_part = match.group(2).strip()
                            score_info = match.group(3).strip()
                        else:
                            # 정규식 실패 시 기존 split 방식 시도
                            parts = line.split(':')
                            rank = parts[0].strip()
                            content_part = parts[1].strip()
                            if '(' in content_part:
                                nums_part = content_part.split('(')[0].strip()
                                score_info = content_part.split('(')[1].replace(')', '').strip()
                            else:
                                nums_part = content_part
                                score_info = ""
                        
                        nums = [n.strip() for n in nums_part.split(',') if n.strip()]
                        
                        ball_html = f'<div class="ball-container"><span class="rank-label">{rank}</span>'
                        for n in nums:
                            try:
                                val = int(n)
                                if val <= 10: color = "#f2b705" # 노랑
                                elif val <= 20: color = "#007bff" # 파랑
                                elif val <= 30: color = "#dc3545" # 빨강
                                elif val <= 40: color = "#6c757d" # 회색
                                else: color = "#28a745" # 초록
                                ball_html += f'<div class="ball" style="background-color: {color};">{val}</div>'
                            except:
                                continue
                        
                        if score_info:
                            ball_html += f'<span class="score-label">({score_info})</span></div>'
                        else:
                            ball_html += '</div>'
                            
                        st.markdown(ball_html, unsafe_allow_html=True)
                    except Exception as e:
                        st.text(line)
                else:
                    st.text(line)
    else:
        # 파일이 없을 경우 안내 메시지 (처음 실행 전)
        st.markdown("---")
        st.info("🤖 아직 생성된 AI 분석 결과가 없습니다. 매일 오전 10시에 자동으로 생성됩니다. (분석 시 AI 크레딧이 사용됩니다.)")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("기본 AI 분석 실행", key="run_ai_manual", use_container_width=True):
                with st.spinner("기본 AI 분석 엔진 가동 중..."):
                    try:
                        from ai_scheduler import run_ai_analysis
                        run_ai_analysis()
                        st.success("분석 완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"오류: {e}")
        with col2:
            if st.button("✨ Manus 지능형 분석 (API)", key="run_manus_ai", use_container_width=True):
                if not os.getenv("MANUS_API_KEY"):
                    st.error("MANUS_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
                else:
                    with st.spinner("Manus AI가 로그를 정밀 분석 중입니다 (약 1~2분 소요)..."):
                        try:
                            from manus_ai_analyzer import run_manus_intelligent_analysis
                            run_manus_intelligent_analysis()
                            st.success("Manus 지능형 분석 완료!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Manus API 오류: {e}")

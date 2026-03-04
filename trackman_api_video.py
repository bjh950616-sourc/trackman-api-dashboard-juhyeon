"""
CLIENT_ID = "LotteGiants-test2"
CLIENT_SECRET = 'q"4Hxn#l8dvq61y^3iU#1t}xCgxap_?O'
"""

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# [1] Streamlit 페이지 설정 (반드시 첫 줄에 위치)
st.set_page_config(layout="wide", page_title="TrackMan Game Analysis Hub")

# [2] API 설정 (가이드 Section 4, 5) [cite: 68, 73]
# 배포 시에는 st.secrets를 사용하는 것이 안전합니다.
CLIENT_ID = st.secrets["tm_client_id"]
CLIENT_SECRET = st.secrets["tm_client_secret"]
AUTH_URL = "https://login.trackmanbaseball.com/connect/token"
BASE_URL = "https://dataapi.trackmanbaseball.com/api/v1"

# [3] 인증 토큰 획득 함수 (Section 5.1) [cite: 91]
@st.cache_data(ttl=3600)
def get_access_token():
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    try:
        response = requests.post(AUTH_URL, data=payload)
        if response.status_code == 200:
            return response.json().get("access_token")
    except:
        return None
    return None

token = get_access_token()
headers = {"Authorization": f"Bearer {token}"} if token else {}

# --- 메인 로직 시작 ---
st.title("⚾ 트랙맨 투구 순서 분석 & 경기 영상 매칭")

if not token:
    st.error("API 인증 실패. Client ID와 Secret을 확인하세요.")
else:
    # [4] 사이드바 필터: 경기 조회 (Section 7.1) [cite: 129, 132]
    st.sidebar.header("🔍 경기 조회 필터")
    s_date = st.sidebar.date_input("조회 시작일", datetime.now() - timedelta(days=7))
    e_date = st.sidebar.date_input("조회 종료일", datetime.now())

    search_payload = {
        "sessionType": "All",
        "utcDateFrom": s_date.strftime("%Y-%m-%dT00:00:00Z"),
        "utcDateTo": e_date.strftime("%Y-%m-%dT23:59:59Z")
    }
    
    # 경기 검색 API 호출
    sessions_res = requests.post(f"{BASE_URL}/discovery/game/sessions", headers=headers, json=search_payload)
    sessions = sessions_res.json() if sessions_res.status_code == 200 else []

    if sessions:
        # 팀 목록 추출
        teams = sorted(list(set([s['homeTeam']['name'] for s in sessions] + [s['awayTeam']['name'] for s in sessions])))
        selected_team = st.sidebar.selectbox("팀 선택", ["전체"] + teams)
        
        # 경기 필터링
        filtered_sessions = [s for s in sessions if selected_team == "전체" or 
                             s['homeTeam']['name'] == selected_team or s['awayTeam']['name'] == selected_team]
        
        if filtered_sessions:
            session_options = {f"{s['gameDateLocal'][:10]} | {s['homeTeam']['name']} vs {s['awayTeam']['name']}": s['sessionId'] for s in filtered_sessions}
            selected_game = st.selectbox("분석할 경기를 선택하세요", list(session_options.keys()))
            sid = session_options[selected_game]

            # [5] 데이터 로드 (Plays, Balls, Video Tokens) [cite: 183, 208, 977]
            with st.spinner('데이터를 동기화 중입니다...'):
                plays = requests.get(f"{BASE_URL}/data/game/plays/{sid}", headers=headers).json()
                balls = requests.get(f"{BASE_URL}/data/game/balls/{sid}", headers=headers).json()
                v_tokens = requests.get(f"{BASE_URL}/media/game/videotokens/{sid}", headers=headers).json()

            if plays:
                # [6] 데이터 통합 및 정렬 로직 (Section 8.3) [cite: 701, 742, 744]
                df_rows = []
                for p in plays:
                    pid = p.get('playID')
                    b_info = next((x for x in balls if x.get('playId') == pid), {})
                    
                    # 가이드에 정의된 필드 추출
                    df_rows.append({
                        "playID": pid,
                        "투구번호": p.get('taggerBehavior', {}).get('pitchNo', 0), # 
                        "이닝숫자": p.get('gameState', {}).get('inning', 1),        # 
                        "초말": p.get('gameState', {}).get('topBottom', 'Top'),    # 
                        "이닝": f"{p['gameState']['inning']}회 {p['gameState']['topBottom']}",
                        "투수": p['pitcher']['name'],                             # [cite: 708]
                        "타자": p['batter']['name'],                              # [cite: 718]
                        "카운트": f"{p['gameState']['balls']}B-{p['gameState']['strikes']}S", # [cite: 748, 750]
                        "구종": p['pitchTag']['taggedPitchType'],                 # [cite: 757]
                        "결과": p.get('playResult', {}).get('playResult', 'Unknown'), # [cite: 771]
                        "구속": round(b_info.get('pitch', {}).get('release', {}).get('relSpeed', 0), 1), # [cite: 228]
                        "타구속도": round(b_info.get('hit', {}).get('launch', {}).get('exitSpeed', 0), 1) # [cite: 532]
                    })
                
                # 투구 번호순으로 정렬 (Section 8.5/8.3 정렬 기준) 
                df = pd.DataFrame(df_rows).sort_values(by="투구번호")

                # [7] 투구 세부 필터 (이닝, 초/말)
                st.sidebar.divider()
                st.sidebar.subheader("🎯 투구 리스트 필터")
                selected_innings = st.sidebar.multiselect("이닝 선택", sorted(df['이닝숫자'].unique()), default=sorted(df['이닝숫자'].unique()))
                selected_half = st.sidebar.radio("초/말 선택", ["전체", "Top", "Bottom"], horizontal=True)

                # 필터 적용
                df_filtered = df[df['이닝숫자'].isin(selected_innings)]
                if selected_half != "전체":
                    df_filtered = df_filtered[df_filtered['초말'] == selected_half]

                # [8] 투구 선택 및 영상 출력
                if not df_filtered.empty:
                    st.subheader(f"📋 투구 목록 ({len(df_filtered)}개)")
                    selected_idx = st.selectbox(
                        "분석할 투구를 선택하세요", 
                        df_filtered.index, 
                        format_func=lambda x: f"[{df_filtered.loc[x, '이닝']}] {df_filtered.loc[x, '투수']} vs {df_filtered.loc[x, '타자']} - {df_filtered.loc[x, '구종']} ({df_filtered.loc[x, '투구번호']}구)"
                    )
                    
                    play_data = df_filtered.loc[selected_idx]
                    st.divider()
                    
                    col_vid, col_stat = st.columns([2, 1])
                    with col_vid:
                        st.subheader("🎥 경기 영상")
                        # 사용자가 발견한 4K mkv 경로 규칙 적용 [cite: 1256, 1262]
                        vt = next((t for t in v_tokens if "PlayVideo" in t['type']), None)
                        if vt:
                            # {playID}_4K.mkv 패턴 적용
                            v_url = f"https://{vt['entityPath']}.blob.core.windows.net/{vt['endpoint']}/Plays/{play_data['playID']}/PlayVideo/{play_data['playID']}_4K.mkv{vt['token']}"
                            st.video(v_url)
                        else:
                            st.warning("영상을 불러올 수 없습니다.")

                    with col_stat:
                        st.subheader("📊 상세 데이터")
                        st.metric("투구 구속", f"{play_data['구속']} mph")
                        if play_data['타구속도'] > 0:
                            st.metric("타구 속도", f"{play_data['타구속도']} mph")
                        
                        st.write(f"**상황:** {play_data['이닝']} ({play_data['카운트']})")
                        st.write(f"**투수:** {play_data['투수']}")
                        st.write(f"**타자:** {play_data['타자']}")
                        st.write(f"**결과:** {play_data['결과']}")
                else:
                    st.warning("선택한 필터 조건에 맞는 투구가 없습니다.")
            else:
                st.info("이 경기에는 상세 투구 데이터가 없습니다.")
        else:
            st.info("해당 팀의 경기가 없습니다.")
    else:
        st.info("선택한 날짜 범위에 경기가 없습니다.")
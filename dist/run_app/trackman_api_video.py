import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# [1] 페이지 기본 설정
st.set_page_config(layout="wide", page_title="TrackMan Pro Analyzer v2.3")

# [2] API 인증 정보
try:
    CLIENT_ID = st.secrets["tm_client_id"]
    CLIENT_SECRET = st.secrets["tm_client_secret"]
except:
    CLIENT_ID = "YOUR_CLIENT_ID"
    CLIENT_SECRET = "YOUR_CLIENT_SECRET"

AUTH_URL = "https://login.trackmanbaseball.com/connect/token"
BASE_URL = "https://dataapi.trackmanbaseball.com/api/v1"

@st.cache_data(ttl=3600)
def get_token():
    payload = {'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, 'grant_type': 'client_credentials'}
    try:
        res = requests.post(AUTH_URL, data=payload, timeout=15)
        return res.json().get("access_token") if res.status_code == 200 else None
    except:
        return None

@st.cache_data(ttl=600)
def fetch_game_data(sid, _headers):
    plays = requests.get(f"{BASE_URL}/data/game/plays/{sid}", headers=_headers).json()
    balls = requests.get(f"{BASE_URL}/data/game/balls/{sid}", headers=_headers).json()
    v_tokens = requests.get(f"{BASE_URL}/media/game/videotokens/{sid}", headers=_headers).json()
    return plays, balls, v_tokens

token = get_token()
headers = {"Authorization": f"Bearer {token}"} if token else {}

st.title("⚾ 트랙맨 통합 분석 대시보드")

if not token:
    st.error("API 인증 실패. secrets.toml 파일이나 IP 화이트리스트를 확인하세요.")
else:
    # [3] 사이드바 설정
    st.sidebar.header("🔍 경기 조회")
    s_date = st.sidebar.date_input("조회 시작일", datetime.now() - timedelta(days=14))
    e_date = st.sidebar.date_input("조회 종료일", datetime.now())

    search_payload = {"sessionType": "All", "utcDateFrom": s_date.strftime("%Y-%m-%dT00:00:00Z"), "utcDateTo": e_date.strftime("%Y-%m-%dT23:59:59Z")}
    sessions = requests.post(f"{BASE_URL}/discovery/game/sessions", headers=headers, json=search_payload).json()

    if sessions and isinstance(sessions, list):
        all_teams = sorted(list(set([s.get('homeTeam', {}).get('name', 'Unknown') for s in sessions if isinstance(s, dict)] + 
                                   [s.get('awayTeam', {}).get('name', 'Unknown') for s in sessions if isinstance(s, dict)])))
        selected_team = st.sidebar.selectbox("팀 선택", ["전체"] + all_teams)
        
        filtered_sessions = [s for s in sessions if selected_team == "전체" or s.get('homeTeam', {}).get('name') == selected_team or s.get('awayTeam', {}).get('name') == selected_team]
        game_options = {f"{s.get('gameDateLocal', '')[:10]} | {s.get('homeTeam', {}).get('name')} vs {s.get('awayTeam', {}).get('name')}": s.get('sessionId') for s in filtered_sessions}
        
        if not game_options:
            st.warning("경기가 없습니다.")
            st.stop()
            
        selected_game = st.selectbox("경기를 선택하세요", list(game_options.keys()))
        sid = game_options[selected_game]

        # [4] 데이터 로드 및 통합 가공
        plays, balls, v_tokens = fetch_game_data(sid, headers)

        if plays:
            df_rows = []
            CONV = 1.60934  # mph to km/h

            for p in plays:
                pid = p.get('playID')
                g_state = p.get('gameState', {})
                p_tag = p.get('pitchTag', {})
                
                # [핵심 수동 통합] 해당 playID를 가진 모든 공 데이터를 가져옴
                matching_balls = [b for b in balls if b.get('playId') == pid]
                
                # 투구 정보(Pitch)와 타구 정보(Hit)를 각각 찾음 
                pitch_ball = next((b for b in matching_balls if b.get('kind') == 'Pitch'), {})
                hit_ball = next((b for b in matching_balls if b.get('kind') == 'Hit'), {})

                # 1. 이닝 한글화
                tb = g_state.get('topBottom', '')
                tb_kor = "초" if tb == "Top" else "말" if tb == "Bottom" else tb
                inning_label = f"{g_state.get('inning', 0)}회 {tb_kor}"

                # 2. 투구 구속 (km/h) [cite: 228]
                mph_pitch = pitch_ball.get('pitch', {}).get('release', {}).get('relSpeed', 0) or 0
                kmh_pitch = round(mph_pitch * CONV, 1) if mph_pitch > 0 else "-"

                # 3. 타구 데이터 (km/h) [cite: 532, 549]
                hit_launch = hit_ball.get('hit', {}).get('launch', {})
                mph_hit = hit_launch.get('exitSpeed', 0) or 0
                kmh_hit = round(mph_hit * CONV, 1) if mph_hit > 0 else "-"
                launch_angle = round(hit_launch.get('angle', 0), 1) if mph_hit > 0 else "-"

                # 4. 타석 결과 텍스트화 [cite: 771]
                raw_res = p.get('playResult', {})
                res_text = raw_res.get('playResult') or raw_res.get('result') or "-"

                df_rows.append({
                    "playID": pid,
                    "No": p.get('taggerBehavior', {}).get('pitchNo', 0) or 0,
                    "이닝": inning_label,
                    "투수": p.get('pitcher', {}).get('name', 'Unknown'),
                    "타자": p.get('batter', {}).get('name', 'Unknown'),
                    "카운트": f"{g_state.get('balls', 0)}-{g_state.get('strikes', 0)}",
                    "구종": p_tag.get('taggedPitchType', '-'),
                    "구속": kmh_pitch,
                    "타구속도": kmh_hit,
                    "타구각도": launch_angle,
                    "결과": p_tag.get('pitchCall', 'Unknown'),
                    "타석결과": res_text
                })
            
            df = pd.DataFrame(df_rows).sort_values(by="No").reset_index(drop=True)

            # [5] 화면 레이아웃
            col_table, col_video = st.columns([3, 2])

            with col_table:
                st.subheader("📋 통합 투구/타구 목록 (km/h)")
                event = st.dataframe(
                    df.drop(columns=["playID"]),
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row"
                )

            with col_video:
                st.subheader("🎥 선택된 투구 영상")
                if event.selection and event.selection.rows:
                    selected_play = df.iloc[event.selection.rows[0]]
                    st.info(f"선택: {selected_play['이닝']} | {selected_play['투수']} vs {selected_play['타자']}")
                    
                    vt = next((t for t in v_tokens if "PlayVideo" in t.get('type', '')), None)
                    if vt:
                        blob_path = f"Plays/{selected_play['playID']}/PlayVideo/{selected_play['playID']}_4K.mkv"
                        v_url = f"https://{vt['entityPath']}.blob.core.windows.net/{vt['endpoint']}/{blob_path}{vt['token']}"
                        st.video(v_url)
                    else:
                        st.warning("영상을 찾을 수 없습니다.")
                else:
                    st.info("왼쪽 표에서 투구를 클릭하세요.")
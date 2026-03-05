import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# [1] 페이지 설정
st.set_page_config(layout="wide", page_title="TrackMan Practice Pro v3.4")

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
    except: return None

# [최적화 핵심] 선수-세션 매핑 데이터를 캐싱합니다.
@st.cache_data(ttl=600)
def get_player_session_map(s_date, e_date, _headers):
    search_payload = {
        "sessionType": "All",
        "utcDateFrom": s_date.strftime("%Y-%m-%dT00:00:00Z"),
        "utcDateTo": e_date.strftime("%Y-%m-%dT23:59:59Z")
    }
    # 1. 세션 검색 [cite: 161]
    res = requests.post(f"{BASE_URL}/discovery/practice/sessions", headers=_headers, json=search_payload)
    if not (res.status_code == 200 and res.text.strip()):
        return {}
    
    sessions = res.json()
    player_map = {}
    
    # 2. 각 세션별 선수 확인 (병목 지점)
    # Streamlit 진행 바를 사용하여 사용자에게 시각적 피드백 제공
    progress_text = "선수 명단을 분석 중입니다. 잠시만 기다려주세요..."
    my_bar = st.sidebar.progress(0, text=progress_text)
    
    for i, s in enumerate(sessions):
        sid = s.get('sessionId')
        date_str = s.get('gameDateLocal', '')[:10]
        # 개별 세션 플레이 데이터 호출 [cite: 940]
        p_res = requests.get(f"{BASE_URL}/data/practice/plays/{sid}", headers=_headers).json()
        
        if p_res and isinstance(p_res, list):
            for p in p_res:
                raw_p = p.get('pitcher', 'Unknown')
                p_name = raw_p.get('pitcher') if isinstance(raw_p, dict) else raw_p
                if p_name not in player_map: player_map[p_name] = {}
                player_map[p_name][f"{date_str} ({s.get('sessionType')})"] = sid
        
        # 진행률 업데이트
        my_bar.progress((i + 1) / len(sessions), text=progress_text)
    
    my_bar.empty() # 완료 후 진행 바 제거
    return player_map

@st.cache_data(ttl=600)
def fetch_session_data(sid, _headers):
    plays = requests.get(f"{BASE_URL}/data/practice/plays/{sid}", headers=_headers).json()
    balls = requests.get(f"{BASE_URL}/data/practice/balls/{sid}", headers=_headers).json()
    v_tokens = requests.get(f"{BASE_URL}/media/practice/videotokens/{sid}", headers=_headers).json()
    v_meta = requests.get(f"{BASE_URL}/media/practice/videometadata/{sid}", headers=_headers).json() # [cite: 1206]
    return plays, balls, v_tokens, v_meta

token = get_token()
headers = {"Authorization": f"Bearer {token}"} if token else {}

st.title("📹 트랙맨 불펜 투구 분석")

if not token:
    st.error("API 인증 실패.")
else:
    # [3] 사이드바 설정
    st.sidebar.header("🔍 세션 필터")
    s_date = st.sidebar.date_input("조회 시작", datetime.now() - timedelta(days=14))
    e_date = st.sidebar.date_input("조회 종료", datetime.now())

    # 최적화된 매핑 함수 호출
    player_map = get_player_session_map(s_date, e_date, headers)

    if player_map:
        selected_pitcher = st.sidebar.selectbox("선수 선택", sorted(list(player_map.keys())))
        selected_date = st.sidebar.selectbox("세션 선택", list(player_map[selected_pitcher].keys()))
        sid = player_map[selected_pitcher][selected_date]

        # [4] 상세 데이터 로드
        plays, balls, v_tokens, v_meta = fetch_session_data(sid, headers)
        video_play_ids = set([m.get('playId') for m in v_meta if m.get('cameraType') == 'Edgertronic'])

        if plays:
            df_rows = []
            MPH_TO_KMH, INCH_TO_CM, FOOT_TO_METER = 1.60934, 2.54, 0.3048

            for p in plays:
                raw_p = p.get('pitcher', '')
                p_name = raw_p.get('pitcher') if isinstance(raw_p, dict) else raw_p
                
                if p_name == selected_pitcher:
                    pid = p.get('playID')
                    b_info = next((b for b in balls if b.get('playId') == pid and b.get('trackType') == 'Pitch'), {})
                    meta = next((m for m in v_meta if m.get('playId') == pid and m.get('cameraType') == 'Edgertronic'), None)
                    
                    if b_info:
                        rel, traj = b_info.get('pitch', {}).get('release', {}), b_info.get('pitch', {}).get('trajectory', {})
                        df_rows.append({
                            "playID": pid, "clipId": meta.get('videoClipId') if meta else None,
                            "영상": "📹 있음" if pid in video_play_ids else "❌ 없음",
                            "No": p.get('taggerBehavior', {}).get('pitchNo', 0),
                            "구종": p.get('pitchTag', {}).get('taggedPitchType', '-'),
                            "구속": round(rel.get('relSpeed', 0) * MPH_TO_KMH, 1) if rel.get('relSpeed') else "-",
                            "IVB(cm)": round(traj.get('inducedVertBreak', 0) * INCH_TO_CM, 1) if traj.get('inducedVertBreak') is not None else "-",
                            "HB(cm)": round(traj.get('horzBreak', 0) * INCH_TO_CM, 1) if traj.get('horzBreak') is not None else "-",
                            "회전수": int(rel.get('spinRate', 0)) if rel.get('spinRate') else "-",
                            "익스텐션(m)": round(rel.get('extension', 0) * FOOT_TO_METER, 2) if rel.get('extension') else "-",
                            "릴리스H(m)": round(rel.get('relHeight', 0) * FOOT_TO_METER, 2) if rel.get('relHeight') else "-",
                            "릴리스S(m)": round(rel.get('relSide', 0) * FOOT_TO_METER, 2) if rel.get('relSide') else "-",
                            "회전축": rel.get('tilt', '-')
                        })
            
            df = pd.DataFrame(df_rows).sort_values(by="No").reset_index(drop=True)
            col_table, col_video = st.columns([3, 2])
            with col_table:
                event = st.dataframe(df.drop(columns=["playID", "clipId"]), use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
            with col_video:
                if event.selection and event.selection.rows:
                    selected_row = df.iloc[event.selection.rows[0]]
                    if selected_row["영상"] == "📹 있음":
                        vt = next((t for t in v_tokens if t.get('type') == 'EdgertronicVideos'), None)
                        if vt and selected_row["clipId"]:
                            blob_path = f"Plays/{selected_row['playID']}/Edgertronic/{selected_row['clipId']}.mov"
                            v_url = f"https://{vt['entityPath']}.blob.core.windows.net/{vt['endpoint']}/{blob_path}{vt['token']}"
                            st.video(v_url)
    else:
        st.info("해당 기간에 데이터가 없습니다.")
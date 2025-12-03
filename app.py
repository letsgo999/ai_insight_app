import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
from fpdf import FPDF
from datetime import datetime, timedelta
import os
import requests
import json
from github import Github # PyGithub 라이브러리

# --- 설정 ---
st.set_page_config(page_title="유튜브 서칭 기반 AI BM 탐색기", page_icon="🕵️‍♂️")

FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# --- GitHub 연동 함수 ---

def get_github_repo():
    """Secrets에서 설정된 토큰으로 깃허브 저장소 객체 반환"""
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo_name = st.secrets["REPO_NAME"]
        g = Github(token)
        return g.get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub 연결 실패: Secrets 설정을 확인하세요. ({e})")
        return None

def load_channels_from_github():
    """깃허브의 channels.json 파일을 읽어옴"""
    repo = get_github_repo()
    if not repo: return []
    
    try:
        contents = repo.get_contents("channels.json")
        json_data = contents.decoded_content.decode("utf-8")
        return json.loads(json_data)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return []

def save_channels_to_github(new_data):
    """변경된 데이터를 깃허브 channels.json에 저장(Commit)"""
    repo = get_github_repo()
    if not repo: return False
    
    try:
        contents = repo.get_contents("channels.json")
        # JSON을 예쁘게 포맷팅해서 저장 (한글 깨짐 방지 ensure_ascii=False)
        new_json_str = json.dumps(new_data, indent=4, ensure_ascii=False)
        
        repo.update_file(
            path="channels.json",
            message="Update channels via Streamlit App",
            content=new_json_str,
            sha=contents.sha
        )
        return True
    except Exception as e:
        st.error(f"데이터 저장 실패: {e}")
        return False

# --- 일반 함수 ---

def download_font_if_not_exists():
    if not os.path.exists(FONT_FILE):
        with st.spinner("폰트 다운로드 중..."):
            try:
                response = requests.get(FONT_URL)
                with open(FONT_FILE, "wb") as f:
                    f.write(response.content)
            except: pass

def get_channel_info_from_handle(api_key, handle_str):
    """핸들(@name)이나 URL을 입력받아 정확한 ID와 채널명을 반환"""
    youtube = build('youtube', 'v3', developerKey=api_key)
    
    # 입력값 정리 (URL 제거, @만 남기기)
    clean_handle = handle_str.strip()
    if "youtube.com/" in clean_handle:
        clean_handle = clean_handle.split("/")[-1]
    
    # 검색 쿼리 (@가 없으면 붙여서 검색 시도)
    query = clean_handle if clean_handle.startswith("@") else f"@{clean_handle}"
    
    try:
        # 1. Search API로 채널 검색
        request = youtube.search().list(
            part="snippet",
            q=query,
            type="channel",
            maxResults=1
        )
        response = request.execute()
        
        if response['items']:
            item = response['items'][0]
            return item['id']['channelId'], item['snippet']['title'], query
        else:
            return None, None, None
    except Exception as e:
        return None, None, f"Error: {e}"

def get_recent_video(api_key, channel_id, days=7):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        now = datetime.utcnow()
        past = now - timedelta(days=days)
        published_after = past.isoformat("T") + "Z"

        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=1,
            order="date",
            publishedAfter=published_after,
            type="video"
        )
        response = request.execute()
        if response.get("items"):
            item = response["items"][0]
            return {
                "title": item["snippet"]["title"],
                "video_id": item["id"]["videoId"],
                "published_at": item["snippet"]["publishedAt"]
            }
        return None
    except: return None

def get_video_script(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko'])
        return " ".join([t['text'] for t in transcript])
    except: return None

def analyze_with_gpt(openai_api_key, script, video_title, channel_name):
    client = OpenAI(api_key=openai_api_key)
    prompt = """
    너는 'AI 에이전트 파견 비즈니스' 전문 컨설턴트야. 
    제공된 유튜브 스크립트를 분석해서, 소규모 기업 대상 AI 에이전트 임대 사업에 적용할 수 있는 
    구체적이고 실현 가능한 비즈니스 인사이트 5가지를 도출해줘.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"채널: {channel_name}\n영상: {video_title}\n내용:\n{script[:12000]}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e: return str(e)

def create_pdf(report_text):
    download_font_if_not_exists()
    class PDF(FPDF):
        def header(self):
            if os.path.exists(FONT_FILE):
                self.add_font('NanumGothic', '', FONT_FILE, uni=True)
                self.set_font('NanumGothic', '', 10)
            self.cell(0, 10, 'AI Business Insight Report', 0, 1, 'C')
    pdf = PDF()
    pdf.add_page()
    if os.path.exists(FONT_FILE):
        pdf.add_font('NanumGothic', '', FONT_FILE, uni=True)
        pdf.set_font('NanumGothic', '', 11)
    else: pdf.set_font("Arial", size=11)
    pdf.multi_cell(0, 8, report_text)
    return pdf.output(dest='S').encode('latin-1')

# --- 데이터 로드 ---

# 세션 상태에 채널 데이터가 없으면 깃허브에서 로드
if 'channels' not in st.session_state:
    with st.spinner("데이터베이스 로딩 중..."):
        st.session_state['channels'] = load_channels_from_github()

# --- UI 구현 ---

st.title("🕵️‍♂️ 유튜브 서칭 기반 AI BM 탐색기")

# 사이드바 키 설정
st.sidebar.header("🔑 설정")
youtube_api_key = st.text_input("YouTube API Key", value=st.secrets.get("YOUTUBE_API_KEY", ""), type="password")
openai_api_key = st.text_input("OpenAI API Key", value=st.secrets.get("OPENAI_API_KEY", ""), type="password")

if not youtube_api_key or not openai_api_key:
    st.warning("사이드바 또는 Secrets에 API 키를 설정해주세요.")
    st.stop()

# 채널 선택 메뉴
channel_list = st.session_state['channels']
channel_names = [f"{c['name']} ({c.get('handle', 'No Handle')})" for c in channel_list]
channel_names.append("➕ [새 채널 추가]")

st.subheader("1️⃣ 분석할 채널 선택")
selection = st.selectbox("채널 목록", channel_names)

# === [로직 1: 새 채널 추가] ===
if selection == "➕ [새 채널 추가]":
    st.info("유튜브 핸들(예: @jocoding)을 입력하면 ID를 자동으로 찾아 저장합니다.")
    
    if len(channel_list) >= 15:
        st.error("⚠️ 최대 15개까지만 등록 가능합니다. 기존 채널을 삭제해주세요.")
        # 삭제 UI 표시
        st.markdown("---")
        st.write("🗑️ **채널 정리하기**")
        for idx, ch in enumerate(channel_list):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{ch['name']}** ({ch.get('handle')})")
            if c2.button("삭제", key=f"del_{idx}"):
                del channel_list[idx]
                if save_channels_to_github(channel_list):
                    st.success("삭제 후 저장 완료!")
                    st.session_state['channels'] = channel_list
                    st.rerun()
    else:
        with st.form("add_form"):
            new_handle = st.text_input("유튜브 핸들 입력 (예: @jocoding)")
            if st.form_submit_button("검색 및 추가"):
                cid, ctitle, chandle = get_channel_info_from_handle(youtube_api_key, new_handle)
                if cid:
                    # 중복 체크
                    if any(c['id'] == cid for c in channel_list):
                        st.warning("이미 등록된 채널입니다.")
                    else:
                        new_data = {"name": ctitle, "handle": chandle, "id": cid}
                        channel_list.append(new_data)
                        if save_channels_to_github(channel_list):
                            st.success(f"✅ '{ctitle}' 저장 완료!")
                            st.session_state['channels'] = channel_list
                            st.rerun()
                else:
                    st.error("채널을 찾을 수 없습니다. 핸들을 확인해주세요.")

# === [로직 2: 기존 채널 분석 및 수정] ===
else:
    # 선택된 채널 객체 찾기
    selected_idx = channel_names.index(selection)
    target_channel = channel_list[selected_idx]
    
    st.write(f"📢 **'{target_channel['name']}'** 분석 대기 중")

    # 관리 메뉴 (수정/삭제)
    with st.expander("⚙️ 채널 정보 수정 및 삭제"):
        st.subheader("✏️ 정보 수정")
        current_handle = target_channel.get('handle', '')
        
        # 수정 폼
        with st.form("edit_form"):
            edit_handle = st.text_input("핸들 수정 (@name)", value=current_handle)
            if st.form_submit_button("수정 저장"):
                cid, ctitle, chandle = get_channel_info_from_handle(youtube_api_key, edit_handle)
                if cid:
                    # 데이터 업데이트
                    updated_data = {"name": ctitle, "handle": chandle, "id": cid}
                    channel_list[selected_idx] = updated_data
                    
                    if save_channels_to_github(channel_list):
                        st.success(f"✅ '{ctitle}'로 업데이트 및 저장되었습니다.")
                        st.session_state['channels'] = channel_list
                        st.rerun()
                else:
                    st.error("유효하지 않은 핸들입니다.")
        
        st.divider()
        if st.button("이 채널 삭제 ❌", type="primary"):
            del channel_list[selected_idx]
            if save_channels_to_github(channel_list):
                st.success("삭제되었습니다.")
                st.session_state['channels'] = channel_list
                st.rerun()

    # 분석 버튼
    if st.button("🚀 분석 및 리포트 생성"):
        with st.status("분석 진행 중...", expanded=True) as status:
            st.write("🔍 최신 영상 검색 중...")
            video_info = get_recent_video(youtube_api_key, target_channel['id'])
            
            if not video_info:
                status.update(label="신규 영상 없음", state="error")
                st.warning("최근 1주일 이내 업로드된 영상이 없습니다.")
            else:
                st.write(f"🎥 영상 발견: {video_info['title']}")
                script = get_video_script(video_info['video_id'])
                
                if not script:
                    status.update(label="자막 없음", state="error")
                    st.error("이 영상에는 한글 자막이 없습니다.")
                else:
                    st.write("🧠 AI 인사이트 도출 중...")
                    insight = analyze_with_gpt(openai_api_key, script, video_info['title'], target_channel['name'])
                    status.update(label="완료!", state="complete")
                    
                    st.subheader("📊 분석 결과")
                    st.markdown(insight)
                    
                    # PDF
                    pdf_content = f"채널: {target_channel['name']}\n영상: {video_info['title']}\n\n{insight}"
                    st.download_button("📥 PDF 다운로드", create_pdf(pdf_content), "report.pdf", "application/pdf")

# 폰트 다운로드
download_font_if_not_exists()

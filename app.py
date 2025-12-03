import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
from fpdf import FPDF
from datetime import datetime, timedelta
import os
import requests
import re # URL 파싱용

# --- 초기 설정 및 데이터 ---

# 나눔고딕 폰트 설정
FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# 기본 11개 채널 데이터 (세션 상태 초기화용)
DEFAULT_CHANNELS = [
    {"name": "조코딩", "id": "UCQNE2JmbasNYbjGAvenGU9g"},
    {"name": "AI코리아 커뮤니티", "id": "UC3SyTcoU-_peD8NKvlYKqag"},
    {"name": "평범한 사업가", "id": "UCDhZ7Z8j7Z7Z8j7Z7Z8j7Z"}, # (실제 ID 필요)
    {"name": "인공지능 한이룸", "id": "UC-default-id-1"},
    {"name": "오빠두엑셀", "id": "UC-default-id-2"},
    {"name": "엑셀러TV", "id": "UC-default-id-3"},
    {"name": "일잘러 장피엠", "id": "UC-default-id-4"},
    {"name": "10X AI Club", "id": "UC-default-id-5"},
    {"name": "GPTers 커뮤니티", "id": "UC-default-id-6"},
    {"name": "감자나라ai", "id": "UC-default-id-7"},
    {"name": "에너지기술연구원", "id": "UC-default-id-8"},
]

# 세션 상태에 채널 목록 관리 (새로고침해도 유지되도록)
if 'channels' not in st.session_state:
    st.session_state['channels'] = DEFAULT_CHANNELS

# --- 함수 정의 ---

def download_font_if_not_exists():
    """나눔고딕 폰트 다운로드"""
    if not os.path.exists(FONT_FILE):
        with st.spinner("한글 폰트(NanumGothic)를 다운로드 중입니다..."):
            try:
                response = requests.get(FONT_URL)
                response.raise_for_status()
                with open(FONT_FILE, "wb") as f:
                    f.write(response.content)
            except Exception as e:
                st.error(f"폰트 다운로드 실패: {e}")

def get_channel_id_from_input(api_key, input_str):
    """입력된 URL이나 핸들(@name)에서 Channel ID 찾기"""
    youtube = build('youtube', 'v3', developerKey=api_key)
    
    # 1. URL이나 핸들에서 키워드 추출
    if "youtube.com/channel/" in input_str:
        return input_str.split("channel/")[1].split("/")[0], None
    
    handle = input_str
    if "youtube.com/@" in input_str:
        handle = input_str.split("@")[1].split("/")[0]
    elif "@" in input_str:
        handle = input_str.replace("@", "")
    
    # 2. Search API로 채널 검색
    try:
        request = youtube.search().list(
            part="snippet",
            q=handle,
            type="channel",
            maxResults=1
        )
        response = request.execute()
        if response['items']:
            item = response['items'][0]
            return item['id']['channelId'], item['snippet']['title']
    except Exception as e:
        return None, f"API 오류: {e}"
    
    return None, "채널을 찾을 수 없습니다."

def get_recent_video(api_key, channel_id, days=7):
    """선택한 채널의 최신 영상 1개 가져오기"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        now = datetime.utcnow()
        past = now - timedelta(days=days)
        published_after = past.isoformat("T") + "Z"

        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=1, # 1개만 분석
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
                "published_at": item["snippet"]["publishedAt"],
                "channel": item["snippet"]["channelTitle"]
            }
        return None
    except Exception as e:
        st.error(f"유튜브 검색 오류: {e}")
        return None

def get_video_script(video_id):
    """자막 추출"""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko'])
        return " ".join([t['text'] for t in transcript])
    except:
        return None

def analyze_with_gpt(openai_api_key, script, video_title, channel_name):
    """GPT-4o 분석"""
    client = OpenAI(api_key=openai_api_key)
    system_prompt = """
    너는 'AI 에이전트 파견 비즈니스' 전문 컨설턴트야. 
    제공된 유튜브 스크립트를 분석해서, 소규모 기업 대상 AI 에이전트 임대 사업에 적용할 수 있는 
    구체적이고 실현 가능한 비즈니스 인사이트 5가지를 도출해줘.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"채널: {channel_name}\n영상: {video_title}\n내용:\n{script[:12000]}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"분석 오류: {e}"

def create_pdf(report_text):
    """PDF 생성 (나눔고딕)"""
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
    else:
        pdf.set_font("Arial", size=11)

    pdf.multi_cell(0, 8, report_text)
    return pdf.output(dest='S').encode('latin-1')

# --- Streamlit UI 구성 ---

st.set_page_config(page_title="AI 에이전트 리포터", page_icon="🕵️‍♂️")
st.title("🕵️‍♂️ AI 에이전트 비즈니스 인사이트 리포터")

# 사이드바: API 키 설정
st.sidebar.header("🔑 설정")
if "YOUTUBE_API_KEY" in st.secrets:
    youtube_api_key = st.secrets["YOUTUBE_API_KEY"]
    st.sidebar.success("유튜브 키 로드됨")
else:
    youtube_api_key = st.sidebar.text_input("YouTube API Key", type="password")

if "OPENAI_API_KEY" in st.secrets:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    st.sidebar.success("OpenAI 키 로드됨")
else:
    openai_api_key = st.sidebar.text_input("OpenAI API Key", type="password")


# --- 메인 인터페이스: 채널 선택 및 관리 ---

# 채널 목록 준비
channel_options = [c['name'] for c in st.session_state['channels']]
channel_options.append("➕ [새 채널 추가]") # 맨 마지막에 추가 옵션

st.subheader("1️⃣ 분석할 채널 선택")
selected_option = st.selectbox("분석하고 싶은 유튜브 채널을 선택하세요:", channel_options)

# [새 채널 추가] 로직
if selected_option == "➕ [새 채널 추가]":
    st.info("새로운 유튜브 채널을 목록에 추가합니다.")
    
    # 채널 수 제한 체크 (15개)
    if len(st.session_state['channels']) >= 15:
        st.error("⚠️ 경고: 더 이상 채널을 추가할 수 없습니다. (최대 15개 제한)")
        st.warning("아래 목록에서 불필요한 채널을 삭제(X)하여 공간을 확보하세요.")
        
        # 삭제 관리 UI (경고 상태일 때 자동 노출)
        st.markdown("---")
        st.write("🗑️ **채널 목록 관리 (삭제)**")
        for idx, ch in enumerate(st.session_state['channels']):
            col1, col2 = st.columns([4, 1])
            col1.write(f"**{ch['name']}**")
            if col2.button("삭제 ❌", key=f"del_{idx}"):
                del st.session_state['channels'][idx]
                st.rerun() # 즉시 새로고침
        st.markdown("---")
        
    else:
        # 채널 추가 입력 폼
        with st.form("add_channel_form"):
            new_channel_input = st.text_input("채널 핸들(@name) 또는 URL 입력", placeholder="예: @jocoding")
            submit_add = st.form_submit_button("추가")
            
            if submit_add and new_channel_input:
                if not youtube_api_key:
                    st.error("유튜브 API 키를 먼저 설정해주세요.")
                else:
                    with st.spinner("채널 정보를 확인 중입니다..."):
                        cid, ctitle = get_channel_id_from_input(youtube_api_key, new_channel_input)
                        
                        if cid:
                            # 중복 체크
                            if any(c['id'] == cid for c in st.session_state['channels']):
                                st.warning("이미 목록에 있는 채널입니다.")
                            else:
                                st.session_state['channels'].append({"name": ctitle or new_channel_input, "id": cid})
                                st.success(f"✅ '{ctitle}' 채널이 추가되었습니다!")
                                st.rerun()
                        else:
                            st.error(f"채널 추가 실패: {ctitle}")

# 일반 채널 선택 시 분석 UI
elif selected_option:
    # 선택된 채널 정보 찾기
    target_channel = next((item for item in st.session_state['channels'] if item["name"] == selected_option), None)
    
    if target_channel:
        st.write(f"📢 **'{target_channel['name']}'** 채널의 최근 1주일 영상을 분석합니다.")
        
        # 채널 삭제 버튼 (개별 관리용)
        with st.expander("이 채널 관리 (삭제)"):
            if st.button("현재 선택된 채널 목록에서 삭제", key="del_current"):
                st.session_state['channels'] = [c for c in st.session_state['channels'] if c['id'] != target_channel['id']]
                st.rerun()

        if st.button("🚀 분석 및 리포트 생성 시작"):
            if not youtube_api_key or not openai_api_key:
                st.error("API 키가 필요합니다.")
            else:
                with st.status("분석 진행 중...", expanded=True) as status:
                    st.write("🔍 최신 영상 검색 중...")
                    video_info = get_recent_video(youtube_api_key, target_channel['id'])
                    
                    if not video_info:
                        status.update(label="신규 영상 없음", state="error")
                        st.warning("최근 1주일 이내 업로드된 영상이 없습니다.")
                    else:
                        st.write(f"🎥 영상 발견: {video_info['title']}")
                        
                        st.write("📝 자막 추출 중...")
                        script = get_video_script(video_info['video_id'])
                        
                        if not script:
                            status.update(label="자막 없음", state="error")
                            st.error("이 영상에는 한글 자막이 없어 분석할 수 없습니다.")
                        else:
                            st.write("🧠 AI 인사이트 도출 중...")
                            insight_text = analyze_with_gpt(openai_api_key, script, video_info['title'], target_channel['name'])
                            
                            status.update(label="완료!", state="complete")
                            
                            # 결과 보여주기
                            st.subheader("📊 분석 결과")
                            st.markdown(insight_text)
                            
                            # PDF 다운로드
                            report_content = f"채널: {target_channel['name']}\n영상: {video_info['title']}\n일자: {datetime.now().strftime('%Y-%m-%d')}\n\n{insight_text}"
                            pdf_bytes = create_pdf(report_content)
                            
                            st.download_button(
                                label="📥 PDF 리포트 다운로드",
                                data=pdf_bytes,
                                file_name=f"Insight_{target_channel['name']}.pdf",
                                mime="application/pdf"
                            )

# 폰트 미리 다운로드 (배경 실행)
download_font_if_not_exists()

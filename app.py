import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
from fpdf import FPDF
from datetime import datetime, timedelta
import os
import requests  # 폰트 다운로드를 위해 추가

# --- 설정 ---
# 11개 추천 채널의 ID 목록
TARGET_CHANNELS = [
    {"name": "조코딩", "id": "UCQNE2JmbasNYbjGAvenGU9g"},
    {"name": "AI코리아 커뮤니티", "id": "UC3SyTcoU-_peD8NKvlYKqag"},
    {"name": "평범한 사업가", "id": "UCDhZ7Z8j7Z7Z8j7Z7Z8j7Z"}, # (실제 ID 확인 필요)
    {"name": "인공지능 한이룸", "id": "UC..."}, # (실제 ID 채워넣기)
    # ... 나머지 채널 ID 추가
]

# 폰트 파일명 및 다운로드 URL (구글 폰트 공식 저장소)
FONT_FILE = "NotoSansKR-Regular.ttf"
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/NotoSansKR-Regular.ttf"

# --- 함수 정의 ---

def download_font_if_not_exists():
    """폰트 파일이 없으면 웹에서 다운로드"""
    if not os.path.exists(FONT_FILE):
        with st.spinner("한글 폰트(Noto Sans KR)를 다운로드 중입니다..."):
            try:
                response = requests.get(FONT_URL)
                response.raise_for_status()
                with open(FONT_FILE, "wb") as f:
                    f.write(response.content)
                st.success("폰트 다운로드 완료!")
            except Exception as e:
                st.error(f"폰트 다운로드 실패: {e}")

def get_recent_videos(api_key, channel_id, days=7):
    """특정 채널에서 최근 N일 이내 업로드된 동영상 목록 가져오기"""
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        
        # 날짜 계산 (RFC 3339 포맷)
        now = datetime.utcnow()
        past = now - timedelta(days=days)
        published_after = past.isoformat("T") + "Z"

        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=3, # 테스트를 위해 3개로 제한
            order="date",
            publishedAfter=published_after,
            type="video"
        )
        response = request.execute()
        
        videos = []
        for item in response.get("items", []):
            videos.append({
                "title": item["snippet"]["title"],
                "video_id": item["id"]["videoId"],
                "published_at": item["snippet"]["publishedAt"],
                "channel": item["snippet"]["channelTitle"]
            })
        return videos
    except Exception as e:
        # API 키 오류 등이 발생해도 멈추지 않고 빈 리스트 반환 후 로그 출력
        print(f"Error fetching videos for channel {channel_id}: {e}")
        return []

def get_video_script(video_id):
    """동영상 자막 추출"""
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko'])
        script_text = " ".join([t['text'] for t in transcript])
        return script_text
    except Exception:
        return None # 자막이 없거나 추출 불가

def analyze_with_gpt(openai_api_key, script, video_title):
    """GPT-4o를 이용해 비즈니스 인사이트 도출"""
    client = OpenAI(api_key=openai_api_key)
    
    system_prompt = """
    너는 'AI 에이전트 파견 비즈니스' 전문 컨설턴트야. 
    제공된 유튜브 스크립트를 분석해서, 소규모 기업 대상 AI 에이전트 임대 사업에 적용할 수 있는 
    구체적이고 실현 가능한 비즈니스 인사이트 5가지를 도출해줘.
    
    보고서 형식:
    1. 영상 요약 (3줄)
    2. 핵심 기술/트렌드 분석
    3. AI 에이전트 비즈니스 적용 아이디어 5가지 (상세하게 기술)
    4. 결론 및 제언
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"영상 제목: {video_title}\n\n스크립트 내용:\n{script[:10000]}"} # 토큰 절약
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 분석 중 오류 발생: {e}"

def create_pdf(report_text):
    """분석 내용을 PDF로 변환 (Noto Sans KR 사용)"""
    
    # PDF 생성 전 폰트 다운로드 확인
    download_font_if_not_exists()

    class PDF(FPDF):
        def header(self):
            # 폰트가 존재할 때만 설정
            if os.path.exists(FONT_FILE):
                self.add_font('NotoSansKR', '', FONT_FILE, uni=True)
                self.set_font('NotoSansKR', '', 10)
            self.cell(0, 10, 'AI Business Insight Report', 0, 1, 'C')

    pdf = PDF()
    pdf.add_page()
    
    # 본문 폰트 설정
    if os.path.exists(FONT_FILE):
        pdf.add_font('NotoSansKR', '', FONT_FILE, uni=True)
        pdf.set_font('NotoSansKR', '', 11)
    else:
        st.warning("폰트 파일 다운로드에 실패하여 기본 폰트를 사용합니다. 한글이 깨질 수 있습니다.")
        pdf.set_font("Arial", size=11)

    # 텍스트 쓰기
    pdf.multi_cell(0, 8, report_text)
    
    return pdf.output(dest='S').encode('latin-1')

# --- Streamlit UI ---

st.title("🕵️‍♂️ AI 에이전트 비즈니스 인사이트 리포터")
st.caption("Noto Sans KR 폰트 자동 적용 버전")

# 사이드바 설정 (Secrets 자동 로드)# 사이드바 설정
st.sidebar.header("설정 (Settings)")

# 1. Secrets에 키가 있는지 먼저 확인
if "YOUTUBE_API_KEY" in st.secrets:
    default_youtube_key = st.secrets["YOUTUBE_API_KEY"]
    st.sidebar.success("유튜브 API 키가 로드되었습니다.")
else:
    default_youtube_key = ""

if "OPENAI_API_KEY" in st.secrets:
    default_openai_key = st.secrets["OPENAI_API_KEY"]
    st.sidebar.success("OpenAI API 키가 로드되었습니다.")
else:
    default_openai_key = ""

# 2. Secrets 값이 있으면 자동으로 채워넣음 (없으면 빈칸)
youtube_api_key = st.sidebar.text_input("YouTube Data API Key", value=default_youtube_key, type="password")
openai_api_key = st.sidebar.text_input("OpenAI API Key", value=default_openai_key, type="password")

if st.button("분석 시작 (Start Analysis)"):
    if not youtube_api_key or not openai_api_key:
        st.error("API 키를 모두 입력해주세요.")
    else:
        st.info("최신 영상을 검색하고 분석을 시작합니다...")
        
        # 폰트 미리 다운로드 (PDF 생성 시 딜레이 방지)
        download_font_if_not_exists()
        
        full_report = f"AI 비즈니스 인사이트 리포트\n생성일: {datetime.now().strftime('%Y-%m-%d')}\n\n"
        video_count = 0
        
        progress_bar = st.progress(0)
        
        for i, channel in enumerate(TARGET_CHANNELS):
            # 채널 ID가 비어있으면 건너뜀
            if "UC" not in channel['id']: 
                continue

            st.write(f"📡 '{channel['name']}' 검색 중...")
            videos = get_recent_videos(youtube_api_key, channel['id'])
            
            if not videos:
                continue
                
            for video in videos:
                st.write(f"   ▶ 분석 중: {video['title']}")
                script = get_video_script(video['video_id'])
                
                if script:
                    insight = analyze_with_gpt(openai_api_key, script, video['title'])
                    
                    report_section = f"\n{'='*40}\n[채널: {channel['name']}] {video['title']}\n{'='*40}\n{insight}\n\n"
                    full_report += report_section

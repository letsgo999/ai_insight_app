import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
from fpdf import FPDF
from datetime import datetime, timedelta
import os

# --- 설정 ---
# 11개 추천 채널의 ID 또는 핸들 리스트 (실제 ID로 변환이 필요할 수 있으나, 여기선 핸들/ID 혼용 예시)
# 정확도를 위해 가급적 Channel ID(UC...)를 사용하는 것이 좋습니다.
TARGET_CHANNELS = [
    {"name": "조코딩", "id": "UCQNE2JmbasNYbjGAvenGU9g"}, # 조코딩
    {"name": "AI코리아 커뮤니티", "id": "UC3SyTcoU-_peD8NKvlYKqag"}, # AI코리아
    {"name": "평범한 사업가", "id": "UCDhZ7Z8j7Z7Z8j7Z7Z8j7Z"}, # (예시 ID, 실제 ID 확인 필요)
    # ... 실제 구현시 11개 채널의 정확한 Channel ID를 채워 넣어야 합니다.
    # 테스트를 위해 조코딩님 채널 ID만 샘플로 넣었습니다. 나머지는 유튜브 채널 정보보기에서 ID 확인 후 추가하세요.
]

# --- 함수 정의 ---

def get_recent_videos(api_key, channel_id, days=7):
    """특정 채널에서 최근 N일 이내 업로드된 동영상 목록 가져오기"""
    youtube = build('youtube', 'v3', developerKey=api_key)
    
    # 날짜 계산 (RFC 3339 포맷)
    now = datetime.utcnow()
    past = now - timedelta(days=days)
    published_after = past.isoformat("T") + "Z"

    try:
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=5,
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
        st.error(f"유튜브 API 오류 ({channel_id}): {e}")
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
    3. AI 에이전트 비즈니스 적용 아이디어 5가지 (상세하게 기술하여 분량을 확보할 것)
    4. 결론 및 제언
    
    전체 분량은 A4 0.5페이지 이상이 되도록 상세하게 작성해줘.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"영상 제목: {video_title}\n\n스크립트 내용:\n{script[:15000]}"} # 토큰 제한 고려하여 자름
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 분석 중 오류 발생: {e}"

def create_pdf(report_text):
    """분석 내용을 PDF로 변환 (한글 폰트 필요)"""
    class PDF(FPDF):
        def header(self):
            # 폰트가 있는 경우에만 사용 (경로 수정 필요)
            if os.path.exists('NanumGothic.ttf'):
                self.add_font('NanumGothic', '', 'NanumGothic.ttf', uni=True)
                self.set_font('NanumGothic', '', 10)
            self.cell(0, 10, 'AI Trend & Insight Report', 0, 1, 'C')

    pdf = PDF()
    pdf.add_page()
    
    # 한글 폰트 설정 (같은 폴더에 NanumGothic.ttf 파일이 있어야 함)
    if os.path.exists('NanumGothic.ttf'):
        pdf.add_font('NanumGothic', '', 'NanumGothic.ttf', uni=True)
        pdf.set_font('NanumGothic', '', 11)
    else:
        st.warning("NanumGothic.ttf 폰트 파일이 없습니다. PDF 한글이 깨질 수 있습니다.")
        pdf.set_font("Arial", size=11)

    # 텍스트 쓰기 (줄바꿈 처리)
    pdf.multi_cell(0, 8, report_text)
    
    return pdf.output(dest='S').encode('latin-1')

# --- Streamlit UI ---

st.title("🕵️‍♂️ AI 에이전트 비즈니스 인사이트 리포터")
st.markdown("""
이 앱은 지정된 유튜브 채널의 **최근 1주일 신규 영상**을 분석하여, 
**AI 에이전트 파견업**에 적용 가능한 비즈니스 모델 아이디어를 도출하고 PDF 리포트로 제공합니다.
""")

# 사이드바 설정
st.sidebar.header("설정 (Settings)")
youtube_api_key = st.sidebar.text_input("YouTube Data API Key", type="password")
openai_api_key = st.sidebar.text_input("OpenAI API Key", type="password")

if st.button("분석 시작 (Start Analysis)"):
    if not youtube_api_key or not openai_api_key:
        st.error("API 키를 모두 입력해주세요.")
    else:
        st.info("최신 영상을 검색하고 분석을 시작합니다... (시간이 소요될 수 있습니다)")
        
        full_report = f"AI 비즈니스 인사이트 리포트\n생성일: {datetime.now().strftime('%Y-%m-%d')}\n\n"
        video_count = 0
        
        progress_bar = st.progress(0)
        
        for i, channel in enumerate(TARGET_CHANNELS):
            st.write(f"📡 '{channel['name']}' 채널 스캔 중...")
            videos = get_recent_videos(youtube_api_key, channel['id'])
            
            if not videos:
                st.write(f"   - 최근 1주일 내 신규 영상 없음.")
                continue
                
            for video in videos:
                st.write(f"   ▶ 분석 중: {video['title']}")
                script = get_video_script(video['video_id'])
                
                if script:
                    insight = analyze_with_gpt(openai_api_key, script, video['title'])
                    
                    # 리포트 누적
                    report_section = f"\n{'='*40}\n[채널: {channel['name']}] {video['title']}\n{'='*40}\n{insight}\n\n"
                    full_report += report_section
                    
                    with st.expander(f"결과 보기: {video['title']}"):
                        st.write(insight)
                    video_count += 1
                else:
                    st.warning(f"   - 자막을 추출할 수 없어 분석을 건너뜁니다: {video['title']}")
            
            progress_bar.progress((i + 1) / len(TARGET_CHANNELS))

        st.success(f"분석 완료! 총 {video_count}개의 영상에서 인사이트를 도출했습니다.")
        
        # PDF 다운로드 버튼
        if video_count > 0:
            pdf_data = create_pdf(full_report)
            st.download_button(
                label="📥 PDF 리포트 다운로드",
                data=pdf_data,
                file_name="AI_Agent_Business_Report.pdf",
                mime="application/pdf"
            )
        else:
            st.warning("분석할 수 있는 신규 영상이 없거나 자막을 가져올 수 없습니다.")

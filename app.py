import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
from fpdf import FPDF
from datetime import datetime, timedelta
import os
import requests
import json
from github import Github
import yt_dlp # 오디오 다운로드용

# --- 설정 ---
st.set_page_config(page_title="유튜브 서칭 기반 AI BM 탐색기", page_icon="🕵️‍♂️")

FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# --- GitHub 연동 함수 (기존과 동일) ---
def get_github_repo():
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo_name = st.secrets["REPO_NAME"]
        g = Github(token)
        return g.get_repo(repo_name)
    except Exception as e:
        st.error(f"GitHub 연결 실패: {e}")
        return None

def load_channels_from_github():
    repo = get_github_repo()
    if not repo: return []
    try:
        contents = repo.get_contents("channels.json")
        return json.loads(contents.decoded_content.decode("utf-8"))
    except: return []

def save_channels_to_github(new_data):
    repo = get_github_repo()
    if not repo: return False
    try:
        contents = repo.get_contents("channels.json")
        new_json_str = json.dumps(new_data, indent=4, ensure_ascii=False)
        repo.update_file("channels.json", "Update channels", new_json_str, contents.sha)
        return True
    except: return False

# --- 일반 함수 ---
def download_font_if_not_exists():
    if not os.path.exists(FONT_FILE):
        try:
            response = requests.get(FONT_URL)
            with open(FONT_FILE, "wb") as f: f.write(response.content)
        except: pass

def get_channel_info_from_handle(api_key, handle_str):
    youtube = build('youtube', 'v3', developerKey=api_key)
    clean_handle = handle_str.strip().split("/")[-1]
    query = clean_handle if clean_handle.startswith("@") else f"@{clean_handle}"
    try:
        request = youtube.search().list(part="snippet", q=query, type="channel", maxResults=1)
        response = request.execute()
        if response['items']:
            item = response['items'][0]
            return item['id']['channelId'], item['snippet']['title'], query
        return None, None, None
    except Exception as e: return None, None, str(e)

def get_recent_video(api_key, channel_id, days=7):
    try:
        youtube = build('youtube', 'v3', developerKey=api_key)
        past = (datetime.utcnow() - timedelta(days=days)).isoformat("T") + "Z"
        request = youtube.search().list(part="snippet", channelId=channel_id, maxResults=1, order="date", publishedAfter=past, type="video")
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

# --- [핵심 수정] 자막 및 오디오 추출 로직 ---

def transcribe_audio_with_whisper(openai_api_key, video_url):
    """자막이 없을 때 오디오를 다운받아 Whisper로 변환"""
    client = OpenAI(api_key=openai_api_key)
    audio_file = "temp_audio.mp3"
    
    # 1. 오디오 다운로드 (yt-dlp)
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        'outtmpl': 'temp_audio',
        'quiet': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        
        # 2. Whisper API 호출
        if os.path.exists(audio_file):
            with open(audio_file, "rb") as f:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=f,
                    response_format="text"
                )
            
            # 파일 정리
            os.remove(audio_file)
            return transcript
        else:
            return None
    except Exception as e:
        print(f"Audio Error: {e}")
        if os.path.exists(audio_file): os.remove(audio_file)
        return None

def get_video_content(video_id, openai_api_key, status_container):
    """자막 우선 시도 -> 실패 시 오디오 추출 (상태 메시지 업데이트 포함)"""
    
    # 1단계: 한글 자막 시도
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(['ko'])
        text_data = transcript.fetch()
        return " ".join([t['text'] for t in text_data]), "자막(KO)"
    except:
        pass # 한글 자막 없음, 다음 단계로

    # 2단계: 영어/자동 자막 번역 시도
    try:
        status_container.info("🔤 한글 자막이 없어 영어 자막을 번역 중입니다...")
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript = transcript_list.find_transcript(['en'])
        except:
            transcript = next(iter(transcript_list)) # 아무 언어나 가져옴
        
        translated_transcript = transcript.translate('ko')
        text_data = translated_transcript.fetch()
        return " ".join([t['text'] for t in text_data]), "자막(번역)"
    except:
        pass # 자막 자체가 없음, 다음 단계로

    # 3단계: 오디오 추출 (Whisper)
    status_container.warning("🎙️ 자막이 없습니다. 음성 스크립트를 추출하여 텍스트를 생성합니다. (최대 2분 소요)")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    script = transcribe_audio_with_whisper(openai_api_key, video_url)
    
    if script:
        return script, "음성추출(Whisper)"
    else:
        return None, "실패"

def analyze_with_gpt(openai_api_key, script, video_title, channel_name):
    client = OpenAI(api_key=openai_api_key)
    prompt = """
    너는 'AI 에이전트 파견 비즈니스' 전문 컨설턴트야. 
    제공된 스크립트를 분석해서 비즈니스 인사이트 5가지를 도출해줘.
    형식: 1.영상요약 2.핵심기술 3.비즈니스 아이디어 5가지 4.결론
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"채널:{channel_name}\n영상:{video_title}\n내용:\n{script[:15000]}"}
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
if 'channels' not in st.session_state:
    with st.spinner("데이터베이스 로딩 중..."):
        st.session_state['channels'] = load_channels_from_github()

# --- UI 구현 ---
st.sidebar.header("🔑 설정")

# API 키 확인 (입력창 숨김, 상태만 표시)
if "YOUTUBE_API_KEY" in st.secrets:
    youtube_api_key = st.secrets["YOUTUBE_API_KEY"]
    st.sidebar.success("✅ 유튜브 API 키값이 정상적으로 호출되었습니다.")
else:
    st.sidebar.error("유튜브 API 키 설정 필요")
    youtube_api_key = None

if "OPENAI_API_KEY" in st.secrets:
    openai_api_key = st.secrets["OPENAI_API_KEY"]
    st.sidebar.success("✅ OpenAI API 키값이 정상적으로 호출되었습니다.")
else:
    st.sidebar.error("OpenAI API 키 설정 필요")
    openai_api_key = None

if not youtube_api_key or not openai_api_key:
    st.warning("설정(Secrets)에서 API 키를 먼저 입력해주세요.")
    st.stop()

st.title("🕵️‍♂️ 유튜브 서칭 기반 AI BM 탐색기")

channel_list = st.session_state['channels']
channel_names = [f"{c['name']} ({c.get('handle', 'No Handle')})" for c in channel_list]
channel_names.append("➕ [새 채널 추가]")

st.subheader("1️⃣ 분석할 채널 선택")
selection = st.selectbox("채널 목록", channel_names)

# [새 채널 추가 로직]
if selection == "➕ [새 채널 추가]":
    st.info("유튜브 핸들(@name)을 입력하세요.")
    if len(channel_list) >= 15:
        st.error("최대 15개 제한입니다. 삭제 후 추가하세요.")
        st.write("🗑️ **채널 관리**")
        for idx, ch in enumerate(channel_list):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{ch['name']}**")
            if c2.button("삭제", key=f"del_{idx}"):
                del channel_list[idx]
                save_channels_to_github(channel_list)
                st.session_state['channels'] = channel_list
                st.rerun()
    else:
        with st.form("add_form"):
            new_handle = st.text_input("유튜브 핸들")
            if st.form_submit_button("추가"):
                cid, ctitle, chandle = get_channel_info_from_handle(youtube_api_key, new_handle)
                if cid:
                    if any(c['id'] == cid for c in channel_list):
                        st.warning("이미 있는 채널입니다.")
                    else:
                        channel_list.append({"name": ctitle, "handle": chandle, "id": cid})
                        save_channels_to_github(channel_list)
                        st.success("추가 완료!")
                        st.session_state['channels'] = channel_list
                        st.rerun()
                else: st.error("채널을 찾을 수 없습니다.")

# [기존 채널 분석 로직]
else:
    selected_idx = channel_names.index(selection)
    target_channel = channel_list[selected_idx]
    
    st.write(f"📢 **'{target_channel['name']}'** 분석 대기 중")

    with st.expander("⚙️ 채널 관리"):
        current_handle = target_channel.get('handle', '')
        with st.form("edit_form"):
            edit_handle = st.text_input("핸들 수정", value=current_handle)
            if st.form_submit_button("수정 저장"):
                cid, ctitle, chandle = get_channel_info_from_handle(youtube_api_key, edit_handle)
                if cid:
                    channel_list[selected_idx] = {"name": ctitle, "handle": chandle, "id": cid}
                    save_channels_to_github(channel_list)
                    st.success("수정 완료!")
                    st.session_state['channels'] = channel_list
                    st.rerun()
                else: st.error("유효하지 않은 핸들입니다.")
        
        st.divider()
        if st.button("삭제 ❌", type="primary"):
            del channel_list[selected_idx]
            save_channels_to_github(channel_list)
            st.session_state['channels'] = channel_list
            st.rerun()

    if st.button("🚀 분석 및 리포트 생성"):
        with st.status("분석 진행 중...", expanded=True) as status:
            st.write("🔍 최신 영상 검색 중...")
            video_info = get_recent_video(youtube_api_key, target_channel['id'])
            
            if not video_info:
                status.update(label="신규 영상 없음", state="error")
                st.warning("최근 1주일 이내 영상이 없습니다.")
            else:
                st.write(f"🎥 영상 발견: {video_info['title']}")
                st.write("📝 스크립트 추출 시도 중...")
                
                # [수정된 로직] 자막 확인 -> 번역 -> 실패시 음성 추출
                script, source_type = get_video_content(video_info['video_id'], openai_api_key, status)
                
                if not script:
                    status.update(label="실패", state="error")
                    st.error("자막이 없고, 음성 추출도 실패했습니다.")
                else:
                    st.write(f"✅ 콘텐츠 확보 완료 ({source_type}) -> AI 분석 시작")
                    insight = analyze_with_gpt(openai_api_key, script, video_info['title'], target_channel['name'])
                    status.update(label="완료!", state="complete")
                    
                    st.subheader("📊 분석 결과")
                    st.markdown(insight)
                    
                    pdf_content = f"채널: {target_channel['name']}\n영상: {video_info['title']}\n출처: {source_type}\n\n{insight}"
                    st.download_button("📥 PDF 다운로드", create_pdf(pdf_content), "report.pdf", "application/pdf")

download_font_if_not_exists()

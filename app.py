import asyncio
import aiohttp
from bs4 import BeautifulSoup
import pandas as pd
import re
import requests
from openai import AsyncOpenAI, OpenAI
import os 
from collections import OrderedDict
import json
import streamlit as st
import io
import xlsxwriter
import getpass
from dotenv import load_dotenv
from urllib.parse import urljoin
from urllib.parse import urlparse
import time
import base64
from playwright.sync_api import sync_playwright

load_dotenv(".env")
if not os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"]=getpass.getpass()
api_key = os.environ.get("OPENAI_API_KEY")

# Asynchronous Client
aclient = AsyncOpenAI(api_key=api_key)

# Keep Sync client for fallback visual verification (Playwright is sync here)
start_client = OpenAI(api_key=api_key)

st.set_page_config(layout="wide", page_title="연구보고서 온라인자료 검증도구", page_icon="assets/logo.png")

# --- UI Customization (KEI Branding) ---
KEI_BLUE = "#2a9df4"
KEI_TEAL = "#03a696"
KEI_GRAY = "#666666"

st.markdown(f"""
    <style>
        /* 1. Reset Top Spacing: Remove whitespace at the very top */
        .block-container {{
            padding-top: 1rem !important;
            padding-bottom: 2rem !important;
        }}
        header {{
            visibility: hidden; /* Hide the default Streamlit hamburger menu/header bar if desired, or just transparent */
        }}
        
        /* 2. Background Decoration */
        [data-testid="stAppViewContainer"] {{
            /* Subtle Gradient using KEI colors */
            background: linear-gradient(135deg, #f4f9fd 0%, #e0f2f1 100%);
        }}
        [data-testid="stHeader"] {{
            background-color: transparent !important;
        }}

        /* 3. Text & Content Styling */
        .stApp, .stMarkdown, p, h1, h2, h3, h4, h5, h6, span, li, div, label {{
            color: #333333 !important;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }}
        
        /* Main Header */
        h1 {{
            color: {KEI_TEAL} !important;
            font-weight: 800;
            margin-top: 0 !important;
        }}
        
        /* Buttons */
        .stButton>button {{
            background: linear-gradient(90deg, {KEI_TEAL} 0%, {KEI_BLUE} 100%);
            color: white !important;
            border: none;
            border-radius: 8px;
            font-weight: bold;
            padding: 0.6rem 1.2rem;
            transition: transform 0.1s ease;
        }}
        .stButton>button:hover {{
            transform: scale(1.02);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}

        /* Dataframe */
        [data-testid="stDataFrame"] th {{
            background-color: {KEI_TEAL} !important;
            color: white !important;
        }}
        
        /* Input Fields - White Bg for readability */
        .stTextArea textarea {{
            background-color: #ffffff !important;
            color: #333333 !important;
            border: 1px solid #ddd;
        }}
        
        /* File Uploader - White Background */
        [data-testid="stFileUploader"] section {{
            background-color: #ffffff !important;
            border: 1px solid #ddd;
        }}
        [data-testid="stFileUploader"] span {{
            color: #333333 !important;
        }}
        
        /* Status Widget -- Dark Background (Matching Input Box) */
        [data-testid="stStatusWidget"] {{
            background-color: #4a4a4a !important;
            border: 1px solid #ddd;
            border-radius: 8px; 
        }}
        [data-testid="stStatusWidget"] > div {{
            background-color: #4a4a4a !important;
            color: #ffffff !important;
        }}
        [data-testid="stStatusWidget"] label {{
            color: #ffffff !important;
            font-size: 1.2rem !important; /* Slightly larger */
        }}
        /* Status Widget Header (Chevron, etc) */
        [data-testid="stStatusWidget"] svg {{
            fill: #ffffff !important;
            color: #ffffff !important;
        }}
        
        /* Custom Result Box (for Validation Complete message) */
        .result-box {{
            background-color: #ffffff;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 15px;
            margin-top: 10px;
            color: #333333;
            font-size: 1.1rem;
            font-weight: bold;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }}

        /* Download Button - White Background (Ghost Style) to match Text Area */
        [data-testid="stBaseButton-secondary"], .stDownloadButton button {{
            background-color: #ffffff !important;
            color: {KEI_TEAL} !important;
            border: 1px solid {KEI_TEAL} !important;
        }}
        [data-testid="stBaseButton-secondary"]:hover, .stDownloadButton button:hover {{
            background-color: #f0f0f0 !important;
            border: 1px solid {KEI_BLUE} !important;
            color: {KEI_BLUE} !important;
        }}
        
        /* Top Right Toolbar (Manage App, Menu, etc.) - White Background */
        [data-testid="stToolbar"] {{
            background-color: #ffffff !important;
            border: 1px solid #ddd;
            border-radius: 8px;
            right: 2rem; 
        }}
        [data-testid="stToolbar"] button {{
            color: #333333 !important;
        }}
        /* Fix icon fill color inside toolbar if needed */
        [data-testid="stToolbar"] svg {{
            fill: #333333 !important;
            color: #333333 !important;
        }}
    </style>
""", unsafe_allow_html=True)

# Logo Placement - Top Left
if os.path.exists("assets/logo.png"):
    col1, col2 = st.columns([0.2, 0.8])
    with col1:
        st.image("assets/logo.png", width=220) 
    # Adjusting layout so Logo and Title can feel close or aligned if needed.
    # But user asked for logo at top left.

GPT_MODEL_TEXT = "gpt-5-nano"
GPT_MODEL_VISION = "gpt-5-nano"

def remove_duplicate_words(text):
    words = text.split()
    seen = OrderedDict()
    for word in words:
        if word not in seen:
            seen[word] = None
    return ' '.join(seen.keys())

def truncate_string(text, max_length=10000):
    return text[:max_length]

async def crawling_async(session, url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }
    if '.pdf' in url:
        return "error_pdf"
    
    try:
        async with session.get(url, headers=headers, ssl=False, timeout=30, allow_redirects=True) as response:
            try:
                response_text = await response.text()
            except UnicodeDecodeError:
                # Fallback to reading bytes and decoding with 'replace'
                content_bytes = await response.read()
                response_text = content_bytes.decode('utf-8', errors='replace')

            # Naive Redirect Check (Regex)
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", response_text)
            if match:
                redirect_url = match.group(1)
                if "javascript:" not in redirect_url.lower():
                    if not redirect_url.startswith("http"):
                        redirect_url = urljoin(url, redirect_url)
                    async with session.get(redirect_url, headers=headers, ssl=False, timeout=30) as response2:
                         response_text += await response2.text()

            if response.status == 200:
                soup = BeautifulSoup(response_text, 'html.parser')
                content = soup.get_text(strip=True)
                
                # Iframes (Simplified: sequential fetch for stability inside async task)
                iframes = soup.find_all('iframe')
                iframe_contents = []
                for iframe in iframes:
                    iframe_src = iframe.get('src')
                    if iframe_src and iframe_src.strip():
                        iframe_url = urljoin(url, iframe_src)
                        parsed = urlparse(iframe_url)
                        if parsed.scheme in ('http', 'https'):
                           try:
                               async with session.get(iframe_url, headers=headers, ssl=False, timeout=10) as iframe_resp:
                                   if iframe_resp.status == 200:
                                       iframe_text = await iframe_resp.text()
                                       iframe_soup = BeautifulSoup(iframe_text, 'html.parser')
                                       iframe_contents.append(iframe_soup.get_text(strip=True))
                           except:
                               pass
                
                if iframe_contents:
                    content += "\n\n" + "\n\n".join(iframe_contents)
                return content
            else:
                return "error_status"
    except Exception as e:
        # print(f"Async Crawling Error {url}: {e}")
        return "error_exception"

def screenshot_and_verify_sync(x, url):
    """
    Sync fallback using Playwright + GPT Vision.
    Kept sync because wrapping Playwright in async inside asyncio.run can be tricky with event loops.
    """
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000) 
                screenshot_bytes = page.screenshot(full_page=False)
            except Exception as e:
                browser.close()
                return "오류(접속실패)"
            browser.close()
            
            base64_image = base64.b64encode(screenshot_bytes).decode('utf-8')
            
            # Sync client call
            response = start_client.chat.completions.create(
                model=GPT_MODEL_VISION,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"정보: {x}\n위 '정보'의 내용이 아래 웹페이지 스크린샷에 포함되어 있거나 관련이 있습니까? 관련성 있으면 O, 없으면 X를 출력해주세요."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Playwright error: {e}")
            return "오류(시스템)"

async def GPTclass_async(session, x, y):
    if "확인필요" in x:
        return "O" 
    
    # 1. Async Crawl
    crawled_content = await crawling_async(session, y)
    
    # 2. Text Check
    if crawled_content not in ["error_pdf", "error_status", "error_exception"] and len(crawled_content) > 50:
        retries = 0
        while retries < 3:
            try:
                response = await aclient.chat.completions.create(
                    model=GPT_MODEL_TEXT,
                    messages=[
                        {"role": "system", "content":"[[웹자료]]에서 내용이 주어진 [[정보]] 관련내용이 대략적으로 포함되어있으면 X, 관련내용이 아니거나, 빈페이지 또는 없는 페이지면 O 출력"},
                        {"role": "user",  "content": f"[[정보]]: {x}, [[웹자료]] : {truncate_string(crawled_content)}"}
                    ]
                )
                result = response.choices[0].message.content
                if "O" in result:
                    break # Go to visual fallback
                else:
                    return result
            except Exception:
                await asyncio.sleep(1)
                retries += 1
    
    # 3. Visual Fallback (Run Sync in Thread)
    # Since Playwright is sync and blocking, we offload to a thread to not block the async loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, screenshot_and_verify_sync, x, y)
    return result

async def GPTcheck_async(doc):
    query = """
    [[문서]]는 "출처(필요시 날짜 포함), 제목(따옴표 필수), URL, 검색일 형태로 4가지 요소로 이루어져 있고 반드시 ,로 구분하되 따옴표안 ,는 무시함
    1. [[문서]] 내용이 [[예시]]의 형태로 정리되어 있는지 체크해서 오류가 있으면 O(오류이유 간략히), 없으면 X출력(4개의 요소로 구성, 콤마, 따옴표, URL 형식 등 반드시 체크) : '오류여부' 변수에 저장
    2. 출력은 반드시 JSON 포맷으로 출력해줘, 반드시 '오류여부' 변수만 존재
    
    [[예시]]
    국가법령정보센터, “물환경보전법 시행규칙”, http://www.law.go.kr/법령/물환경보전법시 행규칙, 검색일: 2018.5.3.
    """
    retries = 0
    while retries < 3:
        try:
            response = await aclient.chat.completions.create(
                model=GPT_MODEL_TEXT,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": f"{query}\n\n주의: 입력된 텍스트가 '문서:'로 시작하면 그 부분은 라벨이므로 무시하고 실제 내용만 분석할 것."},
                    {"role": "user", "content": f"{doc}"}
                ]
            )
            result = response.choices[0].message.content
            result_dict = json.loads(result)
            result_dict["원문"] = doc
            return result_dict
        except Exception:
            await asyncio.sleep(1)
            retries += 1
    return {"오류여부": "O(시스템오류)", "원문": doc}

def separator(entry):
    parts = [""] * 4
    if 'http' in entry:
        pattern_http = r',\s+(?=http)'
    else:
        pattern_http = r',\s+(?=검색일)'

    parts_http = re.split(pattern_http, entry)
    doc_info = parts_http[0]
    ref_info = parts_http[1] if len(parts_http) > 1 else ""

    pattern_doc = r'[,.] \s*(?=(?:[^"]*"[^"]*")*[^"]*$)(?=(?:[^\(]*\([^\)]*\))*[^\)]*$)(?=(?:[^“]*“[^”]*”)*[^”]*$)' 
    parts_doc = re.split(pattern_doc, doc_info)
    if len(parts_doc) == 2:
        parts[0] = parts_doc[0]
        parts[1] = parts_doc[1]
    else:
        parts[0] = parts_doc[0]

    if 'http' in ref_info:
        pattern_ref = r',\s+(?=검색일)'
        parts_ref = re.split(pattern_ref, ref_info)
        parts[2] = parts_ref[0]
        parts[3] = parts_ref[1] if len(parts_ref) > 1 else ""
    else:
        parts[3] = ref_info
    return parts

def process_entries_sync(entries):
    # This part is fast enough to be sync (Regex parsing)
    articles = []
    for entry in entries:
        note = ""
        user_display_text = entry
        
        if re.search(r'(?<!")\. (?![^"]*")', entry):
            note = "확인필요: 마침표(.) 사용 등 형식 오류 가능성"
            entry = re.sub(r'(?<!")\. (?![^"]*")', ', ', entry)
            
        check = separator(entry)
        check = ["확인필요" if item == 'NA' or item == '' else item for item in check]
        source = check[0]
        title = check[1]
        url = check[2]
        search_date = check[3].replace("검색일: ", "")
        
        articles.append({
            "source": source,
            "title": title,
            "URL": url,
            "search_date": search_date,
            "URL_오류여부": "X" if url.startswith("http") else "O", # Simple check first
            "형식체크_오류여부": note,
            "original_text": user_display_text
        })
    return pd.DataFrame(articles)

async def check_url_status_async(session, url):
    if not url.startswith("http"):
        return "O"
    try:
        async with session.get(url, ssl=False, timeout=10) as resp:
            return "X" if resp.status == 200 else "O"
    except:
        return "O"

async def task_with_progress(coro, progress_callback):
    result = await coro
    if progress_callback:
        progress_callback()
    return result

async def process_all_async(entries, result_df, progress_callback=None):
    async with aiohttp.ClientSession() as session:
        # Prepare Tasks
        format_coros = [GPTcheck_async(doc) for doc in entries]
        url_coros = [check_url_status_async(session, u) for u in result_df['URL']]
        
        queries = result_df['title'] + " + " + result_df['source']
        urls = result_df['URL']
        relevance_coros = [GPTclass_async(session, q, u) for q, u in zip(queries, urls)]
        
        # Wrap with progress
        # If callback provided, we need to know total to update? 
        # Actually simplest is callback just increments a counter.
        
        format_tasks = [task_with_progress(c, progress_callback) for c in format_coros]
        url_tasks = [task_with_progress(c, progress_callback) for c in url_coros]
        relevance_tasks = [task_with_progress(c, progress_callback) for c in relevance_coros]
        
        # Execute Concurrently
        # We gather everything. 
        # Note: We can't easily wait for one group then another if we want a global progress bar across all.
        # But we need the results separated. 
        # asyncio.gather preserves order.
        
        all_results = await asyncio.gather(*format_tasks, *url_tasks, *relevance_tasks)
        
        # Unpack results
        n_fmt = len(entries)
        n_url = len(result_df)
        
        gpt_format_results = all_results[:n_fmt]
        url_status_results = all_results[n_fmt:n_fmt+n_url]
        gpt_relevance_results = all_results[n_fmt+n_url:]
        
        return gpt_format_results, url_status_results, gpt_relevance_results

def main():
    st.title("연구보고서 온라인자료 검증도구 (v2.1 Async)")
    
    if 'text_data' not in st.session_state:
        st.session_state['text_data'] = ''
        
    uploaded_file = st.file_uploader("온라인자료 파일(txt)를 업로드 하거나", type=["txt"])
    text_data_input = st.text_area('온라인자료 텍스트를 입력하세요', st.session_state['text_data'], height=150)
    
    if st.button('검증 실행'):
        if uploaded_file or text_data_input.strip():
            if uploaded_file:
                data = uploaded_file.read().decode("utf-8")
            else:
                data = text_data_input
            st.session_state['text_data'] = data 
            
            raw_entries = data.strip().split('\n')
            entries = []
            temp_entry = []
            for line in raw_entries:
                if "검색일:" in line and temp_entry:
                    entries.append(' '.join(temp_entry))
                    temp_entry = [line]
                else:
                    temp_entry.append(line)
            if temp_entry:
                entries.append(' '.join(temp_entry))
                
            # 1. Parsing (Sync)
            result_df = process_entries_sync(entries)
            
            # 2. Async Execution
            with st.status("고속 검증 수행 중 (AsyncIO)...", expanded=True) as status:
                # Remove text message, use Progress Bar
                progress_bar = st.progress(0)
                progress_text = st.empty()
                
                start_time = time.time()
                
                # Progress Logic
                total_tasks = len(entries) * 2 + len(result_df) # Format(entries) + URL(result_df) + Content(entries/result_df matches)
                # Note: Content check count == len(result_df) usually.
                # Actually count based on lists prepared in process_all_async
                # Let's approximate: 3 tasks per entry roughly.
                
                # To be precise, we need to know the count.
                # Format: len(entries), URL: len(result_df), Relevance: len(result_df)
                total_ops = len(entries) + len(result_df) * 2
                
                completed_ops = 0
                
                def update_progress():
                    nonlocal completed_ops
                    completed_ops += 1
                    progress = min(1.0, completed_ops / total_ops)
                    progress_bar.progress(progress)
                    # progress_text.text(f"처리 중: {int(progress*100)}%")

                # Run the Async Loop
                try:
                    gpt_fmt, url_stat, gpt_rel = asyncio.run(process_all_async(entries, result_df, update_progress))
                except RuntimeError:
                    gpt_fmt, url_stat, gpt_rel = asyncio.new_event_loop().run_until_complete(process_all_async(entries, result_df, update_progress))
                
                duration = time.time() - start_time
                # Use custom styled box for completion message inside the status or after it
                st.markdown(f"""
                <div class="result-box">
                    ✅ 검증 완료! (소요시간: {duration:.2f}초)
                </div>
                """, unsafe_allow_html=True)
            
            # 3. Merging Results
            GPT_check_df = pd.DataFrame(gpt_fmt)
            
            # Logic: X=Ok, O=Error. We map this to User Terms: 
            # URL: X->정상, O->오류
            # Format: X->정상, O(reason)->오류(reason)
            # Content: X->관련, O->무관
            
            # 1. URL
            result_df['URL 상태'] = ["정상" if s == "X" else "오류" for s in url_stat]
            
            # 2. Format
            # Parsing Check (Static)
            result_df['형식체크_오류여부'] = result_df.apply(lambda row: '오류' if '확인필요' in str(row['형식체크_오류여부']) else '정상', axis=1)            
            
            # GPT Check
            def map_format_status(val):
                if val == "X": return "정상"
                if "O" in val: return val.replace("O", "오류")
                return val
            result_df['GPT 형식체크'] = GPT_check_df['오류여부'].apply(map_format_status)
            
            # 3. Content
            def map_content_status(val):
                if "X" in val: return "관련"
                if "O" in val: return "무관"
                return val # For potential error messages
            result_df['GPT 내용체크'] = [map_content_status(v) for v in gpt_rel]
            
            result_df['원문'] = GPT_check_df['원문']
            
            st.session_state['result_df'] = result_df
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Save with new column names
                save_df = result_df[['source', 'title', 'URL', 'search_date', 'URL 상태', 'GPT 형식체크', 'GPT 내용체크', '원문']]
                save_df.to_excel(writer, index=False, sheet_name='Sheet1')
            output.seek(0)
            st.session_state.processed_data = output.read()
            
        else:
            st.warning("데이터를 입력해주세요.")

    if 'result_df' in st.session_state and st.session_state['result_df'] is not None:
        st.divider()
        col1, col2 = st.columns([1, 1])
        df = st.session_state['result_df']
        
        with col1:
            st.subheader("검증 결과 요약")
            display_columns = ['title', 'URL', 'URL 상태', 'GPT 형식체크', 'GPT 내용체크']
            st.dataframe(df[display_columns])
            if 'processed_data' in st.session_state and st.session_state.processed_data:
                st.download_button(
                    label="엑셀 다운로드",
                    data=st.session_state.processed_data,
                    file_name='validation_result_v2.xlsx',
                    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                )

        with col2:
            st.subheader("원본 텍스트 검토")
            html_content = "<div style='background-color:#f9f9f9; padding:10px; border-radius:5px; height: 600px; overflow-y: scroll;'>"
            for index, row in df.iterrows():
                text = row['원문']
                is_error = False
                error_reasons = []
                
                # Check using new values
                if row['URL 상태'] == '오류':
                    is_error = True
                    error_reasons.append("URL Invalid")
                
                if '오류' in str(row['GPT 형식체크']):
                    is_error = True
                    error_reasons.append(f"Format: {str(row['GPT 형식체크'])}")
                    
                if '무관' in str(row['GPT 내용체크']):
                    is_error = True
                    msg = str(row['GPT 내용체크'])
                    error_reasons.append("Content Irrelevant" if msg == "무관" else msg)

                if is_error:
                    tooltip = " | ".join(error_reasons)
                    html_content += f"<p style='margin-bottom: 8px;'><span style='background-color: #ffdce0; color: #d8000c; padding: 2px 4px; border-radius: 3px;' title='{tooltip}'>{text}</span> <span style='font-size:0.8em; color:red;'>&#9888; {tooltip}</span></p>"
                else:
                    html_content += f"<p style='margin-bottom: 8px; color: #333;'>{text}</p>"
            html_content += "</div>"
            st.markdown(html_content, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
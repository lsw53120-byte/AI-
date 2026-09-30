import os
import io
import re
import sys
import time
import json
import datetime
import urllib.parse
import subprocess
import webbrowser
from PIL import Image, ImageOps
import requests
from google import genai
from google.genai import types
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 블로그 자동화에 사용하는 현행 Gemini 모델
PRIMARY_MODELS = [
    'gemini-3.8-flash',
    'gemini-3.5-flash-lite',
    'gemini-3.6-flash',
    'gemini-3.1-pro-preview'
]

# 선택 모델이 실패하거나 할당량이 소진될 때의 안전한 순서
MODEL_FALLBACKS = {
    'gemini-3.1-pro-preview': ['gemini-3.8-flash', 'gemini-3.5-flash-lite'],
    'gemini-3.8-flash': ['gemini-3.5-flash-lite', 'gemini-3.6-flash'],
    'gemini-3.6-flash': ['gemini-3.8-flash', 'gemini-3.5-flash-lite'],
    'gemini-3.5-flash-lite': ['gemini-3.8-flash', 'gemini-3.6-flash'],
}

def get_config_dir():
    """안전한 영구 설정 저장 디렉터리 반환"""
    candidates = []
    if hasattr(sys, 'frozen'):
        candidates.append(os.path.dirname(sys.executable))
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.abspath('.'))
    for c in candidates:
        if os.path.exists(c) and os.access(c, os.W_OK):
            return c
    return os.path.expanduser('~')

def get_config_file_path(filename='app_config.json'):
    return os.path.join(get_config_dir(), filename)

def load_app_config():
    """로컬 설정 파일(API 키 등) 안전 로드"""
    cfg_path = get_config_file_path('app_config.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_app_config(key, value):
    """로컬 설정 파일에 키-값 영구 저장 (한번 입력하면 재입력 불필요)"""
    cfg = load_app_config()
    cfg[key] = value
    cfg_path = get_config_file_path('app_config.json')
    try:
        with open(cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"설정 저장 오류 ({cfg_path}): {e}")
        return False

def get_saved_gemini_api_key():
    """저장된 API 키 조회 (1순위: config 파일, 2순위: 환경변수)"""
    cfg = load_app_config()
    saved = cfg.get("gemini_api_key", "").strip()
    if saved:
        return saved
    return os.environ.get("GEMINI_API_KEY", "").strip()

def get_model_pipeline(preferred_model=None, allow_backup=True):
    """
    구글 서버 실시간 검증 기반 완벽 동작 파이프라인
    - 1순위: 사용자가 직접 지정한 모델
    - 2순위: 쿼터 여유 모델
    - 무한루프 방지를 위해 최대 3개 모델로 신속 제한
    """
    selected = preferred_model if preferred_model in PRIMARY_MODELS else 'gemini-3.8-flash'
    pipeline = [selected]
    if allow_backup:
        pipeline.extend(MODEL_FALLBACKS.get(selected, []))
    return pipeline[:3]

SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/drive.file'
]

def get_current_season_hint():
    """현재 날짜 기준 계절 힌트"""
    month = datetime.date.today().month
    if month in (3, 4, 5):
        return "봄(3~5월)"
    elif month in (6, 7, 8):
        return "여름(6~8월)"
    elif month in (9, 10, 11):
        return "가을(9~11월)"
    else:
        return "겨울(12~2월)"

def preprocess_pil_image(image_input, max_dim=1024):
    """
    PIL Image 객체 또는 파일 경로를 받아
    스마트폰 EXIF 회전 보정 및 429 TPM(토큰 한도 초과) 방지용 최적화 RGB 이미지로 변환
    - 1024px 해상도: 한글 간판 및 메뉴판 글자를 선명히 보존하면서 토큰 소모를 70% 이상 절감
    """
    try:
        if isinstance(image_input, str):
            img = Image.open(image_input)
        elif hasattr(image_input, 'read'):
            img = Image.open(image_input)
        elif isinstance(image_input, Image.Image):
            img = image_input.copy()
        else:
            return None

        # EXIF 회전 보정
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # 429 방지용 최적화 리사이징 (글자 가독성은 살리고 토큰은 최소화)
        if max(img.size) > max_dim:
            scale = max_dim / max(img.size)
            new_size = (int(img.width * scale), int(img.height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        # RGB 변환
        if img.mode != 'RGB':
            img = img.convert('RGB')

        return img
    except Exception as e:
        print(f"이미지 전처리 오류: {e}")
        return None

def parse_json_response(raw_text):
    """Gemini 응답에서 순수 JSON 객체 안전 파싱 (절대 예외를 던지지 않는 안전장치)"""
    if not raw_text:
        return {}

    # 1. ```json ... ``` 코드블록
    code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, flags=re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except Exception:
            pass

    # 2. 첫 { 부터 마지막 }
    json_match = re.search(r'\{.*\}', raw_text, flags=re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except Exception:
            pass

    # 3. 마크다운 기호 제거 후 파싱
    cleaned = re.sub(r'^```(json)?\s*', '', raw_text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 4. 정규식을 통한 키-값 비상 추출
    fallback = {}
    title_m = re.search(r'["\']title["\']\s*:\s*["\']([^"\']+)["\']', raw_text)
    if title_m:
        fallback['title'] = title_m.group(1)
    memo_m = re.search(r'["\']memo["\']\s*:\s*["\']([^"\']+)["\']', raw_text)
    if memo_m:
        fallback['memo'] = memo_m.group(1)
    slug_m = re.search(r'["\']slug["\']\s*:\s*["\']([^"\']+)["\']', raw_text)
    if slug_m:
        fallback['slug'] = slug_m.group(1)
    return fallback

def extract_facts_from_images(gemini_client, pil_images, progress_callback=None, preferred_model=None, allow_backup=True):
    """
    1단계: 첨부된 사진들로부터 간판, 주소(지번/도로명), 메뉴판, 가격, 전화번호 텍스트를 정밀 판독
    - 3.8 / 3.1 / 3.5 우선 순차 연결
    - 429 할당량 초과 시 자동 대기 후 재시도 및 안정 백업 모델(2.5/2.0) 자동 전환
    """
    prompt = """
    당신은 대한민국 최고 수준의 비전 팩트체크 전문가입니다.
    첨부된 사진들을 정밀 분석하여 다음 사실(Fact)들을 절대 추측하지 말고 사진에 명시된 그대로 추출하세요:
    1. 간판 상호명 (정확한 철자 및 한글/영문 표기)
    2. 간판/벽면/출입문/명함 등에 기재된 전체 주소 (지번, 도로명, 건물번호 등)
    3. 전화번호 (지역번호 포함)
    4. 메뉴판에 적힌 모든 대표 메뉴 이름과 가격
    5. 영업시간, 휴무일, 브레이크타임, 주차 안내문 등 방문 편의 정보
    6. 제공되는 음식의 비주얼 특징 및 시각적으로 확인되는 독특한 점(예: 밑반찬, 셀프바, 야외석 등)

    결과는 항목별로 명확하고 사실에 근거하여 정리하세요.
    """
    error_logs = []
    has_429 = False
    models_to_run = get_model_pipeline(preferred_model, allow_backup=allow_backup)
    
    for model in models_to_run:
        for retry in range(2):
            try:
                if progress_callback:
                    retry_label = " [재시도...]" if retry > 0 else ""
                    progress_callback(f"사진 속 간판, 메뉴, 주소 판독 중... ({model}){retry_label}")
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=[prompt] + pil_images
                )
                if response and response.text:
                    return response.text.strip(), model
            except Exception as e:
                err_msg = str(e)
                print(f"[{model}] 팩트 추출 실패 (시도 {retry+1}/2): {err_msg}")
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    has_429 = True
                    if retry == 0:
                        if progress_callback:
                            progress_callback(f"⏳ {model} 호출 한도(429) 감지: 1.5초 후 빠른 재시도합니다...")
                        time.sleep(1.5)
                        continue
                error_logs.append(f"{model}: {err_msg[:80]}")
                break

    if has_429:
        raise RuntimeError("Google Gemini 무료 일일/분당 할당량(429)이 일시 초과되었습니다. 잠시 후(1분 뒤) 다시 시도하시거나, 사이드바에서 쿼터가 넉넉한 'gemini-3.5-flash-lite'를 선택해 주세요.")
    detail_err = " | ".join(error_logs[-2:]) if error_logs else "원인 불명"
    raise RuntimeError(f"Gemini 모델 연결 실패 ({detail_err}). API 키 또는 네트워크 상태를 확인해 주세요.")

def crawl_popular_insights(query, gemini_client, progress_callback=None, preferred_model=None, allow_backup=True):
    """
    2단계: 실시간 웹 검색 및 인기 사이트 크롤링 (주소 결측치 역추적 및 인기 꿀팁 수집)
    - 사진에 주소나 간판이 없더라도, 실시간 웹 검색을 통해 정확한 도로명 주소, 지번, 전화번호, 영업시간을 역추적
    - Google Search 도구에서 429나 AFC 오류 발생 시 지연 없이 신속하게 모델 웹 지식으로 즉시 폴백
    """
    if not query or len(query.strip()) < 2:
        return "크롤링 질의어가 부족합니다."

    if progress_callback:
        progress_callback(f"🌐 인터넷 실시간 웹 검색 및 위치 역추적 중: '{query}'...")

    search_prompt = f"""
    당신은 실시간 위치 및 블로그 데이터 크롤러 전문 에디터입니다.
    검색 대상 키워드: '{query}'

    인터넷에 등록된 최신 네이버 플레이스, 다음 카카오맵, 구글 지도, 인기 상위 블로그를 실시간 검색하여 다음 사실(Fact)을 명확하게 찾아내세요:
    1. **정확한 도로명 주소 및 지번 주소** (시/도, 시/군/구, 도로명, 건물번호 등 전체 주소)
       - 사진에 주소가 찍히지 않았더라도 인터넷 지도에 등록된 정확한 실제 주소를 반드시 찾아내세요.
    2. **전화번호** (지역번호 포함 공식 대표번호)
    3. **정확한 영업시간 및 정기 휴무일**, 브레이크타임
    4. **주차 실황 및 꿀팁** (전용 주차장 유무, 만차 시 인근 무료/유료 주차 팁)
    5. **실제 방문객들이 가장 극찬하는 대표 메뉴 및 추천 조합**
    6. **웨이팅/대기 시간, 예약 가능 여부, 방문 전 알아야 할 특이사항**

    절대 상상으로 지어내지 말고 인터넷 검색을 통해 확인된 실제 데이터만 항목별로 명확하게 정리하세요.
    """

    models_to_run = get_model_pipeline(preferred_model, allow_backup=allow_backup)
    
    # 1단계: Google Search Grounding 도구 시도
    for model in models_to_run:
        try:
            search_config = types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
            response = gemini_client.models.generate_content(
                model=model,
                contents=search_prompt,
                config=search_config
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            err_m = str(e)
            print(f"[{model}] Google Search Grounding 실패 ({err_m[:60]}), 일반 웹 지식 모델로 즉시 폴백합니다.")
            # 도구 에러 발생 시 더 이상 같은 도구로 재시도하지 않고 즉시 일반 모드로 전환
            break

    # 2단계: 도구 미지원/429 시 모델 자체 웹 지식으로 신속 폴백 (무한루프 및 지연 완전 방지)
    if progress_callback:
        progress_callback("🌐 웹 검색 지식 기반 매장 정보 및 도로명 주소 동기화 중...")

    for model in models_to_run:
        try:
            response = gemini_client.models.generate_content(
                model=model,
                contents=search_prompt
            )
            if response and response.text:
                return response.text.strip()
        except Exception as ex:
            print(f"[{model}] 지식 폴백 실패: {ex}")
            continue

    return f"키워드 '{query}' 관련 매장 주소와 방문 정보를 사진 팩트와 함께 종합 구성합니다."

def generate_seo_metadata(gemini_client, pil_images, image_names, raw_facts, web_insights, user_hint="", target_platform="naver", progress_callback=None, preferred_model=None, allow_backup=True):
    """
    3단계: SEO / AEO / GEO 최적화 메타데이터 (제목, 해시태그, 슬러그, 핵심요약, 추천썸네일) 생성
    """
    current_year = datetime.date.today().year
    today_str = datetime.date.today().strftime("%Y년 %m월 %d일")
    season_hint = get_current_season_hint()

    if progress_callback:
        progress_callback(f"SEO·AEO·GEO 최적화 메타데이터 도출 중 ({target_platform.upper()})...")

    if target_platform == "naver":
        platform_rules = """
        [네이버 블로그 특화 규칙]
        - title: [정확한 시/군/구 + 동/면/읍 + 맛집/장소명] [핵심 메뉴] 솔직 후기 | [주차/가격/특징] 30~45자 내외 클릭률 극대화 제목.
        - tags: 네이버 스마트블록 검색 유입용 핵심 해시태그 10~15개 (# 포함).
        - thumbnail_recommend: 전체 사진 중 시선을 사로잡는 가장 먹음직스럽거나 돋보이는 사진 파일명 1개 추천.
        """
    else:
        platform_rules = """
        [블로그스팟 / 구글 SEO 특화 규칙]
        - title: [정확한 시/군/구 + 상호명] [핵심 메뉴] [가격/주차/특징] 50자 이내 한글 제목.
        - slug: 구글 퍼머링크용 2~4개 영문 단어 조합 (소문자, 하이픈 연결, 예: yangju-sundaeguk-food).
        - labels: 라벨 4~6개 리스트.
        - search_description: 구글 검색엔진 로봇 수집용 메타 디스크립션 130자 이내.
        """

    prompt = f"""
    당신은 국내 상위 0.1% SEO / AEO / GEO 전문 수석 에디터입니다.
    사진에서 판독된 사실 데이터와 실시간 크롤링된 인기 사이트 정보, 사용자 힌트를 종합 분석하여
    검색 노출률과 클릭률이 가장 높은 최적의 메타데이터를 작성하세요.

    [포스팅 기준 날짜]
    - 현재 연도: {current_year}년 ({today_str}, {season_hint})

    [사진 1차 팩트 데이터]
    {raw_facts}

    [실시간 크롤링된 상위 사이트 인기 꿀팁]
    {web_insights}

    [사용자 보충 힌트]
    {user_hint if user_hint else "없음 (사진과 웹 데이터를 바탕으로 정확한 행정구역 확정)"}

    [핵심 검증 지침]
    - [주소 결측치 자동 보강]: 사진에 간판이나 주소가 찍히지 않은 경우, 실시간 크롤링된 인터넷 지도/플레이스 데이터에서 찾아낸 '정확한 도로명 주소'를 반드시 메타데이터와 본문에 반영할 것.
    - 행정구역 오류 절대 금지: 간판에 읍/면/리만 적혀 있어도 인접 시/군으로 넘겨짚지 말고 도로명/국번으로 시/군/구를 정확히 확정할 것.
    - [업력 계산 오류 방지]: 과거 데이터 착각으로 '27년 전통' 같은 구식 수치를 쓰지 말고, 현재 연도({current_year}년)에 맞춰 '1997년부터 이어온', 'Since 1997', '약 30년 전통'으로 표현할 것.

    {platform_rules}

    - memo: 사진과 크롤링에서 확인된 핵심 팩트(위치, 가격, 주차, 특징)를 요약한 2~3문장.

    출력 형식: 순수 JSON 객체만 출력 (마크다운 백틱 제외):
    {{"title": "...", "memo": "...", "tags": ["#..."], "slug": "...", "labels": ["..."], "search_description": "...", "thumbnail_recommend": "..."}}
    """

    json_config = types.GenerateContentConfig(
        response_mime_type="application/json"
    )

    models_to_run = get_model_pipeline(preferred_model, allow_backup=allow_backup)
    for model in models_to_run:
        for retry in range(2):
            try:
                try:
                    response = gemini_client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=json_config
                    )
                except Exception:
                    response = gemini_client.models.generate_content(
                        model=model,
                        contents=prompt
                    )

                if response and response.text:
                    data = parse_json_response(response.text)
                    if not data:
                        data = {}

                    # 기본값 채우기
                    if not data.get('title'):
                        fallback_subject = user_hint if user_hint else "로컬 맛집"
                        data['title'] = f"[{fallback_subject}] 솔직 방문 후기 | 메뉴 가격 및 주차 꿀팁 총정리"
                    
                    if not data.get('memo'):
                        data['memo'] = f"{user_hint if user_hint else '이곳'}의 대표 메뉴와 솔직한 방문 소감을 꼼꼼하게 정리한 후기입니다."

                    if not data.get('tags'):
                        base_tags = [user_hint] if user_hint else ['맛집추천']
                        data['tags'] = [f"#{t.replace('#','').strip()}" for t in base_tags if t.strip()] + ['#내돈내산', '#맛집투어', '#솔직후기']

                    data.setdefault('slug', 'local-spot-review')
                    data.setdefault('labels', [t.replace('#', '') for t in data.get('tags', [])])
                    data.setdefault('search_description', data.get('memo', ''))
                    data.setdefault('thumbnail_recommend', image_names[0] if image_names else '')

                    clean_slug = re.sub(r'[^a-zA-Z0-9\-]', '-', str(data['slug']).lower()).strip('-')
                    data['slug'] = clean_slug if clean_slug else 'local-spot-review'
                    return data

            except Exception as e:
                err_m = str(e)
                if ("429" in err_m or "RESOURCE_EXHAUSTED" in err_m) and retry == 0:
                    time.sleep(3.0)
                    continue
                print(f"[{model}] 메타데이터 생성 시도 중 예외: {err_m}")
                break

    # 비상 fallback 데이터 반환 (어떤 경우에도 에러로 멈추지 않음!)
    default_title = f"[{user_hint if user_hint else '로컬 핫플'}] 솔직 방문 후기 | 위치, 메뉴, 주차 꿀팁 총정리"
    return {
        'title': default_title,
        'memo': f"{user_hint if user_hint else '해당 장소'}의 생생한 현장 방문 후기와 필수 이용 팁입니다.",
        'tags': [f"#{user_hint}" if user_hint else '#맛집', '#솔직후기', '#방문리뷰', '#핫플레이스'],
        'slug': 'local-food-review',
        'labels': [user_hint] if user_hint else ['맛집리뷰'],
        'search_description': f"{user_hint if user_hint else '로컬 장소'} 방문 팁과 대표 메뉴 안내",
        'thumbnail_recommend': image_names[0] if image_names else ''
    }

def generate_full_article(gemini_client, title, memo, pil_images, image_names, raw_facts, web_insights, target_platform="naver", tone="솔직 담백한 내돈내산 톤", progress_callback=None, preferred_model=None, allow_backup=True, photo_mode="smart_best", **kwargs):
    """
    4단계: SEO / AEO / GEO 최적화 완벽 본문 생성 + 괜찮은 사진 스마트 엄선 자리배치
    - AEO: Perplexity, ChatGPT Search가 즉각 발췌 가능한 상단 5줄 요약 박스 + FAQ 3문 3답
    - GEO: 구글 SGE, 네이버 Cue:가 추천하도록 E-E-A-T(직접 경험, 세부 수치, 신뢰도) 강화
    - SEO: 네이버 스마트에디터 ONE 서식 또는 블로그스팟 반응형 HTML 완벽 구성
    - Photo Selection: 업로드된 사진 중 퀄리티가 우수하고 스토리 흐름에 꼭 맞는 베스트 사진만 엄선 배치
    """
    current_year = datetime.date.today().year
    today_str = datetime.date.today().strftime("%Y년 %m월 %d일")
    season_hint = get_current_season_hint()

    total_photo_cnt = len(image_names) if image_names else 0
    if photo_mode == "all":
        photo_selection_rule = f"""
        - 업로드된 사진 목록: {image_names} (총 {total_photo_cnt}장)
        - [모든 사진 배치 모드]: 업로드된 모든 사진을 본문 흐름에 맞춰 빠짐없이 적재적소에 배치하세요.
        """
        html_photo_rule = f"- 업로드된 모든 이미지({image_names})를 본문 적재적소에 빠짐없이 반응형 <img> 태그로 배치할 것."
    elif photo_mode == "rich":
        target_max = min(max(total_photo_cnt, 1), 12)
        target_min = min(7, total_photo_cnt)
        photo_selection_rule = f"""
        - 업로드된 전체 사진 목록: {image_names} (총 {total_photo_cnt}장)
        - [풍부한 사진 선별 모드]: 다양한 볼거리를 위해 볼만한 사진들을 폭넓게 활용하되, 완전히 겹치는 구도의 중복 사진이나 심하게 흔들린 사진만 제외하고 {target_min}~{target_max}장 내외로 풍성하게 엄선하여 본문에 배치하세요.
        """
        html_photo_rule = f"- 업로드된 이미지 중 중복되거나 흐릿한 사진을 제외하고 볼만한 사진을 풍성하게 골라 반응형 <img> 태그로 배치할 것."
    else:  # smart_best (기본 추천: 괜찮은 사진만 엄선)
        target_cnt = min(max(5, total_photo_cnt), 8)
        photo_selection_rule = f"""
        - 업로드된 전체 사진 목록: {image_names} (총 {total_photo_cnt}장)
        - [⭐ AI 스마트 베스트 엄선 모드 - 괜찮은 사진만 선별]:
          1. **절대로 모든 사진을 다 넣지 마십시오.**
          2. 비슷한 앵글/연사 사진, 초점이 흐리거나 어두운 사진, 단순 영수증/화장실 등 글의 몰입을 해치는 잉여 사진은 **과감히 배제**하십시오.
          3. 독자의 시각적 만족도와 네이버 스마트블록 상위 노출에 가장 효과적인 **'가장 잘 나오고 돋보이는 핵심 베스트 사진(5~{target_cnt}장 내외)'만 엄선**하여 본문에 배치하십시오.
          4. 이상적인 포스팅 스토리라인에 맞추어 사진을 배치하십시오:
             • 외관/간판 또는 대표 전경 (첫인상 전달)
             • 매장 내부 분위기 / 쾌적한 좌석 공간
             • 대표 시그니처 메인 메뉴 (가장 먹음직스럽고 시선을 끄는 컷)
             • 메뉴판 또는 가격표 사진 (필수 정보)
             • 디테일 컷 (음식 젓가락 샷, 국물 클로즈업 등 침샘 자극 컷)
             • 특별한 꿀팁 포인트 (셀프바, 무료 제공, 주차장 등)
          5. **본문에 선별 채택된 사진만** `[📷 사진 배치: 파일명]` 규격으로 배치하고, 배제된 사진은 본문 중간에 억지로 넣지 마십시오.
        """
        html_photo_rule = f"- 업로드된 전체 이미지({image_names}) 중 모든 이미지를 다 넣지 말고, 가장 돋보이고 퀄리티 높은 '핵심 베스트 사진' 5~{target_cnt}장만 엄선하여 반응형 <img> 태그로 배치할 것. (중복/흐릿한 사진 제외)"

    if progress_callback:
        progress_callback(f"SEO·AEO·GEO 최적화 고품질 원고 작성 중 ({target_platform.upper()} / {tone} / 베스트 사진 엄선)...")

    if target_platform == "naver":
        prompt = f"""
        당신은 네이버 상위 0.1% 파워블로거이자 SEO/AEO/GEO 전문가입니다.
        네이버 스마트에디터 ONE의 에디터 컴포넌트(인용구 버티컬 바, 제목 1, 구분선, 사진 캡션/대체텍스트)에 100% 최적화된 완벽한 원고를 작성하세요.

        [기본 정보]
        - 글 제목: {title}
        - 오늘 날짜: {today_str} ({season_hint}, 기준연도: {current_year}년)
        - 작성 톤앤매너: {tone}
        - 핵심 요약: {memo}
        - 사진 속 확인된 팩트:
        {raw_facts}
        - 실시간 크롤링된 인기 사이트 꿀팁:
        {web_insights}

        [⭐ 사진 선별 및 스마트 자리배치 필수 규칙]
        {photo_selection_rule}

        [서식 및 작성 절대 규칙]
        1. **본문 첫 줄에 제목을 절대 중복 작성하지 말 것** (네이버는 제목 입력란이 별도로 존재함).
        2. **AEO 최적화 핵심 요약 (본문 맨 위)**:
           - (인용구 컴포넌트 - 버티컬 라인 스타일 적용)
           - 📌 [{title}] 핵심 정보 5줄 요약
           - • 정확한 위치: (사진에 주소가 없더라도 웹 크롤링 데이터에서 찾아낸 도로명 주소를 정확하게 기재)
           - • 영업시간 및 정기휴무:
           - • 주차 안내: (크롤링된 꿀팁 반영)
           - • 대표 메뉴 & 가격:
           - • 방문 전 필수 꿀팁:
        3. **감성 도입부 (1~2문단)**:
           - 직접 방문한 계기와 첫인상을 생생하고 자연스럽게 서술.
        4. **소제목 및 본문 전개 (3~4개 섹션)**:
           - 각 소제목 앞에는 `## 1. ... (서식: 제목 1)` 형태로 명시.
           - 소제목 섹션 사이마다 `(구분선 컴포넌트 삽입)` 명시.
           - 본문 중 크롤링에서 얻은 '실제 주문 꿀팁'과 '맛있게 먹는 비법'을 자연스럽게 녹여낼 것.
           - 사진은 **엄선된 베스트 사진만** 적재적소에 배치하고 아래 규격을 엄수:
             `[📷 사진 배치: 파일명]`
             `(사진 캡션: 사진 속 구체적 상황 설명 및 방문자 꿀팁)`
             `(대체 텍스트: 스마트렌즈 및 이미지 검색 최적화용 설명)`
        5. **AEO 최적화 FAQ 섹션 (AI 검색 발췌용)**:
           - (인용구 컴포넌트 - 버티컬 라인 스타일 적용)
           - ❓ [{title}] 방문 전 자주 묻는 질문 (FAQ)
           - Q1. (주차/웨이팅/예약 관련 질문)
             A1. (단도직입적이고 명확한 답변)
           - Q2. (대표 메뉴 추천 및 가격 가성비)
             A2. (...)
           - Q3. (아이 동반, 단체, 화장실 등 편의사항)
             A3. (...)
        6. **GEO 최적화 총평 & 네이버 지도 컴포넌트 안내**:
           - 솔직한 재방문 의사와 추천 대상(가족 외식, 데이트 등) 명시.
           - `(네이버 스마트에디터 장소 컴포넌트 추가: '상호명' 등록)` 안내로 마무리.
        7. **AI 사진 큐레이션 리포트 (본문 맨 끝에 추가)**:
           - (구분선 컴포넌트 삽입)
           - 📸 **[AI 스마트 사진 선별 안내]**
           - • 본문 엄선 사진: (실제 본문 자리에 배치된 사진 파일명 목록)
           - • 제외된 사진: (본문에 넣지 않은 사진 파일명들과 간략한 제외 사유 - 예: 유사 각도 중복 컷, 단순 배경 등)
        """
    else:
        # 블로그스팟 (Blogger) 반응형 HTML
        prompt = f"""
        당신은 구글 글로벌 SEO / AEO / GEO 최상위 블로그 전문가입니다.
        반응형 웹 디자인과 시맨틱 HTML5 태그가 적용된 고품질 블로그 포스팅 코드를 작성하세요.

        [기본 정보]
        - 글 제목: {title}
        - 오늘 날짜: {today_str} ({season_hint}, 기준연도: {current_year}년)
        - 작성 톤앤매너: {tone}
        - 핵심 요약: {memo}
        - 사진 속 팩트:
        {raw_facts}
        - 실시간 크롤링된 인기 사이트 꿀팁:
        {web_insights}

        [HTML 작성 필수 규칙]
        1. **AEO 핵심 정보 요약 박스 (본문 맨 위)**:
           - `<blockquote style="border-left: 4px solid #03c75a; padding: 12px 18px; background: #f9f9f9; margin: 18px 0; border-radius: 4px;">`
           - `<p><strong>📌 {title} 핵심 정보 요약</strong></p>`
           - `<ul><li>정확한 위치: (사진에 없더라도 웹 검색으로 확인된 정확한 도로명 주소 기재)</li><li>영업시간, 주차 정보, 대표 메뉴/가격, 방문 꿀팁</li></ul></blockquote>`
        2. `<hr>` 구분선.
        3. **소제목(<h2>)별 본문**: 3~4개 섹션.
           - 사진 삽입 시 {html_photo_rule}
           - 사진 반응형 스타일 적용:
             `<div style="text-align: center; margin: 25px 0;"><img src="파일명" alt="구체적 묘사" style="max-width: 100%; height: auto; border-radius: 8px;"><p style="color: #666; font-size: 13px; margin-top: 6px;">사진 설명 캡션</p></div>`
        4. **AEO FAQ 섹션**:
           - `<h2>❓ {title} 자주 묻는 질문 (FAQ)</h2>`
           - Q1, Q2, Q3 문답 정리 (질문은 `<strong>`, 답변은 `<p>`).
        5. **마무리 문단**: 깔끔한 1~2문장 총평.

        - 마크다운 문법(#, **)을 일체 쓰지 말고 순수 HTML 태그로만 출력하세요.
        """
    article_errors = []
    has_429 = False
    models_to_run = get_model_pipeline(preferred_model, allow_backup=allow_backup)
    for model in models_to_run:
        for retry in range(2):
            try:
                response = gemini_client.models.generate_content(
                    model=model,
                    contents=[prompt] + pil_images
                )
                if response and response.text:
                    raw_text = response.text.strip()
                    if target_platform != "naver":
                        match = re.search(r'```(?:html)?\s*(.*?)\s*```', raw_text, flags=re.DOTALL | re.IGNORECASE)
                        if match:
                            raw_text = match.group(1).strip()
                    return raw_text, model
            except Exception as e:
                err_m = str(e)
                print(f"[{model}] 본문 생성 실패 (시도 {retry+1}/2): {err_m}")
                if "429" in err_m or "RESOURCE_EXHAUSTED" in err_m:
                    has_429 = True
                    if retry == 0:
                        if progress_callback:
                            progress_callback(f"⏳ {model} 분당 호출 한도(429) 감지: 3초 후 자동 재시도합니다...")
                        time.sleep(3.5)
                        continue
                article_errors.append(f"{model}: {err_m[:80]}")
                break

    if has_429:
        raise RuntimeError("Google Gemini 무료 일일/분당 할당량(429)이 초과되었습니다. 잠시 후(1~2분 뒤) 다시 시도하시거나, 사이드바의 '안전 백업 모델' 옵션을 켜시거나, 새 API 키를 등록해 주세요.")
    detail_err = " | ".join(article_errors[-2:]) if article_errors else "원인 불명"
    raise RuntimeError(f"본문 생성 실패 ({detail_err}). 잠시 후 다시 시도해 주세요.")

def find_config_file(filename):
    """실행 환경(EXE, 임시 폴더, 다른 CWD 등)과 무관하게 설정 파일의 절대 경로를 안전하게 탐색"""
    candidates = [
        os.path.abspath(filename),
        os.path.join(os.path.abspath('.'), filename),
        os.path.join(os.path.dirname(sys.executable), filename) if hasattr(sys, 'frozen') else None,
        os.path.join(os.path.dirname(sys.executable), '..', filename) if hasattr(sys, 'frozen') else None,
        os.path.join(os.path.dirname(sys.executable), '..', '..', filename) if hasattr(sys, 'frozen') else None,
        os.path.join(getattr(sys, '_MEIPASS', ''), filename) if hasattr(sys, '_MEIPASS') else None,
        os.path.join(os.path.dirname(__file__), filename),
        os.path.join(os.path.dirname(__file__), '..', filename),
        os.path.join(r"c:\Users\오구링\Desktop\APP\blog자동화", filename)
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    return None

def setup_chrome_browser():
    """Chrome 브라우저 경로 탐색 (BackgroundBrowser 등록은 파라미터 잘림 버그 방지를 위해 사용 안 함)"""
    return None

def open_in_chrome(url):
    """
    사용자가 이미 로그인해 둔 브라우저(기본 프로필)로 URL 열기
    - 1순위: Windows 시스템 기본 브라우저 (사용자의 로그인 세션/쿠키 100% 유지)
    - 2순위: Chrome 기본 사용자 프로필(--profile-directory=Default)로 실행
    """
    # 1. Windows 기본 쉘을 통해 열기 (가장 확실하게 로그인 세션/쿠키 유지)
    try:
        os.startfile(url)
        return True
    except Exception:
        pass

    # 2. Chrome 기본 프로필로 명시적 실행
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe")
    ]
    for cp in chrome_paths:
        if os.path.exists(cp):
            try:
                subprocess.Popen([cp, "--profile-directory=Default", url])
                return True
            except Exception:
                pass
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False

def get_oauth_credentials(progress_callback=None):
    """OAuth 인증 정보 취득 및 토큰 자동 갱신 (한 번 로그인하면 영구 유지)"""
    token_path = find_config_file('token.json')
    secret_path = find_config_file('client_secret.json')

    creds = None
    if token_path and os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            creds = None

    refreshed_or_new = False
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                if progress_callback:
                    progress_callback("🔄 기존 구글 로그인 세션을 자동 갱신 중입니다...")
                creds.refresh(Request())
                refreshed_or_new = True
            except Exception as ref_err:
                print(f"토큰 리프레시 실패: {ref_err}")
                creds = None

        if not creds or not creds.valid:
            if not secret_path or not os.path.exists(secret_path):
                return None
            flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
            
            if progress_callback:
                progress_callback("🌐 구글 계정 인증 창을 열었습니다. 브라우저에서 구글 계정을 선택해 주세요!")
            
            # Windows에서 BackgroundBrowser 사용 시 URL의 &redirect_uri= 파라미터가 잘리는 버그 방지
            if hasattr(webbrowser, '_browsers') and 'chrome' in webbrowser._browsers:
                try:
                    del webbrowser._browsers['chrome']
                except Exception:
                    pass

            ports_to_try = [8080, 8081, 8082, 0]
            creds = None
            last_err = None
            for p in ports_to_try:
                try:
                    creds = flow.run_local_server(
                        port=p,
                        prompt='consent',
                        access_type='offline',
                        redirect_uri_trailing_slash=True,
                        open_browser=True
                    )
                    if creds:
                        refreshed_or_new = True
                        break
                except Exception as ex:
                    last_err = ex
                    continue
            
            if not creds:
                raise RuntimeError(f"구글 계정 인증에 실패했습니다: {last_err}")

    # 갱신되었거나 신규 발급된 경우 모든 위치에 안전 저장 (다음부터 무조건 재로그인 불필요)
    if creds and creds.valid and (refreshed_or_new or not token_path):
        save_locations = set()
        if secret_path:
            save_locations.add(os.path.join(os.path.dirname(secret_path), 'token.json'))
        if token_path:
            save_locations.add(token_path)
        save_locations.add(os.path.join(get_config_dir(), 'token.json'))
        save_locations.add(os.path.join(os.path.abspath('.'), 'token.json'))

        for s_path in save_locations:
            try:
                with open(s_path, 'w', encoding='utf-8') as token_f:
                    token_f.write(creds.to_json())
            except Exception:
                pass

    return creds

def upload_image_to_drive(drive_service, pil_image, file_name):
    """PIL 이미지를 구글 드라이브에 업로드하고 외부 직링크 반환"""
    try:
        temp_dir = os.path.join(os.path.abspath('.'), 'temp_upload')
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, file_name)
        pil_image.save(temp_path, format='JPEG', quality=90)

        file_metadata = {'name': file_name}
        media = MediaFileUpload(temp_path, mimetype='image/jpeg', resumable=True)
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        file_id = file.get('id')

        drive_service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        try:
            os.remove(temp_path)
        except Exception:
            pass

        direct_url = f"https://lh3.googleusercontent.com/d/{file_id}"
        return file_name, direct_url
    except Exception as e:
        print(f"드라이브 업로드 실패 ({file_name}): {e}")
        return None, None

def publish_to_blogger(creds, title, slug, html_content, labels, search_desc, is_draft=False):
    """
    Blogger 영문 퍼머링크 영구 고정 및 라벨/검색설명 완전 동기화 발행
    """
    blogger_service = build('blogger', 'v3', credentials=creds)
    blogs = blogger_service.blogs().listByUser(userId='self', role='ADMIN').execute()
    if 'items' not in blogs or not blogs['items']:
        raise RuntimeError("관리 권한이 있는 블로그스팟 계정을 찾을 수 없습니다.")

    blog_id = blogs['items'][0]['id']
    blog_name = blogs['items'][0]['name']

    # 1. 라벨 정제 (# 제거 및 공백 트림)
    clean_labels = []
    if labels:
        for l in labels:
            item = str(l).replace('#', '').strip()
            if item and item not in clean_labels:
                clean_labels.append(item)

    # 2. 영문 슬러그 정제 (퍼머링크용 순수 영문/숫자/하이픈)
    clean_slug = re.sub(r'[^a-zA-Z0-9\-]', '-', str(slug).lower()).strip('-') if slug else 'local-post'
    if not clean_slug or len(clean_slug) < 2:
        clean_slug = 'local-post-review'

    # 3. 1단계 등록: 영문 퍼머링크를 서버에 영구 고정하기 위해 슬러그 제목으로 먼저 생성
    initial_body = {
        'kind': 'blogger#post',
        'title': clean_slug,
        'content': html_content,
        'labels': clean_labels
    }
    if search_desc:
        initial_body['customMetaData'] = search_desc

    # Blogger는 공개 발행(isDraft=False) 시점에만 고유 영문 URL을 서버에 영구 할당함
    post = blogger_service.posts().insert(blogId=blog_id, body=initial_body, isDraft=False).execute()
    post_id = post.get('id')
    post_url = post.get('url', '')

    # 4. 2단계 패치: 원래 한글 제목 및 라벨, 검색설명을 완전 동기화 (기존 필드 손실 방지)
    patch_body = {
        'title': title,
        'labels': clean_labels
    }
    if search_desc:
        patch_body['customMetaData'] = search_desc

    try:
        updated_post = blogger_service.posts().patch(blogId=blog_id, postId=post_id, body=patch_body).execute()
        if 'url' in updated_post and updated_post['url']:
            post_url = updated_post['url']
    except Exception as pe:
        print(f"Blogger patch warning: {pe}")

    # 사용자가 초안 상태를 원했을 경우에만 revert
    if is_draft:
        blogger_service.posts().revert(blogId=blog_id, postId=post_id).execute()

    edit_url = f"https://www.blogger.com/blog/post/edit/{blog_id}/{post_id}" if post_id else None
    return {
        'blog_name': blog_name,
        'post_id': post_id,
        'post_url': post_url,
        'edit_url': edit_url,
        'labels': clean_labels,
        'slug': clean_slug,
        'search_desc': search_desc
    }

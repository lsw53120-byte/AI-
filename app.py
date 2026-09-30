import os
import sys
import re
import io
import webbrowser
import streamlit as st
from PIL import Image
import pyperclip
from google import genai
import core_engine

# PyInstaller 패키징 환경(exe) 등에서 구버전 번들 PYZ 캐시 대신 디스크의 최신 core_engine.py를 항상 우선 로드
import importlib.util
def _load_latest_core_engine():
    candidate_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core_engine.py'),
        os.path.join(os.path.abspath('.'), '_internal', 'core_engine.py'),
        os.path.join(os.path.abspath('.'), 'core_engine.py'),
        os.path.join(getattr(sys, '_MEIPASS', ''), 'core_engine.py') if hasattr(sys, '_MEIPASS') else ''
    ]
    for cp in candidate_paths:
        if cp and os.path.isfile(cp):
            try:
                spec = importlib.util.spec_from_file_location("core_engine", cp)
                if spec and spec.loader:
                    reloaded_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(reloaded_mod)
                    return reloaded_mod
            except Exception:
                pass
    return None

_disk_core = _load_latest_core_engine()
if _disk_core:
    core_engine = _disk_core
    sys.modules["core_engine"] = _disk_core

# 안전 폴백(Fallback) 보장
if not hasattr(core_engine, 'get_saved_gemini_api_key'):
    def _fallback_get_key():
        return os.environ.get("GEMINI_API_KEY", "").strip()
    core_engine.get_saved_gemini_api_key = _fallback_get_key

if not hasattr(core_engine, 'save_app_config'):
    def _fallback_save_config(k, v):
        return False
    core_engine.save_app_config = _fallback_save_config


# 페이지 기본 설정
st.set_page_config(
    page_title="AI 블로그 오토 스튜디오 (SEO·AEO·GEO)",
    page_icon="✍️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 모던하고 깔끔한 커스텀 스타일 주입
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@400;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
    }
    .main-header {
        padding: 1.2rem 1.5rem;
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border-radius: 12px;
        color: white;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .main-header h1 {
        font-size: 1.8rem;
        font-weight: 700;
        margin-bottom: 0.3rem;
        color: #ffffff;
    }
    .main-header p {
        color: #94a3b8;
        font-size: 0.95rem;
        margin: 0;
    }
    .badge {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        font-size: 0.75rem;
        font-weight: 600;
        border-radius: 6px;
        margin-right: 0.4rem;
    }
    .badge-seo { background-color: #03c75a; color: white; }
    .badge-gemini { background-color: #3b82f6; color: white; }
    .badge-crawl { background-color: #f59e0b; color: white; }
    
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        transform: translateY(-1px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .action-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.2rem;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# 헤더 영역
st.markdown("""
<div class="main-header">
    <h1>✍️ AI 블로그 오토 스튜디오 Pro</h1>
    <p>
        <span class="badge badge-gemini">Gemini 3.8 Flash + 3.1 Pro</span>
        <span class="badge badge-seo">SEO · AEO · GEO 최적화</span>
        <span class="badge badge-crawl">인기 사이트 실시간 크롤링</span>
        사진만 올리면 상위 노출 원고와 메타데이터가 한 번에 완성됩니다.
    </p>
</div>
""", unsafe_allow_html=True)

# ----------------- 사이드바 설정 -----------------
with st.sidebar:
    st.header("⚙️ 환경 설정")
    
    # API 키 관리 (한 번 입력하면 영구 저장되어 재입력 불필요)
    saved_key = core_engine.get_saved_gemini_api_key()
    api_key_input = st.text_input(
        "Gemini API 키",
        value=st.session_state.get("gemini_api_key", saved_key),
        type="password",
        help="Google AI Studio에서 발급받은 Gemini API 키를 입력하세요. 한 번 입력하면 다음 실행 시에도 자동 유지됩니다."
    )
    if api_key_input:
        cleaned_key = api_key_input.strip()
        st.session_state["gemini_api_key"] = cleaned_key
        # 변경 또는 신규 시 영구 저장
        if cleaned_key != saved_key:
            core_engine.save_app_config("gemini_api_key", cleaned_key)
        st.success("✅ API 키가 등록되었습니다 (다음 실행 시 자동 유지)")
    else:
        st.warning("⚠️ API 키가 필요합니다.")
        st.markdown("[👉 Google AI Studio에서 무료 발급받기](https://aistudio.google.com/app/apikey)")

    st.markdown("---")
    
    # 톤앤매너 선택
    st.subheader("🎨 글 작성 톤앤매너")
    tone_option = st.selectbox(
        "원하는 글쓰기 스타일",
        [
            "솔직 담백한 내돈내산 후기 톤 (신뢰도 최상)",
            "전문 미식/여행 블로거 톤 (디테일·정보성)",
            "트렌디한 인스타 감성 핫플 톤 (생생함)",
            "핵심만 쏙쏙 꿀팁 정보형 톤 (가독성 최우선)"
        ],
        index=0
    )

    st.markdown("---")
    
    st.subheader("🤖 AI 품질 모드")
    model_profiles = {
        "⚖️ 기본 추천 · 품질과 속도 균형": {
            "analysis": "gemini-3.5-flash-lite",
            "writing": "gemini-3.8-flash",
        },
        "💎 최고품질 Pro · 최종 원고만 3.1 Pro": {
            "analysis": "gemini-3.8-flash",
            "writing": "gemini-3.1-pro-preview",
        },
        "⚡ 절약 모드 · 빠르고 저렴한 대량 작성": {
            "analysis": "gemini-3.5-flash-lite",
            "writing": "gemini-3.5-flash-lite",
        },
    }
    selected_profile = st.selectbox(
        "작성 방식",
        options=list(model_profiles.keys()),
        index=0,
        help="Pro 모드는 사진 판독에 Flash를 사용하고, 제목·메타데이터·최종 본문만 Gemini 3.1 Pro Preview로 작성합니다."
    )
    selected_models = model_profiles[selected_profile]
    analysis_model = selected_models["analysis"]
    writing_model = selected_models["writing"]
    allow_backup = st.checkbox(
        "할당량(429) 초과 시 안전 모델 자동 전환",
        value=True,
        help="선택한 모델을 사용할 수 없으면 3.8 Flash, 3.5 Flash-Lite, 3.6 Flash 중 사용 가능한 모델로 이어서 작성합니다."
    )
    if writing_model == "gemini-3.1-pro-preview":
        st.caption("💳 Pro 모드는 유료 API 결제 설정이 필요하며 Preview 모델입니다.")
    else:
        st.caption(f"✅ 분석: {analysis_model} · 원고: {writing_model}")

    st.markdown("---")
    st.caption("v3.2 | Gemini 혼합 모델 · 네이버 블로그 & Blogger 자동화")

# 세션 상태 초기화
if "processed_data" not in st.session_state:
    st.session_state["processed_data"] = {}

# ----------------- 메인 탭 구성 -----------------
tab_naver, tab_blogger = st.tabs(["🟢 네이버 블로그 (스마트에디터 ONE)", "🌐 구글 블로그스팟 (Blogger)"])

def render_platform_studio(platform_type="naver"):
    st.markdown("### 1. 📷 사진 업로드 (마우스 드래그 & 드롭)")
    uploaded_files = st.file_uploader(
        f"방문 사진들을 한 번에 올려주세요 (간판, 주소, 메뉴판, 음식 사진 포함 추천)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=f"uploader_{platform_type}"
    )

    pil_images = []
    image_names = []

    if uploaded_files:
        st.write(f"총 **{len(uploaded_files)}장**의 사진이 선택되었습니다.")
        
        # 이미지 전처리 결과 세션 캐싱 (매 렌더링 시 중복 디코딩 방지로 웹소켓 끊김/버벅임 완전 해소)
        file_signature = [(f.name, f.size) for f in uploaded_files]
        cache_key = f"cached_imgs_{platform_type}"
        sig_key = f"cached_sig_{platform_type}"

        if st.session_state.get(sig_key) != file_signature:
            cached_pil = []
            cached_names = []
            for file in uploaded_files:
                pil_img = core_engine.preprocess_pil_image(file)
                if pil_img:
                    cached_pil.append(pil_img)
                    cached_names.append(file.name)
            st.session_state[cache_key] = (cached_pil, cached_names)
            st.session_state[sig_key] = file_signature

        cached_data = st.session_state.get(cache_key, ([], []))
        pil_images, image_names = cached_data[0], cached_data[1]

        # 썸네일 그리드 미리보기 (최대 6개 열)
        cols = st.columns(min(len(pil_images), 6))
        for idx, (p_img, f_name) in enumerate(zip(pil_images, image_names)):
            cols[idx % 6].image(p_img, caption=f_name, use_container_width=True)

    st.markdown("### 2. 📸 사진 선별 및 자리배치 방식")
    photo_mode = st.radio(
        "본문에 배치할 사진 선별 방식 선택",
        options=["smart_best", "rich", "all"],
        format_func=lambda x: {
            "smart_best": "🌟 AI 스마트 베스트 엄선 (추천: 5~8장) — 중복·흐릿한 사진 제외, 가장 잘 나온 사진만 엄선 배치",
            "rich": "📷 풍부한 사진 배치 (8~12장) — 다양한 볼거리를 위해 사진을 폭넓게 선별 배치",
            "all": "📁 업로드한 모든 사진 다 올리기 — 올린 사진 빠짐없이 전부 본문에 배치"
        }[x],
        index=0,
        key=f"photo_mode_{platform_type}",
        help="스마트 베스트 엄선 모드는 수많은 사진 중 블로그 글의 몰입도와 상위 노출에 가장 효과적인 핵심 사진들만 AI가 직접 골라 자리를 배치합니다."
    )

    st.markdown("### 3. 💡 [선택] 보충 힌트")
    user_hint = st.text_input(
        "상호명이나 특별한 기억이 있다면 적어주세요 (없으면 비워두셔도 AI가 사진에서 찾아냅니다)",
        placeholder="예: 양주 은현면 엄마손 순대국, 주차장 넉넉함, 깍두기가 맛있음",
        key=f"hint_{platform_type}"
    )

    st.markdown("---")

    # 원클릭 생성 버튼
    btn_label = "🚀 [원클릭] 팩트 판독 + 인기 사이트 크롤링 + SEO·AEO·GEO 원고 생성"
    can_generate = bool(st.session_state.get("gemini_api_key")) and len(pil_images) > 0

    if not can_generate:
        if not st.session_state.get("gemini_api_key"):
            st.info("💡 사이드바에 Gemini API 키를 먼저 입력해 주세요.")
        elif len(pil_images) == 0:
            st.info("💡 블로그에 사용할 사진을 먼저 업로드해 주세요.")

    if st.button(btn_label, disabled=not can_generate, type="primary", key=f"btn_gen_{platform_type}"):
        api_key = str(st.session_state.get("gemini_api_key", "")).strip()
        client = genai.Client(api_key=api_key)
        
        progress_bar = st.progress(10)
        status_box = st.empty()

        try:
            # 1단계: 사진 속 팩트 텍스트 추출
            status_box.info("🔍 [1단계] 사진 속 간판, 지번/도로명 주소, 메뉴판 글자를 정밀 판독 중입니다...")
            raw_facts, used_model_fact = core_engine.extract_facts_from_images(
                client, pil_images,
                progress_callback=lambda msg: status_box.info(f"🔍 [1단계] {msg}"),
                preferred_model=analysis_model,
                allow_backup=allow_backup
            )
            progress_bar.progress(35)

            # 2단계: 크롤링 질의어 도출 및 실시간 웹 크롤링 (주소 및 영업정보 역추적)
            status_box.info("🌐 [2단계] 사진에 없는 도로명 주소와 매장 정보를 인터넷 실시간 검색으로 역추적 중입니다...")
            query_hint = user_hint.strip() if user_hint and len(user_hint.strip()) > 1 else ""
            if not query_hint:
                fact_lines = [l.strip() for l in raw_facts.splitlines() if l.strip() and not l.startswith("#")]
                query_hint = " ".join(fact_lines[:3])[:80] if fact_lines else "맛집"
            
            web_insights = core_engine.crawl_popular_insights(
                query=query_hint,
                gemini_client=client,
                progress_callback=lambda msg: status_box.info(f"🌐 [2단계] {msg}"),
                preferred_model=analysis_model,
                allow_backup=allow_backup
            )
            progress_bar.progress(60)

            # 3단계: SEO / AEO / GEO 메타데이터 도출
            status_box.info(f"📊 [3단계] {platform_type.upper()} 전용 최적화 제목 및 메타데이터를 도출 중입니다...")
            metadata = core_engine.generate_seo_metadata(
                gemini_client=client,
                pil_images=pil_images,
                image_names=image_names,
                raw_facts=raw_facts,
                web_insights=web_insights,
                user_hint=user_hint,
                target_platform=platform_type,
                progress_callback=lambda msg: status_box.info(f"📊 [3단계] {msg}"),
                preferred_model=writing_model,
                allow_backup=allow_backup
            )
            progress_bar.progress(80)

            # 4단계: 최종 원고 생성
            status_box.info(f"✍️ [4단계] 차세대 AEO 요약 및 FAQ가 포함된 고품질 원고를 작성 중입니다...")
            import inspect
            gen_kwargs = {
                "gemini_client": client,
                "title": metadata['title'],
                "memo": metadata['memo'],
                "pil_images": pil_images,
                "image_names": image_names,
                "raw_facts": raw_facts,
                "web_insights": web_insights,
                "target_platform": platform_type,
                "tone": tone_option,
                "progress_callback": lambda msg: status_box.info(f"✍️ [4단계] {msg}"),
                "preferred_model": writing_model,
                "allow_backup": allow_backup,
            }
            sig = inspect.signature(core_engine.generate_full_article)
            if "photo_mode" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                gen_kwargs["photo_mode"] = photo_mode

            full_article, used_model_article = core_engine.generate_full_article(**gen_kwargs)
            progress_bar.progress(100)
            status_box.success(
                f"🎉 작성이 완료됐습니다! "
                f"(사진 분석: {used_model_fact} · 최종 원고: {used_model_article})"
            )

            # 세션에 저장
            st.session_state[f"result_{platform_type}"] = {
                "metadata": metadata,
                "full_article": full_article,
                "raw_facts": raw_facts,
                "web_insights": web_insights,
                "image_names": image_names,
                "pil_images": pil_images
            }

        except Exception as e:
            err_str = str(e)
            status_box.error(f"❌ 생성 중 오류 발생: {err_str}")
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                st.warning("💡 **[Google API 429 할당량 초과 해결 방법]**\n- 좌측의 **'안전 모델 자동 전환'**이 체크되어 있는지 확인하세요.\n- 1~2분 뒤 다시 시도하거나 절약 모드를 선택해 보세요.\n- Pro 모드는 해당 API 키에 유료 결제 설정이 필요합니다.")

    # 결과물 표시 영역
    res = st.session_state.get(f"result_{platform_type}")
    if res:
        st.markdown("---")
        st.markdown("## 📋 4. 생성된 최적화 원고 및 메타데이터")
        
        meta = res["metadata"]
        
        # 포스팅 제목
        st.subheader("📌 블로그 포스팅 제목")
        title_val = st.text_input("제목 (수정 가능)", value=meta.get("title", ""), key=f"res_title_{platform_type}")
        
        col_copy1, col_copy2 = st.columns([1, 4])
        if col_copy1.button("📋 제목 복사", key=f"copy_title_{platform_type}"):
            try:
                pyperclip.copy(title_val)
                st.toast("✅ 제목이 클립보드에 복사되었습니다!")
            except Exception:
                st.info("브라우저에서 제목 텍스트를 드래그하여 복사하세요.")

        # 메타데이터 서브 정보
        if platform_type == "naver":
            tags_list = meta.get("tags", [])
            tags_str = " ".join(tags_list)
            st.subheader("🏷️ 네이버 스마트블록 해시태그")
            tags_val = st.text_input("태그 (수정 가능)", value=tags_str, key="res_tags_naver")
            
            t_col1, t_col2 = st.columns([1, 4])
            if t_col1.button("📋 태그 복사", key="copy_tags_naver"):
                try:
                    pyperclip.copy(tags_val)
                    st.toast("✅ 태그가 클립보드에 복사되었습니다!")
                except Exception:
                    st.info("태그를 드래그하여 복사하세요.")

            # 추천 썸네일 안내
            thumb = meta.get("thumbnail_recommend", "")
            if thumb:
                st.info(f"🌟 **대표 썸네일 추천 사진**: `{thumb}` (가장 시선을 끄는 메인 사진으로 등록하세요)")

            # 본문 사진 배치 현황 안내
            article_raw = res.get("full_article", "")
            placed_matches = re.findall(r'\[📷\s*사진\s*배치:\s*([^\]]+)\]', article_raw)
            placed_photos = [m.strip() for m in placed_matches if m.strip()]
            
            with st.expander("📸 **본문 사진 자리배치 현황 (AI 엄선 결과)**", expanded=True):
                if placed_photos:
                    st.success(f"✨ 업로드된 사진 중 **총 {len(placed_photos)}장**이 본문에 최적으로 엄선 배치되었습니다.")
                    st.write("**본문 배치 순서:** " + " ➔ ".join([f"`{idx+1}. {name}`" for idx, name in enumerate(placed_photos)]))
                    unplaced = [name for name in res.get("image_names", []) if name not in placed_photos]
                    if unplaced:
                        st.caption(f"💡 유사 구도/품질 사유로 본문에서 제외된 사진 ({len(unplaced)}장): " + ", ".join([f"`{u}`" for u in unplaced]))
                else:
                    st.info("원고 본문 내의 `[📷 사진 배치: 파일명]` 위치를 참고하여 사진을 배치하세요.")

        else:
            # Blogger 전용 필드
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                suggested_slug = meta.get("slug", "local-spot-review")
                slug_val = st.text_input("영문 퍼머링크 슬러그 (소문자/하이픈)", value=suggested_slug, key="res_slug_blogger")
                if st.button("📋 퍼머링크 슬러그 복사", key="copy_slug_blogger_btn"):
                    try:
                        pyperclip.copy(slug_val)
                        st.toast(f"✅ 영문 슬러그 '{slug_val}' 복사 완료! Blogger 우측 [링크 ➔ 맞춤 퍼머링크]에 붙여넣으세요.")
                    except Exception:
                        pass
            with col_b2:
                blogger_labels = meta.get("labels", meta.get("tags", []))
                clean_lbls = [str(l).replace('#', '').strip() for l in blogger_labels if str(l).replace('#', '').strip()]
                labels_str = ", ".join(clean_lbls)
                labels_val = st.text_input("Blogger 라벨 (쉼표 구분, 예: 속초맛집, 짬뽕)", value=labels_str, key="res_labels_blogger")
                if st.button("📋 라벨 복사", key="copy_labels_blogger_btn"):
                    try:
                        pyperclip.copy(labels_val)
                        st.toast("✅ 라벨이 복사되었습니다! Blogger 우측 [라벨]란에 붙여넣으세요.")
                    except Exception:
                        pass
            
            search_desc_suggested = meta.get("search_description", meta.get("memo", ""))
            search_desc_val = st.text_area("검색 설명 (Meta Description, 최대 130자)", value=search_desc_suggested, key="res_sdesc_blogger", height=70)
            if st.button("📋 검색 설명 복사", key="copy_sdesc_blogger_btn"):
                try:
                    pyperclip.copy(search_desc_val)
                    st.toast("✅ 검색 설명이 복사되었습니다! Blogger 우측 [검색 설명]란에 붙여넣으세요.")
                except Exception:
                    pass

        # 분석 및 크롤링 결과 아코디언
        with st.expander("🔍 AI가 사진에서 판독한 1차 팩트 (간판/주소/메뉴/가격)"):
            st.markdown(res["raw_facts"])

        with st.expander("🌐 실시간 인기 사이트 & 상위 블로그 크롤링 꿀팁"):
            st.markdown(res["web_insights"])

        # 본문 영역
        st.subheader("📄 본문 원고")
        article_text = st.text_area(
            "원고 본문 (수정 가능)",
            value=res["full_article"],
            height=450,
            key=f"res_article_{platform_type}"
        )

        # 플랫폼별 하단 액션 버튼
        if platform_type == "naver":
            c1, c2, c3 = st.columns([1.5, 2, 3])
            with c1:
                if st.button("📋 본문 전체 복사", type="primary", key="copy_body_naver"):
                    try:
                        pyperclip.copy(article_text)
                        st.toast("✅ 본문이 클립보드에 복사되었습니다! 네이버 에디터에서 바로 Ctrl + V 하세요.")
                    except Exception:
                        st.info("본문 텍스트 전체를 선택(Ctrl+A) 후 복사(Ctrl+C)하세요.")
            with c2:
                if st.button("🌐 크롬으로 네이버 글쓰기 창 열기", key="open_naver_web"):
                    core_engine.open_in_chrome("https://blog.naver.com/GoBlogWrite.naver")
                    st.toast("🚀 로그인된 크롬 브라우저로 네이버 블로그 글쓰기 창을 열었습니다.")
            
            st.markdown("""
            <div class="action-card">
                <b>💡 초보자를 위한 3초 완성 가이드:</b>
                <ol style="margin-bottom:0; padding-left:1.2rem; font-size:0.9rem; color:#475569;">
                    <li><b>[제목 복사]</b> 후 네이버 에디터 제목란에 붙여넣기(Ctrl+V)</li>
                    <li><b>[본문 전체 복사]</b> 후 네이버 에디터 본문란에 붙여넣기(Ctrl+V)</li>
                    <li>원고 속 <code>[📷 사진 배치: 파일명]</code> 위치에 사진을 넣고 캡션을 입력</li>
                    <li><b>[태그 복사]</b> 후 하단 태그 입력란에 붙여넣기 후 발행!</li>
                </ol>
            </div>
            """, unsafe_allow_html=True)

        else:
            # Blogger 전용 수동 복사 & 안내 액션
            st.markdown("### 📋 Blogger 본문 복사 & 글쓰기 바로가기")
            c_b1, c_b2, c_b3 = st.columns([1.5, 2, 3])
            with c_b1:
                if st.button("📋 HTML 본문 전체 복사", type="primary", key="copy_body_blogger"):
                    try:
                        pyperclip.copy(article_text)
                        st.toast("✅ HTML 본문이 복사되었습니다! Blogger 에디터에서 바로 Ctrl + V 하세요.")
                    except Exception:
                        pass
            with c_b2:
                if st.button("🌐 크롬으로 Blogger 글쓰기 열기", key="open_blogger_web"):
                    core_engine.open_in_chrome("https://www.blogger.com/go/create-post")
                    st.toast("🚀 Blogger 새 글 작성 창을 열었습니다.")

            st.markdown('''<div class="action-card" style="background: #f0fdf4; border-left: 4px solid #16a34a; padding: 14px 18px; border-radius: 8px; margin: 15px 0;"><b style="color: #166534; font-size: 1rem;">📌 블로그스팟 영문 퍼머링크 설정 필수 가이드</b><ol style="margin-top: 8px; margin-bottom: 6px; padding-left: 1.2rem; font-size: 0.92rem; color: #1e293b; line-height: 1.7;"><li>Blogger 웹 에디터 우측 사이드바에서 <b>[링크 (Permalink)]</b>를 클릭합니다.</li><li>기본값인 '자동 퍼머링크' 대신 <b>[맞춤 퍼머링크 (Custom Permalink)]</b>를 선택합니다.</li><li>위의 <b>[📋 퍼머링크 슬러그 복사]</b> 버튼을 눌러 영문 슬러그를 붙여넣습니다. (예: <code>sokcho-yeongbin-food</code>)</li><li><b>반드시 우측 상단 [게시] 버튼을 누르기 전에 맞춤 퍼머링크를 입력</b>해야 원하는 주소로 생성됩니다.<br><span style="color: #dc2626; font-size: 0.86rem; font-weight: 600;">⚠️ '자동 퍼머링크' 상태로 [게시]를 먼저 누르면 한글 제목 특성상 <code>blog-post_26.html</code>로 영구 박제됩니다!</span></li></ol><div style="margin-top: 10px; font-size: 0.88rem; color: #334155; background: #ffffff; padding: 10px 14px; border-radius: 6px; border: 1px solid #cbd5e1; line-height: 1.6;">💡 <b>이미 blog-post_26.html로 발행된 기존 글 변경 방법:</b><br>1. Blogger 관리자 글 목록(또는 해당 글 편집창)에서 <b>[초안으로 되돌리기 (Revert to draft)]</b> 클릭<br>2. 초안 상태가 되면 우측 사이드바 <b>[링크] ➔ [맞춤 퍼머링크]</b>에 영문 슬러그 입력<br>3. 다시 <b>[게시]</b>를 누르면 원하는 영문 주소(<code>.../sokcho-yeongbin-food.html</code>)로 즉시 변경 완료!</div></div>''', unsafe_allow_html=True)

            # 블로그스팟 API 자동 발행
            st.markdown("### 🚀 [선택] 구글 드라이브 & Blogger 원클릭 자동 등록")
            col_bp1, col_bp2 = st.columns([2, 3])
            
            is_draft = col_bp1.checkbox(
                "검토를 위해 '초안(Draft)' 상태로 등록",
                value=False,
                help="※ 영문 맞춤 퍼머링크를 서버에 100% 영구 고정하려면 체크 해제(즉시 발행)를 강력히 권장합니다."
            )
            
            if col_bp1.button("☁️ 구글 드라이브 업로드 & Blogger 자동 등록", type="primary", key="pub_blogger_btn"):
                b_status = st.empty()
                b_status.info("🔑 구글 계정 인증을 진행 중입니다... (크롬 브라우저를 확인해 주세요)")
                
                creds = core_engine.get_oauth_credentials(progress_callback=lambda msg: b_status.info(msg))
                if not creds:
                    st.error("❌ 'client_secret.json' 파일이 필요합니다. Google Cloud 콘솔에서 다운로드하여 프로젝트 폴더에 넣어주세요.")
                else:
                    b_status.info("☁️ 사진들을 구글 드라이브에 업로드하고 링크를 생성 중입니다...")
                    
                    drive_service = core_engine.build('drive', 'v3', credentials=creds)
                    image_url_map = {}
                    for pil_img, fname in zip(res["pil_images"], res["image_names"]):
                        fn, furl = core_engine.upload_image_to_drive(drive_service, pil_img, fname)
                        if fn and furl:
                            image_url_map[fn] = furl
                    
                    # URL 치환
                    html_final = article_text
                    for fname, f_url in image_url_map.items():
                        pattern = rf'src=[\'"][^\'"]*{core_engine.re.escape(fname)}[\'"]'
                        html_final = core_engine.re.sub(pattern, f'src="{f_url}"', html_final)

                    # SEO 구조화 헤더 추가
                    seo_header = f"""<!-- SEO & AEO Meta Information -->
<meta name="description" content="{search_desc_val}">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BlogPosting",
  "headline": "{title_val}",
  "description": "{search_desc_val}",
  "keywords": "{labels_val}"
}}
</script>
"""
                    html_final = seo_header + html_final

                    try:
                        b_status.info("🚀 Blogger에 영문 퍼머링크 영구 고정 및 라벨/메타데이터 동기화 발행 중...")
                        # 쉼표 구분 라벨 파싱 및 공백/# 정제
                        labels = [l.replace('#', '').strip() for l in labels_val.split(",") if l.replace('#', '').strip()]
                        
                        post_res = core_engine.publish_to_blogger(
                            creds=creds,
                            title=title_val,
                            slug=slug_val,
                            html_content=html_final,
                            labels=labels,
                            search_desc=search_desc_val,
                            is_draft=is_draft
                        )
                        b_status.success(f"🎉 성공적으로 등록되었습니다! 블로그: [{post_res['blog_name']}]")
                        
                        # 결과 안내 카드
                        st.markdown(f"🔗 **영구 확정 퍼머링크**: [{post_res['post_url']}]({post_res['post_url']})")
                        st.markdown(f"👉 [Blogger 글 확인 및 편집 바로가기]({post_res['edit_url']})")
                        
                        # 클립보드 자동 복사
                        try:
                            pyperclip.copy(search_desc_val)
                            st.toast("✅ [검색 설명]이 클립보드에 자동 복사되었습니다!")
                        except Exception:
                            pass

                        st.markdown(f"""
                        <div style="background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 14px; margin-top: 12px; font-size: 0.92rem;">
                            <b>📌 동기화된 메타데이터 요약:</b><br>
                            • <b>확정된 퍼머링크 슬러그</b>: <code>{post_res['slug']}</code><br>
                            • <b>등록된 라벨</b>: {', '.join(post_res['labels'])}<br>
                            • <b>검색 설명</b>: {post_res['search_desc']}<br>
                            <hr style="margin: 10px 0;">
                            <span style="color: #64748b; font-size: 0.85rem;">
                            💡 <b>Blogger 꿀팁</b>: 본문 최상단에 검색로봇 전용 Schema.org 메타태그가 자동 주입되었습니다.<br>
                            ※ Blogger 관리자 글 편집창 우측 사이드바에 [검색 설명] 칸이 나타나려면 <b>Blogger 설정 ➔ 메타 태그 ➔ '검색 설명 사용 설정'</b>을 켜두셔야 합니다.
                            </span>
                        </div>
                        """, unsafe_allow_html=True)

                    except Exception as ex:
                        b_status.error(f"❌ Blogger 발행 오류: {ex}")

# 탭별 렌더링
with tab_naver:
    render_platform_studio("naver")

with tab_blogger:
    render_platform_studio("blogger")

"""
drive_loader.py - 성경 주석 자료 로더 및 Gemini AI 통합 모듈

우선순위:
1. Google Drive API (서비스 계정 키가 환경변수에 있을 때)
2. 로컬 D드라이브 폴더 (클라우드 접근 불가 시 폴백)
3. 기존 하드코딩 지식 베이스 (로컬도 없을 때 최종 폴백)

Gemini AI를 사용하여 수집된 자료를 바탕으로 보고서를 생성합니다.
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────
# 환경 설정
# ─────────────────────────────────────────────────────────────
CURRENT_DIR = Path(__file__).resolve().parent
CACHE_FILE = CURRENT_DIR / "drive_knowledge_cache.json"
CACHE_TTL_SECONDS = 86400  # 24시간

# 로컬 D드라이브 주석 자료 경로
LOCAL_COMMENTARY_DIRS = [
    Path("D:/1_주석 자료"),
    Path("D:\\1_주석 자료"),
]
LOCAL_PASTORAL_DIRS = [
    Path("D:/2_목회자 성경 연구원 자료"),
    Path("D:\\2_목회자 성경 연구원 자료"),
]

# ─────────────────────────────────────────────────────────────
# Google Drive API 초기화 (선택적)
# ─────────────────────────────────────────────────────────────
_drive_service = None
_drive_available = False

def _init_google_drive():
    """Google Drive API 서비스 초기화. 실패해도 조용히 폴백."""
    global _drive_service, _drive_available
    
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not service_account_json:
        # 파일 경로로도 시도
        sa_file = CURRENT_DIR / "service_account.json"
        if sa_file.exists():
            service_account_json = sa_file.read_text(encoding="utf-8")
    
    if not service_account_json:
        print("📋 [DriveLoader] Google Drive 서비스 계정 없음 → 로컬 D드라이브 모드")
        return
    
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        
        creds_data = json.loads(service_account_json)
        creds = Credentials.from_service_account_info(
            creds_data,
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )
        _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        _drive_available = True
        print("✅ [DriveLoader] Google Drive API 연결 성공")
    except Exception as e:
        print(f"⚠️ [DriveLoader] Google Drive API 초기화 실패 → 로컬 폴백: {e}")
        _drive_available = False

# ─────────────────────────────────────────────────────────────
# Gemini AI 초기화
# ─────────────────────────────────────────────────────────────
_gemini_client = None
_gemini_available = False
GEMINI_MODEL = "gemini-2.5-flash"

def _init_gemini():
    """Gemini AI 클라이언트 초기화."""
    global _gemini_client, _gemini_available
    
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("⚠️ [DriveLoader] GEMINI_API_KEY 없음 → 템플릿 모드")
        return
    
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
        _gemini_available = True
        print(f"✅ [DriveLoader] Gemini AI 초기화 성공 (모델: {GEMINI_MODEL})")
    except Exception as e:
        print(f"⚠️ [DriveLoader] Gemini AI 초기화 실패: {e}")

# 모듈 로드 시 초기화
_init_google_drive()
_init_gemini()


# ─────────────────────────────────────────────────────────────
# 로컬 파일 텍스트 추출
# ─────────────────────────────────────────────────────────────
def _extract_text_from_pdf(file_path: Path, max_chars: int = 8000) -> str:
    """PDF 파일에서 텍스트 추출."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(file_path))
        text_parts = []
        total = 0
        for page in reader.pages:
            if total >= max_chars:
                break
            t = page.extract_text() or ""
            text_parts.append(t)
            total += len(t)
        return " ".join(text_parts)[:max_chars]
    except Exception:
        return ""

def _extract_text_from_docx(file_path: Path, max_chars: int = 8000) -> str:
    """DOCX 파일에서 텍스트 추출."""
    try:
        from docx import Document
        doc = Document(str(file_path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return text[:max_chars]
    except Exception:
        return ""

def _extract_text_from_txt(file_path: Path, max_chars: int = 8000) -> str:
    """텍스트 파일에서 내용 읽기."""
    try:
        for enc in ["utf-8", "utf-8-sig", "cp949", "euc-kr"]:
            try:
                return file_path.read_text(encoding=enc)[:max_chars]
            except (UnicodeDecodeError, Exception):
                continue
        return ""
    except Exception:
        return ""

def _extract_text(file_path: Path, max_chars: int = 8000) -> str:
    """파일 확장자에 따라 텍스트 추출."""
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return _extract_text_from_pdf(file_path, max_chars)
    elif ext in (".docx", ".doc"):
        return _extract_text_from_docx(file_path, max_chars)
    elif ext in (".txt", ".md"):
        return _extract_text_from_txt(file_path, max_chars)
    return ""


# ─────────────────────────────────────────────────────────────
# 성경 권명 관련 파일 검색
# ─────────────────────────────────────────────────────────────
BOOK_KEYWORD_MAP = {
    "창세기": ["창세기", "창세", "창", "Genesis", "Gen"],
    "출애굽기": ["출애굽", "출애굽기", "출", "Exodus", "Exod"],
    "레위기": ["레위기", "레위", "레", "Leviticus", "Lev"],
    "민수기": ["민수기", "민수", "민", "Numbers", "Num"],
    "신명기": ["신명기", "신명", "신", "Deuteronomy", "Deut"],
    "시편": ["시편", "시", "Psalms", "Psalm", "Ps"],
    "이사야": ["이사야", "사", "Isaiah", "Isa"],
    "예레미야": ["예레미야", "렘", "Jeremiah", "Jer"],
    "에스겔": ["에스겔", "겔", "Ezekiel", "Ezek"],
    "다니엘": ["다니엘", "단", "Daniel", "Dan"],
    "마태복음": ["마태복음", "마태", "마", "Matthew", "Matt"],
    "마가복음": ["마가복음", "마가", "막", "Mark"],
    "누가복음": ["누가복음", "누가", "눅", "Luke"],
    "요한복음": ["요한복음", "요한", "요", "John"],
    "사도행전": ["사도행전", "행", "Acts"],
    "로마서": ["로마서", "롬", "Romans", "Rom"],
    "고린도전서": ["고린도전서", "고전", "1 Corinthians", "1Cor"],
    "고린도후서": ["고린도후서", "고후", "2 Corinthians", "2Cor"],
    "갈라디아서": ["갈라디아서", "갈", "Galatians", "Gal"],
    "에베소서": ["에베소서", "엡", "Ephesians", "Eph"],
    "빌립보서": ["빌립보서", "빌", "Philippians", "Phil"],
    "골로새서": ["골로새서", "골", "Colossians", "Col"],
    "요한계시록": ["요한계시록", "계시록", "계", "Revelation", "Rev"],
}

def _get_book_keywords(book_name: str) -> List[str]:
    """성경 권명에 해당하는 검색 키워드 목록 반환."""
    for key, keywords in BOOK_KEYWORD_MAP.items():
        if book_name == key or book_name in keywords:
            return keywords
    # 기본: 책 이름 자체
    return [book_name]


def _search_local_files(root_dirs: List[Path], book_name: str, max_files: int = 5) -> List[str]:
    """로컬 폴더에서 특정 성경 권명과 관련된 파일 텍스트 수집."""
    keywords = _get_book_keywords(book_name)
    collected = []
    
    for root in root_dirs:
        if not root.exists():
            continue
        
        # 재귀 파일 탐색 (PDF, DOCX, TXT)
        for ext in ["*.pdf", "*.docx", "*.txt", "*.doc"]:
            for f in root.rglob(ext):
                if len(collected) >= max_files:
                    break
                fname = f.name
                # 파일명에 관련 키워드가 있는 경우 우선 선택
                if any(kw in fname for kw in keywords):
                    text = _extract_text(f, max_chars=5000)
                    if text.strip():
                        collected.append(f"[{f.parent.name}/{fname}]\n{text[:3000]}")
        
        if len(collected) >= max_files:
            break
    
    return collected


# ─────────────────────────────────────────────────────────────
# Google Drive 파일 검색
# ─────────────────────────────────────────────────────────────
DRIVE_FOLDER_IDS = {
    "commentary": os.environ.get("DRIVE_COMMENTARY_FOLDER_ID", ""),   # 1_주석 자료
    "pastoral": os.environ.get("DRIVE_PASTORAL_FOLDER_ID", ""),        # 2_목회자 성경 연구원 자료
}

def _search_drive_files(book_name: str, max_files: int = 5) -> List[str]:
    """Google Drive에서 특정 성경 권명과 관련된 파일 텍스트 수집."""
    if not _drive_available or not _drive_service:
        return []
    
    keywords = _get_book_keywords(book_name)
    collected = []
    
    for folder_type, folder_id in DRIVE_FOLDER_IDS.items():
        if not folder_id or len(collected) >= max_files:
            break
        
        try:
            # 키워드 기반 파일 검색
            for kw in keywords[:2]:
                if len(collected) >= max_files:
                    break
                query = f"'{folder_id}' in parents and name contains '{kw}' and trashed = false"
                results = _drive_service.files().list(
                    q=query,
                    fields="files(id, name, mimeType)",
                    pageSize=3
                ).execute()
                
                for file_info in results.get("files", []):
                    if len(collected) >= max_files:
                        break
                    try:
                        from googleapiclient.http import MediaIoBaseDownload
                        import io
                        
                        file_id = file_info["id"]
                        mime = file_info.get("mimeType", "")
                        fname = file_info.get("name", "")
                        
                        if "google-apps" in mime:
                            # Google Docs → export as text
                            content = _drive_service.files().export(
                                fileId=file_id, mimeType="text/plain"
                            ).execute()
                            text = content.decode("utf-8", errors="ignore")[:4000] if content else ""
                        else:
                            # 바이너리 파일 → 로컬 임시 저장 후 추출
                            request = _drive_service.files().get_media(fileId=file_id)
                            fh = io.BytesIO()
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()
                            fh.seek(0)
                            
                            tmp_path = CURRENT_DIR / "tmp" / fname
                            tmp_path.parent.mkdir(parents=True, exist_ok=True)
                            tmp_path.write_bytes(fh.read())
                            text = _extract_text(tmp_path, max_chars=4000)
                        
                        if text.strip():
                            collected.append(f"[Drive/{folder_type}/{fname}]\n{text[:3000]}")
                    except Exception as e:
                        print(f"⚠️ [DriveLoader] Drive 파일 읽기 실패 ({fname}): {e}")
        except Exception as e:
            print(f"⚠️ [DriveLoader] Drive 검색 실패: {e}")
    
    return collected


# ─────────────────────────────────────────────────────────────
# 캐시 관리
# ─────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            # TTL 체크
            if time.time() - data.get("_timestamp", 0) < CACHE_TTL_SECONDS:
                return data
    except Exception:
        pass
    return {}

def _save_cache(data: dict):
    try:
        data["_timestamp"] = time.time()
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Gemini AI 기반 보고서 생성
# ─────────────────────────────────────────────────────────────
def generate_with_gemini(
    passage: str,
    book_name: str,
    testament: str,
    genre: str,
    commentary_texts: List[str],
    pastoral_texts: List[str]
) -> Optional[str]:
    """
    Gemini AI를 사용하여 수집된 주석 자료를 바탕으로
    올인원 마스터 보고서의 핵심 섹션을 생성합니다.
    """
    if not _gemini_available or not _gemini_client:
        return None
    
    original_lang = "히브리어(BHS/WLC)" if testament == "구약" else "헬라어(NA28 Nestle-Aland)"
    
    # 자료 컨텍스트 조합
    commentary_ctx = "\n\n---\n".join(commentary_texts[:3]) if commentary_texts else "주석 자료 없음"
    pastoral_ctx = "\n\n---\n".join(pastoral_texts[:3]) if pastoral_texts else "목성연 자료 없음"
    
    prompt = f"""당신은 한국 개혁주의 성경신학 전문가입니다. 
다음 성경 본문에 대해 올인원 마스터 대통합 연구보고서의 핵심 내용을 한국어로 작성하십시오.

**[분석 본문]**: {passage} ({testament}/{genre})
**[원문 권위본]**: {original_lang}

**[수집된 1_주석 자료]**:
{commentary_ctx[:4000]}

**[수집된 2_목회자 성경 연구원 자료]**:
{pastoral_ctx[:3000]}

위 자료를 바탕으로 아래 6가지 핵심 항목을 작성하십시오. 
각 항목은 반드시 자료에서 실제로 파악된 내용을 바탕으로 하되, 자료가 부족하면 학술적으로 보완하십시오.

## OUTPUT_START

### [OXFORD_HOCKMA]
옥스포드 원어성경대전 및 호크마 종합주석에 근거한 {passage}의 원어 분석 및 문맥적 교훈 (3-5문장):

### [CALVIN_PARK]
칼빈 성경주석 및 박윤선 종합주석의 {passage} 해석 및 신학적 통찰 (3-5문장):

### [WBC_IVP]
WBC 및 IVP 성경배경주석의 {passage} 역사적·문화적 배경 및 원독자 분석 (3-5문장):

### [MOKSUNGYEON]
목회자 성경 연구원(목성연) 구속사 강의 맥락에서 {passage}의 언약신학적 의미 및 현대 목회 적용 (3-5문장):

### [NARRATIVE_FOCUS]
{book_name} 전체 맥락에서 {passage}의 구속사적 핵심 초점 (1문장):

### [SERMON_BIGIDEA]
{passage}의 강해설교를 위한 핵심 명제 1문장 (Big Idea):

## OUTPUT_END

반드시 한국어로 작성하고, 각 항목의 구분 태그를 유지하십시오."""

    try:
        from google import genai
        response = _gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"⚠️ [DriveLoader] Gemini API 호출 실패: {e}")
        return None


def _parse_gemini_output(gemini_text: str) -> dict:
    """Gemini 응답에서 각 섹션을 파싱합니다."""
    result = {}
    
    sections = {
        "oxford_hockma": r"\[OXFORD_HOCKMA\](.*?)(?=\[CALVIN_PARK\]|\[WBC_IVP\]|\[MOKSUNGYEON\]|\[NARRATIVE_FOCUS\]|\[SERMON_BIGIDEA\]|## OUTPUT_END|$)",
        "calvin_park": r"\[CALVIN_PARK\](.*?)(?=\[WBC_IVP\]|\[MOKSUNGYEON\]|\[NARRATIVE_FOCUS\]|\[SERMON_BIGIDEA\]|## OUTPUT_END|$)",
        "wbc_ivp": r"\[WBC_IVP\](.*?)(?=\[MOKSUNGYEON\]|\[NARRATIVE_FOCUS\]|\[SERMON_BIGIDEA\]|## OUTPUT_END|$)",
        "moksungyeon": r"\[MOKSUNGYEON\](.*?)(?=\[NARRATIVE_FOCUS\]|\[SERMON_BIGIDEA\]|## OUTPUT_END|$)",
        "narrative_focus": r"\[NARRATIVE_FOCUS\](.*?)(?=\[SERMON_BIGIDEA\]|## OUTPUT_END|$)",
        "sermon_bigidea": r"\[SERMON_BIGIDEA\](.*?)(?=## OUTPUT_END|$)",
    }
    
    for key, pattern in sections.items():
        m = re.search(pattern, gemini_text, re.DOTALL | re.IGNORECASE)
        if m:
            text = m.group(1).strip()
            # ### 헤더 라인 제거
            text = re.sub(r"^###.*$", "", text, flags=re.MULTILINE).strip()
            result[key] = text
    
    return result


# ─────────────────────────────────────────────────────────────
# 통합 지식 베이스 로더 (외부에서 호출하는 메인 함수)
# ─────────────────────────────────────────────────────────────
def load_knowledge_base(book_name: str, passage: str, testament: str, genre: str) -> dict:
    """
    성경 권명과 구절에 맞는 주석 자료를 로드하고 Gemini AI로 분석합니다.
    
    Returns:
        dict with keys: original_words, oxford_hockma, calvin_park, wbc_ivp, 
                        moksungyeon, narrative_focus, sermon_bigidea
        (generator.py의 BOOK_SPECIFIC_KNOWLEDGE 형식과 호환)
    """
    cache_key = f"{book_name}_{passage}"
    
    # 캐시 확인
    cache = _load_cache()
    if cache_key in cache:
        print(f"📦 [DriveLoader] 캐시 히트: {cache_key}")
        return cache[cache_key]
    
    print(f"🔍 [DriveLoader] 자료 수집 시작: {passage} ({book_name})")
    
    # 1. 주석 자료 수집 (Google Drive → 로컬 D드라이브 순)
    commentary_texts = []
    if _drive_available:
        commentary_texts = _search_drive_files(book_name, max_files=4)
    if not commentary_texts:
        commentary_texts = _search_local_files(LOCAL_COMMENTARY_DIRS, book_name, max_files=4)
    
    # 2. 목성연 자료 수집
    pastoral_texts = []
    if _drive_available:
        pastoral_texts = _search_drive_files(book_name, max_files=3)
    if not pastoral_texts:
        pastoral_texts = _search_local_files(LOCAL_PASTORAL_DIRS, book_name, max_files=3)
    
    print(f"📚 [DriveLoader] 수집 완료 - 주석:{len(commentary_texts)}개, 목성연:{len(pastoral_texts)}개")
    
    # 3. Gemini AI로 보고서 생성
    gemini_result = None
    parsed = {}
    if _gemini_available and (commentary_texts or pastoral_texts):
        gemini_text = generate_with_gemini(
            passage, book_name, testament, genre,
            commentary_texts, pastoral_texts
        )
        if gemini_text:
            parsed = _parse_gemini_output(gemini_text)
            print(f"🤖 [DriveLoader] Gemini 생성 완료: {list(parsed.keys())}")
    
    # 4. 원어 기본값 설정 (구약/신약 구분)
    is_ot = (testament == "구약")
    if is_ot:
        default_words = [
            ("בְּרִית", "베리트", "명사 여성 단수", f"언약 - {book_name}에서 하나님께서 자기 백성과 맺으신 영원하고 변함없는 구원의 약속"),
            ("חֶ֫סֶד", "헤세드", "명사 남성 단수", f"인애, 성실 - {book_name} 전체를 관통하는 하나님의 무조건적이고 영원한 언약적 사랑"),
        ]
    else:
        default_words = [
            ("χάρις", "카리스", "명사 여성 단수 주격", f"은혜 - {book_name}에서 죄인을 의인으로 변화시키는 하나님의 조건 없는 선물"),
            ("πίστις", "피스티스", "명사 여성 단수 주격", f"믿음 - {book_name}에서 예수 그리스도의 대속 사역을 신뢰하고 전인격적으로 연합하는 순종"),
        ]
    
    # 5. 결과 조합
    result = {
        "original_words": default_words,
        "oxford_hockma": parsed.get("oxford_hockma") or f"옥스포드 원어성경대전과 호크마 종합주석은 {passage}의 원어 구문 구조를 치밀하게 분석하며, 본문이 언약 백성의 정체성과 순종의 필연성을 강조하고 있음을 논증한다.",
        "calvin_park": parsed.get("calvin_park") or f"칼빈 성경주석과 박윤선 박사 종합주석은 {passage}에 나타난 하나님의 절대 주권과 구속사적 섭리를 개혁주의 신학의 관점에서 조명하며 성도의 실존적 경건을 촉구한다.",
        "wbc_ivp": parsed.get("wbc_ivp") or f"WBC와 IVP 배경주석은 고대 근동의 역사문화적 배경 속에서 {passage}의 원독자들에게 전달되었던 1차적 메시지와 하나님의 거룩한 구별됨을 복원한다.",
        "moksungyeon": parsed.get("moksungyeon") or f"목회자 성경 연구원(목성연) 교재는 {passage}을 '언약과 광야 훈련'의 거시적 맥락에서 해석하며, 고난 속에서도 신실하신 하나님을 신뢰하고 일상의 제자도로 나아가도록 방향을 제시한다.",
        "narrative_focus": parsed.get("narrative_focus") or f"{book_name}의 중심 흐름 속에서 하나님의 언약적 신실하심과 구속사적 통치",
        "sermon_bigidea": parsed.get("sermon_bigidea") or f"하나님의 언약은 인간의 연약함을 넘어 신실하게 성취되며, 성도는 그리스도 안에서 주어진 새로운 정체성으로 거룩한 구별됨과 사랑을 실천하도록 부름받았다.",
        "_source": "gemini+drive" if (parsed and commentary_texts) else ("drive" if commentary_texts else "template"),
        "_commentary_count": len(commentary_texts),
        "_pastoral_count": len(pastoral_texts),
    }
    
    # 6. 캐시 저장
    cache[cache_key] = result
    _save_cache(cache)
    
    source_emoji = "🤖" if "gemini" in result["_source"] else ("📚" if "drive" in result["_source"] else "📝")
    print(f"{source_emoji} [DriveLoader] 완료 [{result['_source']}] - {passage}")
    
    return result


# ─────────────────────────────────────────────────────────────
# 캐시 초기화 (관리자 기능)
# ─────────────────────────────────────────────────────────────
def clear_knowledge_cache():
    """지식 베이스 캐시를 강제 초기화."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
        print("🗑️ [DriveLoader] 캐시 초기화 완료")
        return True
    except Exception as e:
        print(f"⚠️ [DriveLoader] 캐시 초기화 실패: {e}")
        return False


if __name__ == "__main__":
    # 테스트 실행
    test_book = "로마서"
    test_passage = "로마서 8:1-11"
    result = load_knowledge_base(test_book, test_passage, "신약", "바울서신")
    print("\n=== 결과 ===")
    for k, v in result.items():
        if not k.startswith("_"):
            print(f"\n[{k}]:\n{str(v)[:200]}...")

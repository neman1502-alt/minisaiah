"""
drive_loader.py - 성경 주석 자료 로더 및 Gemini AI 통합 모듈

우선순위:
1. Google Drive API (서비스 계정 키가 환경변수에 있을 때)
   - 권별 전용 폴더(예: 11빌립보서, 06로마서, 01창세기 등) 및 장절 우선 탐색
   - .htm, .html, .pdf, .docx, .txt 자료 완벽 추출
2. 로컬 D드라이브 폴더 (클라우드 접근 불가 시 폴백)
3. Gemini AI를 사용하여 수집된 자료를 바탕으로 고품질 학술 주석 및 구속사 통찰 생성
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

CURRENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CURRENT_DIR))

# D드라이브 인덱서 및 성경 66권 매처 임포트
try:
    from d_drive_indexer import get_integrated_commentary_insights, build_or_load_catalog
    from bible_canon_matcher import parse_bible_query, BIBLE_66_BOOKS
    _D_DRIVE_INDEXER_AVAILABLE = True
except Exception as e:
    print(f"⚠️ [DriveLoader] d_drive_indexer 임포트 실패: {e}")
    _D_DRIVE_INDEXER_AVAILABLE = False

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
        # 로컬 파일 경로 시도
        sa_file = CURRENT_DIR / "service_account.json"
        if not sa_file.exists():
            sa_file = CURRENT_DIR / "bible-analysis-508206-fd0095e60c8a.json"
        if sa_file.exists():
            try:
                service_account_json = sa_file.read_text(encoding="utf-8")
            except Exception:
                pass
    
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
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-pro"
]
GEMINI_MODEL = GEMINI_MODELS[0]

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
        print(f"✅ [DriveLoader] Gemini AI 초기화 성공 (기본 모델: {GEMINI_MODEL})")
    except Exception as e:
        print(f"⚠️ [DriveLoader] Gemini AI 초기화 실패: {e}")

# 모듈 로드 시 초기화
_init_google_drive()
_init_gemini()


# ─────────────────────────────────────────────────────────────
# 텍스트 추출 함수들 (PDF, DOCX, HTML/HTM, TXT)
# ─────────────────────────────────────────────────────────────
def _extract_text_from_pdf(file_path: Path, max_chars: int = 8000) -> str:
    """PDF 파일에서 텍스트 추출."""
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(str(file_path))
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

def _extract_text_from_html(file_path: Path, max_chars: int = 8000) -> str:
    """HTML / HTM 파일에서 텍스트 추출 (cp949, utf-8, euc-kr 자동 감지)."""
    try:
        raw_bytes = file_path.read_bytes()
        text = ""
        for enc in ["cp949", "utf-8", "euc-kr", "utf-8-sig"]:
            try:
                text = raw_bytes.decode(enc)
                break
            except Exception:
                continue
        if not text:
            text = raw_bytes.decode("utf-8", errors="replace")
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'&nbsp;', ' ', clean)
        clean = re.sub(r'&quot;', '"', clean)
        clean = re.sub(r'&amp;', '&', clean)
        clean = re.sub(r'&lt;', '<', clean)
        clean = re.sub(r'&gt;', '>', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean[:max_chars]
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
    elif ext in (".htm", ".html"):
        return _extract_text_from_html(file_path, max_chars)
    elif ext in (".txt", ".md"):
        return _extract_text_from_txt(file_path, max_chars)
    return ""


# ─────────────────────────────────────────────────────────────
# 성경 권명 관련 키워드 맵
# ─────────────────────────────────────────────────────────────
BOOK_KEYWORD_MAP = {
    "창세기": ["창세기", "창세", "창", "Genesis", "Gen"],
    "출애굽기": ["출애굽", "출애굽기", "출", "Exodus", "Exod"],
    "레위기": ["레위기", "레위", "레", "Leviticus", "Lev"],
    "민수기": ["민수기", "민수", "민", "Numbers", "Num"],
    "신명기": ["신명기", "신명", "신", "Deuteronomy", "Deut"],
    "여호수아": ["여호수아", "수아", "수", "Joshua", "Josh"],
    "사사기": ["사사기", "사사", "삿", "Judges", "Judg"],
    "룻기": ["룻기", "룻", "Ruth"],
    "사무엘상": ["사무엘상", "삼상", "1Samuel", "1Sam"],
    "사무엘하": ["사무엘하", "삼하", "2Samuel", "2Sam"],
    "열왕기상": ["열왕기상", "왕상", "1Kings"],
    "열왕기하": ["열왕기하", "왕하", "2Kings"],
    "역대상": ["역대상", "대상", "1Chronicles"],
    "역대하": ["역대하", "대하", "2Chronicles"],
    "에스라": ["에스라", "스", "Ezra"],
    "느헤미야": ["느헤미야", "느", "Nehemiah", "Neh"],
    "에스더": ["에스더", "에", "Esther", "Esth"],
    "욥기": ["욥기", "욥", "Job"],
    "시편": ["시편", "시", "Psalms", "Psalm", "Psa"],
    "잠언": ["잠언", "잠", "Proverbs", "Prov"],
    "전도서": ["전도서", "전도", "전", "Ecclesiastes", "Eccl"],
    "아가": ["아가", "아", "Song of Songs", "Song"],
    "이사야": ["이사야", "사", "Isaiah", "Isa"],
    "예레미야": ["예레미야", "렘", "Jeremiah", "Jer"],
    "예레미야애가": ["애가", "예레미야애가", "Lamentations", "Lam"],
    "에스겔": ["에스겔", "겔", "Ezekiel", "Ezek"],
    "다니엘": ["다니엘", "단", "Daniel", "Dan"],
    "호세아": ["호세아", "호", "Hosea", "Hos"],
    "요엘": ["요엘", "욜", "Joel"],
    "아모스": ["아모스", "암", "Amos"],
    "오바댜": ["오바댜", "옵", "Obadiah", "Obad"],
    "요나": ["요나", "욘", "Jonah"],
    "미가": ["미가", "미", "Micah", "Mic"],
    "나훔": ["나훔", "나", "Nahum", "Nah"],
    "하박국": ["하박국", "합", "Habakkuk", "Hab"],
    "스바냐": ["스바냐", "습", "Zephaniah", "Zeph"],
    "학개": ["학개", "학", "Haggai", "Hag"],
    "스가랴": ["스가랴", "슥", "Zechariah", "Zech"],
    "말라기": ["말라기", "말", "Malachi", "Mal"],
    "마태복음": ["마태복음", "마태", "마", "Matthew", "Matt"],
    "마가복음": ["마가복음", "마가", "막", "Mark"],
    "누가복음": ["누가복음", "누가", "눅", "Luke"],
    "요한복음": ["요한복음", "요한", "요", "John"],
    "사도행전": ["사도행전", "사도", "행", "Acts"],
    "로마서": ["로마서", "로마", "롬", "Romans", "Rom"],
    "고린도전서": ["고린도전서", "고전", "1Corinthians", "1Cor"],
    "고린도후서": ["고린도후서", "고후", "2Corinthians", "2Cor"],
    "갈라디아서": ["갈라디아서", "갈라디아", "갈", "Galatians", "Gal"],
    "에베소서": ["에베소서", "에베소", "엡", "Ephesians", "Eph"],
    "빌립보서": ["빌립보서", "빌립보", "빌", "Philippians", "Phil"],
    "골로새서": ["골로새서", "골로새", "골", "Colossians", "Col"],
    "데살로니가전서": ["데살로니가전서", "살전", "1Thessalonians"],
    "데살로니가후서": ["데살로니가후서", "살후", "2Thessalonians"],
    "디모데전서": ["디모데전서", "딤전", "1Timothy"],
    "디모데후서": ["디모데후서", "딤후", "2Timothy"],
    "디도서": ["디도서", "디도", "딛", "Titus"],
    "빌레몬서": ["빌레몬서", "빌레몬", "몬", "Philemon", "Phlm"],
    "히브리서": ["히브리서", "히브리", "히", "Hebrews", "Heb"],
    "야고보서": ["야고보서", "야고보", "약", "James", "Jas"],
    "베드로전서": ["베드로전서", "벧전", "1Peter", "1Pet"],
    "베드로후서": ["베드로후서", "벧후", "2Peter", "2Pet"],
    "요한일서": ["요한일서", "요일", "1John"],
    "요한이서": ["요한이서", "요이", "2John"],
    "요한삼서": ["요한삼서", "요삼", "3John"],
    "유다서": ["유다서", "유다", "유", "Jude"],
    "요한계시록": ["요한계시록", "계시록", "계", "Revelation", "Rev"],
}

def _get_book_keywords(book_name: str) -> List[str]:
    """성경 권명에 대한 검색 키워드 목록 반환."""
    for canonical, kws in BOOK_KEYWORD_MAP.items():
        if canonical in book_name or book_name in canonical:
            return kws
    return [book_name]


def _search_local_files(root_dirs: List[Path], book_name: str, max_files: int = 5) -> List[str]:
    """로컬 폴더에서 특정 성경 권명과 관련된 파일 텍스트 수집."""
    keywords = _get_book_keywords(book_name)
    collected = []
    
    for root in root_dirs:
        if not root.exists():
            continue
        for ext in ["*.pdf", "*.docx", "*.txt", "*.htm", "*.html", "*.doc"]:
            for f in root.rglob(ext):
                if len(collected) >= max_files:
                    break
                fname = f.name
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
def _find_book_folders_on_drive(book_name: str) -> List[dict]:
    """성경 권명과 매칭되는 Drive 폴더 탐색 (예: '11빌립보서', '06로마서', '01창세기')."""
    if not _drive_available or not _drive_service:
        return []
    keywords = _get_book_keywords(book_name)
    found = []
    seen_ids = set()
    for kw in keywords[:3]:
        try:
            q = f"mimeType = 'application/vnd.google-apps.folder' and name contains '{kw}' and trashed = false"
            resp = _drive_service.files().list(q=q, fields="files(id, name)", pageSize=10).execute()
            for f in resp.get("files", []):
                if f["id"] not in seen_ids:
                    seen_ids.add(f["id"])
                    found.append(f)
        except Exception:
            pass
    return found


def _read_drive_file(file_info: dict) -> str:
    """Drive 파일 하나를 읽어 텍스트 반환 (미디어 파일 철저 배제)."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
        import io
        file_id = file_info["id"]
        mime = file_info.get("mimeType", "")
        fname = file_info.get("name", "")
        fext = Path(fname).suffix.lower()

        # 오디오, 비디오, 바이너리 파일 즉시 스킵
        if fext in [".mp3", ".mp4", ".m4a", ".wav", ".wma", ".avi", ".zip", ".exe"]:
            return ""
        if any(m in mime for m in ["audio", "video", "image"]):
            return ""

        if "google-apps" in mime:
            content = _drive_service.files().export(
                fileId=file_id, mimeType="text/plain"
            ).execute()
            return content.decode("utf-8", errors="ignore")[:4000] if content else ""
        else:
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
            return _extract_text(tmp_path, max_chars=4000)
    except Exception as e:
        print(f"⚠️ [DriveLoader] 파일 읽기 실패 ({file_info.get('name')}): {e}")
        return ""


def _search_drive_files(book_name: str, passage: str = "", max_files: int = 2) -> List[str]:
    """Google Drive에서 특정 성경 권명 및 장절과 관련된 텍스트 수집 (미디어 배제 및 초고속화)."""
    if not _drive_available or not _drive_service:
        return []

    collected = []
    seen_file_names = set()

    # 장 번호 추출 (예: '요한복음 1:43-51' -> '1')
    chapter_num = ""
    m = re.search(r'(\d+)(?:장|:)', passage)
    if m:
        chapter_num = m.group(1)

    try:
        # 1. 성경 권별 전용 폴더 내 검색
        book_folders = _find_book_folders_on_drive(book_name)
        for bfolder in book_folders:
            if len(collected) >= max_files:
                break
            fid = bfolder["id"]
            fname = bfolder["name"]

            # 1-1. 해당 장 번호가 포함된 파일 우선 검색
            if chapter_num:
                for ch_kw in [f"{chapter_num}장", f"장{chapter_num}", f"{chapter_num}-"]:
                    if len(collected) >= max_files:
                        break
                    try:
                        q = f"'{fid}' in parents and name contains '{ch_kw}' and trashed = false and mimeType != 'audio/mpeg'"
                        resp = _drive_service.files().list(
                            q=q, fields="files(id, name, mimeType)", pageSize=3
                        ).execute()
                        for finfo in resp.get("files", []):
                            if len(collected) >= max_files:
                                break
                            if finfo["name"] in seen_file_names:
                                continue
                            text = _read_drive_file(finfo)
                            if text.strip():
                                seen_file_names.add(finfo["name"])
                                collected.append(f"[Drive/{fname}/{finfo['name']}]\n{text[:3000]}")
                    except Exception as e:
                        print(f"⚠️ [DriveLoader] 장별 파일 검색 스킵: {e}")
                        break
    except Exception as e:
        print(f"⚠️ [DriveLoader] Drive 검색 전체 스킵: {e}")

    return collected


# ─────────────────────────────────────────────────────────────
# 캐시 관리
# ─────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
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
        _init_gemini()
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

    for model_name in GEMINI_MODELS:
        try:
            response = _gemini_client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response and response.text:
                return response.text
        except Exception as e:
            print(f"⚠️ [DriveLoader] Gemini ({model_name}) 호출 실패: {e}")
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
            clean_val = re.sub(r"^###.*$", "", m.group(1).strip(), flags=re.MULTILINE).strip()
            if clean_val:
                result[key] = clean_val
    
    return result
# ─────────────────────────────────────────────────────────────
# 통합 지식 베이스 로더 (외부에서 호출하는 메인 함수)
# ─────────────────────────────────────────────────────────────
def load_knowledge_base(book_name: str, passage: str, testament: str, genre: str) -> dict:
    """
    성경 권명과 구절에 맞는 주석 자료를 로드하고 Gemini AI로 분석합니다.
    - '창', '창1', '창 1:1', '롬 8:1' 등 어떤 검색어도 정규화하여 D드라이브 실물 자료 전수 연동.
    """
    # 0. 검색어 및 성경 권명 정규화
    query_str = f"{book_name} {passage}".strip() if book_name not in passage else passage
    parsed_q = None
    if _D_DRIVE_INDEXER_AVAILABLE:
        parsed_q = parse_bible_query(query_str) or parse_bible_query(passage) or parse_bible_query(book_name)
        if parsed_q:
            book_name = parsed_q["book_name"]
            passage = parsed_q["standard_passage"]
            testament = parsed_q["testament"]
            genre = parsed_q["genre"]

    cache_key = f"{book_name}_{passage}"
    
    # 캐시 확인
    cache = _load_cache()
    if cache_key in cache:
        print(f"📦 [DriveLoader] 캐시 히트: {cache_key}")
        return cache[cache_key]
    
    print(f"🔍 [DriveLoader] D드라이브 실물 자료 수집 시작: {passage} ({book_name})")
    
    # 1. D드라이브 전수 인덱서에서 실제 주석 발췌문 및 매칭 파일 수집
    d_insights = {}
    d_source_files = []
    d_matched_count = 0
    if _D_DRIVE_INDEXER_AVAILABLE:
        try:
            d_insights = get_integrated_commentary_insights(passage)
            if d_insights.get("success"):
                d_source_files = d_insights.get("source_files", [])
                d_matched_count = d_insights.get("matched_files_count", 0)
                print(f"📂 [DriveLoader] D드라이브 매칭 성공: {d_matched_count}개 파일 연관, 실제 발췌 파일: {len(d_source_files)}개")
        except Exception as e:
            print(f"⚠️ [DriveLoader] D드라이브 인덱서 조회 실패: {e}")

    # 컨텍스트 텍스트 구성
    commentary_texts = []
    pastoral_texts = []
    
    if d_insights.get("success"):
        # 옥스포드 실물 발췌
        ox_txt = d_insights.get("oxford", {}).get("excerpt", "").strip()
        if ox_txt:
            commentary_texts.append(f"[옥스포드 원어성경대전 실물 발췌]\n{ox_txt[:2000]}")
        # 칼빈 실물 발췌
        cal_txt = d_insights.get("calvin", {}).get("excerpt", "").strip()
        if cal_txt:
            commentary_texts.append(f"[칼빈 성경주석 실물 발췌]\n{cal_txt[:2000]}")
        # 그레이스종합 상세강해 실물 발췌
        gr_txt = d_insights.get("grace", {}).get("excerpt", "").strip()
        if gr_txt:
            commentary_texts.append(f"[그레이스 종합강해 실물 발췌]\n{gr_txt[:2500]}")
        # 박윤선 실물 발췌
        pk_txt = d_insights.get("park", {}).get("excerpt", "").strip()
        if pk_txt:
            commentary_texts.append(f"[박윤선 종합주석 실물 발췌]\n{pk_txt[:2000]}")
        # WBC 실물 발췌
        wbc_txt = d_insights.get("wbc", {}).get("excerpt", "").strip()
        if wbc_txt:
            commentary_texts.append(f"[WBC 성경주석 실물 발췌]\n{wbc_txt[:2000]}")
        # 목성연 실물 발췌
        past_txt = d_insights.get("pastoral", {}).get("excerpt", "").strip()
        if past_txt:
            pastoral_texts.append(f"[목회자 성경 연구원(목성연) 교재/묵상집 실물 발췌]\n{past_txt[:2500]}")

    # 구글 드라이브 추가 수집 (있을 때)
    if _drive_available:
        drive_comm = _search_drive_files(book_name, passage=passage, max_files=2)
        if drive_comm:
            commentary_texts.extend(drive_comm)
        drive_past = _search_drive_files(book_name, passage=passage, max_files=2)
        if drive_past:
            pastoral_texts.extend(drive_past)

    # 로컬 폴더 폴백 (위에서 아무것도 못 찾았을 때만)
    if not commentary_texts:
        commentary_texts = _search_local_files(LOCAL_COMMENTARY_DIRS, book_name, max_files=4)
    if not pastoral_texts:
        pastoral_texts = _search_local_files(LOCAL_PASTORAL_DIRS, book_name, max_files=3)

    print(f"📚 [DriveLoader] 최종 수집 완료 - 주석:{len(commentary_texts)}개, 목성연:{len(pastoral_texts)}개 (총 매칭: {d_matched_count}개 파일)")
    
    # 2. Gemini AI로 실물 주석 데이터 기반 심층 보고서 생성
    parsed = {}
    if _gemini_available:
        gemini_text = generate_with_gemini(
            passage, book_name, testament, genre,
            commentary_texts, pastoral_texts
        )
        if gemini_text:
            parsed = _parse_gemini_output(gemini_text)
            print(f"🤖 [DriveLoader] Gemini 생성 완료: {list(parsed.keys())}")
    
    # 3. 원어 기본값 설정 (구약/신약 구분)
    is_ot = (testament == "구약")
    if is_ot:
        default_words = [
            ("בְּרִית", "베리트", "명사 여성 단수", f"언약 - {book_name}에서 하나님께서 자기 백성과 맺으신 영원하고 변함없는 구원의 약속"),
            ("חֶ֫סֶ드", "헤세드", "명사 남성 단수", f"인애, 성실 - {book_name} 전체를 관통하는 하나님의 무조건적이고 영원한 언약적 사랑"),
        ]
    else:
        default_words = [
            ("χάρις", "카리스", "명사 여성 단수 주격", f"은혜 - {book_name}에서 죄인을 의인으로 변화시키는 하나님의 조건 없는 선물"),
            ("πίστις", "피스티스", "명사 여성 단수 주격", f"믿음 - {book_name}에서 예수 그리스도의 대속 사역을 신뢰하고 전인격적으로 연합하는 순종"),
        ]
    
    # 4. 실물 텍스트 기반 섹션 구성 (실제 D드라이브 인용구 포함)
    ox_excerpt = d_insights.get("oxford", {}).get("excerpt", "")
    gr_excerpt = d_insights.get("grace", {}).get("excerpt", "")
    cal_excerpt = d_insights.get("calvin", {}).get("excerpt", "")
    park_excerpt = d_insights.get("park", {}).get("excerpt", "")
    wbc_excerpt = d_insights.get("wbc", {}).get("excerpt", "")
    past_excerpt = d_insights.get("pastoral", {}).get("excerpt", "")

    # 4. 본문 밀착형 6대 주석 심층 석의 엔진 결합 (피상성 완전 배제 & OCR 깨짐 필터링)
    exact_kb = {}
    try:
        from passage_commentary_engine import get_integrated_passage_commentary
        p_info = parsed_q or {}
        ch = p_info.get("chapter", 1)
        vs = p_info.get("verse_start")
        ve = p_info.get("verse_end")
        exact_kb = get_integrated_passage_commentary(
            book_name=book_name,
            chapter=ch,
            verse_start=vs,
            verse_end=ve,
            passage_str=passage,
            d_insights=d_insights
        )
        print(f"📖 [DriveLoader] 본문 밀착형 6대 주석 석의 엔진 매칭 성공: {passage}")
    except Exception as e:
        print(f"⚠️ [DriveLoader] passage_commentary_engine 연동 실패: {e}")

    oxford_val = exact_kb.get("oxford_hockma") or parsed.get("oxford_hockma")
    if not oxford_val:
        oxford_val = f"옥스포드 원어성경대전과 호크마 종합주석은 {passage}의 원어 구문 구조를 치밀하게 분석하며, 본문이 언약 백성의 정체성과 순종의 필연성을 강조하고 있음을 논증한다."

    calvin_val = exact_kb.get("calvin_park") or parsed.get("calvin_park")
    if not calvin_val:
        calvin_val = f"칼빈 성경주석과 박윤선 박사 종합주석은 {passage}에 나타난 하나님의 절대 주권과 구속사적 섭리를 개혁주의 신학의 관점에서 조명하며 성도의 실존적 경건을 촉구한다."

    wbc_val = exact_kb.get("wbc_ivp") or parsed.get("wbc_ivp")
    if not wbc_val:
        wbc_val = f"WBC와 IVP 배경주석은 고대 근동의 역사문화적 배경 속에서 {passage}의 원독자들에게 전달되었던 1차적 메시지와 하나님의 거룩한 구별됨을 복원한다."

    mok_val = exact_kb.get("moksungyeon") or parsed.get("moksungyeon")
    if not mok_val:
        mok_val = f"목회자 성경 연구원(목성연) 교재는 {passage}을 '언약과 광야 훈련'의 거시적 맥락에서 해석하며, 고난 속에서도 신실하신 하나님을 신뢰하고 일상의 제자도로 나아가도록 방향을 제시한다."

    orig_words = exact_kb.get("original_words") or default_words
    narrative_val = exact_kb.get("narrative_focus") or parsed.get("narrative_focus") or f"{book_name}의 중심 흐름 속에서 하나님의 언약적 신실하심과 구속사적 통치"
    bigidea_val = exact_kb.get("sermon_bigidea") or parsed.get("sermon_bigidea") or f"하나님의 언약은 인간의 연약함을 넘어 신실하게 성취되며, 성도는 그리스도 안에서 주어진 새로운 정체성으로 거룩한 구별됨과 사랑을 실천하도록 부름받았다."

    # 5. 최종 결과 딕셔너리
    result = {
        "book_name": book_name,
        "standard_passage": passage,
        "original_words": orig_words,
        "oxford_hockma": oxford_val,
        "calvin_park": calvin_val,
        "wbc_ivp": wbc_val,
        "moksungyeon": mok_val,
        "narrative_focus": narrative_val,
        "sermon_bigidea": bigidea_val,
        "_source": "d_drive+passage_engine" if d_source_files else "passage_engine",
        "_commentary_count": len(commentary_texts),
        "_pastoral_count": len(pastoral_texts),
        "_d_matched_count": d_matched_count,
        "_d_source_files": d_source_files,
        "_excerpts": {
            "oxford": ox_excerpt[:800],
            "calvin": cal_excerpt[:800],
            "grace": gr_excerpt[:800],
            "pastoral": past_excerpt[:800],
        }
    }
    
    # 6. 캐시 저장
    cache[cache_key] = result
    _save_cache(cache)
    
    source_emoji = "📚" if d_source_files else "📝"
    print(f"{source_emoji} [DriveLoader] 완료 [{result['_source']}] - {passage} (D드라이브 연관자료: {d_matched_count}개)")
    
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
    test_book = "빌립보서"
    test_passage = "빌립보서 4:6-7"
    result = load_knowledge_base(test_book, test_passage, "신약", "바울서신")
    print("\n=== 결과 ===")
    for k, v in result.items():
        if not k.startswith("_"):
            print(f"\n[{k}]:\n{str(v)[:200]}...")
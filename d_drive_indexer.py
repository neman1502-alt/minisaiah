# bible_agent/d_drive_indexer.py
# -*- coding: utf-8 -*-
"""
D드라이브 [1_주석 자료] 및 [2_목회자 성경 연구원 자료] 전수 인덱서 & 본문 텍스트 추출기 (초고속 최적화)
- 사전 컴파일된 정규식으로 D드라이브 수천 개 파일을 1~2초 만에 성경 66권과 완벽 매핑.
"""

import os
import sys
import re
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

try:
    from PyPDF2 import PdfReader
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False

CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent
CATALOG_CACHE_FILE = CURRENT_DIR / "d_drive_catalog.json"

DIR_COMMENTARY = Path(r"D:\1_주석 자료")
DIR_PASTORAL = Path(r"D:\2_목회자 성경 연구원 자료")

try:
    from bible_canon_matcher import BIBLE_66_BOOKS, parse_bible_query
except ImportError:
    sys.path.insert(0, str(CURRENT_DIR))
    from bible_canon_matcher import BIBLE_66_BOOKS, parse_bible_query


# ─────────────────────────────────────────────────────────────
# 단일 패스 초고속 매칭 패턴 구축
# ─────────────────────────────────────────────────────────────
# 권명별 정규식 사전 컴파일
_BOOK_PATTERNS: List[Tuple[str, re.Pattern]] = []
for b in BIBLE_66_BOOKS:
    b_name = b["name"]
    abbr = b["abbr"]
    aliases = [a for a in b["aliases"] if len(a) >= 2]
    
    # 패턴 1: 풀네임 및 2글자 이상 별칭 (예: 창세기, 창세, Genesis, Gen)
    parts = [re.escape(a) for a in aliases]
    # 패턴 2: 1글자 약어 (뒤에 숫자, 장, _, -, 공백 등이 오는 경우)
    parts.append(r"(?:^|[_\s\-\(\)\[\]])" + re.escape(abbr) + r"(?:\d|\s|장|_|\-|\.|\(|$)")
    
    combined_re = re.compile("|".join(parts), re.IGNORECASE)
    _BOOK_PATTERNS.append((b_name, combined_re))


def _find_matching_books(filename: str, folder_name: str) -> List[str]:
    """파일명과 폴더명에서 해당하는 성경 권명들을 초고속 매칭 (복수 권명 매칭 지원)."""
    matched = []
    target = f"{folder_name} {filename}"
    for b_name, pattern in _BOOK_PATTERNS:
        if pattern.search(target):
            matched.append(b_name)
    return matched


# ─────────────────────────────────────────────────────────────
# 카탈로그 빌더
# ─────────────────────────────────────────────────────────────
def build_or_load_catalog(force_rebuild: bool = False) -> Dict[str, Any]:
    if not force_rebuild and CATALOG_CACHE_FILE.exists():
        try:
            with open(CATALOG_CACHE_FILE, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            if catalog.get("_total_books_indexed", 0) >= 66:
                return catalog
        except Exception:
            pass

    print("🔍 [D-Drive Indexer] D드라이브 주석 및 목성연 자료 초고속 인덱싱 시작...")
    start_time = time.time()
    
    books_catalog = {}
    for b in BIBLE_66_BOOKS:
        b_name = b["name"]
        books_catalog[b_name] = {
            "meta": b,
            "oxford": [],
            "calvin": [],
            "park": [],
            "wbc": [],
            "ivp": [],
            "bst": [],
            "grace": [],
            "grand": [],
            "etc_comm": [],
            "pastoral": [],
        }

    valid_exts = {".pdf", ".htm", ".html", ".hwp", ".txt", ".docx"}

    # 1. D:\1_주석 자료 스캔
    if DIR_COMMENTARY.exists():
        for root, _, files in os.walk(DIR_COMMENTARY):
            rname = os.path.basename(root)
            for fname in files:
                if fname.startswith("._") or fname.endswith(".DS_Store"):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in valid_exts:
                    continue

                matched_bnames = _find_matching_books(fname, rname)
                if not matched_bnames:
                    continue

                fstr = os.path.join(root, fname)
                item = {"name": fname, "path": fstr, "ext": ext, "folder": rname}

                # 분류
                for b_name in matched_bnames:
                    if "옥스포드" in fstr or "옥스퍼드" in fstr:
                        books_catalog[b_name]["oxford"].append(item)
                    elif "칼빈" in fstr:
                        books_catalog[b_name]["calvin"].append(item)
                    elif "박윤선" in fstr:
                        books_catalog[b_name]["park"].append(item)
                    elif "WBC" in fstr or "wbc" in fstr:
                        books_catalog[b_name]["wbc"].append(item)
                    elif "IVP" in fstr or "ivp" in fstr:
                        books_catalog[b_name]["ivp"].append(item)
                    elif "BST" in fstr or "bst" in fstr:
                        books_catalog[b_name]["bst"].append(item)
                    elif "그레이스" in fstr:
                        books_catalog[b_name]["grace"].append(item)
                    elif "그랜드" in fstr:
                        books_catalog[b_name]["grand"].append(item)
                    else:
                        books_catalog[b_name]["etc_comm"].append(item)

    # 2. D:\2_목회자 성경 연구원 자료 스캔
    if DIR_PASTORAL.exists():
        for root, _, files in os.walk(DIR_PASTORAL):
            rname = os.path.basename(root)
            for fname in files:
                if fname.startswith("._") or fname.endswith(".DS_Store"):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in valid_exts:
                    continue

                matched_bnames = _find_matching_books(fname, rname)
                if not matched_bnames:
                    continue

                fstr = os.path.join(root, fname)
                item = {"name": fname, "path": fstr, "ext": ext, "folder": rname}

                for b_name in matched_bnames:
                    books_catalog[b_name]["pastoral"].append(item)

    catalog = {
        "_timestamp": time.time(),
        "_total_books_indexed": len(books_catalog),
        "books": books_catalog
    }
    
    try:
        with open(CATALOG_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(catalog, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ [D-Drive Indexer] 캐시 저장 실패: {e}")

    elapsed = time.time() - start_time
    print(f"✅ [D-Drive Indexer] 성경 66권 전수 카탈로그 인덱싱 완료! ({elapsed:.1f}초 소요)")
    return catalog


# ─────────────────────────────────────────────────────────────
# 텍스트 발췌 헬퍼
# ─────────────────────────────────────────────────────────────
def extract_text_from_file(file_path: str, max_chars: int = 5000, target_chapter: Optional[int] = None, target_verse: Optional[int] = None) -> str:
    p = Path(file_path)
    if not p.exists():
        return ""
        
    ext = p.suffix.lower()
    
    if ext in [".htm", ".html"]:
        try:
            try:
                raw = p.read_text(encoding="cp949", errors="replace")
            except Exception:
                raw = p.read_text(encoding="utf-8", errors="replace")
            clean = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL)
            clean = re.sub(r"<script[^>]*>.*?</script>", "", clean, flags=re.DOTALL)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean = re.sub(r"&nbsp;", " ", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            return clean[:max_chars]
        except Exception:
            return ""

    if ext == ".pdf" and _PDF_AVAILABLE:
        try:
            reader = PdfReader(str(p))
            total_pages = len(reader.pages)
            
            chap_keywords = []
            if target_chapter:
                chap_keywords = [
                    f"{target_chapter}장",
                    f"제{target_chapter}장",
                    f"제 {target_chapter} 장",
                    f" {target_chapter}:",
                    f"({target_chapter}:",
                    f"[{target_chapter}:",
                ]
            
            pages_to_check = []
            if total_pages <= 40:
                pages_to_check = list(range(total_pages))
            else:
                pages_to_check = list(range(min(35, total_pages)))
                step = max(5, total_pages // 50)
                pages_to_check.extend(list(range(35, total_pages, step)))

            matched_pages = []
            for p_num in pages_to_check:
                try:
                    ptxt = reader.pages[p_num].extract_text() or ""
                    if any(kw in ptxt for kw in chap_keywords):
                        matched_pages.append(p_num)
                        if len(matched_pages) >= 3:
                            break
                except Exception:
                    continue

            target_indices = matched_pages if matched_pages else [p for p in [20, 30, 40] if p < total_pages]
            collected = []
            for idx in target_indices:
                try:
                    ptxt = reader.pages[idx].extract_text() or ""
                    clean_p = re.sub(r"\s+", " ", ptxt).strip()
                    if len(clean_p) > 80:
                        collected.append(clean_p)
                except Exception:
                    pass

            return "\n\n".join(collected)[:max_chars]
        except Exception:
            return ""

    if ext == ".txt":
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:max_chars]
        except Exception:
            try:
                return p.read_text(encoding="cp949", errors="replace")[:max_chars]
            except Exception:
                return ""

    return ""


# ─────────────────────────────────────────────────────────────
# 성경 본문 검색에 대한 D드라이브 실물 주석 통합 추출기
# ─────────────────────────────────────────────────────────────
def get_integrated_commentary_insights(query_or_passage: str) -> Dict[str, Any]:
    parsed = parse_bible_query(query_or_passage)
    if not parsed:
        return {"success": False, "error": f"인식할 수 없는 성경 검색어: '{query_or_passage}'"}

    book_name = parsed["book_name"]
    chapter = parsed["chapter"]
    verse_start = parsed["verse_start"]
    
    catalog = build_or_load_catalog()
    books = catalog.get("books", {})
    book_entry = books.get(book_name)
    
    if not book_entry:
        return {
            "success": False,
            "parsed": parsed,
            "message": f"D드라이브 카탈로그에 '{book_name}' 관련 자료가 등록되지 않았습니다."
        }

    insights = {
        "success": True,
        "parsed": parsed,
        "book_name": book_name,
        "standard_passage": parsed["standard_passage"],
        "chapter": chapter,
        "matched_files_count": 0,
        "source_files": [],
        "oxford": {"files": [], "excerpt": ""},
        "calvin": {"files": [], "excerpt": ""},
        "park": {"files": [], "excerpt": ""},
        "wbc": {"files": [], "excerpt": ""},
        "ivp": {"files": [], "excerpt": ""},
        "bst": {"files": [], "excerpt": ""},
        "grace": {"files": [], "excerpt": ""},
        "grand": {"files": [], "excerpt": ""},
        "pastoral": {"files": [], "excerpt": ""},
    }

    # 1. 옥스포드
    oxford_list = book_entry.get("oxford", [])
    if oxford_list:
        best_oxford = None
        for f in oxford_list:
            if f"{chapter}장" in f["name"] or f"-{chapter}장" in f["name"] or f"{chapter}-" in f["name"] or f"제{chapter}" in f["name"]:
                best_oxford = f
                break
        if not best_oxford:
            best_oxford = oxford_list[0]
            
        txt = extract_text_from_file(best_oxford["path"], max_chars=3500, target_chapter=chapter, target_verse=verse_start)
        insights["oxford"]["files"].append(best_oxford["name"])
        insights["oxford"]["excerpt"] = txt
        insights["source_files"].append(f"[옥스포드 주석] {best_oxford['name']}")

    # 2. 칼빈
    calvin_list = book_entry.get("calvin", [])
    if calvin_list:
        best_calvin = calvin_list[0]
        txt = extract_text_from_file(best_calvin["path"], max_chars=3000, target_chapter=chapter, target_verse=verse_start)
        insights["calvin"]["files"].append(best_calvin["name"])
        insights["calvin"]["excerpt"] = txt
        insights["source_files"].append(f"[칼빈 성경주석] {best_calvin['name']}")

    # 3. 박윤선
    park_list = book_entry.get("park", [])
    if park_list:
        best_park = park_list[0]
        txt = extract_text_from_file(best_park["path"], max_chars=3000, target_chapter=chapter, target_verse=verse_start)
        insights["park"]["files"].append(best_park["name"])
        insights["park"]["excerpt"] = txt
        insights["source_files"].append(f"[박윤선 박사 주석] {best_park['name']}")

    # 4. WBC
    wbc_list = book_entry.get("wbc", [])
    if wbc_list:
        best_wbc = wbc_list[0]
        txt = extract_text_from_file(best_wbc["path"], max_chars=3000, target_chapter=chapter, target_verse=verse_start)
        insights["wbc"]["files"].append(best_wbc["name"])
        insights["wbc"]["excerpt"] = txt
        insights["source_files"].append(f"[WBC 주석] {best_wbc['name']}")

    # 5. 그레이스종합
    grace_list = book_entry.get("grace", [])
    if grace_list:
        best_grace = None
        chap_pad = f"{chapter:02d}"
        for f in grace_list:
            if f"{chapter}장" in f["name"] or f"{chap_pad}장" in f["name"] or f"창{chap_pad}" in f["name"] or f"마{chap_pad}" in f["name"] or f"롬{chap_pad}" in f["name"]:
                best_grace = f
                break
        if not best_grace:
            best_grace = grace_list[0]
            
        txt = extract_text_from_file(best_grace["path"], max_chars=4000)
        insights["grace"]["files"].append(best_grace["name"])
        insights["grace"]["excerpt"] = txt
        insights["source_files"].append(f"[그레이스 종합강해] {best_grace['name']}")

    # 6. 목성연
    past_list = book_entry.get("pastoral", [])
    if past_list:
        best_past = None
        for f in past_list:
            if "인도자" in f["name"] or "강해" in f["name"] or "묵상" in f["name"]:
                best_past = f
                break
        if not best_past:
            best_past = past_list[0]
            
        txt = extract_text_from_file(best_past["path"], max_chars=3500, target_chapter=chapter, target_verse=verse_start)
        insights["pastoral"]["files"].append(best_past["name"])
        insights["pastoral"]["excerpt"] = txt
        insights["source_files"].append(f"[목회자 성경 연구원] {best_past['name']}")

    total_files = (
        len(oxford_list) + len(calvin_list) + len(park_list) + 
        len(wbc_list) + len(grace_list) + len(book_entry.get("bst", [])) + 
        len(book_entry.get("grand", [])) + len(past_list)
    )
    insights["matched_files_count"] = total_files

    return insights


if __name__ == "__main__":
    test_queries = ["창", "창 1:1", "마 10:34", "롬 8:1"]
    for q in test_queries:
        print(f"\n==========================================")
        print(f"🔎 검색어: '{q}' D드라이브 주석 연동 테스트")
        print(f"==========================================")
        res = get_integrated_commentary_insights(q)
        if res.get("success"):
            print(f"✅ 성경 매칭: {res['standard_passage']} (연관 주석자료: 총 {res['matched_files_count']}개)")
            print(f"📚 실제 인용된 원본 파일 목록:")
            for s in res["source_files"]:
                print(f"   - {s}")
            for cat in ["oxford", "calvin", "grace", "pastoral"]:
                data = res.get(cat, {})
                exc = data.get("excerpt", "")
                if exc:
                    print(f"\n[{cat.upper()} 실제 본문 발췌]:\n{exc[:250]}...")
        else:
            print(f"❌ 실패: {res}")

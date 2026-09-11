# bible_agent/bible_canon_matcher.py
# -*- coding: utf-8 -*-
"""
성경 66권 정규화 & 약어 파서 (Bible Canon Matcher)
- 성경 66권의 전체 이름, 1~2글자 공식 약어, 통칭, 영문명, 영문 약어를 전수 매핑.
- "창", "창세기", "창 1:1", "창1:1-5", "창1", "창1장", "Gen 1:1" 등 모든 검색어를 완벽 파싱.
"""

import os
import sys
import re
from typing import Dict, Any, Optional, List, Tuple

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# 성경 66권 마스터 메타데이터 정의
# ─────────────────────────────────────────────────────────────
BIBLE_66_BOOKS = [
    # [구약 39권]
    # 율법서 (모세오경)
    {"id": 1, "testament": "구약", "genre": "율법서", "name": "창세기", "abbr": "창", "aliases": ["창세기", "창세", "창", "Genesis", "Gen", "Ge", "Gn"], "chapters": 50},
    {"id": 2, "testament": "구약", "genre": "율법서", "name": "출애굽기", "abbr": "출", "aliases": ["출애굽기", "출애굽", "출", "Exodus", "Exod", "Exo", "Ex"], "chapters": 40},
    {"id": 3, "testament": "구약", "genre": "율법서", "name": "레위기", "abbr": "레", "aliases": ["레위기", "레위", "레", "Leviticus", "Lev", "Le", "Lv"], "chapters": 27},
    {"id": 4, "testament": "구약", "genre": "율법서", "name": "민수기", "abbr": "민", "aliases": ["민수기", "민수", "민", "Numbers", "Num", "Nu", "Nm"], "chapters": 36},
    {"id": 5, "testament": "구약", "genre": "율법서", "name": "신명기", "abbr": "신", "aliases": ["신명기", "신명", "신", "Deuteronomy", "Deut", "Deu", "Dt"], "chapters": 34},
    # 역사서
    {"id": 6, "testament": "구약", "genre": "역사서", "name": "여호수아", "abbr": "수", "aliases": ["여호수아", "수아", "수", "Joshua", "Josh", "Jos", "Jsh"], "chapters": 24},
    {"id": 7, "testament": "구약", "genre": "역사서", "name": "사사기", "abbr": "삿", "aliases": ["사사기", "사사", "삿", "사기서", "Judges", "Judg", "Jdg", "Jg"], "chapters": 21},
    {"id": 8, "testament": "구약", "genre": "역사서", "name": "룻기", "abbr": "룻", "aliases": ["룻기", "룻", "Ruth", "Rth", "Ru"], "chapters": 4},
    {"id": 9, "testament": "구약", "genre": "역사서", "name": "사무엘상", "abbr": "삼상", "aliases": ["사무엘상", "삼상", "사무엘상하", "1Samuel", "1Sam", "1Sa", "1S"], "chapters": 31},
    {"id": 10, "testament": "구약", "genre": "역사서", "name": "사무엘하", "abbr": "삼하", "aliases": ["사무엘하", "삼하", "2Samuel", "2Sam", "2Sa", "2S"], "chapters": 24},
    {"id": 11, "testament": "구약", "genre": "역사서", "name": "열왕기상", "abbr": "왕상", "aliases": ["열왕기상", "왕상", "열왕기상하", "1Kings", "1Kgs", "1Ki", "1K"], "chapters": 22},
    {"id": 12, "testament": "구약", "genre": "역사서", "name": "열왕기하", "abbr": "왕하", "aliases": ["열왕기하", "왕하", "2Kings", "2Kgs", "2Ki", "2K"], "chapters": 25},
    {"id": 13, "testament": "구약", "genre": "역사서", "name": "역대상", "abbr": "대상", "aliases": ["역대상", "대상", "역대상하", "1Chronicles", "1Chron", "1Chr", "1Ch"], "chapters": 29},
    {"id": 14, "testament": "구약", "genre": "역사서", "name": "역대하", "abbr": "대하", "aliases": ["역대하", "대하", "2Chronicles", "2Chron", "2Chr", "2Ch"], "chapters": 36},
    {"id": 15, "testament": "구약", "genre": "역사서", "name": "에스라", "abbr": "스", "aliases": ["에스라", "스", "Ezra", "Ezr"], "chapters": 10},
    {"id": 16, "testament": "구약", "genre": "역사서", "name": "느헤미야", "abbr": "느", "aliases": ["느헤미야", "느", "Nehemiah", "Neh", "Ne"], "chapters": 13},
    {"id": 17, "testament": "구약", "genre": "역사서", "name": "에스더", "abbr": "에", "aliases": ["에스더", "에", "Esther", "Esth", "Est", "Es"], "chapters": 10},
    # 시가서
    {"id": 18, "testament": "구약", "genre": "시가서", "name": "욥기", "abbr": "욥", "aliases": ["욥기", "욥", "Job", "Jb"], "chapters": 42},
    {"id": 19, "testament": "구약", "genre": "시가서", "name": "시편", "abbr": "시", "aliases": ["시편", "시", "Psalms", "Psalm", "Psa", "Ps"], "chapters": 150},
    {"id": 20, "testament": "구약", "genre": "시가서", "name": "잠언", "abbr": "잠", "aliases": ["잠언", "잠", "Proverbs", "Prov", "Pro", "Pr"], "chapters": 31},
    {"id": 21, "testament": "구약", "genre": "시가서", "name": "전도서", "abbr": "전", "aliases": ["전도서", "전도", "전", "Ecclesiastes", "Eccl", "Ecc", "Ec"], "chapters": 12},
    {"id": 22, "testament": "구약", "genre": "시가서", "name": "아가", "abbr": "아", "aliases": ["아가", "아", "Song of Songs", "Song", "Sos", "So"], "chapters": 8},
    # 대예언서
    {"id": 23, "testament": "구약", "genre": "예언서", "name": "이사야", "abbr": "사", "aliases": ["이사야", "사", "Isaiah", "Isa", "Is"], "chapters": 66},
    {"id": 24, "testament": "구약", "genre": "예언서", "name": "예레미야", "abbr": "렘", "aliases": ["예레미야", "렘", "Jeremiah", "Jer", "Je"], "chapters": 52},
    {"id": 25, "testament": "구약", "genre": "예언서", "name": "예레미야애가", "abbr": "애", "aliases": ["예레미야애가", "렘애가", "애가", "애", "Lamentations", "Lam", "La"], "chapters": 5},
    {"id": 26, "testament": "구약", "genre": "예언서", "name": "에스겔", "abbr": "겔", "aliases": ["에스겔", "겔", "Ezekiel", "Ezek", "Eze", "Ek"], "chapters": 48},
    {"id": 27, "testament": "구약", "genre": "예언서", "name": "다니엘", "abbr": "단", "aliases": ["다니엘", "단", "Daniel", "Dan", "Da"], "chapters": 12},
    # 소예언서 (소선지서)
    {"id": 28, "testament": "구약", "genre": "예언서", "name": "호세아", "abbr": "호", "aliases": ["호세아", "호", "Hosea", "Hos", "Ho"], "chapters": 14},
    {"id": 29, "testament": "구약", "genre": "예언서", "name": "요엘", "abbr": "욜", "aliases": ["요엘", "욜", "Joel", "Joe", "Jl"], "chapters": 3},
    {"id": 30, "testament": "구약", "genre": "예언서", "name": "아모스", "abbr": "암", "aliases": ["아모스", "암", "Amos", "Amo", "Am"], "chapters": 9},
    {"id": 31, "testament": "구약", "genre": "예언서", "name": "오바댜", "abbr": "옵", "aliases": ["오바댜", "옵", "Obadiah", "Obad", "Ob"], "chapters": 1},
    {"id": 32, "testament": "구약", "genre": "예언서", "name": "요나", "abbr": "욘", "aliases": ["요나", "욘", "Jonah", "Jona", "Jon"], "chapters": 4},
    {"id": 33, "testament": "구약", "genre": "예언서", "name": "미가", "abbr": "미", "aliases": ["미가", "미", "Micah", "Mic", "Mc"], "chapters": 7},
    {"id": 34, "testament": "구약", "genre": "예언서", "name": "나훔", "abbr": "나", "aliases": ["나훔", "나", "Nahum", "Nah", "Na"], "chapters": 3},
    {"id": 35, "testament": "구약", "genre": "예언서", "name": "하박국", "abbr": "합", "aliases": ["하박국", "합", "Habakkuk", "Hab", "Hb"], "chapters": 3},
    {"id": 36, "testament": "구약", "genre": "예언서", "name": "스바냐", "abbr": "습", "aliases": ["스바냐", "습", "Zephaniah", "Zeph", "Zep", "Zp"], "chapters": 3},
    {"id": 37, "testament": "구약", "genre": "예언서", "name": "학개", "abbr": "학", "aliases": ["학개", "학", "Haggai", "Hag", "Hg"], "chapters": 2},
    {"id": 38, "testament": "구약", "genre": "예언서", "name": "스가랴", "abbr": "슥", "aliases": ["스가랴", "슥", "Zechariah", "Zech", "Zec", "Zc"], "chapters": 14},
    {"id": 39, "testament": "구약", "genre": "예언서", "name": "말라기", "abbr": "말", "aliases": ["말라기", "말", "Malachi", "Mal", "Ml"], "chapters": 4},

    # [신약 27권]
    # 복음서
    {"id": 40, "testament": "신약", "genre": "복음서", "name": "마태복음", "abbr": "마", "aliases": ["마태복음", "마태", "마", "Matthew", "Matt", "Mat", "Mt"], "chapters": 28},
    {"id": 41, "testament": "신약", "genre": "복음서", "name": "마가복음", "abbr": "막", "aliases": ["마가복음", "마가", "막", "Mark", "Mar", "Mr", "Mk"], "chapters": 16},
    {"id": 42, "testament": "신약", "genre": "복음서", "name": "누가복음", "abbr": "눅", "aliases": ["누가복음", "누가", "눅", "Luke", "Luk", "Lk"], "chapters": 24},
    {"id": 43, "testament": "신약", "genre": "복음서", "name": "요한복음", "abbr": "요", "aliases": ["요한복음", "요한", "요", "John", "Joh", "Jn"], "chapters": 21},
    # 역사서
    {"id": 44, "testament": "신약", "genre": "역사서", "name": "사도행전", "abbr": "행", "aliases": ["사도행전", "행전", "행", "Acts", "Act", "Ac"], "chapters": 28},
    # 바울서신
    {"id": 45, "testament": "신약", "genre": "바울서신", "name": "로마서", "abbr": "롬", "aliases": ["로마서", "로마", "롬", "Romans", "Rom", "Ro", "Rm"], "chapters": 16},
    {"id": 46, "testament": "신약", "genre": "바울서신", "name": "고린도전서", "abbr": "고전", "aliases": ["고린도전서", "고전", "고린도전후서", "1Corinthians", "1Cor", "1Co"], "chapters": 16},
    {"id": 47, "testament": "신약", "genre": "바울서신", "name": "고린도후서", "abbr": "고후", "aliases": ["고린도후서", "고후", "2Corinthians", "2Cor", "2Co"], "chapters": 13},
    {"id": 48, "testament": "신약", "genre": "바울서신", "name": "갈라디아서", "abbr": "갈", "aliases": ["갈라디아서", "갈라디아", "갈", "Galatians", "Gal", "Ga"], "chapters": 6},
    {"id": 49, "testament": "신약", "genre": "바울서신", "name": "에베소서", "abbr": "엡", "aliases": ["에베소서", "에베소", "엡", "Ephesians", "Eph", "Ep"], "chapters": 6},
    {"id": 50, "testament": "신약", "genre": "바울서신", "name": "빌립보서", "abbr": "빌", "aliases": ["빌립보서", "빌립보", "빌", "Philippians", "Phil", "Php", "Pp"], "chapters": 4},
    {"id": 51, "testament": "신약", "genre": "바울서신", "name": "골로새서", "abbr": "골", "aliases": ["골로새서", "골로새", "골", "Colossians", "Col", "Co"], "chapters": 4},
    {"id": 52, "testament": "신약", "genre": "바울서신", "name": "데살로니가전서", "abbr": "살전", "aliases": ["데살로니가전서", "데살전", "살전", "1Thessalonians", "1Thess", "1Th"], "chapters": 5},
    {"id": 53, "testament": "신약", "genre": "바울서신", "name": "데살로니가후서", "abbr": "살후", "aliases": ["데살로니가후서", "데살후", "살후", "2Thessalonians", "2Thess", "2Th"], "chapters": 3},
    {"id": 54, "testament": "신약", "genre": "바울서신", "name": "디모데전서", "abbr": "딤전", "aliases": ["디모데전서", "딤전", "디모데전후서", "1Timothy", "1Tim", "1Ti"], "chapters": 6},
    {"id": 55, "testament": "신약", "genre": "바울서신", "name": "디모데후서", "abbr": "딤후", "aliases": ["디모데후서", "딤후", "2Timothy", "2Tim", "2Ti"], "chapters": 4},
    {"id": 56, "testament": "신약", "genre": "바울서신", "name": "디도서", "abbr": "딛", "aliases": ["디도서", "디도", "딛", "Titus", "Tit", "Ti"], "chapters": 3},
    {"id": 57, "testament": "신약", "genre": "바울서신", "name": "빌레몬서", "abbr": "몬", "aliases": ["빌레몬서", "빌레몬", "몬", "Philemon", "Philem", "Phm", "Pm"], "chapters": 1},
    # 일반서신
    {"id": 58, "testament": "신약", "genre": "일반서신", "name": "히브리서", "abbr": "히", "aliases": ["히브리서", "히브리", "히", "Hebrews", "Heb", "He"], "chapters": 13},
    {"id": 59, "testament": "신약", "genre": "일반서신", "name": "야고보서", "abbr": "약", "aliases": ["야고보서", "야고보", "약", "James", "Jas", "Jm"], "chapters": 5},
    {"id": 60, "testament": "신약", "genre": "일반서신", "name": "베드로전서", "abbr": "벧전", "aliases": ["베드로전서", "벧전", "베드로전후서", "1Peter", "1Pet", "1Pe", "1P"], "chapters": 5},
    {"id": 61, "testament": "신약", "genre": "일반서신", "name": "베드로후서", "abbr": "벧후", "aliases": ["베드로후서", "벧후", "2Peter", "2Pet", "2Pe", "2P"], "chapters": 3},
    {"id": 62, "testament": "신약", "genre": "일반서신", "name": "요한일서", "abbr": "요일", "aliases": ["요한일서", "요일", "요한1서", "1John", "1Jn", "1Jo"], "chapters": 5},
    {"id": 63, "testament": "신약", "genre": "일반서신", "name": "요한이서", "abbr": "요이", "aliases": ["요한이서", "요이", "요한2서", "2John", "2Jn", "2Jo"], "chapters": 1},
    {"id": 64, "testament": "신약", "genre": "일반서신", "name": "요한삼서", "abbr": "요삼", "aliases": ["요한삼서", "요삼", "요한3서", "3John", "3Jn", "3Jo"], "chapters": 1},
    {"id": 65, "testament": "신약", "genre": "일반서신", "name": "유다서", "abbr": "유", "aliases": ["유다서", "유다", "유", "Jude", "Jud", "Jd"], "chapters": 1},
    # 예언서 (종말론)
    {"id": 66, "testament": "신약", "genre": "신약예언서", "name": "요한계시록", "abbr": "계", "aliases": ["요한계시록", "계시록", "계시", "계", "Revelation", "Rev", "Re", "Rv"], "chapters": 22},
]

# ─────────────────────────────────────────────────────────────
# 빠른 조회를 위한 딕셔너리 구축 (긴 이름부터 매칭되도록 정렬)
# ─────────────────────────────────────────────────────────────
_ALIAS_TO_BOOK: Dict[str, dict] = {}
for b in BIBLE_66_BOOKS:
    for alias in b["aliases"]:
        _ALIAS_TO_BOOK[alias.lower()] = b
    _ALIAS_TO_BOOK[b["name"].lower()] = b
    _ALIAS_TO_BOOK[b["abbr"].lower()] = b

# 긴 별칭부터 우선 검사하기 위한 정렬된 별칭 리스트
_SORTED_ALIASES = sorted(_ALIAS_TO_BOOK.keys(), key=lambda x: len(x), reverse=True)


# ─────────────────────────────────────────────────────────────
# 검색어 정밀 파싱 함수
# ─────────────────────────────────────────────────────────────
def parse_bible_query(query: str) -> Optional[dict]:
    """
    사용자가 입력한 검색어를 분석하여 정확한 성경 권명, 장, 절 정보를 도출합니다.
    
    입력 예시:
      - '창' ➔ 창세기 전체 (기본 1장)
      - '창세기' ➔ 창세기 1장
      - '창 1:1' ➔ 창세기 1:1
      - '창1:1-5' ➔ 창세기 1:1-5
      - '창1' / '창1장' ➔ 창세기 1장
      - '출애굽기 20장' ➔ 출애굽기 20장
      - '롬 8:1-11' ➔ 로마서 8:1-11
      - 'Gen 1:1' ➔ 창세기 1:1
    """
    if not query or not query.strip():
        return None
    
    raw = query.strip()
    norm = re.sub(r"\s+", " ", raw)
    
    matched_book = None
    remaining_text = ""
    
    # 1. 긴 별칭부터 앞부분 또는 전체 매칭 시도
    # 예: '요한복음 1:43-51' ➔ alias '요한복음'
    # 예: '요일 1:9' ➔ alias '요일' (요보다 먼저 매칭되어야 함)
    # 예: '삼상 1:1' ➔ alias '삼상' (사보다 먼저 매칭)
    for alias in _SORTED_ALIASES:
        # 단어 경계 또는 문자 뒤에 공백/숫자가 오는 경우
        pattern = r"^" + re.escape(alias) + r"(\b|\d|\s|$|장)"
        m = re.search(pattern, norm, re.IGNORECASE)
        if m:
            matched_book = _ALIAS_TO_BOOK[alias]
            remaining_text = norm[len(alias):].strip()
            break
            
    if not matched_book:
        # 끝이나 중간에 권명이 있는 경우 (예: "성경 창세기")
        for alias in _SORTED_ALIASES:
            if alias in norm.lower():
                matched_book = _ALIAS_TO_BOOK[alias]
                # 권명 이후 부분 추출
                idx = norm.lower().find(alias)
                remaining_text = norm[idx + len(alias):].strip()
                break

    if not matched_book:
        return None

    # 2. 장/절 파싱
    chapter = 1
    verse_start = None
    verse_end = None
    
    # 남은 텍스트에서 장/절 패턴 추출
    # 패턴 예: "1:43-51", "1장 43-51절", "1:1", "1장", "1", "1 1", "1:43~51"
    cv_pattern = r"(?:(\d+)\s*장\s*)?(?:(\d+)\s*[:장\s]\s*(\d+)(?:\s*[-~]\s*(\d+))?)?"
    
    clean_rem = remaining_text.replace("절", "").strip()
    
    # 케이스 A: "1:43-51" 또는 "1:43~51"
    m_cv = re.search(r"(\d+)\s*:\s*(\d+)(?:\s*[-~]\s*(\d+))?", clean_rem)
    if m_cv:
        chapter = int(m_cv.group(1))
        verse_start = int(m_cv.group(2))
        if m_cv.group(3):
            verse_end = int(m_cv.group(3))
        else:
            verse_end = verse_start
    else:
        # 케이스 B: "1장 43-51" 또는 "1장 43절"
        m_chap_v = re.search(r"(\d+)\s*장(?:\s*(\d+)(?:\s*[-~]\s*(\d+))?)?", clean_rem)
        if m_chap_v:
            chapter = int(m_chap_v.group(1))
            if m_chap_v.group(2):
                verse_start = int(m_chap_v.group(2))
                if m_chap_v.group(3):
                    verse_end = int(m_chap_v.group(3))
                else:
                    verse_end = verse_start
        else:
            # 케이스 C: 숫자만 남은 경우 (예: "창 1", "창 1 1", "창1")
            m_nums = re.findall(r"\d+", clean_rem)
            if len(m_nums) == 1:
                chapter = int(m_nums[0])
            elif len(m_nums) >= 2:
                chapter = int(m_nums[0])
                verse_start = int(m_nums[1])
                if len(m_nums) >= 3:
                    verse_end = int(m_nums[2])
                else:
                    verse_end = verse_start

    # 장 번호 검증 (최대 장 수 초과 방지)
    if chapter > matched_book["chapters"]:
        chapter = matched_book["chapters"]
    if chapter <= 0:
        chapter = 1

    # 표준 구절 문자열 생성
    book_name = matched_book["name"]
    if verse_start is not None:
        if verse_end is not None and verse_end != verse_start:
            standard_passage = f"{book_name} {chapter}:{verse_start}-{verse_end}"
            verse_str = f"{verse_start}-{verse_end}"
        else:
            standard_passage = f"{book_name} {chapter}:{verse_start}"
            verse_str = f"{verse_start}"
    else:
        standard_passage = f"{book_name} {chapter}장"
        verse_str = ""

    canon_str = f"{matched_book['id']:02d}"

    return {
        "success": True,
        "input_query": query,
        "book_id": matched_book["id"],
        "canon_str": canon_str,
        "book_name": book_name,
        "short_name": matched_book["abbr"],
        "testament": matched_book["testament"],
        "genre": matched_book["genre"],
        "total_chapters": matched_book["chapters"],
        "chapter": chapter,
        "verse_start": verse_start,
        "verse_end": verse_end,
        "verse_str": verse_str,
        "standard_passage": standard_passage,
        "keywords": matched_book["aliases"],
    }


# ─────────────────────────────────────────────────────────────
# 간이 테스트
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_queries = [
        "창", "창세기", "창 1:1", "창1:1-5", "창1", "창 1장 1-3절",
        "출", "출애굽기 20:1-17", "레 19:2", "민1:47-54", "신 6:4-9",
        "삼상", "왕상 19:1-8", "시 119:17-32", "사 53:5", "단 12:3",
        "마", "마 10:34-39", "요1:43-51", "롬 8:1-11", "계 22:20", "Gen 1:1"
    ]
    print(f"=== 성경 66권 매칭 테스트 ({len(test_queries)}개) ===")
    for q in test_queries:
        res = parse_bible_query(q)
        if res:
            print(f"'{q}' ➔ [{res['canon_str']}] {res['book_name']} ({res['short_name']}) | 표준: {res['standard_passage']} | {res['testament']}/{res['genre']}")
        else:
            print(f"'{q}' ➔ 매칭 실패!")

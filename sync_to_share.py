import os
import sys
import json
import shutil
import re
from pathlib import Path

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
SHARE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = SHARE_DIR / "reports"
INDEX_HTML_PATH = SHARE_DIR / "index.html"

# 성경 66권 정경 순서 목록
BIBLE_CANON_ORDER = [
    # 구약 39권
    "창세기", "출애굽기", "레위기", "민수기", "신명기",
    "여호수아", "사사기", "룻기", "사무엘상", "사무엘하", "열왕기상", "열왕기하",
    "역대상", "역대하", "에스라", "느헤미야", "에스더",
    "욥기", "시편", "잠언", "전도서", "아가",
    "이사야", "예레미야", "예레미야애가", "에스겔", "다니엘",
    "호세아", "요엘", "아모스", "오바댜", "요나", "미가",
    "나훔", "하박국", "스바냐", "학개", "스가랴", "말라기",
    # 신약 27권
    "마태복음", "마가복음", "누가복음", "요한복음",
    "사도행전",
    "로마서", "고린도전서", "고린도후서", "갈라디아서", "에베소서", "빌립보서", "골로새서",
    "데살로니가전서", "데살로니가후서", "디모데전서", "디모데후서", "디도서", "빌레몬서",
    "히브리서", "야고보서", "베드로전서", "베드로후서", "요한일서", "요한이서", "요한삼서", "유다서",
    "요한계시록"
]

def get_canon_index(book_name: str) -> int:
    try:
        return BIBLE_CANON_ORDER.index(book_name)
    except ValueError:
        return 999

# 성경별 정경 분류 사전
CANON_CATEGORY_MAP = {
    # 구약 율법서
    "창세기": ("구약", "율법서"), "출애굽기": ("구약", "율법서"), "레위기": ("구약", "율법서"),
    "민수기": ("구약", "율법서"), "신명기": ("구약", "율법서"),
    # 구약 역사서
    "여호수아": ("구약", "역사서"), "사사기": ("구약", "역사서"), "룻기": ("구약", "역사서"),
    "사무엘상": ("구약", "역사서"), "사무엘하": ("구약", "역사서"), "열왕기상": ("구약", "역사서"),
    "열왕기하": ("구약", "역사서"), "역대상": ("구약", "역사서"), "역대하": ("구약", "역사서"),
    "에스라": ("구약", "역사서"), "느헤미야": ("구약", "역사서"), "에스더": ("구약", "역사서"),
    # 구약 시가서
    "욥기": ("구약", "시가서"), "시편": ("구약", "시가서"), "잠언": ("구약", "시가서"),
    "전도서": ("구약", "시가서"), "아가": ("구약", "시가서"),
    # 구약 예언서
    "이사야": ("구약", "예언서"), "예레미야": ("구약", "예언서"), "예레미야애가": ("구약", "예언서"),
    "에스겔": ("구약", "예언서"), "다니엘": ("구약", "예언서"), "호세아": ("구약", "예언서"),
    "요엘": ("구약", "예언서"), "아모스": ("구약", "예언서"), "오바댜": ("구약", "예언서"),
    "요나": ("구약", "예언서"), "미가": ("구약", "예언서"), "나훔": ("구약", "예언서"),
    "하박국": ("구약", "예언서"), "스바냐": ("구약", "예언서"), "학개": ("구약", "예언서"),
    "스가랴": ("구약", "예언서"), "말라기": ("구약", "예언서"),
    # 신약 복음서
    "마태복음": ("신약", "복음서"), "마가복음": ("신약", "복음서"), "누가복음": ("신약", "복음서"),
    "요한복음": ("신약", "복음서"),
    # 신약 역사서
    "사도행전": ("신약", "역사서"),
    # 신약 바울서신
    "로마서": ("신약", "바울서신"), "고린도전서": ("신약", "바울서신"), "고린도후서": ("신약", "바울서신"),
    "갈라디아서": ("신약", "바울서신"), "에베소서": ("신약", "바울서신"), "빌립보서": ("신약", "바울서신"),
    "골로새서": ("신약", "바울서신"), "데살로니가전서": ("신약", "바울서신"), "데살로니가후서": ("신약", "바울서신"),
    "디모데전서": ("신약", "바울서신"), "디모데후서": ("신약", "바울서신"), "디도서": ("신약", "바울서신"),
    "빌레몬서": ("신약", "바울서신"),
    # 신약 일반서신
    "히브리서": ("신약", "일반서신"), "야고보서": ("신약", "일반서신"), "베드로전서": ("신약", "일반서신"),
    "베드로후서": ("신약", "일반서신"), "요한일서": ("신약", "일반서신"), "요한이서": ("신약", "일반서신"),
    "요한삼서": ("신약", "일반서신"), "유다서": ("신약", "일반서신"),
    # 신약 예언서
    "요한계시록": ("신약", "예언서")
}

# 기본 메타데이터 설정 (사전 등록된 주요 마스터 보고서)
BIBLE_CANON_CONFIG = {
    "민수기": {
        "testament": "구약",
        "genre": "율법서",
        "passage": "민수기 1:47-54",
        "title": "민수기 1:47-54 심층 학술 석의 및 강해설교 대전",
        "subtitle": "거룩한 진노를 막아서는 영적 방파제: 레위인의 성막 수호, 배타적 성별의 사명, 그리고 그리스도의 대속적 중보",
        "master_filename": "민수기_1-47-54_통합_마스터_연구보고서",
        "tags": ["레위인 성별", "증거의 성막", "영적 방파제", "진노(케체프) 방어", "외인 사형", "대속적 중보"]
    },
    "레위기": {
        "testament": "구약",
        "genre": "율법서",
        "passage": "레위기 19:2",
        "title": "레위기 19:2 심층 학술 석의 및 강해설교 대전",
        "subtitle": "너희는 거룩하라 이는 나 여호와 너희 하나님이 거룩함이니라: 제의적 구별에서 일상과 사회 정의의 실천으로",
        "master_filename": "레위기_19-2_통합_마스터_연구보고서",
        "tags": ["카도시(거룩)", "거룩 법전", "모퉁이 곡식", "타자 윤리", "일상의 성결", "이웃 사랑"]
    },
    "시편": {
        "testament": "구약",
        "genre": "시가서",
        "passage": "시편 119:17-32",
        "title": "시편 119:17-32 심층 학술 석의 및 강해설교 대전",
        "subtitle": "내 눈을 열어 주의 법의 기이한 것을 보게 하소서: 영적 맹목의 치유, 나그네 실존, 생명의 말씀",
        "master_filename": "시편_119-17-32_통합_마스터_연구보고서",
        "tags": ["갈-에이나이", "답관체(Acrostic)", "신경가소성", "나그네 실존", "진토에서의 소생"]
    },
    "다니엘": {
        "testament": "구약",
        "genre": "예언서",
        "passage": "다니엘 12:3",
        "title": "다니엘 12:3 심층 학술 석의 및 강해설교 대전",
        "subtitle": "밤하늘의 별처럼 영원히 빛나는 삶: 종말론적 소망, 고난 속의 지혜자, 많은 사람을 옳은 데로 인도하는 사명",
        "master_filename": "다니엘_12-3_통합_마스터_연구보고서",
        "tags": ["마스킬림(지혜자)", "궁창의 빛", "영원한 별빛", "몸의 부활", "프레이밍 효과"]
    },
    "마태복음": {
        "testament": "신약",
        "genre": "복음서",
        "passage": "마태복음 8:28-34",
        "title": "마태복음 8:28-34 심층 학술 석의 및 강해설교 대전",
        "subtitle": "무덤가의 광인 치유와 돼지 떼 사건: 사탄적 결박의 해체, 경제적 손실 회피 편향 vs 한 영혼의 절대적 가치",
        "master_filename": "마태복음_8-28-34_통합_마스터_연구보고서",
        "tags": ["가다라 광인", "돼지 떼", "사탄 결박 해체", "손실 회피 편향", "한 영혼의 가치"]
    },
    "요한복음": {
        "testament": "신약",
        "genre": "복음서",
        "passage": "요한복음 1:43-51",
        "title": "요한복음 1:43-51 심층 학술 석의 및 강해설교 대전",
        "subtitle": "무화과나무 아래에서 열린 하늘을 보라: 1~4단계 무삭제 석의, 벧엘 사닥다리 4대 모형론 및 6대 다학제 팩트체크",
        "master_filename": "요한복음_1-43-51_통합_마스터_연구보고서",
        "tags": ["빌립과 나다나엘", "와서 보라", "무화과나무 아래", "벧엘 사닥다리", "확증 편향 해체"]
    }
}

def scan_and_sync_all_reports():
    print("🔄 [Share Sync] '올인원 마스터 대통합 보고서' 전용 동기화 시작...")
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    processed_books = set()

    # 1. BIBLE_CANON_CONFIG에 정의된 보고서 우선 처리
    for book_name, meta in BIBLE_CANON_CONFIG.items():
        processed_books.add(book_name)
        book_script_dir = SCRIPTS_DIR / book_name
        book_share_dir = REPORTS_DIR / book_name
        book_share_dir.mkdir(parents=True, exist_ok=True)

        master_stem = meta["master_filename"]
        
        src_html = (book_script_dir / f"{master_stem}.html") if (book_script_dir / f"{master_stem}.html").exists() else (SCRIPTS_DIR / f"{master_stem}.html")
        src_pdf = (book_script_dir / f"{master_stem}.pdf") if (book_script_dir / f"{master_stem}.pdf").exists() else (SCRIPTS_DIR / f"{master_stem}.pdf")
        src_md = (book_script_dir / f"{master_stem}.md") if (book_script_dir / f"{master_stem}.md").exists() else (SCRIPTS_DIR / f"{master_stem}.md")

        if src_html.exists():
            dst_html = book_share_dir / f"{master_stem}.html"
            if src_html.resolve() != dst_html.resolve():
                shutil.copy2(src_html, dst_html)
            
            book_script_dir.mkdir(parents=True, exist_ok=True)
            dst_script_html = book_script_dir / f"{master_stem}.html"
            if src_html.resolve() != dst_script_html.resolve():
                shutil.copy2(src_html, dst_script_html)
            
            if src_pdf.exists():
                dst_pdf = book_share_dir / f"{master_stem}.pdf"
                if src_pdf.resolve() != dst_pdf.resolve():
                    shutil.copy2(src_pdf, dst_pdf)
                dst_script_pdf = book_script_dir / f"{master_stem}.pdf"
                if src_pdf.resolve() != dst_script_pdf.resolve():
                    shutil.copy2(src_pdf, dst_script_pdf)

            if src_md.exists():
                dst_md = book_share_dir / f"{master_stem}.md"
                if src_md.resolve() != dst_md.resolve():
                    shutil.copy2(src_md, dst_md)
                dst_script_md = book_script_dir / f"{master_stem}.md"
                if src_md.resolve() != dst_script_md.resolve():
                    shutil.copy2(src_md, dst_script_md)

            manifest.append({
                "id": f"{book_name}-master",
                "book": book_name,
                "testament": meta["testament"],
                "genre": meta["genre"],
                "passage": meta["passage"],
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "date": "2026-09-09",
                "badge": "🌟 올인원 마스터 대통합 보고서",
                "htmlUrl": f"reports/{book_name}/{master_stem}.html",
                "pdfUrl": f"reports/{book_name}/{master_stem}.pdf" if src_pdf.exists() else None,
                "mdUrl": f"reports/{book_name}/{master_stem}.md" if src_md.exists() else None,
                "tags": meta["tags"]
            })

    # 2. scripts/ 디렉토리를 자동 스캔하여 추가로 발견된 마스터 보고서 자동 등록
    for item in SCRIPTS_DIR.glob("*_통합_마스터_연구보고서.html"):
        stem = item.stem
        # 예: 창세기_1-1-5_통합_마스터_연구보고서
        parts = stem.split("_")
        book_name = parts[0]
        if book_name in processed_books:
            continue
        
        passage_raw = parts[1] if len(parts) > 1 else ""
        passage_formatted = f"{book_name} {passage_raw.replace('-', ':')}"
        testament, genre = CANON_CATEGORY_MAP.get(book_name, ("성경", "연구"))

        book_share_dir = REPORTS_DIR / book_name
        book_share_dir.mkdir(parents=True, exist_ok=True)
        
        dst_share_html = book_share_dir / f"{stem}.html"
        if item.resolve() != dst_share_html.resolve():
            shutil.copy2(item, dst_share_html)

        src_pdf = item.with_suffix(".pdf")
        src_md = item.with_suffix(".md")
        if src_pdf.exists():
            dst_pdf = book_share_dir / f"{stem}.pdf"
            if src_pdf.resolve() != dst_pdf.resolve():
                shutil.copy2(src_pdf, dst_pdf)
        if src_md.exists():
            dst_md = book_share_dir / f"{stem}.md"
            if src_md.resolve() != dst_md.resolve():
                shutil.copy2(src_md, dst_md)

        manifest.append({
            "id": f"{book_name}-master",
            "book": book_name,
            "testament": testament,
            "genre": genre,
            "passage": passage_formatted,
            "title": f"{passage_formatted} 심층 학술 석의 및 강해설교 대전",
            "subtitle": f"{passage_formatted} 올인원 마스터 대통합 연구보고서",
            "date": "2026-09-09",
            "badge": "🌟 올인원 마스터 대통합 보고서",
            "htmlUrl": f"reports/{book_name}/{stem}.html",
            "pdfUrl": f"reports/{book_name}/{stem}.pdf" if src_pdf.exists() else None,
            "mdUrl": f"reports/{book_name}/{stem}.md" if src_md.exists() else None,
            "tags": [book_name, genre, "마스터보고서", "원어석의", "강해설교"]
        })
        processed_books.add(book_name)

    # 3. 성경 66권 정경 순서(Canon Order)로 정밀 정렬
    manifest.sort(key=lambda x: get_canon_index(x["book"]))

    # 4. reports_data.json 저장
    json_path = SHARE_DIR / "reports_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 5. index.html의 masterReports 배열 자동 갱신
    if INDEX_HTML_PATH.exists():
        update_index_html_data(manifest)

    print(f"🎉 총 {len(manifest)}개의 '올인원 마스터 대통합 보고서'가 대시보드에 완벽 동기화되었습니다!")
    for item in manifest:
        print(f"  - [{item['testament']}/{item['genre']}] {item['passage']} -> {item['htmlUrl']}")

def update_index_html_data(manifest):
    with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    json_str = json.dumps(manifest, ensure_ascii=False, indent=6)
    # const masterReports = [...]; 블록을 찾아 최신 데이터로 치환
    pattern = r"(const\s+masterReports\s*=\s*)\[[\s\S]*?\];"
    replacement = f"\\1{json_str};"
    
    if re.search(pattern, content):
        new_content = re.sub(pattern, replacement, content, count=1)
        with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("✅ [index.html] 대시보드 내 masterReports 데이터가 최신으로 자동 업데이트되었습니다!")
    else:
        print("⚠️ [index.html] masterReports 선언 블록을 찾지 못해 index.html을 직접 수정하지 못했습니다.")

if __name__ == "__main__":
    scan_and_sync_all_reports()


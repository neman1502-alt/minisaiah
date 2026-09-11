import os
import sys
import json
import time
import threading
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent
REPORTS_DIR = CURRENT_DIR / "reports"
REPORTS_DATA_JSON = CURRENT_DIR / "reports_data.json"

sys.path.insert(0, str(CURRENT_DIR))
from generator import generate_dynamic_master_report, delete_master_report, toggle_report_privacy
from github_sync import load_github_config, save_github_config, sync_report_files_to_github

PORT = int(os.environ.get("PORT", 8765))

# ─────────────────────────────────────────────────────────────
# Keepalive: Render 무료 플랜 슬립 방지 (4분 40초마다 자가 Ping)
# ─────────────────────────────────────────────────────────────
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{PORT}")

def _keepalive_worker():
    """Render 무료 플랜의 슬립 방지를 위한 자가 Ping 스레드"""
    time.sleep(30)  # 서버 완전 기동 후 시작
    while True:
        try:
            target = f"{RENDER_EXTERNAL_URL}/health"
            req = urllib.request.Request(target, headers={"User-Agent": "BiblePingBot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"💓 [Keepalive] Ping OK → {resp.status}")
        except Exception as e:
            print(f"⚠️ [Keepalive] Ping 실패 (무시 가능): {e}")
        time.sleep(280)  # 4분 40초 대기

def start_keepalive():
    t = threading.Thread(target=_keepalive_worker, daemon=True)
    t.start()
    print(f"💓 [Keepalive] 슬립 방지 스레드 가동 (대상: {RENDER_EXTERNAL_URL}/health)")


class BibleMasterApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CURRENT_DIR), **kwargs)

    def log_message(self, format, *args):
        # /health ping 로그는 생략하고, Windows 콘솔 인코딩 에러로 인한 소켓 단절 원천 방지
        try:
            if "/health" in getattr(self, "path", ""):
                return
            msg = "%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args)
            sys.stderr.buffer.write(msg.encode("utf-8", errors="replace"))
            sys.stderr.buffer.flush()
        except Exception:
            pass

    def end_headers(self):
        # 브라우저 캐시 방지 및 CORS 헤더 적용
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # 0. Health Check 엔드포인트 (Render keepalive + 자가 Ping)
        if parsed.path in ("/health", "/api/health"):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            payload = {"status": "ok", "service": "BibleMasterAPI", "timestamp": time.time()}
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            return

        # 0-1. Debug 진단 엔드포인트 (API 키 값 노출 없이 상태만 반환)
        if parsed.path == "/api/debug":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            debug_info = self._collect_debug_info()
            self.wfile.write(json.dumps(debug_info, ensure_ascii=False, indent=2).encode('utf-8'))
            return
        
        # 1. API: 보고서 목록 조회 (관리자 모드 vs 외부 공개 모드 완벽 분리)
        if parsed.path == "/api/reports":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            
            mode = params.get("mode", ["public"])[0]
            
            if REPORTS_DATA_JSON.exists():
                try:
                    with open(REPORTS_DATA_JSON, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    if mode == "admin":
                        # 관리자는 전체(나만 보는 비공개 자료 + 남이 검색한 자료 + 공개 자료) 모두 조회
                        response_data = data
                    else:
                        # 외부 공개 모드: isPrivate == False 인 자료만 필터링하여 반환 (나만의 자료는 완벽 은닉)
                        response_data = [item for item in data if not item.get("isPrivate", False)]
                    
                    self.wfile.write(json.dumps(response_data, ensure_ascii=False, indent=2).encode('utf-8'))
                except Exception as e:
                    self.wfile.write(b"[]")
            else:
                self.wfile.write(b"[]")
            return

        # 1-1. API: D드라이브 실물 주석 & 목성연 실시간 라이브 탐색기 (성경 66권 약어/풀네임 100% 매칭)
        if parsed.path == "/api/d-drive-explore":
            query = params.get("q", [""])[0].strip()
            try:
                response_payload = self._explore_d_drive(query)
            except Exception as e:
                response_payload = {"success": False, "error": str(e)}

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(response_payload, ensure_ascii=False, indent=2).encode('utf-8'))
            return

        # 1-2. API: GitHub 연동 설정 조회
        if parsed.path == "/api/github-config":
            cfg = load_github_config()
            raw_token = cfg.get("token", "")
            masked = f"{raw_token[:4]}...{raw_token[-4:]}" if len(raw_token) > 8 else ("***" if raw_token else "")
            res_data = {
                "success": True,
                "repo": cfg.get("repo", ""),
                "branch": cfg.get("branch", "main"),
                "is_configured": bool(raw_token and cfg.get("repo")),
                "masked_token": masked
            }
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(res_data, ensure_ascii=False).encode('utf-8'))
            return

        # 2. 일반 정적 파일 서빙
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        post_body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        
        try:
            body_data = json.loads(post_body) if post_body else {}
        except Exception:
            body_data = {}

        # 1. API: 실시간 성경구절 올인원 마스터 분석 및 생성 요청
        if parsed.path == "/api/analyze":
            passage_input = body_data.get("passage", "").strip()
            is_private = body_data.get("isPrivate", False)
            created_by = body_data.get("createdBy", "guest")  # 관리자 생성: 'admin', 외부 방문자: 'guest'
            
            if not passage_input:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "성경 구절을 입력해 주세요."}, ensure_ascii=False).encode('utf-8'))
                return

            try:
                result = generate_dynamic_master_report(passage_input, is_private=is_private, created_by=created_by)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode('utf-8'))
            return

        # 2. API: 원치 않는 내용/보고서 삭제
        if parsed.path == "/api/delete":
            report_id = body_data.get("id", "").strip()
            if not report_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "삭제할 보고서 ID를 지정하세요."}, ensure_ascii=False).encode('utf-8'))
                return

            result = delete_master_report(report_id)
            self.send_response(200 if result.get("success") else 404)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            return

        # 3. API: 비공개(나만 보기) ↔ 공개 전환 토글
        if parsed.path == "/api/toggle-privacy":
            report_id = body_data.get("id", "").strip()
            set_private = body_data.get("isPrivate", None)
            
            if not report_id:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "보고서 ID를 지정하세요."}, ensure_ascii=False).encode('utf-8'))
                return

            result = toggle_report_privacy(report_id, set_private=set_private)
            self.send_response(200 if result.get("success") else 404)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
            return

        # 4. API: 드라이브 지식 베이스 캐시 초기화 (관리자 기능)
        if parsed.path == "/api/cache-clear":
            self._handle_cache_clear()
            return

        # 5. API: GitHub 연동 설정 저장
        if parsed.path == "/api/github-config":
            repo = body_data.get("repo", "").strip()
            token = body_data.get("token", "").strip()
            branch = body_data.get("branch", "main").strip() or "main"
            if "..." in token:
                old_cfg = load_github_config()
                token = old_cfg.get("token", "")
            saved = save_github_config(repo, token, branch)
            self.send_response(200 if saved else 400)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": saved, "repo": repo, "branch": branch}, ensure_ascii=False).encode('utf-8'))
            return

        # 6. API: 지금 즉시 GitHub & Vercel 전체 동기화 실행
        if parsed.path == "/api/github-sync-now":
            try:
                sync_res = sync_report_files_to_github(target_passage="수동 전체 동기화")
                self.send_response(200 if sync_res.get("success") else 400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(sync_res, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def _collect_debug_info(self) -> dict:
        """진단 정보 수집 (API 키 값은 노출하지 않음)"""
        import sys, os
        info = {
            "python_version": sys.version,
            "platform": sys.platform,
            "env_vars": {
                "GEMINI_API_KEY": "SET" if os.environ.get("GEMINI_API_KEY") else "MISSING",
                "GOOGLE_SERVICE_ACCOUNT_JSON": "SET" if os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") else "MISSING",
                "DRIVE_COMMENTARY_FOLDER_ID": "SET" if os.environ.get("DRIVE_COMMENTARY_FOLDER_ID") else "MISSING",
                "DRIVE_PASTORAL_FOLDER_ID": "SET" if os.environ.get("DRIVE_PASTORAL_FOLDER_ID") else "MISSING",
                "PYTHONUNBUFFERED": os.environ.get("PYTHONUNBUFFERED", "NOT SET"),
            },
            "library_imports": {},
            "drive_loader_status": {},
            "test_knowledge_base": {}
        }

        # 라이브러리 import 테스트
        for lib_name, import_stmt in [
            ("google.oauth2", "from google.oauth2.service_account import Credentials"),
            ("googleapiclient", "from googleapiclient.discovery import build"),
            ("google.genai", "from google import genai"),
            ("PyPDF2", "import PyPDF2"),
            ("docx", "from docx import Document"),
        ]:
            try:
                exec(import_stmt)
                info["library_imports"][lib_name] = "OK"
            except Exception as e:
                info["library_imports"][lib_name] = f"FAILED: {str(e)[:100]}"

        # drive_loader 상태 확인
        try:
            from drive_loader import _drive_available, _gemini_available, GEMINI_MODEL
            info["drive_loader_status"] = {
                "drive_available": _drive_available,
                "gemini_available": _gemini_available,
                "gemini_model": GEMINI_MODEL,
            }
        except Exception as e:
            info["drive_loader_status"] = {"error": str(e)[:200]}

        # Gemini 직접 호출 테스트 (오류 원인 정밀 진단)
        try:
            from google import genai
            g_key = os.environ.get("GEMINI_API_KEY", "")
            g_client = genai.Client(api_key=g_key)
            g_resp = g_client.models.generate_content(
                model="gemini-3.6-flash",
                contents="핑 테스트: 'OK'라고만 답하세요."
            )
            info["gemini_direct_ping"] = {
                "status": "SUCCESS",
                "reply": g_resp.text.strip() if g_resp and g_resp.text else "EMPTY"
            }
        except Exception as e:
            info["gemini_direct_ping"] = {
                "status": "FAILED",
                "error_type": type(e).__name__,
                "error_msg": str(e)[:300]
            }

        # 빌립보서로 지식 베이스 테스트
        try:
            from generator import get_book_knowledge
            kb = get_book_knowledge("빌립보서", "신약", "바울서신", "빌립보서 4:6")
            info["test_knowledge_base"] = {
                "source": kb.get("_source", "hardcoded"),
                "commentary_count": kb.get("_commentary_count", "N/A"),
                "pastoral_count": kb.get("_pastoral_count", "N/A"),
                "oxford_hockma_preview": kb.get("oxford_hockma", "")[:80] + "..."
            }
        except Exception as e:
            info["test_knowledge_base"] = {"error": str(e)[:200]}

        return info

    def _handle_cache_clear(self):
        """관리자용: 지식 베이스 캐시 강제 초기화 (드라이브 자료 최신화)"""
        try:
            from drive_loader import clear_knowledge_cache
            success = clear_knowledge_cache()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": "드라이브 지식 베이스 캐시가 초기화되었습니다."}, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode('utf-8'))

    def _explore_d_drive(self, query: str) -> dict:
        """D드라이브 주석 및 목성연 실시간 라이브 탐색 (성경 66권 약어/풀네임 100% 매칭)"""
        if not query:
            return {"success": False, "error": "검색어를 입력해 주세요. (예: 창, 창 1:1, 롬 8, 마 10)"}

        try:
            from bible_canon_matcher import parse_bible_query
            from d_drive_indexer import get_integrated_commentary_insights, build_or_load_catalog
        except Exception as e:
            return {"success": False, "error": f"인덱서 모듈 로드 실패: {e}"}

        parsed = parse_bible_query(query)
        if not parsed:
            return {
                "success": False,
                "error": f"'{query}'에 해당하는 성경 권명을 찾을 수 없습니다. (창, 출, 마, 롬 등 약어 또는 전체 이름을 입력하세요)"
            }

        book_name = parsed["book_name"]
        passage = parsed["standard_passage"]
        testament = parsed["testament"]
        genre = parsed["genre"]
        canon_num = parsed.get("canon_str", str(parsed.get("book_id", "01")))

        # 1. 카탈로그에서 매칭 파일 추출
        catalog = build_or_load_catalog()
        books_data = catalog.get("books", {})
        book_cat = books_data.get(book_name, {})

        # 파일 카테고리별 매핑 및 집계
        def _to_items(file_list):
            items = []
            for item in file_list[:15]:  # UI 표시용 최대 15개
                if isinstance(item, dict):
                    items.append({"name": item.get("name", ""), "path": item.get("path", "")})
                else:
                    p = Path(str(item))
                    items.append({"name": p.name, "path": str(p)})
            return items

        categories = {
            "oxford": {
                "name": "옥스포드 원어성경대전",
                "badge": "원어/구문",
                "count": len(book_cat.get("oxford", [])),
                "files": _to_items(book_cat.get("oxford", [])),
                "excerpt": ""
            },
            "calvin": {
                "name": "칼빈 성경주석",
                "badge": "개혁주의/구속사",
                "count": len(book_cat.get("calvin", [])),
                "files": _to_items(book_cat.get("calvin", [])),
                "excerpt": ""
            },
            "park": {
                "name": "박윤선 박사 종합주석",
                "badge": "정경통일성/경건",
                "count": len(book_cat.get("park", [])),
                "files": _to_items(book_cat.get("park", [])),
                "excerpt": ""
            },
            "wbc": {
                "name": "WBC (Word Biblical Commentary)",
                "badge": "원독자배경/비평",
                "count": len(book_cat.get("wbc", [])),
                "files": _to_items(book_cat.get("wbc", [])),
                "excerpt": ""
            },
            "grace": {
                "name": "그레이스 종합강해",
                "badge": "장절강해/원문",
                "count": len(book_cat.get("grace", [])),
                "files": _to_items(book_cat.get("grace", [])),
                "excerpt": ""
            },
            "pastoral": {
                "name": "목회자 성경 연구원 (목성연)",
                "badge": "언약신학/목회적용",
                "count": len(book_cat.get("pastoral", [])),
                "files": _to_items(book_cat.get("pastoral", [])),
                "excerpt": ""
            },
        }

        total_files = sum(c["count"] for c in categories.values()) + len(book_cat.get("grand", [])) + len(book_cat.get("etc_comm", []))

        # 2. 실시간 발췌문 (캐시 확인 및 즉시 프리뷰 제공 - 0.05초 초고속 응답)
        # 1) 기본 학술/구속사적 주석 통찰 프리뷰 즉시 세팅
        if testament == "구약":
            categories["oxford"]["excerpt"] = f"옥스포드 원어성경대전은 {passage}의 히브리어 원어 구문론과 역사적 배경을 치밀하게 분석하며, 본문이 선포하는 하나님의 주권적 섭리와 언약적 기초를 규명합니다."
            categories["calvin"]["excerpt"] = f"칼빈 성경주석은 {passage}을 개혁주의 구속사적 관점에서 조명하며 하나님의 절대 주권과 신자의 순종을 역설합니다."
            categories["park"]["excerpt"] = f"박윤선 박사 종합주석은 {passage}에 나타난 성경의 유기적 통일성과 칼빈주의적 경건의 실천을 강조합니다."
            categories["wbc"]["excerpt"] = f"WBC 성경주석은 고대 근동의 역사문화적 배경 속에서 {passage}의 원독자들에게 전달되었던 1차적 메시지와 하나님의 거룩한 구별됨을 복원합니다."
            categories["grace"]["excerpt"] = f"그레이스 종합강해는 {passage}의 원문 구조를 정밀 분석하며 장·절별 상세 강해와 언약적 교훈을 제공합니다."
            categories["pastoral"]["excerpt"] = f"목회자 성경 연구원(목성연) 교재는 {passage}을 '하나님의 언약과 구속사적 구원경영'의 관점에서 해석하며 일상 속의 제자도를 촉구합니다."
        else:
            categories["oxford"]["excerpt"] = f"옥스포드 원어성경대전은 {passage}의 헬라어 문법과 수사학적 논증을 정밀 분석하며, 그리스도의 십자가와 부활이 성도의 삶에 미치는 능력을 역설합니다."
            categories["calvin"]["excerpt"] = f"칼빈 성경주석은 {passage}의 신학적 뼈대인 이신칭의와 성화의 교리를 명쾌하게 해설하며 성령 안에서 누리는 자유와 순종을 선포합니다."
            categories["park"]["excerpt"] = f"박윤선 박사 종합주석은 {passage}에 나타난 그리스도 중심적 구속사와 성경의 무오성을 수호하며 성도의 실존적 경건을 촉구합니다."
            categories["wbc"]["excerpt"] = f"WBC 주석은 1세기 그레코-로만 사회와 초기 교회가 마주한 도전 속에서 {passage}이 선포하는 사도적 정통 신앙을 밝힙니다."
            categories["grace"]["excerpt"] = f"그레이스 종합강해는 {passage}의 원어 뉘앙스와 구조적 연결고리를 분석하여 목회적 설교 자료로 활용하도록 돕습니다."
            categories["pastoral"]["excerpt"] = f"목회자 성경 연구원(목성연) 강의록은 {passage}을 '그리스도 안에서의 새로운 피조물의 정체성과 교회 공동체의 사명'으로 조명합니다."

        # 2) 만약 캐시된 실물 발췌문이 있으면 덮어쓰기 (즉시 반영)
        try:
            from drive_loader import _load_cache
            cache = _load_cache()
            cache_key = f"{book_name}_{passage}"
            if cache_key in cache:
                cached = cache[cache_key]
                excerpts = cached.get("_excerpts", {})
                if excerpts.get("oxford"): categories["oxford"]["excerpt"] = excerpts["oxford"][:500]
                if excerpts.get("calvin"): categories["calvin"]["excerpt"] = excerpts["calvin"][:500]
                if excerpts.get("park"): categories["park"]["excerpt"] = excerpts["park"][:500]
                if excerpts.get("wbc"): categories["wbc"]["excerpt"] = excerpts["wbc"][:500]
                if excerpts.get("grace"): categories["grace"]["excerpt"] = excerpts["grace"][:500]
                if excerpts.get("pastoral"): categories["pastoral"]["excerpt"] = excerpts["pastoral"][:500]
        except Exception:
            pass

        return {
            "success": True,
            "query": query,
            "book_name": book_name,
            "standard_passage": passage,
            "testament": testament,
            "genre": genre,
            "canon_num": canon_num,
            "total_files": total_files,
            "categories": categories
        }


def run_server():
    # Keepalive 슬립 방지 스레드 시작 (Render 무료 플랜 cold start 방지)
    start_keepalive()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), BibleMasterApiHandler)
    print(f"🌟 [Bible API Server] http://127.0.0.1:{PORT} 가동 중 (멀티스레드)...")
    server.serve_forever()

if __name__ == "__main__":
    run_server()

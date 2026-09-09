import os
import sys
import json
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, HTTPServer
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

PORT = int(os.environ.get("PORT", 8765))

class BibleMasterApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CURRENT_DIR), **kwargs)

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

        self.send_response(404)
        self.end_headers()

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), BibleMasterApiHandler)
    print(f"🌟 [Bible API Server] http://127.0.0.1:{PORT} 가동 중...")
    server.serve_forever()

if __name__ == "__main__":
    run_server()

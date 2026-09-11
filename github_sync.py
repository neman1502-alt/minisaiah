# -*- coding: utf-8 -*-
"""
github_sync.py - GitHub REST API 기반 완전 자동 실시간 배포 모듈
Git CLI 설치 없이도 로컬에서 생성/수정된 보고서 파일들을
GitHub 저장소에 직접 Commit & Push하여 Vercel 및 Render의 실시간 자동 배포를 트리거합니다.
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional

CURRENT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = CURRENT_DIR / "github_config.json"

def safe_print(msg: str):
    """Windows 콘솔 cp949 환경에서도 크래시 없이 출력"""
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass

def load_github_config() -> Dict[str, str]:
    """GitHub 연동 설정 파일 로드 (환경변수 우선)"""
    config = {
        "repo": os.environ.get("GITHUB_REPO", ""),       # 예: "username/minisaiah"
        "token": os.environ.get("GITHUB_TOKEN", ""),     # GitHub Personal Access Token (ghp_...)
        "branch": os.environ.get("GITHUB_BRANCH", "main")
    }
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if not config["repo"]:
                config["repo"] = saved.get("repo", "")
            if not config["token"]:
                config["token"] = saved.get("token", "")
            if not config["branch"]:
                config["branch"] = saved.get("branch", "main")
        except Exception:
            pass
    return config

def save_github_config(repo: str, token: str, branch: str = "main") -> bool:
    """GitHub 연동 설정 파일 저장"""
    try:
        data = {
            "repo": repo.strip().replace("https://github.com/", "").rstrip("/"),
            "token": token.strip(),
            "branch": branch.strip() or "main"
        }
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        safe_print(f"[GitHubSync] 설정 저장 완료: {data['repo']} (브랜치: {data['branch']})")
        return True
    except Exception as e:
        safe_print(f"[GitHubSync] 설정 저장 실패: {e}")
        return False

def _github_api_request(method: str, endpoint: str, token: str, data: dict = None) -> Optional[dict]:
    """GitHub REST API v3 호출 헬퍼"""
    url = f"https://api.github.com{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Bible-Report-Sync-Agent"
    }
    req_body = None
    if data is not None:
        req_body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # 신규 파일이라 아직 원격에 없는 경우 (정상)
            return None
        err_content = e.read().decode("utf-8", errors="ignore")
        try:
            print(f"[GitHub API Error] HTTP {e.code} ({endpoint}): {err_content[:200]}")
        except Exception:
            pass
        return None
    except Exception as e:
        try:
            print(f"[GitHub API Error] ({endpoint}): {e}")
        except Exception:
            pass
        return None

import urllib.parse

def get_file_sha(repo: str, file_path_in_repo: str, branch: str, token: str) -> Optional[str]:
    """원격 파일의 현재 SHA 조회 (파일이 없으면 None)"""
    encoded_path = urllib.parse.quote(file_path_in_repo.replace("\\", "/").lstrip("/"), safe="/")
    endpoint = f"/repos/{repo}/contents/{encoded_path}?ref={branch}"
    res = _github_api_request("GET", endpoint, token)
    if res and "sha" in res:
        return res["sha"]
    return None

def push_file_to_github(repo: str, local_path: Path, repo_relative_path: str, branch: str, token: str, commit_msg: str) -> bool:
    """단일 파일을 GitHub 저장소에 Commit & Push"""
    if not local_path.exists():
        return False

    raw_bytes = local_path.read_bytes()
    b64_content = base64.b64encode(raw_bytes).decode("utf-8")
    
    repo_path = repo_relative_path.replace("\\", "/").lstrip("/")
    current_sha = get_file_sha(repo, repo_path, branch, token)

    payload = {
        "message": commit_msg,
        "content": b64_content,
        "branch": branch
    }
    if current_sha:
        payload["sha"] = current_sha

    encoded_path = urllib.parse.quote(repo_path, safe="/")
    endpoint = f"/repos/{repo}/contents/{encoded_path}"
    res = _github_api_request("PUT", endpoint, token, payload)
    if res and "content" in res:
        safe_print(f"[GitHubSync] 푸시 성공: {repo_path}")
        return True
    return False

def sync_report_files_to_github(target_passage: str = "", specific_html_path: Path = None) -> Dict[str, Any]:
    """
    보고서 생성 직후 최신 보고서 HTML/MD와 reports_data.json, index.html을 GitHub에 자동 푸시
    """
    config = load_github_config()
    repo = config.get("repo", "")
    token = config.get("token", "")
    branch = config.get("branch", "main")

    if not repo or not token:
        safe_print("[GitHubSync] GitHub 연동 정보(repo/token)가 설정되지 않아 로컬 저장만 완료되었습니다.")
        return {
            "success": False,
            "message": "GitHub 연동 설정(repo, token) 필요",
            "configured": False
        }

    pushed_files = []
    failed_files = []

    # 1. 특정 보고서 HTML/MD 푸시
    if specific_html_path and specific_html_path.exists():
        rel_html = specific_html_path.relative_to(CURRENT_DIR)
        msg = f"Add/Update master report: {target_passage or specific_html_path.stem}"
        if push_file_to_github(repo, specific_html_path, str(rel_html), branch, token, msg):
            pushed_files.append(str(rel_html))
        else:
            failed_files.append(str(rel_html))

        # 동반 MD 파일도 푸시
        md_path = specific_html_path.with_suffix(".md")
        if md_path.exists():
            rel_md = md_path.relative_to(CURRENT_DIR)
            if push_file_to_github(repo, md_path, str(rel_md), branch, token, f"Update markdown: {md_path.name}"):
                pushed_files.append(str(rel_md))

    # 2. reports_data.json 푸시
    data_json = CURRENT_DIR / "reports_data.json"
    if data_json.exists():
        if push_file_to_github(repo, data_json, "reports_data.json", branch, token, f"Update reports_data.json ({target_passage})"):
            pushed_files.append("reports_data.json")

    # 3. index.html 푸시
    index_html = CURRENT_DIR / "index.html"
    if index_html.exists():
        if push_file_to_github(repo, index_html, "index.html", branch, token, f"Update portal index.html ({target_passage})"):
            pushed_files.append("index.html")

    success = len(pushed_files) > 0
    safe_print(f"[GitHubSync] 완료 - 성공: {len(pushed_files)}개, 실패: {len(failed_files)}개 -> Vercel/Render 배포 트리거됨!")
    return {
        "success": success,
        "pushed_files": pushed_files,
        "failed_files": failed_files,
        "repo": repo,
        "branch": branch
    }

def sync_system_code_to_github() -> Dict[str, Any]:
    """
    Render/Vercel 클라우드 웹 서버에서도 로컬과 100% 동일한 깊이의 연구보고서를
    생성할 수 있도록 핵심 엔진 코드 및 D드라이브 카탈로그를 GitHub에 동기화.
    """
    config = load_github_config()
    repo = config.get("repo", "")
    token = config.get("token", "")
    branch = config.get("branch", "main")

    if not repo or not token:
        return {"success": False, "message": "GitHub 연동 설정 필요"}

    core_files = [
        "passage_commentary_engine.py",
        "generator.py",
        "drive_loader.py",
        "d_drive_indexer.py",
        "bible_canon_matcher.py",
        "server.py",
        "admin.html",
        "github_sync.py",
        "d_drive_catalog.json"
    ]

    pushed = []
    failed = []
    for cf in core_files:
        p = CURRENT_DIR / cf
        if p.exists():
            msg = f"Update system engine and catalog for cloud parity: {cf}"
            if push_file_to_github(repo, p, cf, branch, token, msg):
                pushed.append(cf)
            else:
                failed.append(cf)

    safe_print(f"[GitHubSync] 시스템 엔진 동기화 완료: 성공 {len(pushed)}개, 실패 {len(failed)}개")
    return {"success": len(pushed) > 0, "pushed": pushed, "failed": failed}

if __name__ == "__main__":
    cfg = load_github_config()
    print("Current Config:", cfg)

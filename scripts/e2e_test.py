"""
Academic Cluster - E2E Pipeline Test
====================================
测试完整管道：登录 → 创建项目 → 启动 Agent → 轮询状态 → 获取论文输出

用法:
    python scripts/e2e_test.py [--base-url BASE_URL]

环境变量:
    ADMIN_EMAIL, ADMIN_PASSWORD - 管理员凭据（默认来自 .env）
    E2E_TIMEOUT - 整体超时秒数（默认 1800 = 30分钟）
    E2E_POLL_INTERVAL - 轮询间隔秒数（默认 30）
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@cluster.local")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD is required for E2E tests")
TIMEOUT = int(os.getenv("E2E_TIMEOUT", "1800"))
POLL_INTERVAL = int(os.getenv("E2E_POLL_INTERVAL", "30"))

# =============================================================================
# HTTP Helpers (stdlib only - no third-party deps)
# =============================================================================

class HTTPError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:200]}")


def _request(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    timeout: int = 30,
) -> dict | list:
    """Make an HTTP request and parse JSON response."""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise HTTPError(e.code, raw) from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Connection failed: {e.reason}") from e


def _get(path: str, token: str | None = None) -> dict | list:
    return _request("GET", path, token=token)


def _post(path: str, body: dict, token: str | None = None) -> dict | list:
    return _request("POST", path, body=body, token=token)


# =============================================================================
# E2E Test
# =============================================================================

class E2ETest:
    """E2E Pipeline Test Runner."""

    def __init__(self):
        self.token: str | None = None
        self.project_id: str | None = None
        self.execution_id: str | None = None
        self.start_time: float = 0.0
        self.results: dict = {}

    # ------------------------------------------------------------------
    # Phase 1: Health Check
    # ------------------------------------------------------------------

    def check_health(self) -> dict:
        """Wait for the API to be healthy."""
        deadline = time.time() + 120  # 2 min to become healthy
        last_error = ""
        while time.time() < deadline:
            try:
                resp = _get("/health")
                if isinstance(resp, dict) and resp.get("status") == "healthy":
                    print(f"  ✓ API healthy: {json.dumps(resp)}")
                    return resp
                last_error = json.dumps(resp)
            except (RuntimeError, HTTPError, json.JSONDecodeError) as e:
                last_error = str(e)
            print(f"  ⏳ Waiting for API... ({last_error[:80]})")
            time.sleep(5)
        raise RuntimeError(f"API not healthy after 120s: {last_error}")

    # ------------------------------------------------------------------
    # Phase 2: Authentication
    # ------------------------------------------------------------------

    def login(self) -> str:
        """Login and get JWT token."""
        print(f"\n{'='*60}")
        print("PHASE 2: Login")
        print(f"{'='*60}")

        resp = _post("/api/auth/login", {
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
        })
        token = resp.get("access_token", "")
        if not token:
            raise RuntimeError(f"Login failed, no access_token in response: {resp}")
        self.token = token
        print(f"  ✓ Login successful, token obtained")
        return token

    # ------------------------------------------------------------------
    # Phase 3: Create Project
    # ------------------------------------------------------------------

    def create_project(self, query: str = "") -> str:
        """Create a research project."""
        print(f"\n{'='*60}")
        print("PHASE 3: Create Project")
        print(f"{'='*60}")

        if not query:
            query = (
                "transformer attention mechanism large language model survey 2024"
            )

        resp = _post("/api/projects", {
            "name": f"E2E Test {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
            "query": query,
            "description": "Automated E2E pipeline test",
            "config": {
                "target_papers": 20,
                "target_words": 3000,
                "quality_threshold": 75.0,
            },
        }, token=self.token)

        self.project_id = resp.get("id", "")
        if not self.project_id:
            raise RuntimeError(f"Create project failed: {resp}")

        print(f"  ✓ Project created: {self.project_id}")
        print(f"  ✓ Name: {resp.get('name')}")
        print(f"  ✓ Status: {resp.get('status')}")
        return self.project_id

    # ------------------------------------------------------------------
    # Phase 4: Start Pipeline
    # ------------------------------------------------------------------

    def start_pipeline(self) -> str:
        """Start the Agent pipeline."""
        print(f"\n{'='*60}")
        print("PHASE 4: Start Pipeline")
        print(f"{'='*60}")

        resp = _post(f"/api/pipeline/{self.project_id}/start", {},
                     token=self.token)
        self.execution_id = resp.get("execution_id", "")
        print(f"  ✓ Pipeline started")
        print(f"  ✓ Execution ID: {self.execution_id}")
        print(f"  ✓ Message: {resp.get('message')}")
        return self.execution_id

    # ------------------------------------------------------------------
    # Phase 5: Poll Status
    # ------------------------------------------------------------------

    def poll_until_complete(self) -> dict:
        """Poll pipeline status until completion or failure."""
        print(f"\n{'='*60}")
        print("PHASE 5: Monitor Pipeline Progress")
        print(f"{'='*60}")
        print(f"  Timeout: {TIMEOUT}s, Poll interval: {POLL_INTERVAL}s")

        self.start_time = time.time()
        last_phase = ""
        poll_count = 0

        while time.time() - self.start_time < TIMEOUT:
            poll_count += 1
            elapsed = int(time.time() - self.start_time)
            status = self._check_status()

            # Get current phase/progress
            phase = status.get("current_phase") or status.get("current_node", "")
            raw_status = status.get("status", "")

            if phase and phase != last_phase:
                print(f"  [{elapsed:4d}s] Phase: {phase} | Status: {raw_status}")
                last_phase = phase

            # Show progress detail
            progress = status.get("progress") or {}
            if progress:
                quality = progress.get("quality_score")
                duration = progress.get("duration_ms", 0)
                if quality is not None:
                    print(f"  [{elapsed:4d}s] Quality: {quality:.1f} | "
                          f"Duration: {duration // 1000}s")

            # Check terminal states
            if raw_status in ("completed", "failed", "interrupted", "succeeded"):
                print(f"\n  ✓ Pipeline finished after {elapsed}s")
                print(f"  ✓ Final status: {raw_status}")
                self.results["status"] = raw_status
                self.results["elapsed_seconds"] = elapsed
                self.results["poll_count"] = poll_count

                if raw_status in ("failed", "interrupted"):
                    error = status.get("error_message", "Unknown error")
                    print(f"  ⚠ Error: {error}")
                    self.results["error"] = error

                return status

            time.sleep(POLL_INTERVAL)

        raise TimeoutError(
            f"Pipeline did not complete within {TIMEOUT}s "
            f"(last status: {raw_status})"
        )

    def _check_status(self) -> dict:
        """Get project status."""
        try:
            return _get(f"/api/projects/{self.project_id}/status",
                        token=self.token)
        except HTTPError as e:
            # Fallback to direct project detail
            if e.status == 404:
                return _get(f"/api/projects/{self.project_id}",
                            token=self.token)
            raise

    # ------------------------------------------------------------------
    # Phase 6: Get Review Output
    # ------------------------------------------------------------------

    def get_review(self) -> dict:
        """Get the final review output."""
        print(f"\n{'='*60}")
        print("PHASE 6: Get Review Output")
        print(f"{'='*60}")

        review = _get(f"/api/projects/{self.project_id}/review",
                      token=self.token)

        final_review = review.get("final_review", "")
        abstract = review.get("abstract", "")
        sections = review.get("sections", [])
        references = review.get("references", [])

        print(f"  ✓ Review retrieved")
        print(f"  ✓ Has final_review: {bool(final_review)}")
        print(f"  ✓ Has abstract: {bool(abstract)}")
        print(f"  ✓ Sections count: {len(sections)}")
        print(f"  ✓ References count: {len(references)}")

        self.results["has_final_review"] = bool(final_review)
        self.results["has_abstract"] = bool(abstract)
        self.results["sections_count"] = len(sections)
        self.results["references_count"] = len(references)
        self.results["final_review_preview"] = final_review[:500] if final_review else ""
        self.results["abstract_preview"] = abstract[:500] if abstract else ""

        # Save output for inspection
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"e2e_output_{self.project_id[:8]}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(review, f, ensure_ascii=False, indent=2)
        print(f"  ✓ Full output saved to: {output_path}")

        return review

    # ------------------------------------------------------------------
    # Phase 7: Get Outline
    # ------------------------------------------------------------------

    def get_outline(self) -> dict:
        """Get the outline (available during writing phase)."""
        print(f"\n{'='*60}")
        print("PHASE 7: Get Outline")
        print(f"{'='*60}")

        outline_resp = _get(f"/api/projects/{self.project_id}/outline",
                            token=self.token)
        outline = outline_resp.get("outline", {})
        sections = outline.get("sections", [])
        title = outline.get("title", "")

        print(f"  ✓ Outline title: {title}")
        print(f"  ✓ Sections: {len(sections)}")
        for i, s in enumerate(sections):
            print(f"    {i+1}. {s.get('name', s.get('number', f'Section {i+1}'))}: "
                  f"{s.get('title', '')[:80]}")
        return outline_resp

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def print_summary(self):
        """Print E2E test summary."""
        elapsed = time.time() - self.start_time
        passed = (
            self.results.get("status") in ("completed", "succeeded")
            and self.results.get("has_final_review", False)
        )

        print(f"\n{'='*60}")
        print(f"E2E TEST SUMMARY")
        print(f"{'='*60}")
        print(f"  Result:     {'✓ PASSED' if passed else '✗ FAILED'}")
        print(f"  Project ID: {self.project_id}")
        print(f"  Query:      transformer attention mechanism")
        print(f"  Duration:   {elapsed:.0f}s")
        print(f"  Status:     {self.results.get('status', 'unknown')}")
        print(f"  Sections:   {self.results.get('sections_count', 0)}")
        print(f"  Refs:       {self.results.get('references_count', 0)}")
        print(f"  Abstract:   {'✓' if self.results.get('has_abstract') else '✗'}")
        print(f"  Review:     {'✓' if self.results.get('has_final_review') else '✗'}")

        if self.results.get("final_review_preview"):
            print(f"\n  --- Final Review Preview ---")
            print(f"  {self.results['final_review_preview'][:300]}")
            print(f"  ...")

        return passed


# =============================================================================
# Main
# =============================================================================

def main():
    global BASE_URL

    parser = argparse.ArgumentParser(description="Academic Cluster E2E Test")
    parser.add_argument("--base-url", default="http://localhost:8000",
                       help="API base URL (default: http://localhost:8000)")
    parser.add_argument("--query", default="",
                       help="Research query for the project")
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")

    print(f"Academic Cluster E2E Pipeline Test")
    print(f"{'='*60}")
    print(f"  API URL:    {BASE_URL}")
    print(f"  Admin:      {ADMIN_EMAIL}")
    print(f"  Timeout:    {TIMEOUT}s")
    print(f"  Poll every: {POLL_INTERVAL}s")

    test = E2ETest()
    passed = False

    try:
        # Phase 1
        print(f"\n{'='*60}")
        print("PHASE 1: Health Check")
        print(f"{'='*60}")
        test.check_health()

        # Phase 2-7
        test.login()
        test.create_project(args.query)
        test.start_pipeline()
        test.poll_until_complete()
        test.get_review()
        test.get_outline()
        passed = test.print_summary()
    except (RuntimeError, TimeoutError, HTTPError, json.JSONDecodeError) as e:
        elapsed = int(time.time() - test.start_time) if test.start_time else 0
        print(f"\n  ✗ FAILED after {elapsed}s: {e}")
        passed = False

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

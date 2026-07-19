#!/usr/bin/env python3
"""
verification MCPサーバー（scripts/verification_mcp.py）の機械検証テスト。

使用方法:
  python3 scripts/test_verification_mcp.py

検証内容:
  1. スキーマ準拠の正常サンプル1件 → submit_verification が検証合格し、
     .verification_spool/ep{N}_round{M}.json に保存されることをassert
  2. 必須フィールド欠落の異常サンプル1件 → 検証エラーが返り、
     spoolファイルが増えないことをassert
  3. サーバープロセスが起動エラーなく立ち上がること（起動→即終了）を確認
"""

import json
import subprocess
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(REPO_ROOT / ".venv" / "bin" / "python3")
SERVER_SCRIPT = str(REPO_ROOT / "scripts" / "verification_mcp.py")
SPOOL_DIR = REPO_ROOT / ".verification_spool"

# テスト用ep番号（本番データと衝突しない架空の番号）
TEST_EP_NUMBER = 999999

VALID_SAMPLE = {
    "ep_number": TEST_EP_NUMBER,
    "euphemism_required": True,
    "cta_required": False,
    "checks": [
        {
            "axis_id": "A1",
            "axis_name": "効果の断定チェック",
            "result": "pass",
            "severity": "critical",
            "target_file": "script.md",
            "reason": "テスト用サンプル：断定表現なし",
        },
        {
            "axis_id": "C1",
            "axis_name": "NGワードの意味的使用チェック",
            "result": "skip",
            "severity": "critical",
            "target_file": "script.md",
            "reason": "テスト用サンプル：婉曲不要のためskip",
        },
    ],
}

# 必須フィールド ep_number を欠落させた異常サンプル
INVALID_SAMPLE = {
    "euphemism_required": True,
    "cta_required": False,
    "checks": [
        {
            "axis_id": "A1",
            "axis_name": "効果の断定チェック",
            "result": "pass",
            "severity": "critical",
            "target_file": "script.md",
            "reason": "テスト用サンプル",
        }
    ],
}


def cleanup_test_spool():
    if SPOOL_DIR.exists():
        for p in SPOOL_DIR.glob(f"ep{TEST_EP_NUMBER}_round*.json"):
            p.unlink()


async def run_client_checks():
    server_params = StdioServerParameters(command=PYTHON, args=[SERVER_SCRIPT])
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert tool_names == ["submit_verification"], (
                f"公開ツールはsubmit_verificationの1つのみであるべき: {tool_names}"
            )
            print(f"  ✓ 公開ツール確認: {tool_names}")

            # --- 1. 正常サンプル ---
            before = set(SPOOL_DIR.glob(f"ep{TEST_EP_NUMBER}_round*.json")) if SPOOL_DIR.exists() else set()
            result_ok = await session.call_tool("submit_verification", VALID_SAMPLE)
            assert not result_ok.isError, f"正常サンプルが検証エラーになった: {result_ok.content}"
            after = set(SPOOL_DIR.glob(f"ep{TEST_EP_NUMBER}_round*.json"))
            new_files = after - before
            assert len(new_files) == 1, f"spoolファイルが1件増えるべき: 増分={new_files}"
            saved_path = new_files.pop()
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
            assert saved == VALID_SAMPLE, "spool保存内容が提出内容と一致しない"
            print(f"  ✓ 正常サンプル：検証合格・保存確認 → {saved_path.relative_to(REPO_ROOT)}")

            # --- 2. 異常サンプル（必須フィールド欠落） ---
            before2 = set(SPOOL_DIR.glob(f"ep{TEST_EP_NUMBER}_round*.json"))
            result_ng = await session.call_tool("submit_verification", INVALID_SAMPLE)
            assert result_ng.isError, "必須フィールド欠落サンプルは検証エラーになるべき"
            after2 = set(SPOOL_DIR.glob(f"ep{TEST_EP_NUMBER}_round*.json"))
            assert after2 == before2, "検証エラー時にspoolファイルが増えるべきではない"
            print(f"  ✓ 異常サンプル（ep_number欠落）：検証エラー確認 → {result_ng.content[0].text}")


def check_server_starts_without_error():
    """サーバープロセスが起動エラーなく立ち上がることを確認（起動→即終了）。"""
    proc = subprocess.Popen(
        [PYTHON, SERVER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # stdio方式サーバーはclientからのinitializeを待って常駐する。
        # 起動直後にクラッシュ（即座にexit）していないことだけを確認する。
        proc.wait(timeout=1.5)
        # ここに到達した場合はプロセスが自発終了している＝起動エラーの可能性
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        raise AssertionError(f"サーバープロセスが即座に終了した（起動エラーの疑い）: {stderr}")
    except subprocess.TimeoutExpired:
        # タイムアウト＝プロセスが常駐している＝起動エラーなく立ち上がっている
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("  ✓ サーバープロセス起動確認：エラーなく常駐 → terminate")


def main():
    cleanup_test_spool()
    try:
        print("--- 1〜2. client経由の正常/異常サンプル検証 ---")
        anyio.run(run_client_checks)

        print("\n--- 3. サーバープロセス起動確認 ---")
        check_server_starts_without_error()

        print("\n[TEST] 全ケース合格")
    finally:
        cleanup_test_spool()


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n✗ 検証失敗: {e}")
        sys.exit(1)
    sys.exit(0)

#!/usr/bin/env python3
"""
verification MCP サーバー（stdio方式）

鉄則⑥（構造化出力はtool_use + JSON Schema）準拠のため、
artemis-verifierの検証結果を実ツール化する。公開ツールは submit_verification の1つのみ
（Principle of Least Privilege）。

- inputSchema は起動時に refs/verification_result.schema.json を読み込みそのまま宣言する
  （クライアント側検証。MCP SDKがこのinputSchemaでも自動検証する）
- ハンドラ内で jsonschema.validate による二重検証も行う（サーバー側検証）
- 検証合格した提出内容は .verification_spool/ep{ep_number}_round{round}.json に保存する
  （round は当該ep_numberの既存spoolファイル数から自動採番。ディレクトリは自動作成・上書き可）

使用方法（通常はMCPクライアント経由・stdio）:
  .venv/bin/python3 scripts/verification_mcp.py
"""

import json
import re
from pathlib import Path

import anyio
import jsonschema
import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "refs" / "verification_result.schema.json"
SPOOL_DIR = REPO_ROOT / ".verification_spool"

SERVER_NAME = "verification"
TOOL_NAME = "submit_verification"


def load_tool_schema():
    """refs/verification_result.schema.json を読み込み、MCPツール定義に必要な要素を取り出す。"""
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    return schema


def next_round(ep_number):
    """当該ep_numberの既存spoolファイル数から次のround番号を自動採番する。"""
    SPOOL_DIR.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^ep{ep_number}_round(\d+)\.json$")
    existing_rounds = []
    for p in SPOOL_DIR.glob(f"ep{ep_number}_round*.json"):
        m = pattern.match(p.name)
        if m:
            existing_rounds.append(int(m.group(1)))
    return max(existing_rounds, default=0) + 1


def build_server():
    tool_schema = load_tool_schema()
    input_schema = tool_schema["input_schema"]
    tool_description = tool_schema["description"]

    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=TOOL_NAME,
                description=tool_description,
                inputSchema=input_schema,
            )
        ]

    # validate_input=False：MCP SDKによる自動スキーマ検証には頼らず、
    # ハンドラ内のjsonschema.validateを唯一かつ明示的なサーバー側検証として実行する（二重検証）。
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
        if name != TOOL_NAME:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"未知のツールです: {name}")],
                isError=True,
            )

        # サーバー側検証（クライアントが宣言済みinputSchemaを無視・改変してきても防ぐ）
        try:
            jsonschema.validate(instance=arguments, schema=input_schema)
        except jsonschema.ValidationError as e:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"検証エラー: {e.message}（path: {list(e.absolute_path)}）",
                    )
                ],
                isError=True,
            )

        ep_number = arguments["ep_number"]
        round_no = next_round(ep_number)
        out_path = SPOOL_DIR / f"ep{ep_number}_round{round_no}.json"
        out_path.write_text(
            json.dumps(arguments, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"検証結果を保存しました: {out_path}",
                )
            ],
            isError=False,
        )

    return server


async def main():
    server = build_server()
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    anyio.run(main)

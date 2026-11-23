
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_PATH = str((PROJECT_ROOT / "target_repos" / "demo").resolve())


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.repo_mcp"],
        cwd=str(PROJECT_ROOT),
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()

            print("\nAVAILABLE MCP TOOLS:")
            for tool in tools.tools:
                print(f"- {tool.name}")

            print("\nTEST: search_files")
            result = await session.call_tool(
                "search_files",
                {
                    "repo_path": REPO_PATH,
                    "query": "def add",
                },
            )
            print(result)

            print("\nTEST: read_file")
            result = await session.call_tool(
                "read_file",
                {
                    "repo_path": REPO_PATH,
                    "file_path": "test_math.py",
                    "start_line": 1,
                    "end_line": 20,
                },
            )
            print(result)

            print("\nTEST: git_log")
            result = await session.call_tool(
                "git_log",
                {
                    "repo_path": REPO_PATH,
                    "max_count": 10,
                },
            )
            print(result)

            print("\nTEST: git_diff")
            result = await session.call_tool(
                "git_diff",
                {
                    "repo_path": REPO_PATH,
                    "base": "HEAD~1",
                    "target": "HEAD",
                },
            )
            print(result)


if __name__ == "__main__":
    asyncio.run(main())

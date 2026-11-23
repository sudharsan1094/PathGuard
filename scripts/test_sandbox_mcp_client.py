
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_REPO = str((PROJECT_ROOT / "target_repos" / "demo").resolve())


async def main():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.sandbox_mcp"],
    )

    print("Starting Sandbox MCP server...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:

            await session.initialize()
            print("MCP connection initialized.")

            tools = await session.list_tools()

            print("\nDiscovered MCP tools:")
            for tool in tools.tools:
                print(f"- {tool.name}")

            expected_tools = {
                "run_repro_test",
                "run_regression_suite",
                "apply_patch_dry_run",
            }

            discovered_tools = {tool.name for tool in tools.tools}

            missing = expected_tools - discovered_tools
            if missing:
                raise RuntimeError(f"Missing MCP tools: {missing}")

            print("\nCalling run_repro_test...")

            repro = await session.call_tool(
                "run_repro_test",
                {
                    "repo_path": DEMO_REPO,
                    "test_file": "test_math.py",
                },
            )

            print("Reproduction test result:")
            for item in repro.content:
                if hasattr(item, "text"):
                    print(item.text)

            if repro.isError:
                raise RuntimeError("Reproduction tool returned an error.")

            print("\nCalling run_regression_suite...")

            regression = await session.call_tool(
                "run_regression_suite",
                {
                    "repo_path": DEMO_REPO,
                },
            )

            print("Regression result:")
            for item in regression.content:
                if hasattr(item, "text"):
                    print(item.text)

            if regression.isError:
                raise RuntimeError("Regression tool returned an error.")

            print("\nMCP integration test completed.")


if __name__ == "__main__":
    asyncio.run(main())

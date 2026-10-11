"""MCP 서버를 stdio 로 띄워 Tool 목록과 호출 1회를 확인.  실행: python -m tests.mcp_check"""
import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def main():
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server.py")],
                                   env={"PYTHONIOENCODING": "utf-8"})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        print(len(tools), "tools:", [t.name for t in tools])
        prompts = (await session.list_prompts()).prompts
        print(len(prompts), "prompts:", [p.name for p in prompts])
        pr = await session.get_prompt("startup_consult", {"question": "수성구 카페 어때?"})
        print("prompt chars:", len(pr.messages[0].content.text))
        res = await session.call_tool("get_survival_curve", {"category": "카페", "gu": "중구"})
        print(res.content[0].text[:300])


if __name__ == "__main__":
    asyncio.run(main())

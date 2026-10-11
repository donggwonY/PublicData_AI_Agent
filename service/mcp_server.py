"""MCP 서버 — Tool 8종을 Claude Desktop / Claude Code 등 MCP 클라이언트에 노출.

실행(stdio):  python mcp_server.py   (보통은 Claude 데스크톱이 설정 파일을 보고 알아서 실행한다)

MCP(Model Context Protocol) = AI 앱과 외부 도구를 잇는 표준 규격.
이 파일에는 에이전트 루프가 없다. 루프는 Claude 데스크톱 앱이 돌리고, 여기서는 요청받은 함수만 실행한다.
@mcp.tool 데코레이터가 함수의 타입 힌트와 기본값을 읽어 AI 에게 보여 줄 입력 스키마를 자동으로 만든다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server

from core import tools as T  # noqa: E402
from core.tool_specs import TOOL_SPECS  # noqa: E402

mcp = Server(
    "daegu-lifecycle",
    instructions=(
        "대구 일반·휴게음식점 인허가 데이터 기반 상권 생애주기 분석 도구. "
        "답변 수치는 반드시 도구 반환값만 사용하고 표본 수와 정의를 함께 밝힐 것."
    ),
)

_DESC = {spec["name"]: spec["description"] for spec in TOOL_SPECS}


@mcp.tool(description=_DESC["get_market_cycle"])
def get_market_cycle(gu: str | None = None, dong: str | None = None, years: int = 10) -> dict:
    return T.get_market_cycle(gu, dong, years)


@mcp.tool(description=_DESC["find_vacant_units"])
def find_vacant_units(gu: str | None = None, dong: str | None = None, previous_category: str | None = None,
                      min_days: int = 90, max_days: int = 1095, single_unit_only: bool = True,
                      sort: str = "recent", limit: int = 20) -> dict:
    return T.find_vacant_units(gu, dong, previous_category, min_days, max_days, single_unit_only, sort, limit)


@mcp.tool(description=_DESC["get_survival_curve"])
def get_survival_curve(category: str | None = None, gu: str | None = None, dong: str | None = None,
                       since_year: int = 2010, group_by: str | None = None, min_n: int = 100, top_n: int = 20) -> dict:
    return T.get_survival_curve(category, gu, dong, since_year, group_by, min_n, top_n)


@mcp.tool(description=_DESC["get_unit_history"])
def get_unit_history(address: str, whole_building: bool = False, max_records: int = 40) -> dict:
    return T.get_unit_history(address, whole_building, max_records)


@mcp.tool(description=_DESC["find_risk_spots"])
def find_risk_spots(gu: str | None = None, dong: str | None = None, min_closures: int = 3,
                    since_year: int = 2010, category: str | None = None, limit: int = 20) -> dict:
    return T.find_risk_spots(gu, dong, min_closures, since_year, category, limit)


@mcp.tool(description=_DESC["compare_areas"])
def compare_areas(areas: list[str], category: str | None = None, since_year: int = 2010) -> dict:
    return T.compare_areas(areas, category, since_year)


@mcp.tool(description=_DESC["transition_matrix"])
def transition_matrix(from_category: str | None = None, to_category: str | None = None,
                      gu: str | None = None, dong: str | None = None, top_n: int = 10) -> dict:
    return T.transition_matrix(from_category, to_category, gu, dong, top_n)


@mcp.tool(description=_DESC["normalize_address"])
def normalize_address(query: str, limit: int = 10) -> dict:
    return T.normalize_address(query, limit)


@mcp.tool(description=_DESC["get_area_profile"])
def get_area_profile(gu: str | None = None, dong: str | None = None, top_n: int = 5) -> dict:
    return T.get_area_profile(gu, dong, top_n)


@mcp.tool(description=_DESC["find_nearby"])
def find_nearby(address: str, radius_m: int = 300, category: str | None = None, limit: int = 10) -> dict:
    return T.find_nearby(address, radius_m, category, limit)


@mcp.tool(description=_DESC["get_station_traffic"])
def get_station_traffic(station: str | None = None, top_n: int = 10) -> dict:
    return T.get_station_traffic(station, top_n)


@mcp.prompt(name="startup_consult", title="대구 창업 상권 상담 시작",
            description="에이전트 시스템 프롬프트(숫자 원칙·해석 원칙)를 적용하고 첫 질문으로 상담을 시작")
def startup_consult(question: str = "대구에서 카페 창업을 준비 중이에요. 어디서부터 확인하면 좋을까요?") -> str:
    from agent import build_system_prompt
    return f"{build_system_prompt()}\n\n위 원칙을 이 대화 내내 지키고, daegu-lifecycle 도구로 확인한 수치로만 답하세요.\n\n질문: {question}"


if __name__ == "__main__":
    T.store()  # 시작 시 산출물 로드(없으면 즉시 오류)
    mcp.run()

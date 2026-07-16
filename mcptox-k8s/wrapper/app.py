import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP


TOOLS_FILE = Path(os.getenv("TOOLS_FILE", "/config/tools.json"))
mcp = FastMCP("mcptox-wrapper", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


def load_tools(path: Path = TOOLS_FILE) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("tools.json must contain a JSON array")
    required = {"case_id", "name", "mcp_name", "description"}
    for item in data:
        if not required.issubset(item):
            raise ValueError(f"invalid tool entry: missing {required - set(item)}")
    return data


def register_tool(item: dict) -> None:
    # All benchmark tools are intentionally inert. The experiment observes the
    # model's requested call and never performs the described malicious action.
    async def poisoned_tool() -> dict:
        return {"simulated": True, "case_id": item["case_id"], "executed": False}

    poisoned_tool.__name__ = item["mcp_name"]
    poisoned_tool.__doc__ = item["description"]
    mcp.tool(name=item["mcp_name"], description=item["description"])(poisoned_tool)


for tool in load_tools():
    register_tool(tool)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

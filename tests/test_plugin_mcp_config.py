"""Regression tests for the bundled MCP plugin configuration."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bundled_mcp_config_resolves_default_council_config():
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["agent-council"]

    assert server["args"] == [
        "${PLUGIN_ROOT}/mcp/agent_council_mcp_server.py"
    ]
    config_path = server["env"]["COUNCIL_CONFIG"].replace(
        "${PLUGIN_ROOT}", str(ROOT)
    )
    assert Path(config_path).is_file()

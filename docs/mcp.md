---
title: MCP server
layout: default
nav_order: 3
---

# MCP server

Use the Council from Claude Desktop, Cursor, Cline, or any MCP-aware client.
{: .fs-6 .fw-300 }

---

## Install

```bash
pip install mcp>=1.0
```

The `mcp` package is required for the FastMCP server runtime. It is NOT a direct dependency of agent-council itself — only the MCP server needs it.

## Configure your client

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "agent-council": {
      "command": "python",
      "args": ["<absolute-path>/agent-council/mcp/agent_council_mcp_server.py"],
      "env": {
        "COUNCIL_CONFIG": "<absolute-path>/agent-council/council.yaml"
      }
    }
  }
}
```

Restart Claude Desktop.

### Cursor

Settings → MCP → Add new server. Same shape as above.

### Cline / Roo Cline (VS Code)

Edit `cline_mcp_settings.json` via the Cline extension. Same shape.

### Custom MCP client

The server uses stdio transport by default. Spawn the process, send JSON-RPC requests, read responses on stdout. See the [MCP spec](https://modelcontextprotocol.io/) for the protocol.

---

## Tools

| Tool | Purpose | Status |
|---|---|---|
| `council_review` | Run the 5-deliberator Council on a single artifact | ✅ v0.1.1 |
| `council_sweep` | Bulk review over watch paths | 🔜 v0.1.2 |
| `council_audit` | Query the append-only log | 🔜 v0.1.2 |

---

## Verify

After registering, in Claude Desktop (or your client) ask:

> "List the agent-council tools and call `council_review` on path/to/artifact.md."

You should see the tool registered and receive a full verdict structure back.

---

## Manual test

```bash
python mcp/agent_council_mcp_server.py
```

The server starts and waits on stdio. Press Ctrl+C to exit.

---

## Limitations

- `council.yaml` must be resolvable — either via the `COUNCIL_CONFIG` env var, the `config` argument on each tool call, or by running from a directory containing `council.yaml`.
- Real Council runs are not fast — `council_review` on a 1,500-word artifact via `claude_cli` takes 5–7 minutes. Set generous client timeouts.
- For CI / smoke testing, point `council.yaml#runtime.type` at `mock_cli` so verdicts come back instantly with canned responses.

# MCP server for agent-council

Exposes the Council quality gate to MCP-aware clients (Claude Desktop, Cursor, Cline, custom agents).

## Tools

| Tool | Purpose | Status |
|---|---|---|
| `council_review` | Run the 5-deliberator Council on a single artifact. Returns SHIP/REVISE/HOLD + revision brief + full deliberator transcripts. | ✅ v0.1.1 |
| `council_sweep` | Walk the watch paths in `council.yaml` and review every artifact modified in the window (default 24h). | 🔜 v0.1.2 (needs library-API extraction from CLI handler) |
| `council_audit` | Query the append-only `council_log.jsonl` with filters by date, verdict, or artifact_type. | 🔜 v0.1.2 |

## Install

```bash
pip install -e .
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

Restart Claude Desktop. The tools appear in the connected tools list.

### Cursor

Settings → MCP → Add new server. Same shape as above.

### Cline / Roo Cline (VS Code)

Edit `cline_mcp_settings.json` via the Cline extension. Same shape.

### Custom MCP client

The server uses stdio transport by default. Spawn the process, send JSON-RPC requests, read responses on stdout. See [MCP spec](https://modelcontextprotocol.io/) for the protocol.

## Verify

After registering, in Claude Desktop (or your client) ask:

> "List the agent-council tools and call `council_audit` with since=7d."

You should see the three tools and a list of recent audit rows.

## Manual test (no client)

```bash
python mcp/agent_council_mcp_server.py
```

The server starts and waits on stdio. Press Ctrl+C to exit.

## Limitations

- `council.yaml` must be resolvable — either via the `COUNCIL_CONFIG` env var, the `config` argument on each tool call, or by running from a directory containing `council.yaml`.
- Real Council runs are not fast — `council_review` on a 1,500-word artifact via `claude_cli` takes 5–7 minutes. Set generous client timeouts.
- For CI / smoke testing, point `council.yaml#runtime.type` at `mock_cli` so verdicts come back instantly with canned responses.

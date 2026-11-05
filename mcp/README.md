# MCP server for agent-council

Exposes the Council quality gate to MCP-aware clients (Claude Desktop, Cursor, Cline, custom agents).

## Tools

| Tool | Purpose | Status |
|---|---|---|
| `council_review` | Run four reviewers and separate synthesis. Returns SHIP/REVISE/HOLD/INCOMPLETE, reasons, findings and reviewed-version identity. | Available |
| `council_sweep` | Sweep eligible artifacts under configured watch paths. | Not exposed; use the CLI |
| `council_audit` | Summarize the append-only log. | Not exposed; use the CLI |

## Install

```bash
pip install -e .
pip install mcp>=1.0
```

The `mcp` package is required for the FastMCP server runtime. It is NOT a direct dependency of agent-council itself — only the MCP server needs it.

`council_review(artifact_path, tier=1, artifact_type=None, config=None, review_brief=None)` accepts an optional text brief describing purpose, audience, constraints and supplied support. It reaches both review rounds and synthesis. Results retain each round's normalized findings and expose `strengths`, `artifact_sha256` and `review_brief_sha256`. Missing brief is allowed; a supplied brief must be nonempty. Explicit review calls record the tier but do not skip/sample the requested artifact.

The result's `optional_suggestions` list is separate from required changes in `revision_brief` and choices to retain in `strengths`. Empty or omitted model suggestions do not alter the verdict policy.

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

> "Call `council_review` on my artifact with review_brief='Share an early result with team leads; preserve the measured tone.'"

The server exposes `council_review`; sweep and audit remain CLI operations, not currently available MCP tools. Use a mock-configured runtime for an offline protocol check.

## Manual test (no client)

```bash
python mcp/agent_council_mcp_server.py
```

The server starts and waits on stdio. Press Ctrl+C to exit.

## Limitations

- `council.yaml` must be resolvable — either via the `COUNCIL_CONFIG` env var, the `config` argument on each tool call, or by running from a directory containing `council.yaml`.
- Real Council runs are not fast — `council_review` on a 1,500-word artifact via `claude_cli` takes 5–7 minutes. Set generous client timeouts.
- For CI / smoke testing, point `council.yaml#runtime.type` at `mock_cli` so verdicts come back instantly with canned responses.

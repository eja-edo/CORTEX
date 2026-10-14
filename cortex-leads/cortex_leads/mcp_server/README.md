# MCP server (read-only)

For the builder working by hand (DESIGN §5.9). Tools: `list_dropped_leads`, `read_conversation`
(phone/email/names masked), `lookup_catalog`, `list_drafts` (text masked). Nothing writes; the
write tool `draft_followup` is not in the allowlist and the effect ceiling is `read`.

Env: `CL_MCP_TENANT_ID`, `CL_MCP_SANDBOX_ID` plus the usual `CL_DATABASE_URL`,
`CL_CONNECTOR_SECRET_KEY`, `CL_LLM_*` (Settings requires them). Run: `python -m cortex_leads.mcp_server`.

Claude Code: `claude mcp add cortex-leads -e CL_MCP_TENANT_ID=<uuid> -e CL_MCP_SANDBOX_ID=<uuid> ... -- /path/to/cortex-leads/.venv/bin/python -m cortex_leads.mcp_server`

Claude Desktop (`claude_desktop_config.json`):

    {"mcpServers": {"cortex-leads": {
      "command": "/path/to/cortex-leads/.venv/bin/python",
      "args": ["-m", "cortex_leads.mcp_server"],
      "cwd": "/path/to/cortex-leads",
      "env": {
        "CL_MCP_TENANT_ID": "<tenant uuid>", "CL_MCP_SANDBOX_ID": "<sandbox uuid>",
        "CL_DATABASE_URL": "postgresql+asyncpg://cl_app:<password>@localhost:5544/cortex_leads",
        "CL_CONNECTOR_SECRET_KEY": "<fernet key>", "CL_LLM_BASE_URL": "http://localhost:0/v1",
        "CL_LLM_API_KEY": "unused", "CL_LLM_MODEL_LITE": "unused"}}}}

It connects as `cl_app` (RLS applies), never as owner.

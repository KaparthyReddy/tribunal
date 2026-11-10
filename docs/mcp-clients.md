# MCP clients

Tribunal exposes three tools over stdio: `submit`, `verdict` and `verify`.

Install the repository once and keep a `.env` with `ANTHROPIC_API_KEY` in it:

```
git clone https://github.com/KaparthyReddy/tribunal.git
cd tribunal
cp .env.example .env
uv sync
```

Replace `/ABSOLUTE/PATH/TO/tribunal` below with the real path.

## Claude Code

```
claude mcp add tribunal -- uv run --directory /ABSOLUTE/PATH/TO/tribunal tribunal mcp
```

## Cursor

`.cursor/mcp.json`

```json
{
  "mcpServers": {
    "tribunal": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/tribunal", "tribunal", "mcp"]
    }
  }
}
```

## Codex

`~/.codex/config.toml`

```toml
[mcp_servers.tribunal]
command = "uv"
args = ["run", "--directory", "/ABSOLUTE/PATH/TO/tribunal", "tribunal", "mcp"]
```

## Using it

Ask the agent to verify its own work before it reports done:

> Commit your changes, then call tribunal `submit` with this repository path, base `main`,
> head `HEAD`, the PR title and description, and the test command. Treat `fail` as blocking.

`submit` blocks until the verdict is ready and returns the verdict, findings, claim statuses
and a receipt id. `verify` checks that a receipt was not altered and was signed by this server.

To restrict which repositories the server may read, set `TRIBUNAL_ALLOWED_REPO_ROOTS` in `.env`
to a JSON list, for example `["/Users/you/code"]`.

#!/usr/bin/env python
"""Call one MCP tool and wait for it without a deadline. Hang test use only.

Used by runbook test B to put a call on the tool worker of the test
instance; against the trickle server that call never returns, which is the
point. Run it in the background and kill it when the test is done.

    python deploy/hangtest/call_tool.py --url http://127.0.0.1:8113/sse \\
        get_identity '{"identity_name": "hangtest"}'
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _call(url: str, tool: str, arguments: dict) -> None:
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    # sse_read_timeout is per event; a day is "never" for this test.
    async with sse_client(url, sse_read_timeout=86400) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            sys.stderr.write(f"calling {tool} {json.dumps(arguments)}\n")
            result = await session.call_tool(tool, arguments)
            sys.stderr.write(f"returned: {result}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("tool")
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args(argv)
    asyncio.run(_call(args.url, args.tool, json.loads(args.arguments)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MCP-based agent workflow: discover challenges, start one, attack, record a submission.

This example shows how to interact with Droplet via the MCP server.
In practice, the MCP tools are called by your Agent framework (Claude Code, Cursor, etc.).

Usage:
    # Start the MCP server (usually configured in your Agent's mcpServers):
    PYTHONPATH=backend:sdk python -m droplet_sdk.mcp_server

    # Or via the installed entry point:
    droplet-mcp
"""

from __future__ import annotations

# The MCP server exposes these tools to your Agent:
#
#   list_challenges()              -> {"challenges": [...]}
#   start_challenge(challenge_id)  -> {"id": ..., "status": ..., "target_url": ...}
#   stop_challenge(challenge_id)   -> {"id": ..., "status": ...}
#   reset_challenge(challenge_id)  -> {"id": ..., "status": ...}
#   submit_answer(id, answer)      -> {"accepted": ..., "judged": ..., "correct": ...}
#   view_hint(challenge_id)        -> {"content": ..., "penalty": ...}
#   get_stats()                    -> {"total_challenges": ..., "solved": ...}
#   list_events(challenge_id)      -> {"events": [...]}
#   report_event(...)              -> event recorded
#
# MCP configuration for your Agent:
#
# {
#   "mcpServers": {
#     "droplet": {
#       "command": "python",
#       "args": ["-m", "droplet_sdk.mcp_server"],
#       "env": {
#         "DROPLET_BASE_URL": "http://127.0.0.1:1349",
#         "DROPLET_API_TOKEN": "your_token_here"
#       }
#     }
#   }
# }

print(__doc__)

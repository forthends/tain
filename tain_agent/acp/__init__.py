"""
ACP (Agent Communication Protocol) package.

Provides an ACP server over stdio transport that wraps a Tain agent
as an embeddable ACP-compatible service for editors like Zed.
"""

from tain_agent.acp.server import ACPServer

__all__ = ["ACPServer"]

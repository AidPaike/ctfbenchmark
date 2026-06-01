from droplet_sdk.client import DropletClient

__all__ = ["DropletClient"]

try:
    from droplet_sdk.mcp_server import mcp

    __all__.append("mcp")
except ImportError:
    pass

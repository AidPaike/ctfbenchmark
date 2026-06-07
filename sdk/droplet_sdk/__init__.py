try:
    from droplet_sdk.mcp_server import mcp  # noqa: F401

    __all__ = ["mcp"]
except ImportError:
    __all__ = []

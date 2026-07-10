"""Vercel ASGI entry point for trainingpeaks-mcp.

This module initializes the MCP HTTP server for Vercel's serverless runtime.
The sys.path shim is needed because Vercel's Python runtime doesn't natively
support the src/ layout — we insert src/ to resolve imports to tp_mcp package.

The app fails closed if MCP_AUTH_SECRET is unset — security by default.
"""

import sys
from pathlib import Path

# Insert src/ directory into sys.path so imports resolve correctly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from tp_mcp.http_app import create_app

# Fails closed: raises RuntimeError if MCP_AUTH_SECRET environment variable is unset.
app = create_app()

"""
Server configuration — MCP instance, settings, and logging.

This module is imported by all tool modules. It handles:
  - Loading .env from the project directory (absolute path)
  - Creating the pydantic-settings config object
  - Configuring structlog JSON logging
  - Creating the shared FastMCP server instance

No circular imports: this module depends only on config.py and logging_config.py.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project directory regardless of where Claude Desktop
# sets the working directory when it launches this process.
load_dotenv(Path(__file__).parent / ".env")

import structlog
from mcp.server.fastmcp import FastMCP

from config import get_settings
from logging_config import configure_logging

settings = get_settings()

# Resolve log file path relative to THIS script's directory, not cwd.
_log_file = str(Path(__file__).parent / settings.log_file)
configure_logging(settings.log_level, _log_file)

log = structlog.get_logger(__name__)

mcp = FastMCP(
    "ServiceTitan",
    instructions=(
        "Access ServiceTitan job management data for American Leak Detection. "
        "All responses show aggregated business metrics only — no customer PII. "
        "Use these tools to answer questions about technician jobs, revenue, "
        "schedules, and business performance."
    ),
)

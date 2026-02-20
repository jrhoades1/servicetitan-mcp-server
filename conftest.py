"""Root conftest — ensures project root is on sys.path for pytest.

Also injects dummy ServiceTitan credentials so pydantic-settings doesn't
raise a ValidationError when tool modules are imported during collection.
These values are never used for real API calls — tests mock fetch_all_pages.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Must happen before any local imports so tool modules can be collected.
sys.path.insert(0, str(Path(__file__).parent))

os.environ.setdefault("ST_CLIENT_ID", "test-client-id")
os.environ.setdefault("ST_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("ST_APP_KEY", "test-app-key")
os.environ.setdefault("ST_TENANT_ID", "12345678")

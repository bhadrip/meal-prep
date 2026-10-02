"""Exercise the portable package's connection against the actual ASGI app."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_marketplace_resolves_one_self_contained_portable_plugin():
    catalog = json.loads((REPO_ROOT / ".agents/plugins/marketplace.json").read_text())
    assert catalog["name"] == "badri-personal-plugins"
    assert len(catalog["plugins"]) == 1
    entry = catalog["plugins"][0]
    package = (REPO_ROOT / entry["source"]["path"]).resolve()
    assert package.is_relative_to(REPO_ROOT)
    manifest = json.loads((package / "plugin.json").read_text())
    mcp = json.loads((package / "mcp.json").read_text())
    assert manifest["name"] == entry["name"] == "meal-prep"
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert mcp["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert mcp["mcpServers"]["meal-prep"]["type"] == "streamable-http"
    interface = manifest["extensions"]["com.openai"]["interface"]
    assert len(interface["shortDescription"]) <= 30
    for key in ("composerIcon", "logo"):
        asset = (package / interface[key]).resolve()
        assert asset.is_relative_to(package) and asset.is_file()
    assert (package / "skills/meal-prep-planning/SKILL.md").is_file()
    for relative in (".claude-plugin/marketplace.json", "plugin/.claude-plugin/plugin.json",
                     "plugin/.codex-plugin/plugin.json", "plugin/.mcp.json"):
        assert not (REPO_ROOT / relative).exists()


@pytest.mark.parametrize("origin", [None, "http://127.0.0.1:18765"])
def test_plugin_and_landing_match_oauth_resource_and_require_authorization(origin, tmp_path):
    package = REPO_ROOT / "plugin"
    manifest = json.loads((package / "plugin.json").read_text())
    endpoint = json.loads((package / "mcp.json").read_text())["mcpServers"]["meal-prep"]["url"]
    if origin is None:
        origin = manifest["homepage"]
        assert endpoint == "https://meal-prep.madhavan-padmaja.dev/mcp"
        assert endpoint == f"{origin}/mcp"
    else:
        endpoint = f"{origin}/mcp"

    # A fresh process builds the real MCP auth middleware from deployment settings
    # without changing modules cached by the rest of the backend test suite.
    script = '''
import json
import os
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, base_url=os.environ["APP_BASE_URL"]) as client:
    metadata = client.get("/.well-known/oauth-protected-resource/mcp")
    landing = client.get("/", headers={"Host": "stale.example.com"})
    denied = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    print(json.dumps({
        "metadataStatus": metadata.status_code,
        "resource": metadata.json()["resource"],
        "landingStatus": landing.status_code,
        "endpoint": landing.text.split('<code id="mcp-url">', 1)[1].split('</code>', 1)[0],
        "deniedStatus": denied.status_code,
        "challenge": denied.headers.get("www-authenticate", ""),
    }))
'''
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True,
        timeout=30, check=True, env={
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT / "backend"),
            "APP_BASE_URL": origin,
            "AUTH_REQUIRED": "true",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-test-key",
        },
    )
    observed = json.loads(result.stdout)
    assert observed["metadataStatus"] == observed["landingStatus"] == 200
    assert observed["resource"] == observed["endpoint"] == endpoint
    assert observed["deniedStatus"] == 401
    assert f'resource_metadata="{origin}/.well-known/oauth-protected-resource/mcp"' in observed["challenge"]

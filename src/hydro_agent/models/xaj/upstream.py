"""Load only pinned numerical modules, avoiding hydromodel's data-tool initializers.

Upstream sources are installed unmodified. Namespaces are created only inside the
numerical worker; this is not a replacement implementation of XAJ.
"""

import importlib
import importlib.metadata
import json
import sys
import types
from pathlib import Path

from .contracts import UPSTREAM_COMMIT


def _pinned_install(direct: dict) -> bool:
    url = str(direct.get("url") or "")
    commit = str((direct.get("vcs_info") or {}).get("commit_id") or "")
    archive = f"https://github.com/OuyangWenyu/hydromodel/archive/{UPSTREAM_COMMIT}.tar.gz"
    git_url = "https://github.com/OuyangWenyu/hydromodel.git"
    return url == archive or (url.startswith(git_url) and commit.startswith(UPSTREAM_COMMIT))


def load_xaj():
    dist = importlib.metadata.distribution("hydromodel")
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    if not _pinned_install(direct):
        raise ValueError("hydromodel commit mismatch")
    root = Path(dist.locate_file("hydromodel")).resolve()
    for name, path in [("hydromodel", root), ("hydromodel.models", root / "models")]:
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
    return importlib.import_module("hydromodel.models.xaj").xaj

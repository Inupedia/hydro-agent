import json
import os
import subprocess
import sys
import time
from pathlib import Path

workspace, mode = Path(sys.argv[1]), sys.argv[2]
result = workspace / "output/result.json"
if mode == "fail":
    raise SystemExit(7)
if mode == "sleep":
    time.sleep(10)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    (workspace / "work/child.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(10)
if mode == "large":
    result.write_text("x" * 2048, encoding="utf-8")
elif mode == "log":
    print("x" * 2048)
elif mode == "invalid":
    result.write_text("{oops", encoding="utf-8")
elif mode == "array":
    result.write_text("[]", encoding="utf-8")
elif mode == "nan":
    result.write_text('{"value":NaN}', encoding="utf-8")
elif mode == "symlink":
    result.symlink_to("/etc/hosts")
elif mode == "env":
    result.write_text(
        json.dumps({"secret_present": "SILICONFLOW_API_KEY" in os.environ}), encoding="utf-8"
    )
elif mode == "success":
    result.write_text(json.dumps({"value": 42}), encoding="utf-8")
print("fixture-runtime-finished")

"""Inspect the open Bayanat/FLEURS Arabic dataset's public row API.

Intentionally prints only row keys, field types, audio URL host and reference
availability; it never publishes raw audio or private access tokens.
"""
from __future__ import annotations
import json
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen, Request

base = "https://datasets-server.huggingface.co/rows"
params = {"dataset": "Bayanat-Labs/arabic-asr-channel-pairs", "config": "CLEAN",
          "split": "test", "offset": "0", "length": "1"}
url = base + "?" + urlencode(params)
with urlopen(Request(url, headers={"User-Agent":"Nass-MCP-Arabic-Eval/0.5"}), timeout=30) as response:
    content = response.read(350000)
data = json.loads(content)
rows = data.get("rows") or []
if not rows:
    raise SystemExit("Dataset row endpoint returned no rows")
row = rows[0].get("row") or {}
summary = {}
for k,v in row.items():
    entry = {"type": type(v).__name__}
    if isinstance(v, dict):
        entry["keys"] = list(v.keys())[:20]
        if isinstance(v.get("src"), str):
            entry["src_host"] = urlsplit(v["src"]).hostname
    elif isinstance(v, str):
        entry["chars"] = len(v)
        if k.lower() in ("text", "sentence", "reference", "transcript"):
            entry["reference_preview"] = v[:130]
    summary[k] = entry
print(json.dumps({"dataset":params["dataset"],"config":params["config"],
                  "split":params["split"],"fields":summary}, ensure_ascii=False, indent=2))

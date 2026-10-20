"""Run a real-world smoke test ONLY when network access and packages are ready.
Usage: python scripts/live_smoke.py 'https://youtu.be/VIDEOID' --mode audio
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from nass_mcp.core import Engine, get_video_id


def main():
    p = argparse.ArgumentParser()
    p.add_argument('url')
    p.add_argument('--mode', choices=['auto', 'captions', 'audio', 'verify'], default='audio')
    p.add_argument('--language', default='ar')
    p.add_argument('--output', default='live-smoke-result.json')
    args = p.parse_args()
    result = Engine().transcribe(get_video_id(args.url), args.language, args.mode)
    target = Path(args.output)
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False), 'utf8')
    print(json.dumps({'ok': result.get('ok'), 'source': result.get('source'),
                      'segments': len(result.get('segments', [])),
                      'attempts': result.get('attempts'), 'output': str(target)},
                     indent=2, ensure_ascii=False))
    if not result.get('ok'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()

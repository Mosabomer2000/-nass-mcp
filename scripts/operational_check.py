"""Run reproducible Nass operational gates and emit evidence JSON.

Exit 0 = all requested gates pass; 2 = integration blocked or tests failed.
`--live` enables real YouTube attempts, and only if required Python packages are installed.
Do not treat fixture-backed local tests as proof that YouTube or ASR models work.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

BACKENDS = ('mcp', 'yt_dlp', 'youtube_transcript_api', 'pytubefix', 'faster_whisper')
COMMANDS = ('ffmpeg', 'ffprobe', 'node', 'deno', 'whisper-cli', 'yt-transcript', 'youtubedr')


def run_process(args, *, seconds=60, env=None):
    try:
        p = subprocess.run(args, text=True, capture_output=True, timeout=seconds, env=env)
        return {'ok': p.returncode == 0, 'returncode': p.returncode,
                'stdout_tail': p.stdout[-1400:], 'stderr_tail': p.stderr[-700:]}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'timeout': True}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--live', action='store_true', help='attempt real YouTube tests')
    p.add_argument('--video', default='https://youtu.be/QxC5E44QoZY')
    p.add_argument('--language', default='ar')
    p.add_argument('--output', default='nass-operational-report.json')
    opts = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'src')
    env.setdefault('NASS_DATA_DIR', str(root / '.operational-work'))
    components = {x: importlib.util.find_spec(x) is not None for x in BACKENDS}
    components.update({x: shutil.which(x) is not None for x in COMMANDS})
    result = {'date_utc': datetime.now(timezone.utc).isoformat(),
              'project': 'nass-mcp', 'version': '0.2.1',
              'dependency_presence': components,
              'tests': {}}
    test = run_process([sys.executable, '-m', 'pytest', '-q',
                        'tests/test_core.py', 'tests/test_v02.py', 'tests/test_operational.py'],
                       seconds=75, env=env)
    result['tests']['offline_regression_and_process_integration'] = test
    result['tests']['sdk_server_import'] = (
        {'state': 'PASS', 'details': run_process([sys.executable, '-c',
            'from nass_mcp.server import mcp; print(type(mcp).__name__)'], seconds=12, env=env)}
        if components['mcp'] else {'state': 'BLOCKED', 'reason': 'mcp Python SDK not installed'})
    if components['mcp'] and not result['tests']['sdk_server_import']['details']['ok']:
        result['tests']['sdk_server_import']['state'] = 'FAIL'
    if opts.live:
        try:
            socket.getaddrinfo('www.youtube.com', 443)
            result['tests']['youtube_dns'] = {'state': 'PASS'}
        except OSError as e:
            result['tests']['youtube_dns'] = {'state': 'BLOCKED', 'reason': type(e).__name__}
        for mode in ('captions', 'audio'):
            if mode == 'captions':
                possible = (components['yt_dlp'] or components['youtube_transcript_api']
                            or components['yt-transcript'])
            else:
                node_package = (root / 'src' / 'nass_mcp' / '_node' / 'node_modules' / 'youtubei.js').exists()
                possible = (components['yt_dlp'] or components['pytubefix'] or
                            components['youtubedr'] or (components['node'] and node_package))
            if not possible or result['tests']['youtube_dns']['state'] != 'PASS':
                result['tests']['live_'+mode] = {'state':'BLOCKED',
                    'reason':'DNS inaccessible or essential extractors not installed'}
                continue
            fname = root / f'.live-{mode}-result.json'
            cmd = [sys.executable, str(root/'scripts'/'live_smoke.py'), opts.video,
                   '--mode', mode, '--language', opts.language, '--output', str(fname)]
            attempt = run_process(cmd, seconds=210, env=env)
            result['tests']['live_'+mode] = {'state': 'PASS' if attempt['ok'] else 'FAIL',
                                            'details': attempt}
    result['overall'] = ('PASS' if test['ok'] and
        all(t.get('state', 'PASS') == 'PASS' for t in result['tests'].values())
        else 'INCOMPLETE_OR_FAILED')
    Path(opts.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf8')
    print(json.dumps({'overall': result['overall'],
        'tests': {k:v.get('state', 'PASS' if v.get('ok') else 'FAIL') for k,v in result['tests'].items()},
        'output': opts.output}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['overall']=='PASS' else 2)

if __name__ == '__main__':
    main()

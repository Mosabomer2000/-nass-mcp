"""Process-level OFFLINE integration tests.

Tests run actual espeak/ffmpeg/ffprobe/Node/subprocess/JobStore operations.
The ASR CLI and YouTube.js Innertube HTTP response are simulated: these tests
MUST NEVER be represented as real speech-recognition or real YouTube successes.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap
import time

import pytest
from nass_mcp import core

VIDEO_ID = 'QxC5E44QoZY'


def make_speech(tmp_path: Path) -> Path:
    if not shutil.which('espeak'):
        pytest.skip('espeak not installed')
    out = tmp_path / 'spoken.wav'
    subprocess.run(['espeak', '-w', str(out), '-s', '115',
                    'The quick brown fox jumps over the lazy dog.'], check=True, capture_output=True)
    return out


def wait(store, jobid, desired='completed'):
    for _ in range(150):
        status = store.get_status(jobid)
        if status['state'] in ('completed', 'failed'):
            return status
        time.sleep(0.03)
    pytest.fail('job did not finish')


def test_process_pipeline_espeak_ffmpeg_cli_export_and_excerpt(tmp_path, monkeypatch):
    """Real file/process/persistence pipeline; recognizer executable is a declared stub."""
    source_dir = tmp_path / 'intake'
    source_dir.mkdir()
    voice = make_speech(source_dir)
    monkeypatch.setattr(core, 'MEDIA_ROOT', source_dir)
    model = tmp_path / 'simulated-model.bin'
    model.write_bytes(b'STUB NOT A REAL MODEL')
    fake_cli = tmp_path / 'fake_whisper_cli.py'
    fake_cli.write_text(textwrap.dedent('''\
        #!/usr/bin/env python3
        import argparse, pathlib, wave
        p=argparse.ArgumentParser()
        p.add_argument('-m'); p.add_argument('-f'); p.add_argument('-l')
        p.add_argument('-osrt',action='store_true'); p.add_argument('-of')
        p.add_argument('--prompt', default='')
        args=p.parse_args()
        with wave.open(args.f, 'rb') as wav:
            assert wav.getframerate()==16000
            assert wav.getnchannels()==1
            assert wav.getnframes()>10000
        pathlib.Path(args.of+'.srt').write_text(
            '1\\n00:00:00,000 --> 00:00:01,300\\nSTUB TRANSCRIPT FROM TEST HARNESS\\n'
        )
    '''))
    fake_cli.chmod(0o755)
    monkeypatch.setenv('NASS_WHISPER_CPP_BIN', str(fake_cli))
    monkeypatch.setenv('NASS_WHISPER_CPP_MODEL', str(model))
    monkeypatch.delenv('NASS_ALLOW_EXTERNAL_ASR', raising=False)
    eng = core.Engine(tmp_path / 'engine')
    store = core.JobStore(eng)
    submitted = store.submit(voice.name, language='en', mode='audio', local=True)
    status = wait(store, submitted['job_id'])
    assert status['state'] == 'completed', status
    result = store.read(submitted['job_id'])
    assert result['source'] == 'asr:whisper.cpp'
    assert result['segments'][0]['text'].startswith('STUB TRANSCRIPT')
    assert result['attempts'][0]['provider'] == 'faster-whisper'
    assert result['attempts'][0]['ok'] is False
    assert result['attempts'][1]['provider'] == 'whisper.cpp'
    assert result['attempts'][1]['ok'] is True
    for fmt in ('txt','json','srt'):
        ex = store.export(submitted['job_id'], fmt)
        assert ex['ok'] and Path(ex['file_on_server']).stat().st_size > 10
    clip = store.make_audio_clip(submitted['job_id'], 0.2, 1.0)
    assert 0.85 <= eng.check_audio(clip) <= 1.15
    found = store.search(submitted['job_id'], 'STUB TRANSCRIPT')
    assert found['total_matches']==1
    restarted_store = core.JobStore(eng)
    persisted = restarted_store.read(submitted['job_id'])
    assert persisted['segments']==result['segments']


def test_actual_node_audio_stream_adapter_with_local_transport(tmp_path, monkeypatch):
    """Execute the actual shipped Node adapter against a local in-process fixture."""
    if not shutil.which('node'):
        pytest.skip('node not installed')
    src = tmp_path / 'sample.m4a'
    spoken = make_speech(tmp_path)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-i',str(spoken),
                    '-vn','-c:a','aac',str(src)], check=True,capture_output=True)
    scriptdir = tmp_path / 'adapter'
    scriptdir.mkdir()
    script = scriptdir/'youtubejs_audio.mjs'
    script.write_text((Path(core.__file__).parent/'_node'/'youtubejs_audio.mjs').read_text('utf8'), 'utf8')
    package = scriptdir/'node_modules'/'youtubei.js'
    package.mkdir(parents=True)
    (package/'package.json').write_text(json.dumps({'name':'youtubei.js','type':'module', 'exports':'./index.js'}))
    (package/'index.js').write_text(textwrap.dedent('''\
        import { readFileSync } from 'node:fs';
        export class Innertube {
          static async create() { return new Innertube(); }
          async download(id, opts) {
            if (id !== 'QxC5E44QoZY' || opts.type !== 'audio') throw new Error('bad options');
            const bytes = readFileSync(process.env.NASS_TEST_AUDIO_FILE);
            return new ReadableStream({ start(controller) {
              controller.enqueue(bytes); controller.close();
            }});
          }
        }
    '''))
    monkeypatch.setenv('NASS_YOUTUBEJS_SCRIPT',str(script))
    monkeypatch.setenv('NASS_TEST_AUDIO_FILE', str(src))
    eng=core.Engine(tmp_path/'engine')
    output=eng.youtubejs_audio(VIDEO_ID, tmp_path/'output')
    assert output.exists()
    assert output.read_bytes()==src.read_bytes()
    assert eng.check_audio(output)>1
    # Enforce stream limiter: verify partial output gets deleted rather than cached.
    monkeypatch.setattr(core, 'MAX_AUDIO_BYTES', 2048)
    with pytest.raises(subprocess.CalledProcessError):
        eng.youtubejs_audio(VIDEO_ID, tmp_path/'too_small')
    assert not (tmp_path/'too_small'/'audio.m4a').exists()


def test_download_audio_job_real_source_from_local_adapter(tmp_path, monkeypatch):
    """Actual audio bytes flow through acquisition, persistence, clipping with no ASR."""
    spoken=make_speech(tmp_path)
    monkeypatch.setenv('NASS_AUDIO_CACHE', '0')
    eng=core.Engine(tmp_path/'engine')
    def local_audio_proxy(video_id, target, client):
        target.mkdir(parents=True,exist_ok=True)
        output=target/'audio.wav'
        shutil.copy2(spoken,output)
        return output
    monkeypatch.setattr(eng,'ytdlp_audio',local_audio_proxy)
    jobs=core.JobStore(eng)
    job=jobs.submit_audio_download(VIDEO_ID)
    status=wait(jobs,job['job_id'])
    assert status['state']=='completed'
    data=jobs.read(job['job_id'])
    assert data['ok'] and data['source']=='raw_audio:yt-dlp/default'
    assert data['size_bytes']>1000
    assert 0.9<eng.check_audio(jobs.make_audio_clip(job['job_id'],0.0,1.0))<1.1


def test_mcp_audio_import_matches_upstream_package_layout():
    """Guard against importing Audio from deprecated/unsupported SDK location."""
    p=Path(__file__).parents[1]/'src'/'nass_mcp'/'server.py'
    data=p.read_text('utf8')
    assert 'from mcp.server.mcpserver.utilities.types import Audio' in data
    assert 'from mcp.server.mcpserver import Audio' not in data

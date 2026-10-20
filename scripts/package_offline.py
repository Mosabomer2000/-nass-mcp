"""Deterministically refresh Nass wheel from v0.2.0 setuptools-built wheel.

For offline deployment testing only, no PyPI. Does not fetch dependencies.
Rebuild RECORD checksums, preserve the old wheel's metadata/dependency graph,
and patch package payload from sources for v0.2.1. Prefer setuptools when
wheel/build is available on the machine.
"""
from __future__ import annotations
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT.parent/'dist/nass_mcp-0.2.0-py3-none-any.whl'
NEW=ROOT.parent/'dist/nass_mcp-0.2.1-py3-none-any.whl'
ZIP=ROOT.parent/'nass-mcp-v0.2.1-source.zip'

def rebuild():
    entries={}
    with zipfile.ZipFile(OLD) as infile:
        for fn in infile.namelist():
            if fn.endswith('/RECORD'): continue
            target=fn.replace('nass_mcp-0.2.0.dist-info','nass_mcp-0.2.1.dist-info')
            data=infile.read(fn)
            if fn=='nass_mcp-0.2.0.dist-info/METADATA':
                head=data.split(b'\n\n',1)[0].replace(b'Version: 0.2.0', b'Version: 0.2.1')
                data=head+b'\n\n'+(ROOT/'README.md').read_bytes()
            elif target.startswith('nass_mcp/'):
                data=(ROOT/'src'/target).read_bytes()
            entries[target]=data
    record_name='nass_mcp-0.2.1.dist-info/RECORD'
    b=io.StringIO()
    writer=csv.writer(b,lineterminator='\n')
    for fn,data in sorted(entries.items()):
        digest=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow([fn,'sha256='+digest,str(len(data))])
    writer.writerow([record_name,'',''])
    entries[record_name]=b.getvalue().encode()
    with zipfile.ZipFile(NEW,'w',compression=zipfile.ZIP_DEFLATED) as out:
        for fn,data in sorted(entries.items()): out.writestr(fn,data)
    include=['src/nass_mcp','tests','scripts','docs','integration']
    rootfiles=['README.md','LICENSE','pyproject.toml','.gitignore']
    with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_DEFLATED) as out:
        for fn in rootfiles:
            out.write(ROOT/fn,arcname='nass-mcp/'+fn)
        for name in include:
            for path in sorted((ROOT/name).rglob('*')):
                if not path.is_file(): continue
                if path.suffix in ('.pyc','.pyo') or any(s.startswith('.') or s=='__pycache__' for s in path.relative_to(ROOT).parts): continue
                out.write(path,arcname='nass-mcp/'+str(path.relative_to(ROOT)))
    print(NEW,NEW.stat().st_size)
    print(ZIP,ZIP.stat().st_size)

if __name__=='__main__': rebuild()

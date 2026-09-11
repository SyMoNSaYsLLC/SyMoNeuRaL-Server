#!/usr/bin/env python3
"""Create/verify deterministic content manifests for storage migration leaves.

Manifest columns: TYPE, RELPATH, SIZE_BYTES, SHA256, MODE, LINK_TARGET.
Does not follow symlinks. Writes atomically. Safe to run without moving/deleting data.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, csv, hashlib, os, stat
from pathlib import Path

FIELDS=['TYPE','RELPATH','SIZE_BYTES','SHA256','MODE','LINK_TARGET']

def sha256_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as fh:
        for b in iter(lambda: fh.read(4<<20), b''): h.update(b)
    return h.hexdigest()

def entries(root: Path):
    if root.is_symlink():
        st=root.lstat(); return [('SYMLINK',Path('.'),st.st_size,'',stat.S_IMODE(st.st_mode),os.readlink(root))]
    if root.is_file():
        st=root.stat(); return [('FILE',Path(root.name),st.st_size,None,stat.S_IMODE(st.st_mode),'')]
    rows=[]
    # Include root dir explicitly.
    st=root.lstat(); rows.append(('DIR',Path('.'),0,'',stat.S_IMODE(st.st_mode),''))
    for dp,dns,fns in os.walk(root,followlinks=False):
        d=Path(dp)
        for n in sorted(dns):
            p=d/n; rel=p.relative_to(root)
            st=p.lstat()
            if p.is_symlink(): rows.append(('SYMLINK',rel,st.st_size,'',stat.S_IMODE(st.st_mode),os.readlink(p)))
            else: rows.append(('DIR',rel,0,'',stat.S_IMODE(st.st_mode),''))
        for n in sorted(fns):
            p=d/n; rel=p.relative_to(root); st=p.lstat()
            if p.is_symlink(): rows.append(('SYMLINK',rel,st.st_size,'',stat.S_IMODE(st.st_mode),os.readlink(p)))
            elif p.is_file(): rows.append(('FILE',rel,st.st_size,None,stat.S_IMODE(st.st_mode),''))
    return rows

def make(root: Path, out: Path, workers: int):
    rows=entries(root)
    file_idxs=[i for i,r in enumerate(rows) if r[0]=='FILE']
    def h(i):
        r=rows[i]; rel=r[1]
        p=root if root.is_file() and rel==Path(root.name) else root/rel
        return i,sha256_file(p)
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i,d in ex.map(h,file_idxs):
            r=list(rows[i]); r[3]=d; rows[i]=tuple(r)
    rows.sort(key=lambda r:(str(r[1]),r[0]))
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+'.tmp')
    with tmp.open('w',newline='',encoding='utf-8') as fh:
        w=csv.writer(fh,delimiter='\t',lineterminator='\n'); w.writerow(FIELDS)
        for typ,rel,size,digest,mode,link in rows:
            w.writerow([typ,str(rel),size,digest or '',f'{mode:04o}',link])
    os.chmod(tmp,0o600); tmp.replace(out)
    manifest_sha=sha256_file(out)
    side=out.with_suffix(out.suffix+'.sha256')
    side.write_text(f'{manifest_sha}  {out.name}\n'); os.chmod(side,0o600)
    print(f'MANIFEST={out}')
    print(f'ROWS={len(rows)}')
    print(f'FILES={len(file_idxs)}')
    print(f'MANIFEST_SHA256={manifest_sha}')

def verify(root: Path, manifest: Path, workers: int):
    with manifest.open(newline='',encoding='utf-8') as fh:
        data=list(csv.DictReader(fh,delimiter='\t'))
    bad=[]; files=[]
    for row in data:
        rel=Path(row['RELPATH'])
        p=root if root.is_file() and rel==Path(root.name) else root/rel
        typ=row['TYPE']
        try:
            if typ=='DIR':
                if not p.is_dir() or p.is_symlink(): bad.append((row['RELPATH'],'DIR_MISMATCH'))
            elif typ=='SYMLINK':
                if not p.is_symlink(): bad.append((row['RELPATH'],'SYMLINK_MISSING'))
                elif os.readlink(p)!=row['LINK_TARGET']: bad.append((row['RELPATH'],'LINK_TARGET'))
            elif typ=='FILE':
                if not p.is_file() or p.is_symlink(): bad.append((row['RELPATH'],'FILE_MISSING'))
                elif p.stat().st_size!=int(row['SIZE_BYTES']): bad.append((row['RELPATH'],'SIZE'))
                else: files.append((row,p))
        except OSError as e: bad.append((row['RELPATH'],f'OSERROR:{e}'))
    def chk(item):
        row,p=item; return row['RELPATH'],sha256_file(p)==row['SHA256']
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for rel,ok in ex.map(chk,files):
            if not ok: bad.append((rel,'SHA256'))
    print(f'VERIFIED_ROWS={len(data)}')
    print(f'MISMATCHES={len(bad)}')
    for rel,why in bad[:50]: print(f'BAD\t{why}\t{rel}')
    return 1 if bad else 0

def main():
    ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest='cmd',required=True)
    p=sp.add_parser('make'); p.add_argument('source'); p.add_argument('output'); p.add_argument('--workers',type=int,default=min(16,(os.cpu_count() or 4)))
    p=sp.add_parser('verify'); p.add_argument('source'); p.add_argument('manifest'); p.add_argument('--workers',type=int,default=min(16,(os.cpu_count() or 4)))
    a=ap.parse_args()
    root=Path(a.source)
    if not root.exists() and not root.is_symlink(): raise SystemExit(f'source absent: {root}')
    if a.cmd=='make': make(root,Path(a.output),a.workers); return 0
    return verify(root,Path(a.manifest),a.workers)
if __name__=='__main__': raise SystemExit(main())

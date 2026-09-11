#!/usr/bin/env python3
"""Read-only storage audit for the SyMoNeuRaL cleanup/reorganization.

Produces durable JSON/TSV/Markdown evidence without moving or deleting anything.
Designed to answer the repetitive questions the coder has been re-measuring by hand.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import time

DEFAULT_ROOT = Path('/home/google/Symoneural')
DEFAULT_HOME = Path('/home/google')
DEFAULT_YOCTO = Path('/yocto')
MUTATOR_MARKERS = (
    'storage_reorg.py run', 'storage_reorg.py resume',
    'cleanup-pipeline', 'offload-to-drive', 'upstream-to-drive',
    'rclone copy', 'rclone move', 'rclone moveto',
)


def run(args, timeout=1800):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def human(n: int) -> str:
    x = float(n)
    for u in ('B','KiB','MiB','GiB','TiB'):
        if x < 1024 or u == 'TiB':
            return f'{x:.1f} {u}' if u != 'B' else f'{int(x)} B'
        x /= 1024
    return str(n)


def proc_snapshot():
    rows=[]
    me=os.getpid()
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==me:
            continue
        try:
            raw=(p/'cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8','replace').strip()
        except Exception:
            continue
        if not raw:
            continue
        if any(m in raw for m in MUTATOR_MARKERS):
            try:
                stat=(p/'stat').read_text().split()
                state=stat[2]
            except Exception:
                state='?'
            rows.append({'pid':int(p.name),'state':state,'cmd':raw})
    return sorted(rows,key=lambda r:r['pid'])


def df_row(path: Path):
    r=run(['df','-B1','--output=source,size,used,avail,pcent,target',str(path)],120)
    lines=[x for x in r.stdout.splitlines() if x.strip()]
    if len(lines)<2:
        return {'path':str(path),'error':r.stderr.strip() or 'df failed'}
    parts=lines[-1].split()
    return {
        'source':parts[0], 'size_bytes':int(parts[1]), 'used_bytes':int(parts[2]),
        'avail_bytes':int(parts[3]), 'percent':parts[4], 'target':parts[5]
    }


def du_bytes(path: Path) -> int:
    r=run(['du','-sb','--one-file-system',str(path)],3600)
    try: return int(r.stdout.split()[0])
    except Exception: return 0


def top_level(path: Path):
    rows=[]
    if not path.exists():
        return rows
    for p in sorted(path.iterdir(), key=lambda x:x.name.lower()):
        # Symlink itself, not its target.
        try:
            if p.is_symlink():
                n=p.lstat().st_size
                typ='SYMLINK'
            else:
                n=du_bytes(p)
                typ='DIR' if p.is_dir() else 'FILE'
        except Exception:
            n=0; typ='ERROR'
        rows.append({'name':p.name,'path':str(p),'type':typ,'bytes':n})
    return sorted(rows,key=lambda r:r['bytes'],reverse=True)


def rclone_root(remote: str):
    r=run(['rclone','lsjson',remote,'--hash'],1800)
    if r.returncode != 0:
        return [], (r.stderr.strip() or r.stdout.strip() or 'rclone lsjson failed')
    try:
        data=json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return [], f'JSON parse failed: {e}'
    rows=[]
    for x in data:
        h=x.get('Hashes') or {}
        rows.append({
            'name':x.get('Name') or x.get('Path') or '',
            'path':x.get('Path') or x.get('Name') or '',
            'is_dir':bool(x.get('IsDir')),
            'size':int(x.get('Size') or 0),
            'md5':h.get('md5') or h.get('MD5') or '',
            'id':x.get('ID') or '',
            'mime_type':x.get('MimeType') or '',
        })
    return rows, None


def write_tsv(path: Path, rows, fields):
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',newline='',encoding='utf-8') as fh:
        w=csv.DictWriter(fh,fieldnames=fields,delimiter='\t',extrasaction='ignore')
        w.writeheader(); w.writerows(rows)
    os.chmod(tmp,0o600); tmp.replace(path)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',default=str(DEFAULT_ROOT))
    ap.add_argument('--home',default=str(DEFAULT_HOME))
    ap.add_argument('--yocto',default=str(DEFAULT_YOCTO))
    ap.add_argument('--remote',default='gdrive:')
    ap.add_argument('--out-dir',default='')
    a=ap.parse_args()
    root=Path(a.root); home=Path(a.home); yocto=Path(a.yocto)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    out=Path(a.out_dir) if a.out_dir else root/'.private'/'storage-reorg'/'audit'/stamp
    out.mkdir(parents=True,exist_ok=True); os.chmod(out,0o700)

    procs=proc_snapshot()
    fs={'root':df_row(Path('/')), 'home':df_row(home), 'yocto':df_row(yocto)}
    yo=top_level(yocto); sy=top_level(root); ho=top_level(home)
    drive, derr=rclone_root(a.remote)

    state_summary={}
    state_path=root/'.private'/'storage-reorg'/'state.json'
    if state_path.is_file():
        try:
            st=json.loads(state_path.read_text())
            counts={}
            for v in (st.get('ops') or {}).values():
                s=v.get('state','?'); counts[s]=counts.get(s,0)+1
            state_summary={'path':str(state_path),'counts':counts,'ops':len(st.get('ops') or {})}
        except Exception as e:
            state_summary={'path':str(state_path),'error':str(e)}

    drive_names={r['name'] for r in drive}
    problem=['Projects_Organize','offload','DONOTDELETE','Historical-Archive','sendtodrive']
    gates={
        'drive_problem_buckets_present':[x for x in problem if x in drive_names],
        'drive_root_entries':len(drive),
        'drive_root_loose_files':sum(1 for x in drive if not x['is_dir']),
        'yocto_artifacts_present':(yocto/'artifacts').exists(),
        'yocto_sendtodrive_present':(yocto/'sendtodrive').exists(),
        'yocto_archives_present':(yocto/'Archives').exists(),
        'symoneural_external_present':(root/'external').exists(),
        'index_present':'INDEX.md' in drive_names,
        'catalog_present':'CATALOG.tsv' in drive_names,
        'migration_map_present':'MIGRATION-MAP.tsv' in drive_names,
        'duplicates_ledger_present':'DUPLICATES.tsv' in drive_names,
    }

    payload={
        'measured_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'mutation_processes':procs,'filesystems':fs,'state':state_summary,
        'gates':gates,'drive_error':derr,
    }
    (out/'summary.json').write_text(json.dumps(payload,indent=2)+'\n'); os.chmod(out/'summary.json',0o600)
    write_tsv(out/'yocto-top.tsv',yo,['name','path','type','bytes'])
    write_tsv(out/'symoneural-top.tsv',sy,['name','path','type','bytes'])
    write_tsv(out/'home-top.tsv',ho,['name','path','type','bytes'])
    write_tsv(out/'drive-root.tsv',drive,['name','path','is_dir','size','md5','id','mime_type'])

    md=[]
    md += ['# SyMoNeuRaL storage audit','',f'Measured: `{payload["measured_at"]}`','']
    md += ['## Mutation owners','']
    if procs:
        md += ['| PID | State | Command |','|---:|:---:|---|']
        for p in procs: md.append(f'| {p["pid"]} | {p["state"]} | `{p["cmd"][:180]}` |')
    else: md.append('None detected.')
    md += ['','## Filesystems','', '| Target | Used | Size | Percent |','|---|---:|---:|---:|']
    for k in ('root','home','yocto'):
        x=fs[k]; md.append(f'| {k} | {human(x.get("used_bytes",0))} | {human(x.get("size_bytes",0))} | {x.get("percent","?")} |')
    md += ['','## Gates','']
    for k,v in gates.items(): md.append(f'- `{k}={v}`')
    md += ['','## Largest `/yocto` entries','', '| Entry | Bytes |','|---|---:|']
    for x in yo[:20]: md.append(f'| `{x["name"]}` | {human(x["bytes"])} |')
    md += ['','## Largest SyMoNeuRaL entries','', '| Entry | Bytes |','|---|---:|']
    for x in sy[:20]: md.append(f'| `{x["name"]}` | {human(x["bytes"])} |')
    if derr: md += ['','## Drive error','',f'`{derr}`']
    else: md += ['','## Drive root','',f'- entries: **{len(drive)}**',f'- loose files: **{gates["drive_root_loose_files"]}**',f'- problem buckets present: **{gates["drive_problem_buckets_present"]}**']
    (out/'REPORT.md').write_text('\n'.join(md)+'\n'); os.chmod(out/'REPORT.md',0o600)

    print(f'AUDIT_DIR={out}')
    print(f'MUTATION_PROCESSES={len(procs)}')
    print(f'DRIVE_ROOT_ENTRIES={len(drive)}')
    print(f'DRIVE_ROOT_LOOSE_FILES={gates["drive_root_loose_files"]}')
    print(f'DRIVE_PROBLEM_BUCKETS={",".join(gates["drive_problem_buckets_present"])}')
    print(f'YOCTO_PERCENT={fs["yocto"].get("percent","?")}')
    return 0

if __name__=='__main__':
    raise SystemExit(main())

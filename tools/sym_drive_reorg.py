#!/usr/bin/env python3
"""Collision-aware, server-side organizer for known Google Drive root collections.

Default is PLAN ONLY. `apply` refuses to run while another storage mutation owner is active.
For an absent destination it uses one server-side `rclone moveto` for speed.
For an existing destination it inventories both trees and merges per file:
  unique -> server-side moveto
  exact duplicate (same size+MD5) -> delete source duplicate
  same path, different/unknown content -> preserve under __from_<source>/
All actions are recorded in a TSV ledger.
"""
from __future__ import annotations
import argparse, csv, json, os, re, subprocess, time
from pathlib import Path

ROOT=Path('/home/google/Symoneural')
STATE_DIR=ROOT/'.private'/'storage-reorg'
LEDGER=STATE_DIR/'drive-helper-migration.tsv'
REMOTE='gdrive:'
MAPPINGS=[
 ('Projects_Active','Projects/Active','projects'),
 ('Projects_Crypto','Projects/Crypto','projects'),
 ('Projects_Database','Projects/Database','projects'),
 ('Projects_ForHost','Projects/Host','projects'),
 ('Projects_Github','Projects/GitHub-Mirrors','projects'),
 ('Projects_helperscripts','Projects/Utilities/Helper-Scripts','projects'),
 ('Projects_Streamer','Projects/Streaming','projects'),
 ('Projects_WebandML','Projects/Web-ML','projects'),
 ('SymoneuralSeptBuilds','Symoneural/History/Build-History/Sept-Builds','symoneural'),
 ('symon-backups','Symoneural/Restore-Recovery/Historical/symon-backups','symoneural'),
 ('SyOsML_Documentation','Symoneural/Documentation/SyOsML','symoneural'),
 ('SyMoNeuRaL_Runtime_Engineering_Guide','Symoneural/Documentation/Runtime-Engineering-Guide','symoneural'),
 ('ClaudeAlienware','Symoneural/History/Agent-Sessions/ClaudeAlienware','symoneural'),
 ('AppleSDK','Development-Reference/Apple/SDKs/AppleSDK-drive','development'),
 ('Apple Machine Learning Research_files','Development-Reference/Apple/ML-Research','development'),
 ('Cross-Platform Development','Development-Reference/Cross-Platform','development'),
 ('Source Code and SDK Matrix','Development-Reference/SDKs/Source-and-SDK-Matrix','development'),
 ('Hardware Profiles','Development-Reference/Hardware','development'),
 ('System Optimization Reference','Development-Reference/Linux-System/Optimization','development'),
 ('System Security','Development-Reference/Security','development'),
 ('Backstage Templates','Development-Reference/SDKs/Backstage-Templates','development'),
 ('VMScripts','Virtualization/Scripts','virtualization'),
 ('Blockchain Proofs of Concept','Projects/Crypto/Research/Blockchain-Proofs-of-Concept','crypto'),
 ('Yocto Firmware','Build-Outputs/Yocto/Firmware','yocto'),
 ('HR MEETING','Personal/HR/HR-Meeting','personal'),
 ('Logistics','Personal/Logistics','personal'),
 ('resumes','Personal/Employment/Resumes','personal'),
 ('Documents','Personal/Documents/Drive-Documents','personal'),
 ('Imagesandvideos','Media/Imported-Albums','media'),
 ('MITModel','Models/Historical/MITModel','models'),
 ('yocto','Build-Outputs/Yocto/Historical/yocto-root','yocto'),
 ('Markdown Dialect Tool','Projects/Utilities/Markdown-Dialect-Tool','projects'),
 ('Spotify API Documentation','Development-Reference/AI-Research/Spotify-API','development'),
 ('spotify-integration','Projects/Archived/Spotify-Integration','projects'),
 ('hiranktesting','Projects/Experimental/hiranktesting','projects'),
 ('Saved from the Google app','Personal/Documents/Saved-From-Google-App','personal'),
]
MUTATOR_MARKERS=('storage_reorg.py run','storage_reorg.py resume','cleanup-pipeline','offload-to-drive','upstream-to-drive','rclone copy','rclone move','rclone moveto')

def sh(args,timeout=21600): return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
def remote(p): return REMOTE+p.strip('/')
def proc_mutators():
    me=os.getpid(); out=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==me: continue
        try: c=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode('utf-8','replace').strip()
        except Exception: continue
        if c and any(m in c for m in MUTATOR_MARKERS): out.append((int(p.name),c))
    return sorted(out)
def stat_path(p):
    r=sh(['rclone','lsjson',remote(p),'--stat','--hash'],900)
    if r.returncode!=0: return None
    try: return json.loads(r.stdout)
    except Exception: return None
def size_path(p):
    r=sh(['rclone','size',remote(p),'--json'],3600)
    if r.returncode!=0: return None
    try: return json.loads(r.stdout)
    except Exception: return None
def inventory(p):
    r=sh(['rclone','lsjson',remote(p),'--recursive','--files-only','--hash'],7200)
    if r.returncode!=0: raise RuntimeError(r.stderr.strip() or f'inventory failed: {p}')
    arr=json.loads(r.stdout); d={}
    for x in arr:
        rel=x.get('Path') or x.get('Name'); h=x.get('Hashes') or {}
        d[rel]={'size':int(x.get('Size') or 0),'md5':h.get('md5') or h.get('MD5') or '','id':x.get('ID') or ''}
    return d
def log(action,src,dest,size=0,md5='',note=''):
    STATE_DIR.mkdir(parents=True,exist_ok=True); os.chmod(STATE_DIR,0o700)
    new=not LEDGER.exists()
    with LEDGER.open('a',newline='',encoding='utf-8') as fh:
        w=csv.writer(fh,delimiter='\t',lineterminator='\n')
        if new: w.writerow(['WHEN','ACTION','SOURCE','DESTINATION','SIZE_BYTES','MD5','NOTE'])
        w.writerow([time.strftime('%Y-%m-%dT%H:%M:%S%z'),action,src,dest,size,md5,note])
    os.chmod(LEDGER,0o600)
def slug(s): return re.sub(r'[^A-Za-z0-9._-]+','_',s).strip('_') or 'source'

def merge(src,dest):
    si=inventory(src); di=inventory(dest)
    unique=dups=conf=0
    conflict_root=f'{dest}/__from_{slug(src)}'
    for rel,meta in si.items():
        dm=di.get(rel)
        sp=f'{src}/{rel}'
        if dm is None:
            dp=f'{dest}/{rel}'
            r=sh(['rclone','moveto',remote(sp),remote(dp)],3600)
            if r.returncode: raise RuntimeError(f'moveto failed {sp}: {r.stderr.strip()}')
            log('MOVE_UNIQUE',sp,dp,meta['size'],meta['md5']); unique+=1
        elif meta['md5'] and dm['md5'] and meta['size']==dm['size'] and meta['md5']==dm['md5']:
            r=sh(['rclone','deletefile',remote(sp)],900)
            if r.returncode: raise RuntimeError(f'delete duplicate failed {sp}: {r.stderr.strip()}')
            log('DELETE_DUPLICATE',sp,f'{dest}/{rel}',meta['size'],meta['md5'],'destination survivor verified same size+MD5'); dups+=1
        else:
            suffix=(meta['md5'][:12] if meta['md5'] else str(meta['size']))
            dp=f'{conflict_root}/{rel}.__source_{suffix}'
            r=sh(['rclone','moveto',remote(sp),remote(dp)],3600)
            if r.returncode: raise RuntimeError(f'conflict preserve failed {sp}: {r.stderr.strip()}')
            log('PRESERVE_CONFLICT',sp,dp,meta['size'],meta['md5'],'same relative path, content differs or MD5 unavailable'); conf+=1
    sh(['rclone','rmdirs',remote(src)],1800)
    # Source root itself may still remain empty.
    sh(['rclone','rmdir',remote(src)],900)
    return unique,dups,conf

def do_one(src,dest,apply=False):
    ss=stat_path(src)
    if ss is None: return 'ABSENT'
    ds=stat_path(dest)
    if not apply: return 'PLAN_FAST_MOVE' if ds is None else 'PLAN_COLLISION_AWARE_MERGE'
    before=size_path(src)
    if ds is None:
        r=sh(['rclone','moveto',remote(src),remote(dest)],21600)
        if r.returncode: raise RuntimeError(r.stderr.strip() or f'moveto failed {src}')
        after=size_path(dest)
        if before and after and (before.get('count')!=after.get('count') or before.get('bytes')!=after.get('bytes')):
            raise RuntimeError(f'aggregate verify failed {src} -> {dest}: {before} != {after}')
        if stat_path(src) is not None: raise RuntimeError(f'source still exists after move: {src}')
        log('MOVE_TREE',src,dest,before.get('bytes',0) if before else 0,'','destination absent; server-side tree move')
        return 'MOVED_TREE'
    u,d,c=merge(src,dest)
    log('MERGE_COMPLETE',src,dest,0,'',f'unique={u} duplicates={d} conflicts={c}')
    return f'MERGED unique={u} dup={d} conflict={c}'

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('cmd',choices=['plan','apply','verify','inventory']); ap.add_argument('--remote',default='gdrive:')
    a=ap.parse_args(); global REMOTE; REMOTE=a.remote.rstrip(':')+':'
    if a.cmd=='inventory':
        x=sh(['rclone','lsjson',REMOTE,'--hash'],1800)
        if x.returncode: print(x.stderr,file=os.sys.stderr); return 1
        print(x.stdout,end=''); return 0
    if a.cmd=='apply':
        muts=proc_mutators()
        if muts:
            print('REFUSING APPLY: another storage mutation owner is active:')
            for p,c in muts: print(f'  PID {p}: {c[:180]}')
            print('Stop/wait for that owner first. Do not create a second mutation owner.')
            return 2
    rc=0
    for src,dest,cat in MAPPINGS:
        try:
            if a.cmd=='verify':
                s=stat_path(src); d=stat_path(dest)
                result='PASS' if s is None and d is not None else ('SOURCE_PRESENT' if s is not None else 'DEST_MISSING')
            else: result=do_one(src,dest,a.cmd=='apply')
            print(f'{result}\t{src}\t{dest}\t{cat}')
            if a.cmd=='verify' and result!='PASS': rc=1
        except Exception as e:
            print(f'ERROR\t{src}\t{dest}\t{e}') ; rc=1
    return rc
if __name__=='__main__': raise SystemExit(main())

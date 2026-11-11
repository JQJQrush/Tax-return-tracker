"""Validate and restore app backups into a NEW directory; never overwrite live data."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile

MAX_TOTAL=2*1024**3
MAX_FILE=128*1024**2
ALLOWED=re.compile(r'(?:taxprep\.sqlite3|backup-manifest\.json|documents/[1-9]\d*/(?:original\.pdf|page-[1-9]\d*\.png|words-[1-9]\d*\.json))\Z')


def inspect_database(directory):
    path=directory/'taxprep.sqlite3'
    if not path.is_file():raise ValueError('未找到备份数据库；请选择“备份全部工作资料”产生的 ZIP，而非程序安装包')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('数据库完整性检查未通过')
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'clients','documents','pages','records','audit'}<=tables:raise ValueError('数据库不是受支持的资料备份')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('数据库关联记录不完整')
        for did,digest in db.execute('SELECT id,hash FROM documents'):
            original=directory/'documents'/str(did)/'original.pdf'
            if not original.is_file():raise ValueError(f'文件 #{did} 缺少原始 PDF')
            if not re.fullmatch(r'[0-9a-f]{64}',digest or ''):raise ValueError(f'文件 #{did} 缺少有效指纹')
            hashed=hashlib.sha256()
            with original.open('rb') as f:
                if f.read(4)!=b'%PDF':raise ValueError(f'文件 #{did} 不是有效 PDF 文件头')
                f.seek(0)
                for chunk in iter(lambda:f.read(1024*1024),b''):hashed.update(chunk)
            if hashed.hexdigest()!=digest:raise ValueError(f'文件 #{did} 的原件与备份指纹不一致')
        for did,number in db.execute('SELECT document_id,page_number FROM pages'):
            image=directory/'documents'/str(did)/f'page-{number}.png'
            if not image.is_file():raise ValueError(f'文件 #{did} 第 {number} 页缺少预览')
            with image.open('rb') as f:
                if f.read(8)!=b'\x89PNG\r\n\x1a\n':raise ValueError('页面预览文件头损坏')
        result={name:db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ['clients','documents','pages','records','audit']}
        result['feedback']=db.execute('SELECT COUNT(*) FROM feedback').fetchone()[0] if 'feedback' in tables else 0
        result['intake']=db.execute('SELECT COUNT(*) FROM intake').fetchone()[0] if 'intake' in tables else 0
        return result
    finally:db.close()


def unpack_checked(archive_path, directory):
    with zipfile.ZipFile(archive_path) as z:
        items=z.infolist()
        if len(items)>20000 or sum(i.file_size for i in items)>MAX_TOTAL:raise ValueError('备份超过当前恢复上限（2GB / 20000 个文件）')
        seen=set();total=0
        for item in items:
            name=item.filename
            if item.is_dir():
                if '..' in PurePosixPath(name).parts or '\\' in name or name.startswith('/'):raise ValueError('备份包含不安全路径')
                continue
            if name in seen or not ALLOWED.fullmatch(name) or stat.S_ISLNK(item.external_attr>>16):raise ValueError('备份包含重复、不支持或不安全的文件路径')
            if item.flag_bits&1:raise ValueError('暂不支持加密 ZIP；请选择程序直接生成的备份')
            if item.file_size>MAX_FILE:raise ValueError('备份中的单个文件超过 128MB')
            seen.add(name);out=directory/PurePosixPath(name);out.parent.mkdir(parents=True,exist_ok=True)
            size=0
            with z.open(item) as source,out.open('wb') as target:
                while True:
                    block=source.read(1024*1024)
                    if not block:break
                    size+=len(block);total+=len(block)
                    if size>MAX_FILE or total>MAX_TOTAL:raise ValueError('解压后的备份超过恢复上限')
                    target.write(block)
        manifest=directory/'backup-manifest.json'
        if manifest.is_file():
            content=json.loads(manifest.read_text(encoding='utf-8'))
            if content.get('format')!='taxprep-local-backup' or content.get('format_version')!=1:raise ValueError('备份格式版本暂不支持')
    return inspect_database(directory)


def restore(archive_path,destination=None,check_only=False):
    archive_path=Path(archive_path).resolve()
    if not check_only:
        if destination is None:raise ValueError('请指定一个新的恢复目录')
        raw=Path(destination).absolute()
        if raw.is_symlink():raise ValueError('恢复目录不能是符号链接')
        destination=raw.resolve()
        if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):raise ValueError('恢复目录必须不存在或为空；程序不会覆盖现有资料')
        destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='taxprep-restore-',dir=destination.parent if not check_only else None) as temp:
        staged=Path(temp)/'data';staged.mkdir()
        try:report=unpack_checked(archive_path,staged)
        except (zipfile.BadZipFile,sqlite3.DatabaseError,json.JSONDecodeError) as exc:raise ValueError('备份文件损坏或格式不正确') from exc
        if check_only:return {'validated':True,**report}
        # New directory publication is atomic; a validation failure leaves old data untouched.
        if destination.exists():destination.rmdir()
        staged.rename(destination)
    return {'validated':True,'destination':str(destination),**report}


def write_launcher(destination):
    def escaped(path):return str(path).replace('%','%%')
    script='@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\n'
    script+=f'set "TAXPREP_DATA_DIR={escaped(destination)}"\r\n"{escaped(Path(__file__).resolve().parents[2]/"scripts"/"windows"/"run_windows.bat")}"\r\n'
    (destination/'start_restored.bat').write_bytes(script.encode('utf-8'))


def interactive():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    try:
        archive=filedialog.askopenfilename(title='选择资料备份 ZIP（不是程序安装包）',filetypes=[('ZIP backup','*.zip')])
        if not archive:return
        parent=filedialog.askdirectory(title='选择恢复位置；会在此创建新目录，不覆盖旧资料')
        if not parent:return
        destination=Path(parent)/('TaxPrep-Restored-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
        report=restore(archive,destination);write_launcher(destination)
        messagebox.showinfo('恢复完成',f"已验证并恢复 {report['clients']} 位客户、{report['documents']} 份文件。\n\n目录：{destination}\n\n先关闭旧程序，再双击新目录中的 start_restored.bat。旧资料未被覆盖。")
    except Exception as exc:messagebox.showerror('未恢复',str(exc))
    finally:root.destroy()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='验证或恢复资料备份，不覆盖原数据')
    parser.add_argument('--backup',type=Path);parser.add_argument('--destination',type=Path)
    parser.add_argument('--check-only',action='store_true');parser.add_argument('--interactive',action='store_true')
    args=parser.parse_args()
    if args.interactive:
        try:interactive()
        except Exception as exc:raise SystemExit('无法打开图形恢复窗口；可用 --backup ZIP --destination 新目录 的命令行方式恢复。'+str(exc))
    elif not args.backup:parser.error('请提供 --backup，或使用 --interactive')
    else:
        try:print(json.dumps(restore(args.backup,args.destination,args.check_only),ensure_ascii=False,indent=2))
        except (ValueError,OSError) as exc:raise SystemExit(str(exc))

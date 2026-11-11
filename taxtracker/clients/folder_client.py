"""Read taxpayer names locally; folder names are never treated as evidence."""
import re
import subprocess
import tempfile
import time
from pathlib import Path
import pymupdf

SUPPORTED={'.pdf','.jpg','.jpeg','.png','.tif','.tiff'}


def clean_name(raw):
    value=re.split(r'\s{2,}|\d{3}[- ]\d{2}[- ]\d{4}',raw.strip())[0].strip(' :：,;')
    value=re.sub(r'\s+',' ',value)
    if re.fullmatch(r'[\u3400-\u9fff]{2,8}',value):return value
    if not re.fullmatch(r"[A-Za-zÀ-ž][A-Za-zÀ-ž .,'’-]{2,99}",value):return None
    tokens=value.split()
    if len(tokens)>=4 and len(tokens)%2==0 and [x.casefold() for x in tokens[:len(tokens)//2]]==[x.casefold() for x in tokens[len(tokens)//2:]]:
        tokens=tokens[:len(tokens)//2];value=' '.join(tokens)
    if not 2<=len(tokens)<=6:return None
    if set(re.findall(r'[a-z]+',value.lower())) & {'name','taxpayer','spouse','employee','employer','address','social','security','number','signature','information','inc','llc','instructions','last','first'}:return None
    return value


def names_from_text(text):
    lines=text.splitlines();found=[]
    for i,line in enumerate(lines):
        chinese=re.search(r'(?:纳税人姓名|客户姓名|姓名)\s*[:：]\s*([\u3400-\u9fff]{2,8})',line)
        if chinese:found.append(chinese.group(1));continue
        # Explicit person labels only; never employer/payer or an arbitrary name-like line.
        label=re.search(r"(?:taxpayer|employee|recipient).{0,8}\bname\b",line,re.I)
        if not label or len(line)>190:continue
        inline=line[label.end():].lstrip(' :：')
        if ':' in line[label.start():label.end()+2]:
            name=clean_name(inline)
            if name:found.append(name)
        for candidate in lines[i+1:i+3]:
            if not candidate.strip():continue
            name=clean_name(candidate)
            if name:found.append(name)
            break
    return list(dict.fromkeys(found))


def folder_info(raw,read_name=False,engine=None):
    path=Path(str(raw).strip().strip('"'))
    if not path.is_absolute():raise ValueError('请填写完整文件夹路径，例如 D:\\客户资料 或 \\\\服务器\\共享目录')
    try:
        if not path.is_dir():raise ValueError('文件夹不存在或服务器账号无权访问，请检查路径')
        files=[]
        for p in path.iterdir():
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUPPORTED:
                files.append(p)
                if read_name and len(files)>40:raise ValueError('文件夹资料超过40份，请直接填写客户姓名，或使用较小的年度资料文件夹')
                if len(files)>200:raise ValueError('文件夹资料超过200份，请使用较小的年度资料文件夹')
    except OSError:raise ValueError('无法读取文件夹，请检查共享连接和访问权限')
    evidence=[];unreadable=[];deadline=time.monotonic()+35
    if read_name:
        if not files:raise ValueError('文件夹内没有可读取的PDF或图片，请填写客户姓名')
        for p in sorted(files,key=lambda p:(p.suffix.lower()!='.pdf',p.name.lower())):
            if time.monotonic()>deadline:raise ValueError('读取姓名超时，请手动填写姓名后重试')
            try:
                if p.stat().st_size>50*1024*1024:unreadable.append(p.name);continue
                with pymupdf.open(p) as doc:
                    if doc.needs_pass:unreadable.append(p.name);continue
                    for index in range(min(2,len(doc))):
                        page=doc[index];names=names_from_text(page.get_text(sort=True));method='pdf_text'
                        if not names and engine and (p.suffix.lower()!='.pdf' or page.get_images()):
                            remaining=deadline-time.monotonic()
                            if remaining<2:raise ValueError('读取姓名超时，请手动填写姓名后重试')
                            with tempfile.TemporaryDirectory(prefix='taxprep-name-') as tmp:
                                image=Path(tmp)/'page.png'
                                page.get_pixmap(matrix=pymupdf.Matrix(2.5,2.5)).save(image)
                                result=subprocess.run([engine,str(image),'stdout','-l','eng','--psm','3'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=min(15,remaining))
                                if result.returncode==0:names=names_from_text(result.stdout);method='tesseract'
                        for name in names:evidence.append({'name':name,'filename':p.name,'page':index+1,'method':method})
            except (OSError,RuntimeError,subprocess.TimeoutExpired):unreadable.append(p.name)
        choices={re.sub(r'\s+',' ',e['name']).casefold():e['name'] for e in evidence}
        if len(choices)>1:raise ValueError('资料中发现多个姓名：'+'、'.join(choices.values())+'。请确认客户姓名后填写，程序不会自动合并。')
        if not choices:raise ValueError('未能从资料中可靠识别纳税人姓名，请填写姓名后重试；扫描件需本机OCR')
        if unreadable:raise ValueError('有文件无法读取，不能确认是否存在不同客户，请填写姓名后重试')
        name=next(iter(choices.values()))
    else:name=None
    return {'path':str(path),'name':name,'evidence':evidence,'files':[{'name':p.name,'path':str(p)} for p in files]}

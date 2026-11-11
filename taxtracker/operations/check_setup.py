"""Local installation report without client files, credentials or usernames."""
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def report():
    lines=['TaxPrep Local v0.4 安装诊断','操作系统：'+platform.system()+' '+platform.release(),
           'Python：'+platform.python_version(),'Python 版本符合要求：'+str(sys.version_info>=(3,10)),
           '图形恢复模块 tkinter：'+('已安装' if importlib.util.find_spec('tkinter') else '未安装，可使用命令行恢复')]
    if importlib.util.find_spec('pymupdf'):
        import pymupdf
        lines.append('PyMuPDF：'+pymupdf.VersionBind)
    else:lines.append('PyMuPDF：未安装，请先运行 run_windows.bat')
    engine=os.environ.get('TESSERACT_CMD') or shutil.which('tesseract')
    fallback=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Tesseract-OCR'/'tesseract.exe'
    if not engine and fallback.is_file():engine=str(fallback)
    if engine:
        try:
            version=subprocess.run([engine,'--version'],capture_output=True,text=True,timeout=10)
            langs=subprocess.run([engine,'--list-langs'],capture_output=True,text=True,timeout=10)
            installed=set(langs.stdout.splitlines()[1:])
            lines+=['OCR：'+(version.stdout.splitlines() or ['检测失败'])[0],
                    '英文 eng 数据：'+str('eng' in installed),'方向 osd 数据：'+str('osd' in installed)]
        except (OSError,subprocess.TimeoutExpired):lines.append('OCR：检测失败，请检查安装和路径设置')
    else:lines.append('OCR：未找到；扫描件自动识别需要 Tesseract，数字 PDF 和手工核对仍可用')
    lines.append('此报告不读取客户文件，不包含 API Key 或完整用户路径。')
    return '\n'.join(lines)


if __name__=='__main__':print(report())

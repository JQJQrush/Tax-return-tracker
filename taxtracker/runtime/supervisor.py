"""Persistent supervisor launched by Windows Task Scheduler."""
import argparse,datetime,json,os,subprocess,sys,time
from pathlib import Path
from taxtracker.operations import instance


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,required=True);args=parser.parse_args()
    data=args.data_dir.resolve();data.mkdir(parents=True,exist_ok=True)
    logs=data/'logs';logs.mkdir(exist_ok=True)
    lock=(data/'supervisor.lock').open('a+b')
    if lock.tell()==0:lock.write(b'0');lock.flush()
    lock.seek(0)
    import msvcrt
    try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:lock.close();return
    root=Path(__file__).resolve().parents[2]
    def event(kind,**extra):
        row={'time':datetime.datetime.now(datetime.timezone.utc).isoformat(),'event':kind,'supervisor_pid':os.getpid(),**extra}
        with (logs/'supervisor.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')
    event('supervisor_started')
    try:
        while True:
            if instance.active_url(data):
                time.sleep(5);continue
            today=datetime.datetime.now().strftime('%Y-%m-%d')
            with (logs/('server-'+today+'.log')).open('ab',buffering=0) as output:
                env=dict(os.environ,PYTHONUNBUFFERED='1',PYTHONIOENCODING='utf-8')
                process=subprocess.Popen([str(Path(sys.executable).with_name('python.exe')),'-u','-m','taxtracker.runtime.server','--data-dir',str(data),'--port','8765'],cwd=root,stdout=output,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
                event('server_started',server_pid=process.pid)
                code=process.wait()
                event('server_exited',server_pid=process.pid,exit_code=code)
            time.sleep(5)
    except BaseException as e:
        event('supervisor_exited',error=repr(e));raise
    finally:lock.close()

if __name__=='__main__':main()

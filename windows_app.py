"""Windows desktop/browser launcher. PyInstaller entry point; no console required."""
import os,sys,time,json,threading,urllib.request,webbrowser,multiprocessing,logging,argparse,subprocess
from pathlib import Path

def use_project_python():
    """File associations may launch the source with an unrelated system Python."""
    if getattr(sys,'frozen',False):return False
    root=Path(__file__).resolve().parent
    environment=root/'.venv'
    if Path(sys.prefix).resolve()==environment.resolve():return False
    python=environment/'Scripts'/'pythonw.exe'
    if not python.is_file():python=environment/'Scripts'/'python.exe'
    if not python.is_file():return False
    subprocess.Popen([str(python),str(root/'windows_app.py'),*sys.argv[1:]],cwd=root)
    return True

def main():
    if use_project_python():return
    parser=argparse.ArgumentParser();parser.add_argument('--browser',action='store_true');parser.add_argument('--desktop',action='store_true');parser.add_argument('--self-test',action='store_true');parser.add_argument('--webview-test',action='store_true');parser.add_argument('--data');parser.add_argument('--port',type=int)
    args=parser.parse_args()
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    default_data=(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'GT7 Race Engineer' if getattr(sys,'frozen',False) else root/'data')
    data=Path(args.data or default_data);data.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=data/'desktop.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    # Windowed Python has no console streams, but libraries may still write to them.
    if sys.stdout is None:sys.stdout=open(data/'runtime.log','a',encoding='utf-8')
    if sys.stderr is None:sys.stderr=sys.stdout
    import tkinter as tk
    from tkinter import messagebox
    choice='browser' if args.browser else 'desktop'
    if not any((args.browser,args.desktop,args.self_test,args.webview_test)):
        launcher=tk.Tk();launcher.title('GT7 Race Engineer / Windows Beta');launcher.geometry('470x310');launcher.configure(bg='#111114');selection=[]
        tk.Label(launcher,text='GT7 RACE ENGINEER',fg='#ff354b',bg='#111114',font=('Segoe UI',22,'bold')).pack(pady=(28,10))
        tk.Label(launcher,text='WINDOWS BETA  /  OFFLINE TELEMETRY',fg='#aaaab3',bg='#111114').pack(pady=5)
        def choose(mode):selection.append(mode);launcher.destroy()
        tk.Button(launcher,text='Open desktop app',command=lambda:choose('desktop'),bg='#ed1b35',fg='white',width=30,pady=10).pack(pady=10)
        tk.Button(launcher,text='Open in my browser',command=lambda:choose('browser'),bg='#303038',fg='white',width=30,pady=8).pack()
        launcher.mainloop()
        if not selection:return
        choice=selection[0]
    server=None;thread=None
    try:
        from backend.app.config import Config
        cfg=Config(data);values=cfg.settings.model_dump()
        if not cfg.path.exists():values.update(input_device=None,output_device=None,ui_hz=10)
        model=root/'models/vosk-model-small-en-us-0.15'
        if not model.exists():model=root/'data/models/vosk-model-small-en-us-0.15'
        if not values.get('vosk_model') or not Path(values['vosk_model']).is_dir():values['vosk_model']=str(model)
        if args.port:values['http_port']=args.port
        port=values['http_port'];url=f'http://127.0.0.1:{port}/'
        values.update(http_host='127.0.0.1',allowed_origins=[url.rstrip('/'),f'http://localhost:{port}']);cfg.save(values)
        def healthy():
            try:
                with urllib.request.urlopen(url+'api/health',timeout=.4) as r:return json.load(r).get('service')=='GT7 Race Engineer'
            except Exception:return False
        existing=healthy()
        if not existing:
            import uvicorn
            from backend.app.api import create_app
            server=uvicorn.Server(uvicorn.Config(create_app(data),host='127.0.0.1',port=port,workers=1,access_log=False,log_config=None))
            thread=threading.Thread(target=server.run,daemon=True);thread.start()
            deadline=time.monotonic()+30
            while not healthy():
                if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError(f'Backend could not start. See {data / "desktop.log"}')
                time.sleep(.15)
        if args.self_test:
            from vosk import Model,KaldiRecognizer,SetLogLevel
            from backend.app.cars import CATALOG
            import sounddevice
            SetLogLevel(-1);recognizer=KaldiRecognizer(Model(str(model)),16000);recognizer.AcceptWaveform(bytes(32000));recognizer.FinalResult()
            result={'backend':healthy(),'frontend':urllib.request.urlopen(url).status==200,'model_loaded':True,'cars':len(CATALOG),'audio_devices':len(sounddevice.query_devices()),'frozen':bool(getattr(sys,'frozen',False))}
            (data/'self-test.json').write_text(json.dumps(result,indent=2));return
        if choice=='desktop':
            try:
                import webview
                webview.settings['ALLOW_DOWNLOADS']=True
                window=webview.create_window('GT7 Race Engineer / Windows Beta',url,width=1280,height=820,min_size=(760,560),background_color='#09090b')
                if args.webview_test:
                    def check():
                        deadline=time.monotonic()+20;heading=None
                        while time.monotonic()<deadline:
                            try:heading=window.evaluate_js('document.querySelector("h1")?.textContent')
                            except Exception:pass
                            if heading=='Live Race':break
                            time.sleep(.3)
                        (data/'webview-test.json').write_text(json.dumps({'heading':heading,'native_renderer':'edgechromium','ok':heading=='Live Race'}));window.destroy()
                    webview.start(check,gui='edgechromium',private_mode=True)
                else:webview.start(gui='edgechromium',private_mode=True)
            except Exception:
                logging.exception('Desktop renderer failed')
                if args.webview_test:raise
                popup=tk.Tk();popup.withdraw()
                fallback=messagebox.askyesno('Desktop runtime unavailable','Install Microsoft Edge WebView2 Runtime for desktop mode. Open the browser version now?');popup.destroy()
                if fallback:choice='browser'
        if choice=='browser' and not args.webview_test:
            webbrowser.open(url)
            controller=tk.Tk();controller.title('GT7 Race Engineer / Running');controller.geometry('440x210');controller.configure(bg='#111114')
            tk.Label(controller,text='TELEMETRY IS RUNNING',fg='#ff354b',bg='#111114',font=('Segoe UI',17,'bold')).pack(pady=20)
            tk.Label(controller,text='Keep this window open while driving.' if not existing else 'Connected to the existing GT7 receiver.',fg='white',bg='#111114').pack()
            tk.Button(controller,text='Open dashboard',command=lambda:webbrowser.open(url)).pack(pady=10)
            tk.Button(controller,text='Close launcher' if existing else 'Stop and exit',command=controller.destroy).pack();controller.mainloop()
    except Exception as error:
        logging.exception('Application failed')
        if args.self_test or args.webview_test:(data/'test-error.txt').write_text(str(error));raise
        popup=tk.Tk();popup.withdraw();messagebox.showerror('GT7 Race Engineer',f'{error}\n\nLogs: {data}');popup.destroy()
    finally:
        if server:server.should_exit=True
        if thread:thread.join(timeout=15)

if __name__=='__main__':
    multiprocessing.freeze_support()
    main()

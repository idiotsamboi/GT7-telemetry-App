#!/usr/bin/env python3
"""Linux desktop entry point; owns its local backend and uses system WebKit."""
import os,sys,subprocess,time,urllib.request,fcntl,signal
from pathlib import Path

def main():
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('WebKit2','4.1')
    from gi.repository import Gtk,WebKit2,GLib
    root=Path(__file__).resolve().parent
    data=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'gt7-race-engineer'
    data.mkdir(parents=True,exist_ok=True)
    lock=(data/'desktop.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        dialog=Gtk.MessageDialog(text='GT7 Race Engineer is already running.',buttons=Gtk.ButtonsType.OK);dialog.run();dialog.destroy();return
    from backend.app.config import Config
    cfg=Config(data);settings=cfg.settings.model_dump()
    if not cfg.path.exists():settings.update(ui_hz=6,input_device=None,output_device=None)
    model=root/'models/vosk-model-small-en-us-0.15'
    if not settings.get('vosk_model') and model.is_dir():settings['vosk_model']=str(model)
    settings['http_host']='127.0.0.1'
    port=settings['http_port'];settings['allowed_origins']=[f'http://127.0.0.1:{port}',f'http://localhost:{port}'];cfg.save(settings)
    # Do not attach to an unrelated service already listening on this port.
    import socket
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',port))
        except OSError:
            dialog=Gtk.MessageDialog(text=f'Port {port} is already in use. Close the other GT7 instance or change its port.',buttons=Gtk.ButtonsType.OK);dialog.run();dialog.destroy();return
    log=(data/'desktop.log').open('w')
    child=subprocess.Popen([sys.executable,str(root/'run.py'),'--data',str(data)],cwd=root,stdout=log,stderr=log)
    window=Gtk.Window(title='GT7 Race Engineer');window.set_default_size(1120,720)
    view=WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral());window.add(view)
    view.get_settings().set_enable_developer_extras(False)
    url=f'http://127.0.0.1:{port}/'
    def navigation(web,decision,kind):
        if kind==WebKit2.PolicyDecisionType.NAVIGATION_ACTION and not decision.get_request().get_uri().startswith(url):
            decision.ignore();return True
        return False
    view.connect('decide-policy',navigation)
    def download_started(context,download):
        def destination(item,suggested):
            chooser=Gtk.FileChooserDialog(title='Save telemetry export',transient_for=window,action=Gtk.FileChooserAction.SAVE)
            chooser.add_buttons('Cancel',Gtk.ResponseType.CANCEL,'Save',Gtk.ResponseType.ACCEPT)
            chooser.set_current_name(Path(suggested).name);chooser.set_do_overwrite_confirmation(True)
            if chooser.run()==Gtk.ResponseType.ACCEPT:
                item.set_allow_overwrite(True);item.set_destination(Path(chooser.get_filename()).as_uri())
            else:item.cancel()
            chooser.destroy();return True
        download.connect('decide-destination',destination)
    view.get_context().connect('download-started',download_started)
    deadline=time.monotonic()+30
    def ready():
        if child.poll() is not None or time.monotonic()>deadline:
            dialog=Gtk.MessageDialog(transient_for=window,text=f'Backend could not start. See {data / "desktop.log"}',buttons=Gtk.ButtonsType.OK);dialog.run();dialog.destroy();window.destroy();return False
        try:
            with urllib.request.urlopen(url+'api/health',timeout=.15) as response:
                if response.status==200:view.load_uri(url);return False
        except OSError:pass
        return True
    window.connect('destroy',lambda *_:Gtk.main_quit());window.show_all();GLib.timeout_add(250,ready)
    try:Gtk.main()
    finally:
        child.send_signal(signal.SIGINT) if child.poll() is None else None
        try:child.wait(timeout=12)
        except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=5)
        log.close();lock.close()

if __name__=='__main__':main()

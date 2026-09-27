"""Create a portable x64 Windows beta with app and browser launch options."""
from pathlib import Path
import subprocess,sys,shutil,hashlib
import tkinter, _tkinter  # Fail early if the build runtime lacks the native launcher.
root=Path(__file__).resolve().parents[1]
for generated in (root/'release/windows-1.3.0',root/'data/windows-build'):
    if not generated.resolve().is_relative_to(root):raise SystemExit('Build output escaped the project directory')
cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--windowed','--onedir','--name','GT7 Race Engineer','--distpath',str(root/'release/windows-1.3.0'),'--workpath',str(root/'data/windows-build'),'--specpath',str(root/'data/windows-build'),'--paths',str(root),'--collect-all','vosk','--collect-all','webview','--collect-all','sounddevice','--collect-submodules','uvicorn','--collect-submodules','backend','--hidden-import','numpy','--hidden-import','tkinter','--hidden-import','_tkinter','--exclude-module','pytest','--exclude-module','PyQt5','--exclude-module','PyQt6','--exclude-module','PySide6']
for src,dest in [('frontend/dist','frontend/dist'),('backend/migrations','backend/migrations'),('backend/app/data','backend/app/data'),('data/models/vosk-model-small-en-us-0.15','models/vosk-model-small-en-us-0.15'),('data/models/vosk-download.json','models'),('docs/licenses','docs/licenses'),('docs/car-assets-provenance.json','docs'),('vendor/gt7-udp/LICENSE','vendor/gt7-udp'),('THIRD_PARTY_NOTICES.md','.')]:cmd+=['--add-data',str(root/src)+';'+dest]
cmd.append(str(root/'windows_app.py'));subprocess.run(cmd,cwd=root,check=True)
folder=root/'release/windows-1.3.0/GT7 Race Engineer'
for required in ('_tkinter.pyd','_tcl_data/init.tcl','_tk_data/tk.tcl'):
    if not (folder/'_internal'/required).is_file():raise SystemExit('Incomplete native launcher payload: '+required)
shutil.copy(root/'release/WINDOWS-BETA.md',folder/'READ ME.md')
# Clickable shortcuts require no shell window or command typing.
for name,arg in [('Open desktop app','--desktop'),('Open in browser','--browser')]:
    (folder/(name+'.vbs')).write_text('Set shell = CreateObject("WScript.Shell")\nSet fs = CreateObject("Scripting.FileSystemObject")\napp = fs.BuildPath(fs.GetParentFolderName(WScript.ScriptFullName), "GT7 Race Engineer.exe")\nshell.Run Chr(34) & app & Chr(34) & " '+arg+'", 1, False\n')
archive=Path(shutil.make_archive(str(root/'release/GT7-Race-Engineer-1.3.0-beta-windows-x64'),'zip',root/'release/windows-1.3.0','GT7 Race Engineer'))
archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
print(archive)

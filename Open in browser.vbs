Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
python = fs.BuildPath(root, ".venv\Scripts\pythonw.exe")
app = fs.BuildPath(root, "windows_app.py")
If Not fs.FileExists(python) Then
  MsgBox "The project Python environment is missing. Use the complete Windows release package.", 16, "GT7 Race Engineer"
  WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & app & Chr(34) & " --browser --data " & Chr(34) & fs.BuildPath(root, "data") & Chr(34), 0, False

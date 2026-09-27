Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
app = fs.BuildPath(fs.GetParentFolderName(WScript.ScriptFullName), "GT7 Race Engineer.exe")
shell.Run Chr(34) & app & Chr(34) & " --browser", 1, False

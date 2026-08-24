Option Explicit

Dim shell, files, root, pythonExe, appPath
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

root = files.GetParentFolderName(WScript.ScriptFullName)
pythonExe = files.BuildPath(root, ".venv\Scripts\python.exe")
appPath = files.BuildPath(root, "app.py")

If Not files.FileExists(pythonExe) Then
    MsgBox "The Python environment was not found:" & vbCrLf & pythonExe & vbCrLf & vbCrLf & _
           "Create .venv and install requirements before launching.", _
           vbCritical, "Crypto Strategy Lab"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Run """" & pythonExe & """ """ & appPath & """", 0, False

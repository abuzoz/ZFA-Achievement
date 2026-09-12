' Silent launcher: runs the app through the trusted installed Python (pythonw),
' so Windows Smart App Control allows it. No console window appears.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
On Error Resume Next
sh.Run "pythonw """ & dir & "\main.py""", 0, False
If Err.Number <> 0 Then
    sh.Run "pyw """ & dir & "\main.py""", 0, False
End If

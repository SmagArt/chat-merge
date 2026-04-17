' Merge Chat launcher v2.0
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
logPath = scriptDir & "\launch_log.txt"

Sub Log(msg)
    On Error Resume Next
    Dim lf : Set lf = fso.OpenTextFile(logPath, 8, True)
    lf.WriteLine Now() & "  " & msg
    lf.Close
End Sub

Function S(p)
    S = p
    On Error Resume Next
    If fso.FileExists(p) Then S = fso.GetFile(p).ShortPath
    If fso.FolderExists(p) Then S = fso.GetFolder(p).ShortPath
    On Error GoTo 0
End Function

Function RunQ(full)
    Log "RUN: " & full
    RunQ = WshShell.Run(full, 0, True)
    Log "EXIT=" & RunQ
End Function

Log "=== START ==="
Log "dir=" & scriptDir

' --- Find Python (bundled first, then system) ---
Dim py : py = ""
Dim bundled : bundled = scriptDir & "\python\python.exe"
If fso.FileExists(bundled) Then py = bundled : Log "bundled: " & py

If py = "" Then
    Dim u : u = WshShell.ExpandEnvironmentStrings("%USERPROFILE%")
    Dim t(5)
    t(0)=u&"\AppData\Local\Programs\Python\Python313\python.exe"
    t(1)=u&"\AppData\Local\Programs\Python\Python312\python.exe"
    t(2)=u&"\AppData\Local\Programs\Python\Python311\python.exe"
    t(3)=u&"\AppData\Local\Programs\Python\Python310\python.exe"
    t(4)="C:\Program Files\Python313\python.exe"
    t(5)="C:\Program Files\Python312\python.exe"
    Dim j : For j=0 To 3
        If fso.FileExists(t(j)) And py="" Then py=t(j) : Log "system: "&py
    Next
End If

If py = "" Then
    MsgBox "Python not found. Please reinstall the application.", 16, "Merge Chat"
    WScript.Quit 1
End If

Dim pyS : pyS = S(py)
Log "python=" & pyS

' --- Install packages if missing (check once, then skip via flag) ---
Dim pkgsFlag : pkgsFlag = scriptDir & "\pkgs_ok.flag"
If Not fso.FileExists(pkgsFlag) Then
    Dim chk : chk = RunQ(pyS & " -c ""import customtkinter""")
    Log "packages=" & chk
    If chk <> 0 Then
        Dim bat : bat = scriptDir & "\setup_base.bat"
        If Not fso.FileExists(bat) Then
            MsgBox "setup_base.bat not found!", 16, "Merge Chat"
            WScript.Quit 1
        End If
        RunQ "powershell -NoProfile -WindowStyle Hidden -Command ""Start-Process cmd -ArgumentList '/c """ & S(bat) & """' -Wait -WindowStyle Hidden"""
        chk = RunQ(pyS & " -c ""import customtkinter""")
        If chk <> 0 Then
            MsgBox "Installation failed. See install_log.txt", 16, "Merge Chat"
            WScript.Quit 1
        End If
    End If
    Dim pf : Set pf = fso.CreateTextFile(pkgsFlag, True)
    pf.WriteLine Now()
    pf.Close
    Log "pkgs_ok flag written"
Else
    Log "pkgs_ok flag found, skipping package check"
End If

' --- Launch GUI ---
Dim gui : gui = scriptDir & "\merge_chat_gui.py"
If Not fso.FileExists(gui) Then
    MsgBox "File not found: merge_chat_gui.py", 16, "Merge Chat"
    WScript.Quit 1
End If

' pythonw.exe for GUI = no console window at all
Dim pyW : pyW = Replace(py, "python.exe", "pythonw.exe")
If Not fso.FileExists(pyW) Then pyW = py
Log "Launch: " & S(pyW) & " " & S(gui)
WshShell.Run S(pyW) & " " & S(gui), 0, False
Log "Started OK"

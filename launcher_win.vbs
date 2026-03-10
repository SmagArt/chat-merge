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
    Dim t(3)
    t(0)=u&"\AppData\Local\Programs\Python\Python313\python.exe"
    t(1)=u&"\AppData\Local\Programs\Python\Python312\python.exe"
    t(2)=u&"\AppData\Local\Programs\Python\Python311\python.exe"
    t(3)=u&"\AppData\Local\Programs\Python\Python310\python.exe"
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
        Dim bat : bat = scriptDir & "\setup_python.bat"
        If Not fso.FileExists(bat) Then
            MsgBox "setup_python.bat not found!", 16, "Merge Chat"
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

' --- CUDA check: only once, skip if flag exists ---
Dim flagFile : flagFile = scriptDir & "\cuda_ok.flag"
If Not fso.FileExists(flagFile) Then
    Log "First run: CUDA check..."
    ' Write a bat that does pip install and exits
    Dim cudaBat : cudaBat = scriptDir & "\install_cuda.bat"
    Dim tf : Set tf = fso.CreateTextFile(cudaBat, True)
    tf.WriteLine "@echo off"
    tf.WriteLine "set LOG=" & scriptDir & "\install_log.txt"
    tf.WriteLine "echo %DATE% %TIME% CUDA check >> ""%LOG%"""
    tf.WriteLine pyS & " -c ""import torch; exit(0 if torch.cuda.is_available() else 1)"" >nul 2>&1"
    tf.WriteLine "if %ERRORLEVEL%==0 goto :done"
    tf.WriteLine "wmic path win32_VideoController get name 2>nul | findstr /i nvidia >nul 2>&1"
    tf.WriteLine "if %ERRORLEVEL% NEQ 0 goto :done"
    tf.WriteLine "echo %DATE% %TIME% Installing torch cu124... >> ""%LOG%"""
    tf.WriteLine pyS & " -m pip install torch --index-url https://download.pytorch.org/whl/cu124 --force-reinstall -q >> ""%LOG%"" 2>&1"
    tf.WriteLine "echo %DATE% %TIME% Done, exit=%ERRORLEVEL% >> ""%LOG%"""
    tf.WriteLine ":done"
    tf.Close

    RunQ "powershell -NoProfile -WindowStyle Hidden -Command ""Start-Process cmd -ArgumentList '/c """ & S(cudaBat) & """' -Wait -WindowStyle Hidden"""
    fso.DeleteFile cudaBat

    ' Write flag so we never check again (whether success or not)
    Dim ff : Set ff = fso.CreateTextFile(flagFile, True)
    ff.WriteLine Now()
    ff.Close
    Log "cuda check done, flag written"
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

; DroneDream WebView2 health gate.
;
; Tauri 2.11.4's built-in WebView2 section treats any non-empty `pv`
; registry value as installed. This hook runs immediately afterwards and also
; requires the registered runtime's core executable to exist. A stale `pv`
; therefore cannot produce an installed application that fails on first run.
;
; The embedded bootstrapper is downloaded by Tauri's bundler from Microsoft's
; official Evergreen distribution endpoint. Microsoft only documents
; `/silent /install`; this is a best-effort reinstall/update, never a forced
; uninstall and never deletes shared WebView2 files or registry keys.

!include "${__FILEDIR__}\runtime-mode.nsh"

!macro NSIS_HOOK_PREINSTALL
  Push $0
  Push $1

  ; Protocol 2 installers hold a durable native quiesce across running-process
  ; checks, old-version uninstall, executable replacement and receipt clearing.
  ; Protocol 1 is retained only as a compatibility gate for the status commands
  ; that version actually implemented.
  IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_no_existing_operation
    ReadRegDWORD $1 SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol"
    ${If} $1 >= 2
      Call DroneDreamRevalidateRuntimeQuiesce
      Pop $0
      ${If} $0 != "ok"
        StrCpy $1 $0
        Call DroneDreamBestEffortEndRuntimeQuiesce
        ${If} $1 == "pending"
          Abort "DroneDreamRuntime setup is waiting to continue / Runtime 安装正在等待续传。Open DroneDream to continue or cancel it before updating or reinstalling / 请先打开 DroneDream 完成或取消安装，再升级或重装。"
        ${ElseIf} $1 == "busy"
          Abort "DroneDreamRuntime is busy or another installer owns maintenance / Runtime 正忙，或另一个安装器正在维护它。"
        ${Else}
          Abort "Unable to validate the durable DroneDreamRuntime update isolation; refusing to replace the application / 无法验证 Runtime 升级隔离，已停止覆盖安装。"
        ${EndIf}
      ${EndIf}
    ${ElseIf} $1 == 1
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --runtime-operation-status' $0
      ${If} $0 == 75
        Abort "DroneDreamRuntime is busy / DroneDreamRuntime 正在运行安装或维护。Cancel or wait for it in DroneDream, then retry / 请先在软件中取消或等待完成后重试。"
      ${ElseIf} $0 != 0
        Abort "Unable to verify DroneDreamRuntime operation state; refusing to replace the application / 无法验证 Runtime 状态，已停止覆盖安装。"
      ${EndIf}
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
      ${If} $0 == 76
        Abort "DroneDreamRuntime setup is waiting to continue / Runtime 安装正在等待续传。Open DroneDream to continue or cancel it before updating or reinstalling / 请先打开 DroneDream 完成或取消安装，再升级或重装。"
      ${ElseIf} $0 != 0
        Abort "Unable to verify the pending DroneDreamRuntime setup request; refusing to replace the application / 无法验证待处理的 Runtime 安装请求，已停止覆盖安装。"
      ${EndIf}
    ${EndIf}
  dronedream_no_existing_operation:

  Call DroneDreamWebView2IsUsable
  Pop $0
  ${If} $0 != "1"
    DetailPrint "WebView2 registration is incomplete; starting the official Microsoft repair/install attempt."
    InitPluginsDir
    Delete "$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe"
    ; This macro is expanded after Tauri defines WEBVIEW2BOOTSTRAPPERPATH.
    File "/oname=$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"
    ExecWait '"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install' $1
    ${If} $1 != 0
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Abort "Microsoft WebView2 could not be installed / Microsoft WebView2 安装失败 (exit code $1). Restart Windows, ensure 2 GB is free on C:, and retry / 请重启 Windows、确保 C 盘至少有 2 GB 空间后重试。"
    ${EndIf}

    ; EdgeUpdate may finish registration shortly after the bootstrapper exits.
    Sleep 2000
    Call DroneDreamWebView2IsUsable
    Pop $0
    ${If} $0 != "1"
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Abort "Microsoft WebView2 is still unusable / Microsoft WebView2 仍不可用. Restart Windows and retry DroneDream; if needed run this installer as administrator / 请重启后重试，必要时以管理员身份运行安装器。"
    ${EndIf}
  ${EndIf}

  Pop $1
  Pop $0
!macroend

!macro NSIS_HOOK_POSTINSTALL
  Push $0

  ; Clear every previous receipt first. Passive, silent, update, reinstall and
  ; desktop-only installs stop here and can never trigger a runtime download.
  ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --clear-installer-handoff' $0
  ${If} $0 != 0
    Call DroneDreamBestEffortEndRuntimeQuiesce
    Abort "Unable to clear the previous DroneDreamRuntime setup request / 无法清除旧的 Runtime 安装请求。"
  ${EndIf}

  ${If} $DroneDreamWasInstalled == "0"
  ${AndIf} $DroneDreamInstallMode != "install-app-only"
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --seal-installer-handoff "$DroneDreamInstallMode" "$DroneDreamRuntimeDrive"' $0
    ${If} $0 != 0
      ; The old receipt is already gone, so failure is safe and cannot be
      ; converted into an automatic install by launching the app.
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Abort "Unable to save the verified DroneDreamRuntime setup request / 无法保存已验证的 Runtime 安装请求。"
    ${EndIf}
  ${EndIf}

  WriteRegDWORD SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol" 2

  ; Clear/seal ran under quiesce. Release it with the newly installed binary
  ; before .onInstSuccess is allowed to auto-launch the application.
  Call DroneDreamEndRuntimeQuiesce
  Pop $0
  ${If} $0 != "ok"
    Abort "Unable to release DroneDreamRuntime update isolation; setup stopped before launching / 无法解除 Runtime 升级隔离，安装已在启动软件前停止。"
  ${EndIf}

  Pop $0
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  Push $0
  Push $1
  IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_uninstall_no_binary
    ReadRegDWORD $1 SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol"
    ${If} $1 >= 2
      Call un.DroneDreamPrepareRuntimeQuiesce
      Pop $0
      ${If} $0 == "pending"
        Abort "DroneDreamRuntime setup is waiting to continue. Open DroneDream to continue or cancel it before uninstalling / Runtime 安装正在等待续传，请先打开 DroneDream 完成或取消安装。"
      ${ElseIf} $0 == "busy"
        Abort "DroneDreamRuntime is busy or another installer owns maintenance; uninstall stopped / Runtime 正忙，或另一个安装器正在维护它，卸载已停止。"
      ${ElseIf} $0 != "ok"
        Abort "Unable to establish safe Runtime uninstall isolation; uninstall stopped / 无法建立安全的 Runtime 卸载隔离，卸载已停止。"
      ${EndIf}
    ${ElseIf} $1 == 1
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --runtime-operation-status' $0
      ${If} $0 == 75
        Abort "DroneDreamRuntime is busy. Cancel or wait for the operation before uninstalling the desktop app / Runtime 正在工作，请先取消或等待完成。"
      ${ElseIf} $0 != 0
        Abort "Unable to verify DroneDreamRuntime operation state; uninstall stopped safely / 无法验证 Runtime 状态，已安全停止卸载。"
      ${EndIf}
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
      ${If} $0 == 76
        Abort "DroneDreamRuntime setup is waiting to continue. Open DroneDream to continue or cancel it before uninstalling / Runtime 安装正在等待续传，请先打开 DroneDream 完成或取消安装。"
      ${ElseIf} $0 != 0
        Abort "Unable to verify the pending DroneDreamRuntime setup request; uninstall stopped safely / 无法验证待处理的 Runtime 请求，已安全停止卸载。"
      ${EndIf}
    ${EndIf}
    ${If} $1 >= 1
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --clear-installer-handoff' $0
      ${If} $0 != 0
        ${If} $1 >= 2
          Call un.DroneDreamBestEffortEndRuntimeQuiesce
        ${EndIf}
        Abort "Unable to clear the pending Runtime request; uninstall stopped safely / 无法清除待处理请求，已安全停止卸载。"
      ${EndIf}
    ${EndIf}
  dronedream_uninstall_no_binary:
  ; On successful protocol-2 uninstall the marker intentionally remains until
  ; this uninstaller (or the live parent updater) exits. No new runtime
  ; operation can begin between the running-process check and binary deletion.
  ; Runtime/cache/other WSL distributions are intentionally untouched.
  Pop $1
  Pop $0
!macroend

Function DroneDreamWebView2IsUsable
  Push $0
  Push $1
  Push $2

  StrCpy $0 "0"

  ; The Evergreen client is registered in the 32-bit EdgeUpdate view even for
  ; a 64-bit runtime. Check both spellings because this template also supports
  ; a future 32-bit build.
  ${If} ${RunningX64}
    ReadRegStr $1 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    ReadRegStr $2 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "location"
  ${Else}
    ReadRegStr $1 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
    ReadRegStr $2 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "location"
  ${EndIf}
  ${If} $1 != ""
  ${AndIf} $1 != "0.0.0.0"
    IfFileExists "$2\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$2\$1\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$2\Application\$1\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$PROGRAMFILES32\Microsoft\EdgeWebView\Application\$1\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$PROGRAMFILES64\Microsoft\EdgeWebView\Application\$1\msedgewebview2.exe" dronedream_webview2_ready 0
  ${EndIf}

  ReadRegStr $1 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "pv"
  ReadRegStr $2 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" "location"
  ${If} $1 != ""
  ${AndIf} $1 != "0.0.0.0"
    IfFileExists "$2\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$2\$1\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$2\Application\$1\msedgewebview2.exe" dronedream_webview2_ready 0
    IfFileExists "$LOCALAPPDATA\Microsoft\EdgeWebView\Application\$1\msedgewebview2.exe" dronedream_webview2_ready 0
  ${EndIf}
  Goto dronedream_webview2_done

  dronedream_webview2_ready:
    StrCpy $0 "1"
  dronedream_webview2_done:
    Pop $2
    Pop $1
    Exch $0
FunctionEnd

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

!macro NSIS_HOOK_PREINSTALL
  Push $0
  Push $1

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
      Abort "Microsoft WebView2 could not be installed / Microsoft WebView2 安装失败 (exit code $1). Restart Windows, ensure 2 GB is free on C:, and retry / 请重启 Windows、确保 C 盘至少有 2 GB 空间后重试。"
    ${EndIf}

    ; EdgeUpdate may finish registration shortly after the bootstrapper exits.
    Sleep 2000
    Call DroneDreamWebView2IsUsable
    Pop $0
    ${If} $0 != "1"
      Abort "Microsoft WebView2 is still unusable / Microsoft WebView2 仍不可用. Restart Windows and retry DroneDream; if needed run this installer as administrator / 请重启后重试，必要时以管理员身份运行安装器。"
    ${EndIf}
  ${EndIf}

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

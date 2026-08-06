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
!define DRONEDREAM_EDITION_IDENTITY_FILE "${__FILEDIR__}\edition-identity.nsh"
!macro DRONEDREAM_EDITION_IDENTITY_TABLE
  !include "${DRONEDREAM_EDITION_IDENTITY_FILE}"
!macroend

; Recreate only shortcuts that already belong to this installation. Pointing
; at a dedicated icon resource gives Windows a new cache identity when an
; existing 1.0.0 installation replaces the retired legacy cloud artwork.
; Missing shortcuts stay missing, including when the user chose /NS.
!macro DRONEDREAM_REFRESH_BRANDED_SHORTCUT SHORTCUT_PATH
  !insertmacro IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  ${If} $0 != 1
    !insertmacro IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\$OldMainBinaryName"
    Pop $0
  ${EndIf}
  ${If} $0 = 1
    Delete "${SHORTCUT_PATH}"
    CreateShortcut "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\icons\DroneDream.ico" 0
    !insertmacro SetLnkAppUserModelId "${SHORTCUT_PATH}"
  ${EndIf}
!macroend

; Early edition candidates used PRODUCTNAME as the shortcut filename. Migrate
; that link only when it belongs to this exact installation and the canonical
; display-name path is free. Cross-edition and legacy collisions are preserved.
!macro DRONEDREAM_MIGRATE_INTERNAL_SHORTCUT DISPLAY_PATH INTERNAL_PATH LABEL_PREFIX
  !if "${DRONEDREAM_SHORTCUTNAME}" != "${PRODUCTNAME}"
    IfFileExists "${INTERNAL_PATH}" 0 ${LABEL_PREFIX}_done
    !insertmacro IsShortcutTarget "${INTERNAL_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 != 1
      !insertmacro IsShortcutTarget "${INTERNAL_PATH}" "$INSTDIR\$OldMainBinaryName"
      Pop $0
    ${EndIf}
    ${If} $0 = 1
      IfFileExists "${DISPLAY_PATH}" ${LABEL_PREFIX}_display_exists 0
      Rename "${INTERNAL_PATH}" "${DISPLAY_PATH}"
      Goto ${LABEL_PREFIX}_done
      ${LABEL_PREFIX}_display_exists:
        !insertmacro IsShortcutTarget "${DISPLAY_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"
        Pop $0
        ${If} $0 = 1
          Delete "${INTERNAL_PATH}"
        ${Else}
          DetailPrint "$(DD_ShortcutConflict)"
        ${EndIf}
    ${EndIf}
    ${LABEL_PREFIX}_done:
  !endif
!macroend

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
          Abort "$(DD_UpdatePending)"
        ${ElseIf} $1 == "busy"
          Abort "$(DD_UpdateBusy)"
        ${Else}
          Abort "$(DD_UpdateIsolationInvalid)"
        ${EndIf}
      ${EndIf}
    ${ElseIf} $1 == 1
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --runtime-operation-status' $0
      ${If} $0 == 75
        Abort "$(DD_LegacyRuntimeBusy)"
      ${ElseIf} $0 != 0
        Abort "$(DD_RuntimeStateUnknown)"
      ${EndIf}
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
      ${If} $0 == 76
        Abort "$(DD_UpdatePending)"
      ${ElseIf} $0 != 0
        Abort "$(DD_RuntimeRequestUnknown)"
      ${EndIf}
    ${EndIf}
  dronedream_no_existing_operation:

  Call DroneDreamWebView2IsUsable
  Pop $0
  ${If} $0 != "1"
    DetailPrint "$(DD_WebViewRepair)"
    InitPluginsDir
    Delete "$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe"
    ; This macro is expanded after Tauri defines WEBVIEW2BOOTSTRAPPERPATH.
    File "/oname=$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"
    ExecWait '"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install' $1
    ${If} $1 != 0
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Abort "$(DD_WebViewInstallFailed)"
    ${EndIf}

    ; EdgeUpdate may finish registration shortly after the bootstrapper exits.
    Sleep 2000
    Call DroneDreamWebView2IsUsable
    Pop $0
    ${If} $0 != "1"
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Abort "$(DD_WebViewStillUnusable)"
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
    Abort "$(DD_ClearRequestFailed)"
  ${EndIf}

  ; Keep the user's verified Runtime choice across repair installs and updates.
  ; The native sealing command revalidates the target before any automatic
  ; operation can start, so a stale or edited registry value still fails closed.
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeInstallMode" "$DroneDreamInstallMode"
  WriteRegStr SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeDrive" "$DroneDreamRuntimeDrive"

  ${If} $DroneDreamInstallMode != "install-app-only"
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --seal-installer-handoff "$DroneDreamInstallMode" "$DroneDreamRuntimeDrive"' $0
    ${If} $0 != 0
      ; The old receipt is already gone, so failure is safe and cannot be
      ; converted into an automatic install by launching the app.
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Abort "$(DD_SaveRequestFailed)"
    ${EndIf}
  ${EndIf}

  WriteRegDWORD SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol" 2

  ; Clear/seal ran under quiesce. Release it with the newly installed binary
  ; before .onInstSuccess is allowed to auto-launch the application.
  Call DroneDreamEndRuntimeQuiesce
  Pop $0
  ${If} $0 != "ok"
    Abort "$(DD_ReleaseIsolationFailed)"
  ${EndIf}

  ; The standard Tauri shortcut functions intentionally skip existing links
  ; during update mode. Refresh those links after the new executable and icon
  ; resource are in place so desktop and Start Menu both adopt the wing mark.
  !insertmacro DRONEDREAM_MIGRATE_INTERNAL_SHORTCUT "$SMPROGRAMS\$AppStartMenuFolder\${DRONEDREAM_SHORTCUTNAME}.lnk" "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk" dronedream_migrate_startmenu_folder
  !insertmacro DRONEDREAM_MIGRATE_INTERNAL_SHORTCUT "$SMPROGRAMS\${DRONEDREAM_SHORTCUTNAME}.lnk" "$SMPROGRAMS\${PRODUCTNAME}.lnk" dronedream_migrate_startmenu_root
  !insertmacro DRONEDREAM_MIGRATE_INTERNAL_SHORTCUT "$DESKTOP\${DRONEDREAM_SHORTCUTNAME}.lnk" "$DESKTOP\${PRODUCTNAME}.lnk" dronedream_migrate_desktop
  !insertmacro DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$SMPROGRAMS\$AppStartMenuFolder\${PRODUCTNAME}.lnk"
  !insertmacro DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$SMPROGRAMS\${PRODUCTNAME}.lnk"
  !insertmacro DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$DESKTOP\${PRODUCTNAME}.lnk"
  !insertmacro DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$SMPROGRAMS\$AppStartMenuFolder\${DRONEDREAM_SHORTCUTNAME}.lnk"
  !insertmacro DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$SMPROGRAMS\${DRONEDREAM_SHORTCUTNAME}.lnk"
  !insertmacro DRONEDREAM_REFRESH_BRANDED_SHORTCUT "$DESKTOP\${DRONEDREAM_SHORTCUTNAME}.lnk"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, i 0, i 0)'

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
        Abort "$(DD_UninstallPending)"
      ${ElseIf} $0 == "busy"
        Abort "$(DD_UninstallBusy)"
      ${ElseIf} $0 != "ok"
        Abort "$(DD_UninstallIsolationFailed)"
      ${EndIf}
    ${ElseIf} $1 == 1
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --runtime-operation-status' $0
      ${If} $0 == 75
        Abort "$(DD_UninstallLegacyBusy)"
      ${ElseIf} $0 != 0
        Abort "$(DD_UninstallStateUnknown)"
      ${EndIf}
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
      ${If} $0 == 76
        Abort "$(DD_UninstallPending)"
      ${ElseIf} $0 != 0
        Abort "$(DD_UninstallRequestUnknown)"
      ${EndIf}
    ${EndIf}
    ${If} $1 >= 1
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --clear-installer-handoff' $0
      ${If} $0 != 0
        ${If} $1 >= 2
          Call un.DroneDreamBestEffortEndRuntimeQuiesce
        ${EndIf}
        Abort "$(DD_UninstallClearFailed)"
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

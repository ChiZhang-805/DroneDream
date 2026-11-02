!define DRONEDREAM_INSTALLED_PROCESS_SCRIPT "${__FILEDIR__}\installed-app-process.ps1"

!macro DRONEDREAM_CHECK_INSTALLED_APP EXECUTABLE DISPLAYNAME
  !define DD_PROCESS_CHECK_ID ${__LINE__}
  InitPluginsDir
  File /oname=$PLUGINSDIR\dronedream-installed-process.ps1 "${DRONEDREAM_INSTALLED_PROCESS_SCRIPT}"
  nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\dronedream-installed-process.ps1" -ExecutablePath "$INSTDIR\${EXECUTABLE}" -Action Check'
  Pop $R0
  Pop $R1
  ${If} $R0 == 10
    nsis_tauri_utils::StrReplace "$(appRunningOkKill)" "{{product_name}}" "${DISPLAYNAME}"
    Pop $R2
    IfSilent dd_stop_${DD_PROCESS_CHECK_ID} 0
    ${IfThen} $PassiveMode != 1 ${|} MessageBox MB_OKCANCEL $R2 IDOK dd_stop_${DD_PROCESS_CHECK_ID} IDCANCEL dd_cancel_${DD_PROCESS_CHECK_ID} ${|}
    dd_stop_${DD_PROCESS_CHECK_ID}:
      nsExec::ExecToStack '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$PLUGINSDIR\dronedream-installed-process.ps1" -ExecutablePath "$INSTDIR\${EXECUTABLE}" -Action Stop'
      Pop $R0
      Pop $R1
  ${EndIf}
  ${If} $R0 != 0
    nsis_tauri_utils::StrReplace "$(failedToKillApp)" "{{product_name}}" "${DISPLAYNAME}"
    Pop $R2
    SetErrorLevel 75
    Abort $R2
  ${EndIf}
  Goto dd_process_done_${DD_PROCESS_CHECK_ID}
  dd_cancel_${DD_PROCESS_CHECK_ID}:
    Abort
  dd_process_done_${DD_PROCESS_CHECK_ID}:
  !undef DD_PROCESS_CHECK_ID
!macroend

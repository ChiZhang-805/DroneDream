; DroneDream runtime-mode page, expanded by anchors in the pinned Tauri template.
; These three variables are declared at include time because the vendored
; reinstall function appends them to the old uninstaller command before the
; custom Runtime page macro is expanded later in the template.
Var DroneDreamQuiesceToken
Var DroneDreamQuiesceOwnerPid
Var DroneDreamQuiesceActive

!macro DRONEDREAM_ONINIT
  StrCpy $DroneDreamWasInstalled "0"
  StrCpy $DroneDreamInstallMode "install-app-only"
  StrCpy $DroneDreamRuntimeDrive ""
  StrCpy $DroneDreamModePageVisited "0"
  StrCpy $DroneDreamAutoLaunched "0"
  StrCpy $DroneDreamRuntimeProtocol "0"
  StrCpy $DroneDreamQuiesceToken ""
  StrCpy $DroneDreamQuiesceOwnerPid ""
  StrCpy $DroneDreamQuiesceActive "0"
  ReadRegStr $0 SHCTX "${UNINSTKEY}" "UninstallString"
  ${If} $0 != ""
    StrCpy $DroneDreamWasInstalled "1"
  ${EndIf}
  ReadRegDWORD $DroneDreamRuntimeProtocol SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol"
  ${If} $DroneDreamRuntimeProtocol >= 2
    IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_oninit_no_quiesce
      Call DroneDreamAcquireRuntimeQuiesce
      Pop $0
      ${If} $0 == "busy"
        MessageBox MB_ICONEXCLAMATION|MB_OK "DroneDreamRuntime 正在运行，或另一个安装器正在维护它。请等待或取消该任务后重试。 / DroneDreamRuntime is busy or another installer owns maintenance. Wait or cancel it, then retry."
        Abort
      ${ElseIf} $0 == "pending"
        MessageBox MB_ICONEXCLAMATION|MB_OK "DroneDreamRuntime 安装正在等待续传。请先打开 DroneDream 完成或取消，再升级或重装。 / Runtime setup is waiting to continue. Open DroneDream to finish or cancel it before updating."
        Abort
      ${ElseIf} $0 != "ok"
        MessageBox MB_ICONEXCLAMATION|MB_OK "无法建立安全的 Runtime 升级隔离，安装已停止。 / Unable to establish safe Runtime update isolation; setup stopped."
        Abort
      ${EndIf}
    dronedream_oninit_no_quiesce:
  ${EndIf}
!macroend

!macro DRONEDREAM_RUNTIME_MODE_PAGE
  !searchreplace DRONEDREAM_PLANNER_LOADER_SOURCE "${MAINBINARYSRCPATH}" "${MAINBINARYNAME}.exe" "WebView2Loader.dll"
  Var DroneDreamWasInstalled
  Var DroneDreamInstallMode
  Var DroneDreamRuntimeDrive
  Var DroneDreamPlannerExe
  Var DroneDreamPlanFile
  Var DroneDreamPlanTarget
  Var DroneDreamPlanCanInstall
  Var DroneDreamFullRadio
  Var DroneDreamCustomRadio
  Var DroneDreamAppOnlyRadio
  Var DroneDreamCustomDriveEdit
  Var DroneDreamModePageVisited
  Var DroneDreamAutoLaunched
  Var DroneDreamRuntimeProtocol

  Page custom DroneDreamRuntimeModePageCreate DroneDreamRuntimeModePageLeave

  Function DroneDreamBestEffortEndRuntimeQuiesce
    ${If} $DroneDreamQuiesceActive != "1"
      Return
    ${EndIf}
    IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_best_effort_end_done
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --end-runtime-quiesce "$DroneDreamQuiesceToken"' $0
      ${If} $0 == 0
        StrCpy $DroneDreamQuiesceActive "0"
      ${EndIf}
    dronedream_best_effort_end_done:
  FunctionEnd

  Function DroneDreamAcquireRuntimeQuiesce
    System::Call 'ole32::CoCreateGuid(g .s)'
    Pop $DroneDreamQuiesceToken
    StrCpy $0 $DroneDreamQuiesceToken 1
    ${If} $0 == "{"
      StrCpy $DroneDreamQuiesceToken $DroneDreamQuiesceToken 36 1
    ${EndIf}
    System::Call 'kernel32::GetCurrentProcessId()i.r0'
    StrCpy $DroneDreamQuiesceOwnerPid $0
    ${If} $DroneDreamQuiesceToken == ""
    ${OrIf} $DroneDreamQuiesceOwnerPid == ""
      Push "error"
      Return
    ${EndIf}
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --recover-runtime-quiesce' $0
    ${If} $0 == 75
      Push "busy"
      Return
    ${ElseIf} $0 != 0
      Push "error"
      Return
    ${EndIf}
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --begin-runtime-quiesce "$DroneDreamQuiesceToken" "$DroneDreamQuiesceOwnerPid"' $0
    ${If} $0 == 75
      Push "busy"
      Return
    ${ElseIf} $0 != 0
      Push "error"
      Return
    ${EndIf}
    StrCpy $DroneDreamQuiesceActive "1"
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
    ${If} $0 == 76
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Push "pending"
      Return
    ${ElseIf} $0 != 0
      Call DroneDreamBestEffortEndRuntimeQuiesce
      Push "error"
      Return
    ${EndIf}
    Push "ok"
  FunctionEnd

  Function DroneDreamRevalidateRuntimeQuiesce
    ${If} $DroneDreamQuiesceActive != "1"
      Push "error"
      Return
    ${EndIf}
    IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_revalidate_without_binary
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --begin-runtime-quiesce "$DroneDreamQuiesceToken" "$DroneDreamQuiesceOwnerPid"' $0
      ${If} $0 == 75
        Push "busy"
        Return
      ${ElseIf} $0 != 0
        Push "error"
        Return
      ${EndIf}
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
      ${If} $0 == 76
        Call DroneDreamBestEffortEndRuntimeQuiesce
        Push "pending"
        Return
      ${ElseIf} $0 != 0
        Call DroneDreamBestEffortEndRuntimeQuiesce
        Push "error"
        Return
      ${EndIf}
    dronedream_revalidate_without_binary:
    Push "ok"
  FunctionEnd

  Function DroneDreamEndRuntimeQuiesce
    ${If} $DroneDreamQuiesceActive != "1"
      Push "ok"
      Return
    ${EndIf}
    IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_strict_end_error
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --end-runtime-quiesce "$DroneDreamQuiesceToken"' $0
      ${If} $0 == 0
        StrCpy $DroneDreamQuiesceActive "0"
        Push "ok"
        Return
      ${EndIf}
    dronedream_strict_end_error:
    Push "error"
  FunctionEnd

  Function .onGUIEnd
    Call DroneDreamBestEffortEndRuntimeQuiesce
  FunctionEnd

  Function un.DroneDreamBestEffortEndRuntimeQuiesce
    ${If} $DroneDreamQuiesceActive != "1"
      Return
    ${EndIf}
    IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_un_best_effort_end_done
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --end-runtime-quiesce "$DroneDreamQuiesceToken"' $0
      ${If} $0 == 0
        StrCpy $DroneDreamQuiesceActive "0"
      ${EndIf}
    dronedream_un_best_effort_end_done:
  FunctionEnd

  Function un.DroneDreamPrepareRuntimeQuiesce
    StrCpy $DroneDreamQuiesceActive "0"
    StrCpy $DroneDreamQuiesceToken ""
    StrCpy $DroneDreamQuiesceOwnerPid ""
    ClearErrors
    ${GetOptions} $CMDLINE "/DRONEDREAMQUIESCETOKEN=" $DroneDreamQuiesceToken
    ClearErrors
    ${GetOptions} $CMDLINE "/DRONEDREAMQUIESCEPID=" $DroneDreamQuiesceOwnerPid
    ${If} $DroneDreamQuiesceToken == ""
    ${AndIf} $DroneDreamQuiesceOwnerPid == ""
      System::Call 'ole32::CoCreateGuid(g .s)'
      Pop $DroneDreamQuiesceToken
      StrCpy $0 $DroneDreamQuiesceToken 1
      ${If} $0 == "{"
        StrCpy $DroneDreamQuiesceToken $DroneDreamQuiesceToken 36 1
      ${EndIf}
      System::Call 'kernel32::GetCurrentProcessId()i.r0'
      StrCpy $DroneDreamQuiesceOwnerPid $0
      ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --recover-runtime-quiesce' $0
      ${If} $0 == 75
        Push "busy"
        Return
      ${ElseIf} $0 != 0
        Push "error"
        Return
      ${EndIf}
    ${ElseIf} $DroneDreamQuiesceToken == ""
      Push "error"
      Return
    ${ElseIf} $DroneDreamQuiesceOwnerPid == ""
      Push "error"
      Return
    ${EndIf}
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --begin-runtime-quiesce "$DroneDreamQuiesceToken" "$DroneDreamQuiesceOwnerPid"' $0
    ${If} $0 == 75
      Push "busy"
      Return
    ${ElseIf} $0 != 0
      Push "error"
      Return
    ${EndIf}
    StrCpy $DroneDreamQuiesceActive "1"
    ExecWait '"$INSTDIR\${MAINBINARYNAME}.exe" --installer-handoff-status' $0
    ${If} $0 == 76
      Call un.DroneDreamBestEffortEndRuntimeQuiesce
      Push "pending"
      Return
    ${ElseIf} $0 != 0
      Call un.DroneDreamBestEffortEndRuntimeQuiesce
      Push "error"
      Return
    ${EndIf}
    Push "ok"
  FunctionEnd

  Function DroneDreamRunPlanner
    Exch $0
    Delete "$DroneDreamPlanFile"
    ${If} $0 == ""
      ExecWait '"$DroneDreamPlannerExe" --write-installer-plan "$DroneDreamPlanFile"' $1
    ${Else}
      ExecWait '"$DroneDreamPlannerExe" --write-installer-plan "$DroneDreamPlanFile" "$0"' $1
    ${EndIf}
    ${If} $1 != 0
      StrCpy $DroneDreamPlanCanInstall "0"
      StrCpy $DroneDreamPlanTarget ""
      Pop $0
      Push "0"
      Return
    ${EndIf}
    ReadINIStr $1 "$DroneDreamPlanFile" "plan" "schemaVersion"
    ReadINIStr $2 "$DroneDreamPlanFile" "plan" "targetDrive"
    ReadINIStr $DroneDreamPlanTarget "$DroneDreamPlanFile" "plan" "targetRoot"
    ReadINIStr $3 "$DroneDreamPlanFile" "plan" "downloadBytes"
    ReadINIStr $4 "$DroneDreamPlanFile" "plan" "installedBytes"
    ReadINIStr $5 "$DroneDreamPlanFile" "plan" "minimumFreeBytes"
    ReadINIStr $DroneDreamPlanCanInstall "$DroneDreamPlanFile" "plan" "canInstall"
    ReadINIStr $6 "$DroneDreamPlanFile" "plan" "blockerCode"
    StrCpy $7 "$2\DroneDream"
    ${If} $1 != "1"
    ${OrIf} $3 != "8589934592"
    ${OrIf} $4 != "25769803776"
    ${OrIf} $5 != "55834574848"
    ${OrIf} $DroneDreamPlanCanInstall != "1"
    ${OrIf} $2 == ""
    ${OrIf} $DroneDreamPlanTarget != $7
    ${OrIf} $6 != "none"
      StrCpy $DroneDreamPlanCanInstall "0"
    ${EndIf}
    Delete "$DroneDreamPlanFile"
    Pop $0
    Push $DroneDreamPlanCanInstall
  FunctionEnd

  Function DroneDreamRuntimeModePageCreate
    IfSilent 0 +2
      Abort
    ${If} $PassiveMode == 1
    ${OrIf} $UpdateMode == 1
    ${OrIf} $DroneDreamWasInstalled == 1
    ${OrIf} $WixMode == 1
      Abort
    ${EndIf}
    InitPluginsDir
    StrCpy $DroneDreamPlannerExe "$PLUGINSDIR\dronedream-installer-planner.exe"
    StrCpy $DroneDreamPlanFile "$PLUGINSDIR\dronedream-installer-plan-v1.ini"
    Delete "$DroneDreamPlannerExe"
    Delete "$DroneDreamPlanFile"
    SetOutPath "$PLUGINSDIR"
    File "/oname=dronedream-installer-planner.exe" "${MAINBINARYSRCPATH}"
    ; LLVM-MinGW fallback builds dynamically import this loader. MSVC builds
    ; do not have the sibling file, so /nonfatal is intentional.
    File /nonfatal "/oname=WebView2Loader.dll" "${DRONEDREAM_PLANNER_LOADER_SOURCE}"
    Push ""
    Call DroneDreamRunPlanner
    Pop $0
    !insertmacro MUI_HEADER_TEXT "DroneDreamRuntime" "选择安装方式 / Choose setup mode"
    nsDialogs::Create 1018
    Pop $1
    ${If} $1 == error
      Abort
    ${EndIf}
    ${NSD_CreateLabel} 0 0 100% 24u "PX4/Gazebo：下载约 6.1 GB（预留 8 GiB）、安装约 24 GiB，至少需要 52 GiB 可用空间。"
    Pop $1
    ${NSD_CreateRadioButton} 0 34u 100% 12u "安装全部（推荐） / Install all (recommended)"
    Pop $DroneDreamFullRadio
    ${NSD_CreateLabel} 18u 50u 95% 16u "推荐位置 / Recommended: $DroneDreamPlanTarget"
    Pop $1
    ${NSD_CreateRadioButton} 0 74u 100% 12u "自定义 Runtime 磁盘 / Custom runtime drive"
    Pop $DroneDreamCustomRadio
    ${NSD_CreateText} 18u 92u 80u 13u "$2"
    Pop $DroneDreamCustomDriveEdit
    ${NSD_CreateLabel} 104u 94u 75% 12u "输入盘符（如 E:）；目录固定为 X:\DroneDream"
    Pop $1
    ${NSD_CreateRadioButton} 0 120u 100% 12u "仅安装桌面程序 / Desktop application only"
    Pop $DroneDreamAppOnlyRadio
    ${NSD_CreateLabel} 18u 138u 95% 28u "软件首屏显示计划和取消按钮后才继续。可能需重启 Windows；现有 Ubuntu 不会被修改。"
    Pop $1
    ${If} $0 == "1"
      ${If} $DroneDreamModePageVisited == "0"
        ${NSD_Check} $DroneDreamFullRadio
        StrCpy $DroneDreamInstallMode "install-all"
        StrCpy $DroneDreamRuntimeDrive $2
      ${ElseIf} $DroneDreamInstallMode == "custom"
        ${NSD_Check} $DroneDreamCustomRadio
        ${NSD_SetText} $DroneDreamCustomDriveEdit $DroneDreamRuntimeDrive
      ${ElseIf} $DroneDreamInstallMode == "install-app-only"
        ${NSD_Check} $DroneDreamAppOnlyRadio
      ${Else}
        ${NSD_Check} $DroneDreamFullRadio
        StrCpy $DroneDreamRuntimeDrive $2
      ${EndIf}
    ${Else}
      EnableWindow $DroneDreamFullRadio 0
      EnableWindow $DroneDreamCustomRadio 0
      EnableWindow $DroneDreamCustomDriveEdit 0
      ${NSD_Check} $DroneDreamAppOnlyRadio
      StrCpy $DroneDreamInstallMode "install-app-only"
      StrCpy $DroneDreamRuntimeDrive ""
      MessageBox MB_ICONEXCLAMATION|MB_OK "没有固定 NTFS 磁盘满足至少 52 GiB 可用空间；本次只能安装桌面程序。"
    ${EndIf}
    StrCpy $DroneDreamModePageVisited "1"
    GetDlgItem $1 $HWNDPARENT 1
    SendMessage $1 ${WM_SETTEXT} 0 "STR:安装 / Install"
    nsDialogs::Show
  FunctionEnd

  Function DroneDreamRuntimeModePageLeave
    ${NSD_GetState} $DroneDreamAppOnlyRadio $0
    ${If} $0 == ${BST_CHECKED}
      StrCpy $DroneDreamInstallMode "install-app-only"
      StrCpy $DroneDreamRuntimeDrive ""
      Return
    ${EndIf}
    ${NSD_GetState} $DroneDreamCustomRadio $0
    ${If} $0 == ${BST_CHECKED}
      ${NSD_GetText} $DroneDreamCustomDriveEdit $DroneDreamRuntimeDrive
      StrCpy $DroneDreamInstallMode "custom"
      ${If} $DroneDreamRuntimeDrive == ""
        MessageBox MB_ICONEXCLAMATION|MB_OK "自定义安装必须输入一个盘符（例如 E:）。 / Custom runtime setup requires a drive such as E:."
        Abort
      ${EndIf}
    ${Else}
      StrCpy $DroneDreamInstallMode "install-all"
    ${EndIf}
    Push $DroneDreamRuntimeDrive
    Call DroneDreamRunPlanner
    Pop $0
    ${If} $0 != "1"
      MessageBox MB_ICONEXCLAMATION|MB_OK "所选磁盘不满足固定 NTFS、安全路径和至少 52 GiB 可用空间要求。"
      Abort
    ${EndIf}
    StrCpy $DroneDreamRuntimeDrive $DroneDreamPlanTarget 2

    ; The desktop application must never be placed in the dedicated runtime
    ; root. The planner runs before application files are copied, so without
    ; this check E:\DroneDream could look empty during planning and then fail
    ; the first-run safety validation after the installer fills it with files.
    GetFullPathName $1 "$INSTDIR"
    GetFullPathName $2 "$DroneDreamPlanTarget"
    ${StrCase} $1 $1 "U"
    ${StrCase} $2 $2 "U"
    ${If} $1 == $2
      MessageBox MB_ICONEXCLAMATION|MB_OK "桌面程序不能安装到专用 Runtime 目录 $DroneDreamPlanTarget。请返回并选择其他桌面安装目录。 / The desktop application cannot be installed inside the dedicated runtime root. Go back and choose another application folder."
      Abort
    ${EndIf}
    StrCpy $3 "$2\"
    ${StrLoc} $0 $1 $3 ">"
    ${If} $0 == 0
      MessageBox MB_ICONEXCLAMATION|MB_OK "桌面程序不能安装到专用 Runtime 目录 $DroneDreamPlanTarget 的子目录。请返回并选择其他桌面安装目录。 / The desktop application cannot be installed below the dedicated runtime root. Go back and choose another application folder."
      Abort
    ${EndIf}
  FunctionEnd
!macroend

; Fresh interactive install-all/custom setups launch once immediately after a
; successful install. Other modes retain Tauri's normal Finish-page or /R
; behavior and never gain an implicit runtime download.
!macro DRONEDREAM_ONINSTSUCCESS
  ${IfNot} ${Silent}
  ${AndIf} $PassiveMode != 1
  ${AndIf} $UpdateMode != 1
  ${AndIf} $DroneDreamWasInstalled == "0"
  ${AndIf} $DroneDreamInstallMode != "install-app-only"
    StrCpy $DroneDreamAutoLaunched "1"
    nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
  ${EndIf}
!macroend

; The Finish-page Run checkbox is checked by default. If the one-confirmation
; path already launched the application, its callback becomes a no-op so a
; quick Finish click cannot create a second process.
!macro DRONEDREAM_BEFORE_RUN_MAIN_BINARY
  ${If} $DroneDreamAutoLaunched == "1"
    Return
  ${EndIf}
!macroend

; When Tauri's reinstall page starts the old uninstaller, let that child prove
; that it is operating inside the parent installer's already-acquired quiesce.
; The child re-runs the idempotent native begin command, so command-line flags
; alone can never bypass the lease.
!macro DRONEDREAM_APPEND_UNINSTALL_QUIESCE
  ${If} $DroneDreamQuiesceActive == "1"
    StrCpy $R1 "$R1 /DRONEDREAMQUIESCETOKEN=$DroneDreamQuiesceToken /DRONEDREAMQUIESCEPID=$DroneDreamQuiesceOwnerPid"
  ${EndIf}
!macroend

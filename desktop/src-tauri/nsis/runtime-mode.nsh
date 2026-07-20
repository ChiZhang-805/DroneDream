; DroneDream runtime-mode page, expanded by anchors in the pinned Tauri template.
; These three variables are declared at include time because the vendored
; reinstall function appends them to the old uninstaller command before the
; custom Runtime page macro is expanded later in the template.
; Tauri registers its MUI languages near the end of the template. Expanding
; this macro there (rather than including the table here) is essential: before
; MUI_LANGUAGE runs, NSIS silently maps every custom LangString to English and
; the later Chinese declaration overwrites it.
!define DRONEDREAM_INSTALLER_LANGUAGES_FILE "${__FILEDIR__}\installer-languages.nsh"
!include "${__FILEDIR__}\path-guard.nsh"
!macro DRONEDREAM_INSTALLER_LANGUAGE_TABLE
  !include "${DRONEDREAM_INSTALLER_LANGUAGES_FILE}"
!macroend

Var DroneDreamQuiesceToken
Var DroneDreamQuiesceOwnerPid
Var DroneDreamQuiesceActive
Var DroneDreamInstallerLanguage
Var DroneDreamDiagnosticLog
Var DroneDreamDiagnosticHandle
Var DroneDreamValidatePathOnly

!macro DRONEDREAM_ONINIT
  ; MUI_LANGDLL_DISPLAY has already returned at this anchor. Preserve that
  ; exact choice for every later custom page and message.
  StrCpy $DroneDreamInstallerLanguage "$LANGUAGE"
  StrCpy $DroneDreamDiagnosticLog "$TEMP\DroneDream\installer-diagnostics.log"
  CreateDirectory "$TEMP\DroneDream"
  Delete "$DroneDreamDiagnosticLog"
  StrCpy $DroneDreamWasInstalled "0"
  StrCpy $DroneDreamInstallMode "install-app-only"
  StrCpy $DroneDreamRuntimeDrive ""
  StrCpy $DroneDreamModePageVisited "0"
  StrCpy $DroneDreamRuntimeProtocol "0"
  StrCpy $DroneDreamQuiesceToken ""
  StrCpy $DroneDreamQuiesceOwnerPid ""
  StrCpy $DroneDreamQuiesceActive "0"
  StrCpy $DroneDreamValidatePathOnly "0"
  ClearErrors
  ${GetOptions} $CMDLINE "/DRONEDREAMVALIDATEPATHONLY" $0
  ${IfNot} ${Errors}
    StrCpy $DroneDreamValidatePathOnly "1"
  ${EndIf}
  ClearErrors
  Push "installer-init language=$DroneDreamInstallerLanguage"
  Call DroneDreamAppendInstallerDiagnostic
  ReadRegStr $0 SHCTX "${UNINSTKEY}" "UninstallString"
  ${If} $0 != ""
    StrCpy $DroneDreamWasInstalled "1"
    ReadRegStr $0 SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeInstallMode"
    ${If} $0 == "install-all"
    ${OrIf} $0 == "custom"
    ${OrIf} $0 == "install-app-only"
      StrCpy $DroneDreamInstallMode $0
    ${EndIf}
    ReadRegStr $0 SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeDrive"
    StrCpy $DroneDreamRuntimeDrive $0
  ${EndIf}
  ReadRegDWORD $DroneDreamRuntimeProtocol SHCTX "${MANUPRODUCTKEY}" "DroneDreamRuntimeOperationProtocol"
  ${If} $DroneDreamRuntimeProtocol >= 2
    IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 dronedream_oninit_no_quiesce
      Call DroneDreamAcquireRuntimeQuiesce
      Pop $0
      ${If} $0 == "busy"
        MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_RuntimeBusy)"
        Abort
      ${ElseIf} $0 == "pending"
        MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_RuntimePendingUpdate)"
        Abort
      ${ElseIf} $0 != "ok"
        MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_RuntimeIsolationFailed)"
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
  Var DroneDreamPlanBlockerCode
  Var DroneDreamPlanDiagnosticCode
  Var DroneDreamSuggestedDrive
  Var DroneDreamRecommendedLabel
  Var DroneDreamRetryButton
  Var DroneDreamFullRadio
  Var DroneDreamCustomRadio
  Var DroneDreamAppOnlyRadio
  Var DroneDreamCustomDriveEdit
  Var DroneDreamModePageVisited
  Var DroneDreamRuntimeProtocol

  Page custom DroneDreamRuntimeModePageCreate DroneDreamRuntimeModePageLeave

  Function DroneDreamAppendInstallerDiagnostic
    Exch $0
    ClearErrors
    FileOpen $DroneDreamDiagnosticHandle "$DroneDreamDiagnosticLog" a
    ${IfNot} ${Errors}
      FileSeek $DroneDreamDiagnosticHandle 0 END
      FileWrite $DroneDreamDiagnosticHandle "$0$\r$\n"
      FileClose $DroneDreamDiagnosticHandle
    ${EndIf}
    ClearErrors
    Pop $0
  FunctionEnd

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
    StrCpy $8 "0"
    StrCpy $DroneDreamPlanDiagnosticCode "not-started"
    dronedream_plan_retry:
    Delete "$DroneDreamPlanFile"
    ClearErrors
    StrCpy $1 "-1"
    ${If} $0 == ""
      ExecWait '"$DroneDreamPlannerExe" --write-installer-plan "$DroneDreamPlanFile"' $1
    ${Else}
      ExecWait '"$DroneDreamPlannerExe" --write-installer-plan "$DroneDreamPlanFile" "$0"' $1
    ${EndIf}
    ${If} ${Errors}
      StrCpy $DroneDreamPlanDiagnosticCode "launch-failed"
      Goto dronedream_plan_retry_or_fail
    ${ElseIf} $1 != 0
      StrCpy $DroneDreamPlanDiagnosticCode "planner-exit-$1"
      Goto dronedream_plan_retry_or_fail
    ${EndIf}
    IfFileExists "$DroneDreamPlanFile" dronedream_plan_file_present 0
      StrCpy $DroneDreamPlanDiagnosticCode "result-missing"
      Goto dronedream_plan_retry_or_fail
    dronedream_plan_file_present:
    ClearErrors
    ReadINIStr $1 "$DroneDreamPlanFile" "plan" "schemaVersion"
    ReadINIStr $2 "$DroneDreamPlanFile" "plan" "targetDrive"
    ReadINIStr $DroneDreamPlanTarget "$DroneDreamPlanFile" "plan" "targetRoot"
    ReadINIStr $3 "$DroneDreamPlanFile" "plan" "downloadBytes"
    ReadINIStr $4 "$DroneDreamPlanFile" "plan" "installedBytes"
    ReadINIStr $5 "$DroneDreamPlanFile" "plan" "minimumFreeBytes"
    ReadINIStr $DroneDreamPlanCanInstall "$DroneDreamPlanFile" "plan" "canInstall"
    ReadINIStr $6 "$DroneDreamPlanFile" "plan" "blockerCode"
    ${If} ${Errors}
      StrCpy $DroneDreamPlanDiagnosticCode "result-incomplete"
      Goto dronedream_plan_retry_or_fail
    ${EndIf}
    StrCpy $DroneDreamPlanBlockerCode "$6"
    StrCpy $7 "$2\DroneDream"
    ${If} $1 != "1"
    ${OrIf} $3 != "8589934592"
    ${OrIf} $4 != "25769803776"
    ${OrIf} $5 != "55834574848"
      Goto dronedream_plan_result_invalid
    ${EndIf}
    ${If} $DroneDreamPlanCanInstall == "1"
      ${If} $2 == ""
      ${OrIf} $DroneDreamPlanTarget != $7
      ${OrIf} $6 != "none"
        Goto dronedream_plan_result_invalid
      ${EndIf}
    ${ElseIf} $DroneDreamPlanCanInstall == "0"
      ${If} $6 == "no-eligible-target"
        ${If} $2 != ""
        ${OrIf} $DroneDreamPlanTarget != ""
          Goto dronedream_plan_result_invalid
        ${EndIf}
      ${ElseIf} $6 == "prerequisite-blocked"
        ${If} $2 == ""
        ${OrIf} $DroneDreamPlanTarget != $7
          Goto dronedream_plan_result_invalid
        ${EndIf}
      ${Else}
        Goto dronedream_plan_result_invalid
      ${EndIf}
    ${Else}
      Goto dronedream_plan_result_invalid
    ${EndIf}
    StrCpy $DroneDreamPlanDiagnosticCode "$6"
    Push "planner-result code=$DroneDreamPlanDiagnosticCode target=$DroneDreamPlanTarget"
    Call DroneDreamAppendInstallerDiagnostic
    Delete "$DroneDreamPlanFile"
    Pop $0
    Push $DroneDreamPlanCanInstall
    Return

    dronedream_plan_result_invalid:
    StrCpy $DroneDreamPlanDiagnosticCode "result-invalid"

    dronedream_plan_retry_or_fail:
    Push "planner-failure code=$DroneDreamPlanDiagnosticCode attempt=$8 drive=$0 exit=$1"
    Call DroneDreamAppendInstallerDiagnostic
    Delete "$DroneDreamPlanFile"
    ${If} $8 == "0"
      StrCpy $8 "1"
      Sleep 300
      Goto dronedream_plan_retry
    ${EndIf}
    StrCpy $DroneDreamPlanCanInstall "0"
    StrCpy $DroneDreamPlanTarget ""
    StrCpy $DroneDreamPlanBlockerCode "planner-error"
    Pop $0
    Push "0"
  FunctionEnd

  Function DroneDreamClassifyApplicationPath
    Push $8
    Push $9
    !insertmacro DRONEDREAM_CLASSIFY_APPLICATION_PATH \
      $INSTDIR $DroneDreamPlanTarget $4 $1 $2 $3 $0 INSTALLER
    Pop $9
    Pop $8
    Push "path-check relation=$4 app=$1 runtime=$2"
    Call DroneDreamAppendInstallerDiagnostic
    Push $4
  FunctionEnd

  Function DroneDreamRuntimeModePageCreate
    StrCpy $LANGUAGE $DroneDreamInstallerLanguage
    IfSilent 0 +2
      Abort
    ${If} $PassiveMode == 1
    ${OrIf} $UpdateMode == 1
    ${OrIf} $DroneDreamWasInstalled == 1
    ${OrIf} $WixMode == 1
      Abort
    ${EndIf}
    InitPluginsDir
    ; Do not put "installer" or "setup" in this temporary executable name.
    ; Windows installer-detection heuristics otherwise reject an as-invoker
    ; launch with Win32 error 740 before the disk probe can run.
    StrCpy $DroneDreamPlannerExe "$PLUGINSDIR\dronedream-runtime-probe.exe"
    StrCpy $DroneDreamPlanFile "$PLUGINSDIR\dronedream-installer-plan-v1.ini"
    Delete "$DroneDreamPlannerExe"
    Delete "$DroneDreamPlanFile"
    SetOutPath "$PLUGINSDIR"
    File "/oname=dronedream-runtime-probe.exe" "${MAINBINARYSRCPATH}"
    ; LLVM-MinGW fallback builds dynamically import this loader. MSVC builds
    ; do not have the sibling file, so /nonfatal is intentional.
    File /nonfatal "/oname=WebView2Loader.dll" "${DRONEDREAM_PLANNER_LOADER_SOURCE}"
    Push ""
    Call DroneDreamRunPlanner
    Pop $DroneDreamPlanCanInstall
    ${If} $DroneDreamPlanCanInstall == "0"
    ${AndIf} $DroneDreamPlanBlockerCode == "prerequisite-blocked"
    ${AndIf} $DroneDreamPlanTarget != ""
      Push "runtime-mode-page-create app-only-runtime-preflight target=$DroneDreamPlanTarget diagnostic=$DroneDreamPlanDiagnosticCode"
      Call DroneDreamAppendInstallerDiagnostic
    ${EndIf}
    StrCpy $LANGUAGE $DroneDreamInstallerLanguage
    StrCpy $DroneDreamSuggestedDrive ""
    ${If} $DroneDreamPlanTarget != ""
      StrCpy $DroneDreamSuggestedDrive $DroneDreamPlanTarget 2
    ${EndIf}
    ${If} $DroneDreamValidatePathOnly == "1"
      Call DroneDreamClassifyApplicationPath
      Pop $0
      StrCmp $0 "safe" dronedream_path_validation_success dronedream_path_validation_failure
      dronedream_path_validation_failure:
        Push "path-validation-only failure relation=$0"
        Call DroneDreamAppendInstallerDiagnostic
        SetErrorLevel 86
        Quit
      dronedream_path_validation_success:
        Push "path-validation-only success"
        Call DroneDreamAppendInstallerDiagnostic
        SetErrorLevel 0
        Quit
    ${EndIf}
    !insertmacro MUI_HEADER_TEXT "DroneDreamRuntime" "$(DD_ModeHeader)"
    nsDialogs::Create 1018
    Pop $1
    ${If} $1 == error
      Abort
    ${EndIf}
    ${NSD_CreateLabel} 0 0 100% 24u "$(DD_ModeRequirements)"
    Pop $1
    ${NSD_CreateRadioButton} 0 30u 100% 14u "$(DD_InstallAll)"
    Pop $DroneDreamFullRadio
    ${If} $DroneDreamPlanCanInstall == "1"
      ${NSD_CreateLabel} 18u 47u 70% 18u "$(DD_RecommendedTarget)"
    ${Else}
      ${NSD_CreateLabel} 18u 47u 70% 18u "$(DD_RuntimeSetupDeferred)"
    ${EndIf}
    Pop $DroneDreamRecommendedLabel
    ${NSD_CreateButton} 76% 45u 24% 17u "$(DD_RetryDetection)"
    Pop $DroneDreamRetryButton
    ${NSD_OnClick} $DroneDreamRetryButton DroneDreamRetryDetection
    ${NSD_CreateRadioButton} 0 69u 100% 14u "$(DD_CustomDrive)"
    Pop $DroneDreamCustomRadio
    ${NSD_CreateText} 18u 88u 52u 14u "$DroneDreamSuggestedDrive"
    Pop $DroneDreamCustomDriveEdit
    ${NSD_CreateLabel} 78u 87u 73% 20u "$(DD_CustomDriveHint)"
    Pop $1
    ${NSD_CreateRadioButton} 0 114u 100% 14u "$(DD_AppOnly)"
    Pop $DroneDreamAppOnlyRadio
    ${NSD_CreateLabel} 18u 132u 95% 26u "$(DD_ModeNote)"
    Pop $1
    ${If} $DroneDreamPlanCanInstall == "1"
      ShowWindow $DroneDreamRetryButton ${SW_HIDE}
      ${If} $DroneDreamModePageVisited == "0"
        ${NSD_Check} $DroneDreamFullRadio
        StrCpy $DroneDreamInstallMode "install-all"
        StrCpy $DroneDreamRuntimeDrive $DroneDreamSuggestedDrive
      ${ElseIf} $DroneDreamInstallMode == "custom"
        ${NSD_Check} $DroneDreamCustomRadio
        ${NSD_SetText} $DroneDreamCustomDriveEdit $DroneDreamRuntimeDrive
      ${ElseIf} $DroneDreamInstallMode == "install-app-only"
        ${NSD_Check} $DroneDreamAppOnlyRadio
      ${Else}
        ${NSD_Check} $DroneDreamFullRadio
        StrCpy $DroneDreamRuntimeDrive $DroneDreamSuggestedDrive
      ${EndIf}
    ${Else}
      EnableWindow $DroneDreamFullRadio 0
      ${If} $DroneDreamPlanBlockerCode == "prerequisite-blocked"
        EnableWindow $DroneDreamCustomRadio 0
        EnableWindow $DroneDreamCustomDriveEdit 0
      ${EndIf}
      ${NSD_Check} $DroneDreamAppOnlyRadio
      StrCpy $DroneDreamInstallMode "install-app-only"
      StrCpy $DroneDreamRuntimeDrive ""
      ; A failed Runtime preflight is not a desktop-installer failure. Keep the
      ; page usable, select the safe app-only fallback, and leave detailed
      ; diagnostics to DroneDream. A modal warning here used to interrupt the
      ; normal first-run journey and briefly exposed the previous MUI page
      ; behind the dialog while this custom page was still being constructed.
    ${EndIf}
    StrCpy $DroneDreamModePageVisited "1"
    GetDlgItem $1 $HWNDPARENT 1
    SendMessage $1 ${WM_SETTEXT} 0 "STR:$(DD_InstallButton)"
    nsDialogs::Show
  FunctionEnd

  Function DroneDreamRetryDetection
    Push ""
    Call DroneDreamRunPlanner
    Pop $DroneDreamPlanCanInstall
    ${If} $DroneDreamPlanCanInstall == "0"
    ${AndIf} $DroneDreamPlanBlockerCode == "prerequisite-blocked"
    ${AndIf} $DroneDreamPlanTarget != ""
      Push "runtime-mode-retry app-only-runtime-preflight target=$DroneDreamPlanTarget diagnostic=$DroneDreamPlanDiagnosticCode"
      Call DroneDreamAppendInstallerDiagnostic
    ${EndIf}
    StrCpy $LANGUAGE $DroneDreamInstallerLanguage
    ${If} $DroneDreamPlanCanInstall == "1"
      StrCpy $DroneDreamSuggestedDrive $DroneDreamPlanTarget 2
      StrCpy $DroneDreamRuntimeDrive $DroneDreamSuggestedDrive
      StrCpy $DroneDreamInstallMode "install-all"
      ${NSD_SetText} $DroneDreamRecommendedLabel "$(DD_RecommendedTarget)"
      ${NSD_SetText} $DroneDreamCustomDriveEdit "$DroneDreamSuggestedDrive"
      EnableWindow $DroneDreamFullRadio 1
      EnableWindow $DroneDreamCustomRadio 1
      EnableWindow $DroneDreamCustomDriveEdit 1
      ${NSD_Check} $DroneDreamFullRadio
      ${NSD_Uncheck} $DroneDreamCustomRadio
      ${NSD_Uncheck} $DroneDreamAppOnlyRadio
      ShowWindow $DroneDreamRetryButton ${SW_HIDE}
    ${Else}
      ${If} $DroneDreamPlanBlockerCode == "prerequisite-blocked"
        EnableWindow $DroneDreamCustomRadio 0
        EnableWindow $DroneDreamCustomDriveEdit 0
        ${NSD_SetText} $DroneDreamRecommendedLabel "$(DD_RuntimeSetupDeferred)"
      ${ElseIf} $DroneDreamPlanBlockerCode == "no-eligible-target"
        EnableWindow $DroneDreamCustomRadio 1
        EnableWindow $DroneDreamCustomDriveEdit 1
        ${NSD_SetText} $DroneDreamRecommendedLabel "$(DD_NoRecommendedTarget)"
      ${Else}
        EnableWindow $DroneDreamCustomRadio 1
        EnableWindow $DroneDreamCustomDriveEdit 1
        ${NSD_SetText} $DroneDreamRecommendedLabel "$(DD_PlannerUnavailable)"
      ${EndIf}
      ${NSD_Check} $DroneDreamAppOnlyRadio
      ${NSD_Uncheck} $DroneDreamFullRadio
      ${NSD_Uncheck} $DroneDreamCustomRadio
      StrCpy $DroneDreamInstallMode "install-app-only"
      StrCpy $DroneDreamRuntimeDrive ""
    ${EndIf}
  FunctionEnd

  Function DroneDreamRuntimeModePageLeave
    StrCpy $LANGUAGE $DroneDreamInstallerLanguage
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
        MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_CustomDriveRequired)"
        Abort
      ${EndIf}
    ${Else}
      StrCpy $DroneDreamInstallMode "install-all"
    ${EndIf}
    Push $DroneDreamRuntimeDrive
    Call DroneDreamRunPlanner
    Pop $0
    StrCpy $LANGUAGE $DroneDreamInstallerLanguage
    ${If} $0 != "1"
    ${AndIf} $DroneDreamPlanBlockerCode == "prerequisite-blocked"
    ${AndIf} $DroneDreamPlanTarget != ""
      Push "runtime-mode-page-leave app-only-runtime-preflight target=$DroneDreamPlanTarget diagnostic=$DroneDreamPlanDiagnosticCode drive=$DroneDreamRuntimeDrive"
      Call DroneDreamAppendInstallerDiagnostic
      StrCpy $DroneDreamInstallMode "install-app-only"
      StrCpy $DroneDreamRuntimeDrive ""
      Return
    ${EndIf}
    ${If} $0 != "1"
      ${If} $DroneDreamPlanBlockerCode == "planner-error"
        MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_SelectedDriveProbeFailed)"
      ${Else}
        MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_SelectedDriveInvalid)"
      ${EndIf}
      Abort
    ${EndIf}
    StrCpy $DroneDreamRuntimeDrive $DroneDreamPlanTarget 2

    ; The desktop application must never be placed in the dedicated runtime
    ; root. The planner runs before application files are copied, so without
    ; this check E:\DroneDream could look empty during planning and then fail
    ; the first-run safety validation after the installer fills it with files.
    Call DroneDreamClassifyApplicationPath
    Pop $4
    StrCmp $4 "same" dronedream_app_at_runtime_root 0
    StrCmp $4 "child" dronedream_app_below_runtime_root 0
    StrCmp $4 "safe" dronedream_app_path_safe dronedream_app_path_invalid

    dronedream_app_path_invalid:
      MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_AppPathCheckFailed)"
      Abort

    dronedream_app_at_runtime_root:
      MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_AppAtRuntimeRoot)"
      Abort

    dronedream_app_below_runtime_root:
      MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_AppBelowRuntimeRoot)"
      Abort

    dronedream_app_path_safe:
  FunctionEnd
!macroend

; Interactive application launch is owned exclusively by Tauri's standard
; Finish-page Run action. Runtime intent remains durable until the application
; opens, so there is no reason to start a second process from .onInstSuccess.
; The desktop binary also enforces single-instance behavior as defense in depth.

; When Tauri's reinstall page starts the old uninstaller, let that child prove
; that it is operating inside the parent installer's already-acquired quiesce.
; The child re-runs the idempotent native begin command, so command-line flags
; alone can never bypass the lease.
!macro DRONEDREAM_APPEND_UNINSTALL_QUIESCE
  ${If} $DroneDreamQuiesceActive == "1"
    StrCpy $R1 "$R1 /DRONEDREAMQUIESCETOKEN=$DroneDreamQuiesceToken /DRONEDREAMQUIESCEPID=$DroneDreamQuiesceOwnerPid"
  ${EndIf}
!macroend

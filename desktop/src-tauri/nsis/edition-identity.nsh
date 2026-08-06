; Canonical Windows presentation identity for each side-by-side DroneDream app.
;
; PRODUCTNAME and BUNDLEID remain the internal installation identities used by
; install directories, registry keys, updater channels, app data, and process
; ownership.  These display-only values must never be used to grant capability
; or collapse two editions into the same Windows installation.

!if "${PRODUCTNAME}" == "DroneDream-Universal"
  !define DRONEDREAM_EDITION_ID "universal"
  !define DRONEDREAM_DISPLAYNAME "DroneDream"
  !define DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED "1"
!else if "${PRODUCTNAME}" == "DroneDream-Sim"
  !define DRONEDREAM_EDITION_ID "sim"
  !define DRONEDREAM_DISPLAYNAME "DroneDream · SIM"
  !define DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED "1"
!else if "${PRODUCTNAME}" == "DroneDream-Lab"
  !define DRONEDREAM_EDITION_ID "lab"
  !define DRONEDREAM_DISPLAYNAME "DroneDream · LAB"
  !define DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED "1"
!else if "${PRODUCTNAME}" == "DroneDream-Field"
  !define DRONEDREAM_EDITION_ID "field"
  !define DRONEDREAM_DISPLAYNAME "DroneDream · FIELD"
  !define DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED "0"
!else if "${PRODUCTNAME}" == "DroneDream"
  ; Retain source-build compatibility for the pre-edition development config.
  ; This identity is never promotion-eligible under the four-edition contract.
  !define DRONEDREAM_EDITION_ID "legacy-development"
  !define DRONEDREAM_DISPLAYNAME "DroneDream"
  !define DRONEDREAM_RUNTIME_MODE_PAGE_ENABLED "1"
!else
  !error "Unknown DroneDream installer PRODUCTNAME: ${PRODUCTNAME}"
!endif

!define DRONEDREAM_SHORTCUTNAME "${DRONEDREAM_DISPLAYNAME}"

; Create or refresh a shortcut only when the path is empty or already belongs
; to this exact installation.  A legacy or cross-edition collision is retained
; byte-for-byte and blocks shortcut creation instead of being overwritten.
!macro DRONEDREAM_CREATE_DISPLAY_SHORTCUT SHORTCUT_PATH LABEL_PREFIX
  IfFileExists "${SHORTCUT_PATH}" 0 ${LABEL_PREFIX}_create

  !insertmacro IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  ${If} $0 != 1
    !insertmacro IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\$OldMainBinaryName"
    Pop $0
  ${EndIf}
  ${If} $0 != 1
    DetailPrint "$(DD_ShortcutConflict)"
    IfSilent ${LABEL_PREFIX}_conflict_done 0
    ${If} $PassiveMode = 0
    ${AndIf} $UpdateMode = 0
      MessageBox MB_ICONEXCLAMATION|MB_OK "$(DD_ShortcutConflict)"
    ${EndIf}
    ${LABEL_PREFIX}_conflict_done:
    SetErrors
    Goto ${LABEL_PREFIX}_done
  ${EndIf}

  Delete "${SHORTCUT_PATH}"
  ${LABEL_PREFIX}_create:
    CreateShortcut "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe" "" "$INSTDIR\icons\DroneDream.ico" 0
    !insertmacro SetLnkAppUserModelId "${SHORTCUT_PATH}"
  ${LABEL_PREFIX}_done:
!macroend

!macro DRONEDREAM_CREATE_OR_UPDATE_STARTMENU_SHORTCUT LABEL_PREFIX
  ; Update-mode shortcuts are migrated/refreshed by NSIS_HOOK_POSTINSTALL after
  ; the new executable and canonical icon have been installed.
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Goto ${LABEL_PREFIX}_done
    ${EndIf}
  ${EndIf}

  !if "${STARTMENUFOLDER}" != ""
    CreateDirectory "$SMPROGRAMS\$AppStartMenuFolder"
    !insertmacro DRONEDREAM_CREATE_DISPLAY_SHORTCUT "$SMPROGRAMS\$AppStartMenuFolder\${DRONEDREAM_SHORTCUTNAME}.lnk" ${LABEL_PREFIX}_folder
  !else
    !insertmacro DRONEDREAM_CREATE_DISPLAY_SHORTCUT "$SMPROGRAMS\${DRONEDREAM_SHORTCUTNAME}.lnk" ${LABEL_PREFIX}_root
  !endif
  ${LABEL_PREFIX}_done:
!macroend

!macro DRONEDREAM_CREATE_OR_UPDATE_DESKTOP_SHORTCUT LABEL_PREFIX
  ${If} $WixMode = 0
    ${If} $UpdateMode = 1
    ${OrIf} $NoShortcutMode = 1
      Goto ${LABEL_PREFIX}_done
    ${EndIf}
  ${EndIf}

  !insertmacro DRONEDREAM_CREATE_DISPLAY_SHORTCUT "$DESKTOP\${DRONEDREAM_SHORTCUTNAME}.lnk" ${LABEL_PREFIX}_shortcut
  ${LABEL_PREFIX}_done:
!macroend

; Remove an early-candidate internal-name shortcut only when its target belongs
; to the installation currently being uninstalled. A foreign link is untouched.
!macro DRONEDREAM_REMOVE_INTERNAL_SHORTCUT SHORTCUT_PATH
  !if "${DRONEDREAM_SHORTCUTNAME}" != "${PRODUCTNAME}"
    !insertmacro IsShortcutTarget "${SHORTCUT_PATH}" "$INSTDIR\${MAINBINARYNAME}.exe"
    Pop $0
    ${If} $0 = 1
      !insertmacro UnpinShortcut "${SHORTCUT_PATH}"
      Delete "${SHORTCUT_PATH}"
    ${EndIf}
  !endif
!macroend

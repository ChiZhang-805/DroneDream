; Single source of truth for classifying the desktop application path relative
; to the dedicated Runtime root. All comparisons are strict string comparisons;
; LogicLib numeric operators must not be used for Windows paths.
!macro DRONEDREAM_CLASSIFY_APPLICATION_PATH APP_PATH RUNTIME_PATH RESULT APP_NORMALIZED RUNTIME_NORMALIZED PREFIX POSITION LABEL_SUFFIX
  ; NSIS GetFullPathName returns an empty string when the final directory does
  ; not exist yet, which is the normal state during a first installation.
  ; Win32 GetFullPathNameW performs lexical normalization without requiring the
  ; target to exist. $8 and $9 are documented scratch registers for this macro.
  StrCpy ${RESULT} "invalid"
  System::Call 'kernel32::GetFullPathNameW(w "${APP_PATH}", i ${NSIS_MAX_STRLEN}, w .r9, p 0) i .r8'
  StrCmp $8 "0" dronedream_path_guard_done_${LABEL_SUFFIX} 0
  StrCpy ${APP_NORMALIZED} $9
  System::Call 'kernel32::GetFullPathNameW(w "${RUNTIME_PATH}", i ${NSIS_MAX_STRLEN}, w .r9, p 0) i .r8'
  StrCmp $8 "0" dronedream_path_guard_done_${LABEL_SUFFIX} 0
  StrCpy ${RUNTIME_NORMALIZED} $9
  ${StrCase} ${APP_NORMALIZED} ${APP_NORMALIZED} "U"
  ${StrCase} ${RUNTIME_NORMALIZED} ${RUNTIME_NORMALIZED} "U"

  StrCpy ${RESULT} "same"
  StrCmp ${APP_NORMALIZED} ${RUNTIME_NORMALIZED} dronedream_path_guard_done_${LABEL_SUFFIX} 0

  StrCpy ${PREFIX} "${RUNTIME_NORMALIZED}\"
  ${StrLoc} ${POSITION} ${APP_NORMALIZED} ${PREFIX} ">"
  StrCpy ${RESULT} "child"
  StrCmp ${POSITION} "0" dronedream_path_guard_done_${LABEL_SUFFIX} 0

  StrCpy ${RESULT} "safe"
  dronedream_path_guard_done_${LABEL_SUFFIX}:
!macroend

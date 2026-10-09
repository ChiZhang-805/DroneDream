// Keep the website import stable while sharing focus and scroll ownership with
// application dialogs. Separate implementations cannot coordinate nested modals.
export { useModalFocus } from "../hooks/useModalFocus";

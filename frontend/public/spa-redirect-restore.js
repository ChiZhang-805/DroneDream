(() => {
  const redirectKey = "dronedream:spa-redirect";
  try {
    const redirectTarget = window.sessionStorage.getItem(redirectKey);
    window.sessionStorage.removeItem(redirectKey);
    if (
      redirectTarget &&
      redirectTarget.startsWith("/") &&
      !redirectTarget.startsWith("//")
    ) {
      window.history.replaceState(null, "", redirectTarget);
    }
  } catch {
    // The selected application entry remains usable without session storage.
  }
})();

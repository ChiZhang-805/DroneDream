(() => {
  const redirectKey = "dronedream:spa-redirect";
  const requestedPath =
    window.location.pathname + window.location.search + window.location.hash;
  const isConsolePath =
    window.location.pathname === "/console" ||
    window.location.pathname.startsWith("/console/");
  const entryPath = isConsolePath ? "/console/" : "/";
  try {
    window.sessionStorage.setItem(redirectKey, requestedPath);
  } catch {
    // Falling back to the correct application root is still safe.
  }
  window.location.replace(entryPath);
})();

/* Runs synchronously in <head> so the page never flashes the wrong theme. */
(function () {
  var t = null;
  try { t = localStorage.getItem("oims-theme"); } catch (e) {}
  if (!t) {
    var m = document.cookie.match(/(?:^|; )oims-theme=(light|dark)/);
    if (m) t = m[1];
  }
  if (t !== "light" && t !== "dark") {
    t = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  var h = document.documentElement;
  h.setAttribute("data-theme", t);
  h.setAttribute("data-bs-theme", t);
  try {
    if (localStorage.getItem("oims-sidebar") === "compact") h.classList.add("sidebar-compact");
  } catch (e) {}
  // Installed app: set before the page draws, so the Back button does not pop in after loading
  if ((window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true) {
    h.classList.add("is-standalone");
  }
})();

/* Installable app: registers the service worker and runs the "Install app" buttons.
   External file (strict CSP, no inline scripts). */
(function () {
  "use strict";

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {});
    });
  }

  /* "Try again" on the offline page reloads the page the person was opening. */
  var retry = document.querySelector("[data-retry]");
  if (retry) retry.addEventListener("click", function (e) { e.preventDefault(); window.location.reload(); });

  var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
    window.navigator.standalone === true;
  var ua = navigator.userAgent || "";
  var isIOS = /iphone|ipad|ipod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
  var deferred = null;

  function buttons() { return document.querySelectorAll("[data-install]"); }
  function show(on) { buttons().forEach(function (b) { b.hidden = !on; }); }

  if (standalone) { show(false); return; }   // already running as the installed app

  // Android, Chrome, Edge and other browsers that can install directly.
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    show(true);
  });
  window.addEventListener("appinstalled", function () { deferred = null; show(false); });

  // iPhone and iPad install through Safari's Share menu, so the button shows the steps instead.
  if (isIOS) show(true);

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-install]");
    if (!b) return;
    e.preventDefault();
    if (deferred) {
      deferred.prompt();
      deferred.userChoice.then(function () { deferred = null; show(false); });
      return;
    }
    var modal = document.getElementById("install-ios-modal");
    if (modal && window.bootstrap) window.bootstrap.Modal.getOrCreateInstance(modal).show();
  });
})();

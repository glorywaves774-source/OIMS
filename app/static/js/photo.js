/* Staff profile photo: take it with the camera (front or back), or choose a picture.
   External file (strict CSP). The camera is switched off as soon as the window closes. */
(function () {
  "use strict";
  var errorBox = document.querySelector("[data-photo-error]");

  /* Choosing a picture uploads it straight away */
  var form = document.querySelector("[data-photo-upload]");
  var file = document.querySelector("[data-photo-file]");
  if (form && file) {
    file.addEventListener("change", function () {
      if (!file.files.length) return;
      if (file.files[0].size > 8 * 1024 * 1024) {
        if (errorBox) { errorBox.textContent = "8 MB max."; errorBox.hidden = false; }
        return;
      }
      form.submit();
    });
  }

  var modal = document.querySelector("[data-camera]");
  var openBtn = document.querySelector("[data-camera-open]");
  if (!modal || !openBtn) return;
  var md = navigator.mediaDevices;
  if (!md || !md.getUserMedia) return;     // no camera support: only "Upload photo" is shown
  openBtn.hidden = false;

  var q = function (s) { return modal.querySelector(s); };
  var video = q("[data-camera-video]"), shot = q("[data-camera-shot]"), err = q("[data-camera-error]");
  var snap = q("[data-camera-snap]"), retake = q("[data-camera-retake]"), use = q("[data-camera-use]");
  var switchBtn = q("[data-camera-switch]"), hint = q("[data-camera-hint]");
  var stream = null, facing = "user";

  function msg(k) { var el = modal.querySelector('[data-camera-msgs] [data-k="' + k + '"]'); return el ? el.textContent : k; }
  function showError(k) { err.textContent = msg(k); err.hidden = false; }
  function stopCamera() {
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    video.srcObject = null;
  }
  function mode(taken) {
    video.hidden = taken; shot.hidden = !taken;
    snap.hidden = taken; retake.hidden = !taken; use.hidden = !taken;
    hint.hidden = taken;
  }
  function startCamera() {
    err.hidden = true;
    stopCamera();
    if (!window.isSecureContext) { showError("insecure"); return; }
    md.getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 1280 } }, audio: false })
      .then(function (s) {
        stream = s;
        video.srcObject = s;
        video.classList.toggle("is-mirrored", facing === "user");
        mode(false);
        return md.enumerateDevices();
      })
      .then(function (devices) {
        var cams = (devices || []).filter(function (d) { return d.kind === "videoinput"; });
        switchBtn.hidden = cams.length < 2;
      })
      .catch(function (e) {
        showError(e && (e.name === "NotAllowedError" || e.name === "SecurityError") ? "blocked" : "none");
      });
  }

  var bs = window.bootstrap;
  var dialog = bs ? bs.Modal.getOrCreateInstance(modal) : null;
  openBtn.addEventListener("click", function () { if (dialog) dialog.show(); });
  modal.addEventListener("shown.bs.modal", startCamera);
  modal.addEventListener("hidden.bs.modal", function () { stopCamera(); mode(false); });
  switchBtn.addEventListener("click", function () { facing = facing === "user" ? "environment" : "user"; startCamera(); });

  snap.addEventListener("click", function () {
    var w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) return;
    var side = Math.min(w, h), sx = (w - side) / 2, sy = (h - side) / 2;
    var ctx = shot.getContext("2d");
    ctx.drawImage(video, sx, sy, side, side, 0, 0, shot.width, shot.height);   // the true picture (not mirrored)
    mode(true);
  });
  retake.addEventListener("click", function () { mode(false); });
  use.addEventListener("click", function () {
    use.disabled = true;
    hint.hidden = false; hint.textContent = msg("saving");
    shot.toBlob(function (blob) {
      var fd = new FormData();
      fd.append("photo", blob, "photo.jpg");
      fetch(modal.getAttribute("data-upload-url"), {
        method: "POST", credentials: "same-origin", body: fd,
        headers: { "X-CSRFToken": modal.getAttribute("data-csrf"), "Accept": "application/json" }
      }).then(function (r) {
        if (!r.ok) throw new Error(r.status);
        stopCamera();
        window.location.reload();
      }).catch(function () { use.disabled = false; hint.hidden = true; showError("failed"); });
    }, "image/jpeg", 0.9);
  });
})();

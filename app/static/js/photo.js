/* Staff profile photo: take it with the camera (front or back), or choose a picture.
   External file (strict CSP). The camera is switched off as soon as the window closes. */
(function () {
  "use strict";
  var errorBox = document.querySelector("[data-photo-error]");

  /* Choosing a picture uploads it straight away */
  var form = document.querySelector("[data-photo-upload]");
  if (form) {
    form.querySelectorAll("[data-photo-file]").forEach(function (file) {
      file.addEventListener("change", function () {
        if (!file.files.length) return;
        if (file.files[0].size > 8 * 1024 * 1024) {
          if (errorBox) { errorBox.textContent = "8 MB max."; errorBox.hidden = false; }
          return;
        }
        // send only the picture that was just chosen (front, back or from the gallery)
        form.querySelectorAll("[data-photo-file]").forEach(function (o) { o.disabled = o !== file; });
        form.submit();
      });
    });
  }

  var modal = document.querySelector("[data-camera]");
  var openBtn = document.querySelector("[data-camera-open]");
  if (!modal || !openBtn) return;
  var md = navigator.mediaDevices;
  if (!md || !md.getUserMedia) return;     // no camera support here: "Upload photo" still opens the phone camera
  openBtn.hidden = false;

  var q = function (s) { return modal.querySelector(s); };
  var video = q("[data-camera-video]"), shot = q("[data-camera-shot]"), err = q("[data-camera-error]");
  var snap = q("[data-camera-snap]"), retake = q("[data-camera-retake]"), use = q("[data-camera-use]");
  var hint = q("[data-camera-hint]"), fallback = q("[data-camera-fallback]");
  var facingBtns = modal.querySelectorAll("[data-camera-facing]");
  var stream = null, facing = "user";

  function msg(k) { var el = modal.querySelector('[data-camera-msgs] [data-k="' + k + '"]'); return el ? el.textContent : k; }
  function showError(k) { err.textContent = msg(k); fallback.hidden = false; }
  function stopCamera() {
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    video.srcObject = null;
  }
  function mode(taken) {
    video.hidden = taken; shot.hidden = !taken;
    snap.hidden = taken; retake.hidden = !taken; use.hidden = !taken;
    hint.hidden = taken;
  }
  function markFacing() {
    facingBtns.forEach(function (b) {
      var on = b.getAttribute("data-camera-facing") === facing;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  function startCamera() {
    fallback.hidden = true;
    markFacing();
    stopCamera();
    if (!window.isSecureContext) { showError("insecure"); return; }
    md.getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 1280 } }, audio: false })
      .then(function (s) {
        stream = s;
        video.srcObject = s;
        video.classList.toggle("is-mirrored", facing === "user");
        mode(false);
      })
      .catch(function (e) {
        if (e && e.name === "OverconstrainedError" && facing === "environment") { facing = "user"; startCamera(); return; }
        showError(e && (e.name === "NotAllowedError" || e.name === "SecurityError") ? "blocked" : "none");
      });
  }

  var bs = window.bootstrap;
  var dialog = bs ? bs.Modal.getOrCreateInstance(modal) : null;
  openBtn.addEventListener("click", function () { if (dialog) dialog.show(); });
  modal.addEventListener("shown.bs.modal", startCamera);
  modal.addEventListener("hidden.bs.modal", function () { stopCamera(); mode(false); });
  facingBtns.forEach(function (b) {
    b.addEventListener("click", function () {
      var want = b.getAttribute("data-camera-facing");
      if (want === facing && stream) return;
      facing = want;
      startCamera();
    });
  });

  snap.addEventListener("click", function () {
    var w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) return;
    // passport proportions (7:9), centred like the oval on screen; the saved picture is not mirrored
    var ratio = shot.width / shot.height, cw = w, ch = w / ratio;
    if (ch > h) { ch = h; cw = h * ratio; }
    var sx = (w - cw) / 2, sy = (h - ch) / 2;
    var ctx = shot.getContext("2d");
    ctx.drawImage(video, sx, sy, cw, ch, 0, 0, shot.width, shot.height);
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

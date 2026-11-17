/* Live meeting notes: the browser's own speech recognition writes down what is said (Chrome, Edge, Safari),
   notes are kept on the server while they are taken, and "Draft the minutes" asks the server for a draft.
   External file (strict CSP). Nothing here records sound; the browser only hands over text. */
(function () {
  "use strict";
  var root = document.querySelector("[data-notes]");
  if (!root) return;

  var q = function (sel) { return root.querySelector(sel); };
  var text = q("[data-notes-text]"), interim = q("[data-notes-interim]"), status = q("[data-notes-status]");
  var startBtn = q("[data-notes-start]"), stopBtn = q("[data-notes-stop]"), consent = q("[data-notes-consent]");
  var langSel = q("[data-notes-lang]"), savedNote = q("[data-notes-saved]");
  var draftBtn = q("[data-notes-draft]"), draftBox = q("[data-notes-draft-box]"), draftText = q("[data-notes-draft-text]");
  var useBtn = q("[data-notes-use]");
  var csrf = root.getAttribute("data-csrf");

  function msg(key) {
    var el = root.querySelector('[data-notes-msgs] [data-k="' + key + '"]');
    return el ? el.textContent : key;
  }
  function setStatus(key, live) {
    status.textContent = key ? msg(key) : "";
    status.classList.toggle("is-live", !!live);
  }
  function post(url, body, keepalive) {
    return fetch(url, {
      method: "POST", credentials: "same-origin", keepalive: !!keepalive,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body)
    });
  }

  /* ---- keeping the notes on the server ---- */
  var dirty = false, saving = false;
  function save(keepalive) {
    if (!dirty || saving) return Promise.resolve();
    saving = true; dirty = false;
    savedNote.textContent = msg("saving");
    return post(root.getAttribute("data-save-url"), { transcript: text.value }, keepalive).then(function (r) {
      saving = false;
      if (!r.ok) throw new Error(r.status);
      savedNote.textContent = msg("saved");
    }).catch(function () { saving = false; dirty = true; savedNote.textContent = msg("offline"); });
  }
  text.addEventListener("input", function () { dirty = true; });
  setInterval(function () { save(false); }, 20000);
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden") save(true); });
  window.addEventListener("pagehide", function () { save(true); });

  /* ---- listening ---- */
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  var rec = null, listening = false, wake = null;

  function stamp() {
    var d = new Date();
    return "[" + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0") + "] ";
  }
  function addLine(line) {
    line = line.trim();
    if (!line) return;
    line = line.charAt(0).toUpperCase() + line.slice(1);
    var v = text.value;
    text.value = v + (v && !/\n$/.test(v) ? "\n" : "") + stamp() + line;
    text.scrollTop = text.scrollHeight;
    dirty = true;
  }
  function keepAwake(on) {
    try {
      if (on && navigator.wakeLock && !wake) {
        navigator.wakeLock.request("screen").then(function (w) { wake = w; }).catch(function () {});
      } else if (!on && wake) { wake.release(); wake = null; }
    } catch (e) { /* not available: fine */ }
  }
  function showButtons() {
    startBtn.hidden = listening;
    stopBtn.hidden = !listening;
    startBtn.disabled = !consent.checked || !SR;
    langSel.disabled = listening;
  }

  if (!SR) {
    q("[data-notes-unsupported]").hidden = false;
    startBtn.disabled = true;
  }
  consent.addEventListener("change", showButtons);

  function start() {
    if (!SR || !consent.checked) return;
    rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = langSel.value;
    rec.onresult = function (e) {
      var partial = "";
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var r = e.results[i];
        if (r.isFinal) addLine(r[0].transcript); else partial += r[0].transcript;
      }
      interim.textContent = partial;
    };
    rec.onerror = function (e) {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") { listening = false; setStatus("blocked"); }
      else if (e.error === "audio-capture") { listening = false; setStatus("nomic"); }
      showButtons();
    };
    rec.onend = function () {
      interim.textContent = "";
      // browsers stop after a silence or about a minute: carry on while the person has not paused
      if (listening) { try { rec.start(); } catch (err) { setTimeout(function () { if (listening) start(); }, 400); } }
      else { keepAwake(false); }
    };
    try { rec.start(); } catch (err) { return; }
    listening = true;
    setStatus("listening", true);
    keepAwake(true);
    showButtons();
  }
  function stop() {
    listening = false;
    if (rec) { try { rec.stop(); } catch (e) { /* already stopped */ } }
    setStatus("paused");
    keepAwake(false);
    showButtons();
    save(false);
  }
  startBtn.addEventListener("click", start);
  stopBtn.addEventListener("click", stop);
  showButtons();

  /* ---- drafting the minutes ---- */
  draftBtn.addEventListener("click", function () {
    if (!text.value.trim()) { setStatus("empty"); return; }
    draftBtn.disabled = true;
    setStatus("drafting");
    post(root.getAttribute("data-draft-url"), { transcript: text.value }).then(function (r) {
      return r.json().then(function (data) { return { ok: r.ok, data: data }; });
    }).then(function (res) {
      draftBtn.disabled = false;
      if (!res.ok || !res.data.draft) { setStatus(res.data && res.data.error === "empty" ? "empty" : "failed"); return; }
      dirty = false;
      draftText.textContent = res.data.draft;
      draftBox.hidden = false;
      status.textContent = msg("ready") + " " + msg(res.data.source === "ai" ? "ai" : "rules");
      draftBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }).catch(function () { draftBtn.disabled = false; setStatus("failed"); });
  });
  useBtn.addEventListener("click", function () {
    var box = document.querySelector('#minutes textarea[name="minutes"]');
    if (!box) return;
    box.value = draftText.textContent;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.scrollIntoView({ behavior: "smooth", block: "center" });
    box.focus({ preventScroll: true });
  });
})();

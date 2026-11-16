/* ZENTAVA Assistant window. External file (strict CSP). Answers are added as text, never as HTML. */
(function () {
  "use strict";
  var root = document.querySelector("[data-assistant]");
  if (!root) return;
  var html = document.documentElement;
  var fab = root.querySelector(".assist-fab");
  var panel = root.querySelector(".assist-panel");
  var log = root.querySelector(".assist-log");
  var form = root.querySelector(".assist-form");
  var input = root.querySelector("#assist-q");
  var phone = window.matchMedia("(max-width: 760px)");
  var WORDS = {
    fr: {
      "Thinking…": "Je réfléchis…",
      "Sorry, the assistant could not answer. Please try again.": "Désolé, l'assistant n'a pas pu répondre. Réessayez.",
      "Too many questions just now. Please wait a minute.": "Trop de questions pour l'instant. Patientez une minute.",
      "From the help guide": "D'après le guide d'aide"
    }
  };
  function t(s) { var d = WORDS[html.getAttribute("lang")]; return (d && d[s]) || s; }

  function open() {
    panel.hidden = false;
    fab.setAttribute("aria-expanded", "true");
    root.classList.add("is-open");
    // Do not pop the keyboard up on phones; on larger screens go straight to the question box
    if (!phone.matches) input.focus();
    log.scrollTop = log.scrollHeight;
  }
  function close() {
    panel.hidden = true;
    fab.setAttribute("aria-expanded", "false");
    root.classList.remove("is-open", "typing");
    fab.focus();
  }
  fab.addEventListener("click", function () { panel.hidden ? open() : close(); });
  root.querySelector(".assist-close").addEventListener("click", close);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) close(); });

  function add(kind, text, links, note) {
    var msg = document.createElement("div");
    msg.className = "assist-msg " + kind;
    String(text).split(/\n{2,}/).forEach(function (para) {
      var p = document.createElement("p");
      p.textContent = para;
      msg.appendChild(p);
    });
    if (links && links.length) {
      var row = document.createElement("div");
      row.className = "assist-links";
      links.forEach(function (l) {
        if (typeof l.url !== "string" || l.url.charAt(0) !== "/" || l.url.charAt(1) === "/") return;  // same site only
        var a = document.createElement("a");
        a.href = l.url;
        a.textContent = l.label;
        a.className = "assist-link";
        row.appendChild(a);
      });
      msg.appendChild(row);
    }
    if (note) {
      var n = document.createElement("p");
      n.className = "assist-source";
      n.textContent = note;
      msg.appendChild(n);
    }
    log.appendChild(msg);
    log.scrollTop = log.scrollHeight;
    return msg;
  }

  var busy = false;
  function ask(question) {
    question = (question || "").trim();
    if (!question || busy) return;
    busy = true;
    add("me", question);
    var wait = add("bot pending", t("Thinking…"));
    fetch(root.getAttribute("data-ask-url"), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": root.getAttribute("data-csrf") },
      body: JSON.stringify({ question: question })
    }).then(function (r) {
      if (r.status === 429) throw new Error("busy");
      if (!r.ok) throw new Error("failed");
      return r.json();
    }).then(function (data) {
      wait.remove();
      add("bot", data.answer, data.links, data.source === "guide" ? t("From the help guide") : null);
    }).catch(function (e) {
      wait.remove();
      add("bot error", e.message === "busy" ? t("Too many questions just now. Please wait a minute.")
                                            : t("Sorry, the assistant could not answer. Please try again."));
    }).then(function () { busy = false; });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = input.value;
    input.value = "";
    ask(q);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });
  root.querySelectorAll(".assist-chip").forEach(function (b) {
    b.addEventListener("click", function () { ask(b.textContent); });
  });

  // Phones: while typing, the window fills the space above the keyboard and hides the suggestions and note
  function fit() {
    if (!phone.matches || !window.visualViewport) return;
    var vv = window.visualViewport;
    root.style.setProperty("--assist-vh", Math.round(vv.height) + "px");
    root.style.setProperty("--assist-top", Math.round(vv.offsetTop) + "px");
  }
  input.addEventListener("focus", function () { if (phone.matches) { root.classList.add("typing"); fit(); } });
  input.addEventListener("blur", function () { root.classList.remove("typing"); });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", fit);
    window.visualViewport.addEventListener("scroll", fit);
  }
})();

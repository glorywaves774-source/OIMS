/* ZENTAVA client behaviour. Loaded as an external file (strict CSP, no inline scripts). */
(function () {
  "use strict";
  var html = document.documentElement;

  /* ---------- Words written by this script (the server translates the page itself) ---------- */
  var WORDS = {
    fr: { "Light mode": "Mode clair", "Dark mode": "Mode sombre", "Confirm": "Confirmer", "Copied": "Copié" }
  };
  function t(text) {
    var d = WORDS[html.getAttribute("lang")];
    return (d && d[text]) || text;
  }

  /* ---------- Theme ---------- */
  function setTheme(mode, persist) {
    html.setAttribute("data-theme", mode);
    html.setAttribute("data-bs-theme", mode);
    if (persist) {
      try { localStorage.setItem("oims-theme", mode); } catch (e) {}
      document.cookie = "oims-theme=" + mode + "; path=/; max-age=31536000; SameSite=Lax";
    }
    document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
      var dark = mode === "dark";
      b.setAttribute("aria-pressed", dark ? "true" : "false");
      var label = t(dark ? "Light mode" : "Dark mode");
      b.setAttribute("title", label);
      b.setAttribute("aria-label", label);
      var icon = b.querySelector("i");
      if (icon) icon.className = dark ? "bi bi-sun" : "bi bi-moon-stars";
      var txt = b.querySelector("[data-theme-label]");
      if (txt) txt.textContent = label;
    });
  }
  setTheme(html.getAttribute("data-theme") || "light", false);
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-theme-toggle]");
    if (!b) return;
    setTheme(html.getAttribute("data-theme") === "dark" ? "light" : "dark", true);
  });
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    var follow = function (ev) {
      var chosen = null;
      try { chosen = localStorage.getItem("oims-theme"); } catch (e) {}
      if (!chosen) setTheme(ev.matches ? "dark" : "light", false);
    };
    if (mq.addEventListener) mq.addEventListener("change", follow);
  }

  /* ---------- Sidebar: collapsible on desktop, drawer on phones ---------- */
  var sidebar = document.getElementById("sidebar");
  var scrim = document.getElementById("scrim");
  var openBtn = document.getElementById("menu-open");
  var closeBtn = document.getElementById("menu-close");
  var drawerOpen = false;
  var pendingHref = null;
  var isPhone = function () { return window.matchMedia("(max-width: 760px)").matches; };

  function openDrawer() {
    if (!sidebar || drawerOpen) return;
    drawerOpen = true;
    html.classList.add("drawer-open");
    sidebar.setAttribute("aria-hidden", "false");
    if (openBtn) openBtn.setAttribute("aria-expanded", "true");
    history.pushState({ oimsDrawer: true }, "");
    var f = document.getElementById("nav-filter");
    if (f && !isPhone()) f.focus();
  }
  function closeDrawer(fromPop) {
    if (!drawerOpen) return;
    drawerOpen = false;
    html.classList.remove("drawer-open");
    if (isPhone()) sidebar.setAttribute("aria-hidden", "true");
    if (openBtn) { openBtn.setAttribute("aria-expanded", "false"); }
    if (!fromPop && history.state && history.state.oimsDrawer) history.back();
  }
  window.addEventListener("popstate", function () {
    if (drawerOpen) closeDrawer(true);
    if (pendingHref) { var h = pendingHref; pendingHref = null; window.location.href = h; }
  });
  if (openBtn) openBtn.addEventListener("click", openDrawer);
  document.querySelectorAll("[data-open-menu]").forEach(function (b) { b.addEventListener("click", openDrawer); });
  if (closeBtn) closeBtn.addEventListener("click", function () { closeDrawer(false); });
  if (scrim) scrim.addEventListener("click", function () { closeDrawer(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(false); });
  if (sidebar) {
    if (isPhone()) sidebar.setAttribute("aria-hidden", "true");
    sidebar.addEventListener("click", function (e) {
      var a = e.target.closest("a[href]");
      if (!a || !drawerOpen || !isPhone()) return;
      /* Leave the drawer's history entry first so the new page needs no extra Back. */
      e.preventDefault();
      pendingHref = a.href;
      drawerOpen = false;
      html.classList.remove("drawer-open");
      history.back();
    });
  }
  var collapseBtn = document.getElementById("sidebar-collapse");
  if (collapseBtn) collapseBtn.addEventListener("click", function () {
    var compact = html.classList.toggle("sidebar-compact");
    try { localStorage.setItem("oims-sidebar", compact ? "compact" : "full"); } catch (e) {}
    collapseBtn.setAttribute("aria-pressed", compact ? "true" : "false");
  });

  /* ---------- Menu filter (accent-insensitive) ---------- */
  var fold = function (s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };
  var filter = document.getElementById("nav-filter");
  if (filter) filter.addEventListener("input", function () {
    var q = fold(filter.value.trim());
    document.querySelectorAll(".nav-group").forEach(function (group) {
      var any = false;
      group.querySelectorAll(".nav-link-item").forEach(function (li) {
        var hit = !q || fold(li.textContent).indexOf(q) !== -1;
        li.hidden = !hit;
        if (hit) any = true;
      });
      group.hidden = !any;
    });
  });

  /* ---------- Back button inside installed apps only ---------- */
  var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
  if (standalone) {
    html.classList.add("is-standalone");
    var back = document.getElementById("app-back");
    if (back) back.addEventListener("click", function () { history.back(); });
  }

  /* ---------- Confirmation dialogs ---------- */
  var modalEl = document.getElementById("confirm-modal");
  var confirmTarget = null;
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches("[data-confirm]") || form.dataset.confirmed === "1") return;
    e.preventDefault();
    confirmTarget = form;
    if (modalEl && window.bootstrap) {
      modalEl.querySelector("[data-confirm-text]").textContent = form.getAttribute("data-confirm");
      var ok = modalEl.querySelector("[data-confirm-ok]");
      ok.className = "btn " + (form.getAttribute("data-confirm-variant") || "btn-primary");
      ok.textContent = form.getAttribute("data-confirm-label") || t("Confirm");
      window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
    } else if (window.confirm(form.getAttribute("data-confirm"))) {
      form.dataset.confirmed = "1"; form.requestSubmit();
    }
  });
  if (modalEl) modalEl.querySelector("[data-confirm-ok]").addEventListener("click", function () {
    if (!confirmTarget) return;
    confirmTarget.dataset.confirmed = "1";
    window.bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    confirmTarget.requestSubmit();
  });

  /* ---------- Copy buttons ---------- */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-copy]");
    if (!b) return;
    var src = document.getElementById(b.getAttribute("data-copy"));
    if (!src || !navigator.clipboard) return;
    navigator.clipboard.writeText(src.value || src.textContent).then(function () {
      var old = b.textContent; b.textContent = t("Copied"); setTimeout(function () { b.textContent = old; }, 1500);
    });
  });

  /* ---------- Loading state on submit ---------- */
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var btn = e.target.querySelector("button[type=submit][data-loading]");
    if (btn) { btn.disabled = true; btn.classList.add("is-loading"); }
  });

  /* ---------- Auto-submit selects (filters) ---------- */
  document.querySelectorAll("select[data-autosubmit]").forEach(function (s) {
    s.addEventListener("change", function () { s.form.submit(); });
  });
})();

/* Filter boxes for checkbox lists */
(function () {
  var fold = function (s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); };
  document.querySelectorAll("[data-filter-for]").forEach(function (input) {
    var box = document.getElementById(input.getAttribute("data-filter-for"));
    if (!box) return;
    input.addEventListener("input", function () {
      var q = fold(input.value.trim());
      box.querySelectorAll(".checklist-item").forEach(function (it) {
        it.hidden = q && fold(it.textContent).indexOf(q) === -1;
      });
    });
  });
  /* Print buttons */
  document.querySelectorAll("[data-print]").forEach(function (b) {
    b.addEventListener("click", function () { window.print(); });
  });
  /* Scroll conversation to the latest message */
  var latest = document.getElementById("latest");
  if (latest && latest.scrollIntoView) latest.scrollIntoView({ block: "end" });
})();

// Chart tooltips: every bar and column shows its label and value on hover and on keyboard focus.
(function () {
  var tip = null;
  function show(el) {
    var text = el.getAttribute("data-tip");
    if (!text) return;
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tip";
      tip.setAttribute("role", "status");
      document.body.appendChild(tip);
    }
    tip.textContent = text;
    tip.hidden = false;
    var r = el.getBoundingClientRect();
    var x = Math.min(window.innerWidth - tip.offsetWidth - 8, Math.max(8, r.left + r.width / 2 - tip.offsetWidth / 2));
    var y = r.top - tip.offsetHeight - 8;
    if (y < 8) y = r.bottom + 8;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function hide() { if (tip) tip.hidden = true; }
  document.addEventListener("pointerover", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (el) show(el);
  });
  document.addEventListener("pointerout", function (e) {
    if (e.target.closest && e.target.closest("[data-tip]")) hide();
  });
  document.addEventListener("focusin", function (e) {
    var el = e.target.closest && e.target.closest("[data-tip]");
    if (el) show(el); else hide();
  });
  window.addEventListener("scroll", hide, { passive: true });
})();

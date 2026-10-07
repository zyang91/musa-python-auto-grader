/* MUSA Grader documentation: theme, navigation, search, copy buttons, scrollspy. */
(function () {
  "use strict";

  var root = document.documentElement;
  var base = document.body.getAttribute("data-root") || "";

  // ---- Theme -------------------------------------------------------------
  function currentTheme() {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function syncHighlightTheme() {
    var theme = currentTheme();
    var light = document.getElementById("hljs-light");
    var dark = document.getElementById("hljs-dark");
    if (light && dark) {
      light.media = theme === "light" ? "all" : "not all";
      dark.media = theme === "dark" ? "all" : "not all";
    }
  }
  syncHighlightTheme();
  var toggle = document.querySelector(".theme-toggle");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("musa-docs-theme", next); } catch (e) {}
      syncHighlightTheme();
    });
  }

  // ---- Mobile navigation -------------------------------------------------
  var menu = document.querySelector(".menu-button");
  var scrim = document.querySelector(".sidebar-scrim");
  function setNav(open) {
    document.body.classList.toggle("nav-open", open);
    if (menu) menu.setAttribute("aria-expanded", open ? "true" : "false");
    if (scrim) scrim.hidden = !open;
  }
  if (menu) menu.addEventListener("click", function () { setNav(!document.body.classList.contains("nav-open")); });
  if (scrim) scrim.addEventListener("click", function () { setNav(false); });

  var sidebarEl = document.querySelector(".sidebar");
  var active = document.querySelector(".sidebar a.active");
  if (sidebarEl && active) {
    var top = active.offsetTop - sidebarEl.offsetTop;
    if (top > sidebarEl.clientHeight - 80) sidebarEl.scrollTop = top - sidebarEl.clientHeight / 2;
  }

  // ---- Code blocks: highlighting and copy --------------------------------
  document.querySelectorAll("pre > code").forEach(function (code) {
    if (window.hljs && !code.closest(".doc-literal")) {
      try { window.hljs.highlightElement(code); } catch (e) {}
    }
    var pre = code.parentElement;
    var button = document.createElement("button");
    button.type = "button";
    button.className = "copy-button";
    button.textContent = "Copy";
    button.addEventListener("click", function () {
      var text = code.innerText.replace(/\n$/, "");
      var done = function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy"; }, 1400);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
    });
    pre.appendChild(button);
  });

  // ---- Table of contents scrollspy ---------------------------------------
  var tocLinks = Array.prototype.slice.call(document.querySelectorAll(".toc a"));
  if (tocLinks.length && "IntersectionObserver" in window) {
    var targets = tocLinks.map(function (a) {
      return document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)));
    });
    var visible = new Set();
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) visible.add(entry.target); else visible.delete(entry.target);
      });
      var index = -1;
      for (var i = 0; i < targets.length; i++) {
        if (targets[i] && visible.has(targets[i])) { index = i; break; }
      }
      if (index >= 0) tocLinks.forEach(function (a, i) { a.classList.toggle("active", i === index); });
    }, { rootMargin: "-70px 0px -65% 0px" });
    targets.forEach(function (t) { if (t) observer.observe(t); });
  }

  // ---- Search ------------------------------------------------------------
  var dialog = document.querySelector(".search-dialog");
  var input = dialog && dialog.querySelector("input");
  var list = dialog && dialog.querySelector(".search-results");
  var hint = dialog && dialog.querySelector(".search-hint");
  var index = window.MUSA_SEARCH_INDEX || [];
  var selected = 0;

  function openSearch() {
    if (!dialog) return;
    dialog.hidden = false;
    input.value = "";
    render("");
    setTimeout(function () { input.focus(); }, 0);
  }
  function closeSearch() { if (dialog) dialog.hidden = true; }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function highlight(text, terms) {
    var out = escapeHtml(text);
    terms.forEach(function (t) {
      if (!t) return;
      out = out.replace(new RegExp("(" + t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
    });
    return out;
  }
  var kindWeight = { page: 6, module: 5, "class": 5, section: 4, "function": 4, method: 3, property: 3, classmethod: 3, staticmethod: 3, constant: 2 };

  function score(entry, terms, query) {
    var title = entry.t.toLowerCase();
    var hay = (entry.t + " " + (entry.s || "") + " " + (entry.d || "")).toLowerCase();
    var total = 0;
    for (var i = 0; i < terms.length; i++) {
      var t = terms[i];
      if (hay.indexOf(t) === -1) return 0;
      if (title === t) total += 40;
      else if (title.indexOf(t) === 0) total += 24;
      else if (title.indexOf(t) !== -1) total += 14;
      else total += 3;
    }
    if (title === query) total += 30;
    return total + (kindWeight[entry.k] || 1);
  }

  function render(query) {
    query = query.trim().toLowerCase();
    selected = 0;
    if (!query) {
      list.innerHTML = "";
      hint.textContent = "Type to search pages, sections, classes and functions.";
      return;
    }
    var terms = query.split(/\s+/);
    var results = index
      .map(function (e) { return { e: e, s: score(e, terms, query) }; })
      .filter(function (r) { return r.s > 0; })
      .sort(function (a, b) { return b.s - a.s; })
      .slice(0, 30);
    hint.textContent = results.length ? results.length + (results.length === 30 ? "+" : "") + " results · ↑↓ to move, Enter to open" : "No results for “" + query + "”.";
    list.innerHTML = results.map(function (r, i) {
      var e = r.e;
      return '<li role="option" aria-selected="' + (i === 0) + '"><a href="' + base + e.u + '">' +
        '<span class="r-title"><span>' + highlight(e.t, terms) + '</span><span class="r-kind">' + escapeHtml(e.k) + "</span>" +
        '<span class="r-where">' + escapeHtml(e.s || "") + "</span></span>" +
        (e.d ? '<span class="r-desc">' + highlight(e.d, terms) + "</span>" : "") +
        "</a></li>";
    }).join("");
  }

  function move(delta) {
    var items = list.querySelectorAll("li");
    if (!items.length) return;
    items[selected].setAttribute("aria-selected", "false");
    selected = (selected + delta + items.length) % items.length;
    items[selected].setAttribute("aria-selected", "true");
    items[selected].scrollIntoView({ block: "nearest" });
  }

  if (dialog) {
    document.querySelector(".search-trigger").addEventListener("click", openSearch);
    input.addEventListener("input", function () { render(input.value); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); move(-1); }
      else if (event.key === "Enter") {
        var link = list.querySelectorAll("li a")[selected];
        if (link) { closeSearch(); window.location.href = link.href; }
      }
    });
    list.addEventListener("click", function (event) { if (event.target.closest("a")) closeSearch(); });
    dialog.addEventListener("click", function (event) { if (event.target === dialog) closeSearch(); });
  }

  document.addEventListener("keydown", function (event) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (event.key === "Escape") { closeSearch(); setNav(false); }
    else if (!typing && (event.key === "/" || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k"))) {
      event.preventDefault();
      openSearch();
    }
  });
})();

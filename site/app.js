// Search, language filter and sort for the film tables, plus the report form.
// The pages work without this script; it only narrows and reorders what's shown.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var q = $("q"), sort = $("sort"), clear = $("clear"), count = $("count"), none = $("none");
  var sections = Array.prototype.slice.call(document.querySelectorAll("section.lang"));
  var toggles = Array.prototype.slice.call(document.querySelectorAll("[data-filter]"));
  var lang = "";

  function sortRows() {
    if (!sort) return;
    var how = sort.value;
    document.querySelectorAll("tbody").forEach(function (tb) {
      var rows = Array.prototype.slice.call(tb.children);
      rows.sort(function (a, b) {
        if (how === "title") return a.dataset.title.localeCompare(b.dataset.title);
        var d = (+a.dataset.year) - (+b.dataset.year);
        return how === "year-asc" ? d : -d;
      });
      rows.forEach(function (r) { tb.appendChild(r); });
    });
  }

  function apply() {
    var words = (q ? q.value : "").toLowerCase().trim().split(/\s+/).filter(Boolean);
    var shown = 0, announced = 0;
    sections.forEach(function (sec) {
      var langOk = !lang || sec.dataset.lang === lang;
      var hits = 0;
      sec.querySelectorAll("tbody tr").forEach(function (tr) {
        var text = tr.dataset.search || "";
        var ok = langOk && words.every(function (w) { return text.indexOf(w) !== -1; });
        tr.hidden = !ok;
        if (ok && !tr.closest("details")) hits++;     // count confirmed films only, like the bar
      });
      var maybe = sec.querySelector("details.maybe");
      var maybeHits = maybe ? maybe.querySelectorAll("tbody tr:not([hidden])").length : 0;
      if (maybe && words.length) maybe.open = maybeHits > 0;
      sec.hidden = !langOk || (words.length > 0 && hits === 0 && maybeHits === 0);
      shown += hits;
      announced += maybeHits;
    });
    var filtered = words.length || lang;
    var text = shown + (shown === 1 ? " film" : " films");
    if (announced) text += ", plus " + announced + " announced but not confirmed";
    if (count) count.textContent = filtered ? text : "";
    if (clear) clear.hidden = !filtered;
    if (none) none.hidden = shown + announced > 0;
  }

  if (q) q.addEventListener("input", apply);
  if (sort) sort.addEventListener("change", sortRows);
  toggles.forEach(function (btn) {
    btn.addEventListener("click", function () {
      lang = lang === btn.dataset.filter ? "" : btn.dataset.filter;
      toggles.forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.filter === lang)); });
      apply();
    });
  });
  if (clear) clear.addEventListener("click", function () {
    lang = "";
    if (q) q.value = "";
    toggles.forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
    apply();
  });

  // Report form: prefill from "Report a problem" links, send without leaving the page.
  var form = $("report");
  if (!form) return;
  var params = new URLSearchParams(location.search);
  if (params.get("film")) {
    form.film.value = params.get("film");
    form.year.value = params.get("year") || "";
    var wrong = form.querySelector('input[value="Wrong details"]');
    if (wrong) wrong.checked = true;
  }
  var status = $("status");
  form.addEventListener("submit", function (ev) {
    if (!form.getAttribute("action")) {
      ev.preventDefault();
      status.textContent = "The form isn't connected yet. Please try again later.";
      return;
    }
    if (!window.fetch) return;
    ev.preventDefault();
    status.textContent = "Sending…";
    fetch(form.action, { method: "POST", body: new FormData(form), headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          if (!r.ok) {
            var msg = body.errors && body.errors.length ? body.errors.map(function (x) { return x.message; }).join(" ") : "";
            throw new Error(msg);
          }
          form.reset();
          status.textContent = "Thanks. Your report was sent and will be checked against a source.";
        });
      })
      .catch(function (err) {
        status.textContent = err.message
          ? "The report didn't send: " + err.message
          : "The report didn't send. Check your connection and try again.";
      });
  });
})();

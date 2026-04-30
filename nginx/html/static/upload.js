// Upload + list + delete UI for /kb/* endpoints. Server validates JWT on every
// request; this layer only handles UX.
(function () {
  "use strict";

  var MAX_BYTES = 25 * 1024 * 1024;
  var ALLOWED_EXT = ["pdf", "docx", "txt", "md", "markdown", "html", "htm"];

  var dz       = document.getElementById("dropzone");
  var fileIn   = document.getElementById("file");
  var status   = document.getElementById("upload-status");
  var listEl   = document.getElementById("doc-list");
  var emptyEl  = document.getElementById("doc-empty");

  function setStatus(msg, kind) {
    if (!msg) { status.hidden = true; status.textContent = ""; return; }
    status.hidden = false;
    status.textContent = msg;
    status.className = kind === "ok" ? "form-ok" : "form-error";
  }

  function humanBytes(n) {
    if (n == null) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    try {
      var d = new Date(iso);
      return d.toLocaleString("ro-RO", { dateStyle: "short", timeStyle: "short" });
    } catch (_) { return iso; }
  }

  function extOf(name) {
    var dot = name.lastIndexOf(".");
    return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
  }

  // ─── List ──────────────────────────────────────────────────────────────────

  function refreshList() {
    fetch("/kb/documents", { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { window.location.assign("/login"); return null; }
      return r.json();
    }).then(function (body) {
      if (!body) return;
      renderList(body.documents || []);
    }).catch(function () {
      listEl.innerHTML = "";
      var p = document.createElement("p");
      p.className = "form-error";
      p.textContent = "Nu am putut încărca lista de documente.";
      listEl.appendChild(p);
    });
  }

  function renderList(docs) {
    listEl.innerHTML = "";
    if (!docs.length) {
      var p = document.createElement("p");
      p.className = "muted";
      p.textContent = "Niciun document încă. Încarcă primul fișier mai sus.";
      listEl.appendChild(p);
      return;
    }
    var table = document.createElement("table");
    table.className = "doc-table";
    var thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Fișier</th><th>Mărime</th><th>Bucăți</th><th>Încărcat</th><th></th></tr>";
    table.appendChild(thead);
    var tbody = document.createElement("tbody");
    docs.forEach(function (d) {
      var tr = document.createElement("tr");
      tr.appendChild(cell(d.filename || "—"));
      tr.appendChild(cell(humanBytes(d.size_bytes)));
      tr.appendChild(cell(String(d.chunk_count || 0)));
      tr.appendChild(cell(fmtDate(d.uploaded_at)));
      var tdBtn = document.createElement("td");
      var btn = document.createElement("button");
      btn.className = "btn btn-danger";
      btn.type = "button";
      btn.textContent = "Șterge";
      btn.addEventListener("click", function () { confirmDelete(d); });
      tdBtn.appendChild(btn);
      tr.appendChild(tdBtn);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    listEl.appendChild(table);
  }

  function cell(text) {
    var td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  // ─── Delete ────────────────────────────────────────────────────────────────

  function confirmDelete(doc) {
    var name = doc.filename || doc.doc_id;
    if (!window.confirm("Sigur ștergi „" + name + "”?")) return;
    fetch("/kb/documents/" + encodeURIComponent(doc.doc_id), {
      method: "DELETE",
      credentials: "same-origin",
    }).then(function (r) {
      if (r.status === 401) { window.location.assign("/login"); return; }
      if (!r.ok) {
        setStatus("Ștergerea a eșuat.", "err");
        return;
      }
      setStatus("Document șters.", "ok");
      refreshList();
    }).catch(function () {
      setStatus("Eroare de rețea la ștergere.", "err");
    });
  }

  // ─── Upload ────────────────────────────────────────────────────────────────

  function handleFile(file) {
    setStatus(null);
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setStatus("Fișier prea mare. Maxim 25 MB.", "err");
      return;
    }
    var ext = extOf(file.name);
    if (ALLOWED_EXT.indexOf(ext) === -1) {
      setStatus("Tip de fișier nepermis. Acceptăm: " + ALLOWED_EXT.join(", ") + ".", "err");
      return;
    }

    dz.classList.add("dz-busy");
    setStatus("Se încarcă „" + file.name + "”…", "ok");

    var fd = new FormData();
    fd.append("file", file, file.name);

    fetch("/kb/upload", {
      method: "POST",
      credentials: "same-origin",
      body: fd,
    }).then(function (r) {
      return r.json().then(function (body) { return { status: r.status, body: body }; });
    }).then(function (res) {
      if (res.status === 401) { window.location.assign("/login"); return; }
      if (res.status === 200) {
        setStatus("Încărcat: „" + (res.body.filename || file.name) + "” (" + (res.body.chunks || 0) + " bucăți).", "ok");
        refreshList();
        return;
      }
      var msg = (res.body && res.body.detail) || "Încărcare eșuată.";
      if (res.status === 413) msg = "Fișier prea mare. Maxim 25 MB.";
      if (res.status === 415) msg = "Tip de fișier nepermis.";
      if (res.status === 422) msg = "Nu s-a putut extrage text din fișier.";
      setStatus(msg, "err");
    }).catch(function () {
      setStatus("Eroare de rețea la încărcare.", "err");
    }).finally(function () {
      dz.classList.remove("dz-busy");
      fileIn.value = "";
    });
  }

  // ─── Wire-up ───────────────────────────────────────────────────────────────

  dz.addEventListener("click", function () { fileIn.click(); });
  dz.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fileIn.click(); }
  });

  ["dragenter", "dragover"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) {
      e.preventDefault(); e.stopPropagation();
      dz.classList.add("dz-hover");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dz.addEventListener(ev, function (e) {
      e.preventDefault(); e.stopPropagation();
      dz.classList.remove("dz-hover");
    });
  });
  dz.addEventListener("drop", function (e) {
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files[0]) handleFile(files[0]);
  });
  fileIn.addEventListener("change", function () {
    if (fileIn.files && fileIn.files[0]) handleFile(fileIn.files[0]);
  });

  refreshList();
})();

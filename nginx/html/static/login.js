// Client-side validation + submit. Server re-validates everything;
// this layer is just for fast feedback.
(function () {
  "use strict";

  var EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;
  var PASSWORD_MIN = 8;
  var PASSWORD_MAX = 256;

  var form  = document.getElementById("login-form");
  var email = document.getElementById("email");
  var pwd   = document.getElementById("password");
  var btn   = document.getElementById("submit");
  var errEmail = document.getElementById("err-email");
  var errPwd   = document.getElementById("err-password");
  var errForm  = document.getElementById("form-error");

  function setFieldError(input, p, msg) {
    if (msg) {
      input.setAttribute("aria-invalid", "true");
      p.textContent = msg;
      p.hidden = false;
    } else {
      input.removeAttribute("aria-invalid");
      p.hidden = true;
      p.textContent = "";
    }
  }

  function setFormError(msg) {
    if (msg) { errForm.textContent = msg; errForm.hidden = false; }
    else     { errForm.hidden = true; errForm.textContent = ""; }
  }

  function hasControlChars(s) {
    // reject NUL and ASCII control bytes (except tab is irrelevant for password)
    for (var i = 0; i < s.length; i++) {
      var code = s.charCodeAt(i);
      if (code === 0 || (code < 32 && code !== 9) || code === 127) return true;
    }
    return false;
  }

  function validate() {
    var ok = true;
    var e = email.value.trim().toLowerCase();
    var p = pwd.value;

    if (e.length < 3 || e.length > 254 || !EMAIL_RE.test(e)) {
      setFieldError(email, errEmail, "Adresa de e-mail nu este validă.");
      ok = false;
    } else {
      setFieldError(email, errEmail, null);
    }

    if (p.length < PASSWORD_MIN || p.length > PASSWORD_MAX) {
      setFieldError(pwd, errPwd, "Parola trebuie să aibă între " + PASSWORD_MIN + " și " + PASSWORD_MAX + " caractere.");
      ok = false;
    } else if (hasControlChars(p)) {
      setFieldError(pwd, errPwd, "Parola conține caractere nepermise.");
      ok = false;
    } else {
      setFieldError(pwd, errPwd, null);
    }

    return ok ? { email: e, password: p } : null;
  }

  email.addEventListener("blur", validate);
  pwd.addEventListener("blur", validate);

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    setFormError(null);
    var data = validate();
    if (!data) return;

    btn.disabled = true;
    var prevLabel = btn.textContent;
    btn.textContent = "Se autentifică…";

    fetch("/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json", "accept": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(data),
    }).then(function (r) {
      return r.json().then(function (body) { return { status: r.status, body: body }; });
    }).then(function (res) {
      if (res.status === 200 && res.body && res.body.redirect) {
        window.location.assign(res.body.redirect);
        return;
      }
      var msg = (res.body && res.body.detail) || "Autentificare eșuată.";
      if (res.status === 429) msg = "Prea multe încercări. Reîncercați mai târziu.";
      if (res.status === 401) msg = "E-mail sau parolă incorecte.";
      if (res.status === 400) msg = "Date invalide.";
      setFormError(msg);
    }).catch(function () {
      setFormError("Eroare de rețea. Reîncercați.");
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = prevLabel;
    });
  });
})();

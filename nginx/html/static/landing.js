// If a token cookie is already present, the user is signed in — change the CTA
// to take them straight to the chat instead of the login form.
(function () {
  "use strict";

  function hasToken() {
    return document.cookie.split(";").some(function (c) {
      return c.trim().indexOf("token=") === 0;
    });
  }

  if (hasToken()) {
    var cta = document.getElementById("cta-primary");
    if (cta) {
      cta.textContent = "Continuă la aplicație";
      cta.setAttribute("href", "/c/");
    }
  }
})();

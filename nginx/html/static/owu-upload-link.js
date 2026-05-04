// Re-parent the nginx-injected `.rag-upload-link` so it flows as a sibling
// directly below OWU's chat input form, instead of floating at a corner.
//
// OWU is a Svelte SPA: the chat input form is created during hydration and
// can be re-rendered on SPA navigation. A MutationObserver catches both
// cases. relocate() is idempotent — fast no-op if the link is already in
// place under the current form.
(function () {
  "use strict";

  function findChatForm() {
    // OWU 0.5.4: the chat input is the LAST textarea on the page (sidebar
    // search uses <input>, settings textareas only exist on admin screens).
    // Take the last one, walk up to its enclosing <form>.
    var textareas = document.querySelectorAll("textarea");
    for (var i = textareas.length - 1; i >= 0; i--) {
      var form = textareas[i].closest("form");
      if (form && form.parentNode) return form;
    }
    return null;
  }

  function relocate() {
    var link = document.querySelector(".rag-upload-link");
    if (!link) return false;
    var form = findChatForm();
    if (!form) return false;
    // Already in place — bail fast (this fires from MutationObserver a lot).
    if (link.previousElementSibling === form && link.parentNode === form.parentNode) {
      return true;
    }
    form.parentNode.insertBefore(link, form.nextSibling);
    link.classList.add("rag-upload-link--inline");
    return true;
  }

  // Initial attempt — form may already exist if hydration completed before us.
  relocate();

  // Watch for the form to appear / be re-rendered. Subtree because Svelte
  // mounts components deep in the body. Throttle the relocate calls so we
  // don't trigger a relocation storm during heavy DOM activity (token streams).
  var pending = false;
  var obs = new MutationObserver(function () {
    if (pending) return;
    pending = true;
    setTimeout(function () { pending = false; relocate(); }, 100);
  });
  obs.observe(document.body, { childList: true, subtree: true });
})();

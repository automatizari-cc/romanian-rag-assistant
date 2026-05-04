// Re-parent the nginx-injected `.rag-upload-link` so it flows as a sibling
// directly below OWU's chat input form, rather than floating at a corner.
//
// OWU is a Svelte SPA: the chat input form may be (re)rendered after our
// initial DOM scan, and SPA navigation can swap it out. A MutationObserver
// catches both cases. relocate() is idempotent — early-returns if the link
// is already in place under the current form.
(function () {
  "use strict";

  function findChatForm() {
    // OWU 0.5.4's chat input lives in a form with classes
    // "w-full flex gap-1.5" wrapping a textarea. CSS class selectors with
    // dots-in-names need escaping; querySelector on the textarea + closest()
    // is more robust to OWU class shuffles across versions.
    var ta = document.querySelector("textarea");
    return ta && ta.closest("form");
  }

  function relocate() {
    var link = document.querySelector(".rag-upload-link");
    if (!link) return;
    var form = findChatForm();
    if (!form || !form.parentNode) return;
    // Already in place — bail out fast (this fires from MutationObserver a lot).
    if (link.previousElementSibling === form) return;
    form.parentNode.insertBefore(link, form.nextSibling);
    link.classList.add("rag-upload-link--inline");
  }

  // Initial attempt — form may already exist if hydration completed before we ran.
  relocate();

  // Watch for the form to appear / be re-rendered. Subtree because Svelte
  // mounts components deep in the body.
  var obs = new MutationObserver(relocate);
  obs.observe(document.body, { childList: true, subtree: true });
})();

/* Home — quick prompt starts a real conversation and streams on the chat page. */

(() => {
  const form = document.getElementById("quick-prompt-form");
  if (!form) return;

  const input = document.getElementById("quick-prompt");
  const modelInput = form.querySelector('input[name="model"]');
  const submit = form.querySelector('button[type="submit"]');
  const label = submit.querySelector("span");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) {
      input.focus();
      return;
    }

    submit.disabled = true;
    label.textContent = "Starting…";

    try {
      const created = await Ultron.api("/api/conversations", {
        method: "POST",
        body: {
          first_message: content,
          model: modelInput ? modelInput.value : undefined,
        },
      });
      window.location.href = `/chat/${created.id}?autosend=1`;
    } catch (error) {
      Ultron.toast(error.message, "error");
      submit.disabled = false;
      label.textContent = "Send prompt";
    }
  });
})();

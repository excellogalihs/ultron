/* Memory — user-curated context for local chat requests. */

(() => {
  const form = document.getElementById("memory-form");
  const list = document.getElementById("memory-list");
  const dialog = document.getElementById("memory-dialog");
  if (!form || !list || !dialog) return;

  const contentInput = document.getElementById("memory-content");
  const categoryInput = document.getElementById("memory-category");
  const submit = document.getElementById("memory-submit");
  const editForm = document.getElementById("memory-edit-form");
  const editId = document.getElementById("memory-id");
  const editContent = document.getElementById("memory-edit-content");
  const editCategory = document.getElementById("memory-edit-category");
  const editSave = document.getElementById("memory-save");
  const errorBox = document.getElementById("memory-error");
  const submitLabel = submit.innerHTML;

  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.hidden = !message;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = contentInput.value.trim();
    if (!content) {
      contentInput.focus();
      return;
    }

    submit.disabled = true;
    submit.textContent = "Storing…";

    try {
      await Ultron.api("/api/memories", {
        method: "POST",
        body: { content, category: categoryInput.value },
      });
      window.location.reload();
    } catch (error) {
      Ultron.toast(error.message, "error");
      submit.disabled = false;
      submit.innerHTML = submitLabel;
    }
  });

  list.addEventListener("click", async (event) => {
    const card = event.target.closest(".memory-card");
    if (!card) return;
    const memoryId = Number(card.dataset.memoryId);

    const toggle = event.target.closest("[data-memory-toggle]");
    if (toggle) {
      const nextActive = Number(toggle.dataset.active) !== 1;
      toggle.disabled = true;
      try {
        await Ultron.api(`/api/memories/${memoryId}`, {
          method: "PATCH",
          body: { active: nextActive },
        });
        window.location.reload();
      } catch (error) {
        toggle.disabled = false;
        Ultron.toast(error.message, "error");
      }
      return;
    }

    const edit = event.target.closest("[data-memory-edit]");
    if (edit) {
      editId.value = memoryId;
      editContent.value = card.querySelector(".memory-card__content").textContent;
      editCategory.value = card.querySelector(".tag").textContent.trim().toLowerCase();
      showError("");
      Ultron.openDialog(dialog);
      window.setTimeout(() => editContent.focus(), 20);
      return;
    }

    const remove = event.target.closest("[data-memory-delete]");
    if (remove) {
      if (!window.confirm("Delete this memory? It will no longer be used as chat context.")) {
        return;
      }
      try {
        await Ultron.api(`/api/memories/${memoryId}`, { method: "DELETE" });
        window.location.reload();
      } catch (error) {
        Ultron.toast(error.message, "error");
      }
    }
  });

  editForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = editContent.value.trim();
    if (!content) {
      showError("Memory content is required.");
      editContent.focus();
      return;
    }

    editSave.disabled = true;
    editSave.textContent = "Saving…";
    showError("");

    try {
      await Ultron.api(`/api/memories/${editId.value}`, {
        method: "PATCH",
        body: { content, category: editCategory.value },
      });
      window.location.reload();
    } catch (error) {
      showError(error.message);
      editSave.disabled = false;
      editSave.textContent = "Save memory";
    }
  });
})();

(() => {
  const list = document.querySelector("[data-experience-id]")?.parentElement;
  if (!list) return;
  list.addEventListener("click", async (event) => {
    const card = event.target.closest("[data-experience-id]");
    if (!card) return;
    const id = card.dataset.experienceId;
    try {
      if (event.target.closest("[data-archive]")) {
        const archived = event.target.closest("[data-archive]").textContent.trim() === "Archive";
        await Ultron.api(`/api/experiences/${id}`, { method: "PATCH", body: { archived } });
        window.location.reload();
      } else if (event.target.closest("[data-edit]")) {
        const button = event.target.closest("[data-edit]");
        const title = window.prompt("Experience title", button.dataset.title);
        if (title === null) return;
        const successful_methods = window.prompt("Confirmed successful method", button.dataset.method);
        if (successful_methods === null) return;
        await Ultron.api(`/api/experiences/${id}`, { method: "PATCH", body: { title, successful_methods } });
        window.location.reload();
      } else if (event.target.closest("[data-delete]")) {
        if (!window.confirm("Permanently delete this experience?")) return;
        await Ultron.api(`/api/experiences/${id}`, { method: "DELETE" });
        window.location.reload();
      }
    } catch (error) { Ultron.toast(error.message, "error"); }
  });
})();

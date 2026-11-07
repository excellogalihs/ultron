(() => {
  const feedback = document.getElementById("project-toast");
  const show = (message) => { if (feedback) feedback.textContent = message; else Ultron.toast(message); };
  document.getElementById("project-create-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget;
    try { const project = await Ultron.api("/api/projects", { method: "POST", body: Object.fromEntries(new FormData(form)) }); window.location.assign(`/projects?project=${project.project.id}`); }
    catch (error) { show(error.message); }
  });
  document.getElementById("project-edit-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget;
    try { await Ultron.api(`/api/projects/${form.dataset.projectId}`, { method: "PATCH", body: Object.fromEntries(new FormData(form)) }); show("Project saved."); window.setTimeout(() => window.location.reload(), 350); }
    catch (error) { show(error.message); }
  });
  document.querySelectorAll("[data-project-archive]").forEach((button) => button.addEventListener("click", async () => {
    const id = button.dataset.projectArchive;
    try { const current = await Ultron.api(`/api/projects/${id}`); await Ultron.api(`/api/projects/${id}`, { method: "PATCH", body: { status: current.project.status === "active" ? "archived" : "active" } }); window.location.reload(); }
    catch (error) { show(error.message); }
  }));
  document.querySelectorAll("[data-project-delete]").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Delete this project? Its tasks and linked workspace items will remain.")) return;
    try { await Ultron.api(`/api/projects/${button.dataset.projectDelete}`, { method: "DELETE" }); window.location.assign("/projects"); }
    catch (error) { show(error.message); }
  }));
  document.querySelectorAll(".project-task-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await Ultron.api("/api/tasks", { method: "POST", body: { title: form.elements.title.value, due_date: form.elements.due_date.value || null, project_id: Number(form.dataset.projectId) } }); window.location.reload(); }
    catch (error) { show(error.message); }
  }));
  document.querySelectorAll(".project-link-form").forEach((form) => {
    const type = form.elements.type; const item = form.elements.id;
    const filter = () => { Array.from(item.options).forEach((option) => { if (option.dataset.type) option.hidden = option.dataset.type !== type.value; }); const visible = Array.from(item.options).find((option) => option.dataset.type === type.value); if (visible) item.value = visible.value; };
    type.addEventListener("change", filter); filter();
    form.addEventListener("submit", async (event) => { event.preventDefault();
      try { await Ultron.api(`/api/projects/${form.dataset.projectId}/links`, { method: "POST", body: { type: type.value, id: Number(item.value) } }); window.location.reload(); }
      catch (error) { show(error.message); }
    });
  });
})();

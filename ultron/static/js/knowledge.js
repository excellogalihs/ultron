(() => {
  const form = document.getElementById("knowledge-import-form");
  const status = document.getElementById("knowledge-import-status");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    status.textContent = "Extracting and indexing locally…";
    try {
      const result = await Ultron.api("/api/knowledge/import", { method: "POST", body: new FormData(form) });
      window.location.assign(`/knowledge?file=${result.file.id}`);
    } catch (error) {
      status.textContent = error.message;
    }
  });
  document.getElementById("knowledge-collection-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await Ultron.api("/api/knowledge/collections", { method: "POST", body: { name: event.currentTarget.elements.name.value } });
      const option = new Option(result.collection.name, result.collection.id);
      document.getElementById("knowledge-collection").add(option);
      event.currentTarget.reset();
      Ultron.toast("Collection created.");
    } catch (error) { Ultron.toast(error.message, "error"); }
  });
  document.getElementById("knowledge-meta-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget;
    try {
      await Ultron.api(`/api/knowledge/${form.dataset.fileId}`, { method: "PATCH", body: { title: form.elements.title.value, collection_id: form.elements.collection_id.value ? Number(form.elements.collection_id.value) : null } });
      window.location.reload();
    } catch (error) { Ultron.toast(error.message, "error"); }
  });
  document.querySelectorAll("[data-knowledge-delete]").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Remove this imported knowledge file?")) return;
    try { await Ultron.api(`/api/knowledge/${button.dataset.knowledgeDelete}`, { method: "DELETE" }); window.location.assign("/knowledge"); }
    catch (error) { Ultron.toast(error.message, "error"); }
  }));
  document.querySelectorAll("[data-collection-delete]").forEach((button) => button.addEventListener("click", async () => {
    if (!window.confirm("Delete this collection? Its files will remain in Unsorted.")) return;
    try { await Ultron.api(`/api/knowledge/collections/${button.dataset.collectionDelete}`, { method: "DELETE" }); window.location.reload(); }
    catch (error) { Ultron.toast(error.message, "error"); }
  }));
})();

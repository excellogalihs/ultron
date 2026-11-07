/* Tasks — create, complete, and delete tasks against the local API. */

(() => {
  const app = document.getElementById("tasks-app");
  const form = document.getElementById("task-form");
  if (!form) return;

  const titleInput = document.getElementById("task-title");
  const dueInput = document.getElementById("task-due");
  const priorityInput = document.getElementById("task-priority");
  const categoryInput = document.getElementById("task-category");
  const projectInput = document.getElementById("task-project");
  const submit = document.getElementById("task-submit");
  const submitLabel = submit.innerHTML;
  const editDialog = document.getElementById("task-edit-dialog");
  const editForm = document.getElementById("task-edit-form");
  const editId = document.getElementById("edit-task-id");
  const editTitle = document.getElementById("edit-task-title");
  const editNotes = document.getElementById("edit-task-notes");
  const editDue = document.getElementById("edit-task-due");
  const editPriority = document.getElementById("edit-task-priority");
  const editCategory = document.getElementById("edit-task-category");
  const editProject = document.getElementById("edit-task-project");
  const editError = document.getElementById("task-edit-error");
  const editSave = document.getElementById("task-edit-save");

  const openEdit = async (taskId) => {
    try {
      const { task } = await Ultron.api(`/api/tasks/${taskId}`);
      editId.value = task.id;
      editTitle.value = task.title;
      editNotes.value = task.notes || "";
      editDue.value = task.due_date || "";
      editPriority.value = task.priority;
      editCategory.value = task.category || "general";
      editProject.value = task.project_id || "";
      editError.hidden = true;
      Ultron.openDialog(editDialog);
      editTitle.focus();
    } catch (error) {
      Ultron.toast(error.message, "error");
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = titleInput.value.trim();
    if (!title) {
      titleInput.focus();
      return;
    }

    submit.disabled = true;
    submit.textContent = "Adding…";

    try {
      await Ultron.api("/api/tasks", {
        method: "POST",
        body: {
          title,
          due_date: dueInput.value,
          priority: priorityInput.value,
          category: categoryInput.value,
          project_id: projectInput.value ? Number(projectInput.value) : null,
        },
      });
      window.location.href = "/tasks?view=pending";
    } catch (error) {
      Ultron.toast(error.message, "error");
      submit.disabled = false;
      submit.innerHTML = submitLabel;
    }
  });

  editForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    editSave.disabled = true;
    editError.hidden = true;
    try {
      await Ultron.api(`/api/tasks/${editId.value}`, {
        method: "PATCH",
        body: {
          title: editTitle.value.trim(),
          notes: editNotes.value,
          due_date: editDue.value,
          priority: editPriority.value,
          category: editCategory.value,
          project_id: editProject.value ? Number(editProject.value) : null,
        },
      });
      window.location.reload();
    } catch (error) {
      editError.textContent = error.message;
      editError.hidden = false;
      editSave.disabled = false;
    }
  });

  document.getElementById("task-edit-close").addEventListener("click", () => editDialog.close());
  document.getElementById("task-edit-cancel").addEventListener("click", () => editDialog.close());

  if (app) {
    app.addEventListener("click", async (event) => {
      const edit = event.target.closest("[data-task-edit]");
      if (edit) {
        openEdit(Number(edit.closest(".task-row").dataset.taskId));
        return;
      }

      const toggle = event.target.closest("[data-task-toggle]");
      if (toggle) {
        const row = toggle.closest(".task-row");
        const currentStatus = toggle.dataset.status;
        const nextStatus = currentStatus === "pending" ? "completed" : "pending";
        toggle.disabled = true;

        try {
          await Ultron.api(`/api/tasks/${row.dataset.taskId}`, {
            method: "PATCH",
            body: { status: nextStatus },
          });
          window.location.reload();
        } catch (error) {
          toggle.disabled = false;
          Ultron.toast(error.message, "error");
        }
        return;
      }

      const remove = event.target.closest("[data-task-delete]");
      if (remove) {
        const row = remove.closest(".task-row");
        if (!window.confirm("Delete this task?")) return;

        try {
          await Ultron.api(`/api/tasks/${row.dataset.taskId}`, { method: "DELETE" });
          window.location.reload();
        } catch (error) {
          Ultron.toast(error.message, "error");
        }
      }
    });
  }

  const requestedTask = new URLSearchParams(window.location.search).get("task");
  if (requestedTask && /^\d+$/.test(requestedTask)) openEdit(Number(requestedTask));
})();

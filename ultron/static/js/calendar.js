/* Calendar — month grid and real event CRUD through /api/events. */

(() => {
  const app = document.getElementById("calendar-app");
  const dialog = document.getElementById("event-dialog");
  if (!app || !dialog) return;

  const form = document.getElementById("event-form");
  const idInput = document.getElementById("event-id");
  const titleInput = document.getElementById("event-title");
  const dateInput = document.getElementById("event-date");
  const startInput = document.getElementById("event-start");
  const endInput = document.getElementById("event-end");
  const descriptionInput = document.getElementById("event-description");
  const categoryInput = document.getElementById("event-category");
  const dialogTitle = document.getElementById("event-dialog-title");
  const deleteBtn = document.getElementById("event-delete");
  const saveBtn = document.getElementById("event-save");
  const errorBox = document.getElementById("event-error");
  const today = app.dataset.today;
  const currentMonth = app.dataset.month;
  const currentView = app.dataset.view || "month";
  const selectedDate = app.dataset.selectedDate || today;

  const calendarUrl = (date = selectedDate) => currentView === "month"
    ? `/calendar?view=month&month=${currentMonth}`
    : `/calendar?view=${currentView}&date=${date}`;

  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.hidden = !message;
  };

  const openNew = (date = selectedDate) => {
    form.reset();
    idInput.value = "";
    dialogTitle.textContent = "New event";
    dateInput.value = date || today;
    startInput.value = "09:00";
    endInput.value = "10:00";
    categoryInput.value = "general";
    deleteBtn.hidden = true;
    showError("");
    Ultron.openDialog(dialog);
    window.setTimeout(() => titleInput.focus(), 20);
  };

  const openEdit = async (eventId) => {
    try {
      const data = await Ultron.api(`/api/events/${eventId}`);
      const event = data.event;
      idInput.value = event.id;
      dialogTitle.textContent = "Edit event";
      titleInput.value = event.title;
      dateInput.value = event.start_at.slice(0, 10);
      startInput.value = event.start_at.slice(11, 16);
      endInput.value = event.end_at ? event.end_at.slice(11, 16) : "";
      descriptionInput.value = event.description || "";
      categoryInput.value = event.category || "general";
      deleteBtn.hidden = false;
      showError("");
      Ultron.openDialog(dialog);
      window.setTimeout(() => titleInput.focus(), 20);
    } catch (error) {
      Ultron.toast(error.message, "error");
    }
  };

  app.addEventListener("click", (event) => {
    const eventButton = event.target.closest("[data-event-id]");
    if (eventButton) {
      event.stopPropagation();
      openEdit(Number(eventButton.dataset.eventId));
      return;
    }

    const day = event.target.closest(".cal-day, [data-calendar-add-date]");
    if (day) openNew(day.dataset.date || day.dataset.calendarAddDate);
  });

  document.getElementById("new-event-btn").addEventListener("click", () => openNew());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const title = titleInput.value.trim();
    if (!title) {
      showError("Event title is required.");
      titleInput.focus();
      return;
    }
    if (!dateInput.value) {
      showError("Choose a date for this event.");
      dateInput.focus();
      return;
    }

    const editingId = idInput.value ? Number(idInput.value) : null;
    const payload = {
      title,
      date: dateInput.value,
      start_time: startInput.value,
      end_time: endInput.value,
      description: descriptionInput.value,
      category: categoryInput.value,
    };

    saveBtn.disabled = true;
    saveBtn.textContent = "Saving…";
    showError("");

    try {
      await Ultron.api(editingId ? `/api/events/${editingId}` : "/api/events", {
        method: editingId ? "PATCH" : "POST",
        body: payload,
      });
      window.location.href = calendarUrl(payload.date);
    } catch (error) {
      showError(error.message);
      saveBtn.disabled = false;
      saveBtn.textContent = "Save event";
    }
  });

  deleteBtn.addEventListener("click", async () => {
    const editingId = idInput.value ? Number(idInput.value) : null;
    if (!editingId) return;
    if (!window.confirm("Delete this event?")) return;

    try {
      await Ultron.api(`/api/events/${editingId}`, { method: "DELETE" });
      window.location.href = calendarUrl(dateInput.value || selectedDate);
    } catch (error) {
      showError(error.message);
    }
  });

  const openEventId = Number(app.dataset.openEvent || 0);
  if (openEventId) {
    history.replaceState(null, "", calendarUrl());
    openEdit(openEventId);
  }
})();

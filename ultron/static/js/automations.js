(() => {
  const form = document.getElementById("automation-form");
  const list = document.getElementById("automation-list");
  if (!form || !list) return;
  const type = document.getElementById("automation-type");
  const fields = {
    time: document.getElementById("schedule-time-field"), at: document.getElementById("schedule-at-field"),
    weekday: document.getElementById("schedule-weekday-field"), day: document.getElementById("schedule-day-field"),
    interval: document.getElementById("schedule-interval-field"),
  };
  const updateFields = () => {
    Object.values(fields).forEach((el) => { el.hidden = true; });
    if (type.value === "once") fields.at.hidden = false;
    else fields.time.hidden = false;
    if (type.value === "weekly") fields.weekday.hidden = false;
    if (type.value === "monthly") fields.day.hidden = false;
    if (type.value === "custom") fields.interval.hidden = false;
  };
  type.addEventListener("change", updateFields);
  updateFields();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const kind = type.value;
    const schedule_value = kind === "once" ? { at: document.getElementById("automation-at").value.replace("T", " ") } : { time: document.getElementById("automation-time").value };
    if (kind === "weekly") schedule_value.weekday = Number(document.getElementById("automation-weekday").value);
    if (kind === "monthly") schedule_value.day = Number(document.getElementById("automation-day").value);
    if (kind === "custom") schedule_value.interval_minutes = Number(document.getElementById("automation-interval").value);
    const button = document.getElementById("automation-submit");
    button.disabled = true;
    try {
      await Ultron.api("/api/automations", { method: "POST", body: { name: document.getElementById("automation-name").value.trim(), instruction: document.getElementById("automation-instruction").value.trim(), schedule_type: kind, schedule_value, timezone: document.getElementById("automation-timezone").value.trim() } });
      window.location.reload();
    } catch (error) { Ultron.toast(error.message, "error"); button.disabled = false; }
  });
  list.addEventListener("click", async (event) => {
    const card = event.target.closest("[data-automation-id]");
    if (!card) return;
    const id = card.dataset.automationId;
    try {
      if (event.target.closest("[data-run]")) {
        const result = await Ultron.api(`/api/automations/${id}/run`, { method: "POST", body: {} });
        Ultron.toast(result.result || "Automation completed."); window.location.reload();
      } else if (event.target.closest("[data-toggle]")) {
        const currentlyEnabled = card.querySelector(".tag:not(.tag--accent)").textContent.trim() === "ACTIVE";
        await Ultron.api(`/api/automations/${id}`, { method: "PATCH", body: { enabled: !currentlyEnabled } }); window.location.reload();
      } else if (event.target.closest("[data-edit]")) {
        const edit = event.target.closest("[data-edit]");
        const name = window.prompt("Automation name", edit.dataset.name);
        if (name === null) return;
        const instruction = window.prompt("Summary instruction", edit.dataset.instruction);
        if (instruction === null) return;
        await Ultron.api(`/api/automations/${id}`, { method: "PATCH", body: { name, instruction } }); window.location.reload();
      } else if (event.target.closest("[data-delete]")) {
        if (!window.confirm("Delete this automation? Its execution history will be retained.")) return;
        await Ultron.api(`/api/automations/${id}`, { method: "DELETE" }); window.location.reload();
      }
    } catch (error) { Ultron.toast(error.message, "error"); }
  });
})();

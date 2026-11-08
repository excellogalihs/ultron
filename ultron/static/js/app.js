/* ============================================================
   ultron — shared application behavior
   ============================================================ */

const Ultron = (() => {
  async function api(url, options = {}) {
    const { method = "GET", body = null, headers: customHeaders, ...rest } = options;
    const headers = new Headers(customHeaders || {});
    let payload = body;

    if (body !== null && body !== undefined && !(body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
      payload = JSON.stringify(body);
    }

    const response = await fetch(url, { method, headers, body: payload, ...rest });
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }

    if (!response.ok) {
      const message =
        (data && typeof data === "object" && data.error) ||
        (typeof data === "string" && data) ||
        `Request failed (${response.status}).`;
      const error = new Error(message);
      error.status = response.status;
      error.data = data;
      throw error;
    }

    return data;
  }

  function toast(message, kind = "success") {
    const host = document.getElementById("toasts");
    if (!host) return;

    const toastEl = document.createElement("div");
    toastEl.className = `toast toast--${kind}`;

    const glyph = document.createElement("span");
    glyph.className = "toast__icon";
    glyph.textContent = kind === "error" ? "!" : "✓";

    const text = document.createElement("span");
    text.className = "toast__text";
    text.textContent = message;

    toastEl.append(glyph, text);
    host.appendChild(toastEl);

    const remove = () => {
      toastEl.classList.add("is-hiding");
      window.setTimeout(() => toastEl.remove(), 200);
    };
    window.setTimeout(remove, kind === "error" ? 6000 : 3800);
    toastEl.addEventListener("click", remove);
  }

  function openDialog(dialog) {
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (!dialog.open) dialog.showModal();
  }

  function closeDialog(dialog) {
    if (dialog && dialog.open) dialog.close();
  }

  function setSidebar(open) {
    const sidebar = document.getElementById("sidebar");
    const scrim = document.getElementById("sidebar-scrim");
    const toggle = document.getElementById("sidebar-toggle");
    if (!sidebar || !scrim || !toggle) return;

    sidebar.classList.toggle("is-open", open);
    scrim.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("nav-open", open);
  }

  function initSidebar() {
    const toggle = document.getElementById("sidebar-toggle");
    const scrim = document.getElementById("sidebar-scrim");
    const sidebar = document.getElementById("sidebar");

    if (toggle) {
      toggle.addEventListener("click", () => {
        setSidebar(!sidebar.classList.contains("is-open"));
      });
    }
    if (scrim) {
      scrim.addEventListener("click", () => setSidebar(false));
    }
    if (sidebar) {
      sidebar.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => setSidebar(false));
      });
    }

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && sidebar.classList.contains("is-open")) {
        setSidebar(false);
        toggle?.focus();
      }
    });

    window.addEventListener("resize", () => {
      if (window.innerWidth > 1024) setSidebar(false);
    });
  }

  function initDialogBehavior() {
    document.querySelectorAll("dialog").forEach((dialog) => {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
      });
    });

    document.addEventListener("click", (event) => {
      const opener = event.target.closest("[data-dialog-open]");
      if (opener) {
        openDialog(document.getElementById(opener.dataset.dialogOpen));
      }

      const closer = event.target.closest("[data-dialog-close]");
      if (closer) {
        closeDialog(closer.closest("dialog"));
      }
    });
  }

  function initFlash() {
    document.querySelectorAll(".flash").forEach((flash) => {
      const dismiss = () => {
        flash.classList.add("is-hiding");
        window.setTimeout(() => flash.remove(), 200);
      };

      flash.querySelector(".flash__close")?.addEventListener("click", dismiss);
      window.setTimeout(dismiss, 6500);
    });
  }

  function initEngineStatus() {
    const dot = document.getElementById("engine-dot");
    const state = document.getElementById("engine-state");
    if (!dot || !state) return;

    const render = (data) => {
      dot.classList.remove("status-dot--idle", "status-dot--online", "status-dot--offline");
      if (data.available) {
        dot.classList.add("status-dot--online");
        state.textContent = `Ollama online · ${data.models.length} model${data.models.length === 1 ? "" : "s"}`;
        state.classList.add("is-online");
        state.classList.remove("is-offline");
        state.title = data.models.length ? data.models.join(", ") : "No models installed yet.";
      } else {
        dot.classList.add("status-dot--offline");
        state.textContent = "Ollama offline";
        state.classList.add("is-offline");
        state.classList.remove("is-online");
        state.title = data.error || "Start Ollama with: ollama serve";
      }
    };

    fetch("/api/ollama/status", { headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then(render)
      .catch(() => {
        dot.classList.remove("status-dot--idle", "status-dot--online");
        dot.classList.add("status-dot--offline");
        state.textContent = "Status unavailable";
        state.classList.add("is-offline");
      });
  }

  function initNotifications() {
    const center = document.getElementById("notification-center");
    const toggle = document.getElementById("notification-toggle");
    const panel = document.getElementById("notification-panel");
    const count = document.getElementById("notification-count");
    const list = document.getElementById("notification-list");
    const readAll = document.getElementById("notification-read-all");
    const desktop = document.getElementById("notification-desktop");
    if (!center || !toggle || !panel || !list) return;

    let loading = false;
    const notified = new Set();
    const updateCount = (unread) => {
      count.textContent = unread > 99 ? "99+" : String(unread);
      count.hidden = unread < 1;
      toggle.setAttribute("aria-label", unread ? `Notifications, ${unread} unread` : "Notifications");
    };

    const render = (notifications) => {
      list.replaceChildren();
      if (!notifications.length) {
        const empty = document.createElement("p");
        empty.className = "notification-empty";
        empty.textContent = "No reminders yet.";
        list.appendChild(empty);
        return;
      }
      notifications.forEach((item) => {
        const link = document.createElement("a");
        link.className = `notification-item${item.read_at ? "" : " is-unread"}`;
        link.href = item.href;
        const title = document.createElement("strong");
        title.textContent = item.title;
        const message = document.createElement("span");
        message.textContent = item.message;
        const meta = document.createElement("small");
        meta.textContent = `${item.source_type} · ${item.due_at}`;
        link.append(title, message, meta);
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          try {
            await api(item.read_url || `/api/notifications/${item.id}/read`, { method: "POST" });
          } finally {
            window.location.assign(link.href);
          }
        });
        list.appendChild(link);
      });
    };

    const refresh = async (notify = true) => {
      if (loading) return;
      loading = true;
      try {
        const result = await api("/api/notifications");
        render(result.notifications || []);
        updateCount(result.unread || 0);
        if (notify) {
          (result.new || []).forEach((item) => {
            const notificationKey = `${item.source_type}:${item.id}`;
            if (notified.has(notificationKey)) return;
            notified.add(notificationKey);
            toast(`${item.title}: ${item.message}`, "success");
            if (window.Notification && Notification.permission === "granted" && localStorage.getItem("ultron-desktop-notifications") === "1") {
              new Notification(item.title, { body: item.message, tag: `ultron-${notificationKey}` });
            }
          });
        }
      } catch {
        /* Reminders stay local; retry on the next poll if this request fails. */
      } finally {
        loading = false;
      }
    };

    toggle.addEventListener("click", () => {
      const opening = panel.hidden;
      panel.hidden = !opening;
      toggle.setAttribute("aria-expanded", String(opening));
      if (opening) refresh(false);
    });
    document.addEventListener("click", (event) => {
      if (!center.contains(event.target)) {
        panel.hidden = true;
        toggle.setAttribute("aria-expanded", "false");
      }
    });
    readAll.addEventListener("click", async () => {
      try {
        await api("/api/notifications/read-all", { method: "POST" });
        await refresh(false);
      } catch (error) {
        toast(error.message, "error");
      }
    });
    if (!window.Notification) {
      desktop.hidden = true;
    } else {
      desktop.addEventListener("click", async () => {
        if (Notification.permission === "granted") {
          localStorage.setItem("ultron-desktop-notifications", "1");
          toast("Desktop notifications enabled.");
          return;
        }
        const permission = await Notification.requestPermission();
        if (permission === "granted") {
          localStorage.setItem("ultron-desktop-notifications", "1");
          toast("Desktop notifications enabled.");
        } else {
          toast("Desktop notification permission was not granted.", "error");
        }
      });
      if (Notification.permission === "granted" && localStorage.getItem("ultron-desktop-notifications") === "1") {
        desktop.textContent = "Desktop notifications enabled";
      }
    }
    refresh();
    window.setInterval(() => refresh(), 60000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    initDialogBehavior();
    initFlash();
    initEngineStatus();
    initNotifications();
  });

  return { api, toast, openDialog, closeDialog, setSidebar };
})();

window.Ultron = Ultron;

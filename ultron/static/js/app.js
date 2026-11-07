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

  document.addEventListener("DOMContentLoaded", () => {
    initSidebar();
    initDialogBehavior();
    initFlash();
    initEngineStatus();
  });

  return { api, toast, openDialog, closeDialog, setSidebar };
})();

window.Ultron = Ultron;

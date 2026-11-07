/* Chat — server-rendered history with streaming replies from Ollama. */

(() => {
  const app = document.getElementById("chat-app");
  if (!app) return;

  const conversationId = app.dataset.conversationId ? Number(app.dataset.conversationId) : null;
  const messagesEl = document.getElementById("chat-messages");
  const emptyEl = document.getElementById("chat-empty");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  const stopBtn = document.getElementById("chat-stop");
  const modelSelect = document.getElementById("chat-model");
  const titleEl = document.getElementById("chat-title");
  const subtitleEl = document.getElementById("chat-subtitle");
  const composerModel = document.getElementById("composer-model");
  const deleteBtn = document.getElementById("delete-conversation");
  const renameBtn = document.getElementById("rename-conversation");
  const renameDialog = document.getElementById("rename-dialog");
  const renameForm = document.getElementById("rename-form");
  const renameInput = document.getElementById("rename-input");
  const renameSave = document.getElementById("rename-save");
  const renameCancel = document.getElementById("rename-cancel");
  const renameClose = document.getElementById("rename-close");
  const newBtn = document.getElementById("new-conversation");
  const connectionState = document.getElementById("chat-connection-state");
  const errorBanner = document.getElementById("chat-error");
  const rail = document.getElementById("chat-rail");
  const railToggle = document.getElementById("chat-rail-toggle");
  const railClose = document.getElementById("chat-rail-close");
  const railScrim = document.getElementById("chat-rail-scrim");

  let streaming = false;
  let activeController = null;
  let previousModel = modelSelect.value;

  const modelLabel = () => {
    const option = modelSelect.options[modelSelect.selectedIndex];
    return option ? option.textContent.trim() : modelSelect.value;
  };

  const updateModelDisplay = () => {
    subtitleEl.textContent = `${modelLabel()} · local inference`;
    composerModel.textContent = modelSelect.value;
  };

  const autoResize = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  };

  const nearBottom = () =>
    messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 120;

  const scrollBottom = (force = false) => {
    if (force || nearBottom()) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }
  };

  const hideEmpty = () => {
    if (emptyEl) emptyEl.hidden = true;
  };

  const setStreaming = (value) => {
    streaming = value;
    sendBtn.disabled = value;
    sendBtn.hidden = value;
    stopBtn.hidden = !value;
    messagesEl.setAttribute("aria-busy", value ? "true" : "false");
  };

  const addMessageActions = (message) => {
    if (!message || message.querySelector(".msg__actions")) return;
    const body = message.querySelector(".msg__body");
    if (!body) return;

    const actions = document.createElement("div");
    actions.className = "msg__actions";
    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "msg__action";
    copyButton.textContent = "Copy";
    copyButton.title = "Copy response";
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(body.dataset.rawText || body.textContent);
        copyButton.textContent = "Copied";
        window.setTimeout(() => { copyButton.textContent = "Copy"; }, 1200);
      } catch {
        Ultron.toast("Clipboard access is unavailable in this browser.", "error");
      }
    });
    actions.appendChild(copyButton);

    const assistantMessages = messagesEl.querySelectorAll(".msg--assistant:not(.msg--error)");
    if (message === assistantMessages[assistantMessages.length - 1] && conversationId) {
      const regenerateButton = document.createElement("button");
      regenerateButton.type = "button";
      regenerateButton.className = "msg__action";
      regenerateButton.textContent = "Regenerate";
      regenerateButton.title = "Regenerate response";
      regenerateButton.addEventListener("click", async () => {
        if (streaming) return;
        regenerateButton.disabled = true;
        try {
          await Ultron.api(`/api/conversations/${conversationId}/regenerate`, { method: "POST" });
          message.remove();
          await startStream(null);
        } catch (error) {
          regenerateButton.disabled = false;
          Ultron.toast(error.message, "error");
        }
      });
      actions.appendChild(regenerateButton);
    }
    message.appendChild(actions);
  };

  const renderAssistant = (message, text) => {
    const body = message.querySelector(".msg__body");
    body.dataset.rawText = text;
    window.UltronMarkdown.render(body, text);
    addMessageActions(message);
  };

  const applyTitle = (title) => {
    if (!title) return;
    titleEl.textContent = title;
    document.title = `${title} · ULTRON`;
    const activeThread = document.querySelector(".chat-rail .thread.is-active .thread__title");
    if (activeThread) activeThread.textContent = title;
  };

  const markThreadCurrent = () => {
    const activeMeta = document.querySelector(".chat-rail .thread.is-active .thread__meta span:last-child");
    if (activeMeta) activeMeta.textContent = "just now";
  };

  const createMessage = (role, text) => {
    const wrap = document.createElement("div");
    wrap.className = `msg msg--${role}`;

    const meta = document.createElement("div");
    meta.className = "msg__meta";

    const roleEl = document.createElement("span");
    roleEl.className = "msg__role";
    roleEl.textContent = role === "user" ? "YOU" : "ULTRON";

    const time = document.createElement("time");
    time.textContent = "just now";

    const body = document.createElement("div");
    body.className = "msg__body";
    body.textContent = text;

    meta.append(roleEl, time);
    wrap.append(meta, body);
    messagesEl.appendChild(wrap);
    hideEmpty();
    scrollBottom(true);

    return { wrap, body, time, roleEl };
  };

  const createStreamingMessage = () => {
    const message = createMessage("assistant", "");
    message.wrap.classList.add("is-streaming");

    const textSpan = document.createElement("span");
    textSpan.className = "msg__text";
    const cursor = document.createElement("span");
    cursor.className = "msg__cursor";
    cursor.setAttribute("aria-hidden", "true");

    message.body.append(textSpan, cursor);
    message.textSpan = textSpan;
    message.cursor = cursor;
    scrollBottom(true);
    return message;
  };

  const parseEvent = (raw) => {
    let eventName = "message";
    const dataLines = [];
    raw.split("\n").forEach((line) => {
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    });
    if (!dataLines.length) return null;
    try {
      return { event: eventName, data: JSON.parse(dataLines.join("\n")) };
    } catch {
      return null;
    }
  };

  const consumeStream = async (response, target) => {
    if (!response.body) {
      throw new Error("Streaming is not supported by this browser.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let received = "";
    let completed = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");

      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseEvent(raw);

        if (event) {
          if (event.event === "token") {
            received += event.data.token || "";
            target.textSpan.textContent = received;
            scrollBottom();
          } else if (event.event === "meta") {
            applyTitle(event.data.title);
          } else if (event.event === "error") {
            throw new Error(event.data.error || "The local model returned an error.");
          } else if (event.event === "tool") {
            const activity = document.createElement("div");
            activity.className = "msg__tool-status";
            const actionLabel = event.data.name.replaceAll("_", " ");
            activity.textContent = !event.data.ok
              ? `Workspace action needs correction · ${actionLabel}`
              : event.data.requires_approval
                ? `Suggestion ready for review · ${actionLabel}`
                : event.data.changed
                  ? `Updated local workspace · ${actionLabel}`
                  : `Checked local workspace · ${actionLabel}`;
            target.body.replaceChildren(activity, target.textSpan, target.cursor);
          } else if (event.event === "done") {
            completed = true;
            if (event.data.content) {
              received = event.data.content;
            }
            if (event.data.id) target.wrap.dataset.messageId = event.data.id;
            target.cursor.remove();
            target.wrap.classList.remove("is-streaming");
            renderAssistant(target.wrap, received);
            applyTitle(event.data.title);
            markThreadCurrent();
          }
        }

        boundary = buffer.indexOf("\n\n");
      }
    }

    if (!completed) {
      throw new Error("The response ended before it was complete. Check Ollama and try again.");
    }

    scrollBottom();
    return received;
  };

  const showStreamError = (target, message) => {
    target.cursor?.remove();
    target.wrap.classList.add("msg--error");
    target.roleEl.textContent = "SYSTEM";
    target.time.textContent = "error";
    target.textSpan.textContent = message;
    errorBanner.textContent =
      "Generation failed. Your message is stored locally; retry when the engine is ready.";
    errorBanner.hidden = false;
    scrollBottom(true);
  };

  const startStream = async (content = null) => {
    if (streaming || !conversationId) return;
    errorBanner.hidden = true;
    const target = createStreamingMessage();
    activeController = new AbortController();
    setStreaming(true);

    try {
      const response = await fetch(`/api/conversations/${conversationId}/stream`, {
        method: "POST",
        signal: activeController.signal,
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(content ? { content } : {}),
      });

      if (!response.ok) {
        let message = `Request failed (${response.status}).`;
        try {
          const data = await response.json();
          if (data && data.error) message = data.error;
        } catch {
          /* keep the fallback */
        }
        throw new Error(message);
      }

      await consumeStream(response, target);
    } catch (error) {
      if (error.name === "AbortError") {
        const partial = target.textSpan.textContent.trim();
        target.cursor.remove();
        target.wrap.classList.remove("is-streaming");
        if (partial) {
          renderAssistant(target.wrap, partial);
          try {
            await Ultron.api(`/api/conversations/${conversationId}/partial`, {
              method: "POST",
              body: { content: partial },
            });
          } catch {
            Ultron.toast("Generation stopped; this partial response could not be saved.", "error");
          }
        } else {
          target.wrap.remove();
        }
      } else {
        showStreamError(target, error.message || "The local model request failed.");
      }
    } finally {
      activeController = null;
      setStreaming(false);
      input.focus();
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (streaming) return;

    const content = input.value.trim();
    if (!content) {
      input.focus();
      return;
    }

    if (!conversationId) {
      sendBtn.disabled = true;
      try {
        const created = await Ultron.api("/api/conversations", {
          method: "POST",
          body: { first_message: content, model: modelSelect.value },
        });
        window.location.href = `/chat/${created.id}?autosend=1`;
      } catch (error) {
        sendBtn.disabled = false;
        Ultron.toast(error.message, "error");
      }
      return;
    }

    input.value = "";
    autoResize();
    createMessage("user", content);
    await startStream(content);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!streaming) form.requestSubmit();
    }
  });

  input.addEventListener("input", autoResize);

  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.prompt || "";
      input.focus();
      autoResize();
      input.setSelectionRange(input.value.length, input.value.length);
    });
  });

  modelSelect.addEventListener("change", async () => {
    const nextModel = modelSelect.value;
    updateModelDisplay();

    if (!conversationId) {
      previousModel = nextModel;
      return;
    }

    modelSelect.disabled = true;
    try {
      await Ultron.api(`/api/conversations/${conversationId}`, {
        method: "PATCH",
        body: { model: nextModel },
      });
      previousModel = nextModel;
    } catch (error) {
      modelSelect.value = previousModel;
      updateModelDisplay();
      Ultron.toast(error.message, "error");
    } finally {
      modelSelect.disabled = false;
    }
  });

  newBtn.addEventListener("click", async () => {
    if (streaming) return;

    const hasMessages = messagesEl.querySelectorAll(".msg").length > 0;
    if (!conversationId || !hasMessages) {
      input.focus();
      return;
    }

    newBtn.disabled = true;
    try {
      const created = await Ultron.api("/api/conversations", {
        method: "POST",
        body: { model: modelSelect.value },
      });
      window.location.href = `/chat/${created.id}`;
    } catch (error) {
      newBtn.disabled = false;
      Ultron.toast(error.message, "error");
    }
  });

  deleteBtn.addEventListener("click", async () => {
    if (!conversationId) return;
    if (!window.confirm("Delete this conversation and all of its messages?")) return;

    deleteBtn.disabled = true;
    try {
      await Ultron.api(`/api/conversations/${conversationId}`, { method: "DELETE" });
      window.location.href = "/chat";
    } catch (error) {
      deleteBtn.disabled = false;
      Ultron.toast(error.message, "error");
    }
  });

  renameBtn.addEventListener("click", () => {
    if (!conversationId) return;
    renameInput.value = titleEl.textContent.trim();
    renameDialog.showModal();
    renameInput.focus();
    renameInput.select();
  });

  renameForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const nextTitle = renameInput.value.trim();
    if (!nextTitle) return;
    renameSave.disabled = true;
    try {
      const result = await Ultron.api(`/api/conversations/${conversationId}`, {
        method: "PATCH",
        body: { title: nextTitle.trim() },
      });
      applyTitle(result.conversation.title);
      renameDialog.close();
    } catch (error) {
      Ultron.toast(error.message, "error");
    } finally {
      renameSave.disabled = false;
    }
  });

  renameCancel.addEventListener("click", () => renameDialog.close());
  renameClose.addEventListener("click", () => renameDialog.close());

  stopBtn.addEventListener("click", () => activeController?.abort());

  const setRail = (open) => {
    app.classList.toggle("rail-open", open);
    if (railScrim) railScrim.hidden = !open;
  };

  railToggle?.addEventListener("click", () => setRail(!app.classList.contains("rail-open")));
  railClose?.addEventListener("click", () => setRail(false));
  railScrim?.addEventListener("click", () => setRail(false));
  rail?.querySelectorAll(".thread").forEach((thread) => {
    thread.addEventListener("click", () => setRail(false));
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && app.classList.contains("rail-open")) {
      setRail(false);
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 1024) setRail(false);
  });

  updateModelDisplay();
  messagesEl.querySelectorAll(".msg--assistant:not(.msg--error)").forEach((message) => {
    const body = message.querySelector(".msg__body");
    const raw = body.textContent;
    body.dataset.rawText = raw;
    window.UltronMarkdown.render(body, raw);
    addMessageActions(message);
  });
  input.focus();
  window.requestAnimationFrame(() => scrollBottom(true));

  Ultron.api("/api/ollama/status").then((status) => {
    connectionState.classList.remove("is-checking", "is-error", "is-ok");
    connectionState.classList.add(status.available ? "is-ok" : "is-error");
    connectionState.textContent = status.available
      ? `Online · ${status.models.length} models`
      : "Ollama offline";
    connectionState.title = status.error || status.models.join(", ");
  }).catch((error) => {
    connectionState.classList.remove("is-checking", "is-ok");
    connectionState.classList.add("is-error");
    connectionState.textContent = "Status unavailable";
    connectionState.title = error.message;
  });

  const params = new URLSearchParams(window.location.search);
  if (params.get("autosend") === "1" && conversationId) {
    history.replaceState(null, "", window.location.pathname);
    const allMessages = messagesEl.querySelectorAll(".msg");
    const last = allMessages[allMessages.length - 1];
    if (last && last.classList.contains("msg--user")) {
      startStream(null);
    }
  }
})();

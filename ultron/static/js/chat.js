/* Chat — server-rendered history with streaming replies from Ollama. */

(() => {
  const app = document.getElementById("chat-app");
  if (!app) return;

  const conversationId = app.dataset.conversationId ? Number(app.dataset.conversationId) : null;
  const messagesEl = document.getElementById("chat-messages");
  const emptyEl = document.getElementById("chat-empty");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const attachButton = document.getElementById("chat-attach");
  const attachmentInput = document.getElementById("chat-attachment-file");
  const attachmentChip = document.getElementById("chat-attachment");
  const attachmentName = document.getElementById("chat-attachment-name");
  const attachmentRemove = document.getElementById("chat-attachment-remove");
  const sendBtn = document.getElementById("chat-send");
  const stopBtn = document.getElementById("chat-stop");
  const titleEl = document.getElementById("chat-title");
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
  let pendingAttachment = null;
  let uploadingAttachment = false;

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

    if (message.dataset.documentId) {
      const downloadButton = document.createElement("button");
      downloadButton.type = "button";
      downloadButton.className = "msg__action";
      downloadButton.textContent = "Download result";
      downloadButton.title = "Download the assistant response in the attached file's format";
      downloadButton.addEventListener("click", async () => {
        downloadButton.disabled = true;
        try {
          let content = body.dataset.rawText || body.textContent;
          const fenced = content.match(/^```[\w.+-]*\s*\n([\s\S]*?)\n```\s*$/);
          if (fenced) content = fenced[1];
          const response = await fetch(`/api/documents/${message.dataset.documentId}/export`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content }),
          });
          if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `Download failed (${response.status}).`);
          }
          const blob = await response.blob();
          const disposition = response.headers.get("Content-Disposition") || "";
          const filename = disposition.match(/filename=\"?([^\";]+)\"?/i)?.[1] || "ultron-edited-file";
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = filename;
          link.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (error) {
          Ultron.toast(error.message, "error");
        } finally {
          downloadButton.disabled = false;
        }
      });
      actions.appendChild(downloadButton);
    }

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

  const createMessage = (role, text, documentId = null, documentTitle = "") => {
    const wrap = document.createElement("div");
    wrap.className = `msg msg--${role}`;
    if (documentId) wrap.dataset.documentId = documentId;

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
    if (documentId && documentTitle) {
      const attachment = document.createElement("span");
      attachment.className = "msg__attachment";
      attachment.textContent = `FILE · ${documentTitle}`;
      meta.appendChild(attachment);
      wrap.dataset.documentTitle = documentTitle;
    }
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
    textSpan.hidden = true;
    const thinking = document.createElement("span");
    thinking.className = "msg__thinking";
    thinking.setAttribute("role", "status");
    const thinkingLabel = document.createElement("span");
    thinkingLabel.className = "msg__thinking-label";
    thinkingLabel.textContent = "Thinking";
    const visualizer = document.createElement("span");
    visualizer.className = "msg__visualizer";
    visualizer.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) {
      visualizer.appendChild(document.createElement("i"));
    }
    thinking.append(thinkingLabel, visualizer);
    const cursor = document.createElement("span");
    cursor.className = "msg__cursor";
    cursor.hidden = true;
    cursor.setAttribute("aria-hidden", "true");

    message.body.append(thinking, textSpan, cursor);
    message.textSpan = textSpan;
    message.thinking = thinking;
    message.thinkingLabel = thinkingLabel;
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
            if (event.data.token && target.thinking) {
              target.thinking.remove();
              target.thinking = null;
              target.textSpan.hidden = false;
              target.cursor.hidden = false;
            }
            received += event.data.token || "";
            target.textSpan.textContent = received;
            scrollBottom();
          } else if (event.event === "status") {
            if (target.thinkingLabel) {
              target.thinkingLabel.textContent = event.data.message || "Working with your workspace…";
            }
            scrollBottom();
          } else if (event.event === "meta") {
            applyTitle(event.data.title);
          } else if (event.event === "error") {
            throw new Error(event.data.error || "The local model returned an error.");
          } else if (event.event === "done") {
            completed = true;
            if (event.data.content) {
              received = event.data.content;
            }
            if (event.data.id) target.wrap.dataset.messageId = event.data.id;
            if (event.data.document_id) target.wrap.dataset.documentId = event.data.document_id;
            target.cursor.remove();
            target.thinking?.remove();
            target.thinking = null;
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
    target.thinking?.remove();
    target.textSpan.hidden = false;
    target.wrap.classList.add("msg--error");
    target.roleEl.textContent = "SYSTEM";
    target.time.textContent = "error";
    target.textSpan.textContent = message;
    errorBanner.textContent =
      "Generation failed. Your message is stored locally; retry when the engine is ready.";
    errorBanner.hidden = false;
    scrollBottom(true);
  };

  const startStream = async (content = null, documentId = null) => {
    if (streaming || !conversationId) return;
    errorBanner.hidden = true;
    const target = createStreamingMessage();
    if (documentId) target.wrap.dataset.documentId = documentId;
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
        body: JSON.stringify(content ? { content, document_id: documentId } : {}),
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
    if (streaming || uploadingAttachment) return;

    const content = input.value.trim() || (pendingAttachment
      ? "Please improve the writing and clarity of this document. Return the complete revised file content."
      : "");
    if (!content) {
      input.focus();
      return;
    }

    if (!conversationId) {
      sendBtn.disabled = true;
      try {
        const created = await Ultron.api("/api/conversations", {
          method: "POST",
          body: { first_message: content, document_id: pendingAttachment?.id || null },
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
    const documentId = pendingAttachment?.id || null;
    createMessage("user", content, documentId, pendingAttachment ? `${pendingAttachment.title}${pendingAttachment.fileType}` : "");
    pendingAttachment = null;
    attachmentChip.hidden = true;
    attachmentInput.value = "";
    await startStream(content, documentId);
  });

  attachButton?.addEventListener("click", () => attachmentInput.click());
  attachmentRemove?.addEventListener("click", () => {
    pendingAttachment = null;
    attachmentChip.hidden = true;
    attachmentInput.value = "";
  });
  attachmentInput?.addEventListener("change", async () => {
    const file = attachmentInput.files[0];
    if (!file) return;
    uploadingAttachment = true;
    attachButton.disabled = true;
    sendBtn.disabled = true;
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("context", "chat");
      const result = await Ultron.api("/api/documents/import", { method: "POST", body });
      pendingAttachment = {
        id: result.document.id,
        title: result.document.title,
        fileType: result.document.file_type,
      };
      attachmentName.textContent = `${result.document.title}${result.document.file_type}`;
      attachmentChip.hidden = false;
      Ultron.toast(result.document.file_type === ".docx"
        ? "Word text added. Layout is simplified for editing. Ask ultron what to change."
        : "File added. Ask ultron what to change.");
    } catch (error) {
      Ultron.toast(error.message, "error");
      attachmentInput.value = "";
    } finally {
      attachButton.disabled = false;
      sendBtn.disabled = streaming;
      uploadingAttachment = false;
    }
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
        body: {},
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

  messagesEl.querySelectorAll(".msg--user[data-document-title]").forEach((message) => {
    const meta = message.querySelector(".msg__meta");
    if (!meta || meta.querySelector(".msg__attachment")) return;
    const attachment = document.createElement("span");
    attachment.className = "msg__attachment";
    attachment.textContent = `FILE · ${message.dataset.documentTitle}`;
    meta.appendChild(attachment);
  });
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

  // Web search toggle chip
  const webChip = document.getElementById("chat-web-chip");
  let webSearchActive = (app.dataset.webSearch !== "0");
  if (webChip) {
    webChip.addEventListener("click", () => {
      webSearchActive = !webSearchActive;
      webChip.classList.toggle("is-active", webSearchActive);
      webChip.setAttribute("aria-pressed", webSearchActive ? "true" : "false");
    });
  }

})();

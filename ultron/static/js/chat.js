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
  const workspace = window.UltronWorkspace;

  let streaming = false;
  let activeController = null;
  let pendingAttachment = null;
  let uploadingAttachment = false;
  let pendingEmailDraft = false;
  let emailDraftActive = false;
  let emailDraftSource = "";
  let pendingDocumentEdit = false;
  let pendingDocumentRange = null;

  const looksLikeEmail = (text) => {
    const value = (text || "").trim();
    const headers = /^\s*(?:from|subject|to|date|cc):\s*.+/im.test(value);
    const greeting = /^(?:dear|hello|hi)\s+[^\n,]+[,\n]/im.test(value);
    const emailAddress = /[\w.+-]+@[\w.-]+\.[a-z]{2,}/i.test(value);
    const signoff = /\b(?:regards|best|sincerely|thank you|thanks),?\s*\n/i.test(value);
    const asksForReply = /\b(?:draft|write|compose|reply to|respond to)\b.{0,40}\b(?:email|message)\b/i.test(value);
    return (headers && value.length > 70) || (value.length > 100 && greeting && (emailAddress || signoff) && value.includes("?")) || (asksForReply && value.length > 120);
  };
  const emailRevision = (text) => /\b(?:make (?:it )?(?:shorter|longer|more professional|more natural|more polite|less formal|confident)|make it sound (?:more )?(?:natural|professional|confident|polite)|be (?:more )?(?:professional|natural|polite|confident)|decline (?:the )?invitation|accept (?:the )?offer|ask them for more information|revise (?:the )?(?:email|reply)|change the tone|add more detail)\b/i.test(text || "");
  const startsWritingRequest = (text) => /^\s*(?:(?:please|hey)\s+)*(?:(?:(?:can|could|would|will)\s+you(?:\s+please)?|i need you to|i want you to|i'd like you to|help me(?:\s+to)?|let'?s)\s+)?(?:write|draft|compose|author)\b/i.test(text || "");
  const explicitWriteRequest = (text) => /^\s*(?:(?:please|hey)\s+)*write\b/i.test(text || "");
  const documentIntent = (text) => {
    const value = text || "";
    const action = /\b(?:write|draft|create|make|compose|prepare|improve|rewrite|edit|format|turn|add|remove|delete|change|replace|update|revise|correct|adjust|insert|append|shorten|expand|fix|organize|build)\b/i.test(value);
    const artifact = /\b(?:document|essay|report|speech|study guide|business letter|meeting notes|proposal|memo|article|paragraph|introduction|conclusion|draft|manuscript|poem|poetry|story|blog post|newsletter|resume|cover letter|script|chapter|study notes|guide|letter)\b/i.test(value);
    const broadWritingRequest = startsWritingRequest(value) && !/\b(?:email|reply|message|python|javascript|typescript|code|function|class|sql|shell script)\b/i.test(value);
    const otherWorkspaceAction = /\b(?:calendar|event|reminder|python|javascript|typescript|function|class|code|sql|shell script)\b/i.test(value) && /\b(?:add|create|schedule|complete|delete|update|write|make|build)\b/i.test(value);
    const explicitDocumentWrite = explicitWriteRequest(value) && artifact && !otherWorkspaceAction;
    return (action && (artifact || broadWritingRequest) && !otherWorkspaceAction) || explicitDocumentWrite;
  };
  const documentEdit = (text) => /\b(?:write|draft|create|make|compose|prepare|improve|rewrite|edit|format|turn this into|add|remove|delete|change|replace|update|revise|correct|adjust|insert|append|shorten|expand|fix|organize|build)\b/i.test(text || "") && !/\b(?:explain|summarize|review|suggest|check|find)\b/i.test(text || "");
  const newDocumentRequest = (text) => {
    const value = text || "";
    const newWritingRequest = startsWritingRequest(value)
      && !/\b(?:email|reply|message|python|javascript|typescript|code|function|class|sql|shell script)\b/i.test(value);
    const existingDocumentReference = /\b(?:this|current|existing|same|the\s+document|introduction|conclusion|paragraph|section|heading)\b/i.test(value);
    return (newWritingRequest || (/\bmake\s+(?:me\s+)?(?:a|an|new)\b/i.test(value) && /\b(?:essay|report|speech|study guide|letter|proposal|memo|article|study notes|meeting notes|document|poem|poetry|story|blog post|newsletter|resume|cover letter|script|chapter|guide|something|anything|smth)\b/i.test(value))) && !existingDocumentReference;
  };
  const documentTitle = (text) => {
    const cleaned = (text || "").replace(/\s+/g, " ").trim();
    const about = cleaned.match(/\b(?:about|on|titled|called)\s+(.+?)\s*[.!?]*$/i)?.[1];
    return (about || cleaned).slice(0, 72).replace(/^["'“”]+|["'“”]+$/g, "") || "New document";
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
          pendingDocumentEdit = Boolean(message.dataset.documentId);
          pendingDocumentRange = pendingDocumentEdit ? workspace?.getSelectionRange() : null;
          if (emailDraftActive) pendingEmailDraft = true;
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

  const renderDocumentCard = (message, documentTitle = "Document") => {
    const documentId = message.dataset.documentId;
    if (!documentId) return;
    const body = message.querySelector(".msg__body");
    body.replaceChildren();
    body.classList.add("msg__body--file");
    const card = document.createElement("div");
    card.className = "msg-file-card";
    const icon = document.createElement("span");
    icon.className = "msg-file-card__icon";
    icon.textContent = "DOC";
    const name = document.createElement("span");
    name.className = "msg-file-card__name";
    name.textContent = `${documentTitle}.docx`;
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "msg-file-card__open";
    openButton.textContent = "Open";
    openButton.addEventListener("click", async () => {
      try { await workspace?.open(documentId, "document"); }
      catch (error) { Ultron.toast(error.message, "error"); }
    });
    const textDownload = document.createElement("a");
    textDownload.className = "msg-file-card__download";
    textDownload.href = `/api/documents/${documentId}/export?format=text`;
    textDownload.download = "";
    textDownload.textContent = "Download .txt";
    const wordDownload = document.createElement("a");
    wordDownload.className = "msg-file-card__download";
    wordDownload.href = `/api/documents/${documentId}/export?format=docx`;
    wordDownload.download = "";
    wordDownload.textContent = "Download .docx";
    card.append(icon, name, openButton, textDownload, wordDownload);
    card.addEventListener("click", (event) => {
      if (event.target.closest("a, button")) return;
      openButton.click();
    });
    body.appendChild(card);
    message.dataset.documentCard = "1";
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
            if (pendingDocumentEdit) {
              received += event.data.token || "";
            } else if (event.data.token && target.thinking) {
              target.thinking.remove();
              target.thinking = null;
              target.textSpan.hidden = false;
              target.cursor.hidden = false;
            }
            if (!pendingDocumentEdit) {
              received += event.data.token || "";
              target.textSpan.textContent = received;
              scrollBottom();
            }
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
            if (pendingDocumentEdit) {
              if (workspace) await workspace.setGeneratedContent(received, pendingDocumentRange);
              renderDocumentCard(target.wrap, event.data.document_title || "Document");
              pendingDocumentEdit = false;
              pendingDocumentRange = null;
            } else renderAssistant(target.wrap, received);
            applyTitle(event.data.title);
            markThreadCurrent();
            if (pendingEmailDraft && emailDraftActive && workspace) {
              workspace.captureEmail(received, emailDraftSource, target.wrap);
              pendingEmailDraft = false;
            }
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

  const startStream = async (content = null, documentId = null, documentSelection = "") => {
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
        body: JSON.stringify({ ...(content ? { content } : {}), document_id: documentId, document_selection: documentSelection, email_draft: pendingEmailDraft ? (workspace?.getEmailDraft() || "") : "", workspace_only: pendingDocumentEdit }),
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
      pendingDocumentEdit = false;
      pendingDocumentRange = null;
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

    if (/^write[.!]?$/i.test(content)) {
      try {
        const result = await Ultron.api("/api/documents", { method: "POST", body: { title: "Untitled document", content: "", format: "markdown" } });
        input.value = "";
        autoResize();
        await workspace?.open(result.document.id, "document");
        return;
      } catch (error) {
        Ultron.toast(`Could not open the document editor: ${error.message}`, "error");
        return;
      }
    }

    const incomingEmail = looksLikeEmail(content);
    const revisingEmail = emailDraftActive && emailRevision(content) && !incomingEmail;
    const documentRequest = !incomingEmail && !revisingEmail && (documentIntent(content) || (pendingAttachment && documentEdit(content)) || (workspace?.getDocumentId() && documentEdit(content)));
    let documentId = incomingEmail ? null : (pendingAttachment?.id || null);
    let documentSelection = "";

    if (incomingEmail) {
      emailDraftActive = true;
      emailDraftSource = content;
      pendingEmailDraft = true;
      workspace?.prepareEmail(content);
    } else if (revisingEmail) {
      pendingEmailDraft = true;
      emailDraftSource = workspace?.getEmailOriginal() || emailDraftSource;
    }

    if (documentRequest && workspace) {
      try {
        const startsNewDocument = newDocumentRequest(content);
        if (startsNewDocument) documentId = null;
        else documentId = documentId || workspace.getDocumentId();
        if (!documentId && !startsNewDocument) {
          const rememberedId = Number(sessionStorage.getItem("ultron-active-document") || 0);
          if (rememberedId && (documentIntent(content) || documentEdit(content))) documentId = rememberedId;
        }
        if (documentId) {
          await workspace.open(documentId, "document");
        } else {
          const created = await Ultron.api("/api/documents", { method: "POST", body: { title: documentTitle(content), content: "", format: "markdown" } });
          documentId = created.document.id;
          await workspace.open(documentId, "document");
        }
        pendingDocumentEdit = true;
        pendingDocumentRange = workspace.getSelectionRange();
        documentSelection = workspace.getSelection();
      } catch (error) {
        Ultron.toast(`Could not open the document workspace: ${error.message}`, "error");
        return;
      }
    }

    if (!conversationId) {
      sendBtn.disabled = true;
      try {
        const created = await Ultron.api("/api/conversations", {
          method: "POST",
          body: { first_message: content, document_id: documentId },
        });
        const query = new URLSearchParams({ autosend: "1" });
        if (documentId) query.set("doc", documentId);
        if (incomingEmail) query.set("email", "1");
        window.location.href = `/chat/${created.id}?${query}`;
      } catch (error) {
        sendBtn.disabled = false;
        pendingDocumentEdit = false;
        pendingDocumentRange = null;
        Ultron.toast(error.message, "error");
      }
      return;
    }

    input.value = "";
    autoResize();
    createMessage("user", content, documentId, pendingAttachment ? `${pendingAttachment.title}${pendingAttachment.fileType}` : "");
    pendingAttachment = null;
    attachmentChip.hidden = true;
    attachmentInput.value = "";
    await startStream(content, documentId, documentSelection);
  });

  document.addEventListener("ultron:email-regenerate", () => {
    if (streaming || !conversationId) return;
    emailDraftActive = true;
    pendingEmailDraft = true;
    emailDraftSource = workspace?.getEmailOriginal() || emailDraftSource;
    startStream(null);
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
      Ultron.toast(result.notice || (result.document.file_type === ".docx"
        ? "Word file added. Supported formatting is available in the document workspace; advanced layout may not be preserved."
        : "File added. Ask ultron what to change."));
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
    if (raw.trim() === "Document ready." && message.dataset.documentId) {
      const title = (message.dataset.documentTitle || "Document").replace(/\.(?:docx?|txt|md|markdown)$/i, "");
      renderDocumentCard(message, title);
      return;
    }
    body.dataset.rawText = raw;
    window.UltronMarkdown.render(body, raw);
    addMessageActions(message);
  });
  const persistedMessages = [...messagesEl.querySelectorAll(".msg")];
  const lastPersisted = persistedMessages[persistedMessages.length - 1];
  const persistedUserTexts = persistedMessages.filter((message) => message.classList.contains("msg--user")).map((message) => message.querySelector(".msg__body")?.dataset.rawText || message.querySelector(".msg__body")?.textContent || "");
  const latestPersistedUser = persistedUserTexts[persistedUserTexts.length - 1] || "";
  const previousEmail = [...persistedUserTexts].reverse().find(looksLikeEmail) || "";
  if (lastPersisted?.classList.contains("msg--assistant") && previousEmail && (looksLikeEmail(latestPersistedUser) || emailRevision(latestPersistedUser)) && workspace) {
    const lastReply = lastPersisted.querySelector(".msg__body")?.dataset.rawText || lastPersisted.querySelector(".msg__body")?.textContent || "";
    emailDraftActive = true;
    emailDraftSource = previousEmail;
    workspace.captureEmail(lastReply, previousEmail, lastPersisted);
  }
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
    const documentParam = params.get("doc");
    history.replaceState(null, "", `${window.location.pathname}${documentParam ? `?doc=${documentParam}` : ""}`);
    const allMessages = messagesEl.querySelectorAll(".msg");
    const last = allMessages[allMessages.length - 1];
    if (last && last.classList.contains("msg--user")) {
      const lastText = last.querySelector(".msg__body")?.textContent || "";
      if (params.get("email") === "1" || looksLikeEmail(lastText)) {
        emailDraftActive = true;
        pendingEmailDraft = true;
        emailDraftSource = lastText;
        workspace?.prepareEmail(lastText);
      }
      const docId = Number(documentParam || 0) || null;
      pendingDocumentEdit = Boolean(docId && (documentIntent(lastText) || documentEdit(lastText)));
      (async () => {
        if (docId) await workspace?.open(docId, "document");
        await startStream(null, docId, "");
      })().catch((error) => Ultron.toast(error.message, "error"));
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

/* Chat-integrated local document and email workspace. */
(() => {
  const app = document.getElementById("chat-app");
  const pane = document.getElementById("chat-workspace");
  if (!app || !pane) return;
  const title = document.getElementById("workspace-title");
  const content = document.getElementById("workspace-content");
  const preview = document.getElementById("workspace-preview");
  const status = document.getElementById("workspace-save-status");
  const editor = document.getElementById("workspace-document");
  const email = document.getElementById("workspace-email");
  const docTab = pane.querySelector('[data-work-kind="document"]');
  const emailTab = pane.querySelector('[data-work-kind="email"]');
  let docId = null;
  let docFormat = "markdown";
  let fileType = "";
  let dirty = false;
  let timer = null;
  let saving = null;
  let currentMode = "edit";
  let currentKind = "document";
  let originalEmail = "";
  let latestReplyMessage = null;
  const emailStorageKey = `ultron-email-draft-${app.dataset.conversationId || "new"}`;

  const setStatus = (value) => { status.textContent = value; };
  const countWords = () => { document.getElementById("workspace-word-count").textContent = `${(content.value.trim().match(/\S+/g) || []).length} words`; };
  const renderPreview = () => {
    if (window.UltronMarkdown) window.UltronMarkdown.render(preview, content.value);
    else preview.textContent = content.value;
  };
  const setMode = (mode) => {
    currentMode = mode;
    content.hidden = mode !== "edit";
    preview.hidden = mode !== "preview";
    pane.querySelectorAll("[data-work-mode]").forEach((button) => {
      const active = button.dataset.workMode === mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (mode === "preview") renderPreview();
  };
  const setKind = (kind) => {
    currentKind = kind;
    editor.hidden = kind !== "document";
    email.hidden = kind !== "email";
    docTab.classList.toggle("is-active", kind === "document");
    emailTab.classList.toggle("is-active", kind === "email");
    if (kind === "email") pane.classList.add("is-email");
    else pane.classList.remove("is-email");
  };
  const open = async (id, kind = "document") => {
    pane.hidden = false;
    app.classList.add("has-workspace");
    document.getElementById("workspace-splitter").hidden = false;
    pane.querySelectorAll("[data-mobile-view]").forEach((button) => button.hidden = window.innerWidth > 900);
    setKind(kind);
    if (id && Number(id) !== docId) {
      setStatus("Loading…");
      const result = await Ultron.api(`/api/documents/${id}`);
      const doc = result.document;
      docId = doc.id;
      title.value = doc.title;
      content.value = doc.content;
      docFormat = doc.format || "markdown";
      fileType = doc.file_type || "";
      dirty = false;
      setStatus("Saved locally");
      document.getElementById("workspace-export").href = `/api/documents/${docId}/export?format=docx`;
      history.replaceState(null, "", `${window.location.pathname}?doc=${docId}`);
      sessionStorage.setItem("ultron-active-document", String(docId));
      if (fileType.toLowerCase() === ".docx" && sessionStorage.getItem(`ultron-docx-note-${doc.id}`) !== "1") {
        sessionStorage.setItem(`ultron-docx-note-${doc.id}`, "1");
        Ultron.toast("Word import keeps supported text, headings, lists, and tables. Advanced Word-specific layout may not be preserved.");
      }
    }
    countWords();
    setMode(currentMode);
    if (window.innerWidth <= 900) setMobileView("workspace");
    if (kind === "document") content.focus();
  };
  const close = () => {
    pane.hidden = true;
    document.getElementById("workspace-splitter").hidden = true;
    app.classList.remove("has-workspace", "mobile-pane-workspace", "mobile-pane-chat");
    document.getElementById("workspace-mobile-open").hidden = true;
    const query = new URLSearchParams(window.location.search);
    if (query.has("doc")) {
      query.delete("doc");
      history.replaceState(null, "", `${window.location.pathname}${query.size ? `?${query}` : ""}`);
    }
  };
  const markDirty = () => {
    dirty = true;
    setStatus("Unsaved changes…");
    countWords();
    if (currentMode === "preview") renderPreview();
    clearTimeout(timer);
    timer = setTimeout(() => save(), 650);
  };
  const save = async (force = false) => {
    if (saving) { await saving; return dirty ? save(force) : true; }
    if (!dirty && docId && !force) return true;
    if (!force && !title.value.trim() && !content.value) return true;
    setStatus("Saving…");
    saving = (async () => {
      try {
        const payload = { title: title.value.trim() || "Untitled document", content: content.value, format: docFormat };
        const result = await Ultron.api(docId ? `/api/documents/${docId}` : "/api/documents", { method: docId ? "PATCH" : "POST", body: payload });
        docId = result.document.id;
        title.value = result.document.title;
        fileType = result.document.file_type || fileType;
        history.replaceState(null, "", `${window.location.pathname}?doc=${docId}`);
        sessionStorage.setItem("ultron-active-document", String(docId));
        document.getElementById("workspace-export").href = `/api/documents/${docId}/export?format=docx`;
        dirty = false;
        setStatus("Saved locally");
        return true;
      } catch (error) {
        setStatus("Save failed");
        Ultron.toast(error.message, "error");
        return false;
      } finally { saving = null; }
    })();
    return saving;
  };
  const setMobileView = (view) => {
    app.classList.toggle("mobile-pane-workspace", view === "workspace");
    app.classList.toggle("mobile-pane-chat", view === "chat");
    pane.querySelectorAll("[data-mobile-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.mobileView === view));
    document.getElementById("workspace-mobile-open").hidden = view === "workspace" || window.innerWidth > 900;
  };

  pane.querySelectorAll("[data-work-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.workMode)));
  pane.querySelectorAll("[data-work-kind]").forEach((button) => button.addEventListener("click", () => setKind(button.dataset.workKind)));
  pane.querySelectorAll("[data-mobile-view]").forEach((button) => button.addEventListener("click", () => setMobileView(button.dataset.mobileView)));
  document.getElementById("workspace-close").addEventListener("click", close);
  document.getElementById("workspace-mobile-open").addEventListener("click", () => setMobileView("workspace"));
  document.getElementById("workspace-save").addEventListener("click", () => save(true));
  document.getElementById("workspace-open-library").addEventListener("click", () => { save().then(() => { window.location.href = docId ? `/documents?doc=${docId}` : "/documents"; }); });
  title.addEventListener("input", markDirty);
  content.addEventListener("input", markDirty);
  content.addEventListener("select", () => {});
  document.getElementById("workspace-export").addEventListener("click", async (event) => {
    if (dirty || !docId) { event.preventDefault(); if (await save(true) && docId) window.location.assign(`/api/documents/${docId}/export?format=docx`); }
  });
  const parseEmailHeaders = (source) => {
    const from = source.match(/^\s*From:\s*(.+)$/im)?.[1]?.trim() || "";
    let subject = source.match(/^\s*Subject:\s*(.+)$/im)?.[1]?.trim() || "";
    if (subject && !/^re:/i.test(subject)) subject = `Re: ${subject}`;
    const emailAddress = from.match(/<([^>]+)>/)?.[1] || from.match(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/i)?.[0] || from;
    return { recipient: emailAddress, subject };
  };
  const readSavedEmail = (source) => {
    try {
      const saved = JSON.parse(localStorage.getItem(emailStorageKey) || "null");
      return saved && saved.source === source ? saved : null;
    } catch { return null; }
  };
  const saveEmailDraft = () => {
    try {
      localStorage.setItem(emailStorageKey, JSON.stringify({
        source: originalEmail,
        recipient: document.getElementById("email-recipient").value,
        subject: document.getElementById("email-subject").value,
        reply: document.getElementById("email-reply").value,
      }));
    } catch { /* private browsing may disable local storage */ }
  };
  const setEmailDraft = (reply, source, message) => {
    const changedSource = Boolean(source && source !== originalEmail);
    originalEmail = source || originalEmail;
    const parsed = parseEmailHeaders(originalEmail);
    const saved = readSavedEmail(originalEmail);
    if (changedSource || !document.getElementById("email-recipient").value) document.getElementById("email-recipient").value = saved?.recipient ?? parsed.recipient;
    if (changedSource || !document.getElementById("email-subject").value) document.getElementById("email-subject").value = saved?.subject ?? parsed.subject;
    document.getElementById("email-reply").value = changedSource && saved ? (saved.reply || reply.trim()) : reply.trim();
    document.getElementById("email-status").textContent = "Draft ready. Review it before copying; nothing has been sent.";
    const original = document.getElementById("email-original-content");
    if (original) original.textContent = originalEmail;
    saveEmailDraft();
    latestReplyMessage = message || latestReplyMessage;
    emailTab.hidden = false;
    pane.hidden = false;
    app.classList.add("has-workspace");
    document.getElementById("workspace-splitter").hidden = false;
    setKind("email");
    if (window.innerWidth <= 900) setMobileView("workspace");
  };
  const prepareEmail = (source) => {
    const changedSource = Boolean(source && source !== originalEmail);
    originalEmail = source || originalEmail;
    const parsed = parseEmailHeaders(originalEmail);
    const saved = readSavedEmail(originalEmail);
    if (changedSource || !document.getElementById("email-recipient").value) document.getElementById("email-recipient").value = saved?.recipient ?? parsed.recipient;
    if (changedSource || !document.getElementById("email-subject").value) document.getElementById("email-subject").value = saved?.subject ?? parsed.subject;
    if (saved) document.getElementById("email-reply").value = saved.reply || "";
    document.getElementById("email-original-content").textContent = originalEmail;
    emailTab.hidden = false;
    pane.hidden = false;
    app.classList.add("has-workspace");
    document.getElementById("workspace-splitter").hidden = false;
    setKind("email");
    if (window.innerWidth <= 900) setMobileView("workspace");
  };
  const copyReply = async () => {
    const to = document.getElementById("email-recipient").value.trim();
    const sub = document.getElementById("email-subject").value.trim();
    const body = document.getElementById("email-reply").value.trim();
    const full = `${to ? `To: ${to}\n` : ""}${sub ? `Subject: ${sub}\n\n` : ""}${body}`;
    try { await navigator.clipboard.writeText(full); document.getElementById("email-status").textContent = "Reply copied. Review and send it from your email app."; }
    catch { Ultron.toast("Clipboard access is unavailable in this browser.", "error"); }
  };
  document.getElementById("email-copy").addEventListener("click", copyReply);
  ["email-recipient", "email-subject", "email-reply"].forEach((id) => document.getElementById(id).addEventListener("input", () => {
    saveEmailDraft();
    document.getElementById("email-status").textContent = "Edited locally · not sent";
  }));
  document.getElementById("email-regenerate").addEventListener("click", () => {
    document.dispatchEvent(new CustomEvent("ultron:email-regenerate"));
    document.getElementById("email-status").textContent = "Regenerating with the current local model…";
  });
  document.getElementById("email-insert-document").addEventListener("click", async () => {
    try {
      if (!docId) {
        const result = await Ultron.api("/api/documents", { method: "POST", body: { title: document.getElementById("email-subject").value || "Email reply draft", content: document.getElementById("email-reply").value, format: "markdown" } });
        docId = result.document.id;
      } else {
        const separator = content.value && !content.value.endsWith("\n") ? "\n\n" : "";
        content.value += separator + document.getElementById("email-reply").value;
        markDirty();
        await save();
      }
      await open(docId, "document");
      document.getElementById("workspace-insert-email").hidden = true;
    } catch (error) { Ultron.toast(error.message, "error"); }
  });
  document.getElementById("workspace-insert-email").addEventListener("click", () => {
    content.value += `${content.value && !content.value.endsWith("\n") ? "\n\n" : ""}${document.getElementById("email-reply").value}`;
    markDirty();
    setKind("document");
  });
  const splitter = document.getElementById("workspace-splitter");
  splitter.removeAttribute("tabindex");
  window.addEventListener("resize", () => {
    pane.querySelectorAll("[data-mobile-view]").forEach((button) => button.hidden = window.innerWidth > 900);
    if (window.innerWidth > 900) app.classList.remove("mobile-pane-workspace", "mobile-pane-chat");
  });

  const params = new URLSearchParams(window.location.search);
  const initialId = Number(params.get("doc") || 0);
  if (initialId) open(initialId).catch((error) => Ultron.toast(error.message, "error"));
  else if (params.get("newdoc") === "1") {
    Ultron.api("/api/documents", { method: "POST", body: { title: "Untitled document", content: "", format: "markdown" } })
      .then((result) => open(result.document.id))
      .catch((error) => Ultron.toast(error.message, "error"));
  }
  window.UltronWorkspace = {
    open,
    close,
    getDocumentId: () => docId,
    getSelection: () => content.selectionEnd > content.selectionStart ? content.value.slice(content.selectionStart, content.selectionEnd) : "",
    getSelectionRange: () => content.selectionEnd > content.selectionStart ? { start: content.selectionStart, end: content.selectionEnd, text: content.value.slice(content.selectionStart, content.selectionEnd) } : null,
    save,
    setGeneratedContent: async (text, selectionRange = null) => {
      if (!docId) return;
      const normalized = text.trim()
        .replace(/^```[\w+-]*\s*\n([\s\S]*?)\n```\s*$/, "$1")
        .replace(/^(?:(?:okay|sure)[,!]?\s+)?(?:let'?s|here'?s|i'?ve written|i wrote)[^\n]*(?:\n\s*\n|\n)/i, "")
        .replace(/\n\s*(?:hope you (?:enjoy|like) it|let me know if you(?:'d| would) like[^\n]*|is there anything else[^\n]*|anything else i can help with[^\n]*)[.!?\s]*$/i, "");
      const start = selectionRange && content.value.slice(selectionRange.start, selectionRange.end) === selectionRange.text
        ? selectionRange.start : 0;
      const end = selectionRange && start === selectionRange.start ? selectionRange.end : content.value.length;
      const prefix = content.value.slice(0, start);
      const suffix = content.value.slice(end);
      const delay = Math.min(8, 2400 / Math.max(normalized.length, 1));
      content.value = prefix + suffix;
      content.focus();
      for (let index = 0; index < normalized.length; index += 1) {
        content.value = prefix + normalized.slice(0, index + 1) + suffix;
        if (index % 32 === 0 || index === normalized.length - 1) {
          countWords();
          content.scrollTop = content.scrollHeight;
        }
        await new Promise((resolve) => window.setTimeout(resolve, delay));
      }
      dirty = true;
      countWords();
      setStatus("AI updated document · saving version…");
      const ok = await save(true);
      document.getElementById("workspace-insert-email").hidden = currentKind !== "email";
      return ok;
    },
    captureEmail: setEmailDraft,
    prepareEmail,
    getEmailDraft: () => document.getElementById("email-reply").value,
    hasEmailDraft: () => Boolean(document.getElementById("email-reply").value),
    getEmailOriginal: () => originalEmail,
  };
})();

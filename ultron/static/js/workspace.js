/* Chat-integrated local document and email workspace. */
(() => {
  const app = document.getElementById("chat-app");
  const pane = document.getElementById("chat-workspace");
  if (!app || !pane) return;
  const title = document.getElementById("workspace-title");
  const content = document.getElementById("workspace-content");
  const preview = document.getElementById("workspace-preview");
  const status = document.getElementById("workspace-save-status");
  const versionSelect = document.getElementById("workspace-version-select");
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
      await loadVersions();
      if (fileType.toLowerCase() === ".docx" && sessionStorage.getItem(`ultron-docx-note-${doc.id}`) !== "1") {
        sessionStorage.setItem(`ultron-docx-note-${doc.id}`, "1");
        Ultron.toast("Word import keeps supported text, headings, lists, and tables. Advanced Word-specific layout may not be preserved.");
      }
    }
    countWords();
    setMode(currentMode);
    if (window.innerWidth <= 900) setMobileView("workspace");
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
        await loadVersions();
        return true;
      } catch (error) {
        setStatus("Save failed");
        Ultron.toast(error.message, "error");
        return false;
      } finally { saving = null; }
    })();
    return saving;
  };
  const loadVersions = async () => {
    if (!docId) return;
    try {
      const result = await Ultron.api(`/api/documents/${docId}/versions`);
      versionSelect.replaceChildren(new Option("History…", ""));
      result.versions.forEach((version) => versionSelect.add(new Option(`${version.created_at} · ${version.title}`, version.id)));
    } catch { /* history is optional on an older local database */ }
  };
  const setMobileView = (view) => {
    app.classList.toggle("mobile-pane-workspace", view === "workspace");
    app.classList.toggle("mobile-pane-chat", view === "chat");
    pane.querySelectorAll("[data-mobile-view]").forEach((button) => button.classList.toggle("is-active", button.dataset.mobileView === view));
    document.getElementById("workspace-mobile-open").hidden = view === "workspace" || window.innerWidth > 900;
  };

  const templates = {
    essay: "# Essay Title\n\n## Introduction\n\n## Main Argument\n\n## Supporting Points\n\n## Conclusion\n",
    academic: "# Academic Report Title\n\n**Author:** [Name]  \n**Date:** [Date]\n\n## Abstract\n\n## Introduction\n\n## Method\n\n## Findings\n\n## Discussion\n\n## Conclusion\n\n## References\n",
    professional: "# Professional Report\n\n**Prepared for:** [Audience]  \n**Prepared by:** [Name]  \n**Date:** [Date]\n\n## Executive Summary\n\n## Background\n\n## Analysis\n\n## Recommendations\n\n## Conclusion\n",
    speech: "# Speech Title\n\n*[Occasion or audience]*\n\n## Opening\n\n## Main Message\n\n## Supporting Stories\n\n## Closing\n",
    letter: "[Your name]\n[Your address]\n[Date]\n\n[Recipient name]\n[Organization]\n\nDear [Name],\n\n[Message]\n\nSincerely,\n[Your name]\n",
    meeting: "# Meeting Notes\n\n**Date:** [Date]  \n**Attendees:** [Names]\n\n## Agenda\n\n## Discussion\n\n## Decisions\n\n## Action Items\n",
    study: "# Study Guide: [Topic]\n\n## Learning Objectives\n\n## Key Concepts\n\n## Detailed Notes\n\n## Examples\n\n## Review Questions\n\n## Quick Summary\n",
  };
  const surround = (before, after = before) => {
    const start = content.selectionStart;
    const end = content.selectionEnd;
    const selected = content.value.slice(start, end) || "text";
    content.setRangeText(`${before}${selected}${after}`, start, end, "select");
    content.focus();
    markDirty();
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
  pane.querySelectorAll("[data-format]").forEach((button) => button.addEventListener("click", () => {
    const format = button.dataset.format;
    if (format === "bold") surround("**");
    else if (format === "italic") surround("*");
    else if (format === "strike") surround("~~");
    else if (format === "underline") surround("++");
    else if (format.startsWith("align-")) {
      const align = format.slice(6);
      const start = content.selectionStart;
      const end = content.selectionEnd;
      const selected = content.value.slice(start, end) || "Text";
      content.setRangeText(`:::${align}\n${selected}\n:::`, start, end, "select");
      content.focus();
      markDirty();
    }
    else if (format === "heading") surround("## ", "");
    else if (format === "bullet") surround("- ", "");
    else if (format === "number") surround("1. ", "");
    else if (format === "table") { content.setRangeText("| Heading | Heading |\n| --- | --- |\n| Detail | Detail |", content.selectionStart, content.selectionEnd, "end"); content.focus(); markDirty(); }
    else if (format === "pagebreak") { content.setRangeText("\n\n\\pagebreak\n\n", content.selectionStart, content.selectionEnd, "end"); content.focus(); markDirty(); }
  }));
  document.getElementById("workspace-template").addEventListener("change", (event) => {
    const value = event.target.value;
    if (!value || !templates[value]) return;
    if (content.value && !window.confirm("Replace the current content with this template?")) { event.target.value = ""; return; }
    content.value = templates[value];
    docFormat = "markdown";
    event.target.value = "";
    markDirty();
  });
  document.getElementById("workspace-restore").addEventListener("click", async () => {
    if (!docId || !versionSelect.value) return;
    if (!window.confirm("Restore this version? The current version will remain in history.")) return;
    try {
      const response = await Ultron.api(`/api/documents/${docId}/versions/${versionSelect.value}/restore`, { method: "POST", body: {} });
      title.value = response.document.title;
      content.value = response.document.content;
      docFormat = response.document.format;
      dirty = false;
      setStatus("Version restored");
      countWords();
      await loadVersions();
    } catch (error) { Ultron.toast(error.message, "error"); }
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
  document.getElementById("workspace-find-button").addEventListener("click", () => {
    const needle = document.getElementById("workspace-find").value;
    if (!needle) return;
    const position = content.value.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase(), content.selectionEnd);
    if (position < 0) { Ultron.toast("No further match found."); return; }
    content.focus();
    content.setSelectionRange(position, position + needle.length);
  });
  document.getElementById("workspace-replace-button").addEventListener("click", () => {
    const needle = document.getElementById("workspace-find").value;
    if (!needle) return;
    const next = content.value.replaceAll(needle, document.getElementById("workspace-replace").value);
    if (next !== content.value) { content.value = next; markDirty(); }
  });
  document.getElementById("workspace-delete").addEventListener("click", async () => {
    if (!docId || !window.confirm("Delete this document and its version history? This cannot be undone.")) return;
    try {
      await Ultron.api(`/api/documents/${docId}`, { method: "DELETE" });
      sessionStorage.removeItem("ultron-active-document");
      docId = null;
      title.value = "";
      content.value = "";
      dirty = false;
      close();
      Ultron.toast("Document deleted.");
    } catch (error) { Ultron.toast(error.message, "error"); }
  });

  const splitter = document.getElementById("workspace-splitter");
  splitter.addEventListener("pointerdown", (event) => {
    if (window.innerWidth <= 900) return;
    splitter.setPointerCapture(event.pointerId);
    const move = (pointerEvent) => {
      const rect = app.getBoundingClientRect();
      const local = pointerEvent.clientX - rect.left;
      const railWidth = 0;
      const available = rect.width - railWidth - 6;
      const chatWidth = Math.min(Math.max(local - railWidth, 320), available - 380);
      app.style.gridTemplateColumns = `0 ${chatWidth}px 6px ${available - chatWidth}px`;
    };
    const stop = () => { splitter.removeEventListener("pointermove", move); splitter.removeEventListener("pointerup", stop); };
    splitter.addEventListener("pointermove", move);
    splitter.addEventListener("pointerup", stop, { once: true });
  });
  splitter.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const rect = app.getBoundingClientRect();
    const current = app.querySelector(".chat-panel").getBoundingClientRect().width;
    const next = Math.min(Math.max(current + (event.key === "ArrowRight" ? 24 : -24), 320), rect.width - 386);
    app.style.gridTemplateColumns = `0 ${next}px 6px ${rect.width - next - 6}px`;
  });
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
      const normalized = text.trim().replace(/^```[\w+-]*\s*\n([\s\S]*?)\n```\s*$/, "$1");
      if (selectionRange && content.value.slice(selectionRange.start, selectionRange.end) === selectionRange.text) {
        content.setRangeText(normalized, selectionRange.start, selectionRange.end, "end");
      } else content.value = normalized;
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

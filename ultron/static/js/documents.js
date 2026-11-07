/* Documents — local library, autosaving editor, and approval-based AI suggestions. */

(() => {
  const app = document.getElementById("documents-app");
  if (!app) return;

  const form = document.getElementById("editor-form");
  const empty = document.getElementById("editor-empty");
  const titleInput = document.getElementById("doc-title");
  const contentInput = document.getElementById("doc-content");
  const folderInput = document.getElementById("doc-folder");
  const formatInput = document.getElementById("doc-format");
  const status = document.getElementById("doc-status");
  const count = document.getElementById("doc-count");
  const updated = document.getElementById("doc-updated");
  const saveButton = document.getElementById("doc-save");
  const deleteButton = document.getElementById("doc-delete");
  const searchInput = document.getElementById("doc-search");
  const folderFilter = document.getElementById("doc-folder-filter");
  const list = document.getElementById("doc-list");
  const listEmpty = document.getElementById("doc-filter-empty");
  const preview = document.getElementById("doc-preview");
  const assistant = document.getElementById("doc-assistant");
  const aiAction = document.getElementById("doc-ai-action");
  const aiInstruction = document.getElementById("doc-ai-instruction");
  const aiRun = document.getElementById("doc-ai-run");
  const aiStop = document.getElementById("doc-ai-stop");
  const aiSelection = document.getElementById("doc-ai-selection");
  const aiStatus = document.getElementById("doc-ai-status");
  const suggestionPanel = document.getElementById("doc-suggestion");
  const suggestionBody = document.getElementById("doc-suggestion-body");
  const suggestionAccept = document.getElementById("doc-ai-accept");
  const suggestionReject = document.getElementById("doc-ai-reject");
  const exportButton = document.getElementById("doc-export-btn");
  const importButton = document.getElementById("doc-import-btn");
  const importFileInput = document.getElementById("doc-import-file");
  const folderDialog = document.getElementById("folder-dialog");
  const folderForm = document.getElementById("folder-form");
  const folderName = document.getElementById("folder-name");
  const folderError = document.getElementById("folder-error");

  let currentId = null;
  let dirty = false;
  let revision = 0;
  let savePromise = null;
  let saveTimer = null;
  let searchTimer = null;
  let aiController = null;
  let suggestion = null;
  let lastSelection = null;

  const wordCount = (text) => (text.trim().match(/\S+/g) || []).length;

  const formatDateTime = (value) => {
    if (!value) return "";
    const date = new Date(value.replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return value;
    return `${date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })} · ${date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
  };

  const setStatus = (message, isDirty = false) => {
    status.textContent = message;
    status.classList.toggle("is-dirty", isDirty);
  };

  const updateCount = () => {
    const words = wordCount(contentInput.value);
    count.textContent = `${words} word${words === 1 ? "" : "s"}`;
  };

  const selectedFolder = () => folderFilter.value;

  const updateActive = () => {
    list.querySelectorAll(".doc-item").forEach((item) => {
      item.classList.toggle("is-active", Number(item.dataset.docId) === currentId);
    });
  };

  const renderList = (documents) => {
    list.querySelectorAll(".doc-item").forEach((item) => item.remove());
    documents.forEach((doc) => {
      const item = document.createElement("a");
      item.className = `doc-item${doc.id === currentId ? " is-active" : ""}`;
      item.href = `/documents?doc=${doc.id}`;
      item.dataset.docId = doc.id;
      item.setAttribute("role", "listitem");
      const title = document.createElement("span");
      title.className = "doc-item__title";
      title.textContent = doc.title;
      const meta = document.createElement("span");
      meta.className = "doc-item__meta";
      const date = formatDateTime(doc.updated_at) || "Not saved";
      meta.textContent = `${date} · ${(doc.file_type || doc.format).replace(/^\./, "").toUpperCase()}`;
      item.append(title, meta);
      list.insertBefore(item, listEmpty);
    });
    listEmpty.hidden = documents.length > 0;
  };

  const refreshList = async () => {
    const params = new URLSearchParams();
    const query = searchInput.value.trim();
    const folder = selectedFolder();
    if (query) params.set("q", query);
    if (folder) params.set("folder", folder);
    try {
      const result = await Ultron.api(`/api/documents?${params}`);
      renderList(result.documents);
    } catch (error) {
      Ultron.toast(error.message, "error");
    }
  };

  const renderPreview = () => {
    if (formatInput.value === "markdown" && window.UltronMarkdown) {
      UltronMarkdown.render(preview, contentInput.value);
      return;
    }
    preview.classList.remove("is-markdown");
    preview.replaceChildren();
    const plain = document.createElement("pre");
    plain.textContent = contentInput.value;
    preview.appendChild(plain);
  };

  const setMode = (mode) => {
    const showPreview = mode === "preview";
    contentInput.hidden = showPreview;
    preview.hidden = !showPreview;
    document.querySelectorAll("[data-doc-mode]").forEach((button) => {
      const active = button.dataset.docMode === mode;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    if (showPreview) renderPreview();
  };

  const setSuggestion = (text, detail) => {
    suggestion = detail ? { text, ...detail } : null;
    suggestionPanel.hidden = !suggestion;
    suggestionBody.replaceChildren();
    if (!suggestion) return;
    if (formatInput.value === "markdown" && window.UltronMarkdown) {
      UltronMarkdown.render(suggestionBody, text);
    } else {
      suggestionBody.textContent = text;
    }
    const inserts = ["ask", "explain", "ideas"].includes(suggestion.action);
    suggestionAccept.textContent = inserts ? "Insert answer" : "Accept";
  };

  const markDirty = () => {
    dirty = true;
    revision += 1;
    setStatus(currentId ? "Unsaved changes" : "New document · unsaved", true);
    if (!preview.hidden) renderPreview();
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => saveDocument(), 700);
  };

  const saveDocument = async (force = false) => {
    if (savePromise) {
      const saved = await savePromise;
      if (!saved) return false;
      if (dirty) return saveDocument(force);
      return true;
    }
    if (!dirty && currentId !== null) return true;
    if (!force && currentId === null && !titleInput.value.trim() && !contentInput.value) return true;

    const savedRevision = revision;
    const creating = currentId === null;
    const payload = {
      title: titleInput.value.trim() || "Untitled document",
      content: contentInput.value,
      folder_id: folderInput.value || null,
      format: formatInput.value,
    };
    saveButton.disabled = true;
    setStatus("Saving…", true);
    savePromise = (async () => {
      try {
        const result = await Ultron.api(
          creating ? "/api/documents" : `/api/documents/${currentId}`,
          { method: creating ? "POST" : "PATCH", body: payload }
        );
        const savedDoc = result.document;
        currentId = savedDoc.id;
        titleInput.value = savedDoc.title;
        folderInput.value = savedDoc.folder_id || "";
        history.replaceState(null, "", `/documents?doc=${currentId}`);
        assistant.hidden = false;
        deleteButton.hidden = false;
        if (exportButton) {
          exportButton.href = `/api/documents/${currentId}/export`;
          exportButton.style.display = "inline-flex";
        }
        updated.textContent = `Updated ${formatDateTime(savedDoc.updated_at)}`;
        if (revision === savedRevision) {
          dirty = false;
          setStatus("Saved locally");
        }
        await refreshList();
        updateActive();
        return true;
      } catch (error) {
        setStatus("Save failed", true);
        Ultron.toast(error.message, "error");
        return false;
      } finally {
        saveButton.disabled = false;
        savePromise = null;
      }
    })();
    const saved = await savePromise;
    if (saved && dirty) return saveDocument(force);
    return saved;
  };

  const fillDocument = (doc) => {
    currentId = doc.id;
    titleInput.value = doc.title;
    contentInput.value = doc.content;
    folderInput.value = doc.folder_id || "";
    formatInput.value = doc.format || "markdown";
    form.hidden = false;
    empty.hidden = true;
    assistant.hidden = false;
    deleteButton.hidden = false;
    if (exportButton) {
      exportButton.href = `/api/documents/${doc.id}/export`;
      exportButton.style.display = "inline-flex";
    }
    dirty = false;
    revision += 1;
    setStatus("Saved locally");
    updateCount();
    updated.textContent = `Updated ${formatDateTime(doc.updated_at)}`;
    history.replaceState(null, "", `/documents?doc=${doc.id}`);
    updateActive();
    setSuggestion(null);
    setMode("edit");
    aiStatus.textContent = "";
  };

  const openNew = async () => {
    if (dirty && !(await saveDocument())) return;
    currentId = null;
    dirty = false;
    revision += 1;
    form.reset();
    titleInput.value = "";
    contentInput.value = "";
    folderInput.value = /^\d+$/.test(selectedFolder()) ? selectedFolder() : "";
    formatInput.value = "markdown";
    form.hidden = false;
    empty.hidden = true;
    assistant.hidden = false;
    deleteButton.hidden = true;
    setStatus("Not saved yet");
    updateCount();
    updated.textContent = "";
    setSuggestion(null);
    setMode("edit");
    updateActive();
    history.replaceState(null, "", "/documents?new=1");
    titleInput.focus();
  };

  const loadDocument = async (id) => {
    if (Number(id) === currentId) return;
    if (dirty && !(await saveDocument())) return;
    try {
      const result = await Ultron.api(`/api/documents/${id}`);
      fillDocument(result.document);
    } catch (error) {
      Ultron.toast(error.message, "error");
    }
  };

  document.querySelectorAll("#new-document-btn, #new-document-btn-rail, #empty-new-document").forEach((button) => {
    button.addEventListener("click", openNew);
  });

  list.addEventListener("click", (event) => {
    const item = event.target.closest(".doc-item");
    if (!item) return;
    event.preventDefault();
    loadDocument(Number(item.dataset.docId));
  });

  searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(refreshList, 250);
  });
  folderFilter.addEventListener("change", () => {
    const query = new URLSearchParams();
    if (folderFilter.value && folderFilter.value !== "none") query.set("folder", folderFilter.value);
    history.replaceState(null, "", `/documents${query.size ? `?${query}` : ""}`);
    refreshList();
  });

  titleInput.addEventListener("input", markDirty);
  contentInput.addEventListener("input", () => {
    lastSelection = null;
    markDirty();
    updateCount();
    updateSelectionHint();
  });
  contentInput.addEventListener("select", updateSelectionHint);
  contentInput.addEventListener("keyup", updateSelectionHint);
  folderInput.addEventListener("change", markDirty);
  formatInput.addEventListener("change", () => {
    markDirty();
    if (!preview.hidden) renderPreview();
  });
  document.querySelectorAll("[data-doc-mode]").forEach((button) => {
    button.addEventListener("click", () => setMode(button.dataset.docMode));
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    saveDocument(true);
  });

  exportButton?.addEventListener("click", async (event) => {
    if (!dirty) return;
    event.preventDefault();
    if (!(await saveDocument())) return;
    window.location.assign(exportButton.href);
  });

  deleteButton.addEventListener("click", async () => {
    if (currentId === null || !window.confirm("Delete this document? This cannot be undone.")) return;
    try {
      await Ultron.api(`/api/documents/${currentId}`, { method: "DELETE" });
      currentId = null;
      dirty = false;
      form.hidden = true;
      assistant.hidden = true;
      empty.hidden = false;
      history.replaceState(null, "", "/documents");
      await refreshList();
    } catch (error) {
      Ultron.toast(error.message, "error");
    }
  });

  document.getElementById("new-folder-btn").addEventListener("click", () => {
    folderName.value = "";
    folderError.hidden = true;
    Ultron.openDialog(folderDialog);
    folderName.focus();
  });
  folderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await Ultron.api("/api/document-folders", {
        method: "POST",
        body: { name: folderName.value.trim() },
      });
      const option = document.createElement("option");
      option.value = result.folder.id;
      option.textContent = result.folder.name;
      folderFilter.appendChild(option.cloneNode(true));
      folderInput.appendChild(option);
      folderInput.value = String(result.folder.id);
      if (!form.hidden) markDirty();
      folderDialog.close();
    } catch (error) {
      folderError.textContent = error.message;
      folderError.hidden = false;
    }
  });

  function updateSelectionHint() {
    const hasSelection = contentInput.selectionEnd > contentInput.selectionStart;
    if (hasSelection) {
      lastSelection = {
        start: contentInput.selectionStart,
        end: contentInput.selectionEnd,
        text: contentInput.value.slice(contentInput.selectionStart, contentInput.selectionEnd),
      };
    }
    aiSelection.textContent = hasSelection
      ? `${contentInput.selectionEnd - contentInput.selectionStart} characters selected for the next suggestion.`
      : "Select text in the editor to target a specific passage.";
  }

  const parseSse = (raw) => {
    let name = "message";
    const lines = [];
    raw.split("\n").forEach((line) => {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) lines.push(line.slice(5).replace(/^ /, ""));
    });
    if (!lines.length) return null;
    try { return { name, data: JSON.parse(lines.join("\n")) }; } catch { return null; }
  };

  const showSuggestionText = (text) => {
    suggestionBody.replaceChildren();
    if (formatInput.value === "markdown" && window.UltronMarkdown) {
      UltronMarkdown.render(suggestionBody, text);
    } else {
      suggestionBody.textContent = text;
    }
  };

  const requestSuggestion = async () => {
    if (currentId === null) {
      const saved = await saveDocument(true);
      if (!saved || currentId === null) return;
    } else if (dirty && !(await saveDocument())) {
      return;
    }
    const action = aiAction.value;
    const instruction = aiInstruction.value.trim();
    let selectionStart = contentInput.selectionStart;
    let selectionEnd = contentInput.selectionEnd;
    if (selectionEnd <= selectionStart && lastSelection) {
      const currentSelection = contentInput.value.slice(lastSelection.start, lastSelection.end);
      if (currentSelection === lastSelection.text) {
        selectionStart = lastSelection.start;
        selectionEnd = lastSelection.end;
      }
    }
    const selectedText = selectionEnd > selectionStart
      ? contentInput.value.slice(selectionStart, selectionEnd)
      : "";
    const original = contentInput.value;
    setSuggestion(null);
    aiStatus.textContent = "Generating a preview…";
    aiRun.disabled = true;
    aiStop.hidden = false;
    aiController = new AbortController();
    let buffer = "";
    let suggestionText = "";
    let completed = false;

    try {
      const response = await fetch(`/api/documents/${currentId}/assist`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ action, instruction, selection: selectedText }),
        signal: aiController.signal,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Request failed (${response.status}).`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const event = parseSse(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 2);
          if (event?.name === "token") {
            suggestionText += event.data.token || "";
            suggestionBody.textContent = suggestionText;
          } else if (event?.name === "error") {
            throw new Error(event.data.error || "The local model could not make a suggestion.");
          } else if (event?.name === "done") {
            suggestionText = event.data.suggestion || suggestionText;
            completed = true;
          }
          boundary = buffer.indexOf("\n\n");
        }
      }
      if (!completed || !suggestionText.trim()) throw new Error("The suggestion ended before it was complete.");
      showSuggestionText(suggestionText);
      setSuggestion(suggestionText, {
        action,
        original,
        selectionStart,
        selectionEnd,
      });
      aiStatus.textContent = "Review the preview. Your document has not been changed.";
    } catch (error) {
      if (error.name === "AbortError") {
        aiStatus.textContent = "Suggestion stopped. The document is unchanged.";
      } else {
        aiStatus.textContent = error.message || "The suggestion failed.";
      }
    } finally {
      aiController = null;
      aiRun.disabled = false;
      aiStop.hidden = true;
    }
  };

  aiRun.addEventListener("click", requestSuggestion);
  aiStop.addEventListener("click", () => aiController?.abort());
  suggestionReject.addEventListener("click", () => {
    setSuggestion(null);
    aiStatus.textContent = "Suggestion rejected. The document is unchanged.";
  });
  suggestionAccept.addEventListener("click", () => {
    if (!suggestion) return;
    if (contentInput.value !== suggestion.original) {
      aiStatus.textContent = "The document changed after this preview. Generate a fresh suggestion before accepting.";
      return;
    }
    const { text, action, selectionStart, selectionEnd } = suggestion;
    const insertOnly = ["ask", "explain", "ideas"].includes(action);
    if (action === "continue") {
      const separator = contentInput.value && !contentInput.value.endsWith("\n") ? "\n\n" : "";
      contentInput.value += separator + text;
      contentInput.setSelectionRange(contentInput.value.length, contentInput.value.length);
    } else if (insertOnly) {
      const position = selectionEnd;
      const before = contentInput.value.slice(0, position);
      const after = contentInput.value.slice(position);
      const inserted = `${before && !before.endsWith("\n") ? "\n\n" : ""}${text}${after && !after.startsWith("\n") ? "\n\n" : ""}`;
      contentInput.value = before + inserted + after;
      const cursor = before.length + inserted.length;
      contentInput.setSelectionRange(cursor, cursor);
    } else if (selectionEnd > selectionStart) {
      contentInput.value = contentInput.value.slice(0, selectionStart) + text + contentInput.value.slice(selectionEnd);
      contentInput.setSelectionRange(selectionStart, selectionStart + text.length);
    } else {
      contentInput.value = text;
      contentInput.setSelectionRange(0, 0);
    }
    markDirty();
    updateCount();
    setSuggestion(null);
    aiStatus.textContent = "Suggestion accepted. Saving locally…";
    contentInput.focus();
  });

  window.addEventListener("beforeunload", (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  refreshList();
  const initialSelected = Number(app.dataset.selected || 0);
  if (initialSelected) loadDocument(initialSelected);
  else if (app.dataset.new === "1") openNew();
  else {
    assistant.hidden = true;
    form.hidden = true;
    empty.hidden = false;
  }

  if (importButton && importFileInput) {
    importButton.addEventListener("click", () => {
      importFileInput.click();
    });

    importFileInput.addEventListener("change", async () => {
      const file = importFileInput.files[0];
      if (!file) return;

      try {
        const folderVal = folderFilter.value === "none" ? null : (folderFilter.value || null);
        const body = new FormData();
        body.append("file", file);
        if (folderVal) body.append("folder_id", folderVal);
        const result = await Ultron.api("/api/documents/import", { method: "POST", body });

        if (result && result.document) {
          window.location.href = `/documents?doc=${result.document.id}`;
        }
      } catch (err) {
        Ultron.toast("Failed to import document: " + (err.message || err), "error");
      } finally {
        importFileInput.value = "";
      }
    });
  }

})();

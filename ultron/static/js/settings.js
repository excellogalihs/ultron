/* Settings — live Ollama connection check, appearance sync, and AJAX persistence. */

(() => {
  const form = document.getElementById("settings-form");
  if (!form) return;

  const urlInput = document.getElementById("ollama_url");
  const modelSelect = document.getElementById("default_model");
  const testButton = document.getElementById("test-connection");
  const state = document.getElementById("connection-state");
  const modelsHost = document.getElementById("connection-models");
  const temperature = document.getElementById("temperature");
  const temperatureOutput = document.getElementById("temperature-output");
  const saveButton = document.getElementById("settings-submit");

  temperature.addEventListener("input", () => {
    temperatureOutput.textContent = Number(temperature.value).toFixed(1);
  });

  // AJAX save to prevent page reload and form state reset
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    saveButton.disabled = true;
    saveButton.textContent = "Saving…";

    const formData = new FormData(form);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: formData,
        headers: { Accept: "application/json" },
      });

      const data = await response.json().catch(() => ({}));

      if (!response.ok || !data.ok) {
        throw new Error(data.error || "Failed to save settings.");
      }

      // Update document root data attributes immediately
      const themeVal = formData.get("theme");
      const accentVal = formData.get("accent");
      const fontVal = formData.get("font");
      if (themeVal) document.documentElement.dataset.theme = themeVal;
      if (accentVal) document.documentElement.dataset.accent = accentVal;
      if (fontVal) document.documentElement.dataset.font = fontVal;

      Ultron.toast(data.message || "Settings saved locally.", "success");
    } catch (error) {
      Ultron.toast(error.message || "Could not save settings.", "error");
    } finally {
      saveButton.disabled = false;
      saveButton.textContent = "Save settings";
    }
  });

  testButton.addEventListener("click", async () => {
    const url = urlInput.value.trim();
    if (!url) {
      urlInput.focus();
      return;
    }

    testButton.disabled = true;
    testButton.textContent = "Checking…";
    state.className = "engine-check__state";
    state.textContent = "Contacting Ollama…";
    modelsHost.hidden = true;
    modelsHost.replaceChildren();

    try {
      const status = await Ultron.api(`/api/ollama/status?url=${encodeURIComponent(url)}`);

      if (!status.available) {
        state.classList.add("is-error");
        state.textContent = "Offline — start it with: ollama serve";
        state.title = status.error || "";
        updateModelOptions(status.options || []);
        return;
      }

      state.classList.add("is-ok");
      state.textContent = `Online · ${status.models.length} model${status.models.length === 1 ? "" : "s"} installed`;
      state.title = status.models.join(", ");

      status.supported.forEach((model) => {
        const chip = document.createElement("span");
        chip.className = `engine-model${model.installed ? " is-installed" : ""}`;
        chip.textContent = model.installed
          ? `${model.id} · installed`
          : `${model.id} · pull to use`;
        modelsHost.appendChild(chip);
      });

      updateModelOptions(status.options || []);

      const extras = status.models.filter(
        (name) => !status.supported.some((model) => model.id === name)
      );
      extras.forEach((name) => {
        const chip = document.createElement("span");
        chip.className = "engine-model is-installed";
        chip.textContent = name;
        modelsHost.appendChild(chip);
      });

      modelsHost.hidden = false;
    } catch (error) {
      state.classList.add("is-error");
      state.textContent = error.message;
    } finally {
      testButton.disabled = false;
      testButton.textContent = "Test connection";
    }
  });

  const updateModelOptions = (models) => {
    const selected = modelSelect.value;
    const options = [...models];
    if (selected && !options.some((model) => model.id === selected)) {
      options.push({ id: selected, label: selected, note: "Current selection", installed: false });
    }
    modelSelect.replaceChildren();
    options.forEach((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${model.label} — ${model.note}${model.installed ? "" : " · unavailable"}`;
      option.selected = model.id === selected;
      modelSelect.appendChild(option);
    });

    if (window.UltronSelects && typeof window.UltronSelects.refresh === "function") {
      window.UltronSelects.refresh(modelSelect);
    }
  };

  // Live appearance preview
  const themeSelect = document.getElementById("theme");
  const accentSelect = document.getElementById("accent");
  const fontSelect = document.getElementById("font");

  if (themeSelect) {
    themeSelect.addEventListener("change", () => {
      document.documentElement.dataset.theme = themeSelect.value;
    });
  }
  if (accentSelect) {
    accentSelect.addEventListener("change", () => {
      document.documentElement.dataset.accent = accentSelect.value;
    });
  }
  if (fontSelect) {
    fontSelect.addEventListener("change", () => {
      document.documentElement.dataset.font = fontSelect.value;
    });
  }

  // Restore JSON trigger
  const restoreTrigger = document.getElementById("restore-trigger-btn");
  const restoreForm = document.getElementById("restore-form");
  const restoreFileInput = document.getElementById("restore-file-input");

  if (restoreTrigger && restoreForm && restoreFileInput) {
    restoreTrigger.addEventListener("click", () => {
      restoreFileInput.click();
    });
    restoreFileInput.addEventListener("change", () => {
      if (!restoreFileInput.files.length) return;
      const file = restoreFileInput.files[0];
      if (confirm(`Restoring from "${file.name}" will replace the current workspace data with the backup. Continue?`)) {
        restoreForm.submit();
      } else {
        restoreFileInput.value = "";
      }
    });
  }
})();

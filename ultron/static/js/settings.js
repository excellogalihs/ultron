/* Settings — live Ollama connection check and form feedback. */

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

  form.addEventListener("submit", () => {
    saveButton.disabled = true;
    saveButton.textContent = "Saving…";
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
  };

  testButton.click();
})();

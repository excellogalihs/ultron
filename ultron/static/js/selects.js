/* App-themed select popups backed by the original native form controls. */

(() => {
  const nativeValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  const widgets = new WeakMap();
  let openWidget = null;

  const closeOpen = (restoreFocus = false) => {
    if (!openWidget) return;
    const widget = openWidget;
    openWidget = null;
    widget.close(restoreFocus);
  };

  const positionMenu = (widget) => {
    const rect = widget.trigger.getBoundingClientRect();
    const gap = 4;
    const margin = 8;
    const availableBelow = window.innerHeight - rect.bottom - margin - gap;
    const availableAbove = rect.top - margin - gap;
    const openAbove = availableBelow < 150 && availableAbove > availableBelow;
    const maxHeight = Math.max(100, Math.min(280, openAbove ? availableAbove : availableBelow));
    const width = Math.min(Math.max(rect.width, 180), window.innerWidth - margin * 2);
    const left = Math.min(Math.max(margin, rect.left), window.innerWidth - width - margin);
    widget.menu.style.width = `${width}px`;
    widget.menu.style.maxHeight = `${maxHeight}px`;
    widget.menu.style.left = `${left}px`;
    widget.menu.style.top = openAbove
      ? `${Math.max(margin, rect.top - gap - Math.min(widget.menu.scrollHeight, maxHeight))}px`
      : `${Math.min(window.innerHeight - maxHeight - margin, rect.bottom + gap)}px`;
  };

  const enhance = (select) => {
    if (widgets.has(select) || select.multiple || select.size > 1) return;
    const parent = select.parentElement;
    if (!parent) return;

    const widget = document.createElement("div");
    widget.className = "ultron-select";
    if (select.classList.contains("select--compact")) {
      widget.classList.add("ultron-select--compact");
    }

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "ultron-select__trigger";
    trigger.id = `${select.id || `ultron-select-${Math.random().toString(36).slice(2)}`}--trigger`;
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");

    const label = document.createElement("span");
    label.className = "ultron-select__value";
    const caret = document.createElement("span");
    caret.className = "ultron-select__caret";
    caret.setAttribute("aria-hidden", "true");
    trigger.append(label, caret);

    const menu = document.createElement("div");
    menu.className = "ultron-select__menu";
    menu.id = `${trigger.id}--listbox`;
    menu.setAttribute("role", "listbox");
    menu.hidden = true;
    trigger.setAttribute("aria-controls", menu.id);

    const associatedLabels = Array.from(select.labels || []);
    if (associatedLabels.length) {
      associatedLabels.forEach((item, index) => {
        if (!item.id) item.id = `${trigger.id}--label-${index + 1}`;
      });
      trigger.setAttribute("aria-labelledby", associatedLabels.map((item) => item.id).join(" "));
      associatedLabels.forEach((item) => { item.htmlFor = trigger.id; });
    } else if (select.getAttribute("aria-label")) {
      trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
    } else if (select.getAttribute("aria-labelledby")) {
      trigger.setAttribute("aria-labelledby", select.getAttribute("aria-labelledby"));
    }

    const sync = () => {
      const option = select.options[select.selectedIndex];
      label.textContent = option ? option.textContent.trim() : "Select an option";
      trigger.disabled = select.disabled;
      trigger.required = select.required;
      if (select.required) trigger.setAttribute("aria-required", "true");
      else trigger.removeAttribute("aria-required");
      if (select.disabled && openWidget === api) closeOpen(false);
      if (!menu.hidden) renderOptions();
    };

    const choose = (option) => {
      if (!option || option.disabled) return;
      select.value = option.value;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
      sync();
      closeOpen(true);
    };

    let activeIndex = -1;
    const renderOptions = () => {
      const options = Array.from(select.options);
      menu.replaceChildren();
      options.forEach((option, index) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "ultron-select__option";
        row.id = `${menu.id}--option-${index}`;
        row.setAttribute("role", "option");
        row.setAttribute("aria-selected", option.selected ? "true" : "false");
        row.disabled = option.disabled || option.parentElement?.disabled === true;
        row.textContent = option.textContent.trim();
        if (option.selected) row.classList.add("is-selected");
        if (index === activeIndex) row.classList.add("is-active");
        row.addEventListener("pointerenter", () => setActive(index));
        row.addEventListener("click", () => choose(option));
        menu.appendChild(row);
      });
    };

    const setActive = (index) => {
      const available = Array.from(select.options)
        .map((option, optionIndex) => ({ option, optionIndex }))
        .filter(({ option }) => !option.disabled && option.parentElement?.disabled !== true);
      if (!available.length) return;
      const bounded = Math.min(Math.max(index, 0), select.options.length - 1);
      let candidate = bounded;
      while (candidate >= 0 && candidate < select.options.length) {
        const option = select.options[candidate];
        if (!option.disabled && option.parentElement?.disabled !== true) break;
        candidate += index >= activeIndex ? 1 : -1;
      }
      if (candidate < 0 || candidate >= select.options.length) {
        candidate = index >= activeIndex ? available[0].optionIndex : available[available.length - 1].optionIndex;
      }
      activeIndex = candidate;
      menu.querySelectorAll(".ultron-select__option").forEach((row, rowIndex) => {
        const active = rowIndex === activeIndex;
        row.classList.toggle("is-active", active);
        if (active) trigger.setAttribute("aria-activedescendant", row.id);
      });
      menu.querySelector(`#${CSS.escape(`${menu.id}--option-${activeIndex}`)}`)?.scrollIntoView({ block: "nearest" });
    };

    const adjacentEnabled = (from, direction) => {
      const count = select.options.length;
      for (let step = 1; step <= count; step += 1) {
        const index = (from + direction * step + count) % count;
        const option = select.options[index];
        if (!option.disabled && option.parentElement?.disabled !== true) return index;
      }
      return from;
    };

    const open = (edge = "selected") => {
      if (select.disabled) return;
      if (openWidget && openWidget !== api) closeOpen(false);
      sync();
      activeIndex = select.selectedIndex;
      if (edge === "first") activeIndex = 0;
      if (edge === "last") activeIndex = select.options.length - 1;
      if (edge === "next") activeIndex = adjacentEnabled(select.selectedIndex, 1);
      if (edge === "previous") activeIndex = adjacentEnabled(select.selectedIndex, -1);
      renderOptions();
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      openWidget = api;
      positionMenu(api);
      if (activeIndex >= 0) setActive(activeIndex);
      menu.querySelectorAll(".ultron-select__option")[activeIndex]?.scrollIntoView({ block: "nearest" });
    };

    const close = (restoreFocus) => {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      trigger.removeAttribute("aria-activedescendant");
      if (restoreFocus) trigger.focus();
    };

    let typeahead = "";
    let typeaheadTimer = 0;
    const api = { select, trigger, menu, close, open, sync };
    widgets.set(select, api);
    select.classList.add("ultron-select-source");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    parent.insertBefore(widget, select);
    widget.append(select, trigger);
    document.body.appendChild(menu);

    Object.defineProperty(select, "value", {
      configurable: true,
      get() { return nativeValue.get.call(this); },
      set(value) {
        nativeValue.set.call(this, value);
        api.sync();
      },
    });

    select.addEventListener("change", sync);
    select.addEventListener("input", sync);
    const optionsObserver = new MutationObserver(sync);
    optionsObserver.observe(select, { childList: true, subtree: true, characterData: true, attributes: true });
    select.form?.addEventListener("reset", () => window.setTimeout(sync, 0));

    trigger.addEventListener("click", () => {
      if (menu.hidden) open();
      else closeOpen(false);
    });
    trigger.addEventListener("keydown", (event) => {
      const isOpen = !menu.hidden;
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!isOpen) open(event.key === "ArrowDown" ? "next" : "previous");
        else setActive(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
      } else if (event.key === "Home" && isOpen) {
        event.preventDefault();
        setActive(0);
      } else if (event.key === "End" && isOpen) {
        event.preventDefault();
        setActive(select.options.length - 1);
      } else if ((event.key === "Enter" || event.key === " ") && isOpen) {
        event.preventDefault();
        choose(select.options[activeIndex]);
      } else if (event.key === "Escape" && isOpen) {
        event.preventDefault();
        closeOpen(true);
      } else if (event.key === "Tab" && isOpen) {
        closeOpen(false);
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        typeahead += event.key.toLocaleLowerCase();
        window.clearTimeout(typeaheadTimer);
        typeaheadTimer = window.setTimeout(() => { typeahead = ""; }, 650);
        const start = isOpen ? activeIndex + 1 : 0;
        const options = Array.from(select.options);
        const ordered = options.slice(start).concat(options.slice(0, start));
        const match = ordered.find((option) => !option.disabled && option.textContent.trim().toLocaleLowerCase().startsWith(typeahead));
        if (match) {
          if (!isOpen) open();
          setActive(Array.from(select.options).indexOf(match));
        }
      }
    });

    sync();
    return api;
  };

  document.addEventListener("pointerdown", (event) => {
    if (!openWidget) return;
    if (openWidget.trigger.contains(event.target) || openWidget.menu.contains(event.target)) return;
    closeOpen(false);
  });
  window.addEventListener("resize", () => closeOpen(false));
  window.addEventListener("scroll", () => {
    if (openWidget) positionMenu(openWidget);
  }, true);

  const init = () => {
    document.querySelectorAll("select").forEach(enhance);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  window.UltronSelects = {
    enhance,
    refresh(select) { widgets.get(select)?.sync(); },
    close() { closeOpen(false); },
  };
})();
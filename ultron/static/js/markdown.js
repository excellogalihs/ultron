/* Small, safe Markdown subset for locally generated assistant messages. */

(() => {
  const inlinePattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g;
  const blockPattern = /^(#{1,6}\s|```|>\s?|(?:[-*+]\s|\d+\.\s)|(?:---+|___+|\*\*\*+)$)/;

  const appendInline = (parent, text) => {
    let cursor = 0;
    for (const match of text.matchAll(inlinePattern)) {
      if (match.index > cursor) {
        parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      }
      const token = match[0];
      let node;
      if (token.startsWith("`")) {
        node = document.createElement("code");
        node.textContent = token.slice(1, -1);
      } else if (token.startsWith("**") || token.startsWith("__")) {
        node = document.createElement("strong");
        node.textContent = token.slice(2, -2);
      } else if (token.startsWith("*") || token.startsWith("_")) {
        node = document.createElement("em");
        node.textContent = token.slice(1, -1);
      } else {
        const parts = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
        if (parts) {
          node = document.createElement("a");
          node.textContent = parts[1];
          node.href = parts[2];
          node.target = "_blank";
          node.rel = "noopener noreferrer";
        } else {
          node = document.createTextNode(token);
        }
      }
      parent.appendChild(node);
      cursor = match.index + token.length;
    }
    if (cursor < text.length) {
      parent.appendChild(document.createTextNode(text.slice(cursor)));
    }
  };

  const appendCode = (parent, language, source) => {
    const frame = document.createElement("div");
    frame.className = "markdown__code";
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    if (/^[a-z0-9_+-]{1,24}$/i.test(language)) {
      code.className = `language-${language}`;
    }
    code.textContent = source;
    pre.appendChild(code);

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "markdown__copy";
    copyButton.textContent = "Copy code";
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(source);
        copyButton.textContent = "Copied";
        window.setTimeout(() => { copyButton.textContent = "Copy code"; }, 1200);
      } catch {
        copyButton.textContent = "Copy unavailable";
      }
    });
    frame.append(pre, copyButton);
    parent.appendChild(frame);
  };

  const render = (container, source) => {
    const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
    container.replaceChildren();
    container.classList.add("is-markdown");

    for (let index = 0; index < lines.length;) {
      const line = lines[index];
      if (!line.trim()) {
        index += 1;
        continue;
      }

      const fence = line.match(/^```\s*([\w+-]*)\s*$/);
      if (fence) {
        const openingFence = line;
        const codeLines = [];
        let closed = false;
        index += 1;
        while (index < lines.length && !/^```\s*$/.test(lines[index])) {
          codeLines.push(lines[index]);
          index += 1;
        }
        if (index < lines.length) {
          closed = true;
          index += 1;
        }
        if (!closed && !codeLines.length) {
          const paragraph = document.createElement("p");
          appendInline(paragraph, openingFence);
          container.appendChild(paragraph);
          continue;
        }
        appendCode(container, fence[1], codeLines.join("\n"));
        continue;
      }

      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        const element = document.createElement(`h${heading[1].length}`);
        appendInline(element, heading[2]);
        container.appendChild(element);
        index += 1;
        continue;
      }

      if (/^(---+|___+|\*\*\*+)$/.test(line.trim())) {
        container.appendChild(document.createElement("hr"));
        index += 1;
        continue;
      }

      if (/^>\s?/.test(line)) {
        const quote = document.createElement("blockquote");
        while (index < lines.length && /^>\s?/.test(lines[index])) {
          const paragraph = document.createElement("p");
          appendInline(paragraph, lines[index].replace(/^>\s?/, ""));
          quote.appendChild(paragraph);
          index += 1;
        }
        container.appendChild(quote);
        continue;
      }

      const listItem = line.match(/^\s*([-*+]|\d+\.)\s+(.+)$/);
      if (listItem) {
        const ordered = /\d+\./.test(listItem[1]);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (index < lines.length) {
          const item = lines[index].match(/^\s*([-*+]|\d+\.)\s+(.+)$/);
          if (!item || /\d+\./.test(item[1]) !== ordered) break;
          const element = document.createElement("li");
          appendInline(element, item[2]);
          list.appendChild(element);
          index += 1;
        }
        container.appendChild(list);
        continue;
      }

      const paragraph = document.createElement("p");
      const paragraphLines = [line];
      index += 1;
      while (index < lines.length && lines[index].trim() && !blockPattern.test(lines[index])) {
        paragraphLines.push(lines[index]);
        index += 1;
      }
      appendInline(paragraph, paragraphLines.join(" "));
      container.appendChild(paragraph);
    }
  };

  window.UltronMarkdown = { render };
})();
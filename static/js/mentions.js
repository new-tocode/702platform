// @ 补全：在标注 data-mentions 的输入框里打 @ 时列出成员姓名。
//
// 服务端才是权威——正文里写了 @姓名 就算提及，这段脚本只是帮忙打字：没脚本时
// 手打照样有效。名单来自页面嵌的 JSON（json_script 的 #mention-names），
// 不入库、不发请求。

const mentionData = document.getElementById("mention-names");
const mentionInputs = mentionData
  ? document.querySelectorAll("textarea[data-mentions]")
  : [];

if (mentionInputs.length) {
  const names = JSON.parse(mentionData.textContent);
  mentionInputs.forEach((input) => attachMentionMenu(input, names));
}

function attachMentionMenu(input, names) {
  const menu = document.createElement("div");
  menu.className = "mention-menu";
  menu.hidden = true;
  menu.setAttribute("role", "listbox");
  // 下拉贴在输入框所在块的底部：给块一个定位上下文。
  input.parentElement.classList.add("mention-host");
  input.parentElement.appendChild(menu);

  let options = [];
  let active = -1;
  let queryStart = -1; // 文本里 @ 的下标

  // 光标前是不是一个正在输入的 @词。@ 前必须是空白或行首，邮箱里的 @ 不算。
  function currentQuery() {
    const caret = input.selectionStart;
    if (caret === null || caret !== input.selectionEnd) return null;
    const before = input.value.slice(0, caret);
    const match = /(?:^|\s)@([^\s@]{0,30})$/.exec(before);
    return match
      ? { start: caret - match[1].length - 1, query: match[1] }
      : null;
  }

  function close() {
    menu.hidden = true;
    menu.textContent = "";
    options = [];
    active = -1;
    queryStart = -1;
  }

  function render(matches) {
    menu.textContent = "";
    options = matches;
    active = matches.length ? 0 : -1;
    matches.forEach((name, index) => {
      const option = document.createElement("div");
      option.className = "mention-option" + (index === 0 ? " is-active" : "");
      option.setAttribute("role", "option");
      option.textContent = name;
      // mousedown 而不是 click：click 晚于 blur，选项会先随失焦消失。
      option.addEventListener("mousedown", (event) => {
        event.preventDefault();
        choose(name);
      });
      menu.appendChild(option);
    });
    menu.hidden = matches.length === 0;
  }

  function highlight() {
    Array.from(menu.children).forEach((child, index) => {
      child.classList.toggle("is-active", index === active);
    });
  }

  function choose(name) {
    if (queryStart < 0) return;
    const caret = input.selectionStart;
    const before = input.value.slice(0, queryStart);
    const after = input.value.slice(caret);
    const insert = `@${name} `;
    input.value = before + insert + after;
    const position = before.length + insert.length;
    input.setSelectionRange(position, position);
    close();
    input.focus();
  }

  function refresh() {
    const query = currentQuery();
    if (!query) {
      close();
      return;
    }
    queryStart = query.start;
    const matches = names
      .filter((name) => name.includes(query.query))
      .slice(0, 8);
    render(matches);
  }

  input.addEventListener("input", (event) => {
    if (event.isComposing) return; // 输入法合成期间不弹，免得选字时误触
    refresh();
  });
  input.addEventListener("compositionend", refresh);

  input.addEventListener("keydown", (event) => {
    if (menu.hidden || !options.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      active = (active + 1) % options.length;
      highlight();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      active = (active - 1 + options.length) % options.length;
      highlight();
    } else if (event.key === "Enter" || event.key === "Tab") {
      // 菜单开着时 Enter 是「选中这个人」，不是换行。
      event.preventDefault();
      choose(options[active]);
    } else if (event.key === "Escape") {
      close();
    }
  });

  input.addEventListener("blur", () => {
    // 兜底：万一焦点还是走了，把菜单收掉（mousedown 那条路不会走到这里）。
    window.setTimeout(close, 120);
  });
}

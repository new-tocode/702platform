// Markdown 预览：服务端渲染，前端只负责取结果与切换面板。
//
// 与发布后的正文共用 content.templatetags.rendering.render_markdown，不在浏览器
// 里另写一套 Markdown 解析——两边语法一有出入，「预览」就会变成另一件事。
// 按钮与面板由脚本插到 textarea 前后，输入框的 DOM 结构保持原样：
// mentions.js 依赖 textarea.parentElement 定位 @ 补全菜单，包一层容器会让菜单
// 掉到下面去。没有脚本时输入框照常可用，只是没有预览。

(() => {
  let url = "";

  // 前台由 base.html 用 defer 加载（DOM 已就绪）；后台的 form.media 在 <head>
  // 里同步输出脚本，执行时输入框还没解析出来。两处都走同一个入口。
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }

  function init() {
    url = document.querySelector('meta[name="markdown-preview-url"]')?.content;
    if (!url) return;

    document.querySelectorAll("textarea[data-markdown-preview]").forEach(setup);
  }

  function setup(textarea) {
    if (textarea.dataset.markdownPreviewReady) return;
    textarea.dataset.markdownPreviewReady = "1";

    const panelId = `${textarea.id || textarea.name}-markdown-preview`;

    const toolbar = document.createElement("div");
    toolbar.className = "markdown-field-toolbar";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-sm markdown-preview-toggle";
    button.textContent = textarea.dataset.previewLabel;
    button.setAttribute("aria-controls", panelId);
    button.setAttribute("aria-expanded", "false");
    toolbar.append(button);

    const panel = document.createElement("div");
    panel.className = "prose markdown-preview";
    panel.id = panelId;
    panel.hidden = true;

    // 前台字段容器是普通块；Django admin 的字段在 `.flex-container` 里，直接
    // 把按钮插成它的兄弟会被挤成一条竖排文字。后台改插到 `.form-row`：按钮在
    // 整个字段行之上，面板在字段行之下，宽度都跟字段行一致。
    //
    // 前台的面板放在 `.field` 之后而不是 textarea 之后：mentions.js 把 @ 菜单
    // 的定位基准设成 textarea 的父元素（`.field`），面板若在 `.field` 里面，
    // 展开后菜单会掉到面板下方、离输入框几百像素。放进 `.field-row`（两列
    // 网格）的字段例外，面板留在字段内，免得成为第三个网格项。
    const host = textarea.parentElement;
    const adminRow = host?.classList.contains("flex-container")
      ? host.closest(".form-row")
      : null;
    const field = textarea.closest(".field");
    if (adminRow) {
      adminRow.prepend(toolbar);
      adminRow.append(panel);
    } else {
      textarea.before(toolbar);
      const inGrid = field?.parentElement?.classList.contains("field-row");
      if (field?.parentElement && !inGrid) {
        field.after(panel);
      } else {
        textarea.after(panel);
      }
    }

    let busy = false;

    button.addEventListener("click", async () => {
      if (busy) return;
      if (!panel.hidden) {
        collapse();
        return;
      }

      busy = true;
      button.disabled = true;
      try {
        // 页面上任何一个表单都带着 CSRF 隐藏字段；从当前字段所在的表单取，
        // 不在脚本里读 cookie（CSRF_COOKIE_HTTPONLY 一开就读不到了）。
        const token = textarea
          .closest("form")
          ?.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
        if (!token) throw new Error("missing CSRF token");

        const response = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-CSRFToken": token,
            Accept: "application/json",
          },
          body: new URLSearchParams({ text: textarea.value }),
        });
        if (!response.ok) throw new Error(`preview failed: ${response.status}`);

        const data = await response.json();
        if (data.html) {
          panel.textContent = "";
          panel.innerHTML = data.html;
          expand();
        } else {
          showMessage(textarea.dataset.previewEmpty);
        }
      } catch (error) {
        showMessage(textarea.dataset.previewError);
      } finally {
        busy = false;
        button.disabled = false;
      }
    });

    function showMessage(message) {
      panel.textContent = "";
      const line = document.createElement("p");
      line.className = "muted";
      line.textContent = message;
      panel.append(line);
      expand();
    }

    function expand() {
      panel.hidden = false;
      button.textContent = textarea.dataset.previewHideLabel;
      button.setAttribute("aria-expanded", "true");
    }

    function collapse() {
      panel.hidden = true;
      button.textContent = textarea.dataset.previewLabel;
      button.setAttribute("aria-expanded", "false");
    }
  }
})();

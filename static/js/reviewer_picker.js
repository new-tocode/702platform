// 初审人指定评审人的浮动窗：开关 <dialog>、显示已选人数、挡住超额选择。
//
// 复选框本身用 form="preliminary-form" 归属页面上的初审表单，所以脚本不搬家、
// 不复制值——选中项就是随表单一起 POST 的那几项。没有这段脚本时窗口打不开，
// 初审也就提交不了；「通过必须点名评审人」是服务端的硬规则，不在这里留随机兜底。
(() => {
  const dialog = document.querySelector("[data-reviewer-dialog]");
  const openButton = document.querySelector("[data-reviewer-picker-open]");
  if (!dialog || !openButton || typeof dialog.showModal !== "function") return;

  const picks = Array.from(dialog.querySelectorAll("[data-reviewer-pick]"));
  const counter = document.querySelector("[data-reviewer-count]");
  const hint = dialog.querySelector("[data-reviewer-hint]");
  const required = Number(counter?.dataset.required || 0);
  const selected = () => picks.filter((pick) => pick.checked);

  const refresh = () => {
    if (!counter) return;
    counter.textContent = `${selected().length}/${required}`;
    if (hint) hint.textContent = "";
  };

  openButton.addEventListener("click", () => {
    dialog.showModal();
    (picks.find((pick) => !pick.checked) || picks[0])?.focus();
  });

  dialog
    .querySelector("[data-reviewer-dialog-close]")
    ?.addEventListener("click", () => dialog.close());

  // 点窗外关掉：<dialog> 铺满视口，事件目标是它本身就说明点在了遮罩上。
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  picks.forEach((pick) => {
    pick.addEventListener("change", () => {
      if (pick.checked && selected().length > required) {
        pick.checked = false;
        if (hint) hint.textContent = hint.dataset.limitText || "";
        return;
      }
      refresh();
    });
  });

  refresh();
})();

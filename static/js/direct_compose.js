// 写私信的小浮动窗：把「私信 / 快速回信 / 回复」那几条普通链接升级成 <dialog>。
//
// 只做渐进增强：那些链接本来就指向整页表单（notices:direct_compose），没有这段脚本
// 照样发得出私信，只是打开一整页。收件人名字与提交地址都从被点的那条链接上取
// （data-direct-name 与 href），脚本不去猜，也不拼句子。
//
// 发送成功由服务端 302 回原页面（PRG + flash）：页面一刷新，窗口自己就没了，
// 顶上是「私信已发送。」；失败时服务端重渲染那一页表单，写过的正文还在。
(() => {
  const dialog = document.querySelector("[data-direct-dialog]");
  const form = dialog?.querySelector("[data-direct-form]");
  const recipient = dialog?.querySelector("[data-direct-recipient]");
  // 没有窗口的页面，或浏览器不支持 showModal：什么都不做，链接自己打开整页。
  if (!form || !recipient || typeof dialog.showModal !== "function") return;

  const open = (link) => {
    form.action = link.href;
    recipient.textContent = link.dataset.directName || "";
    // 上一次留下的正文与错误提示不该跟到这一次。
    form.reset();
    dialog.showModal();
    form.querySelector("textarea")?.focus();
  };

  document.querySelectorAll("[data-direct-compose]").forEach((link) => {
    link.addEventListener("click", (event) => {
      // 按住修饰键是「新标签页打开」，那是浏览器的事，别拦。
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      open(link);
    });
  });

  dialog
    .querySelector("[data-direct-cancel]")
    ?.addEventListener("click", () => dialog.close());

  // 点窗外关掉：<dialog> 自己铺满视口，事件目标是它本身就说明点在了遮罩上。
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
})();

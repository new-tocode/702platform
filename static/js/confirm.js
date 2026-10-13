// 需要确认的提交：表单上写了 data-confirm 的，提交前问一句。
//
// 原先这段在 discussion.js 里，只有社团空间那一页生效——而「删除」这类不可撤销的
// 动作别的页面也有（头像、图册、私信）。它本来就是全站通用的东西，所以挪到这里、
// 跟着 base.html 一起加载。没有脚本时不问、照常提交：确认是一道礼貌，不是权限。
document.addEventListener("submit", (event) => {
  const form = event.target;
  const confirmation = form.dataset?.confirm;

  if (confirmation && !window.confirm(confirmation)) {
    event.preventDefault();
  }
});

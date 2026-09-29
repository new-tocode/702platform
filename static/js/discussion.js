document.addEventListener("submit", (event) => {
  const form = event.target;
  const confirmation = form.dataset.confirm;

  if (confirmation && !window.confirm(confirmation)) {
    event.preventDefault();
  }
});

// 过长的帖子先折到一屏内，点「展开全文」后不再折回去。
//
// 「多长算长」只有 CSS 一个出处（.discussion-post-content.is-collapsed 的 max-height），
// 这里不重复那个数字：先给正文套上类，再问浏览器有没有真的溢出，溢出了才留下按钮。
// 没脚本时这段不执行，正文整段照常显示——折叠是脚本加的，不是模板欠下的。
const collapsiblePosts = [];
document.querySelectorAll(".discussion-post-body").forEach((body) => {
  const content = body.querySelector(".discussion-post-content");
  const more = body.querySelector(".discussion-post-more");
  if (content && more) collapsiblePosts.push({ content, more });
});

// 写与读分成两轮：先全部套上，再逐个量，免得读写交错触发多次重排。
collapsiblePosts.forEach(({ content }) => content.classList.add("is-collapsed"));

collapsiblePosts.forEach(({ content, more }) => {
  // 留 1px 余量：行高取整会让 scrollHeight 比 clientHeight 多出一星半点。
  if (content.scrollHeight <= content.clientHeight + 1) {
    content.classList.remove("is-collapsed");
    return;
  }

  more.hidden = false;
  more.addEventListener("click", () => expandPost(content, more));
  // 折叠区里的链接照样能被 Tab 到，浏览器会为了让它可见把裁掉的部分滚上来；
  // 与其让人对着半截正文，不如直接展开。
  content.addEventListener("focusin", () => expandPost(content, more));
});

function expandPost(content, more) {
  content.classList.remove("is-collapsed");
  more.setAttribute("aria-expanded", "true");
  more.hidden = true;
  // 按钮一藏，焦点就落回 body，再按 Tab 会跳回页首；交给刚展开的正文接着往下走。
  content.focus({ preventScroll: true });
}

// 板块滑轨是横向滚动的：窄屏下当前板块可能落在视口外，进页面时先把它带进视野。
window.addEventListener(
  "load",
  () => {
    window.requestAnimationFrame(() => {
      const rail = document.querySelector(".discussion-board-rail");
      const activeTab = rail?.querySelector(".discussion-board-tab.is-active");

      if (!rail || !activeTab || rail.scrollWidth <= rail.clientWidth) return;

      const railBounds = rail.getBoundingClientRect();
      const tabBounds = activeTab.getBoundingClientRect();
      if (tabBounds.right > railBounds.right) {
        rail.scrollLeft += Math.ceil(tabBounds.right - railBounds.right);
      } else if (tabBounds.left < railBounds.left) {
        rail.scrollLeft -= Math.ceil(railBounds.left - tabBounds.left);
      }
    });
  },
  { once: true },
);

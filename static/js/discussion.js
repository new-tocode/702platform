document.addEventListener("submit", (event) => {
  const form = event.target;
  const confirmation = form.dataset.confirm;

  if (confirmation && !window.confirm(confirmation)) {
    event.preventDefault();
  }
});

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

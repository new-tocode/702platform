(() => {
  const revealActiveNavigationItem = () => {
    const nav = document.querySelector(".nav");
    const activeLink = nav?.querySelector('[aria-current="page"]');

    if (!nav || !activeLink || nav.scrollWidth <= nav.clientWidth) return;

    const navBounds = nav.getBoundingClientRect();
    const linkBounds = activeLink.getBoundingClientRect();
    if (linkBounds.right > navBounds.right) {
      nav.scrollLeft += Math.ceil(linkBounds.right - navBounds.right);
    } else if (linkBounds.left < navBounds.left) {
      nav.scrollLeft -= Math.ceil(navBounds.left - linkBounds.left);
    }
  };

  window.addEventListener(
    "load",
    () => window.requestAnimationFrame(revealActiveNavigationItem),
    { once: true },
  );
})();

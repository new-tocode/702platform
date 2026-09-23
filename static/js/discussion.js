document.addEventListener("submit", (event) => {
  const form = event.target;
  const confirmation = form.dataset.confirm;

  if (confirmation && !window.confirm(confirmation)) {
    event.preventDefault();
  }
});

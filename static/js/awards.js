// 历年获奖页的勾选：全选本页、已选几条。
//
// 只做渐进增强：没有这段脚本，勾选与「下载所选证书」照样能用，少的是全选与计数。
// 计数那句话整句来自模板（英文分单复数），脚本只把其中的数字换掉——不拼句子，
// 也就不会拼出「已选 3 条」在英文里该有的样子。
document.querySelectorAll("[data-award-bar]").forEach((bar) => {
  const picks = Array.from(document.querySelectorAll("[data-award-pick]"));
  const all = bar.querySelector("[data-award-all]");
  const counter = bar.querySelector("[data-award-counter]");

  if (!picks.length) return;

  // 先留一份原话：下面的替换就地把数字改掉，第二次数就没有模板可依了。
  const sentence = counter.textContent;

  const refresh = () => {
    const chosen = picks.filter((box) => box.checked).length;
    counter.hidden = chosen === 0;
    counter.textContent = sentence.replace(/\d+/, chosen);
    all.checked = chosen > 0 && chosen === picks.length;
    // 选了一半时全选框画成横杠，而不是留一个看起来「没生效」的空框。
    all.indeterminate = chosen > 0 && chosen < picks.length;
  };

  all.addEventListener("change", () => {
    picks.forEach((box) => {
      box.checked = all.checked;
    });
    refresh();
  });
  picks.forEach((box) => box.addEventListener("change", refresh));
  refresh();
});

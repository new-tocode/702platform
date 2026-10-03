// 个人图册的批量上传：选完文件立刻说清楚选了几张、合计多大、哪几张超限。
//
// 只做渐进增强：没有这段脚本，多选与提交照常，只是少一行即时反馈（服务端
// 提交后照样会逐张点名）。句子整句来自模板的 data 属性（英文要分单复数），
// 脚本只把张数、大小与文件名填进去——不拼句子，也就不会拼出英文里不该有的
// 样子，与 awards.js 同一条约定。
(() => {
  const hint = document.querySelector("[data-gallery-picked]");
  const input = document.querySelector('input[type="file"][name="images"]');
  if (!hint || !input) return;

  // 单张上限由模板带下来，与服务端同一个常量（字节，不做 MB 换算）。
  const maxBytes = Number(hint.dataset.maxBytes) || 0;
  const one = hint.dataset.pickedOne || "";
  const many = hint.dataset.pickedMany || "";
  const oversize = hint.dataset.oversize || "";

  const megabytes = (bytes) => (bytes / (1024 * 1024)).toFixed(1);

  const render = () => {
    const files = Array.from(input.files || []);
    hint.textContent = "";
    if (!files.length) {
      hint.hidden = true;
      return;
    }

    const total = files.reduce((sum, file) => sum + file.size, 0);
    const sentence = (files.length === 1 ? one : many)
      .replace("{count}", String(files.length))
      .replace("{size}", megabytes(total));
    hint.append(document.createTextNode(sentence));

    const tooBig = maxBytes ? files.filter((file) => file.size > maxBytes) : [];
    if (tooBig.length) {
      // 文件名是用户所选，一律经文本节点拼进去：这里若用 innerHTML 就是注入点。
      const names = document.createElement("span");
      names.className = "gallery-picked-names";
      names.textContent =
        oversize + tooBig.map((file) => file.name).join(" · ");
      hint.append(names);
      hint.classList.add("is-warning");
    } else {
      hint.classList.remove("is-warning");
    }
    hint.hidden = false;
  };

  input.addEventListener("change", render);
  // 提交失败返回后浏览器可能留着已选的文件（前进/后退回来也一样），
  // 进页面先对一次现状，免得提示与输入框不同步。
  render();
})();

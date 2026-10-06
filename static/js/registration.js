// 竞赛报名：切换项目组后，把「参赛成员」与「竞赛组长」两个下拉框过滤为该组成员。
//
// 只做渐进增强：没有这段脚本，两个下拉框照常列出全部成员，只是不再随项目组收窄
// ——服务端提交时仍会校验（选错人会被表单拒绝），所以它坏掉的后果是「多选了几个人
// 然后被拒」，不是「错误的数据进了库」。
//
// 这段逻辑原先写在模板里的内联 <script> 中。挪出来是为了让 CSP 能真正生效：
// 内联脚本要么得靠 'unsafe-inline' 放行（那 CSP 对 XSS 的防护基本就没了），
// 要么得逐块算哈希——而这里的 id 是模板插值出来的，每次请求都可能不同，哈希
// 用不了。元素 id 由模板用 data 属性带下来：表单字段的 id 带前缀，脚本不该去猜。
(() => {
  const form = document.querySelector("[data-registration-form]");
  if (!form) return;

  const mapElement = document.getElementById(form.dataset.groupMap);
  const groupSelect = document.getElementById(form.dataset.groupField);
  const membersSelect = document.getElementById(form.dataset.membersField);
  const leaderSelect = document.getElementById(form.dataset.leaderField);
  if (!mapElement || !groupSelect || !membersSelect || !leaderSelect) return;

  // 「成员 → 他所属的全部项目组」，由模板序列化。
  const memberGroups = JSON.parse(mapElement.textContent);

  const filterSelect = (select) => {
    Array.from(select.options).forEach((option) => {
      const groups = memberGroups[option.value] || [];
      const visible = !groupSelect.value || groups.includes(groupSelect.value);
      option.hidden = !visible;
      // 被藏起来的选项不能留在选中状态：表单提交的是「选了什么」，
      // 不是「看得见什么」，留着等于悄悄带上一个不属于本组的人。
      if (!visible && option.selected) option.selected = false;
    });
  };

  const filterAll = () => {
    filterSelect(membersSelect);
    filterSelect(leaderSelect);
  };

  groupSelect.addEventListener("change", filterAll);
  filterAll();
})();

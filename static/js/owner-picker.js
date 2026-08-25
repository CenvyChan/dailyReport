// 负责业务员选择器：给多选标签组加一个即时过滤框和「已选 N 人」计数。
//
// 字段本身必须是多选：线上有 33 个客户绑定了 2 个业务员（历史导入带来的），
// 改成单选会在保存时静默删掉一个绑定，那个业务员从此看不到自己的客户。
// 所以做法是保留多选能力，但让常见情况（只有一个负责人）看起来和单选一样清爽。
(function () {
  const field = document.querySelector(".field-choices");
  if (!field) return;

  const group = field.querySelector(":scope > div");
  const boxes = Array.from(field.querySelectorAll('input[type="checkbox"]'));
  if (!group || boxes.length === 0) return;

  const optionOf = (box) => box.closest("div");
  const labelText = (box) => (optionOf(box).textContent || "").trim();

  // 人少时不必加搜索框，反而多一层噪音
  const needsFilter = boxes.length > 8;

  const bar = document.createElement("div");
  bar.className = "choices-bar";

  let search = null;
  if (needsFilter) {
    search = document.createElement("input");
    search.type = "search";
    search.className = "choices-search";
    search.placeholder = "输入姓名筛选";
    search.setAttribute("aria-label", "筛选业务员");
    bar.append(search);
  }

  const count = document.createElement("span");
  count.className = "choices-count";
  bar.append(count);

  const selectedOnly = document.createElement("button");
  selectedOnly.type = "button";
  selectedOnly.className = "choices-toggle";
  selectedOnly.textContent = "只看已选";
  bar.append(selectedOnly);

  group.parentNode.insertBefore(bar, group);

  let showSelectedOnly = false;

  const refreshCount = () => {
    const chosen = boxes.filter((box) => box.checked);
    count.textContent = chosen.length ? `已选 ${chosen.length} 人` : "未选择";
    count.dataset.empty = chosen.length ? "no" : "yes";
    selectedOnly.hidden = chosen.length === 0;
  };

  const applyFilter = () => {
    const keyword = (search ? search.value : "").trim().toLowerCase();
    boxes.forEach((box) => {
      const option = optionOf(box);
      const matchesKeyword = !keyword || labelText(box).toLowerCase().includes(keyword);
      const matchesMode = !showSelectedOnly || box.checked;
      option.hidden = !(matchesKeyword && matchesMode);
    });
    // 选中项永远可见，否则筛掉之后用户以为绑定丢了
    boxes.filter((box) => box.checked).forEach((box) => {
      if (showSelectedOnly) optionOf(box).hidden = false;
    });
  };

  if (search) {
    search.addEventListener("input", applyFilter);
    // 搜索框里按回车不该提交整个表单
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") event.preventDefault();
    });
  }

  selectedOnly.addEventListener("click", () => {
    showSelectedOnly = !showSelectedOnly;
    selectedOnly.classList.toggle("on", showSelectedOnly);
    selectedOnly.textContent = showSelectedOnly ? "看全部" : "只看已选";
    applyFilter();
  });

  boxes.forEach((box) => {
    box.addEventListener("change", () => {
      refreshCount();
      if (showSelectedOnly) applyFilter();
    });
  });

  refreshCount();
  applyFilter();
})();

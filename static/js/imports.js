(() => {
  const form = document.getElementById("import-form");
  if (!form) return;

  const fileInput = document.getElementById("import-file");
  const commitButton = document.getElementById("commit-import");
  const result = document.getElementById("import-result");
  const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

  const show = (message, errors = []) => {
    result.replaceChildren();
    const summary = document.createElement("p");
    summary.textContent = message;
    result.append(summary);
    if (errors.length) {
      const list = document.createElement("ul");
      errors.forEach((error) => {
        const item = document.createElement("li");
        item.textContent = `第 ${error.row_number} 行，${error.field}: ${error.message}`;
        list.append(item);
      });
      result.append(list);
    }
  };

  const upload = async (url) => {
    if (!fileInput.files.length) return;
    const data = new FormData();
    data.append("file", fileInput.files[0]);
    const response = await fetch(url, { method: "POST", body: data, headers: { "X-CSRFToken": csrfToken } });
    const payload = await response.json();
    if (!response.ok) {
      show(payload.error || "操作失败", payload.error_rows || []);
      commitButton.disabled = true;
      return;
    }
    if (payload.imported !== undefined) {
      show(`已成功导入 ${payload.imported} 条记录。`);
      commitButton.disabled = true;
      return;
    }
    const errors = payload.error_rows || [];
    show(`可导入 ${payload.valid_row_count} 条记录。`, errors);
    commitButton.disabled = errors.length > 0 || payload.valid_row_count === 0;
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    upload(form.dataset.previewUrl);
  });
  commitButton.addEventListener("click", () => upload(form.dataset.commitUrl));
})();

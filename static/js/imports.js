(() => {
  const form = document.getElementById("import-form");
  if (!form) return;

  const fileInput = document.getElementById("import-file");
  const previewButton = form.querySelector("[type=submit]");
  const commitButton = document.getElementById("commit-import");
  const result = document.getElementById("import-result");
  const csrfToken = form.querySelector("[name=csrfmiddlewaretoken]").value;

  // 上传中禁用两个按钮。不这样做的话，几秒的等待里用户会以为没反应而再点一次，
  // 导致同一份数据被导入两遍、金额翻倍。
  let busy = false;

  const show = (message, errors = [], kind = "info") => {
    result.replaceChildren();
    result.dataset.kind = kind;
    const summary = document.createElement("p");
    summary.textContent = message;
    result.append(summary);
    if (errors.length) {
      const list = document.createElement("ul");
      errors.forEach((error) => {
        const item = document.createElement("li");
        const where = error.row_number ? `第 ${error.row_number} 行，` : "";
        const field = error.field ? `${error.field}: ` : "";
        item.textContent = `${where}${field}${error.message}`;
        list.append(item);
      });
      result.append(list);
    }
  };

  const upload = async (url, busyMessage) => {
    if (busy) return;
    if (!fileInput.files.length) {
      show("请先选择要上传的 Excel 文件。", [], "fail");
      return;
    }
    busy = true;
    previewButton.disabled = true;
    commitButton.disabled = true;
    show(busyMessage, [], "busy");
    const data = new FormData();
    data.append("file", fileInput.files[0]);
    try {
      const response = await fetch(url, {
        method: "POST",
        body: data,
        headers: { "X-CSRFToken": csrfToken },
      });
      // 后端异常时返回的是 HTML 错误页，直接 .json() 会抛 SyntaxError，
      // 界面上表现为「点了没反应」，所以这里单独兜住。
      let payload;
      try {
        payload = await response.json();
      } catch {
        show("服务器返回了无法识别的内容，导入未完成。请联系管理员查看日志。", [], "fail");
        return;
      }
      if (!response.ok) {
        show(payload.error || "操作失败", payload.error_rows || [], "fail");
        return;
      }
      if (payload.imported !== undefined) {
        show(`已成功导入 ${payload.imported} 条记录。`, [], "ok");
        // 导入成功后不允许再点一次，避免重复写入；要再导就重新选文件。
        fileInput.value = "";
        return;
      }
      const errors = payload.error_rows || [];
      const usable = errors.length === 0 && payload.valid_row_count > 0;
      show(
        `可导入 ${payload.valid_row_count} 条记录。` + (usable ? "请点「正式导入」写入数据。" : ""),
        errors,
        usable ? "ok" : "fail"
      );
      if (usable) commitButton.disabled = false;
    } catch {
      show("网络中断或服务器无响应，导入未完成。请稍后重试。", [], "fail");
    } finally {
      busy = false;
      previewButton.disabled = false;
    }
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    upload(form.dataset.previewUrl, "正在校验文件，请稍候…");
  });
  commitButton.addEventListener("click", () =>
    upload(form.dataset.commitUrl, "正在导入，请勿关闭页面…")
  );
  // 换了文件就得重新预览，否则可能拿旧的校验结果去导新文件。
  fileInput.addEventListener("change", () => {
    commitButton.disabled = true;
    result.replaceChildren();
  });
})();

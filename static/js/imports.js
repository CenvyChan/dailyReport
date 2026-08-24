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

  // 网页上只列出错误时，用户得对着行号回 Excel 里逐条翻找。几百行数据里错几行
  // 就很痛苦，所以给一个把「原始内容 + 行号 + 原因」导出成表格的入口。
  const errorsUrl = form.dataset.errorsUrl;

  const downloadErrors = async (button) => {
    if (!fileInput.files.length) return;
    button.disabled = true;
    const original = button.textContent;
    button.textContent = "正在生成…";
    const data = new FormData();
    data.append("file", fileInput.files[0]);
    try {
      const response = await fetch(errorsUrl, {
        method: "POST",
        body: data,
        headers: { "X-CSRFToken": csrfToken },
      });
      if (!response.ok) {
        button.textContent = "生成失败，请重试";
        button.disabled = false;
        return;
      }
      // 后端用 filename* 传中文名，这里解出来作为下载名。
      const disposition = response.headers.get("Content-Disposition") || "";
      const matched = disposition.match(/filename\*=UTF-8''([^;]+)/);
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = matched ? decodeURIComponent(matched[1]) : "错误清单.xlsx";
      link.click();
      URL.revokeObjectURL(link.href);
      button.textContent = original;
      button.disabled = false;
    } catch {
      button.textContent = "生成失败，请重试";
      button.disabled = false;
    }
  };

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
      if (errorsUrl && fileInput.files.length) {
        const download = document.createElement("button");
        download.type = "button";
        download.className = "button";
        download.textContent = "下载错误清单";
        download.addEventListener("click", () => downloadErrors(download));
        const actions = document.createElement("p");
        actions.className = "page-actions";
        actions.append(download);
        result.append(actions);
      }
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

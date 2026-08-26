// 明暗主题：初始化 + 切换。
//
// 必须在 <head> 里同步引入（不能 defer）：主题要在样式表生效前就落到 <html> 上，
// 晚一步暗色用户会先闪一帧亮色。本文件是自托管的，不走 CDN——登录页只有这一个
// 交互开关，让它依赖一个可能加载失败的外部脚本不划算。
//
// 页面里凡是带 data-theme-toggle 的元素都会被接上，所以 base.html 的导航按钮和
// base_auth.html 登录页右上角那个用的是同一份实现，不用各写一遍。
(function () {
  var KEY = "fns-theme";

  function apply(theme) {
    var root = document.documentElement;
    root.dataset.theme = theme;
    // Tailwind 配的是 darkMode: 'class'，它认的是 .dark 而不是 data-theme，
    // 两个都要跟着改，否则用到的 dark: 工具类会和自托管样式对不上。
    root.classList.toggle("dark", theme === "dark");
  }

  function saved() {
    try {
      return localStorage.getItem(KEY);
    } catch (error) {
      // 隐私模式下 localStorage 会抛错
      return null;
    }
  }

  apply(saved() || "dark");

  function toggle() {
    var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(next);
    try {
      localStorage.setItem(KEY, next);
    } catch (error) { /* 存不下就只在本次会话生效 */ }
    // ECharts 的坐标轴和文字色是初始化时算好的，主题一换必须让图表自己重画，
    // 否则切到亮色只剩一堆看不见的灰字。
    window.dispatchEvent(new CustomEvent("fns-theme-change", { detail: next }));
  }

  window.fnsToggleTheme = toggle;

  function wire() {
    var nodes = document.querySelectorAll("[data-theme-toggle]");
    for (var index = 0; index < nodes.length; index += 1) {
      nodes[index].addEventListener("click", toggle);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();

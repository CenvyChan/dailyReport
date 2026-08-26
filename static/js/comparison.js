(() => {
  const source = document.getElementById("comparison-data");
  const node = document.getElementById("comparison-chart");
  if (!source || !node || !window.echarts) return;

  let data;
  try {
    data = JSON.parse(source.textContent);
  } catch {
    // 数据拼装出问题时留着表格就行，别把整页 JS 拖崩。
    return;
  }

  const token = (name, fallback) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const money = (value) =>
    Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const compact = (value) => {
    const number = Number(value || 0);
    if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
    if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(1)}万`;
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
  };

  const chart = window.echarts.init(node, null, { renderer: "canvas" });

  const paint = () => {
    const dark = document.documentElement.dataset.theme !== "light";
    const label = token("--text-mute", "#667487");
    const split = dark ? "rgba(255,255,255,0.06)" : "rgba(15,23,42,0.07)";
    const axis = dark ? "rgba(255,255,255,0.12)" : "rgba(15,23,42,0.14)";
    const purchase = token("--ok", "#34d399");
    const sales = token("--cyan", "#22d3ee");
    const share = token("--warn", "#fbbf24");

    chart.setOption(
      {
        backgroundColor: "transparent",
        grid: { left: 58, right: 58, top: 34, bottom: 34, containLabel: true },
        legend: { top: 2, textStyle: { color: label, fontSize: 11 }, icon: "roundRect" },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow", shadowStyle: { color: split } },
          backgroundColor: dark ? "rgba(9,14,24,0.94)" : "rgba(255,255,255,0.97)",
          borderColor: axis,
          textStyle: { color: token("--text", dark ? "#e6edf7" : "#0f1729"), fontSize: 12 },
          formatter: (rows) => {
            const lines = [rows[0].axisValue];
            rows.forEach((row) => {
              const value = row.seriesName === "占比" ? `${money(row.value)}%` : money(row.value);
              lines.push(`${row.marker}${row.seriesName}：${row.value === null ? "-" : value}`);
            });
            return lines.join("<br/>");
          },
        },
        xAxis: {
          type: "category",
          data: data.labels,
          axisLine: { lineStyle: { color: axis } },
          axisTick: { show: false },
          axisLabel: { color: label, fontSize: 10, interval: data.labels.length > 20 ? 1 : 0 },
        },
        yAxis: [
          {
            type: "value",
            name: "金额",
            nameTextStyle: { color: label, fontSize: 10 },
            axisLabel: { formatter: compact, color: label, fontSize: 10 },
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: split } },
          },
          {
            // 占比和金额差几个数量级，共用一根轴的话折线会被压成一条直线。
            type: "value",
            name: "占比 %",
            nameTextStyle: { color: label, fontSize: 10 },
            axisLabel: { formatter: "{value}%", color: label, fontSize: 10 },
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { show: false },
          },
        ],
        series: [
          { name: "采购入库", type: "bar", barMaxWidth: 14, data: data.purchase, itemStyle: { color: purchase, borderRadius: [3, 3, 0, 0] } },
          { name: "销售", type: "bar", barMaxWidth: 14, data: data.sales, itemStyle: { color: sales, borderRadius: [3, 3, 0, 0] } },
          {
            name: "占比",
            type: "line",
            yAxisIndex: 1,
            smooth: true,
            symbolSize: 4,
            // 销售为 0 的那天占比是 null，连起来会凭空补一条斜线。
            connectNulls: false,
            data: data.share,
            lineStyle: { color: share, width: 1.6 },
            itemStyle: { color: share },
          },
        ],
      },
      true
    );
  };

  paint();
  window.addEventListener("resize", () => chart.resize());
  window.addEventListener("fns-theme-change", paint);
})();

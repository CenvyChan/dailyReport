# 采购数据录入模板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 生成一份按未税口径录入采购入库、粘贴销售明细并按日/月自动计算占比的 Excel 模板。

**Architecture:** 使用 `@oai/artifact-tool` 创建独立 `.xlsx` 工作簿，包含 `采购入库明细`、`销售数据`、`月度对比` 三张表。明细表只保存可编辑源数据，对比表使用有限范围 `SUMIFS` 公式汇总，避免外部链接和整列引用。

**Tech Stack:** Node.js 24、`@oai/artifact-tool` 2.8.6+、Excel `.xlsx`。

## Global Constraints

- 采购和销售金额均为未税金额。
- 必须使用工作区依赖目录中的 `@oai/artifact-tool`，不得使用 `openpyxl`、`pandas.ExcelWriter` 或其他工作簿写入库。
- 所有公式使用有限范围（第 2 至 5000 行），并对销售金额为零的占比返回空值。
- 输出目录为 `E:\DEV\dailyReport\outputs\purchase-template-20260810`。
- 生成后必须检查关键值/公式、扫描 `#REF!`、`#DIV/0!` 等错误，并渲染三张表做视觉检查。

---

### Task 1: Create the workbook builder

**Files:**
- Create: `E:\DEV\dailyReport\.tmp\build_purchase_template.mjs`

**Interfaces:**
- Consumes: source workbook field conventions confirmed in `docs/superpowers/specs/2026-08-10-purchase-entry-template-design.md`.
- Produces: `E:\DEV\dailyReport\outputs\purchase-template-20260810\采购数据录入模板（未税）.xlsx` and one PNG preview per worksheet in the same output directory.

- [ ] **Step 1: Create the builder with the bundled artifact-tool import.**

  Import `fs/promises`, `SpreadsheetFile`, and `Workbook` from `@oai/artifact-tool`; create the output directory and a new workbook with exactly three worksheets named `采购入库明细`, `销售数据`, and `月度对比`.

- [ ] **Step 2: Add the editable detail sheets.**

  Write headers and blank reserved rows through row 5000. Use these exact headers:

  - `采购入库明细`: `供应商名称`, `采购员`, `采购类型`, `入库日期`, `入库数量`, `入库金额（未税）`, `备注`
  - `销售数据`: `客户名称`, `业务跟单`, `销售类型`, `出货日期`, `数量`, `销售金额（未税）`

  Add explicit tables named `PurchaseInputTable` and `SalesInputTable`, freeze the header row, keep text columns left-aligned, dates as `yyyy-mm-dd`, quantities as `#,##0.00`, amounts as `#,##0.00`, and style headers to match the FNS workbook's light title/header treatment. Keep detail inputs empty.

- [ ] **Step 3: Add the monthly comparison sheet and formulas.**

  Use `A1:E1` as a merged title, `A2` as `统计月份`, and `B2` as the first day of the current month. Put headers in `A4:E4`: `日期`, `入库金额（未税）`, `销售金额（未税）`, `占比`, `备注`.

  Seed the following formulas in row 5 and fill through row 35:

  ```text
  A5 =IF(ROW()-4<=DAY(EOMONTH($B$2,0)),DATE(YEAR($B$2),MONTH($B$2),ROW()-4),"")
  B5 =IF($A5="","",SUMIFS('采购入库明细'!$F$2:$F$5000,'采购入库明细'!$D$2:$D$5000,$A5))
  C5 =IF($A5="","",SUMIFS('销售数据'!$F$2:$F$5000,'销售数据'!$D$2:$D$5000,$A5))
  D5 =IF(OR($A5="",$C5=0),"",$B5/$C5)
  ```

  Put `月度合计` in `A36`, `=SUM(B5:B35)` in `B36`, `=SUM(C5:C35)` in `C36`, and `=IF(C36=0,"",B36/C36)` in `D36`. Format dates as `yyyy-mm-dd`, amounts as `#,##0.00`, and ratios as `0.00%`. Freeze rows 4 and hide gridlines on this report sheet.

- [ ] **Step 4: Add usability styling and notes.**

  Use a light-yellow fill for input columns on the two detail sheets, a light-blue fill for formula cells on `月度对比`, a concise note in `A38:E39` stating “采购和销售金额均按未税口径录入；销售数据请粘贴源表六列明细；统计月份请输入该月月初日期。” Set widths and row heights so no labels or values are clipped.

### Task 2: Verify the workbook

**Files:**
- Modify: `E:\DEV\dailyReport\.tmp\build_purchase_template.mjs` if verification exposes a formula or layout issue.
- Verify: `E:\DEV\dailyReport\outputs\purchase-template-20260810\采购数据录入模板（未税）.xlsx`

**Interfaces:**
- Consumes: workbook produced by Task 1.
- Produces: inspected key ranges, formula-error scan, and three worksheet PNG renders.

- [ ] **Step 1: Add representative test data in an in-memory verification workbook.**

  Insert one purchase row dated `2026-08-10` with amount `100`, one sales row dated `2026-08-10` with amount `250`, set `月度对比!B2` to `2026-08-01`, and verify `B14=100`, `C14=250`, `D14=40.00%`, `B36=100`, `C36=250`, and `D36=40.00%` (row 14 is August 10 because the first date is row 5).

- [ ] **Step 2: Inspect formulas and scan errors.**

  Use `workbook.inspect` on `月度对比!A1:E39` with values and formulas, then use a regex scan for `#REF!|#DIV/0!|#VALUE!|#NAME\?|#N/A`. The scan must return no matches for the blank template and the representative-data workbook.

- [ ] **Step 3: Render all worksheets and inspect the images.**

  Render `采购入库明细!A1:G18`, `销售数据!A1:F18`, and `月度对比!A1:E39` at scale 2. Confirm title/header visibility, readable number formats, and no clipping or overlapping content.

- [ ] **Step 4: Export the final workbook.**

  Export exactly one final `.xlsx` to the output path from the global constraints. Keep previews only as verification artifacts; do not export alternate workbook variants.


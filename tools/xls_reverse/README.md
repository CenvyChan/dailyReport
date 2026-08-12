# xls_reverse — 采购入库 .xls 模板逆向 / 构建工具

一组基于 Excel COM（`pywin32`）与 `olefile` 的一次性脚本，用于从
`demo.xls`（销售模板）逆向出采购版 `采购入库模板.xls`，复用其公式、
Spinner 表单控件与 VBA 工程。**仅在装有 Excel 的 Windows 上可运行。**

## 数据位置

- 源文件：`data/source/*.xls` / `*.xlsx`
- dump 输出：`tools/xls_reverse/dumps/*.txt`（已 gitignore）
- VBA 导出：`tools/xls_reverse/vba_export/`

所有脚本用 `ROOT = Path(__file__).parent.parent.parent` 定位项目根目录，
可从任意工作目录运行，例如：

```bash
python tools/xls_reverse/com_extract.py
```

## 脚本分类

### 检查 / dump（只读）
- `com_extract.py`      — 读 demo.xls 全部公式 → `dumps/formulas_dump.txt`
- `biff_parse.py`       — 纯二进制解析 BIFF8 记录（不依赖 Excel）→ `dumps/sheets_dump.txt`
- `btn_extract.py`      — 列出各表按钮 shape → `dumps/btn_dump.txt`
- `spinner_extract.py`  — 列出 Spinner 控件及 LinkedCell → `dumps/spinner_dump.txt`
- `form_extract.py`     — UserForm 设计器控件 + VBA 组件 → `dumps/form_dump.txt`
- `inspect_new.py`      — 采购入库模板.xls 全表概览 → `dumps/inspect_dump.txt`
- `inspect_summary.py`  — 采购入库汇总表布局 → `dumps/summary_dump.txt`
- `inspect_newsheet.py` — 销售与入库占比 表内容 → `dumps/newsheet_dump.txt`
- `verify_procurement.py` — 成品校验（表头/公式/Spinner/VBA）→ `dumps/verify_dump.txt`

### 构建 / 改写（写文件）
按顺序执行可从 demo.xls 重建成品：
1. `build_procurement.py` — 复制 demo.xls → 采购入库模板.xls，做中文表头/币别字符串替换
2. `refactor_sheet.py`    — 重构“销售与入库占比”表（年/月 Spinner + 本位币公式）
3. `refactor_v2.py`       — 修 Spinner 布局 + 强制自动计算
4. `fix_summary_b.py`     — 补“采购入库汇总表”B7:B18 去年人民币入库数量公式
5. `patch_summary_gl.py`  — 写 G/L 列本位币金额公式
6. `patch_calcmode.py`    — 二进制 patch CALCMODE 记录为自动计算
7. `verify_procurement.py`— 校验成品

> 注意：脚本会强制关闭宏（`AutomationSecurity = 3`）与事件后再打开工作簿。

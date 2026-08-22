# demo.xls 公式与 VBA 完整重构说明

## 0. 前置结论

- 这是一份**飞诺斯采购入库日报 / 年度汇总**模板，不是销售出库。用户口述中的“销售出库日报/汇总”在本文件里实际是 `采购入库日报表` / `采购入库汇总表`，逻辑完全一致（出货日期/客户/数量/金额、内销外销双口径）。
- 所谓“VBA 加密”其实是 **VBE 工程被设了查看口令**（CMG/DPB/GC 哈希只锁住编辑器，并不加密宏字节流）。用 `oletools` 直接把压缩的 Ptg 宏流解出来即可拿到全部源码，无需破解口令。
- 所有公式都能通过 Excel COM 正常读取，没有任何“加密”。

## 1. 工作表与 VBA 代号对照

| 显示名（中文） | VBA CodeName | 内容 | 在 VBA 里出现于 |
|---|---|---|---|
| 数据表 | `Sheet1` | 录入底表：客户/跟单/销售类型/出货日期/数量/金额 | `Sheet1` 类事件 `Worksheet_SelectionChange` |
| 采购入库日报表 | `Sheet4` | 按年月日过滤数据表 + 当日小计/月初至当日累计/月总计 | 由公式驱动 |
| 采购入库汇总表 | `Sheet3` | 按年度 B2 + 月份 1-12 双年对照（去年 / 今年）内销外销汇总 | 由公式驱动 |
| 基础信息表 | `Sheet2` | 客户主数据：客户名 / 跟单人 / 内销外销 | UserForm1 取数源 |
| 汇率 | `Sheet5` | 月份→汇率 查找表 | 公式 VLOOKUP |
| Sheet2 | `Sheet7` | 空（隐藏 visibility=1） | — |

## 2. 整体交互链（用户描述逐条对应）

1. **数据表 A 列单击 → 弹出录入窗口**
   - 触发点：`Sheet1.Worksheet_SelectionChange`。命中 `A2:A20000` 即调 `UserForm1.Show Model`。
   - 用户原话“单击 A4 单元格即出现录入窗口”——文件里实际是 A2 起，A4 当然也在区间内。
2. **录入窗口数据取自 基础信息表**
   - `UserForm_Initialize`：`arr = Sheets("基础信息表").Range("A1").CurrentRegion`，灌进 `ListBox1`，多选 + 复选框样式。
   - `TextBox1_Change`：对 A 列做 `InStr` 模糊匹配，实时筛选 ListBox。
3. **录入后写入数据表，按日期出现在日报表**
   - `CommandButton1_Click`：把选中的若干行 ListBox 数据 + TextBox2(日期)/TextBox3(数量)/TextBox4(金额) 写入 ActiveCell 起的连续行。
   - 数据表 D 列（出货日期）即日报表的过滤键。
4. **日报表用日期上下变动来切换显示**
   - 表单微调按钮（Form 控件 Spinner）：
     - `Spinner 2050` → `LinkedCell=$C$2`，Min2024 Max2050（年）
     - `Spinner 2049`(月) → `LinkedCell=$F$2`，Min1 Max12（月）
     - `Spinner 2049`(日) → `LinkedCell=$I$2`，Min1 Max31（日）
   - C2/F2/I2 一变，B6:O15 的整片 IF+INDEX+MATCH 公式自动重算，呈现当日明细。
5. **汇总表按年度+月度汇总**
   - `Spinner 2050` → `LinkedCell=$B$2`（年），Min2024 Max2050。
   - B2 一变，B7:K18 的 SUMIFS 双年度矩阵全部重算。

---

## 3. 公式（逐单元格，可直接复制回 Excel）

### 3.1 采购入库日报表（Sheet4）

```
C2 = 2026            F2 = 8            I2 = 10          （年/月/日，被 Spinner 控制）
N2 = "汇率："
O2 = ="1:"&VLOOKUP($C$2&"年"&$F$2&"月份", 汇率!$A:$B, 2, 0)

' 日报明细主体（B/F/J/L/N/O 列，行 6~15），以第 6 行为例，其余行把 $A6 换成 $A7...$A15
B6 = =IF(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,
         INDEX(数据表!$A:$A, IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)), "")
F6 = =IF(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,
         INDEX(数据表!$E:$E, IFNA(MIN(MATCH(...)),0)+ROW()-ROW($A$6)), "")     ' 出货数量
J6 = =IF(..., INDEX(数据表!$C:$C, ...+ROW()-ROW($A$6)), "")                  ' 方式(内销/外销)
L6 = =IF(AND(COUNTIF(...)>=A6, J6="内销"),
         INDEX(数据表!$F:$F, ...+ROW()-ROW($A$6)), "")                        ' 人民币(未税)，仅内销
N6 = =IF(AND(COUNTIF(...)>=A6, J6="外销"),
         INDEX(数据表!$F:$F, ...+ROW()-ROW($A$6)), 0)                          ' 美金，仅外销
O6 = =IF(..., INDEX(数据表!$B:$B, ...+ROW()-ROW($A$6)), "")                    ' 负责人

' 底部合计/累计/月总计
A16 = =TEXT(DATE(C2,F2,I2),"yy/m/d")&"合计："
F16 = =SUM(F6:I15)            ' 当日数量合计
L16 = =SUM(L6:M15)            ' 当日人民币合计
N16 = =SUM(N6:N15)            ' 当日美金合计

A17 = =TEXT(DATE(C2,F2,1),"yy/m/d")&"-"&TEXT(DATE(C2,F2,I2),"m/d")&"累计："
F17 = =SUMIFS(数据表!$E:$E, 数据表!$D:$D, ">="&TEXT(DATE(C2,F2,1),"yyyy/m/d"),
              数据表!$D:$D, "<="&TEXT(DATE(C2,F2,I2),"yyyy/m/d"))
L17 = =SUMIFS(数据表!$F:$F, ...日期区间..., 数据表!$C:$C, "内销")
N17 = =SUMIFS(数据表!$F:$F, 数据表!$D:$D, ">="&DATE(C2,F2,1),
              数据表!$D:$D, "<="&DATE(C2,F2,I2), 数据表!$C:$C, "外销")

A18 = =TEXT(DATE(C2,F2,I2),"yy/m")&"月总计："
F18 = =SUMIFS(数据表!$E:$E, 数据表!$D:$D, ">="&DATE(C2,F2,1),
              数据表!$D:$D, "<="&EOMONTH(DATE(C2,F2,1),0))
L18 = =SUMIFS(数据表!$F:$F, ...月初~月末..., 数据表!$C:$C, "内销")
N18 = =SUMIFS(数据表!$F:$F, ...月初~月末..., 数据表!$C:$C, "外销")
```

> 关键技巧：`MIN(MATCH(查找日期,D列,0))` 取该日期首匹配行号，再 `+ROW()-ROW($A$6)` 让每一行向下偏移取第 1、2、3… 条匹配记录，实现“按日期展开当天的多条出货明细”。外面套 `IF(COUNTIF(...)>=$A6, ..., "")` 用序号 A6~A15 控制只在“还有第 N 条”时显示，否则留空。

### 3.2 采购入库汇总表（Sheet3）

```
B2 = 2026                       （年，被 Spinner 控制）
B4 = =(B2-1)&"年度"             ' 去年表头
H4 = =B2&"年度"                 ' 今年表头

' 月份 1~12 对应 7~18 行，以第 7 行为例（ROW()-ROW($H$6)=1 即 1 月）：
' 列含义： B/E 去年内销数量/金额 ; F/G 去年外销数量/金额*汇率
'         H/I 今年内销数量/金额 ; J/K 今年外销数量/金额*汇率
B7 = =SUMIFS(数据表!$E:$E, 数据表!$D:$D, ">="&DATE($B$2-1,ROW()-ROW($H$6),1),
              数据表!$D:$D, "<="&EOMONTH(DATE($B$2-1,ROW()-ROW($H$6),1),0),
              数据表!$C:$C, "内销")
E7 = =SUMIFS(数据表!$F:$F, ...去年该月..., "内销")
F7 = =SUMIFS(数据表!$E:$E, ...去年该月..., "外销")
G7 = =SUMIFS(数据表!$F:$F, ...去年该月..., "外销")
       *IFERROR(VLOOKUP(TEXT(DATE($B$2-1,ROW()-ROW($H$6),1),"yyyy年mm月份"),汇率!$A:$B,2,0),1)
H7 = =SUMIFS(数据表!$E:$E, ...今年该月..., "内销")
I7 = =SUMIFS(数据表!$F:$F, ...今年该月..., "内销")
J7 = =SUMIFS(数据表!$E:$E, ...今年该月..., "外销")
K7 = =SUMIFS(数据表!$F:$F, ...今年该月..., "外销")
       *IFERROR(VLOOKUP(TEXT(DATE($B$2,ROW()-ROW($H$6),1),"yyyy年mm月份"),汇率!$A:$B,2,0),1)

' L 列在 13/14/15 行另有手工 Lxx=Kxx*7.2008 残留（疑似旧版外销折算），可忽略或清理
L13 = =K13*7.2008    L14 = =K14*7.2008    L15 = =K15*7.2008

A19 = 合计
B19:K19 = =SUM(B7:B18) ... =SUM(K7:K18)   ' 12 个月纵向合计
```

> 关键技巧：用 `ROW()-ROW($H$6)` 把“当前行号”映射成“月份 1~12”，因此 B7:K18 是同一套公式向下复制即可，改年只要改 B2。

### 3.3 汇率表（Sheet5）

A 列形如 `2026年8月份`（注意是 `mm` 两位补零）。这是上面 VLOOKUP 的查找键，因此**月份字符串格式必须严格匹配**，否则汇率查不到。日报表 O2 用 `TEXT(...,"yyyy年mm月份")` 也是同样格式，保证匹配。

### 3.4 已命名区域（Defined Names）

- `数据表!_FilterDatabase = 数据表!$A$1:$F$1`（自动筛选残留）
- `基础信息表!_FilterDatabase = =基础信息表!#REF!`（筛选已删除）
- 一批 `_xlfn.*`（FILTER/COUNTIFS/SUMIFS/IFERROR/IFNA/UNIQUE）属于 Excel 内部保留名，#NAME? 是因为旧版 xls 在保存时把这些“未来函数”记成占位名，**不影响公式正常运行**。

---

## 4. VBA 源码（已解出，按模块整理）

> 全部为业务逻辑，无任何恶意行为（不联网、不读盘、不 Shell、不写注册表）。下面给出**可直接导回 VBE** 的版本。导入步骤：Alt+F11 → 文件 → 导入文件。

### 4.1 ThisWorkbook（无代码，仅声明）

### 4.2 Sheet1（数据表）事件 —— 单击 A 列弹窗

```vb
' CodeName: Sheet1  (工作表名: 数据表)
Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    ' 在 A2:A20000 任一单元格单击，就弹出录入窗体
    If Intersect(Target, Range("A2:A20000")) Is Nothing Then Exit Sub
    Cancel = True
    UserForm1.Show Model          ' vbModal 模式
End Sub
```

> 说明：`Cancel` 在 SelectionChange 里其实没作用（它是 BeforeRightClick 参数），原代码就这么写，不影响弹窗。要更严谨可改成 Application.EnableEvents=False 防抖，但保持与原样一致即可。

### 4.3 UserForm1 —— 录入窗体（核心）

**窗体设计器控件清单**（重建时按此放置）：

| 控件 | Name | 类型 | 说明 |
|---|---|---|---|
| 文本框 | `TextBox1` | TextBox | 关键字，模糊筛选客户（Change 事件） |
| 列表框 | `ListBox1` | ListBox | MultiSelect=fmMultiSelectExtended；ListStyle=fmListStyleOption（带复选） |
| 文本框 | `TextBox2` | TextBox | 出货日期，初始化为今天 |
| 文本框 | `TextBox3` | TextBox | 数量（需校验为数字） |
| 文本框 | `TextBox4` | TextBox | 金额 |
| 按钮 | `CommandButton1` | CommandButton | 录入 |
| 按钮 | `CommandButton2` | CommandButton | 关闭 |

**窗体代码**：

```vb
' === UserForm1.frm ===
Attribute VB_Name = "UserForm1"

Private Sub UserForm_Initialize()
    arr = Sheets("基础信息表").Range("A1").CurrentRegion
    With ListBox1
        .List = arr
        .MultiSelect = fmMultiSelectExtended      ' 可多选（含 Shift 区选）
        .ColumnCount = UBound(arr, 2)             ' 列数 = 基础信息表列数
        .ListStyle = fmListStyleOption            ' 每行前显示复选框
    End With
    ' 默认出货日期 = 今天
    TextBox2.Text = DateSerial(Year(Date), Month(Date), Day(Date))
End Sub

Private Sub TextBox1_Change()
    ' 模糊匹配：在基础信息表 A 列里找包含 TextBox1 文字的客户
    Dim drr()
    Dim n As Long
    arr = Sheets("基础信息表").Range("A1").CurrentRegion
    For i = 1 To UBound(arr)
        If InStr(CStr(arr(i, 1)), TextBox1.Text) > 0 Then
            n = n + 1
            ReDim Preserve drr(1 To ListBox1.ColumnCount, 1 To n)
            For j = 1 To UBound(arr, 2)
                drr(j, n) = arr(i, j)
            Next
        End If
    Next
    If n > 1 Then
        ListBox1.List = Application.Transpose(drr)
    ElseIf n = 1 Then
        ReDim crr(1 To 1, 1 To UBound(drr))
        For i = 1 To UBound(drr)
            crr(1, i) = drr(i, 1)
        Next
        ListBox1.List = crr
    Else
        ListBox1.Clear
    End If
End Sub

Private Sub CommandButton1_Click()
    ' --- 校验数量 ---
    If Val(TextBox3.Text) = 0 And TextBox3.Text <> "0" Then
        MsgBox "订单数量输入不正确": Exit Sub
    End If

    ' --- 把选中的多行 + 三个输入框 组成数组 ---
    Dim brr(), grr
    Dim k As Long, m As Long
    For i = 0 To ListBox1.ListCount - 1
        If ListBox1.Selected(i) = True Then
            k = k + 1
            ReDim Preserve brr(1 To ListBox1.ColumnCount + 3, 1 To k)
            For j = 0 To ListBox1.ColumnCount - 1
                brr(j + 1, k) = ListBox1.List(i, j)     ' 客户/跟单/类型
            Next
            brr(ListBox1.ColumnCount + 1, k) = TextBox2.Text   ' 出货日期
            brr(ListBox1.ColumnCount + 2, k) = TextBox3.Text   ' 数量
            brr(ListBox1.ColumnCount + 3, k) = TextBox4.Text   ' 金额
        End If
    Next
    If k = 0 Then MsgBox "请选择数据": Exit Sub

    ' --- 写入 ActiveCell 起的连续行 ---
    grr = Application.Transpose(brr)
    If k = 1 Then
        For i = 1 To UBound(grr)
            ActiveCell.Offset(, m) = grr(i): m = m + 1
        Next
        ActiveCell.Offset(1).Select
    Else
        For i = 1 To UBound(grr)
            For j = 1 To UBound(grr, 2)
                ActiveCell.Offset(, m) = grr(i, j): m = m + 1
            Next
            ActiveCell.Offset(1).Select: m = 0
        Next
    End If

    ' --- 跳到 A 列下一个空行，等待下次录入 ---
    Cells(Rows.Count, "A").End(3).Offset(1).Select
End Sub

Private Sub CommandButton2_Click()
    Unload Me
End Sub

Private Sub UserForm_QueryClose(Cancel As Integer, CloseMode As Integer)
    Unload Me
End Sub

' 双击列表项也可改数（原代码注释掉了，保留空壳）
Private Sub ListBox1_DblClick(ByVal Cancel As MSForms.ReturnBoolean)
End Sub
```

### 4.4 模块1 —— 按钮宏（基础信息表 → 数据表，内销）

```vb
Attribute VB_Name = "模块1"
Sub Button1_Click()
    Dim srcSheet As Worksheet, destSheet As Worksheet
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("Sheet1")        ' 注意：目标工作表名是"Sheet1"（其实指数据表）
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="内销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("A1").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub
```

### 4.5 模块3 —— 选项按钮宏（基础信息表 → 新增订单查询表）

```vb
Attribute VB_Name = "模块3"
Sub OptionButton4_Click()      ' 内销
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("新增订单查询表")
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="内销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("F5").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub

Sub OptionButton6_Click()      ' 外销
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("新增订单查询表")
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="外销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("F5").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub
```

> 注：`模块1` / `模块3` 引用到的 “Sheet1”、“新增订单查询表” 两个工作表名在当前文件里已不存在（被删/改名过），如果要让这两个按钮宏生效，需要在表里建对应表名，或把字符串改成 `数据表`。

### 4.6 Spinner（微调按钮）—— 不需要 VBA

`采购入库日报表` 上 3 个 Spinner、`采购入库汇总表` 上 1 个 Spinner 都是 **表单控件**，直接在“设置控件格式”里指定 `LinkedCell`、`Min/Max/Step` 即可，**没有任何 VBA**。配置如下：

| 工作表 | 控件 | LinkedCell | Min | Max | Step |
|---|---|---|---|---|---|
| 采购入库日报表 | Spinner(月) | $F$2 | 1 | 12 | 1 |
| 采购入库日报表 | Spinner(年) | $C$2 | 2024 | 2050 | 1 |
| 采购入库日报表 | Spinner(日) | $I$2 | 1 | 31 | 1 |
| 采购入库汇总表 | Spinner(年) | $B$2 | 2024 | 2050 | 1 |

加 Spinner 的方式：开发工具 → 插入 → 表单控件 → 微调按钮 → 画到表上 → 右键设置控件格式 → 单元格链接填上面对应地址。

---

## 5. 重建步骤（从空文件到完整模板）

1. 新建 6 张工作表，依次重命名为：`数据表`、`采购入库日报表`、`采购入库汇总表`、`基础信息表`、`汇率`、`Sheet2`（隐藏）。
2. 基础信息表录入：A1:C1 = `示例供应商甲 / 示例员工丙 / 内销`，往下续行。
3. 汇率表录入：A 列 `2026年8月份` 格式，B 列汇率数值。
4. 日报表按 §3.1 放 C2/F2/I2（先填 2026/8/10 测试）、放标题与小计公式，再放 B6:O15 的明细公式（向下复制到第 15 行）。
5. 汇总表按 §3.2 放 B2(年) 与 B7:K18 公式（向下复制到第 18 行）。
6. 在日报表/汇总表上加 4 个 Spinner 微调按钮，按 §4.6 表设置 LinkedCell。
7. Alt+F11 → 文件 → 导入：`UserForm1.frm`、`模块1.bas`、`模块3.bas`；双击 数据表(sheet1) 粘贴 `Worksheet_SelectionChange`。
8. 启用宏：文件 → 选项 → 信任中心 → 宏设置 → 启用。
9. 测试：在数据表 A 列单击 → 弹窗 → 选客户 → 填日期/数量/金额 → 录入；调日报表 Spinner，应能看到当天明细；调汇总表 Spinner，应看到按月汇总。

## 6. 已知小坑 / 提醒

- **基础信息表必须无空行**：UserForm 用 `Range("A1").CurrentRegion` 取数，中间一旦断行，后面的客户就不会进 ListBox。
- **日期列必须真日期**：日报表用 `DATE($C$2,$F$2,$I$2)` 比较数据表 D 列。D 列若存成文本日期会匹配不到。UserForm 写入的 `TextBox2.Text` 默认是字符串，建议在录入时 `CDate()` 一下，或在数据表 D 列预先设日期格式。
- **汇率表 A 列字符串格式**：必须 `yyyy年mm月份`（月份两位补零）。原汇总表某些月份（如 2025年1月份）其实没补零，会导致 VLOOKUP 在 1 月查不到 → 落到 `IFERROR(...,1)`，外销折算按汇率 1 处理，结果偏大。建议统一补零。
- **L13:L15 残留公式 `=Kxx*7.2008`** 是历史遗留，可删。
- **模块1/模块3 按钮宏引用了不存在的表名**，要么补表，要么把字符串改成实际表名。

## 7. 提取方法（备忘）

- VBA 解出：`oletools.olevba.VBA_Parser('demo.xls').extract_macros()`（VBE 口令只锁编辑器，不解锁也能取流）。
- 公式读取：Excel COM `cell.Formula`（`ReadOnly=True`，不保存）。
- Spinner 配置：`Shape.ControlFormat.LinkedCell / Min / Max / SmallChange`。

— 提取脚本与原始 dump：`vba_dump.txt`、`formulas_dump.txt`、`sheets_dump.txt`、`spinner_dump.txt`、`btn_dump.txt`。

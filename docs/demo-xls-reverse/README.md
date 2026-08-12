# demo.xls 结构与逻辑还原

来源：`demo.xls`（BIFF8 / 代码页 936，由 WPS 保存，带 `ETExtData` 流）。

关于「VBA 加密」：`_VBA_PROJECT_CUR/PROJECT` 流里有 `CMG` / `DPB` / `GC` 三个保护记录，
它只锁 VBE 界面（不让你在 Excel 里看代码），**模块源码本身只是 MS-OVBA 的 RLE 压缩，不是加密**。
所以下面的 VBA 是从 OLE 流里原样解出来的真实源码，不是我按效果反推的。
`vba/` 目录里放的是解锁副本用 Excel 原生导出的同一份代码（见第七节），可直接导入。

---

## 一、工作表与 CodeName

| 序 | 表名 | CodeName | 可见 | 用途 |
|---|---|---|---|---|
| 1 | 数据表 | `Sheet1` | 是 | 明细流水，录入落地表 |
| 2 | 采购入库日报表 | `Sheet4` | 是 | 按日展示 |
| 3 | 采购入库汇总表 | `Sheet3` | 是 | 按年/月汇总 |
| 4 | 基础信息表 | `Sheet2` | 是 | 客户 / 业务跟单 / 销售类型 主数据 |
| 5 | 汇率 | `Sheet5` | 是 | 月度汇率对照 |
| 6 | Sheet2 | `Sheet7` | 隐藏 | 空表 |

CodeName 和表名是错位的：CodeName `Sheet2` 指的是「基础信息表」，而那张真叫「Sheet2」的空表 CodeName 是 `Sheet7`。
VBA 里的 `Sheet1` 就是「数据表」。改表名不影响 VBA，但改 CodeName 会。

你说的 `销售出库日报表` / `销售出库汇总表`，在这个文件里叫 `采购入库日报表` / `采购入库汇总表`
（A1 标题文字分别是「飞诺斯采购入库日报表」和「飞诺斯年度销售汇总表」，本身就不一致）。
逻辑一模一样，改名即可，但公式里所有 `数据表!` / `汇率!` 之外的跨表引用要同步替换。

---

## 二、数据流

`数据表` 表头 `A1:F1` = 客户名称 | 业务跟单 | 销售类型 | 出货日期 | 数量 | 金额

1. 单击 `数据表` A 列（`A2:A20000` 范围内任一格，含你说的 A4）→ `Worksheet_SelectionChange` 弹出 `UserForm1`（标题「录入窗口」）。
2. 窗口列表框数据源 = `基础信息表!A1.CurrentRegion`，即 A:C 三列（客户 / 跟单 / 销售类型）。
3. 点「录入」→ 把列表里勾选的行按「3 列基础信息 + 日期 + 数量 + 金额」共 6 列，从 `ActiveCell` 起逐行写进 `数据表`。
4. `采购入库日报表` 以 `C2`/`F2`/`I2`（年/月/日）为条件，用 `COUNTIF` 判断当天有几条、`MATCH` 定位首条、`INDEX` 逐行取数，填到 6~15 行；3 个微调项控制年月日上下变动。
5. `采购入库汇总表` 以 `B2`（年）为条件，用 `SUMIFS` 按 1~12 月汇总；左半区是上一年 `B2-1`，右半区是本年 `B2`；1 个微调项控制年份。

---

## 三、VBA

### 数据表（CodeName `Sheet1`）—— 触发录入窗口

```vb
Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    If Intersect(Target, Range("A2:A20000")) Is Nothing Then Exit Sub
    Cancel = True
    UserForm1.Show Model
End Sub
```

两处要留意（原样保留，不是我写错）：

- `Cancel = True` —— `SelectionChange` 没有 `Cancel` 参数，这里是个未声明的隐式变量，没有任何作用。
- `Show Model` —— 应该是 `Modal`，拼错成了未声明变量 `Model`，值为 `Empty`→`0`→正好等于 `vbModal`，所以歪打正着是模态显示。整个工程没有 `Option Explicit`，所以不报错。

其余 `ThisWorkbook`、`Sheet2/3/4/5/7` 类模块都只有属性头，没有代码。

### UserForm1「录入窗口」

窗体本身：`Caption = "录入窗口"`，`ClientWidth = 5370`，`ClientHeight = 6510`（缇），`StartUpPosition = 1`（所有者中心）。

控件清单（共 11 个，精确坐标见第七节）：

| 控件 | 作用 |
|---|---|
| `Label1` + `TextBox1` | 关键字，输入即模糊筛选列表 |
| `ListBox1` | 基础信息表数据，多选 |
| `Label2` + `TextBox2` | 出货日期，初始化为当天 |
| `Label3` + `TextBox3` | 数量（必填、必须是数字） |
| `Label4` + `TextBox4` | 金额 |
| `CommandButton1` | 录入 |
| `CommandButton2` | 关闭 |

代码见 `vba/UserForm1.frm`，关键四段：

```vb
Private Sub UserForm_Initialize()
    arr = Sheets("基础信息表").Range("A1").CurrentRegion
    With ListBox1
        .List = arr
        .MultiSelect = fmMultiSelectExtended
        .ColumnCount = UBound(arr, 2)
        .ListStyle = fmListStyleOption
        LISTBOX_Post_Flag = 1
        LISTBOX_Mouse_Flag = 1
    End With
    TextBox2.Text = DateSerial(Year(Date), Month(Date), Day(Date))
End Sub
```

`ColumnCount` 是按基础信息表的实际列数动态定的，所以基础信息表加列，列表框自动跟着加列。
`LISTBOX_Post_Flag` / `LISTBOX_Mouse_Flag` 是 WPS 特有的未声明变量，在 Excel 里是空操作，可以删。

```vb
Private Sub TextBox1_Change()
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
```

只对第 1 列（客户名称）做 `InStr` 包含匹配。`n = 1` 要单独处理，是因为 `Application.Transpose`
对单行数组会降维成一维，直接赋给 `.List` 会变成一列。
`ReDim Preserve` 只能改最后一维，所以数组是「列 × 行」倒着存的，最后统一 `Transpose`。

```vb
Private Sub CommandButton1_Click()
    If Val(TextBox3.Text) = 0 And TextBox3.Text <> "0" Then
        MsgBox "订单数量输入不正确": Exit Sub
    End If
    Dim brr(), grr
    Dim k As Long, m As Long
    For i = 0 To ListBox1.ListCount - 1
        If ListBox1.Selected(i) = True Then
            k = k + 1
            ReDim Preserve brr(1 To ListBox1.ColumnCount + 3, 1 To k)
            For j = 0 To ListBox1.ColumnCount - 1
                brr(j + 1, k) = ListBox1.List(i, j)
            Next
            brr(ListBox1.ColumnCount + 1, k) = TextBox2.Text
            brr(ListBox1.ColumnCount + 2, k) = TextBox3.Text
            brr(ListBox1.ColumnCount + 3, k) = TextBox4.Text
        End If
    Next
    If k = 0 Then MsgBox "请选择数据": Exit Sub
    grr = Application.Transpose(brr)
    If k > 0 Then
        If k = 1 Then
            For i = 1 To UBound(grr)
                ActiveCell.Offset(, m) = grr(i)
                m = m + 1
            Next
            ActiveCell.Offset(1).Select
        Else
            For i = 1 To UBound(grr)
                For j = 1 To UBound(grr, 2)
                    ActiveCell.Offset(, m) = grr(i, j)
                    m = m + 1
                Next
                ActiveCell.Offset(1).Select
                m = 0
            Next
        End If
    End If
    Cells(Rows.Count, "A").End(3).Offset(1).Select
End Sub

Private Sub CommandButton2_Click()
    Unload Me
End Sub

Private Sub UserForm_QueryClose(Cancel As Integer, CloseMode As Integer)
    Unload Me
End Sub
```

`ColumnCount + 3` 就是「基础信息 3 列 + 日期 + 数量 + 金额」= 6 列，正好对上数据表 A:F。
写完最后 `Cells(Rows.Count,"A").End(3).Offset(1).Select` 把光标推到 A 列最后一行的下一行
（`3` = `xlUp` 的字面值），所以下一次录入自动接着往下写。

### 模块1 / 模块3 —— 死代码

三个过程 `模块1.Button1_Click`、`模块3.OptionButton4_Click`、`模块3.OptionButton6_Click`
结构完全一样：对 `基础信息表!A1:C200` 按第 3 列（销售类型）自动筛选「内销」或「外销」，
把可见单元格复制到目标表，再 `AutoFilterMode = False`。

```vb
Sub Button1_Click()
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("Sheet1")
    Set srcRange = srcSheet.Range("A1:C200")
    srcRange.AutoFilter field:=3, Criteria1:="内销"
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("A1").PasteSpecial xlPasteValues
    srcSheet.AutoFilterMode = False
End Sub
```

这三个都是**从别的模板抄过来的残留，当前文件里跑不通也没有入口**：

- `模块3` 两个过程的目标表 `新增订单查询表` 在本工作簿里不存在，一执行就 9 号下标越界。
- `模块1` 的目标表写的是 `Sheets("Sheet1")`（按表名找，指那张隐藏空表），会把主数据直接盖到空表 A1。
- 三个过程都没有任何控件的 `OnAction` 指向它们（本文件里只有 4 个微调项，`OnAction` 全为空）。

可以整个删掉，不影响录入和报表。

---

## 四、日期选择控件（微调项）接线

全是表单控件里的「微调项 / Spinner」，靠 `LinkedCell` 直接写单元格，没有一行 VBA。
公式引用这些单元格，所以点一下上下箭头，报表就整体重算。

| 所在表 | 控件 | 链接单元格 | 最小 | 最大 | 步长 |
|---|---|---|---|---|---|
| 采购入库日报表 | `Spinner 2050` | `$C$2`（年） | 2024 | 2050 | 1 |
| 采购入库日报表 | `Spinner 2049` | `$F$2`（月） | 1 | 12 | 1 |
| 采购入库日报表 | `Spinner 2049` | `$I$2`（日） | 1 | 31 | 1 |
| 采购入库汇总表 | `Spinner 2050` | `$B$2`（年） | 2024 | 2050 | 1 |

日报表上有两个控件重名（都叫 `Spinner 2049`），只是链接单元格不同，不影响运行。
日的上限固定 31，不跟着月份变，所以 2 月能选到 31 日，此时 `DATE(y,2,31)` 会溢出到 3 月 2、3 日。

---

## 五、公式

### 采购入库日报表

布局：第 1 行标题；第 2 行日期选择器 + 汇率；第 4~5 行表头；**第 6~15 行明细（固定 10 行）**；
第 16/17/18 行三级合计。合并格：`B:E` = 客户，`F:I` = 出货数量，`J:K` = 方式，`L:M` = 人民币，`N` = 美金，`O` = 负责人。

汇率显示（`O2`）：

```
="1:"&VLOOKUP($C$2&"年"&$F$2&"月份",汇率!$A:$B,2,0)
```

明细行以 `A6=1 … A15=10` 作序号，5 个取数公式（这里给第 6 行，7~15 行只是 `$A6` 递增）：

```
B6  客户   =IF(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,INDEX(数据表!$A:$A,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)),"")
F6  数量   =IF(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,INDEX(数据表!$E:$E,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)),"")
J6  方式   =IF(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,INDEX(数据表!$C:$C,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)),"")
O6  负责人 =IF(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,INDEX(数据表!$B:$B,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)),"")
L6  人民币 =IF(AND(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,$J6="内销"),INDEX(数据表!$F:$F,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)),"")
N6  美金   =IF(AND(COUNTIF(数据表!D:D,DATE($C$2,$F$2,$I$2))>=$A6,$J6="外销"),INDEX(数据表!$F:$F,IFNA(MIN(MATCH(DATE($C$2,$F$2,$I$2),数据表!$D:$D,0)),0)+ROW()-ROW($A$6)),0)
```

拆开看就三件事：

1. `COUNTIF(数据表!D:D, DATE($C$2,$F$2,$I$2)) >= $A6` —— 当天记录数够不够第 N 行，不够就留空，这是「显示几行」的开关。
2. `MATCH(日期, 数据表!$D:$D, 0)` —— 找当天**第一条**记录的行号；`MIN(...)` 在这里没作用（`MATCH` 本来就返回单值），`IFNA(...,0)` 兜没匹配的情况。
3. `+ROW()-ROW($A$6)` —— 在首行基础上加偏移，第 6 行 +0、第 7 行 +1…… 也就是**从首条开始连续往下取**。
4. `L`（人民币）和 `N`（美金）靠 `$J6` 的「内销/外销」二选一，同一条记录只会落在其中一列。

三级合计：

```
A16 =TEXT(DATE(C2,F2,I2),"yy/m/d")&"合计："          F16 =SUM(F6:I15)   L16 =SUM(L6:M15)   N16 =SUM(N6:N15)
A17 =TEXT(DATE(C2,F2,1),"yy/m/d")&"-"&TEXT(DATE(C2,F2,I2),"m/d")&"累计："
A18 =TEXT(DATE(C2,F2,I2),"yy/m")&"月总计："
```

```
F17 =SUMIFS(数据表!$E:$E,数据表!$D:$D,">="&TEXT(DATE(C2,F2,1),"yyyy/m/d"),数据表!$D:$D,"<="&TEXT(DATE(C2,F2,I2),"yyyy/m/d"))
L17 =SUMIFS(数据表!$F:$F,数据表!$D:$D,">="&TEXT(DATE(C2,F2,1),"yyyy/m/d"),数据表!$D:$D,"<="&TEXT(DATE(C2,F2,I2),"yyyy/m/d"),数据表!$C:$C,"内销")
N17 =SUMIFS(数据表!$F:$F,数据表!$D:$D,">="&DATE(C2,F2,1),数据表!$D:$D,"<="&DATE(C2,F2,I2),数据表!$C:$C,"外销")

F18 =SUMIFS(数据表!$E:$E,数据表!$D:$D,">="&DATE(C2,F2,1),数据表!$D:$D,"<="&EOMONTH(DATE(C2,F2,1),0))
L18 =SUMIFS(数据表!$F:$F,数据表!$D:$D,">="&DATE(C2,F2,1),数据表!$D:$D,"<="&EOMONTH(DATE(C2,F2,1),0),数据表!$C:$C,"内销")
N18 =SUMIFS(数据表!$F:$F,数据表!$D:$D,">="&DATE(C2,F2,1),数据表!$D:$D,"<="&EOMONTH(DATE(C2,F2,1),0),数据表!$C:$C,"外销")
```

第 16 行是「当天」，第 17 行是「月初到当天」，第 18 行是「整月」。
`F16` 写成 `SUM(F6:I15)` 是因为 F:I 是合并格，横向多扫几列不影响结果。
17 行用 `TEXT(...,"yyyy/m/d")` 拼字符串、18 行直接用日期序列值，两种写法都能算对，只是不统一。

### 采购入库汇总表

布局：`B2` = 年份（微调项）；第 4 行两个年度表头；第 5 行内销/外销；第 6 行出货数量/金额；
**第 7~18 行 = 1~12 月**；第 19 行合计。

```
B4 =(B2-1)&"年度"      H4 =B2&"年度"
```

月份不是靠 A 列的 1~12 取的，而是靠行号算的：`ROW()-ROW($H$6)`，第 7 行得 1、第 18 行得 12。
每列一条 `SUMIFS`，区间是 `月初 → EOMONTH(月初,0)`：

上一年（`$B$2-1`）：

```
B列 上年内销数量 =SUMIFS(数据表!$E:$E,数据表!$D:$D,">="&DATE($B$2-1,ROW()-ROW($H$6),1),数据表!$D:$D,"<="&EOMONTH(DATE($B$2-1,ROW()-ROW($H$6),1),0),数据表!$C:$C,"内销")
E列 上年内销金额 =SUMIFS(数据表!$F:$F, …同上… ,数据表!$C:$C,"内销")
F列 上年外销数量 =SUMIFS(数据表!$E:$E, …同上… ,数据表!$C:$C,"外销")
G列 上年外销金额 =SUMIFS(数据表!$F:$F, …同上… ,数据表!$C:$C,"外销")*IFERROR(VLOOKUP(TEXT(DATE($B$2-1,ROW()-ROW($H$6),1),"yyyy年mm月份"),汇率!$A:$B,2,0),1)
```

本年（`$B$2`）：

```
H列 本年内销数量 =SUMIFS(数据表!$E:$E,数据表!$D:$D,">="&DATE($B$2,ROW()-ROW($H$6),1),数据表!$D:$D,"<="&EOMONTH(DATE($B$2,ROW()-ROW($H$6),1),0),数据表!$C:$C,"内销")
I列 本年内销金额 =SUMIFS(数据表!$F:$F, …同上… ,数据表!$C:$C,"内销")
J列 本年外销数量 =SUMIFS(数据表!$E:$E, …同上… ,数据表!$C:$C,"外销")
K列 本年外销金额 =SUMIFS(数据表!$F:$F, …同上… ,数据表!$C:$C,"外销")*IFERROR(VLOOKUP(TEXT(DATE($B$2,ROW()-ROW($H$6),1),"yyyy年mm月份"),汇率!$A:$B,2,0),1)
```

合计行：`B19`/`E19`/`F19`/`G19`/`H19`/`I19`/`J19`/`K19` 各自 `=SUM(x7:x18)`。

外销金额列（`G`、`K`）会再乘一次月度汇率，把美金折成人民币，查不到汇率就 `IFERROR` 退化成 ×1。

### 汇率表

`A` 列是**文本**「2024年10月份」……「2026年8月份」（单元格格式虽然是 `yyyy/m/d`，但值是字符串），`B` 列是数字汇率。
`A2:B24` 覆盖 2024年10月 ~ 2026年8月。

### 定义名称

只有两个自动生成的筛选区（`数据表!_FilterDatabase` = `$A$1:$F$1`，`基础信息表!_FilterDatabase` 已是 `#REF!`），
外加 `_xlfn.UNIQUE`、`_xlfn._xlws.FILTER`、`_xlfn.SUMIFS`、`_xlfn.IFERROR`、`_xlfn.IFNA`、`_xlfn.COUNTIFS` 这几个占位名称——
这是 WPS/低版本 Excel 存 BIFF8 时留下的函数兼容壳，指向 `#NAME?`，不用管，也别删。

---

## 六、实测出来的缺陷

以下都是在 Excel 里打开原文件核对过计算结果的，不是猜的。

**1. 汇总表的汇率永远查不中 1~9 月（已确认）**

汇总表用 `TEXT(...,"yyyy年mm月份")` 拼出来的是 `2026年08月份`（月份补零），
而汇率表 A 列存的是 `2026年8月份`（不补零）。两者不相等 → `VLOOKUP` 失败 → `IFERROR` 返回 1 → 外销金额没折算。
只有 10、11、12 月因为本来就是两位数才查得中。

实测：数据表里 2026-08-10 有一笔外销 1412，汇总表 `K14`（本年 8 月外销金额）算出来就是 `1412`，没乘 6.8067。
日报表的 `O2` 用的是 `$C$2&"年"&$F$2&"月份"` 拼接（不补零），反而是对的。

改法二选一：汇总表改成 `TEXT(...,"yyyy年m月份")`，或者把汇率表 A 列统一成补零写法。

**2. 汇总表 `B7` 是空的（已确认）**

`B7`（上一年 1 月内销数量）压根没有公式，`B8:B18` 才有。往上补一格即可。

**3. 汇总表 `L13:L15` 是残留垃圾**

`=K13*7.2008`、`=K14*7.2008`、`=K15*7.2008`，写死了 2025 年 5 月的汇率，落在标题合并区 `A1:K1` 之外，
表格边框里看不见但会参与计算。当初大概是用来手工验汇率的，直接删。

**4. 日报表明细依赖「数据表按日期排序且同日记录连续」**

取数逻辑是 `MATCH` 找当天首条 + `ROW()` 偏移**连续往下读**，并不做逐条筛选。
录入窗口是从 `ActiveCell` 往下追加写入的，所以只要有人插行、改日期、或者跳到中间某行录入，
同一天的记录一旦不连续，日报表就会把别的日期的记录显示进来（`COUNTIF` 的行数开关也拦不住）。
明细区还固定只有 10 行，当天超过 10 条就只显示前 10 条，但第 16 行 `SUM(F6:I15)`「合计」也只加这 10 条，
和第 17/18 行用 `SUMIFS` 全量算出来的数会对不上。

**5. 日期上限**

日的微调项固定 1~31，不随月份变。2 月选到 30、31 时 `DATE(y,2,31)` 会溢出成 3 月 2/3 日。

**6. `Show Model` / `Cancel = True`**

见第三节。目前歪打正着能跑，但工程一旦加 `Option Explicit` 就会编译不过。

---

## 七、解锁副本与可导入的窗体

`demo_unlocked.xls` 是 `demo.xls` 的副本，已解掉 VBE 界面锁（原文件没动）。
在 Excel 里 `Alt+F11` 可以直接看/改所有模块和 `UserForm1` 的设计视图。

做法见 `unlock_vba_project.py`：MS-OVBA 2.4.3 里 `PROJECT` 流的三个值用的是同一套可逆混淆，
`ProjKey` 本身就存在密文里，所以不需要任何口令，解出 data 换掉再按原 seed 混淆回去即可。

| 字段 | 含义 | 原值 | 改为 |
|---|---|---|---|
| `CMG` | ProjectProtectionState | `0x00000005`（用户锁定 + VBE 锁定） | `0x00000000` 未保护 |
| `DPB` | ProjectPassword | 29 字节口令块 | `0x00` 无口令 |
| `GC` | ProjectVisibilityState | `0x00` 不可见 | `0xFF` 可见 |

`olefile` 只能等长覆写流，所以 `PROJECT` 流尾部补了 56 字节 CRLF 凑回原来的 927 字节。
脚本自带回环校验：先解密再用原 seed 重新加密，能逐字节复现原 hex 才继续，避免算法写错却静默产出坏文件。
实测 `demo_unlocked.xls` 用 Excel 打开正常（无修复提示），`VBProject.Protection = 0`。

### vba/ 目录

现在是从解锁副本里用 Excel 原生导出的，可直接 `导入文件` 用：

```
UserForm1.frm + UserForm1.frx   ← 必须成对，.frm 里靠 OleObjectBlob 引用 .frx
Sheet1.cls                      ← 数据表的 SelectionChange
模块1.bas / 模块3.bas           ← 死代码，可以不导
ThisWorkbook.cls / Sheet2~7.cls ← 空壳，不用导
```

已验证：把 `UserForm1.frm` 导进一个新工作簿，11 个控件连坐标一起完整还原。
文件是 GBK 编码（VBA 导出的惯例），用文本编辑器打开中文可能是乱码，但 VBE 导入时正常。

窗体实际布局（单位：磅，`ClientWidth 5370 × ClientHeight 6510` 缇 ≈ 358 × 434 磅）：

| 控件 | Left | Top | Width | Height |
|---|---|---|---|---|
| `Label1` | 0 | 12 | 72 | 18 |
| `TextBox1` | 66 | 6 | 138 | 18 |
| `CommandButton2` | 234 | 6 | 24 | 18 |
| `ListBox1` | 6 | 30 | 258 | 235.6 |
| `Label2` | 6 | 282 | 30 | 18 |
| `TextBox2` | 30 | 276 | 60 | 18 |
| `Label3` | 6 | 306 | 72 | 18 |
| `TextBox3` | 30 | 300 | 60 | 18 |
| `Label4` | 96 | 306 | 72 | 18 |
| `TextBox4` | 120 | 300 | 60 | 18 |
| `CommandButton1` | 204 | 300 | 54 | 18 |

关闭按钮 `CommandButton2` 只有 24 磅宽、贴在右上角搜索框旁边，不在下方按钮区。

---

## 八、目录内文件

| 文件 | 说明 |
|---|---|
| `vba/` | Excel 原生导出的全部模块，可直接导入 |
| `xls_dump.json` | 全量单元格值/公式、定义名称、合并区、控件接线的原始数据 |
| `dump_xls.py` | 上面这份 json 的生成脚本（Excel COM，强制禁用宏） |
| `unlock_vba_project.py` | `inspect` 查看保护状态 / `unlock` 生成解锁副本 |



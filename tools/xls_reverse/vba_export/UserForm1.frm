VERSION 5.00
' UserForm1.frm - 录入窗体（飞诺斯采购入库）
' 控件清单（需在设计器里手工放置，名称必须与下方一致）：
'   TextBox1       关键字模糊筛选
'   ListBox1        多选列表(数据源=基础信息表A1.CurrentRegion)
'   TextBox2        出货日期(初始化为今天)
'   TextBox3        数量
'   TextBox4        金额
'   CommandButton1  录入
'   CommandButton2  关闭
Attribute VB_Name = "UserForm1"
Attribute VB_Base = "0{764BC436-B3AB-40ED-A348-44148B0A5797}{28D40F44-DE8F-428E-9AFD-0F9546C97BF2}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = False

Private Sub UserForm_Initialize()
    ' 取基础信息表整块作为列表数据源
    arr = Sheets("基础信息表").Range("A1").CurrentRegion
    With ListBox1
        .List = arr
        .MultiSelect = fmMultiSelectExtended      ' 可多选(含Shift区选)
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

Private Sub ListBox1_DblClick(ByVal Cancel As MSForms.ReturnBoolean)
    ' 双击改数据(原文件注释掉了，保留空壳)
End Sub

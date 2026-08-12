VERSION 5.00
Begin {C62A69F0-16DC-11CE-9E98-00AA00574A4F} UserForm1 
   Caption         =   "录入窗口"
   ClientHeight    =   6510
   ClientLeft      =   105
   ClientTop       =   450
   ClientWidth     =   5370
   OleObjectBlob   =   "UserForm1.frx":0000
   StartUpPosition =   1  '所有者中心
End
Attribute VB_Name = "UserForm1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False

Private Sub CommandButton1_Click()
    If Val(TextBox3.Text) = 0 And TextBox3.Text <> "0" Then
        MsgBox "订单数量输入不正确": Exit Sub
    End If
    '录入
    Dim brr(), grr
    Dim k As Long, m As Long
    For i = 0 To ListBox1.ListCount - 1
        If ListBox1.Selected(i) = True Then
            k = k + 1
            ReDim Preserve brr(1 To ListBox1.ColumnCount + 3, 1 To k)
            For j = 0 To ListBox1.ColumnCount - 1
                brr(j + 1, k) = ListBox1.List(i, j)
                '选中的数据存入数组brr
            Next
            'Sheet1.Range("H1") = j
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
    '取消选中
    Cells(Rows.Count, "A").End(3).Offset(1).Select
                
End Sub

Private Sub CommandButton2_Click()
    Unload Me
End Sub

Private Sub ListBox1_DblClick(ByVal Cancel As MSForms.ReturnBoolean)
    '双击的时候也可以更改数据
   ' Dim crr()
  '  Dim m As Long
  '  For i = 0 To ListBox1.ListCount - 1
  '      If ListBox1.Selected(i) = True Then
  '          m = m + 1
  '        ReDim Preserve crr(1 To ListBox1.ColumnCount + 2, 1 To m)
  '         For j = 0 To ListBox1.ColumnCount - 1
  '              crr(j + 1, m) = ListBox1.List(i, j)
  '          Next
  '      End If
  '  Next
     
  '  If m > 0 Then ActiveCell.Resize(m, j) = Application.Transpose(crr)
End Sub

Private Sub TextBox1_Change()
    '模糊匹配
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


Private Sub UserForm_Initialize()
    arr = Sheets("基础信息表").Range("A1").CurrentRegion
    With ListBox1
    '设置列表框属性
        .List = arr
        .MultiSelect = fmMultiSelectExtended
        .ColumnCount = UBound(arr, 2)
        .ListStyle = fmListStyleOption
        LISTBOX_Post_Flag = 1
        LISTBOX_Mouse_Flag = 1
    End With
    TextBox2.Text = DateSerial(Year(Date), Month(Date), Day(Date))
End Sub

Private Sub UserForm_QueryClose(Cancel As Integer, CloseMode As Integer)
'    If CloseMode <> vbFormCode Then Cancel = True
    Unload Me
End Sub

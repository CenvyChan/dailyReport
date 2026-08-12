Attribute VB_Name = "Sheet1"
Attribute VB_Base = "0{00020820-0000-0000-C000-000000000046}"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = True
Attribute VB_TemplateDerived = False
Attribute VB_Customizable = True
' CodeName: Sheet1  /  工作表显示名: 数据表
' 在 A2:A20000 任一单元格单击，弹出录入窗体 UserForm1
Private Sub Worksheet_SelectionChange(ByVal Target As Range)
    If Intersect(Target, Range("A2:A20000")) Is Nothing Then Exit Sub
    Cancel = True
    UserForm1.Show Model
End Sub

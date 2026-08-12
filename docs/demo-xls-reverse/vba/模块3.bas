Attribute VB_Name = "模块3"
Sub OptionButton4_Click()
'
' OptionButton4_Click Macro
    Dim srcSheet As Worksheet
    Dim destSheet As Worksheet
    Dim srcRange As Range
    Dim destRange As Range
    
    ' 设置源表格和目标表格
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("新增订单查询表")
    
    ' 设置源数据区域
    Set srcRange = srcSheet.Range("A1:C200")
    
    ' 定义筛选条件
    srcRange.AutoFilter field:=3, Criteria1:="内销" ' 根据第一列的条件1进行筛选
    
    ' 复制筛选后的数据到目标表格
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("F5").PasteSpecial xlPasteValues
    
    ' 清除筛选
    srcSheet.AutoFilterMode = False
End Sub
Sub OptionButton6_Click()
    Dim srcSheet As Worksheet
    Dim destSheet As Worksheet
    Dim srcRange As Range
    Dim destRange As Range
    
    ' 设置源表格和目标表格
    Set srcSheet = Sheets("基础信息表")
    Set destSheet = Sheets("新增订单查询表")
    
    ' 设置源数据区域
    Set srcRange = srcSheet.Range("A1:C200")
    
    ' 定义筛选条件
    srcRange.AutoFilter field:=3, Criteria1:="外销" ' 根据第一列的条件1进行筛选
    
    ' 复制筛选后的数据到目标表格
    srcRange.SpecialCells(xlCellTypeVisible).Copy
    destSheet.Range("F5").PasteSpecial xlPasteValues
    
    ' 清除筛选
    srcSheet.AutoFilterMode = False
End Sub

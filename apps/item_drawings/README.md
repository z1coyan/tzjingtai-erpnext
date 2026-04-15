# item_drawings

物料图纸支持：

- 给 Item 新增 `custom_drawings` 子表（Item Drawing），支持多张图纸上传、版本、主图勾选、禁用保留历史
- 在所有 Item Link 字段左侧渲染 eye icon，点击弹出 carousel lightbox
- 图片支持 carousel / 缩放 / 旋转 / 下载 / 关闭；非图片（PDF/DWG 等）仅显示通用文件图标 + 下载 / 关闭

与 `tzjingtai` 的 link_formatters 正交，互不冲突。

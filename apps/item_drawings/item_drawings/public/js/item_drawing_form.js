// Item 表单本地脚本：
// 1) custom_drawings 子表新增一行时，如果这是唯一一行，自动勾上 is_main
// 2) 用户勾选某一行的 is_main 时，其它行自动取消 —— 保证"主图唯一"语义
//
// 纯前端 UI 约束，不做后端 validate，符合 "按需加抽象" 原则。

frappe.ui.form.on("Item", {
    custom_drawings_add: function (frm, cdt, cdn) {
        const rows = frm.doc.custom_drawings || [];
        if (rows.length === 1) {
            frappe.model.set_value(cdt, cdn, "is_main", 1);
        }
    },
});

frappe.ui.form.on("Item Drawing", {
    is_main: function (frm, cdt, cdn) {
        const changed = frappe.get_doc(cdt, cdn);
        if (!changed || !changed.is_main) return;
        (frm.doc.custom_drawings || []).forEach((row) => {
            if (row.name !== cdn && row.is_main) {
                frappe.model.set_value(row.doctype, row.name, "is_main", 0);
            }
        });
    },
});

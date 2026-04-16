// Item 表单本地脚本：
// 1) 第一张有效图纸自动成为主图
// 2) 用户勾选某一行主图时，其它行自动取消
// 3) 主图被禁用/删除后，自动把第一张有效图纸补成主图

frappe.ui.form.on("Item", {
    custom_drawings_add: function (frm, cdt, cdn) {
        sync_main_drawing(frm, cdn);
    },

    custom_drawings_remove: function (frm) {
        sync_main_drawing(frm);
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

    drawing_file: function (frm, cdt, cdn) {
        sync_main_drawing(frm, cdn);
    },

    disabled: function (frm, cdt, cdn) {
        sync_main_drawing(frm, cdn);
    },
});

function sync_main_drawing(frm, preferred_row_name) {
    const rows = frm.doc.custom_drawings || [];
    const activeRows = rows.filter((row) => row.drawing_file && !row.disabled);

    if (!activeRows.length) {
        rows.forEach((row) => {
            if (row.is_main) {
                frappe.model.set_value(row.doctype, row.name, "is_main", 0);
            }
        });
        return;
    }

    const preferredRow = preferred_row_name
        ? activeRows.find((row) => row.name === preferred_row_name)
        : null;
    const currentMain = activeRows.find((row) => row.is_main);
    const nextMain = preferredRow || currentMain || activeRows[0];

    rows.forEach((row) => {
        const shouldBeMain = row.name === nextMain.name ? 1 : 0;
        if ((row.is_main || 0) !== shouldBeMain) {
            frappe.model.set_value(row.doctype, row.name, "is_main", shouldBeMain);
        }
    });
}

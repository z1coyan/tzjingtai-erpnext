// 台州京泰 —— 全局 link 字段展示格式化
// 统一按 "编号 - 名称" 的形式展示常用主数据链接。
frappe.form.link_formatters["Customer"] = function (value, doc) {
    if (doc && doc.customer_name && doc.customer_name !== value) {
        return value + " - " + doc.customer_name;
    }
    return value;
};

frappe.form.link_formatters["Supplier"] = function (value, doc) {
    if (doc && doc.supplier_name && doc.supplier_name !== value) {
        return value + " - " + doc.supplier_name;
    }
    return value;
};

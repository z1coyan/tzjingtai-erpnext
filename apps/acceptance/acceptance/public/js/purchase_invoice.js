// 采购发票扩展：添加"创建票据转让"按钮

frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.outstanding_amount > 0) {
			frm.add_custom_button(__("Bill Transfer"), function () {
				frappe.new_doc("Bill Transfer", {
					company: frm.doc.company,
					supplier: frm.doc.supplier,
					linked_purchase_invoice: frm.doc.name,
				});
			}, __("Create"));
		}
	},
});

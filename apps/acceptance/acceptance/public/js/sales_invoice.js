// 销售发票扩展：添加"创建票据接收"按钮

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.outstanding_amount > 0) {
			frm.add_custom_button(__("票据接收"), function () {
				frappe.new_doc("Bill Receive", {
					company: frm.doc.company,
					customer: frm.doc.customer,
					linked_sales_invoice: frm.doc.name,
				});
			}, __("创建"));
		}
	},
});

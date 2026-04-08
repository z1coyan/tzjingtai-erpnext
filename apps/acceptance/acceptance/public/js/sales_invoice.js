// 销售发票扩展：添加"创建票据接收"按钮

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.outstanding_amount > 0) {
			frm.add_custom_button(__("Bill Receive"), function () {
				frappe.new_doc("Bill Receive", {
					company: frm.doc.company,
					party_type: "Customer",
					party: frm.doc.customer,
					linked_invoice_type: "Sales Invoice",
					linked_invoice: frm.doc.name,
				});
			}, __("Create"));
		}
	},
});

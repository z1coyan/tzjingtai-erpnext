// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill of Exchange", {
	refresh(frm) {
		// 已提交且可流通状态下显示操作按钮
		if (frm.doc.docstatus === 1 && frm.doc.bill_status === "已收票-可流通") {
			frm.add_custom_button(__("票据转让"), function () {
				frappe.model.open_mapped_doc({
					method: "",
					frm: frm,
				});
				frappe.new_doc("Bill Transfer", {
					bill_of_exchange: frm.doc.name,
					company: frm.doc.company,
				});
			}, __("创建"));

			frm.add_custom_button(__("提前贴现"), function () {
				frappe.new_doc("Bill Discount", {
					bill_of_exchange: frm.doc.name,
					company: frm.doc.company,
				});
			}, __("创建"));

			frm.add_custom_button(__("到期兑付"), function () {
				frappe.new_doc("Bill Payment", {
					bill_of_exchange: frm.doc.name,
					company: frm.doc.company,
				});
			}, __("创建"));
		}
	},

	sub_ticket_start(frm) {
		calculate_amount(frm);
	},

	sub_ticket_end(frm) {
		calculate_amount(frm);
	},
});

function calculate_amount(frm) {
	if (frm.doc.sub_ticket_start === 0 && frm.doc.sub_ticket_end === 0) {
		frm.set_value("is_splittable", 0);
	} else if (frm.doc.sub_ticket_start > 0 && frm.doc.sub_ticket_end >= frm.doc.sub_ticket_start) {
		let amount = (frm.doc.sub_ticket_end - frm.doc.sub_ticket_start + 1) * 0.01;
		frm.set_value("bill_amount", amount);
		frm.set_value("is_splittable", 1);
	}
}

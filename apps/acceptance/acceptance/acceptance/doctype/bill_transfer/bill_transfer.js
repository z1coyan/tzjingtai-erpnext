// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill Transfer", {
	transfer_amount(frm) {
		if (frm.doc.original_amount && frm.doc.transfer_amount) {
			if (frm.doc.transfer_amount < frm.doc.original_amount) {
				frm.set_value("is_partial_transfer", 1);
				frm.set_value("remaining_amount", frm.doc.original_amount - frm.doc.transfer_amount);
			} else {
				frm.set_value("is_partial_transfer", 0);
				frm.set_value("remaining_amount", 0);
			}
		}
	},
});

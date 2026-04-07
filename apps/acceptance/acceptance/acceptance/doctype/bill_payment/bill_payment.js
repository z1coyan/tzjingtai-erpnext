// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill Payment", {
	bill_of_exchange(frm) {
		if (frm.doc.bill_of_exchange) {
			// 自动填入兑付金额为票面金额
			frappe.db.get_value("Bill of Exchange", frm.doc.bill_of_exchange, "bill_amount", (r) => {
				if (r && r.bill_amount) {
					frm.set_value("payment_amount", r.bill_amount);
				}
			});
		}
	},
});

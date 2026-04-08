// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill Discount", {
	discount_date(frm) {
		calculate_discount(frm);
	},

	discount_rate(frm) {
		calculate_discount(frm);
	},

	discount_amount(frm) {
		calculate_discount(frm);
	},

	bill_of_exchange(frm) {
		if (frm.doc.bill_of_exchange) {
			// 默认贴现金额为票面金额
			frappe.db.get_value("Bill of Exchange", frm.doc.bill_of_exchange, ["bill_amount", "due_date"], (r) => {
				if (r) {
					if (!frm.doc.discount_amount) {
						frm.set_value("discount_amount", r.bill_amount);
					}
					calculate_discount(frm, r.due_date);
				}
			});
		}
	},
});

function calculate_discount(frm, due_date) {
	if (!frm.doc.discount_date || !frm.doc.discount_rate || !frm.doc.discount_amount) return;

	// 获取到期日期
	if (!due_date) {
		frappe.db.get_value("Bill of Exchange", frm.doc.bill_of_exchange, "due_date", (r) => {
			if (r && r.due_date) {
				do_calculate(frm, r.due_date);
			}
		});
	} else {
		do_calculate(frm, due_date);
	}
}

function do_calculate(frm, due_date) {
	let remaining_days = frappe.datetime.get_diff(due_date, frm.doc.discount_date);
	if (remaining_days <= 0) {
		frappe.msgprint(__("Discount date must be before due date"));
		return;
	}

	frm.set_value("remaining_days", remaining_days);

	let interest = frm.doc.discount_amount * (frm.doc.discount_rate / 100) * remaining_days / 360;
	frm.set_value("discount_interest", interest);
	frm.set_value("actual_amount", frm.doc.discount_amount - interest);
}

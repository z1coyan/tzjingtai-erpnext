// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bill Transfer", {
	party_type(frm) {
		if (frm.doc.party_type === "Supplier") {
			frm.set_value("linked_invoice_type", "Purchase Invoice");
		} else if (frm.doc.party_type === "Customer") {
			frm.set_value("linked_invoice_type", "Sales Invoice");
		}
		frm.set_value("party", "");
		frm.set_value("linked_invoice", "");
	},

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
		calculate_sub_ticket_split(frm);
	},

	transfer_sub_start(frm) {
		calculate_sub_ticket_split(frm);
	},
});

function calculate_sub_ticket_split(frm) {
	if (!frm.doc.is_partial_transfer || !frm.doc.transfer_amount || !frm.doc.transfer_sub_start) {
		return;
	}

	let split_count = Math.round(frm.doc.transfer_amount / 0.01);
	let transfer_end = frm.doc.transfer_sub_start + split_count - 1;

	frm.set_value("transfer_sub_end", transfer_end);
	frm.set_value("remaining_sub_start", transfer_end + 1);

	// remaining_sub_end 从台账的 sub_ticket_end 获取
	if (frm.doc.bill_of_exchange) {
		frappe.db.get_value("Bill of Exchange", frm.doc.bill_of_exchange, "sub_ticket_end", (r) => {
			if (r && r.sub_ticket_end) {
				frm.set_value("remaining_sub_end", r.sub_ticket_end);
			}
		});
	}
}

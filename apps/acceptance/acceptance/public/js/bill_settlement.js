frappe.ui.form.on("Bill Settlement", {
    onload(frm) {
        acceptance.bind_bill_link_filter(frm);
        if (frm.is_new() && !frm.doc.company) {
            const c = frappe.defaults.get_user_default("Company") || frappe.defaults.get_default("Company");
            if (c) frm.set_value("company", c);
        }
        if (frm.is_new()) {
            frappe.db.get_doc("Bill of Exchange Settings").then((settings) => {
                if (settings.default_bill_receivable_account && !frm.doc.bill_credit_account) {
                    frm.set_value("bill_credit_account", settings.default_bill_receivable_account);
                }
                if (settings.default_bank_account && !frm.doc.settlement_bank_account) {
                    frm.set_value("settlement_bank_account", settings.default_bank_account);
                }
            });
        }
    },

    refresh(frm) { acceptance.render_holdings(frm); },
    bill(frm) { acceptance.render_holdings(frm); },

    settlement_bank_account(frm) {
        if (!frm.doc.settlement_bank_account) return;
        frappe.db.get_value("Bank Account", frm.doc.settlement_bank_account, "account").then(({ message }) => {
            if (message && message.account) frm.set_value("bank_cash_account", message.account);
        });
    },

    segments_settled_add(frm) { recompute_total(frm); },
    segments_settled_remove(frm) { recompute_total(frm); },
});

frappe.ui.form.on("Bill Settlement Item", {
    amount(frm) { recompute_total(frm); },
    segment_from(frm, cdt, cdn) { auto_row_amount(frm, cdt, cdn); },
    segment_to(frm, cdt, cdn) { auto_row_amount(frm, cdt, cdn); },
});

function auto_row_amount(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const f = parseInt(row.segment_from, 10);
    const t = parseInt(row.segment_to, 10);
    if (!Number.isFinite(f) || !Number.isFinite(t) || t < f) return;
    const calc = Math.round(((t - f + 1) / 100) * 100) / 100;
    frappe.model.set_value(cdt, cdn, "amount", calc);
}

function recompute_total(frm) {
    let total = 0;
    (frm.doc.segments_settled || []).forEach((r) => { total += r.amount || 0; });
    frm.set_value("total_amount", total);
}

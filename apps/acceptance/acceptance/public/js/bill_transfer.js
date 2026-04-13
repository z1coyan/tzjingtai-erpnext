frappe.ui.form.on("Bill Transfer", {
    onload(frm) {
        acceptance.bind_bill_link_filter(frm);
        if (frm.is_new() && !frm.doc.company) {
            const c = frappe.defaults.get_user_default("Company") || frappe.defaults.get_default("Company");
            if (c) frm.set_value("company", c);
        }
        if (frm.is_new() && !frm.doc.credit_account) {
            frappe.db.get_single_value("Bill of Exchange Settings", "default_bill_receivable_account")
                .then((v) => { if (v) frm.set_value("credit_account", v); });
        }
    },

    refresh(frm) { acceptance.render_holdings(frm); },
    bill(frm) { acceptance.render_holdings(frm); },

    to_party_type(frm) {
        frm.set_value("to_party", null);
        frm.set_value("debit_account", null);
    },

    to_party(frm) {
        resolve_debit_account(frm);
    },

    segment_from(frm) { auto_amount(frm); },
    segment_to(frm) { auto_amount(frm); },
});

function auto_amount(frm) {
    const f = parseInt(frm.doc.segment_from, 10);
    const t = parseInt(frm.doc.segment_to, 10);
    if (!Number.isFinite(f) || !Number.isFinite(t) || t < f) return;
    const calc = Math.round(((t - f + 1) / 100) * 100) / 100;
    frm.set_value("amount", calc);
}

function resolve_debit_account(frm) {
    if (!frm.doc.to_party_type || !frm.doc.to_party || !frm.doc.company) return;
    frappe.call({
        method: "erpnext.accounts.party.get_party_account",
        args: {
            party_type: frm.doc.to_party_type,
            party: frm.doc.to_party,
            company: frm.doc.company,
        },
        callback: ({ message }) => {
            if (message) frm.set_value("debit_account", message);
        },
    });
}

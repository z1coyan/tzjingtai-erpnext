frappe.ui.form.on("Payroll Adjustment", {
    setup(frm) {
        const company_filter = (field) => {
            frm.set_query(field, () => ({
                filters: { company: frm.doc.company, is_group: 0 },
            }));
        };
        company_filter("wage_expense_account");
        company_filter("payroll_payable_account");
        frm.set_query("cost_center", () => ({
            filters: { company: frm.doc.company, is_group: 0 },
        }));
        frm.set_query("employee", "details", () => ({
            filters: { status: "Active" },
        }));
    },

    refresh(frm) {
        if (frm.doc.journal_entry) {
            frm.add_custom_button(__("Open Journal Entry"), () => {
                frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry);
            });
        }
    },

    company(frm) {
        if (frm.doc.company && !frm.doc.cost_center) {
            frappe.db.get_value("Company", frm.doc.company, "cost_center").then((r) => {
                if (r.message && r.message.cost_center) {
                    frm.set_value("cost_center", r.message.cost_center);
                }
            });
        }
    },

    period_year(frm) {
        if (!frm.doc.period_year) {
            frm.set_value("period_year", new Date().getFullYear());
        }
    },
});

frappe.ui.form.on("Payroll Adjustment Detail", {
    amount: refresh_totals,
    adjustment_type: refresh_totals,
    details_remove: refresh_totals,
});

function refresh_totals(frm) {
    let bonus = 0, supp = 0, total = 0;
    const emps = new Set();
    (frm.doc.details || []).forEach((r) => {
        const amt = parseFloat(r.amount) || 0;
        if (r.employee) emps.add(r.employee);
        if (r.adjustment_type === "Bonus") bonus += amt;
        else supp += amt;
        total += amt;
    });
    frm.set_value("total_bonus", bonus);
    frm.set_value("total_supplementary", supp);
    frm.set_value("total_amount", total);
    frm.set_value("total_employees", emps.size);
}

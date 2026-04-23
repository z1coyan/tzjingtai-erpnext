frappe.ui.form.on("Monthly Payroll Run", {
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
    },

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Generate"), () => {
                if (!frm.doc.company || !frm.doc.period_year || !frm.doc.period_month) {
                    frappe.msgprint({
                        title: __("Missing Fields"),
                        message: __("Please fill Company, Period Year and Period Month first."),
                        indicator: "orange",
                    });
                    return;
                }
                frappe.confirm(
                    __("Recalculate details for {0}-{1}?", [
                        frm.doc.period_year,
                        String(frm.doc.period_month).padStart(2, "0"),
                    ]),
                    () => {
                        frm.call("generate").then((r) => {
                            if (r.message) {
                                frappe.show_alert({
                                    message: __("Generated {0} rows, total {1}", [
                                        r.message.employees,
                                        format_currency(r.message.total_amount),
                                    ]),
                                    indicator: "green",
                                });
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }).addClass("btn-primary");
        }

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

frappe.ui.form.on("Monthly Payroll Detail", {
    adjustment: recalc_row,
});

function recalc_row(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    const amt =
        (parseFloat(row.basic_wage) || 0) +
        (parseFloat(row.adjustment) || 0);
    frappe.model.set_value(cdt, cdn, "amount", amt);

    let total = 0;
    (frm.doc.details || []).forEach((r) => {
        total += parseFloat(r.amount) || 0;
    });
    frm.set_value("total_amount", total);
}

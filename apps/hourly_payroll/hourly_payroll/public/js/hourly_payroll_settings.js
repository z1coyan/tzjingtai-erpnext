frappe.ui.form.on("Hourly Payroll Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Setup Shift & Assignments"), () => {
            const dlg = new frappe.ui.Dialog({
                title: __("Setup Shift & Assignments"),
                fields: [
                    {
                        fieldname: "company",
                        fieldtype: "Link",
                        label: __("Company"),
                        options: "Company",
                        description: __("Leave empty to bind every Active employee across all companies"),
                    },
                ],
                primary_action_label: __("Run"),
                primary_action(values) {
                    dlg.hide();
                    frm.call("setup_shift_and_assignments", {
                        company: values.company || null,
                    }).then((r) => {
                        if (r.message) {
                            const m = r.message;
                            frappe.msgprint({
                                title: __("Shift Setup Finished"),
                                message: __(
                                    "Shift Type: {0}<br>Created: {1} · Updated: {2}<br>Employees bound: {3} · Already bound: {4}",
                                    [m.shift_type, m.created, m.updated, m.employees_bound, m.employees_already_bound]
                                ),
                                indicator: "green",
                            });
                            frm.reload_doc();
                        }
                    });
                },
            });
            dlg.show();
        });

        if (frm.doc.linked_shift_type) {
            frm.add_custom_button(__("Open Shift Type"), () => {
                frappe.set_route("Form", "Shift Type", frm.doc.linked_shift_type);
            });
        }
    },
});

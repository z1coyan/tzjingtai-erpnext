frappe.ui.form.on("Attlog Import", {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.attach_file && frm.doc.status !== "Imported") {
            frm.add_custom_button(__("Parse & Create Checkins"), () => {
                frappe.confirm(
                    __("Parse the attlog file and create Employee Checkin records?"),
                    () => {
                        frm.call("parse_and_create").then((r) => {
                            if (r.message) {
                                const m = r.message;
                                frappe.msgprint({
                                    title: __("Import Finished"),
                                    message: __(
                                        "Total: {0} · Created: {1} · New Employees: {2} · Duplicates: {3} · Unmapped: {4}",
                                        [m.total, m.created, m.created_employees, m.duplicates, m.unmapped]
                                    ),
                                    indicator: "green",
                                });
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }).addClass("btn-primary");
        }
    },

    auto_create_unknown(frm) {
        if (!frm.doc.auto_create_unknown) {
            frm.set_value("default_company", null);
        } else if (!frm.doc.default_company) {
            frappe.db.get_single_value("Global Defaults", "default_company").then((c) => {
                if (c) frm.set_value("default_company", c);
            });
        }
    },
});

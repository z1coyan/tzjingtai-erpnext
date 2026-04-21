frappe.query_reports["Payroll Summary"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 1,
        },
        {
            fieldname: "period_year",
            label: __("Period Year"),
            fieldtype: "Int",
            default: new Date().getFullYear(),
            reqd: 1,
        },
        {
            fieldname: "period_month",
            label: __("Period Month"),
            fieldtype: "Select",
            options: [
                "",
                "1","2","3","4","5","6","7","8","9","10","11","12",
            ].join("\n"),
            default: "",
        },
        {
            fieldname: "department",
            label: __("Department"),
            fieldtype: "Link",
            options: "Department",
        },
        {
            fieldname: "employee",
            label: __("Employee"),
            fieldtype: "Link",
            options: "Employee",
        },
    ],
};

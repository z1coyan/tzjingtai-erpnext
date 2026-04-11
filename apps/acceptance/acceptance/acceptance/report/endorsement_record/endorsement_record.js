// Copyright (c) 2026, 台州京泰 and contributors
// For license information, please see license.txt

frappe.query_reports["Endorsement Record"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "bill_no",
			label: __("Bill No"),
			fieldtype: "Data",
		},
		{
			fieldname: "endorsement_type",
			label: __("Endorsement Type"),
			fieldtype: "Select",
			options: [
				{ value: "", label: "" },
				{ value: "Endorsement Received", label: __("Endorsement Received") },
				{ value: "Endorsement Transfer", label: __("Endorsement Transfer") },
			],
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "bill_status",
			label: __("Bill Status"),
			fieldtype: "Select",
			options: [
				{ value: "", label: "" },
				{ value: "Received - Circulating", label: __("Received - Circulating") },
				{ value: "Endorsed", label: __("Endorsed") },
				{ value: "Discounted", label: __("Discounted") },
				{ value: "Settled", label: __("Settled") },
				{ value: "Split", label: __("Split") },
			],
		},
	],
	formatter(value, row, column, data, default_formatter) {
		if (value && ["endorsement_type", "bill_status", "source_doctype"].includes(column.fieldname)) {
			return default_formatter(__(value), row, column, data);
		}
		return default_formatter(value, row, column, data);
	},
};

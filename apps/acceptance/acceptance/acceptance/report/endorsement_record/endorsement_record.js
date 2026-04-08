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
			options: "\nEndorsement Received\nEndorsement Transfer",
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
			options:
				"\nReceived - Circulating\nEndorsed\nDiscounted\nSettled\nSplit",
		},
	],
};

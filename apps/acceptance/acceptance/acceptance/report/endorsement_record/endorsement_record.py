# Copyright (c) 2026, 台州京泰 and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "bill_no",
			"label": _("Bill No"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "bill_of_exchange",
			"label": _("Bill of Exchange"),
			"fieldtype": "Link",
			"options": "Bill of Exchange",
			"width": 140,
		},
		{
			"fieldname": "sequence",
			"label": _("Sequence"),
			"fieldtype": "Int",
			"width": 70,
		},
		{
			"fieldname": "endorsement_type",
			"label": _("Endorsement Type"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "endorser_name",
			"label": _("Endorser Name"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "endorsee_name",
			"label": _("Endorsee Name"),
			"fieldtype": "Data",
			"width": 160,
		},
		{
			"fieldname": "endorsement_date",
			"label": _("Endorsement Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "endorsement_amount",
			"label": _("Endorsement Amount"),
			"fieldtype": "Currency",
			"width": 130,
		},
		{
			"fieldname": "sub_start",
			"label": _("Sub Start"),
			"fieldtype": "Int",
			"width": 90,
		},
		{
			"fieldname": "sub_end",
			"label": _("Sub End"),
			"fieldtype": "Int",
			"width": 90,
		},
		{
			"fieldname": "source_doctype",
			"label": _("Source DocType"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "source_docname",
			"label": _("Source Document"),
			"fieldtype": "Dynamic Link",
			"options": "source_doctype",
			"width": 140,
		},
		{
			"fieldname": "bill_status",
			"label": _("Bill Status"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "due_date",
			"label": _("Due Date"),
			"fieldtype": "Date",
			"width": 110,
		},
	]


def get_data(filters):
	conditions = get_conditions(filters)

	data = frappe.db.sql(
		"""
		SELECT
			boe.bill_no,
			boe.name AS bill_of_exchange,
			ec.sequence,
			ec.endorsement_type,
			ec.endorser_name,
			ec.endorsee_name,
			ec.endorsement_date,
			ec.endorsement_amount,
			ec.sub_start,
			ec.sub_end,
			ec.source_doctype,
			ec.source_docname,
			boe.bill_status,
			boe.due_date
		FROM `tabEndorsement Chain` ec
		INNER JOIN `tabBill of Exchange` boe ON ec.parent = boe.name
		WHERE boe.docstatus = 1
		{conditions}
		ORDER BY boe.bill_no, ec.sequence
		""".format(conditions=conditions),
		filters,
		as_dict=True,
	)

	return data


def get_conditions(filters):
	conditions = ""

	if not filters:
		return conditions

	if filters.get("bill_no"):
		conditions += " AND boe.bill_no = %(bill_no)s"

	if filters.get("company"):
		conditions += " AND boe.company = %(company)s"

	if filters.get("endorsement_type"):
		conditions += " AND ec.endorsement_type = %(endorsement_type)s"

	if filters.get("from_date"):
		conditions += " AND ec.endorsement_date >= %(from_date)s"

	if filters.get("to_date"):
		conditions += " AND ec.endorsement_date <= %(to_date)s"

	if filters.get("bill_status"):
		conditions += " AND boe.bill_status = %(bill_status)s"

	return conditions

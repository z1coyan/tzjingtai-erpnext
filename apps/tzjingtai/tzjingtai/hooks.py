app_name = "tzjingtai"
app_title = "Tzjingtai Customizations"
app_publisher = "台州京泰"
app_description = "台州京泰 ERPNext 自定义逻辑 (link formatters / 业务微调)"
app_email = "it@tzjingtai.com"
app_license = "MIT"

required_apps = ["erpnext"]

app_include_js = ["/assets/tzjingtai/js/link_formatters.js"]

doctype_js = {
    "Item": "public/js/item_form.js",
    "Delivery Note": "public/js/order_remark.js",
    "Purchase Receipt": "public/js/order_remark.js",
    "Stock Entry": "public/js/order_remark.js",
    "Subcontracting Receipt": "public/js/order_remark.js",
}

doc_events = {
    "Item": {
        "before_naming": "tzjingtai.item_code.before_naming_item",
        "validate": "tzjingtai.item_code.validate_item",
    },
}

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "Item-custom_specification",
                    "Item-custom_customer_item_code",
                    "Sales Order Item-custom_specification",
                    "Sales Order Item-custom_customer_item_code",
                    "Quotation Item-custom_specification",
                    "Quotation Item-custom_customer_item_code",
                    "Sales Invoice Item-custom_specification",
                    "Sales Invoice Item-custom_customer_item_code",
                    "Delivery Note Item-custom_specification",
                    "Delivery Note Item-custom_customer_item_code",
                    "Delivery Note Item-custom_remark",
                    "Purchase Order Item-custom_specification",
                    "Purchase Receipt Item-custom_specification",
                    "Purchase Receipt Item-custom_remark",
                    "Purchase Invoice Item-custom_specification",
                    "Stock Entry Detail-custom_specification",
                    "Stock Entry Detail-custom_customer_item_code",
                    "Stock Entry Detail-custom_remark",
                    "Subcontracting Receipt Item-custom_remark",
                    "Item Group-custom_item_code_prefix",
                    "Item Group-custom_item_code_mode",
                    "Employee-custom_insurance_section",
                    "Employee-custom_insurance_pension",
                    "Employee-custom_insurance_medical",
                    "Employee-custom_insurance_unemployment",
                    "Employee-custom_insurance_injury",
                    "Employee-custom_insurance_maternity",
                    "Employee-custom_insurance_column_break",
                    "Employee-custom_insurance_provider",
                    "Employee-custom_id_card_section",
                    "Employee-custom_id_card_no",
                    "Employee-custom_id_card_col_break",
                    "Employee-custom_id_card_front",
                    "Employee-custom_id_card_back",
                ],
            ]
        ],
    },
    {
        "dt": "Property Setter",
        "filters": [
            [
                "name",
                "in",
                [
                    "Employee-middle_name-hidden",
                    "Employee-last_name-hidden",
                    "Employee-employee_name-hidden",
                    "Employee-health_details-hidden",
                    "Employee-passport_details_section-hidden",
                    "Employee-passport_number-hidden",
                    "Employee-valid_upto-hidden",
                    "Employee-date_of_issue-hidden",
                    "Employee-place_of_issue-hidden",
                ],
            ]
        ],
    },
]

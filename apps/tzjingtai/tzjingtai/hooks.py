app_name = "tzjingtai"
app_title = "Tzjingtai Customizations"
app_publisher = "台州京泰"
app_description = "台州京泰 ERPNext 自定义逻辑 (link formatters / 业务微调)"
app_email = "it@tzjingtai.com"
app_license = "MIT"

required_apps = ["erpnext"]

app_include_js = ["/assets/tzjingtai/js/link_formatters.js"]

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
                    "Item-custom_drawings_section",
                    "Item-custom_drawings",
                    "Sales Order Item-custom_specification",
                    "Sales Order Item-custom_customer_item_code",
                    "Quotation Item-custom_specification",
                    "Quotation Item-custom_customer_item_code",
                    "Sales Invoice Item-custom_specification",
                    "Sales Invoice Item-custom_customer_item_code",
                    "Delivery Note Item-custom_specification",
                    "Delivery Note Item-custom_customer_item_code",
                    "Purchase Order Item-custom_specification",
                    "Purchase Receipt Item-custom_specification",
                    "Purchase Invoice Item-custom_specification",
                    "Stock Entry Detail-custom_specification",
                    "Stock Entry Detail-custom_customer_item_code",
                ],
            ]
        ],
    },
]

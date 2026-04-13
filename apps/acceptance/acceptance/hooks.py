app_name = "acceptance"
app_title = "Bill of Exchange Management"
app_publisher = "台州京泰"
app_description = "承兑汇票管理 —— 接收 / 背书转让 / 贴现 / 兑付 + 子票区间 + 阿里云 OCR"
app_email = "it@tzjingtai.com"
app_license = "MIT"

required_apps = ["erpnext"]

app_include_js = ["/assets/acceptance/js/acceptance_holdings.js"]

doctype_js = {
    "Bill Receipt": "public/js/bill_receipt.js",
    "Bill Transfer": "public/js/bill_transfer.js",
    "Bill Discount": "public/js/bill_discount.js",
    "Bill Settlement": "public/js/bill_settlement.js",
}

fixtures = []

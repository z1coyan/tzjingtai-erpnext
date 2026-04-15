app_name = "item_drawings"
app_title = "Item Drawings"
app_publisher = "台州京泰"
app_description = "物料图纸：Item 多图纸子表 + 全局 eye-icon lightbox 预览"
app_email = "it@tzjingtai.com"
app_license = "MIT"

required_apps = ["erpnext"]

# 全局生效：desk 所有页面注入 lightbox + eye-icon link formatter
app_include_js = ["/assets/item_drawings/js/item_drawings_lightbox.js"]

# Item 表单本地脚本：子表 is_main 单选 + 首行默认主图
doctype_js = {"Item": "public/js/item_drawing_form.js"}

fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            [
                "name",
                "in",
                [
                    "Item-custom_drawings_section",
                    "Item-custom_drawings",
                ],
            ]
        ],
    },
]

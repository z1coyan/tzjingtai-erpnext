// 台州京泰 —— 物料图纸 Lightbox
//
// 作用：在 ERPNext 里所有 Item Link 字段的跳转链接前加一个 eye icon，
// 点击后弹出一个 carousel lightbox 展示该 Item 的所有 active 图纸
// （custom_drawings 子表里 disabled = 0 的条目）。
//
// - 图片：居中预览，右上角按钮支持旋转、放大、缩小、下载、关闭，
//   左右两侧箭头切上一张 / 下一张，键盘 ←→ Esc 同理。
// - 非图片（PDF/DWG 等）：中间显示通用文件图标 + 文件名，
//   右上角只剩下载和关闭（旋转/缩放无意义时自动隐藏）。

(function () {
    const EYE_CLASS = "tzjt-drawings-eye";
    const OVERLAY_CLASS = "tzjt-drawings-lightbox";
    const IMG_EXT_RE = /\.(png|jpe?g|gif|webp|svg|bmp|tiff?)$/i;

    // ---------- Link formatter：给 Item 链接前加 eye icon ----------
    // 注：link_formatters 的返回值会被包进 <a>，所以 eye 其实是 <a> 的一部分，
    // 靠事件委托 + stopPropagation 阻止父级 <a> 的跳转。
    frappe.form.link_formatters["Item"] = function (value, doc) {
        if (!value) return value;
        const safe_value = frappe.utils.escape_html(value);
        const eye_svg =
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" ' +
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
            'stroke-linejoin="round" style="vertical-align:-2px;">' +
            '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>' +
            '<circle cx="12" cy="12" r="3"/></svg>';
        const eye =
            '<span class="' +
            EYE_CLASS +
            '" data-item="' +
            safe_value +
            '" title="' +
            __("View drawings") +
            '">' +
            eye_svg +
            "</span> ";
        return eye + safe_value;
    };

    // ---------- Click delegation ----------
    $(document).on("click", "." + EYE_CLASS, function (e) {
        e.preventDefault();
        e.stopPropagation();
        const item_code = $(this).attr("data-item");
        if (!item_code) return;
        open_lightbox(item_code);
    });

    function open_lightbox(item_code) {
        frappe.db
            .get_doc("Item", item_code)
            .then((item) => {
                const drawings = (item.custom_drawings || []).filter(
                    (d) => d.drawing_file && !d.disabled
                );
                if (!drawings.length) {
                    frappe.show_alert({
                        message: __("No active drawings for {0}", [item_code]),
                        indicator: "orange",
                    });
                    return;
                }
                new DrawingsLightbox(item, drawings).open();
            })
            .catch(() => {
                frappe.show_alert({
                    message: __("Failed to load {0}", [item_code]),
                    indicator: "red",
                });
            });
    }

    // ---------- Lightbox 组件 ----------
    class DrawingsLightbox {
        constructor(item, drawings) {
            this.item = item;
            this.drawings = drawings;
            this.index = 0;
            this.rotation = 0;
            this.zoom = 1;
            this.$overlay = null;
            this._kb_handler = null;
        }

        open() {
            inject_styles_once();
            this.$overlay = $(this._template()).appendTo("body");
            this._bind_events();
            this._render();
            this.$overlay.trigger("focus");
        }

        _template() {
            const t = (key) => frappe.utils.escape_html(__(key));
            return (
                '<div class="' +
                OVERLAY_CLASS +
                '" tabindex="-1">' +
                '  <div class="tzjt-lb-topbar">' +
                '    <div class="tzjt-lb-caption"></div>' +
                '    <div class="tzjt-lb-tools">' +
                '      <button type="button" class="tzjt-lb-btn tzjt-lb-rotate" title="' +
                t("Rotate") +
                '">' +
                icon_svg("rotate") +
                "</button>" +
                '      <button type="button" class="tzjt-lb-btn tzjt-lb-zoom-out" title="' +
                t("Zoom out") +
                '">' +
                icon_svg("zoom-out") +
                "</button>" +
                '      <button type="button" class="tzjt-lb-btn tzjt-lb-zoom-in" title="' +
                t("Zoom in") +
                '">' +
                icon_svg("zoom-in") +
                "</button>" +
                '      <button type="button" class="tzjt-lb-btn tzjt-lb-download" title="' +
                t("Download") +
                '">' +
                icon_svg("download") +
                "</button>" +
                '      <button type="button" class="tzjt-lb-btn tzjt-lb-close" title="' +
                t("Close") +
                '">' +
                icon_svg("close") +
                "</button>" +
                "    </div>" +
                "  </div>" +
                '  <button type="button" class="tzjt-lb-nav tzjt-lb-prev" title="' +
                t("Previous") +
                '">' +
                icon_svg("chevron-left") +
                "</button>" +
                '  <button type="button" class="tzjt-lb-nav tzjt-lb-next" title="' +
                t("Next") +
                '">' +
                icon_svg("chevron-right") +
                "</button>" +
                '  <div class="tzjt-lb-stage"></div>' +
                '  <div class="tzjt-lb-footer"></div>' +
                "</div>"
            );
        }

        _bind_events() {
            const self = this;
            this.$overlay.find(".tzjt-lb-close").on("click", () => self.close());
            this.$overlay
                .find(".tzjt-lb-prev")
                .on("click", () => self.goto(self.index - 1));
            this.$overlay
                .find(".tzjt-lb-next")
                .on("click", () => self.goto(self.index + 1));
            this.$overlay.find(".tzjt-lb-rotate").on("click", () => self.rotate());
            this.$overlay
                .find(".tzjt-lb-zoom-in")
                .on("click", () => self.zoom_by(1.25));
            this.$overlay
                .find(".tzjt-lb-zoom-out")
                .on("click", () => self.zoom_by(0.8));
            this.$overlay.find(".tzjt-lb-download").on("click", () => self.download());
            // 点击遮罩空白关闭
            this.$overlay.on("click", (e) => {
                if (e.target === self.$overlay[0]) self.close();
            });
            this._kb_handler = (e) => {
                if (e.key === "Escape") self.close();
                else if (e.key === "ArrowLeft") self.goto(self.index - 1);
                else if (e.key === "ArrowRight") self.goto(self.index + 1);
            };
            $(document).on("keydown.tzjt-lb", this._kb_handler);
        }

        current() {
            return this.drawings[this.index];
        }

        goto(new_index) {
            const n = this.drawings.length;
            if (n === 0) return;
            new_index = ((new_index % n) + n) % n;
            if (new_index === this.index) return;
            this.index = new_index;
            this.rotation = 0;
            this.zoom = 1;
            this._render();
        }

        rotate() {
            this.rotation = (this.rotation + 90) % 360;
            this._apply_transform();
        }

        zoom_by(factor) {
            this.zoom = Math.max(0.1, Math.min(10, this.zoom * factor));
            this._apply_transform();
        }

        _apply_transform() {
            const $img = this.$overlay.find(".tzjt-lb-stage img");
            if ($img.length) {
                $img.css(
                    "transform",
                    "rotate(" + this.rotation + "deg) scale(" + this.zoom + ")"
                );
            }
        }

        download() {
            const d = this.current();
            if (!d || !d.drawing_file) return;
            const a = document.createElement("a");
            a.href = d.drawing_file;
            a.download = d.drawing_name || "";
            a.target = "_blank";
            a.rel = "noopener";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        _render() {
            const d = this.current();
            const is_image = IMG_EXT_RE.test(d.drawing_file || "");
            const $stage = this.$overlay.find(".tzjt-lb-stage").empty();
            if (is_image) {
                $stage.append(
                    '<img src="' +
                        frappe.utils.escape_html(d.drawing_file) +
                        '" alt="' +
                        frappe.utils.escape_html(d.drawing_name || "") +
                        '">'
                );
                this.$overlay
                    .find(".tzjt-lb-rotate, .tzjt-lb-zoom-in, .tzjt-lb-zoom-out")
                    .css("display", "");
                this._apply_transform();
            } else {
                const filename = (d.drawing_file || "").split("/").pop();
                $stage.append(
                    '<div class="tzjt-lb-fileview">' +
                        '<svg width="120" height="120" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
                        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
                        '<polyline points="14 2 14 8 20 8"/>' +
                        "</svg>" +
                        '<div class="tzjt-lb-filename">' +
                        frappe.utils.escape_html(filename) +
                        "</div>" +
                        "</div>"
                );
                // 非图片时隐藏旋转/缩放按钮（无意义）
                this.$overlay
                    .find(".tzjt-lb-rotate, .tzjt-lb-zoom-in, .tzjt-lb-zoom-out")
                    .css("display", "none");
            }
            // caption
            const parts = [
                "<strong>" + frappe.utils.escape_html(this.item.item_code) + "</strong>",
            ];
            if (d.drawing_name) parts.push(frappe.utils.escape_html(d.drawing_name));
            if (d.version) parts.push("v" + frappe.utils.escape_html(d.version));
            if (d.remark)
                parts.push(
                    '<span class="tzjt-lb-muted">' +
                        frappe.utils.escape_html(d.remark) +
                        "</span>"
                );
            this.$overlay.find(".tzjt-lb-caption").html(parts.join(" · "));
            this.$overlay
                .find(".tzjt-lb-footer")
                .text(this.index + 1 + " / " + this.drawings.length);
            // 单张时隐藏左右箭头
            const hide_nav = this.drawings.length <= 1;
            this.$overlay
                .find(".tzjt-lb-prev, .tzjt-lb-next")
                .css("display", hide_nav ? "none" : "");
        }

        close() {
            if (this._kb_handler) $(document).off("keydown.tzjt-lb");
            if (this.$overlay) this.$overlay.remove();
        }
    }

    // ---------- SVG icons ----------
    function icon_svg(name) {
        const attrs =
            'width="18" height="18" viewBox="0 0 24 24" fill="none" ' +
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
        switch (name) {
            case "rotate":
                return (
                    "<svg " +
                    attrs +
                    '><path d="M23 4v6h-6"/><path d="M20.49 15A9 9 0 1 1 18 5.61L23 10"/></svg>'
                );
            case "zoom-in":
                return (
                    "<svg " +
                    attrs +
                    '><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>'
                );
            case "zoom-out":
                return (
                    "<svg " +
                    attrs +
                    '><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/></svg>'
                );
            case "download":
                return (
                    "<svg " +
                    attrs +
                    '><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>'
                );
            case "close":
                return (
                    "<svg " +
                    attrs +
                    '><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
                );
            case "chevron-left":
                return (
                    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>'
                );
            case "chevron-right":
                return (
                    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>'
                );
        }
        return "";
    }

    // ---------- Styles ----------
    let _styles_injected = false;
    function inject_styles_once() {
        if (_styles_injected) return;
        _styles_injected = true;
        const css =
            "." +
            EYE_CLASS +
            " { display:inline-flex; align-items:center; cursor:pointer; color:var(--text-muted, #6c7680); margin-right:4px; }" +
            "." +
            EYE_CLASS +
            ":hover { color: var(--primary-color, #5e64ff); }" +
            "." +
            OVERLAY_CLASS +
            " { position:fixed; inset:0; background:rgba(0,0,0,0.88); z-index:9999; display:flex; align-items:center; justify-content:center; outline:none; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-topbar { position:absolute; top:0; left:0; right:0; padding:12px 20px; display:flex; justify-content:space-between; align-items:center; color:#fff; background:linear-gradient(rgba(0,0,0,0.65), transparent); pointer-events:none; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-caption { font-size:14px; pointer-events:auto; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-muted { color:#bbb; font-weight:400; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-tools { display:flex; gap:8px; pointer-events:auto; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-btn { background:rgba(255,255,255,0.12); border:none; color:#fff; width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer; transition:background 0.15s; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-btn:hover { background:rgba(255,255,255,0.28); }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-nav { position:absolute; top:50%; transform:translateY(-50%); background:rgba(255,255,255,0.12); border:none; color:#fff; width:48px; height:48px; border-radius:50%; display:flex; align-items:center; justify-content:center; cursor:pointer; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-nav:hover { background:rgba(255,255,255,0.28); }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-prev { left:20px; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-next { right:20px; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-stage { max-width:90vw; max-height:82vh; display:flex; align-items:center; justify-content:center; overflow:hidden; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-stage img { max-width:90vw; max-height:82vh; object-fit:contain; transition:transform 0.2s ease; user-select:none; -webkit-user-drag:none; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-fileview { color:#fff; text-align:center; display:flex; flex-direction:column; align-items:center; gap:16px; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-filename { font-size:14px; color:#ccc; word-break:break-all; max-width:480px; }" +
            "." +
            OVERLAY_CLASS +
            " .tzjt-lb-footer { position:absolute; bottom:16px; left:0; right:0; text-align:center; color:#ccc; font-size:12px; }";
        const $s = $("<style>").prop("type", "text/css").html(css);
        $("head").append($s);
    }
})();

/**
 * Mneme 前端配置
 *
 * 两种模式：
 * - dev: 直连 Python Agent（无需鉴权，开发调试用）
 * - prod: 通过 Java Gateway（JWT 鉴权 + 多租户隔离）
 *
 * 切换方式：修改 mode 字段或设置 localStorage.mneme_mode
 */
const MnemeConfig = (() => {
    // 从 localStorage 读取模式偏好，默认 dev
    const savedMode = localStorage.getItem("mneme_mode");
    const mode = savedMode || "dev";

    const endpoints = {
        dev: {
            baseUrl: "http://localhost:8000/api/v1",
            authRequired: false,
            label: "直连 Python Agent"
        },
        prod: {
            baseUrl: "http://localhost:8080/api/v1",
            authRequired: true,
            label: "通过 Java Gateway"
        }
    };

    const current = endpoints[mode] || endpoints.dev;

    return {
        mode,
        baseUrl: current.baseUrl,
        authRequired: current.authRequired,
        label: current.label,

        /** 切换模式 */
        setMode(newMode) {
            localStorage.setItem("mneme_mode", newMode);
            location.reload();
        },

        /** 获取带认证头的 fetch options */
        getFetchOptions(extraOptions = {}) {
            const options = {
                headers: { "Content-Type": "application/json", ...(extraOptions.headers || {}) },
                ...extraOptions
            };
            if (this.authRequired) {
                const token = localStorage.getItem("mneme_token") || "";
                options.headers["Authorization"] = `Bearer ${token}`;
            }
            return options;
        }
    };
})();

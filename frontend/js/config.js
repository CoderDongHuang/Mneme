/**
 * Mneme 前端配置
 *
 * dev:  直连 Python Agent (localhost:8000)，无需鉴权
 * prod: 通过 Java Gateway (localhost:8080)，JWT 鉴权
 *
 * 切换方式：浏览器控制台输入 localStorage.setItem("mneme_mode", "prod") 后刷新
 */
const MnemeConfig = (() => {
    const mode = localStorage.getItem("mneme_mode") || "dev";

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

        setMode(newMode) {
            localStorage.setItem("mneme_mode", newMode);
            location.reload();
        },

        getFetchOptions(extraOptions = {}) {
            const options = {
                headers: { "Content-Type": "application/json", ...(extraOptions.headers || {}) },
                ...extraOptions
            };
            if (this.authRequired) {
                const token = localStorage.getItem("mneme_token") || "";
                options.headers["Authorization"] = "Bearer " + token;
            }
            return options;
        }
    };
})();

# 静态资源

## ⚠️ htmx.min.js 需要你手动放进来

模板里引用的是 `/static/htmx.min.js`（**本地文件，不是 CDN**）。
仓库里没有这个文件——本项目的开发沙箱访问不了外网，没法替你下载。

部署前放一份进来：

```bash
curl -o src/scheduling/interfaces/web/static/htmx.min.js \
  https://cdnjs.cloudflare.com/ajax/libs/htmx/1.9.12/htmx.min.js
```

或者从 https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js 下载后拷进来。

## 为什么不直接用 CDN

**这个服务部署在公司内网，很可能连不上外网。** 从 CDN 加载会让页面
静默降级——HTML 照常渲染，但所有 `hx-*` 属性失效：任务进度不再自动
刷新，用户看到的是一个永远停在「求解中」的页面，而且**没有任何报错**。

这类沉默失效是本项目反复强调要避免的一类问题，所以宁可多一步手动下载。

页面在 htmx 缺失时会在顶部显示一条提示，不会让人对着假进度干等。

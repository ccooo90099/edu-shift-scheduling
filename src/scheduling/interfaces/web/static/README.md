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

## 用 Docker 构建的话不用管

`Dockerfile` 里有一步会在构建时下载它（版本写死 1.9.12）。
Render、HF、本地 `docker build` 都能联网，正常不会缺。
只有直接 `uvicorn` 起、且没手动放过文件时才会缺。

## 为什么不直接从 CDN 引

**内网部署很可能连不上外网。** 从 CDN 引会让页面静默降级 ——
HTML 照常渲染，但所有 `hx-*` 失效，而且**没有任何报错**。

## 缺了会怎样（不严重）

进度刷新**不依赖**这个文件：htmx 不在时，任务页会自动插一个整页
`meta refresh` 顶上，进度照样会动，只是整页刷新而不是局部更新。
顶部会有一条提示说明已降级。

这是有意设计的 —— 「进度不会动」这种事不该取决于某个静态文件在不在。

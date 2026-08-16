# 个人能力汇报演示

本分支仅保存个人能力汇报相关页面与资源。

## 版本说明

- `outputs/ability-demo-v5.html`：静态版本，用于内容和版式审阅。
- `outputs/ability-demo-v5.pptx`：PowerPoint 静态版本，用于离线汇报与放映。
- `outputs/ability-demo-v5-editable.pptx`：PowerPoint 原生可编辑版本，文本、形状、流程与表格均可调整。
- `outputs/ability-demo-interactive-v2.html`：单页交互版本，可直接打开演示。
- `outputs/ability-demo-web-v2/index.html`：可扩展项目版本，样式、脚本、配置和图片相互独立。

## 演示控制

- 点击页面空白区域：进入下一页。
- 点击内容块：唤醒或取消当前讲述主题。
- `1`、`2`、`3`：直接聚焦当前页对应主题。
- `0` 或 `Esc`：恢复当前页总览。
- `→`、`Space` 或 `PageDown`：依次唤醒主题，讲完后进入下一页。
- `←` 或 `PageUp`：按相反顺序返回。
- `F`：切换全屏。

## 图片替换

可扩展版本的图片位于：

```text
outputs/ability-demo-web-v2/assets/images/
```

替换同名的 `graph-before.svg`、`graph-after.svg` 即可更新图结构对比图片，也可以在 `outputs/ability-demo-web-v2/deck-config.js` 中修改资源路径。

静态版和单页交互版使用分支根目录的 `graph-before.svg` 与 `graph-after.svg`。

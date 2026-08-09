# 能力汇报交互网页

## 目录说明

- `index.html`：六页汇报内容；每个 `<section class="slide">` 是一页。
- `styles.css`：页面排版、配色和切换动画。
- `app.js`：翻页、键盘、触摸、全屏和自适应逻辑。
- `deck-config.js`：统一维护图片路径。
- `assets/images/`：图片资源目录。

## 替换图片

直接覆盖 `assets/images/` 中的同名文件即可保留现有布局。

使用不同文件名时，只需修改 `deck-config.js`：

```js
window.DECK_CONFIG = {
  images: {
    profilePhoto: "assets/images/profile.jpg",
    graphBefore: "assets/images/graph-before.svg",
    graphAfter: "assets/images/graph-after.svg"
  }
};
```

个人照片支持 JPG、PNG 或 WebP，会自动裁切到预留区域。

## 增加页面

在 `index.html` 的 `<main>` 中复制并修改一个 `.slide` 区块。页码、导航圆点和进度条会根据页面数量自动更新。

## 逐项唤醒

- 第 3 至第 6 页的核心内容默认弱化显示，鼠标点击内容块可进入或退出聚焦状态。
- 键盘 `1`、`2`、`3` 可直接聚焦当前页对应主题。
- 键盘 `0` 或 `Esc` 恢复当前页总览。
- 连续按右方向键、空格或 `PageDown`，会按叙事顺序逐项唤醒，讲完后再进入下一页。
- 左方向键或 `PageUp` 按相反顺序退回，直至恢复全部灰化。

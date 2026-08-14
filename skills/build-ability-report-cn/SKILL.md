---
name: build-ability-report-cn
description: Build and iteratively refine evidence-based Chinese personal capability, promotion-readiness, and engineer growth presentations as concise 6–7 page HTML or PPT narratives. Use when Codex needs to structure 技术能力汇报、个人能力展示、晋升述职、工程师成长汇报、案例型领导汇报, revise an existing interactive HTML slide deck, integrate AI practices naturally into engineering cases, or keep static, interactive, and modular web versions consistent.
---

# 中文个人能力汇报

将原始工程案例转化为领导可快速理解、以事实证明个人成长的短篇汇报。优先展示已经发生的能力变化，不把未来职位目标、空泛自评或工具清单当作证明。

## 核心原则

- 从案例证据出发，再提炼能力与主题；不要先定口号再硬套内容。
- 聚焦“我如何判断、如何行动、如何产生结果”，但不要使用“个人能力展示”“证明重点”等制作标签。
- 将“完成、优化、协作”等词作为内部分析维度，不直接作为章节标题。
- 允许能力阶段在时间上重叠；不要用虚假的严格时间线表达并行成长。
- 保留完整背景和目标，压缩重复解释、通用动作与无证据形容词。
- 将 AI 融入需求拆解、反向审查、验证、定位或沉淀过程；除非形成独特资产，不单列“AI 使用”模块。
- 不发明指标。严格区分项目实测、推导值、行业 Benchmark 和待回填数据。
- 每页只承担一个叙事任务，并让结论比案例复述高一层。

## 工作流

1. **读取现状**：检查用户目标、受众、页数、已有文稿、现有页面和不可变约束。编辑已有文件前先完整读取相关页面与共享样式。
2. **建立能力主线**：从案例中寻找“交付更稳 → 思考更深 → 影响更广”或同等强度的递进关系。使用 [narrative-framework.md](references/narrative-framework.md) 校准主线与主题。
3. **补齐案例证据**：按 [case-input-template.md](references/case-input-template.md) 收集缺失信息。能从现有材料推断的内容直接整理；只有关键事实缺失且无法安全假设时才询问用户。
4. **重写页面文案**：按“观点 → 背景与目标 → 挑战 → 我的做法 → 直观效果 → 升华结论”组织案例。使用 [copy-and-evidence.md](references/copy-and-evidence.md) 选择证据形式并检查措辞。
5. **选择页面结构**：默认使用 6 页；内容确有必要时扩展至 7 页。使用 [page-and-interaction-patterns.md](references/page-and-interaction-patterns.md) 选择版式、交互和统一规则。
6. **抽取封面主题**：完成主体页后，从共同思想提炼 8–12 字抽象主题。封面只保留主题、汇报人和时间，不放目录、能力主线或解释性副标题。
7. **实现与同步**：已有设计优先沿用现有 CSS、组件和资源路径。同步维护静态版、单文件交互版和模块化 Web 版；不要覆盖用户要求保留的旧版本。
8. **验证与交付**：检查内容、视觉、交互、资源和版本一致性。HTML 至少运行 `scripts/validate_html_deck.mjs`；能够渲染时还要逐页截图检查遮挡和对齐。

## 默认页序

1. 封面：抽象主题、汇报人、时间。
2. 个人简介：以入职为起点，用能力轨迹而非履历复述串联主体章节；并行阶段使用重叠泳道或能力带。
3. 第一案例页：高质量交付、设计前置或复杂需求判断。
4. 第二案例页：根因优化、技术攻关、方法沉淀或复用扩散。
5. 第三案例页：复杂协作、风险收敛、依赖解耦和结果闭环。
6. 总结与展望：总结已形成的能力，并给出具体且不重复前文的下一步精进方向。

不要机械套用“初试羽翼、独当一面、团队协同”。仅在它们与用户成长语境匹配时使用；否则重新命名，但保持层次递进。

## 产物规则

- **HTML**：默认 16:9、固定设计画布并自适应缩放。新建项目时可复制 `assets/interactive-deck-starter/`，替换全部占位符后再交付。
- **PPTX**：同时遵循 `presentations` Skill 的创建、渲染和逐页验收要求。
- **互动版**：内容块默认弱化，点击或数字键直接唤醒；右方向键、空格或 PageDown 按叙事顺序推进；当前页讲完后再翻页。
- **版本同步**：公共文案、图片和样式修改必须同步到所有当前版本。修改前确认哪些文件是备份，哪些是交付版本。
- **Git**：仅在用户已要求自动发布或当前工作区已有明确约定时，完成校验后提交并推送；提交范围只能包含本次汇报改动。

## 验收清单

- 页面数量、标题层级和章节命名一致。
- 背景与目标足够完整，动作和效果是视觉重点。
- 同一位置的字体、边距、底部结论和交互状态统一。
- 所有箭头、标签、图片和文字不遮挡、不溢出、不被裁切。
- 每个数字有依据；行业数据未冒充项目成果。
- AI 描述已融入真实动作，没有独立悬浮的工具宣传句。
- 封面主题能覆盖全部主体页，而非只对应某一个案例。
- 总结页没有重复主体页原句，展望具体且与已有能力相连。
- 静态、交互、模块化版本内容一致，资源路径有效。
- 若存在自动推送约定，本地提交与远端分支一致且工作区干净。

## 资源

- 组织主线、能力递进和主题：读取 [narrative-framework.md](references/narrative-framework.md)。
- 写案例、处理指标和融合 AI：读取 [copy-and-evidence.md](references/copy-and-evidence.md)。
- 设计页面、交互和视觉验收：读取 [page-and-interaction-patterns.md](references/page-and-interaction-patterns.md)。
- 向用户收集案例：使用 [case-input-template.md](references/case-input-template.md)。
- 新建互动 HTML：复制 `assets/interactive-deck-starter/`。
- 校验 HTML：运行 `node scripts/validate_html_deck.mjs <index-or-single-html>`。

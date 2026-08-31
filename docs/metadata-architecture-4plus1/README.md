# 统一元数据平台 4+1 架构视图

当前阶段仅维护可编辑的 PlantUML 源文件及对应 SVG 预览。架构最终确认后再制作演示文稿。

## 视图清单

| 4+1 视图 | PlantUML 源文件 | SVG 预览 |
|---|---|---|
| +1 场景视图 | [01-scenario-view.puml](diagrams/01-scenario-view.puml) | [01-scenario-view.svg](rendered/01-scenario-view.svg) |
| 逻辑视图 | [02-logical-view.puml](diagrams/02-logical-view.puml) | [02-logical-view.svg](rendered/02-logical-view.svg) |
| 开发视图 | [03-development-view.puml](diagrams/03-development-view.puml) | [03-development-view.svg](rendered/03-development-view.svg) |
| 进程视图 | [04-process-view.puml](diagrams/04-process-view.puml) | [04-process-view.svg](rendered/04-process-view.svg) |
| 物理视图 | [05-physical-view.puml](diagrams/05-physical-view.puml) | [05-physical-view.svg](rendered/05-physical-view.svg) |

## 当前架构约束

- 不同生态入口继承统一抽象类，由抽象类定义统一入口契约并收敛公共逻辑。
- Gravitino、Iceberg 和内部入口分别实现生态差异。
- 底层数据源通过 `DataSourceFactory` 按类型和配置选择、创建。
- StarRocks、Iceberg、OpenSearch 实现统一数据源抽象并注册到工厂。
- 混合索引按查询粒度和更新粒度拆分为 `catalog`、`schema`、`dataset`、`table`、`tags`、`tags-relation`。
- 动态模板支持产品自定义查询 Key，同时通过准入、配额和 Mapping Key 上限防止索引爆炸。

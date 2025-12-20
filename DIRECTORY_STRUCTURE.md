# 目录结构说明

## 新的文件组织方式

文章 HTML 文件现在按照以下结构组织：

```
data/html/
├── en/          # 英文文章目录
│   ├── 2025-12-17_culture_author_title.html
│   └── ...
└── zh/          # 中文翻译目录
    ├── 2025-12-17_culture_author_title.html  (与英文同名)
    └── ...
```

### 关键特性

1. **文件名相同**：中英文版本使用相同的文件名
2. **目录分离**：英文文件在 `/en` 目录，中文文件在 `/zh` 目录
3. **自动匹配**：系统自动根据文件名匹配中英文版本

## 文件命名格式

文件名格式（新格式，包含source标识符）：
```
YYYY-MM-DD_source_category_author_title.html
```

示例：
- `2025-12-19_newyorker_culture_Joshua_Rothman_Is_A.I._Actually_a_Bubble.html`
- `2025-06-30_nytimes_interactive_steven-strogatz_Bowling_for_Nobels.html`

**Source标识符**：
- `newyorker` - New Yorker 文章
- `nytimes` - New York Times 文章

**注意**：
- 中文文件使用相同的文件名，存储在 `/zh` 目录中
- 系统同时支持旧格式（向后兼容），但新保存的文件将使用新格式

## 数据库存储

数据库中的路径格式：
- `html_file_en`: `en/filename.html`
- `html_file_zh`: `zh/filename.html`

## 使用方法

### 手动上传文件

1. **英文文件**：上传到 `/home/tensor/projects/articles/data/html/en/`
2. **中文文件**：上传到 `/home/tensor/projects/articles/data/html/zh/`
3. **文件名**：确保中英文文件使用相同的文件名

### 导入文章

运行导入脚本：

```bash
cd /home/tensor/projects/articles
./scripts/import_manual_articles.sh
```

或者：

```bash
cd /home/tensor/projects/ktizo
docker compose exec articles python scripts/import_from_subdirs.py
```

### 移动现有文件

如果已有文件在旧位置，可以使用移动脚本：

```bash
cd /home/tensor/projects/articles
python3 scripts/move_to_subdirs.py --source-dir data/html
```

这个脚本会：
- 将非 `zh_` 开头的文件移动到 `en/` 目录
- 将 `zh_` 开头的文件移动到 `zh/` 目录（并移除 `zh_` 前缀）

## 前端行为

- **默认语言**：中文（`zh`）
- **卡片标题**：根据全局语言设置显示中文或英文标题
- **文章内容**：根据选择的语言从对应目录加载

## 后端 API

API 会根据 `lang` 参数从正确的子目录读取文件：
- `lang=en` → 从 `/en` 目录读取
- `lang=zh` → 从 `/zh` 目录读取

## 定时任务

定时任务会自动将文件保存到正确的目录：
- 英文文件 → `data/html/en/`
- 中文翻译 → `data/html/zh/`（相同文件名）


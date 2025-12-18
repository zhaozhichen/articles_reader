# 手动导入文章指南

## 文章存储位置

文章 HTML 文件应存储在以下目录：

**宿主机路径**：
```
/home/tensor/projects/articles/data/html/
```

**容器内路径**：
```
/app/data/html/
```

## 文件命名格式

### 英文文章
```
YYYY-MM-DD_category_author_title.html
```

### 中文翻译
```
zh_YYYY-MM-DD_category_author_title.html
```

### 示例
- `2025-12-17_culture_Alexandra_Schwartz_Rob_Reiner_Made_a_New_Kind_of_Fairy_Tale.html`
- `zh_2025-12-17_culture_Alexandra_Schwartz_Rob_Reiner_Made_a_New_Kind_of_Fairy_Tale.html`

### 文件名组成部分

1. **日期**：`YYYY-MM-DD` 格式（必需）
2. **类别**：如 `culture`, `books`, `news`, `cartoons` 等（必需）
3. **作者**：作者姓名，下划线会被替换为空格（必需）
4. **标题**：文章标题，下划线会被替换为空格（必需）

**注意**：如果文件名格式不正确，脚本会跳过该文件。

## 子目录支持

文章可以放在子目录中，脚本会递归搜索所有 HTML 文件。例如：
```
html/
  articles/
    2025-12-17_culture_author_title.html
    zh_2025-12-17_culture_author_title.html
```

## 元数据提取

脚本会从以下来源提取元数据：

1. **文件名**：日期、类别、作者、标题
2. **HTML 内容**：
   - URL：从 `<meta property="og:url">` 或 `<link rel="canonical">` 提取
   - 标题：从 `<meta property="og:title">` 或 `<title>` 标签提取（优先使用 HTML 中的标题）
   - 作者：从 `<meta property="article:author">` 提取（优先使用 HTML 中的作者）

## 导入方法

### 方法 1：使用便捷脚本（推荐）

```bash
cd /home/tensor/projects/articles
./scripts/import_manual_articles.sh
```

### 方法 2：在容器内运行

```bash
cd /home/tensor/projects/ktizo
docker compose exec articles python scripts/import_from_html.py --directory /app/data/html
```

### 方法 3：直接运行 Python 代码

如果脚本文件不在容器内，可以使用内联 Python 代码（见脚本内容）。

## 导入逻辑

1. **扫描文件**：递归扫描指定目录下的所有 `.html` 文件
2. **解析文件名**：从文件名提取日期、类别、作者、标题
3. **提取 HTML 元数据**：从 HTML 内容提取 URL、标题、作者
4. **匹配中英文**：自动匹配 `zh_` 开头的文件与对应的英文文件
5. **去重检查**：通过 URL 或文件路径检查是否已存在
6. **导入/更新**：新文章导入，已存在的文章更新

## 注意事项

1. **文件格式**：确保文件名遵循命名格式，否则会被跳过
2. **中文翻译**：`zh_` 开头的文件会被识别为中文翻译，需要匹配对应的英文文件
3. **元数据优先级**：HTML 内容中的元数据优先于文件名中的元数据
4. **去重**：如果文章已存在（通过 URL 或文件路径），会更新而不是创建新记录
5. **相对路径**：文件路径会保存为相对于 `html/` 目录的相对路径

## 验证导入

导入后，可以通过以下方式验证：

```bash
# 检查数据库中的文章数量
cd /home/tensor/projects/ktizo
docker compose exec articles python -c "
from app.database import SessionLocal
from app.models import Article
db = SessionLocal()
count = db.query(Article).count()
print(f'Total articles: {count}')
db.close()
"

# 访问网页查看
# http://articles.ktizo.io
```

## 常见问题

### Q: 文件导入后没有显示在网页上？

A: 检查以下几点：
1. 文件名格式是否正确
2. 文件是否在正确的目录（`data/html/`）
3. 导入脚本是否成功运行
4. 查看容器日志：`docker compose logs articles`

### Q: 中文翻译没有关联？

A: 确保中文文件名以 `zh_` 开头，且日期、类别、作者与英文文件匹配。

### Q: 如何更新已导入的文章？

A: 重新运行导入脚本，脚本会自动检测并更新已存在的文章。


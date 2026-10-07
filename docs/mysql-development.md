# 本地 MySQL 开发

默认仍使用 SQLite。以下配置启用独立 MySQL 8.4，数据存在 Docker 卷中；切换连接不会搬运 SQLite 中已有会话。

## 安装驱动

项目通过 Django MySQL backend 和 `mysqlclient` 驱动连接数据库。
macOS 编译驱动需要客户端开发库和编译工具。已有 Homebrew MySQL 时可使用：

```bash
MYSQLCLIENT_CFLAGS="$(mysql_config --cflags)" \
MYSQLCLIENT_LDFLAGS="$(mysql_config --libs) -L/opt/homebrew/opt/openssl@3/lib -L/opt/homebrew/opt/zstd/lib" \
uv sync --locked --extra mysql
```

上面路径适用于 Apple Silicon Homebrew。其他环境参照 [mysqlclient 安装说明](https://github.com/PyMySQL/mysqlclient#installation) 安装依赖后运行 `uv sync --locked --extra mysql`。

## 启动数据库与迁移

在仓库根目录复制配置（已有 `.env.mysql` 时保留它）：

```bash
cp .env.mysql.example .env.mysql
```

将两个密码占位符替换成不同的随机密码。`.env.mysql` 被 Git 忽略。
启动 Docker Desktop 后执行：

```bash
docker compose --env-file .env.mysql -f compose.mysql.yml up -d --wait
uv run --locked --extra mysql python src/main/python/manage.py migrate --settings=config.settings_mysql
uv run --locked --extra mysql python src/main/python/manage.py runserver --settings=config.settings_mysql
```

数据库只绑定 `127.0.0.1:3307`。应用使用普通数据库用户；root 仅用于数据库管理。
容器环境变量只在首次初始化空数据卷时创建账号和数据库，修改文件不会自动修改已有账号密码。
若调整端口，请保持 Compose 与 Django 使用同一份 `.env.mysql`。进程环境变量优先于该文件。

CLI 用环境变量选择相同设置：

```bash
DJANGO_SETTINGS_MODULE=config.settings_mysql uv run --locked --extra mysql python src/main/python/cli.py --list
```

新 MySQL 空库通过 `0001_squashed_0010_path_hash` 创建最终表结构；原迁移文件保留，供已有 SQLite 库继续升级。
连接采用 `utf8mb4`、严格模式和 `READ COMMITTED`；容器默认排序规则是 `utf8mb4_0900_bin`，路径比较区分大小写。
相关设置见 [Django MySQL 说明](https://docs.djangoproject.com/en/5.2/ref/databases/#mysql-notes)。

## 验证

```bash
uv run --locked --extra mysql python src/main/python/manage.py showmigrations chat --settings=config.settings_mysql
uv run --locked --extra mysql python src/main/python/manage.py dbshell --settings=config.settings_mysql
```

`dbshell` 需要本机 `mysql` 命令。进入后运行：

```sql
SELECT VERSION(), DATABASE(), @@transaction_isolation;
SHOW CREATE TABLE chat_memoryspace\G
SHOW INDEX FROM chat_memoryspace;
```

应看到完整路径为 `longtext`，`path_hash` 为非空 `varchar(64)`，联合唯一索引为 `(owner_id, path_hash)`。

## 回归测试

Django 会创建并在测试结束后删除独立测试库。使用示例中的库名和用户名时，先授权一次：

```bash
docker compose --env-file .env.mysql -f compose.mysql.yml exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot' <<'SQL'
GRANT ALL PRIVILEGES ON `test\_mini\_agent\_mysql`.* TO 'mini_agent'@'%';
SQL

uv run --locked --extra mysql python src/main/python/manage.py test \
  tests.chat.test_application tests.chat.test_api tests.chat.test_cli \
  --settings=config.settings_mysql --noinput
```

如果改过库名或用户名，相应修改测试库授权语句。权限中的 `\_` 表示字面下划线，避免数据库名中的下划线被当成通配符。

停止服务并保留数据：

```bash
docker compose --env-file .env.mysql -f compose.mysql.yml stop
```

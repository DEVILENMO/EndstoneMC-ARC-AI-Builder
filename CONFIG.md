# ARC AI Builder 配置说明

## 配置文件位置
配置文件位于：`plugins/ARCAIBuilder/core_setting.yml`

## 配置项说明

### OpenAI API 配置
```yaml
# OpenAI API 密钥（必需）
openai_api_key=your_api_key_here

# OpenAI API 基础URL（可选，默认为官方API）
openai_api_url=https://api.openai.com/v1
```

### 经济系统价格配置
```yaml
# 地价：每格方块的价格
economy_land_per_block=5000

# 钻石：每颗钻石的价格
economy_diamond=15000

# 原木：每块原木的价格
economy_log=20

# 石头：每块石头的价格
economy_stone=10

# 土豆：每颗土豆的价格
economy_potato=30
```

### 建筑限制配置
```yaml
# 最大建筑范围（格数）
max_building_size=64

# 最小建筑范围（格数）
min_building_size=1
```

### AI 模型配置
```yaml
# 使用的AI模型
ai_model=gpt-3.5-turbo

# 最大生成令牌数
ai_max_tokens=2000

# 温度参数（0.0-1.0，越高越随机）
ai_temperature=0.7
```

### 建造配置
```yaml
# 命令执行间隔（秒）
build_delay=0.1

# 每次建造最大指令数
max_commands_per_build=1000
```

### 语言配置
```yaml
# 默认语言
default_language=CN
```

## 配置方法

### 方法1：通过命令配置（推荐）
管理员可以使用以下命令快速配置：
```
/aibuilderconfig <openai_api_key> [api_url]
```

### 方法2：手动编辑配置文件
1. 停止服务器
2. 编辑 `plugins/ARCAIBuilder/core_setting.yml` 文件
3. 重启服务器

## 配置示例

### 基础配置
```yaml
openai_api_key=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
openai_api_url=https://api.openai.com/v1
economy_land_per_block=5000
economy_diamond=15000
economy_log=20
economy_stone=10
economy_potato=30
max_building_size=64
min_building_size=1
ai_model=gpt-3.5-turbo
ai_max_tokens=2000
ai_temperature=0.7
build_delay=0.1
max_commands_per_build=1000
default_language=CN
```

### 自定义经济系统
如果你想要调整经济系统价格，可以修改以下配置：
```yaml
# 提高地价
economy_land_per_block=10000

# 降低材料价格
economy_log=10
economy_stone=5

# 提高钻石价格
economy_diamond=20000
```

### 性能优化配置
如果服务器性能较低，可以调整以下配置：
```yaml
# 增加命令执行间隔
build_delay=0.2

# 减少最大指令数
max_commands_per_build=500

# 使用更便宜的模型
ai_model=gpt-3.5-turbo
ai_max_tokens=1000
```

## 注意事项

1. **API密钥安全**：请妥善保管你的OpenAI API密钥，不要泄露给他人
2. **价格平衡**：调整经济系统价格时，请确保价格合理，避免破坏游戏平衡
3. **性能考虑**：建筑范围越大，生成的指令越多，执行时间越长
4. **模型选择**：GPT-4效果更好但成本更高，GPT-3.5-turbo性价比更高

## 故障排除

### 配置不生效
- 确保配置文件格式正确（键值对格式）
- 重启服务器使配置生效
- 检查配置文件权限

### API连接失败
- 检查网络连接
- 验证API密钥是否正确
- 确认API URL是否正确

### 经济系统问题
- 确保安装了arc_core或umoney插件
- 检查价格配置是否为数字
- 验证经济系统插件是否正常工作

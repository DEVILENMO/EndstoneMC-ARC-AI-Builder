import os
from pathlib import Path

MAIN_PATH = 'plugins/ARCAIBuilder'

class SettingManager:
    setting_dict = {}  # Class variable to store all settings

    def __init__(self):
        self.setting_file_path = Path(MAIN_PATH) / "default_settings.txt"
        self._load_setting_file()
        self._load_default_settings()
    
    def _load_default_settings(self):
        """加载默认设置"""
        # 默认配置
        default_settings = {
            "openai_api_key": "",
            "openai_api_url": "https://api.openai.com/v1",
            "economy_land_per_block": "5000",
            "economy_diamond": "15000", 
            "economy_log": "20",
            "economy_stone": "10",
            "economy_potato": "30",
            "max_building_size": "64",
            "min_building_size": "1",
            "ai_model": "gpt-3.5-turbo",
            "ai_max_tokens": "2000",
            "ai_temperature": "0.7",
            "build_delay": "0.1",
            "max_commands_per_build": "1000",
            "default_language": "CN"
        }
        
        # 将默认设置添加到设置字典中
        for key, value in default_settings.items():
            if key not in SettingManager.setting_dict:
                SettingManager.setting_dict[key] = value

    def _create_default_settings_file(self):
        """创建默认配置文件"""
        default_content = """# ARC AI Builder 默认配置文件
# 这个文件包含了所有可配置的设置项及其默认值

# OpenAI API 配置
openai_api_key=
openai_api_url=https://api.openai.com/v1

# 经济系统价格配置
economy_land_per_block=5000
economy_diamond=15000
economy_log=20
economy_stone=10
economy_potato=30

# 建筑限制配置
max_building_size=64
min_building_size=1

# AI 模型配置
ai_model=gpt-3.5-turbo
ai_max_tokens=2000
ai_temperature=0.7

# 建造配置
build_delay=0.1
max_commands_per_build=1000

# 语言配置
default_language=CN
"""
        with self.setting_file_path.open("w", encoding="utf-8") as f:
            f.write(default_content)

    def _load_setting_file(self):
        # Create config directory if not exists
        self.setting_file_path.parent.mkdir(exist_ok=True)

        # Create settings file if not exists
        if not self.setting_file_path.exists():
            self._create_default_settings_file()

        # Load settings file content
        print(f"[ARC AI Builder] Loading settings from: {self.setting_file_path}")
        with self.setting_file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    SettingManager.setting_dict[key.strip()] = value.strip()
                    print(f"[ARC AI Builder] Loaded setting: {key.strip()} = {value.strip()}")
        
        print(f"[ARC AI Builder] Total settings loaded from file: {len(SettingManager.setting_dict)}")

    def GetSetting(self, key):
        # If key doesn't exist in settings, add it
        if key not in SettingManager.setting_dict:
            with self.setting_file_path.open("a", encoding="utf-8") as f:
                f.write(f"\n{key}=")
            SettingManager.setting_dict[key] = ""

        value = None if not SettingManager.setting_dict[key] else SettingManager.setting_dict[key]
        print(f"[ARC AI Builder] GetSetting({key}) = {value}")
        return value

    def SetSetting(self, key, value):
        # Update setting in memory
        SettingManager.setting_dict[key] = str(value)

        # Rewrite entire file with updated settings
        with self.setting_file_path.open("w", encoding="utf-8") as f:
            for k, v in SettingManager.setting_dict.items():
                f.write(f"{k}={v}\n")
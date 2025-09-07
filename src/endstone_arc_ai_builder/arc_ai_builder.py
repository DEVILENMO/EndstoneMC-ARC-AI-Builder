import datetime
import os
import json
import threading
from typing import Dict, List, Optional, Tuple

from endstone.command import Command, CommandSender
from endstone.event import EventPriority, ServerLoadEvent, event_handler
from endstone.plugin import Plugin
from endstone.form import ActionForm, ModalForm, Label, TextInput

from .LanguageManager import LanguageManager
from .SettingManager import SettingManager
from .OpenAIManager import OpenAIManager
from .CommandExecutor import CommandExecutor


class ARCAIBuilderPlugin(Plugin):
    prefix = "ARCAIBuilderPlugin"
    api_version = "0.10"
    load = "POSTWORLD"

    commands = {
        "aibuilder": {
            "description": "AI建筑师主命令",
            "usages": ["/aibuilder"],
            "permissions": ["arc_ai_builder.command.aibuilder"],
        },
        "aibuilderconfig": {
            "description": "配置AI建筑师插件，OP专用",
            "usages": ["/aibuilderconfig [openai_key] [api_url]"]
        }
    }

    permissions = {
        "arc_ai_builder.command.aibuilder": {
            "description": "允许使用AI建筑师功能",
            "default": True
        },
        "arc_ai_builder.command.config": {
            "description": "允许配置AI建筑师插件",
            "default": False
        }
    }

    def _safe_log(self, level: str, message: str):
        """
        安全的日志记录方法，在logger未初始化时使用print
        :param level: 日志级别 (info, warning, error)
        :param message: 日志消息
        """
        if hasattr(self, 'logger') and self.logger is not None:
            if level.lower() == 'info':
                self.logger.info(message)
            elif level.lower() == 'warning':
                self.logger.warning(message)
            elif level.lower() == 'error':
                self.logger.error(message)
            else:
                self.logger.info(message)
        else:
            # 如果logger未初始化，使用print
            print(f"[{level.upper()}] {message}")

    def on_load(self) -> None:
        self._safe_log('info', "[ARC AI Builder] on_load is called!")
        
        # 初始化语言管理器
        self.language_manager = LanguageManager("CN")
        
        # 初始化设置管理器
        self.setting_manager = SettingManager()
        
        # 初始化内存数据存储
        self.building_records = {}  # 建筑记录 {building_id: record_dict}
        self.building_coordinates = {}  # 建筑坐标缓存 {building_id: (x, y, z)}
        self.next_building_id = 1  # 下一个建筑ID
        
        # 初始化OpenAI管理器（稍后配置）
        self.openai_manager = None
        
        # 初始化命令执行器
        self.command_executor = None
        
        # 玩家建筑请求缓存
        self.player_requests = {}  # 存储玩家的建筑请求 {player_name: request_data}
        # 请求位置跟踪 {request_id: (x, y, z, dimension)}
        self.request_positions = {}  # 存储请求发起时的位置
        self.next_request_id = 1  # 下一个请求ID

    def on_enable(self) -> None:
        self._safe_log('info', "[ARC AI Builder] on_enable is called!")
        self.register_events(self)
        
        # 初始化命令执行器
        self.command_executor = CommandExecutor(
            server=self.server,
            on_progress=self._on_build_progress,
            on_complete=self._on_build_complete,
            setting_manager=self.setting_manager,
            plugin_self=self
        )

        # 初始化经济系统
        self._init_economy_system()
        
        # 加载OpenAI配置
        self._load_openai_config()

        self.logger.info(f"[ARC AI Builder] Plugin enabled!")

    def on_disable(self) -> None:
        self._safe_log('info', "[ARC AI Builder] on_disable is called!")
        
        # 停止所有正在执行的建筑任务
        if self.command_executor:
            self.command_executor.stop_execution()
        
        # 清理内存数据（可选）
        self.building_records.clear()
        self.request_positions.clear()
    
    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        match command.name:
            case "aibuilder":
                if hasattr(sender, 'location') and hasattr(sender, 'send_form'):
                    self._show_ai_builder_panel(sender)
                else:
                    sender.send_message(self.language_manager.GetText("PLAYER_ONLY_COMMAND"))
            case "aibuild":
                if hasattr(sender, 'location') and hasattr(sender, 'send_form'):
                    self._show_rebuild_panel(sender)
                else:
                    sender.send_message(self.language_manager.GetText("PLAYER_ONLY_COMMAND"))
            case "aibuilderconfig":
                return self._handle_config_command(sender, args)
        return True
    
    def _show_rebuild_panel(self, player):
        """显示待确认建筑设计面板 - 让玩家重新调出AI规划好的弹窗"""
        try:
            # 从内存中查询玩家的待确认建筑记录（只查询pending状态的）
            records = []
            for building_id, record in self.building_records.items():
                if record['player_name'] == player.name and record['status'] == 'pending':
                    records.append(record)
            
            # 按创建时间倒序排列
            records.sort(key=lambda x: x['created_time'], reverse=True)
            records = records[:10]  # 限制最多10条
            
            if not records:
                player.send_message("❌ 没有找到待确认的建筑设计！")
                return
            
            # 创建选择面板
            panel = ActionForm(
                title="🏗️ 待确认建筑设计",
                content=f"找到 {len(records)} 条待确认的建筑设计：\n\n请选择要重新查看的建筑："
            )
            
            import json
            for i, record in enumerate(records):
                panel.add_button(
                    text=f"建筑 #{record['id']} - 待确认\n位置: ({int(record['center_x'])}, {int(record['center_y'])}, {int(record['center_z'])})\n需求: {record['requirements'][:20]}...",
                    on_click=lambda s, r=record: self._show_build_confirm_panel(s, 
                        json.loads(r['commands']) if isinstance(r['commands'], str) else r['commands'], 
                        r['estimated_cost'], r)
                )
            
            panel.add_button(
                text="❌ 取消",
                on_click=lambda s: s.send_message("已取消")
            )
            
            player.send_form(panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Show rebuild panel error: {str(e)}")
            player.send_message("❌ 调出建筑规划时出错！")
    
    def _confirm_building_with_record(self, player, commands, estimated_cost, record):
        """从记录确认建造（会删除原记录）"""
        try:
            # 检查余额
            player_money = self._get_player_money(player.name)
            if player_money < estimated_cost:
                player.send_message("余额不足，无法建造！")
                return
            
            # 扣费
            if not self._deduct_money(player.name, estimated_cost):
                player.send_message("扣费失败，无法建造！")
                return
            
            # 验证原始记录中的坐标信息
            if not record or 'center_x' not in record or 'center_y' not in record or 'center_z' not in record:
                # 扣费失败，退款
                self._add_money(player.name, estimated_cost)
                player.send_message("❌ 建筑记录坐标信息缺失，无法建造！已退款。")
                return
            
            # 使用原始记录中的坐标
            import math
            center_pos = (math.floor(record['center_x']), math.floor(record['center_y']), math.floor(record['center_z']))
            dimension = record.get('dimension', 'Overworld')
            size = record.get('size', 10)
            requirements = record.get('requirements', '重新确认的建筑')
            
            # 创建建筑记录
            request = {
                'center_pos': center_pos,
                'dimension': dimension,
                'size': size,
                'requirements': requirements,
                'commands': commands,
                'estimated_cost': estimated_cost
            }
            
            # 保存建筑记录
            building_id = self._save_building_record(player, request)
            if not building_id:
                # 扣费失败，退款
                self._add_money(player.name, estimated_cost)
                player.send_message("保存建筑记录失败，已退款。")
                return
            
            # 删除原记录（从内存中删除）
            if record['id'] in self.building_records:
                del self.building_records[record['id']]
                self._safe_log('info', f"[ARC AI Builder] Deleted original record {record['id']} from memory")
            
            # 开始执行建筑指令
            self._execute_building_commands(player, commands, building_id)
            
            # 显示开始建造消息
            player.send_message(f"✅ 建造已开始！预计成本：{estimated_cost:,} 元")
            player.send_message(f"📍 建筑位置：({center_pos[0]}, {center_pos[1]}, {center_pos[2]})")
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Confirm building with record error: {str(e)}")
            player.send_message("确认建造时出错，请重试。")
    
    def _execute_building_commands_direct(self, player, commands, building_id, center_pos):
        """直接执行建筑指令（使用传入的坐标）"""
        try:
            self._safe_log('info', f"[ARC AI Builder] Execute building commands direct - player: {player.name}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands direct - commands count: {len(commands) if commands else 0}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands direct - building_id: {building_id}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands direct - center_pos: {center_pos}")
            
            # 验证参数
            if commands is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands direct - commands is None")
                player.send_message("建筑指令为空，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            if not isinstance(commands, list):
                self._safe_log('error', f"[ARC AI Builder] Execute building commands direct - commands is not list: {type(commands)}")
                player.send_message("建筑指令格式错误，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            if building_id is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands direct - building_id is None")
                player.send_message("建筑记录ID错误，无法执行！")
                return
            
            if center_pos is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands direct - center_pos is None")
                player.send_message("建筑位置错误，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            # 使用命令执行器异步执行指令
            self.command_executor.execute_commands_async(commands, player.name, center_pos)
            
            # 更新建筑状态为建造中
            self._update_building_status(building_id, 'building')
            
            # 显示进度提示
            player.send_message("🏗️ 建筑指令已开始执行，请耐心等待...")
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Execute building commands direct error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Execute building commands direct traceback: {traceback.format_exc()}")
            player.send_message("执行建筑指令时出错，请重试。")

    # 内存数据管理方法
    
    def _init_economy_system(self) -> None:
        """初始化经济系统"""
        try:
            # 检查arc_core插件
            self.economy_plugin = self.server.plugin_manager.get_plugin('arc_core')
            if self.economy_plugin is not None:
                print("[ARC AI Builder] Using ARC Core economy system for money transactions.")
            else:
                # 检查umoney插件
                self.economy_plugin = self.server.plugin_manager.get_plugin('umoney')
                if self.economy_plugin is not None:
                    print("[ARC AI Builder] Using UMoney economy system for money transactions.")
                else:
                    print("[ARC AI Builder] No supported economy plugin found (arc_core or umoney). Money transactions will not be available.")
                    self.economy_plugin = None
        except Exception as e:
            print(f"[ARC AI Builder] Failed to load economy plugin: {e}. Money transactions will not be available.")
            self.economy_plugin = None
    
    # 配置相关方法
    def _handle_config_command(self, sender: CommandSender, args: list[str]) -> bool:
        """处理配置命令"""
        # 检查是否为OP
        if not sender.is_op:
            sender.send_message(self.language_manager.GetText("NO_PERMISSION"))
            return True
        
        if len(args) < 1:
            sender.send_message("用法: /aibuilderconfig <openai_key> [api_url]")
            return True
        
        openai_key = args[0]
        api_url = args[1] if len(args) > 1 else "https://api.openai.com/v1"
        
        # 保存配置到SettingManager
        self.setting_manager.SetSetting("openai_api_key", openai_key)
        self.setting_manager.SetSetting("openai_api_url", api_url)
        
        # 初始化OpenAI管理器
        self.openai_manager = OpenAIManager(openai_key, api_url, self.setting_manager)
        
        # 测试连接
        if self.openai_manager.test_connection():
            sender.send_message("✓ AI建筑师配置成功！OpenAI API连接正常。")
            self._safe_log('info', "[ARC AI Builder] OpenAI configuration successful")
        else:
            sender.send_message("✗ AI建筑师配置失败！请检查API密钥和网络连接。")
            self._safe_log('error', "[ARC AI Builder] OpenAI configuration failed")
        
        return True
    
    def _load_openai_config(self) -> None:
        """加载OpenAI配置"""
        api_key = self.setting_manager.GetSetting("openai_api_key")
        api_url = self.setting_manager.GetSetting("openai_api_url") or "https://api.openai.com/v1"
        
        if api_key:
            self.openai_manager = OpenAIManager(api_key, api_url, self.setting_manager)
            self._safe_log('info', "[ARC AI Builder] OpenAI configuration loaded from settings")
        else:
            self._safe_log('warning', "[ARC AI Builder] No OpenAI configuration found. Please use /aibuilderconfig to configure.")
    
    # 用户界面相关方法
    def _show_ai_builder_panel(self, player):
        """显示AI建筑师主面板"""
        try:
            # 检查OpenAI是否配置
            if not self.openai_manager:
                player.send_message("AI建筑师未配置！请联系管理员使用 /aibuilderconfig 配置OpenAI API。")
                return
            
            # 检查经济系统
            if not self.economy_plugin:
                player.send_message("经济系统未找到！无法进行建筑交易。")
                return
            
            # 获取玩家当前位置
            location = player.location
            import math
            center_pos = (math.floor(location.x), math.floor(location.y), math.floor(location.z))
            dimension = location.dimension.name
            
            # 创建主面板
            main_panel = ActionForm(
                title="🏗️ AI建筑师",
                content=f"当前位置: ({center_pos[0]}, {center_pos[1]}, {center_pos[2]})\n维度: {dimension}\n\n请选择操作："
            )
            
            # 添加开始建造按钮
            main_panel.add_button(
                "🏠 开始建造",
                on_click=lambda sender: self._show_build_input_panel(sender, center_pos, dimension)
            )
            
            # 添加待确认建筑设计按钮
            main_panel.add_button(
                "📋 待确认建筑设计",
                on_click=lambda sender: self._show_rebuild_panel(sender)
            )
            
            # 添加关闭按钮
            main_panel.add_button(
                "❌ 关闭",
                on_click=lambda sender: None
            )
            
            player.send_form(main_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Show main panel error: {str(e)}")
            player.send_message("显示面板时出错，请重试。")
    
    def _show_build_input_panel(self, player, center_pos, dimension):
        """显示建造输入面板"""
        try:
            # 获取范围限制，添加详细的调试信息
            min_size_setting = self.setting_manager.GetSetting("min_building_size")
            max_size_setting = self.setting_manager.GetSetting("max_building_size")
            
            self._safe_log('info', f"[ARC AI Builder] Build input panel - min_size_setting: {min_size_setting}, max_size_setting: {max_size_setting}")
            
            # 安全地转换设置值
            try:
                min_size = int(min_size_setting) if min_size_setting is not None else 1
                max_size = int(max_size_setting) if max_size_setting is not None else 64
            except (ValueError, TypeError) as e:
                self._safe_log('error', f"[ARC AI Builder] Build input panel - Error converting size settings: {str(e)}")
                min_size = 1
                max_size = 64
            
            self._safe_log('info', f"[ARC AI Builder] Build input panel - Final min_size: {min_size}, max_size: {max_size}")
            
            # 创建输入表单
            size_input = TextInput(
                label=f"建筑范围 ({min_size}-{max_size})",
                placeholder=f"输入建筑范围，如: 10",
                default_value="10"
            )
            
            requirements_input = TextInput(
                label="建筑需求描述",
                placeholder="描述你想要的建筑，如: 建造一个两层的小木屋，有窗户和门",
                default_value=""
            )
            
            # 添加调试信息
            self._safe_log('info', f"[ARC AI Builder] Build input panel - Created size_input: {size_input}")
            self._safe_log('info', f"[ARC AI Builder] Build input panel - Created requirements_input: {requirements_input}")
            
            def handle_build_submit(sender, *args, **kwargs):
                try:
                    # 添加详细的调试信息
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Sender: {sender}")
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Args: {args}")
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Kwargs: {kwargs}")
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Args count: {len(args)}")
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Kwargs keys: {list(kwargs.keys())}")
                    
                    # 处理不同的参数格式
                    form_data = None
                    if len(args) > 0:
                        form_data = args[0]
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Using first arg as form_data: {form_data}")
                    elif 'form_data' in kwargs:
                        form_data = kwargs['form_data']
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Using form_data from kwargs: {form_data}")
                    elif 'data' in kwargs:
                        form_data = kwargs['data']
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Using data from kwargs: {form_data}")
                    else:
                        self._safe_log('error', "[ARC AI Builder] Build submit - No form data found in args or kwargs")
                        self._safe_log('error', f"[ARC AI Builder] Build submit - Available kwargs: {list(kwargs.keys())}")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content="无法获取表单数据，请重试。",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Form data: {form_data}")
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Form data type: {type(form_data)}")
                    
                    # 处理不同的数据格式
                    if isinstance(form_data, str):
                        # 如果是JSON字符串，解析它
                        try:
                            data = json.loads(form_data)
                            self._safe_log('info', f"[ARC AI Builder] Build submit - Parsed JSON data: {data}")
                        except json.JSONDecodeError as je:
                            self._safe_log('error', f"[ARC AI Builder] Build submit - JSON decode error: {str(je)}")
                            error_form = ActionForm(
                                title="❌ 输入错误",
                                content="输入数据格式错误，请重试。",
                                on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                            )
                            sender.send_form(error_form)
                            return
                    elif isinstance(form_data, (list, tuple)):
                        # 如果直接是列表或元组
                        data = form_data
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Direct list data: {data}")
                    else:
                        # 其他格式，尝试转换
                        self._safe_log('error', f"[ARC AI Builder] Build submit - Unexpected data format: {type(form_data)}")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content="输入数据格式错误，请重试。",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    # 验证数据长度
                    if not isinstance(data, (list, tuple)) or len(data) < 3:
                        self._safe_log('error', f"[ARC AI Builder] Build submit - Invalid data format: {data}")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content="输入数据格式错误，请重试。",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    # 数据格式: [Label, size_input, requirements_input]
                    # 所以索引应该是: data[1] = size_str, data[2] = requirements
                    size_str = data[1]  # 范围输入 (第二个元素)
                    requirements = data[2]  # 需求输入 (第三个元素)
                    
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Corrected size_str: '{size_str}' (type: {type(size_str)})")
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Corrected requirements: '{requirements}' (type: {type(requirements)})")
                    
                    # 验证size_str不为None
                    if size_str is None:
                        self._safe_log('error', "[ARC AI Builder] Build submit - size_str is None")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content="建筑范围不能为空！",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    # 验证requirements不为None
                    if requirements is None:
                        self._safe_log('error', "[ARC AI Builder] Build submit - requirements is None")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content="建筑需求不能为空！",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    # 验证范围
                    try:
                        # 确保size_str是字符串
                        if not isinstance(size_str, str):
                            size_str = str(size_str)
                        
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Converting size_str to int: '{size_str}'")
                        size = int(size_str)
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Converted size: {size}")
                        
                        # 获取范围限制，添加None检查
                        min_size_setting = self.setting_manager.GetSetting("min_building_size")
                        max_size_setting = self.setting_manager.GetSetting("max_building_size")
                        
                        self._safe_log('info', f"[ARC AI Builder] Build submit - min_size_setting: {min_size_setting}, max_size_setting: {max_size_setting}")
                        
                        min_size = int(min_size_setting) if min_size_setting is not None else 1
                        max_size = int(max_size_setting) if max_size_setting is not None else 64
                        
                        self._safe_log('info', f"[ARC AI Builder] Build submit - Final min_size: {min_size}, max_size: {max_size}")
                        
                        if size < min_size or size > max_size:
                            raise ValueError(f"范围必须在{min_size}-{max_size}之间")
                            
                    except ValueError as ve:
                        self._safe_log('error', f"[ARC AI Builder] Build submit - ValueError in size validation: {str(ve)}")
                        min_size = int(self.setting_manager.GetSetting("min_building_size") or "1")
                        max_size = int(self.setting_manager.GetSetting("max_building_size") or "64")
                        result_form = ActionForm(
                            title="❌ 输入错误",
                            content=f"建筑范围必须是{min_size}-{max_size}之间的数字！",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(result_form)
                        return
                    except Exception as e:
                        self._safe_log('error', f"[ARC AI Builder] Build submit - Unexpected error in size validation: {str(e)}")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content=f"处理建筑范围时出错：{str(e)}",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    # 验证需求
                    if not isinstance(requirements, str):
                        self._safe_log('error', f"[ARC AI Builder] Build submit - requirements is not string: {type(requirements)}")
                        error_form = ActionForm(
                            title="❌ 输入错误",
                            content="建筑需求必须是文本！",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(error_form)
                        return
                    
                    if not requirements.strip():
                        self._safe_log('error', "[ARC AI Builder] Build submit - requirements is empty")
                        result_form = ActionForm(
                            title="❌ 输入错误", 
                            content="请描述你的建筑需求！",
                            on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                        )
                        sender.send_form(result_form)
                        return
                    
                    # 添加最终验证的调试信息
                    self._safe_log('info', f"[ARC AI Builder] Build submit - Final validation passed. size: {size}, requirements: '{requirements}'")
                    
                    # 开始生成建筑指令
                    self._start_building_generation(sender, center_pos, dimension, size, requirements)
                    
                except json.JSONDecodeError as je:
                    self._safe_log('error', f"[ARC AI Builder] Build submit - JSON decode error: {str(je)}")
                    error_form = ActionForm(
                        title="❌ 输入错误",
                        content="输入数据格式错误，请重试。",
                        on_close=lambda s: self._show_build_input_panel(s, center_pos, dimension)
                    )
                    sender.send_form(error_form)
                except Exception as e:
                    self._safe_log('error', f"[ARC AI Builder] Build input submit error: {str(e)}")
                    self._safe_log('error', f"[ARC AI Builder] Build input submit error type: {type(e)}")
                    import traceback
                    self._safe_log('error', f"[ARC AI Builder] Build input submit traceback: {traceback.format_exc()}")
                    error_form = ActionForm(
                        title="❌ 错误",
                        content=f"处理输入时出错：{str(e)}\n请重试。",
                        on_close=lambda s: self._show_ai_builder_panel(s)
                    )
                    sender.send_form(error_form)
            
            build_input_panel = ModalForm(
                title="🏗️ 开始建造",
                controls=[
                    Label(text=f"中心位置: ({center_pos[0]}, {center_pos[1]}, {center_pos[2]})"),
                    size_input,
                    requirements_input
                ],
                on_close=lambda sender: self._show_ai_builder_panel(sender),
                on_submit=handle_build_submit
            )
            
            player.send_form(build_input_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Show build input panel error: {str(e)}")
            player.send_message("显示输入面板时出错，请重试。")
    
    def _start_building_generation(self, player, center_pos, dimension, size, requirements):
        """开始生成建筑指令"""
        try:
            # 添加参数验证和调试信息
            self._safe_log('info', f"[ARC AI Builder] Start building generation - player: {player.name}")
            self._safe_log('info', f"[ARC AI Builder] Start building generation - center_pos: {center_pos}")
            self._safe_log('info', f"[ARC AI Builder] Start building generation - dimension: {dimension}")
            self._safe_log('info', f"[ARC AI Builder] Start building generation - size: {size} (type: {type(size)})")
            self._safe_log('info', f"[ARC AI Builder] Start building generation - requirements: '{requirements}' (type: {type(requirements)})")
            
            # 验证参数
            if size is None:
                self._safe_log('error', "[ARC AI Builder] Start building generation - size is None")
                error_form = ActionForm(
                    title="❌ 错误",
                    content="建筑范围参数错误！",
                    on_close=lambda sender: self._show_ai_builder_panel(sender)
                )
                player.send_form(error_form)
                return
            
            if requirements is None:
                self._safe_log('error', "[ARC AI Builder] Start building generation - requirements is None")
                error_form = ActionForm(
                    title="❌ 错误",
                    content="建筑需求参数错误！",
                    on_close=lambda sender: self._show_ai_builder_panel(sender)
                )
                player.send_form(error_form)
                return
            
            # 生成请求ID并记录位置
            request_id = self.next_request_id
            self.next_request_id += 1
            
            # 记录请求发起时的位置
            self.request_positions[request_id] = {
                'center_pos': center_pos,
                'dimension': dimension,
                'size': size,
                'requirements': requirements,
                'player_name': player.name
            }
            
            self._safe_log('info', f"[ARC AI Builder] Recorded request {request_id} with position: {center_pos}")
            
            # 发送生成中提示消息
            player.send_message("🤖 AI建筑师正在分析你的需求并生成建筑指令，请稍候...")
            
            # 在子线程中调用OpenAI API
            def generate_in_thread():
                try:
                    self._safe_log('info', f"[ARC AI Builder] Generate thread - Calling OpenAI with size: {size}, requirements: '{requirements}'")
                    
                    success, error_msg, commands, estimated_cost = self.openai_manager.generate_building_commands(
                        center_pos, size, requirements, player.name
                    )
                    
                    self._safe_log('info', f"[ARC AI Builder] Generate thread - OpenAI result: success={success}, error_msg={error_msg}, commands_count={len(commands) if commands else 0}, estimated_cost={estimated_cost}")
                    
                    # 使用服务器主线程来更新UI，避免线程安全问题
                    def update_ui():
                        try:
                            self._safe_log('info', f"[ARC AI Builder] Update UI - success: {success}")
                            if success:
                                # 缓存玩家请求
                                self.player_requests[player.name] = {
                                    'center_pos': center_pos,
                                    'dimension': dimension,
                                    'size': size,
                                    'requirements': requirements,
                                    'commands': commands,
                                    'estimated_cost': estimated_cost
                                }
                                
                                self._safe_log('info', f"[ARC AI Builder] Update UI - Showing confirm panel for {player.name}")
                                # 发送成功消息
                                player.send_message("✅ AI建筑师已完成建筑方案设计！")
                                # 显示确认面板，传递请求ID
                                self._show_build_confirm_panel(player, commands, estimated_cost, request_id=request_id)
                            else:
                                self._safe_log('info', f"[ARC AI Builder] Update UI - Showing error message for {player.name}")
                                # 发送错误消息
                                player.send_message(f"❌ AI生成建筑指令失败：{error_msg}")
                                player.send_message("请重新尝试或联系管理员。")
                        except Exception as ui_e:
                            self._safe_log('error', f"[ARC AI Builder] UI update error: {str(ui_e)}")
                            import traceback
                            self._safe_log('error', f"[ARC AI Builder] UI update traceback: {traceback.format_exc()}")
                            player.send_message("更新界面时出错，请重试。")
                    
                    # 在主线程中执行UI更新
                    self._safe_log('info', f"[ARC AI Builder] Scheduling UI update task")
                    self.server.scheduler.run_task(self, update_ui, delay=0)
                        
                except Exception as e:
                    self._safe_log('error', f"[ARC AI Builder] Generate building commands error: {str(e)}")
                    self._safe_log('error', f"[ARC AI Builder] Generate building commands error type: {type(e)}")
                    import traceback
                    self._safe_log('error', f"[ARC AI Builder] Generate building commands traceback: {traceback.format_exc()}")
                    
                    def show_error():
                        try:
                            self._safe_log('info', f"[ARC AI Builder] Show error - Showing error message for {player.name}")
                            player.send_message(f"❌ 生成建筑指令时发生错误：{str(e)}")
                            player.send_message("请重新尝试或联系管理员。")
                        except Exception as ui_e:
                            self._safe_log('error', f"[ARC AI Builder] Error UI update error: {str(ui_e)}")
                            import traceback
                            self._safe_log('error', f"[ARC AI Builder] Error UI update traceback: {traceback.format_exc()}")
                            player.send_message("显示错误信息时出错，请重试。")
                    
                    # 在主线程中执行错误UI更新
                    self._safe_log('info', f"[ARC AI Builder] Scheduling error UI update task")
                    self.server.scheduler.run_task(self, show_error, delay=0)
            
            # 启动生成线程
            thread = threading.Thread(target=generate_in_thread, daemon=True)
            thread.start()
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Start building generation error: {str(e)}")
            player.send_message("开始生成建筑指令时出错，请重试。")
    
    def _show_build_confirm_panel(self, player, commands, estimated_cost, record=None, request_id=None):
        """显示建筑确认面板"""
        try:
            # 获取玩家金钱
            player_money = self._get_player_money(player.name)
            
            # 构建确认内容
            content = f"🏗️ 建筑方案确认\n\n"
            content += f"💰 预估成本: {estimated_cost:,} 元\n"
            content += f"💳 你的余额: {player_money:,} 元\n"
            content += f"📋 指令数量: {len(commands)} 条\n\n"
            
            if player_money < estimated_cost:
                content += "❌ 余额不足！无法建造此建筑。"
            else:
                content += "✅ 余额充足，可以开始建造！\n\n"
                content += "📝 建筑指令预览（前5条）：\n"
                for i, cmd in enumerate(commands[:5]):
                    content += f"{i+1}. {cmd}\n"
                if len(commands) > 5:
                    content += f"... 还有 {len(commands)-5} 条指令"
            
            # 创建确认面板
            confirm_panel = ActionForm(
                title="🏗️ 确认建造",
                content=content
            )
            
            # 如果余额充足，添加确认按钮
            if player_money >= estimated_cost:
                if record:
                    # 从记录确认的情况
                    confirm_panel.add_button(
                        "✅ 确认建造",
                        on_click=lambda sender: self._confirm_building_with_record(sender, commands, estimated_cost, record)
                    )
                else:
                    # 正常确认的情况
                    confirm_panel.add_button(
                        "✅ 确认建造",
                        on_click=lambda sender: self._confirm_building(sender, commands, estimated_cost, request_id=request_id)
                    )
            
            # 添加取消按钮
            if record:
                confirm_panel.add_button(
                    "❌ 取消",
                    on_click=lambda sender: self._show_rebuild_panel(sender)
                )
            else:
                confirm_panel.add_button(
                    "❌ 取消",
                    on_click=lambda sender: self._show_ai_builder_panel(sender)
                )
            
            player.send_form(confirm_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Show build confirm panel error: {str(e)}")
            player.send_message("显示确认面板时出错，请重试。")
    
    def _confirm_building(self, player, commands=None, estimated_cost=None, building_record=None, request_id=None):
        """确认建造"""
        try:
            # 如果提供了参数，说明是从AI生成后确认建造
            if commands is not None and estimated_cost is not None:
                # 检查余额
                player_money = self._get_player_money(player.name)
                if player_money < estimated_cost:
                    player.send_message("余额不足，无法建造！")
                    return
                
                # 扣费
                if not self._deduct_money(player.name, estimated_cost):
                    player.send_message("扣费失败，无法建造！")
                    return
                
                # 获取建筑位置
                if request_id and request_id in self.request_positions:
                    # 使用请求时记录的位置
                    request_data = self.request_positions[request_id]
                    center_pos = request_data['center_pos']
                    dimension = request_data['dimension']
                    size = request_data['size']
                    requirements = request_data['requirements']
                    
                    self._safe_log('info', f"[ARC AI Builder] Using recorded position for request {request_id}: {center_pos}")
                    
                    # 生成建筑ID
                    building_id = self.next_building_id
                    self.next_building_id += 1
                    
                    # 保存建筑记录到内存
                    building_data = {
                        'id': building_id,
                        'player_name': player.name,
                        'player_uuid': self._get_player_uuid(player.name),
                        'center_x': center_pos[0],
                        'center_y': center_pos[1],
                        'center_z': center_pos[2],
                        'dimension': dimension,
                        'size': size,
                        'requirements': requirements,
                        'estimated_cost': estimated_cost,
                        'actual_cost': estimated_cost,
                        'commands': commands,
                        'status': 'building',
                        'created_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'completed_time': None
                    }
                    
                    self.building_records[building_id] = building_data
                    
                    # 开始执行建筑指令
                    self._execute_building_commands_direct(player, commands, building_id, center_pos)
                    
                    # 清理请求记录
                    del self.request_positions[request_id]
                    
                    # 显示开始建造消息
                    player.send_message(f"✅ 建造已开始！预计成本：{estimated_cost:,} 元")
                    player.send_message(f"📍 建筑位置：({center_pos[0]}, {center_pos[1]}, {center_pos[2]})")
                    return
                else:
                    player.send_message("❌ 建筑位置信息丢失，无法建造！")
                    return
            
            # 从缓存中获取请求的情况
            if player.name not in self.player_requests:
                player.send_message("建筑请求已过期，请重新开始。")
                return
            
            request = self.player_requests[player.name]
            estimated_cost = request['estimated_cost']
            
            # 检查余额
            player_money = self._get_player_money(player.name)
            if player_money < estimated_cost:
                player.send_message("余额不足，无法建造！")
                return
            
            # 扣费
            if not self._deduct_money(player.name, estimated_cost):
                player.send_message("扣费失败，无法建造！")
                return
            
            # 保存建筑记录
            building_id = self._save_building_record(player, request)
            if not building_id:
                # 扣费失败，退款
                self._add_money(player.name, estimated_cost)
                player.send_message("保存建筑记录失败，已退款。")
                return
            
            # 开始执行建筑指令
            self._execute_building_commands(player, request['commands'], building_id)
            
            # 清除缓存
            del self.player_requests[player.name]
            
            # 显示开始建造消息
            player.send_message(f"✅ 建造已开始！预计成本：{estimated_cost:,} 元")
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Confirm building error: {str(e)}")
            player.send_message("确认建造时出错，请重试。")
    
    # 经济系统相关方法
    def _get_player_money(self, player_name: str) -> int:
        """获取玩家金钱"""
        try:
            if not self.economy_plugin:
                self._safe_log('warning', f"[ARC AI Builder] Get player money - No economy plugin available for {player_name}")
                return 0
            
            # 使用经济系统API获取玩家金钱
            money = self.economy_plugin.api_get_player_money(player_name)
            self._safe_log('info', f"[ARC AI Builder] Get player money - {player_name}: {money} (type: {type(money)})")
            
            # 确保返回的是整数
            if money is None:
                self._safe_log('warning', f"[ARC AI Builder] Get player money - {player_name} returned None, using 0")
                return 0
            
            try:
                return int(money)
            except (ValueError, TypeError) as e:
                self._safe_log('error', f"[ARC AI Builder] Get player money - Cannot convert {money} to int: {str(e)}")
                return 0
                
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Get player money error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Get player money traceback: {traceback.format_exc()}")
            return 0
    
    def _deduct_money(self, player_name: str, amount: int) -> bool:
        """扣除玩家金钱"""
        try:
            if not self.economy_plugin:
                self._safe_log('warning', f"[ARC AI Builder] Deduct money - No economy plugin available for {player_name}")
                return False
            
            if amount is None or amount <= 0:
                self._safe_log('error', f"[ARC AI Builder] Deduct money - Invalid amount: {amount}")
                return False
            
            self._safe_log('info', f"[ARC AI Builder] Deduct money - {player_name}: {amount}")
            
            # 使用经济系统API扣除金钱
            self.economy_plugin.api_change_player_money(player_name, -amount)
            return True
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Deduct money error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Deduct money traceback: {traceback.format_exc()}")
            return False
    
    def _add_money(self, player_name: str, amount: int) -> bool:
        """增加玩家金钱"""
        try:
            if not self.economy_plugin:
                self._safe_log('warning', f"[ARC AI Builder] Add money - No economy plugin available for {player_name}")
                return False
            
            if amount is None or amount <= 0:
                self._safe_log('error', f"[ARC AI Builder] Add money - Invalid amount: {amount}")
                return False
            
            self._safe_log('info', f"[ARC AI Builder] Add money - {player_name}: {amount}")
            
            # 使用经济系统API增加金钱
            self.economy_plugin.api_change_player_money(player_name, amount)
            return True
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Add money error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Add money traceback: {traceback.format_exc()}")
            return False
    
    # 建筑记录相关方法
    def _save_building_record(self, player, request) -> Optional[int]:
        """保存建筑记录"""
        try:
            # 添加详细的调试信息
            self._safe_log('info', f"[ARC AI Builder] Save building record - player: {player.name}")
            self._safe_log('info', f"[ARC AI Builder] Save building record - request: {request}")
            
            # 验证request参数
            if not isinstance(request, dict):
                self._safe_log('error', f"[ARC AI Builder] Save building record - request is not dict: {type(request)}")
                return None
            
            required_keys = ['center_pos', 'dimension', 'size', 'requirements', 'estimated_cost', 'commands']
            for key in required_keys:
                if key not in request:
                    self._safe_log('error', f"[ARC AI Builder] Save building record - missing key: {key}")
                    return None
                if request[key] is None:
                    self._safe_log('error', f"[ARC AI Builder] Save building record - {key} is None")
                    return None
            
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 获取玩家UUID
            player_uuid = self._get_player_uuid(player.name)
            self._safe_log('info', f"[ARC AI Builder] Save building record - player_uuid: {player_uuid}")
            
            # 验证center_pos
            center_pos = request['center_pos']
            if not isinstance(center_pos, (list, tuple)) or len(center_pos) < 3:
                self._safe_log('error', f"[ARC AI Builder] Save building record - invalid center_pos: {center_pos}")
                return None
            
            # 验证数值类型
            try:
                center_x = float(center_pos[0])
                center_y = float(center_pos[1])
                center_z = float(center_pos[2])
                size = int(request['size'])
                estimated_cost = int(request['estimated_cost'])
            except (ValueError, TypeError) as e:
                self._safe_log('error', f"[ARC AI Builder] Save building record - type conversion error: {str(e)}")
                return None
            
            # 生成新的建筑ID
            building_id = self.next_building_id
            self.next_building_id += 1
            
            building_data = {
                'id': building_id,
                'player_name': player.name,
                'player_uuid': player_uuid,
                'center_x': center_x,
                'center_y': center_y,
                'center_z': center_z,
                'dimension': str(request['dimension']),
                'size': size,
                'requirements': str(request['requirements']),
                'estimated_cost': estimated_cost,
                'actual_cost': estimated_cost,  # 初始时等于预估成本
                'commands': request['commands'],  # 直接存储列表，不需要JSON序列化
                'status': 'building',
                'created_time': current_time,
                'completed_time': None
            }
            
            self._safe_log('info', f"[ARC AI Builder] Save building record - building_data: {building_data}")
            
            # 保存到内存
            self.building_records[building_id] = building_data
            self._safe_log('info', f"[ARC AI Builder] Save building record - Memory insert successful")
            
            # 缓存坐标信息到内存
            self.building_coordinates[building_id] = (center_x, center_y, center_z)
            self._safe_log('info', f"[ARC AI Builder] Cached coordinates for building {building_id}: ({center_x}, {center_y}, {center_z})")
            
            return building_id
                
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Save building record error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Save building record traceback: {traceback.format_exc()}")
            return None
    
    def _execute_building_commands_with_record(self, player, commands, building_id, building_record):
        """使用建筑记录执行建筑指令"""
        try:
            # 添加详细的调试信息
            self._safe_log('info', f"[ARC AI Builder] Execute building commands with record - player: {player.name}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands with record - commands count: {len(commands) if commands else 0}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands with record - building_id: {building_id}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands with record - building_record: {building_record}")
            
            # 验证参数
            if commands is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands with record - commands is None")
                player.send_message("建筑指令为空，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            if not isinstance(commands, list):
                self._safe_log('error', f"[ARC AI Builder] Execute building commands with record - commands is not list: {type(commands)}")
                player.send_message("建筑指令格式错误，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            if building_id is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands with record - building_id is None")
                player.send_message("建筑记录ID错误，无法执行！")
                return
            
            # 获取建筑位置（从传入的记录或内存中获取）
            center_pos = None
            
            if building_record and 'center_x' in building_record and 'center_y' in building_record and 'center_z' in building_record:
                # 从传入的建筑记录中获取位置信息
                import math
                center_pos = (math.floor(building_record['center_x']), math.floor(building_record['center_y']), math.floor(building_record['center_z']))
                self._safe_log('info', f"[ARC AI Builder] Execute building commands with record - using record position: {center_pos}")
            elif building_id in self.building_records:
                # 从内存中获取建筑记录
                building_record = self.building_records[building_id]
                if 'center_x' in building_record and 'center_y' in building_record and 'center_z' in building_record:
                    import math
                    center_pos = (math.floor(building_record['center_x']), math.floor(building_record['center_y']), math.floor(building_record['center_z']))
                    self._safe_log('info', f"[ARC AI Builder] Execute building commands with record - using memory position: {center_pos}")
                else:
                    self._safe_log('error', f"[ARC AI Builder] Execute building commands with record - building record missing coordinates")
                    player.send_message("❌ 建筑位置信息缺失，无法执行建筑指令！")
                    return
            else:
                self._safe_log('error', f"[ARC AI Builder] Execute building commands with record - no building position found")
                player.send_message("❌ 建筑位置信息缺失，无法执行建筑指令！")
                return
            
            # 使用命令执行器异步执行指令
            self.command_executor.execute_commands_async(commands, player.name, center_pos)
            
            # 更新建筑状态为建造中
            self._update_building_status(building_id, 'building')
            
            # 显示进度提示
            player.send_message("🏗️ 建筑指令已开始执行，请耐心等待...")
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Execute building commands with record error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Execute building commands with record traceback: {traceback.format_exc()}")
            player.send_message("执行建筑指令时出错，请重试。")

    def _execute_building_commands(self, player, commands, building_id):
        """执行建筑指令"""
        try:
            # 添加详细的调试信息
            self._safe_log('info', f"[ARC AI Builder] Execute building commands - player: {player.name}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands - commands count: {len(commands) if commands else 0}")
            self._safe_log('info', f"[ARC AI Builder] Execute building commands - building_id: {building_id}")
            
            # 验证参数
            if commands is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands - commands is None")
                player.send_message("建筑指令为空，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            if not isinstance(commands, list):
                self._safe_log('error', f"[ARC AI Builder] Execute building commands - commands is not list: {type(commands)}")
                player.send_message("建筑指令格式错误，无法执行！")
                self._update_building_status(building_id, 'failed')
                return
            
            if building_id is None:
                self._safe_log('error', "[ARC AI Builder] Execute building commands - building_id is None")
                player.send_message("建筑记录ID错误，无法执行！")
                return
            
            # 获取建筑位置（优先从内存缓存获取）
            center_pos = None
            
            # 从内存中获取建筑记录和坐标
            if building_id in self.building_records:
                building_record = self.building_records[building_id]
                if 'center_x' in building_record and 'center_y' in building_record and 'center_z' in building_record:
                    import math
                    center_pos = (math.floor(building_record['center_x']), math.floor(building_record['center_y']), math.floor(building_record['center_z']))
                    self._safe_log('info', f"[ARC AI Builder] Execute building commands - using memory position: {center_pos}")
                else:
                    self._safe_log('error', f"[ARC AI Builder] Execute building commands - building record missing coordinates")
                    player.send_message("❌ 建筑位置信息缺失，无法执行建筑指令！")
                    return
            else:
                self._safe_log('error', f"[ARC AI Builder] Execute building commands - building record not found in memory")
                player.send_message("❌ 建筑记录不存在，无法执行建筑指令！")
                return
            
            # 使用命令执行器异步执行指令
            self.command_executor.execute_commands_async(commands, player.name, center_pos)
            
            # 更新建筑状态为建造中
            self._update_building_status(building_id, 'building')
            
            # 显示进度提示
            player.send_message("🏗️ 建筑指令已开始执行，请耐心等待...")
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Execute building commands error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Execute building commands traceback: {traceback.format_exc()}")
            player.send_message("执行建筑指令时出错！")
            if building_id is not None:
                self._update_building_status(building_id, 'failed')
    
    def _update_building_status(self, building_id: int, status: str):
        """更新建筑状态"""
        try:
            # 添加详细的调试信息
            self._safe_log('info', f"[ARC AI Builder] Update building status - building_id: {building_id}, status: {status}")
            
            # 验证参数
            if building_id is None:
                self._safe_log('error', "[ARC AI Builder] Update building status - building_id is None")
                return
            
            if status is None:
                self._safe_log('error', "[ARC AI Builder] Update building status - status is None")
                return
            
            current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 更新内存中的建筑记录
            if building_id in self.building_records:
                self.building_records[building_id]['status'] = str(status)
                if status in ['completed', 'failed']:
                    self.building_records[building_id]['completed_time'] = current_time
                
                self._safe_log('info', f"[ARC AI Builder] Update building status - Memory update successful for building {building_id}")
                
                # 如果建筑完成或失败，清理坐标缓存和建筑记录
                if status in ['completed', 'failed']:
                    if building_id in self.building_coordinates:
                        del self.building_coordinates[building_id]
                        self._safe_log('info', f"[ARC AI Builder] Cleared coordinate cache for building {building_id}")
                    # 可以选择保留建筑记录用于历史查看，或者删除
                    # del self.building_records[building_id]
            else:
                self._safe_log('error', f"[ARC AI Builder] Update building status - Building record not found in memory: {building_id}")
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Update building status error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Update building status traceback: {traceback.format_exc()}")
    
    # 回调方法
    def _on_build_progress(self, player_name: str, current: int, total: int):
        """建筑进度回调"""
        try:
            # 添加详细的调试信息
            self._safe_log('info', f"[ARC AI Builder] Build progress - player_name: {player_name}, current: {current}, total: {total}")
            
            # 验证参数
            if current is None or total is None:
                self._safe_log('error', f"[ARC AI Builder] Build progress - current or total is None: current={current}, total={total}")
                return
            
            # 安全地计算进度百分比
            try:
                progress_percent = int((current / total) * 100) if total > 0 else 0
            except (ZeroDivisionError, TypeError) as e:
                self._safe_log('error', f"[ARC AI Builder] Build progress - Error calculating progress: {str(e)}")
                progress_percent = 0
            
            self._safe_log('info', f"[ARC AI Builder] Building progress for {player_name}: {current}/{total} ({progress_percent}%)")
            
            # 可以在这里添加进度通知给玩家
            online_player = self.server.get_player(player_name)
            if online_player:
                online_player.send_message(f"🏗️ 建筑进度: {current}/{total} ({progress_percent}%)")
                
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Build progress callback error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Build progress callback traceback: {traceback.format_exc()}")
    
    def _on_build_complete(self, player_name: str, completed: int, total: int):
        """建筑完成回调"""
        try:
            # 添加详细的调试信息
            self._safe_log('info', f"[ARC AI Builder] Build complete - player_name: {player_name}, completed: {completed}, total: {total}")
            
            # 验证参数
            if completed is None or total is None:
                self._safe_log('error', f"[ARC AI Builder] Build complete - completed or total is None: completed={completed}, total={total}")
                return
            
            self._safe_log('info', f"[ARC AI Builder] Building completed for {player_name}: {completed}/{total}")
            
            # 从内存中查找该玩家的建筑记录
            building_id = None
            for bid, record in self.building_records.items():
                if record['player_name'] == player_name and record['status'] == 'building':
                    building_id = bid
                    break
            
            if building_id:
                self._safe_log('info', f"[ARC AI Builder] Build complete - Found building record: {building_id}")
                self._update_building_status(building_id, 'completed')
            else:
                self._safe_log('warning', f"[ARC AI Builder] Build complete - No building record found for {player_name}")
            
            # 通知玩家
            online_player = self.server.get_player(player_name)
            if online_player:
                online_player.send_message("✅ 建筑建造完成！")
            else:
                self._safe_log('warning', f"[ARC AI Builder] Build complete - Player {player_name} is not online")
                
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Build complete callback error: {str(e)}")
            import traceback
            self._safe_log('error', f"[ARC AI Builder] Build complete callback traceback: {traceback.format_exc()}")
    
    # 历史记录相关方法
    # 辅助方法
    def _get_player_uuid(self, player_name: str) -> str:
        """获取玩家UUID"""
        try:
            # 如果玩家在线，直接获取UUID
            online_player = self.server.get_player(player_name)
            if online_player is not None:
                return str(online_player.unique_id)
            
            # 如果玩家不在线，返回玩家名作为临时UUID
            return f"offline_{player_name}"
            
        except Exception as e:
            self._safe_log('error', f"[ARC AI Builder] Get player UUID error: {str(e)}")
            return f"offline_{player_name}"

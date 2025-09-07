import threading
import time
from typing import List, Callable, Optional

class CommandExecutor:
    def __init__(self, server, on_progress: Optional[Callable] = None, on_complete: Optional[Callable] = None, setting_manager=None, plugin_self=None):
        """
        初始化命令执行器
        :param server: 服务器实例
        :param on_progress: 进度回调函数
        :param on_complete: 完成回调函数
        :param setting_manager: 设置管理器实例
        :param plugin_self: 插件实例
        """
        self.server = server
        self.on_progress = on_progress
        self.on_complete = on_complete
        self.setting_manager = setting_manager
        self.plugin_self = plugin_self
        self.is_running = False
        self.current_progress = 0
        self.total_commands = 0

    def execute_commands_async(self, commands: List[str], player_name: str, center_pos: tuple = None) -> None:
        """
        异步执行命令列表
        :param commands: 命令列表
        :param player_name: 玩家名称
        :param center_pos: 建筑中心位置 (x, y, z)，如果为None则使用玩家当前位置
        """
        if self.is_running:
            return
        
        # 启动新线程执行命令
        thread = threading.Thread(
            target=self._execute_commands_thread,
            args=(commands, player_name, center_pos),
            daemon=True
        )
        thread.start()

    def _execute_commands_thread(self, commands: List[str], player_name: str, center_pos: tuple = None) -> None:
        """
        在子线程中执行命令
        """
        try:
            self.is_running = True
            self.total_commands = len(commands)
            self.current_progress = 0
            
            print(f"[ARC AI Builder] 开始为玩家 {player_name} 执行 {len(commands)} 条建筑指令")
            
            # 必须提供建筑中心位置，不允许使用玩家当前位置
            if center_pos is None:
                print(f"[ARC AI Builder] 错误：没有提供建筑位置，无法执行建筑指令")
                return
            
            print(f"[ARC AI Builder] 使用指定的建筑位置: {center_pos}")
            
            for i, command in enumerate(commands):
                if not self.is_running:  # 检查是否被停止
                    break
                
                try:
                    # 先清理不支持的方块状态
                    cleaned_command = self._clean_block_states(command)
                    print(f"[ARC AI Builder] 清理后命令: {cleaned_command}")
                    
                    # 再转换相对坐标为绝对坐标
                    absolute_command = self._convert_relative_coords(cleaned_command, center_pos)
                    print(f"[ARC AI Builder] 执行命令: {absolute_command}")
                    
                    # 执行命令
                    self.server.dispatch_command(self.server.command_sender, absolute_command)
                    self.current_progress = i + 1
                    
                    # 调用进度回调（在主线程中执行）
                    if self.on_progress and self.plugin_self:
                        def progress_callback():
                            try:
                                self.on_progress(player_name, self.current_progress, self.total_commands)
                            except Exception as e:
                                print(f"[ARC AI Builder] 进度回调错误: {str(e)}")
                        
                        # 使用scheduler在主线程中执行回调
                        self.server.scheduler.run_task(self.plugin_self, progress_callback, delay=0)
                    
                    # 添加小延迟避免服务器卡顿
                    delay = float(self.setting_manager.GetSetting("build_delay") or "0.1") if self.setting_manager else 0.1
                    time.sleep(delay)
                    
                except Exception as e:
                    print(f"[ARC AI Builder] 执行命令失败: {command}, 错误: {str(e)}")
                    continue
            
            # 调用完成回调（在主线程中执行）
            if self.on_complete and self.plugin_self:
                def complete_callback():
                    try:
                        self.on_complete(player_name, self.current_progress, self.total_commands)
                    except Exception as e:
                        print(f"[ARC AI Builder] 完成回调错误: {str(e)}")
                
                # 使用scheduler在主线程中执行回调
                self.server.scheduler.run_task(self.plugin_self, complete_callback, delay=0)
            
            print(f"[ARC AI Builder] 玩家 {player_name} 的建筑指令执行完成")
            
        except Exception as e:
            print(f"[ARC AI Builder] 执行建筑指令时出错: {str(e)}")
        finally:
            self.is_running = False

    def stop_execution(self) -> None:
        """
        停止命令执行
        """
        self.is_running = False

    def get_progress(self) -> tuple:
        """
        获取当前进度
        :return: (当前进度, 总命令数)
        """
        return self.current_progress, self.total_commands

    def is_executing(self) -> bool:
        """
        检查是否正在执行命令
        """
        return self.is_running
    
    def _clean_block_states(self, command: str) -> str:
        """
        清理不支持的方块状态语法
        :param command: 原始命令
        :return: 清理后的命令
        """
        try:
            # 移除不支持的方块状态，如 [facing=east], [type=top] 等
            # Bedrock Edition 不支持这些语法
            import re
            
            # 匹配 [facing=xxx] 格式
            command = re.sub(r'\[facing=[^\]]+\]', '', command)
            # 匹配 [type=xxx] 格式  
            command = re.sub(r'\[type=[^\]]+\]', '', command)
            # 匹配 [waterlogged=true/false] 格式
            command = re.sub(r'\[waterlogged=[^\]]+\]', '', command)
            # 匹配其他可能的方块状态
            command = re.sub(r'\[[^\]]*\]', '', command)
            
            # 移除数据值（如 carpet 0, oak_fence 0, oak_door 0 等）
            # 匹配空格后跟数字的模式
            command = re.sub(r'\s+\d+$', '', command)  # 移除末尾的数字
            command = re.sub(r'\s+\d+\s+', ' ', command)  # 移除中间的数字
            
            # 清理多余的空格
            command = re.sub(r'\s+', ' ', command).strip()
            
            return command
            
        except Exception as e:
            print(f"[ARC AI Builder] 方块状态清理失败: {command}, 错误: {str(e)}")
            return command
    
    def _convert_relative_coords(self, command: str, center_pos: tuple) -> str:
        """
        将相对坐标转换为绝对坐标
        :param command: 包含相对坐标的命令
        :param center_pos: 中心位置 (x, y, z)
        :return: 转换后的命令
        """
        try:
            import re
            x, y, z = center_pos
            
            print(f"[ARC AI Builder] 原始命令: {command}")
            print(f"[ARC AI Builder] 中心位置: x={x}, y={y}, z={z}")
            
            # 按空格分割命令
            parts = command.split()
            coord_count = 0
            
            for i, part in enumerate(parts):
                if part.startswith("~"):
                    # 处理相对坐标
                    if part == "~":
                        # 简单的 ~ 坐标
                        if coord_count % 3 == 0:
                            parts[i] = str(x)
                        elif coord_count % 3 == 1:
                            parts[i] = str(y)
                        elif coord_count % 3 == 2:
                            parts[i] = str(z)
                        coord_count += 1
                    else:
                        # 带偏移的 ~-4 或 ~+4 格式
                        offset_str = part[1:]
                        if not offset_str:
                            offset = 0
                        else:
                            # 处理 ~+A 和 ~-A 格式
                            if offset_str.startswith('+'):
                                offset = int(offset_str[1:])
                            else:
                                offset = int(offset_str)
                        
                        if coord_count % 3 == 0:
                            parts[i] = str(x + offset)
                        elif coord_count % 3 == 1:
                            parts[i] = str(y + offset)
                        elif coord_count % 3 == 2:
                            parts[i] = str(z + offset)
                        coord_count += 1
                        
                        print(f"[ARC AI Builder] 坐标 {coord_count}: {part} -> {parts[i]}")
                elif part.isdigit() or (part.startswith('-') and part[1:].isdigit()):
                    # 处理绝对坐标，也要计数
                    coord_count += 1
            
            result = " ".join(parts)
            print(f"[ARC AI Builder] 转换后命令: {result}")
            return result
            
        except Exception as e:
            print(f"[ARC AI Builder] 坐标转换失败: {command}, 错误: {str(e)}")
            import traceback
            print(f"[ARC AI Builder] 坐标转换错误详情: {traceback.format_exc()}")
            return command
